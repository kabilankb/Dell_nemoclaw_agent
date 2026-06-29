"""OpenClaw ↔ LeIsaac bridge script.

This script runs the OpenClaw NL command parser and sends commands
to the OpenClawDevice running inside a LeIsaac simulation.

Usage:
    # Terminal 1: Start LeIsaac with OpenClaw device
    python scripts/environments/teleoperation/teleop_se3_agent.py \
        --task=LeIsaac-SO101-PickOrange-v0 \
        --teleop_device=openclaw \
        --num_envs=1 \
        --device=cuda \
        --enable_cameras

    # Terminal 2: Start this bridge (interactive CLI or connect OpenClaw)
    python scripts/environments/teleoperation/openclaw_bridge.py \
        --host=localhost --port=5557

    # Then type natural language commands:
    > forward 1m
    > turn left 45
    > gripper open
    > pick
"""

import argparse
import json
import sys
import time

try:
    import zmq
except ImportError:
    print("pyzmq required: pip install pyzmq")
    sys.exit(1)

# ── NL command parser (standalone, no OpenClaw dependency needed) ──

import re

COMMAND_PATTERNS = [
    (r"(forward|前进|向前)\s*(\d+(?:\.\d+)?)?\s*m?", "forward", "distance", 1.0),
    (r"(backward|后退|向后)\s*(\d+(?:\.\d+)?)?\s*m?", "backward", "distance", 1.0),
    (r"(left)\s*(\d+(?:\.\d+)?)?\s*m?", "left", "distance", 0.5),
    (r"(right)\s*(\d+(?:\.\d+)?)?\s*m?", "right", "distance", 0.5),
    (r"(up|升)\s*(\d+(?:\.\d+)?)?\s*m?", "up", "distance", 0.3),
    (r"(down|降)\s*(\d+(?:\.\d+)?)?\s*m?", "down", "distance", 0.3),
    (r"(turn.?left|左转)\s*(\d+)?\s*度?", "turn_left", "angle", 45),
    (r"(turn.?right|右转)\s*(\d+)?\s*度?", "turn_right", "angle", 45),
    (r"(gripper.?open|open.?gripper|张开)", "gripper_open", None, None),
    (r"(gripper.?close|close.?gripper|夹紧)", "gripper_close", None, None),
    (r"(stop|停止)", "stop", None, None),
    (r"(pick|拾取)", "pick", None, None),
    (r"(place|放置)", "place", None, None),
]


def parse_command(text: str) -> dict:
    text = text.strip().lower()
    for pattern, action, param_name, default in COMMAND_PATTERNS:
        match = re.search(pattern, text)
        if match:
            params = {}
            if param_name and match.lastindex and match.lastindex >= 2:
                try:
                    params[param_name] = float(match.group(2))
                except (ValueError, TypeError):
                    params[param_name] = default
            elif param_name:
                params[param_name] = default
            return {"action": action, "params": params}
    return None


# ── Compound actions (pick = down + close + up) ──

COMPOUND_ACTIONS = {
    "pick": [
        {"action": "down", "params": {"distance": 0.15}},
        {"action": "gripper_close", "params": {}},
        {"action": "up", "params": {"distance": 0.15}},
    ],
    "place": [
        {"action": "down", "params": {"distance": 0.15}},
        {"action": "gripper_open", "params": {}},
        {"action": "up", "params": {"distance": 0.15}},
    ],
}


def main():
    parser = argparse.ArgumentParser(description="OpenClaw ↔ LeIsaac bridge")
    parser.add_argument("--host", type=str, default="localhost")
    parser.add_argument("--port", type=int, default=5557)
    args = parser.parse_args()

    ctx = zmq.Context()

    pub = ctx.socket(zmq.PUB)
    pub.connect(f"tcp://{args.host}:{args.port}")

    status_sub = ctx.socket(zmq.SUB)
    status_sub.setsockopt(zmq.SUBSCRIBE, b"")
    status_sub.setsockopt(zmq.CONFLATE, 1)
    status_sub.setsockopt(zmq.RCVTIMEO, 500)
    status_sub.connect(f"tcp://{args.host}:{args.port + 1}")

    time.sleep(0.5)

    print(f"Connected to LeIsaac at {args.host}:{args.port}")
    print("Type natural language commands (or 'quit' to exit):")
    print("  Examples: forward 1m, turn left 45, gripper open, pick, stop")
    print()

    try:
        while True:
            try:
                text = input("> ").strip()
            except EOFError:
                break

            if text.lower() in ("quit", "exit", "q"):
                break
            if not text:
                continue

            cmd = parse_command(text)
            if cmd is None:
                print(f"  Unknown command: {text}")
                continue

            if cmd["action"] in COMPOUND_ACTIONS:
                print(f"  Executing compound action: {cmd['action']}")
                for step in COMPOUND_ACTIONS[cmd["action"]]:
                    msg = json.dumps(step).encode("utf-8")
                    pub.send(msg)
                    print(f"    -> {step['action']}")
                    time.sleep(2.0)
                    try:
                        status = json.loads(status_sub.recv().decode("utf-8"))
                        print(f"    <- {status['message']}")
                    except zmq.Again:
                        pass
            else:
                msg = json.dumps(cmd).encode("utf-8")
                pub.send(msg)
                print(f"  Sent: {cmd['action']} {cmd.get('params', {})}")
                try:
                    status = json.loads(status_sub.recv().decode("utf-8"))
                    print(f"  Status: {status['message']}")
                except zmq.Again:
                    print("  (no status received)")

    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        pub.close()
        status_sub.close()
        ctx.term()


if __name__ == "__main__":
    main()
