"""VLM-controlled pick and place using Gemma 4 via llama-server.

Connects the LeIsaac-SO101-LiftCube-Direct-v0 environment to a Gemma 4 vision
model running on llama-server (OpenAI-compatible API). The model receives the
front camera image and current joint positions, then outputs target joint
positions to pick and place the red cube.

Usage:
    # 1. Start llama-server in another terminal:
    #    ./build/bin/llama-server -m models/gemma-4-E2B-it-GGUF/gemma-4-e2b-it-Q8_0.gguf \
    #        --mmproj models/gemma-4-E2B-it-GGUF/mmproj-gemma-4-e2b-it-f16.gguf
    #
    # 2. Run this script:
    #    python scripts/vlm_pick_and_place.py --task LeIsaac-SO101-LiftCube-Direct-v0
"""

import multiprocessing

if multiprocessing.get_start_method() != "spawn":
    multiprocessing.set_start_method("spawn", force=True)

import argparse

from isaaclab.app import AppLauncher

parser = argparse.ArgumentParser(description="VLM-controlled pick and place with Gemma 4")
parser.add_argument("--task", type=str, default="LeIsaac-SO101-LiftCube-Direct-v0")
parser.add_argument("--step_hz", type=int, default=30, help="Environment stepping rate in Hz.")
parser.add_argument("--vlm_url", type=str, default="http://localhost:8080/v1/chat/completions")
parser.add_argument("--max_steps", type=int, default=3000, help="Max env steps before reset.")
parser.add_argument("--vlm_query_interval", type=int, default=30, help="Query VLM every N steps.")
parser.add_argument("--action_repeat", type=int, default=30, help="Repeat each VLM action for N steps.")

AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

app_launcher = AppLauncher(vars(args_cli))
simulation_app = app_launcher.app

import base64
import io
import json
import math
import re
import time

import gymnasium as gym
import numpy as np
import requests
import torch
from isaaclab_tasks.utils import parse_env_cfg
from PIL import Image

import leisaac  # noqa: F401

# Joint names and their limits in radians
JOINT_NAMES = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper"]
JOINT_LIMITS_DEG = {
    "shoulder_pan": (-110.0, 110.0),
    "shoulder_lift": (-100.0, 100.0),
    "elbow_flex": (-100.0, 90.0),
    "wrist_flex": (-95.0, 95.0),
    "wrist_roll": (-160.0, 160.0),
    "gripper": (-10.0, 100.0),
}


class RateLimiter:
    def __init__(self, hz):
        self.hz = hz
        self.last_time = time.time()
        self.sleep_duration = 1.0 / hz
        self.render_period = min(0.0166, self.sleep_duration)

    def sleep(self, env):
        next_wakeup_time = self.last_time + self.sleep_duration
        while time.time() < next_wakeup_time:
            time.sleep(self.render_period)
            env.sim.render()
        self.last_time = self.last_time + self.sleep_duration
        if self.last_time < time.time():
            while self.last_time < time.time():
                self.last_time += self.sleep_duration


def tensor_to_base64_image(image_tensor: torch.Tensor) -> str:
    """Convert a (H, W, 3) uint8 tensor to a base64-encoded JPEG string."""
    img_np = image_tensor.cpu().numpy().astype(np.uint8)
    img = Image.fromarray(img_np)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


def joint_pos_to_degrees(joint_pos: torch.Tensor) -> list[float]:
    """Convert joint positions from radians to degrees."""
    return [round(math.degrees(j), 1) for j in joint_pos.cpu().tolist()]


def degrees_to_radians(degrees: list[float]) -> list[float]:
    """Convert degrees to radians."""
    return [math.radians(d) for d in degrees]


def clamp_joints(joint_degrees: list[float]) -> list[float]:
    """Clamp joint values to their limits."""
    clamped = []
    for name, val in zip(JOINT_NAMES, joint_degrees):
        lo, hi = JOINT_LIMITS_DEG[name]
        clamped.append(max(lo, min(hi, val)))
    return clamped


def query_vlm(vlm_url: str, image_b64: str, joint_pos_deg: list[float],
              ee_state: list[float], phase: str, history: list[dict]) -> list[float]:
    """Query the Gemma 4 VLM for the next joint target positions."""

    joint_str = ", ".join(f"{n}={v:.1f}°" for n, v in zip(JOINT_NAMES, joint_pos_deg))
    ee_pos_str = f"x={ee_state[0]:.3f}, y={ee_state[1]:.3f}, z={ee_state[2]:.3f}"

    system_prompt = f"""You are controlling a SO-101 6-DOF robot arm to pick up a red cube and lift it.

Robot joints (current positions in degrees):
{joint_str}

End-effector position (in robot base frame): {ee_pos_str}

Joint names and limits (degrees):
- shoulder_pan: -110 to 110 (rotates arm left/right)
- shoulder_lift: -100 to 100 (lifts/lowers upper arm, negative=up)
- elbow_flex: -100 to 90 (bends elbow)
- wrist_flex: -95 to 95 (flexes wrist)
- wrist_roll: -160 to 160 (rotates wrist/gripper)
- gripper: -10 to 100 (lower=closed/gripping, higher=open)

Current phase: {phase}

TASK: Pick up the red cube and lift it 20cm above the table.

Strategy:
1. OPEN: Open the gripper wide (gripper=90)
2. APPROACH: Move arm above the cube, looking at the image to locate it
3. LOWER: Lower the arm to bring gripper around the cube
4. GRASP: Close gripper (gripper=-5) to grab the cube
5. LIFT: Raise the arm to lift the cube up

IMPORTANT: You must respond with ONLY a JSON object, no other text:
{{"joints": [shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll, gripper], "phase": "OPEN|APPROACH|LOWER|GRASP|LIFT", "reasoning": "brief explanation"}}"""

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-4:])  # keep last 4 exchanges for context

    user_content = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
        },
        {
            "type": "text",
            "text": f"Current joint positions (degrees): [{', '.join(f'{v:.1f}' for v in joint_pos_deg)}]\nCurrent phase: {phase}\nWhat should the next joint targets be? Respond with JSON only."
        }
    ]
    messages.append({"role": "user", "content": user_content})

    try:
        resp = requests.post(
            vlm_url,
            json={
                "model": "gemma-4",
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": 300,
            },
            timeout=30,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        print(f"  VLM response: {content[:200]}")

        # Parse JSON from response (handle markdown code blocks)
        json_match = re.search(r'\{[^{}]*"joints"\s*:\s*\[[^\]]+\][^{}]*\}', content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            joints = data["joints"]
            new_phase = data.get("phase", phase)
            print(f"  Parsed joints: {joints}, phase: {new_phase}")
            return clamp_joints(joints), new_phase, content
        else:
            print(f"  Failed to parse JSON from VLM response")
            return None, phase, content

    except Exception as e:
        print(f"  VLM query failed: {e}")
        return None, phase, str(e)


def interpolate_joints(current: torch.Tensor, target: torch.Tensor, steps: int) -> list[torch.Tensor]:
    """Generate smooth interpolation from current to target joint positions."""
    waypoints = []
    for i in range(1, steps + 1):
        alpha = i / steps
        # Smooth ease-in-out
        alpha = 0.5 * (1.0 - math.cos(math.pi * alpha))
        wp = current + alpha * (target - current)
        waypoints.append(wp)
    return waypoints


def main():
    env_cfg = parse_env_cfg(args_cli.task, device=args_cli.device, num_envs=1)
    env_cfg.episode_length_s = 120.0  # give VLM plenty of time
    env_cfg.never_time_out = True
    env_cfg.manual_terminate = True
    env_cfg.return_success_status = False
    env_cfg.recorders = None

    env = gym.make(args_cli.task, cfg=env_cfg).unwrapped

    rate_limiter = RateLimiter(args_cli.step_hz)

    print("=" * 60)
    print("VLM Pick and Place Controller")
    print(f"  VLM endpoint: {args_cli.vlm_url}")
    print(f"  Task: {args_cli.task}")
    print(f"  Query interval: every {args_cli.vlm_query_interval} steps")
    print("=" * 60)

    obs_dict, _ = env.reset()
    phase = "OPEN"
    history = []
    step_count = 0
    current_action = None
    action_waypoints = []
    waypoint_idx = 0

    while simulation_app.is_running():
        with torch.inference_mode():
            policy_obs = obs_dict["policy"]
            joint_pos = policy_obs["joint_pos"][0]  # (6,)
            ee_state = policy_obs["ee_frame_state"][0]  # (7,)

            # Query VLM at intervals or when waypoints exhausted
            should_query = (step_count % args_cli.vlm_query_interval == 0) or (
                action_waypoints and waypoint_idx >= len(action_waypoints)
            )

            if should_query and "front" in policy_obs:
                joint_deg = joint_pos_to_degrees(joint_pos)
                ee_list = ee_state.cpu().tolist()
                image_b64 = tensor_to_base64_image(policy_obs["front"][0])

                print(f"\n[Step {step_count}] Phase={phase} | Joints(deg)={[round(j,1) for j in joint_deg]}")
                print(f"  EE pos: x={ee_list[0]:.3f} y={ee_list[1]:.3f} z={ee_list[2]:.3f}")

                target_deg, new_phase, response_text = query_vlm(
                    args_cli.vlm_url, image_b64, joint_deg, ee_list, phase, history
                )

                if target_deg is not None:
                    phase = new_phase
                    target_rad = degrees_to_radians(target_deg)
                    target_tensor = torch.tensor(target_rad, dtype=torch.float32, device=env.device)

                    # Smooth interpolation
                    action_waypoints = interpolate_joints(
                        joint_pos, target_tensor, args_cli.action_repeat
                    )
                    waypoint_idx = 0

                    # Track conversation history
                    history.append({
                        "role": "assistant",
                        "content": response_text
                    })
                else:
                    print("  Using previous action (VLM parse failed)")

            # Apply action
            if action_waypoints and waypoint_idx < len(action_waypoints):
                action = action_waypoints[waypoint_idx].unsqueeze(0)
                waypoint_idx += 1
            elif current_action is not None:
                action = current_action
            else:
                # Hold current position
                action = joint_pos.unsqueeze(0)

            current_action = action
            obs_dict, _, terminated, timed_out, _ = env.step(action)

            if terminated[0]:
                print("\n*** SUCCESS! Cube lifted! ***")
                obs_dict, _ = env.reset()
                phase = "OPEN"
                history = []
                step_count = 0
                action_waypoints = []
                continue

            step_count += 1
            if step_count >= args_cli.max_steps:
                print(f"\n--- Max steps ({args_cli.max_steps}) reached, resetting ---")
                obs_dict, _ = env.reset()
                phase = "OPEN"
                history = []
                step_count = 0
                action_waypoints = []
                continue

            rate_limiter.sleep(env)

    env.close()
    simulation_app.close()


if __name__ == "__main__":
    main()
