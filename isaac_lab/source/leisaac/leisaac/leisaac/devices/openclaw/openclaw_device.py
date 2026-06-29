"""OpenClaw teleop device for LeIsaac.

Receives high-level NL commands from OpenClaw (via ZMQ) and converts them
into continuous IK delta-pose actions compatible with LeIsaac's keyboard
action pipeline.

Architecture:
    OpenClaw (chat app) -> IsaacLabAdapter -> ZMQ PUB ->
    -> OpenClawDevice (ZMQ SUB) -> delta poses @ 60Hz -> env.step()
"""

import json
import struct
import threading
from typing import Any

import numpy as np

from ..device_base import Device

try:
    import zmq
except ImportError:
    raise ImportError("pyzmq is required: pip install pyzmq")


COMMAND_SCHEMA = {
    "forward": {"param": "distance", "default": 1.0},
    "backward": {"param": "distance", "default": 1.0},
    "left": {"param": "distance", "default": 0.5},
    "right": {"param": "distance", "default": 0.5},
    "up": {"param": "distance", "default": 0.3},
    "down": {"param": "distance", "default": 0.3},
    "turn_left": {"param": "angle", "default": 45.0},
    "turn_right": {"param": "angle", "default": 45.0},
    "gripper_open": {"param": None, "default": None},
    "gripper_close": {"param": None, "default": None},
    "stop": {"param": None, "default": None},
}

# delta-pose vector indices: [dx, dy, dz, droll, dpitch, dyaw, d_shoulder_pan, d_gripper]
ACTION_VECTORS = {
    "forward": np.array([0.0, 0.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    "backward": np.array([0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    "left": np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0]),
    "right": np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0]),
    "up": np.array([1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    "down": np.array([-1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    "turn_left": np.array([0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]),
    "turn_right": np.array([0.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 0.0]),
    "gripper_open": np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]),
    "gripper_close": np.array([0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0]),
    "stop": np.zeros(8),
}


class OpenClawDevice(Device):
    """Teleop device that receives commands from OpenClaw over ZMQ.

    Uses device_type="keyboard" to reuse the existing Differential IK action
    pipeline (8-element delta pose: dx,dy,dz,droll,dpitch,dyaw,d_shoulder_pan,d_gripper).

    Commands are converted into timed motion trajectories that feed delta poses
    at the simulation step rate.
    """

    def __init__(
        self,
        env,
        endpoint: str = "tcp://0.0.0.0:5557",
        step_hz: int = 60,
        pos_speed: float = 0.15,
        rot_speed: float = 0.5,
        gripper_duration: float = 1.0,
    ):
        """
        Args:
            env: Isaac Lab environment.
            endpoint: ZMQ SUB endpoint to bind/connect.
            step_hz: Simulation step rate (must match --step_hz).
            pos_speed: Cartesian speed in m/s for position commands.
            rot_speed: Rotation speed in rad/s for turn commands.
            gripper_duration: Time in seconds to hold gripper open/close.
        """
        self._endpoint = endpoint
        super().__init__(env, "keyboard")

        self._step_hz = step_hz
        self._pos_speed = pos_speed
        self._rot_speed = rot_speed
        self._gripper_duration = gripper_duration

        self._delta_action = np.zeros(8)
        self._remaining_steps = 0
        self._gripper_hold = 0.0
        self._lock = threading.Lock()

        self.asset_name = "robot"
        self.robot_asset = self.env.scene[self.asset_name]
        self.target_frame = "gripper"
        body_idxs, _ = self.robot_asset.find_bodies(self.target_frame)
        self.target_frame_idx = body_idxs[0]

        self._ctx = zmq.Context()
        self._sub = self._ctx.socket(zmq.SUB)
        self._sub.setsockopt(zmq.SUBSCRIBE, b"")
        self._sub.setsockopt(zmq.CONFLATE, 1)
        self._sub.bind(endpoint)

        self._connected = True
        self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
        self._recv_thread.start()

        self._status_pub = self._ctx.socket(zmq.PUB)
        self._status_pub.bind(endpoint.replace("5557", "5558"))

        print(f"[OpenClawDevice] Listening for commands on {endpoint}")
        print(f"[OpenClawDevice] Publishing status on {endpoint.replace('5557', '5558')}")

    def _recv_loop(self):
        """Background thread: receive JSON commands from OpenClaw."""
        while self._connected:
            try:
                msg = self._sub.recv(flags=0)
                cmd = json.loads(msg.decode("utf-8"))
                self._process_command(cmd)
            except zmq.ZMQError:
                break
            except (json.JSONDecodeError, KeyError) as e:
                print(f"[OpenClawDevice] Bad command: {e}")

    def _process_command(self, cmd: dict):
        """Convert an OpenClaw command dict into a timed delta-pose trajectory."""
        if not self._started:
            self._started = True
            print("[OpenClawDevice] Auto-started on first command")
        action = cmd.get("action", "stop")
        params = cmd.get("params", {})

        if action not in ACTION_VECTORS:
            print(f"[OpenClawDevice] Unknown action: {action}")
            self._publish_status(False, f"Unknown action: {action}")
            return

        schema = COMMAND_SCHEMA.get(action, {})
        param_name = schema.get("param")

        if action == "stop":
            with self._lock:
                self._delta_action = np.zeros(8)
                self._remaining_steps = 0
            self._publish_status(True, "Stopped")
            return

        base_vector = ACTION_VECTORS[action].copy()

        if action in ("gripper_open", "gripper_close"):
            self._gripper_hold = -0.05 if action == "gripper_close" else 0.0
            duration = self._gripper_duration
            scale = 0.15
        elif action in ("turn_left", "turn_right"):
            angle_deg = float(params.get("angle", schema["default"]))
            angle_rad = np.deg2rad(angle_deg)
            duration = angle_rad / self._rot_speed
            scale = self._rot_speed / self._step_hz
        else:
            distance = float(params.get("distance", schema["default"]))
            duration = distance / self._pos_speed
            scale = self._pos_speed / self._step_hz

        num_steps = max(1, int(duration * self._step_hz))
        delta = base_vector * scale

        with self._lock:
            self._delta_action = delta
            self._remaining_steps = num_steps

        self._publish_status(True, f"Executing: {action} ({num_steps} steps)")
        print(f"[OpenClawDevice] {action} -> {num_steps} steps @ {scale:.4f}/step")

    def _publish_status(self, success: bool, message: str):
        """Publish execution status back to OpenClaw."""
        try:
            status = json.dumps({"success": success, "message": message})
            self._status_pub.send(status.encode("utf-8"), flags=zmq.NOBLOCK)
        except zmq.ZMQError:
            pass

    def get_device_state(self) -> np.ndarray:
        with self._lock:
            if self._remaining_steps > 0:
                self._remaining_steps -= 1
                delta = self._delta_action.copy()
            else:
                delta = np.zeros(8)
            if self._remaining_steps <= 0 and self._gripper_hold != 0.0:
                delta[7] = self._gripper_hold
        return self._convert_delta_from_frame(delta)

    def _add_device_control_description(self):
        self._display_controls_table.add_row(["OpenClaw", f"Listening on {self._endpoint}"])
        self._display_controls_table.add_row(["Commands", "forward/backward/left/right/up/down/turn/gripper"])

    def reset(self):
        with self._lock:
            self._delta_action = np.zeros(8)
            self._remaining_steps = 0

    def disconnect(self):
        self._connected = False
        self._sub.close()
        self._status_pub.close()
        self._ctx.term()

    def __del__(self):
        self.disconnect()
        super().__del__()
