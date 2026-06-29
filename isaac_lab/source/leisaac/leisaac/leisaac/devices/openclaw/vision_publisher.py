"""Vision publisher for YOLO-based orange detection in LeIsaac.

Captures camera frames from the simulation, runs YOLO inference to detect
oranges, and publishes detection data (positions, distances, subtask status)
over ZMQ for NemoClaw consumption.

The publisher combines YOLO visual detections with ground-truth positions
from the simulation scene, giving the NemoClaw agent accurate world
coordinates for each orange and the plate.
"""

import json
import queue
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
import torch

try:
    import zmq
except ImportError:
    raise ImportError("pyzmq is required: pip install pyzmq")


class VisionPublisher:
    """Publishes orange/plate detections over ZMQ for NemoClaw.

    Runs YOLO on the front camera image at a configurable interval and
    publishes a JSON message containing:
    - Gripper world position
    - Robot base position and forward direction
    - Per-orange: world position, relative offset, distance, subtask status
    - Plate: world position, relative offset
    - YOLO detection results (bounding boxes, confidences)
    """

    ORANGE_NAMES = ["Orange001", "Orange002", "Orange003"]
    PLATE_NAME = "Plate"
    COCO_DETECT_CLASSES = [32, 47, 49]

    def __init__(self, env, yolo_model="yolo11n.pt", port=5559, detect_interval=15):
        """
        Args:
            env: IsaacLab environment with scene containing oranges, plate, robot.
            yolo_model: Path to YOLO model weights.
            port: ZMQ PUB port for detection messages.
            detect_interval: Run YOLO every N simulation frames.
        """
        self.env = env
        self._port = port
        self._detect_interval = detect_interval
        self._frame_count = 0

        self._yolo = None
        try:
            from ultralytics import YOLO
            self._yolo = YOLO(yolo_model)
            print(f"[VisionPublisher] YOLO model loaded: {yolo_model}")
        except ImportError:
            print("[VisionPublisher] ultralytics not installed — using ground-truth positions only")
        except Exception as e:
            print(f"[VisionPublisher] YOLO load failed ({e}) — using ground-truth positions only")

        self._ctx = zmq.Context()
        self._pub = self._ctx.socket(zmq.PUB)
        self._pub.bind(f"tcp://0.0.0.0:{port}")

        self._latest_json = b"{}"
        self._command_queue = queue.Queue()
        self._http_port = port + 1
        self._http_server = _start_http_server(self, self._http_port)

        print(f"[VisionPublisher] Publishing detections on tcp://0.0.0.0:{port}")
        print(f"[VisionPublisher] HTTP endpoint at http://0.0.0.0:{self._http_port}/detect")

    def update(self):
        """Call after env.step(). Runs detection and publishes at the configured interval."""
        self._frame_count += 1
        if self._frame_count % self._detect_interval != 0:
            return
        try:
            self._detect_and_publish()
        except Exception as e:
            print(f"[VisionPublisher] Error: {e}")

    def _detect_and_publish(self):
        yolo_results = self._run_yolo()

        gripper_pos = self._get_gripper_pos()
        base_pos, forward_dir = self._get_robot_base_info()

        oranges = []
        subtask = self._get_subtask_status()
        for name in self.ORANGE_NAMES:
            info = self._get_object_info(name, gripper_pos, subtask)
            if info is not None:
                oranges.append(info)

        plate_info = self._get_plate_info(gripper_pos)

        message = {
            "timestamp": time.time(),
            "frame": self._frame_count,
            "gripper_pos": _round_list(gripper_pos),
            "robot_base_pos": _round_list(base_pos),
            "robot_forward_dir": _round_list(forward_dir),
            "oranges": oranges,
            "plate": plate_info,
            "yolo_count": len(yolo_results),
            "yolo_detections": yolo_results,
        }

        payload = json.dumps(message).encode("utf-8")
        self._latest_json = payload
        self._pub.send(payload, flags=zmq.NOBLOCK)

    def _run_yolo(self):
        if self._yolo is None:
            return []
        image = self._get_camera_image()
        if image is None:
            return []
        try:
            results = self._yolo(image, verbose=False, classes=self.COCO_DETECT_CLASSES)
            detections = []
            for box in results[0].boxes:
                cx, cy, w, h = box.xywh[0].cpu().numpy()
                if w > 100 or h > 100:
                    continue
                detections.append({
                    "confidence": round(float(box.conf.item()), 3),
                    "class": results[0].names[int(box.cls.item())],
                    "center": [round(float(cx), 1), round(float(cy), 1)],
                    "size": [round(float(w), 1), round(float(h), 1)],
                })
            return detections
        except Exception as e:
            print(f"[VisionPublisher] YOLO error: {e}")
            return []

    def _get_camera_image(self):
        """Get front camera RGB image as numpy uint8 [H, W, 3]."""
        try:
            if hasattr(self.env, "obs_buf") and self.env.obs_buf is not None:
                img = self.env.obs_buf["policy"]["front"][0]
                return self._tensor_to_uint8(img)
        except (KeyError, IndexError, AttributeError):
            pass
        try:
            cam = self.env.scene["front"]
            img = cam.data.output["rgb"][0]
            if img.shape[-1] == 4:
                img = img[:, :, :3]
            return self._tensor_to_uint8(img)
        except (KeyError, IndexError, AttributeError):
            pass
        return None

    @staticmethod
    def _tensor_to_uint8(t):
        if t.dtype in (torch.float32, torch.float16, torch.bfloat16):
            t = (t * 255).clamp(0, 255).byte()
        return t.cpu().numpy()

    def _get_gripper_pos(self):
        ee = self.env.scene["ee_frame"]
        return ee.data.target_pos_w[0, 1].cpu().numpy()

    def _get_robot_base_info(self):
        robot = self.env.scene["robot"]
        pos = robot.data.root_pos_w[0].cpu().numpy()
        quat = robot.data.root_quat_w[0].cpu().numpy()
        fwd = _quat_forward_xy(quat)
        return pos, fwd

    def _get_object_info(self, name, gripper_pos, subtask):
        try:
            obj = self.env.scene[name]
            pos = obj.data.root_pos_w[0].cpu().numpy()
            rel = pos - gripper_pos
            dist = float(np.linalg.norm(rel))
            idx = name[-3:]
            return {
                "id": name,
                "world_pos": _round_list(pos),
                "relative_pos": _round_list(rel),
                "distance": round(dist, 4),
                "picked": subtask.get(f"pick_orange{idx}", False),
                "on_plate": subtask.get(f"put_orange{idx}_to_plate", False),
            }
        except (KeyError, IndexError):
            return None

    def _get_plate_info(self, gripper_pos):
        try:
            obj = self.env.scene[self.PLATE_NAME]
            pos = obj.data.root_pos_w[0].cpu().numpy()
            rel = pos - gripper_pos
            return {
                "world_pos": _round_list(pos),
                "relative_pos": _round_list(rel),
                "distance": round(float(np.linalg.norm(rel)), 4),
            }
        except (KeyError, IndexError):
            return None

    def _get_subtask_status(self):
        status = {}
        try:
            if hasattr(self.env, "obs_buf") and self.env.obs_buf is not None:
                for key, val in self.env.obs_buf.get("subtask_terms", {}).items():
                    status[key] = bool(val[0].item() if val.dim() == 1 else val[0, 0].item())
        except (AttributeError, IndexError):
            pass
        return status

    def drain_commands(self):
        """Return list of pending command dicts from HTTP POST requests."""
        cmds = []
        while not self._command_queue.empty():
            try:
                cmds.append(self._command_queue.get_nowait())
            except queue.Empty:
                break
        return cmds

    def close(self):
        try:
            if self._http_server:
                self._http_server.shutdown()
        except Exception:
            pass
        try:
            self._pub.close()
            self._ctx.term()
        except Exception:
            pass

    def __del__(self):
        self.close()


def _round_list(arr, decimals=4):
    return [round(float(x), decimals) for x in arr]


def _start_http_server(publisher, port):
    """Start a background HTTP server for detection (GET) and commands (POST)."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            body = publisher._latest_json
            self._respond(200, body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b""
            try:
                cmd = json.loads(raw)
                publisher._command_queue.put(cmd)
                resp = json.dumps({"status": "sent", "action": cmd.get("action", "")}).encode()
                self._respond(200, resp)
            except Exception as e:
                resp = json.dumps({"status": "error", "message": str(e)}).encode()
                self._respond(400, resp)

        def _respond(self, code, body):
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            self.wfile.flush()

        def log_message(self, format, *args):
            pass

    server = HTTPServer(("0.0.0.0", port), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def _quat_forward_xy(quat_wxyz):
    """Compute the forward direction (local +X) projected onto XY plane from a wxyz quaternion."""
    w, x, y, z = quat_wxyz
    fx = 1 - 2 * (y * y + z * z)
    fy = 2 * (x * y + w * z)
    norm = np.sqrt(fx * fx + fy * fy)
    if norm < 1e-6:
        return [1.0, 0.0]
    return [round(float(fx / norm), 4), round(float(fy / norm), 4)]
