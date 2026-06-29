# Copyright (c) 2026.
# SPDX-License-Identifier: BSD-3-Clause
"""Hierarchical G1 walk + attach-grasp pick-and-place demo (AUTHORING ONLY).

High-level controller (finite state machine):

    WALK_TO_SOURCE -> REACH_SOURCE -> GRASP -> LIFT
    -> WALK_TO_DEST -> REACH_DEST -> RELEASE -> DONE

Layers
------
* Locomotion (low level): the exported rsl_rl velocity policy from
  ``Isaac-Velocity-Flat-G1-v0`` produces joint-position targets for the WHOLE
  body every physics step. A simple heading/velocity planner turns the policy
  into a "walk to (x, y)" primitive.
* Manipulation (low level): during reach states the locomotion policy keeps the
  legs balancing at zero base-velocity command, while a differential-IK
  controller OVERRIDES the right-arm joint targets to drive the hand to the cube.
* Grasp: a simplified attach grasp (runtime FixedJoint hand<->cube).

This script is launched with the Isaac Sim python.sh launcher (see README.md).
It NEVER imports torch before the SimulationApp is created. Every long loop is
killable (finite max_steps + Ctrl-C friendly).

NOTE: this is authoring output. It has been checked against the Isaac Lab API by
reading source, NOT by running it on this machine (the harness kills GPU/Kit
processes). The user runs it in their own terminal with DISPLAY=:10.
"""

from __future__ import annotations

import argparse

from isaaclab.app import AppLauncher

# ---------------------------------------------------------------------------
# CLI + app launch (must happen before any torch / isaaclab.* import).
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Hierarchical G1 pick-and-place demo.")
parser.add_argument(
    "--policy",
    type=str,
    required=True,
    help="Path to the exported locomotion TorchScript policy (policy.pt). "
    "Produced by the rsl_rl play.py export step; see README.md.",
)
parser.add_argument("--mode", choices=["full", "manip_only"], default="full",
                    help="'full' walks between tables; 'manip_only' skips walking (robot starts at source).")
parser.add_argument("--max_steps", type=int, default=6000, help="Hard cap on physics steps (killable).")
parser.add_argument("--device", type=str, default="cuda:0")
# Table / cube layout in the ROBOT-LOCAL start frame (origin = robot start, +x forward).
parser.add_argument("--source_xy", type=float, nargs=2, default=[0.0, -1.2], help="Source table (x, y).")
parser.add_argument("--dest_xy", type=float, nargs=2, default=[0.0, 1.2], help="Dest table (x, y).")
parser.add_argument("--table_top_z", type=float, default=0.62)
parser.add_argument("--cube_size", type=float, default=0.16)
AppLauncher.add_app_launcher_args(parser)
args_cli = parser.parse_args()

app_launcher = AppLauncher(args_cli)
simulation_app = app_launcher.app

# ---------------------------------------------------------------------------
# Safe to import sim-dependent modules now.
# ---------------------------------------------------------------------------
import math
import torch

import isaaclab.sim as sim_utils
import isaaclab.utils.math as math_utils
from isaaclab.assets import Articulation, RigidObject
from isaaclab.sim import SimulationContext
from isaaclab.sim.utils.stage import get_current_stage

import g1_loco_manip_lib as lib

DEVICE = args_cli.device
SIM_DT = 1.0 / 200.0

# Approach standoff: where the pelvis stops relative to the table (metres).
APPROACH_STANDOFF = 0.55
REACH_TOL = 0.06          # metres, EE-to-cube distance that counts as "reached"
WALK_TOL = 0.20           # metres, pelvis-to-target distance that counts as "arrived"
MAX_WALK_SPEED = 0.8      # m/s commanded forward speed cap
MAX_YAW_RATE = 1.0        # rad/s commanded yaw cap


def design_scene():
    """Spawn ground, light, robot, two tables and a cube. Returns handles."""
    # Ground + light
    ground_cfg = sim_utils.GroundPlaneCfg()
    ground_cfg.func("/World/GroundPlane", ground_cfg)
    light_cfg = sim_utils.DomeLightCfg(intensity=3000.0, color=(0.75, 0.75, 0.75))
    light_cfg.func("/World/Light", light_cfg)

    robot = Articulation(lib.make_g1_cfg("/World/Robot"))

    src = args_cli.source_xy
    dst = args_cli.dest_xy
    top_z = args_cli.table_top_z

    source_table = RigidObject(lib.make_table_cfg("/World/SourceTable", (src[0], src[1], 0.0), top_z))
    dest_table = RigidObject(lib.make_table_cfg("/World/DestTable", (dst[0], dst[1], 0.0), top_z))

    cube_pos = (src[0], src[1], top_z + args_cli.cube_size / 2.0)
    cube = RigidObject(lib.make_cube_cfg("/World/Cube", cube_pos, args_cli.cube_size))

    return robot, source_table, dest_table, cube


def heading_velocity_command(robot: Articulation, target_xy: torch.Tensor) -> torch.Tensor:
    """Planner: produce [vx, vy, wz] in the robot base frame to walk toward target.

    The velocity policy expects commands in the base frame: vx forward, wz yaw.
    We steer by yaw toward the target and walk forward, slowing on arrival.
    """
    root_pos = robot.data.root_pos_w[:, :2]
    root_quat = robot.data.root_quat_w
    to_target = target_xy - root_pos
    dist = torch.norm(to_target, dim=-1, keepdim=True)

    # desired world heading
    desired_yaw = torch.atan2(to_target[:, 1], to_target[:, 0])
    # current yaw from quaternion
    _, _, yaw = math_utils.euler_xyz_from_quat(root_quat)
    yaw_err = math_utils.wrap_to_pi(desired_yaw - yaw)

    wz = torch.clamp(2.0 * yaw_err, -MAX_YAW_RATE, MAX_YAW_RATE).unsqueeze(-1)
    # only walk forward once roughly facing the target
    facing = (torch.abs(yaw_err) < 0.5).float().unsqueeze(-1)
    vx = torch.clamp(MAX_WALK_SPEED * dist, 0.0, MAX_WALK_SPEED) * facing
    vy = torch.zeros_like(vx)
    return torch.cat([vx, vy, wz], dim=-1)


def run():
    sim = SimulationContext(sim_utils.SimulationCfg(dt=1.0 / 200.0, device=DEVICE))
    sim.set_camera_view(eye=(3.0, -3.0, 2.0), target=(0.0, 0.0, 0.7))

    robot, source_table, dest_table, cube = design_scene()
    sim.reset()

    print("[INFO] joint_names:", robot.joint_names)
    print("[INFO] body_names :", robot.body_names)

    # Decimation: policy runs at 50 Hz (sim 200 Hz / 4), matching the velocity task.
    decimation = 4

    loco = lib.LocomotionPolicy(robot, args_cli.policy, DEVICE)
    arm = lib.ArmIK(robot, side="right", command_type="position", device=DEVICE)
    print(f"[INFO] arm EE body = {arm.ee_name}; arm joint ids = {arm.joint_ids}")

    stage = get_current_stage()
    grasp = lib.AttachGrasp(stage, "/World/Robot", arm.ee_name, "/World/Cube")

    src = torch.tensor([args_cli.source_xy], device=DEVICE)
    dst = torch.tensor([args_cli.dest_xy], device=DEVICE)
    top_z = args_cli.table_top_z

    # Approach points: stand APPROACH_STANDOFF metres "inside" the aisle from the table.
    src_approach = src.clone(); src_approach[:, 1] += APPROACH_STANDOFF * (1.0 if src[0, 1] < 0 else -1.0)
    dst_approach = dst.clone(); dst_approach[:, 1] += APPROACH_STANDOFF * (1.0 if dst[0, 1] < 0 else -1.0)

    state = "REACH_SOURCE" if args_cli.mode == "manip_only" else "WALK_TO_SOURCE"
    state_timer = 0
    sim_dt = SIM_DT
    step = 0

    while simulation_app.is_running() and step < args_cli.max_steps:
        cmd = torch.zeros((robot.num_instances, 3), device=DEVICE)
        do_arm = False

        if state == "WALK_TO_SOURCE":
            cmd = heading_velocity_command(robot, src_approach)
            if torch.norm(robot.data.root_pos_w[:, :2] - src_approach, dim=-1).item() < WALK_TOL:
                state, state_timer = "REACH_SOURCE", 0
        elif state == "WALK_TO_DEST":
            cmd = heading_velocity_command(robot, dst_approach)
            if torch.norm(robot.data.root_pos_w[:, :2] - dst_approach, dim=-1).item() < WALK_TOL:
                state, state_timer = "REACH_DEST", 0
        elif state in ("REACH_SOURCE", "REACH_DEST", "GRASP", "LIFT", "RELEASE"):
            # Stand still (zero velocity command) and drive the arm.
            do_arm = True

        # ---- low level: locomotion policy targets for the whole body ----
        targets = loco.compute_targets(cmd)

        if do_arm:
            # Pick the IK target in the robot root frame.
            cube_pos_w = cube.data.root_pos_w  # (1, 3)
            if state in ("REACH_SOURCE", "GRASP"):
                tgt_w = cube_pos_w.clone()
            elif state == "LIFT":
                tgt_w = cube_pos_w.clone(); tgt_w[:, 2] += 0.20
            elif state in ("REACH_DEST", "RELEASE"):
                tgt_w = torch.cat([dst[:, 0:1], dst[:, 1:2], torch.full_like(dst[:, 0:1], top_z + 0.12)], dim=-1)
            # transform world target -> base frame
            tgt_b, _ = math_utils.subtract_frame_transforms(
                robot.data.root_pos_w, robot.data.root_quat_w, tgt_w
            )
            arm.set_target_b(tgt_b)
            arm_targets = arm.compute_joint_targets()
            targets[:, arm.joint_ids] = arm_targets

            ee_to_cube = torch.norm(arm.ee_pos_w() - cube.data.root_pos_w, dim=-1).item()

            # ---- state transitions for the manipulation phase ----
            state_timer += 1
            if state == "REACH_SOURCE" and (ee_to_cube < REACH_TOL or state_timer > 400):
                grasp.grasp(); state, state_timer = "GRASP", 0
                print(f"[FSM] grasped cube (ee_to_cube={ee_to_cube:.3f})")
            elif state == "GRASP" and state_timer > 30:
                state, state_timer = "LIFT", 0
            elif state == "LIFT" and state_timer > 120:
                state, state_timer = ("RELEASE", 0) if args_cli.mode == "manip_only" else ("WALK_TO_DEST", 0)
            elif state == "REACH_DEST" and state_timer > 200:
                state, state_timer = "RELEASE", 0
            elif state == "RELEASE" and state_timer > 30:
                grasp.release(); state = "DONE"
                print("[FSM] released cube -> DONE")

        # ---- apply + step physics ----
        robot.set_joint_position_target(targets)
        robot.write_data_to_sim()
        for _ in range(decimation):
            sim.step()
            step += 1
        robot.update(sim_dt * decimation)
        source_table.update(sim_dt * decimation)
        dest_table.update(sim_dt * decimation)
        cube.update(sim_dt * decimation)

        if state == "DONE":
            print("[FSM] task complete.")
            break

    # Optional: leave the app open a moment for a screenshot, then close.
    for _ in range(60):
        if not simulation_app.is_running():
            break
        sim.step()
    simulation_app.close()


if __name__ == "__main__":
    run()
