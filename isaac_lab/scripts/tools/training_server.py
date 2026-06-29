#!/usr/bin/env python3
"""Host-side HTTP server for controlling Isaac Lab RL training from the NemoClaw sandbox."""

import json
import os
import signal
import subprocess
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

HOST = "0.0.0.0"
PORT = 5561

CONDA_PYTHON = "/home/dgx-destro/miniforge3/envs/env_isaaclab/bin/python"
ROBOT_LAB_DIR = "/home/dgx-destro/humanoid_nemoclaw/robot_lab"
LOG_BASE = os.path.join(ROBOT_LAB_DIR, "logs")
LD_PRELOAD = "/lib/aarch64-linux-gnu/libgomp.so.1"

BACKENDS = {
    "cusrl": "scripts/reinforcement_learning/cusrl/train.py",
    "rsl_rl": "scripts/reinforcement_learning/rsl_rl/train.py",
}

ENVIRONMENTS = [
    {"id": "RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0", "robot": "RobotEra XBot", "category": "humanoid", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-RobotEra-Xbot-v0", "robot": "RobotEra XBot", "category": "humanoid", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0", "robot": "Unitree G1", "category": "humanoid", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Unitree-G1-v0", "robot": "Unitree G1", "category": "humanoid", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Unitree-H1-v0", "robot": "Unitree H1", "category": "humanoid", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Unitree-H1-v0", "robot": "Unitree H1", "category": "humanoid", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-FFTAI-GR1T1-v0", "robot": "FFTAI GR1T1", "category": "humanoid", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-FFTAI-GR1T1-v0", "robot": "FFTAI GR1T1", "category": "humanoid", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-FFTAI-GR1T2-v0", "robot": "FFTAI GR1T2", "category": "humanoid", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-FFTAI-GR1T2-v0", "robot": "FFTAI GR1T2", "category": "humanoid", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Booster-T1-v0", "robot": "Booster T1", "category": "humanoid", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Booster-T1-v0", "robot": "Booster T1", "category": "humanoid", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Openloong-Loong-v0", "robot": "Openloong Loong", "category": "humanoid", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Openloong-Loong-v0", "robot": "Openloong Loong", "category": "humanoid", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-RoboParty-ATOM01-v0", "robot": "RoboParty ATOM01", "category": "humanoid", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-RoboParty-ATOM01-v0", "robot": "RoboParty ATOM01", "category": "humanoid", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-MagicLab-Bot-Gen1-v0", "robot": "MagicLab MagicBot Gen1", "category": "humanoid", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-MagicLab-Bot-Gen1-v0", "robot": "MagicLab MagicBot Gen1", "category": "humanoid", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-MagicLab-Bot-Z1-v0", "robot": "MagicLab MagicBot Z1", "category": "humanoid", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-MagicLab-Bot-Z1-v0", "robot": "MagicLab MagicBot Z1", "category": "humanoid", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Unitree-Go2-v0", "robot": "Unitree Go2", "category": "quadruped", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Unitree-Go2-v0", "robot": "Unitree Go2", "category": "quadruped", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Unitree-A1-v0", "robot": "Unitree A1", "category": "quadruped", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Unitree-A1-v0", "robot": "Unitree A1", "category": "quadruped", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Unitree-B2-v0", "robot": "Unitree B2", "category": "quadruped", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Unitree-B2-v0", "robot": "Unitree B2", "category": "quadruped", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Deeprobotics-Lite3-v0", "robot": "Deeprobotics Lite3", "category": "quadruped", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Deeprobotics-Lite3-v0", "robot": "Deeprobotics Lite3", "category": "quadruped", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Zsibot-ZSL1-v0", "robot": "Zsibot ZSL1", "category": "quadruped", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Zsibot-ZSL1-v0", "robot": "Zsibot ZSL1", "category": "quadruped", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-MagicLab-Dog-v0", "robot": "MagicLab MagicDog", "category": "quadruped", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-MagicLab-Dog-v0", "robot": "MagicLab MagicDog", "category": "quadruped", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Agibot-D1-v0", "robot": "Agibot D1", "category": "quadruped", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Agibot-D1-v0", "robot": "Agibot D1", "category": "quadruped", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Unitree-Go2W-v0", "robot": "Unitree Go2W", "category": "wheeled", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Unitree-Go2W-v0", "robot": "Unitree Go2W", "category": "wheeled", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Unitree-B2W-v0", "robot": "Unitree B2W", "category": "wheeled", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Unitree-B2W-v0", "robot": "Unitree B2W", "category": "wheeled", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Deeprobotics-M20-v0", "robot": "Deeprobotics M20", "category": "wheeled", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Deeprobotics-M20-v0", "robot": "Deeprobotics M20", "category": "wheeled", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-DDTRobot-Tita-v0", "robot": "DDTRobot Tita", "category": "wheeled", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-DDTRobot-Tita-v0", "robot": "DDTRobot Tita", "category": "wheeled", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-Zsibot-ZSL1W-v0", "robot": "Zsibot ZSL1W", "category": "wheeled", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-Zsibot-ZSL1W-v0", "robot": "Zsibot ZSL1W", "category": "wheeled", "terrain": "rough"},
    {"id": "RobotLab-Isaac-Velocity-Flat-MagicLab-Dog-W-v0", "robot": "MagicLab MagicDog-W", "category": "wheeled", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-MagicLab-Dog-W-v0", "robot": "MagicLab MagicDog-W", "category": "wheeled", "terrain": "rough"},
    {"id": "RobotLab-Isaac-G1-AMP-Dance-Direct-v0", "robot": "Unitree G1 (AMP Dance)", "category": "direct", "terrain": "flat"},
    {"id": "RobotLab-Isaac-BeyondMimic-Flat-Unitree-G1-v0", "robot": "Unitree G1 (BeyondMimic)", "category": "direct", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Flat-HandStand-Unitree-A1-v0", "robot": "Unitree A1 (Handstand)", "category": "other", "terrain": "flat"},
    {"id": "RobotLab-Isaac-Velocity-Rough-HandStand-Unitree-A1-v0", "robot": "Unitree A1 (Handstand)", "category": "other", "terrain": "rough"},
]

training_state = {
    "process": None,
    "pid": None,
    "task": None,
    "backend": None,
    "num_envs": None,
    "start_time": None,
    "log_file": None,
}


def is_training_running():
    proc = training_state["process"]
    if proc is None:
        return False
    if proc.poll() is not None:
        training_state["process"] = None
        return False
    return True


def tail_log(n=30):
    log_file = training_state.get("log_file")
    if not log_file or not os.path.exists(log_file):
        return ""
    with open(log_file, "r") as f:
        lines = f.readlines()
    return "".join(lines[-n:])


class TrainingHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {format % args}")

    def _respond(self, code, data):
        body = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self):
        if self.path == "/envs":
            self._respond(200, {"environments": ENVIRONMENTS, "count": len(ENVIRONMENTS)})

        elif self.path == "/status":
            running = is_training_running()
            info = {
                "running": running,
                "task": training_state["task"],
                "backend": training_state["backend"],
                "num_envs": training_state["num_envs"],
                "pid": training_state["pid"],
            }
            if running and training_state["start_time"]:
                elapsed = time.time() - training_state["start_time"]
                info["elapsed_seconds"] = round(elapsed)
                info["elapsed_human"] = f"{int(elapsed//3600)}h {int((elapsed%3600)//60)}m {int(elapsed%60)}s"
            if not running and training_state["task"]:
                info["status"] = "completed"
            self._respond(200, info)

        elif self.path.startswith("/logs"):
            n = 30
            if "?" in self.path:
                params = dict(p.split("=") for p in self.path.split("?")[1].split("&") if "=" in p)
                n = int(params.get("lines", 30))
            lines = tail_log(n)
            self._respond(200, {"lines": lines, "log_file": training_state.get("log_file")})

        else:
            self._respond(404, {"error": f"Unknown endpoint: {self.path}"})

    def do_POST(self):
        if self.path == "/train":
            if is_training_running():
                self._respond(409, {
                    "error": "Training already running",
                    "task": training_state["task"],
                    "pid": training_state["pid"],
                })
                return

            body = self._read_body()
            task = body.get("task")
            backend = body.get("backend", "cusrl")
            num_envs = body.get("num_envs", 4096)
            max_iterations = body.get("max_iterations")
            seed = body.get("seed")

            if not task:
                self._respond(400, {"error": "Missing 'task' field"})
                return

            valid_ids = [e["id"] for e in ENVIRONMENTS]
            if task not in valid_ids:
                self._respond(400, {"error": f"Unknown task: {task}", "valid_tasks": valid_ids})
                return

            if backend not in BACKENDS:
                self._respond(400, {"error": f"Unknown backend: {backend}", "valid": list(BACKENDS.keys())})
                return

            script = os.path.join(ROBOT_LAB_DIR, BACKENDS[backend])
            log_dir = os.path.join(LOG_BASE, "training_server")
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, f"{task}_{int(time.time())}.log")

            cmd = [CONDA_PYTHON, script, f"--task={task}", "--headless", f"--num_envs={num_envs}"]
            if max_iterations:
                cmd.append(f"--max_iterations={max_iterations}")
            if seed:
                cmd.append(f"--seed={seed}")

            env = os.environ.copy()
            env["LD_PRELOAD"] = LD_PRELOAD

            with open(log_file, "w") as lf:
                proc = subprocess.Popen(cmd, cwd=ROBOT_LAB_DIR, env=env, stdout=lf, stderr=subprocess.STDOUT)

            training_state["process"] = proc
            training_state["pid"] = proc.pid
            training_state["task"] = task
            training_state["backend"] = backend
            training_state["num_envs"] = num_envs
            training_state["start_time"] = time.time()
            training_state["log_file"] = log_file

            self._respond(200, {
                "status": "started",
                "task": task,
                "backend": backend,
                "num_envs": num_envs,
                "pid": proc.pid,
                "log_file": log_file,
            })

        elif self.path == "/stop":
            if not is_training_running():
                self._respond(200, {"status": "no training running"})
                return

            proc = training_state["process"]
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()

            self._respond(200, {
                "status": "stopped",
                "task": training_state["task"],
                "pid": training_state["pid"],
            })
            training_state["process"] = None

        else:
            self._respond(404, {"error": f"Unknown endpoint: {self.path}"})


def main():
    server = HTTPServer((HOST, PORT), TrainingHandler)
    print(f"NemoClaw Training Server listening on {HOST}:{PORT}")
    print(f"  POST /train   — start training (body: {{task, backend, num_envs}})")
    print(f"  POST /stop    — stop training")
    print(f"  GET  /status  — training status")
    print(f"  GET  /logs    — tail training logs")
    print(f"  GET  /envs    — list environments")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        if is_training_running():
            training_state["process"].terminate()
        server.server_close()


if __name__ == "__main__":
    main()
