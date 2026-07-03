#!/usr/bin/env python3
"""
Isaac Control Server  —  the single host-side control surface for isaac-claw.

Both runtimes (NemoClaw / Nemotron and OpenClaw / Gemma) drive Isaac Sim AND
Isaac Lab through THIS one HTTP API from inside their sandbox. It generalizes
the old training-only server (robot_lab/scripts/tools/training_server.py) into a
full Isaac control API:

    GET  /envs            list registered Isaac Lab tasks + available scenes
    GET  /scenes          list USD scenes under isaac_sim/scenes
    GET  /robots          list robots resolvable from the asset catalog
    GET  /status          current job (sim OR train/play/eval) status
    GET  /logs?lines=N    tail the active job log

    POST /sim/launch      {scene?}            launch Isaac Sim headless on a scene
    POST /scene/load      {scene}             load a USD into the RUNNING sim (port 8226)
    POST /robot/spawn     {robot, x?,y?,z?}   spawn a catalog robot into the running sim
    POST /exec            {code}              run arbitrary python in the running sim
    POST /train           {task, backend, num_envs?, max_iterations?, seed?}
    POST /play            {task, backend?, checkpoint?, num_envs?}
    POST /eval            {task, backend?, checkpoint?, num_envs?}
    POST /stop            {}                  stop the active GPU job

Design rules carried over from the originals:
  * Only ONE heavy GPU job at a time (a sim bring-up OR an RL run) — the GPU is
    the bottleneck, so /train while a sim is up returns 409.
  * Scene-load / robot-spawn / exec target an ALREADY-RUNNING Isaac Sim by
    sending python over the isaacsim.code_editor.python_server TCP socket
    (default 127.0.0.1:8226) — the extension shipped in isaac_sim/source/.
  * Paths come from the environment (see CONFIG below), never hardcoded users.

This file is dependency-free (Python stdlib only) so it runs under any python.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# --------------------------------------------------------------------------- #
# CONFIG — everything is overridable by environment, with isaac-claw defaults.
# --------------------------------------------------------------------------- #
HERE = Path(__file__).resolve()
# isaac-claw/isaac_sim/scripts/isaac_control_server.py -> repo root is parents[2]
CLAW_DIR = Path(os.environ.get("ISAAC_CLAW_DIR", HERE.parents[2]))
LAB_DIR = CLAW_DIR / "isaac_lab"
SIM_DIR = CLAW_DIR / "isaac_sim"

# The python that has Isaac Lab installed (conda env or IsaacSim's python.sh).
LAB_PYTHON = os.environ.get(
    "ISAAC_LAB_PYTHON",
    os.path.expanduser("~/miniforge3/envs/env_isaaclab/bin/python"),
)
# Isaac Sim install root (referenced, not vendored — see repo README).
ISAAC_SIM_INSTALL = Path(os.environ.get("ISAAC_SIM_DIR", os.path.expanduser("~/IsaacSim")))

# Asset catalog used to resolve friendly robot names -> USD paths (Layer-1).
CATALOG = Path(os.environ.get(
    "ISAAC_CLAW_CATALOG", CLAW_DIR / "agents" / "core" / "assets" / "catalog.yaml"))
# Scene/robot composition templates (environments.yaml + composite templates) so
# /open and /templates can resolve env+robot server-side (NemoClaw has no `claw`).
TPL_DIR = SIM_DIR / "templates"

# Running-sim python bridge (isaacsim.code_editor.python_server).
PY_SERVER_HOST = os.environ.get("ISAAC_PY_SERVER_HOST", "127.0.0.1")
PY_SERVER_PORT = int(os.environ.get("ISAAC_PY_SERVER_PORT", "8226"))

# Optional LD_PRELOAD fix carried from robot_lab (libgomp on aarch64). Set "" to skip.
LD_PRELOAD = os.environ.get("ISAAC_LD_PRELOAD",
                            "/lib/aarch64-linux-gnu/libgomp.so.1")

HOST = os.environ.get("ISAAC_CONTROL_HOST", "0.0.0.0")
PORT = int(os.environ.get("ISAAC_CONTROL_PORT", "5561"))  # same port the clients already use

LOG_DIR = CLAW_DIR / "isaac_sim" / "_control_logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# RL training entry scripts per framework (relative to isaac_lab/). Missing files
# are simply not offered — keeps the server honest about what's installed.
TRAIN_SCRIPTS = {
    "cusrl":    "scripts/reinforcement_learning/cusrl/train.py",
    "rsl_rl":   "scripts/reinforcement_learning/rsl_rl/train.py",
    "skrl":     "scripts/reinforcement_learning/skrl/train.py",
}
PLAY_SCRIPTS = {
    "cusrl":    "scripts/reinforcement_learning/cusrl/play.py",
    "rsl_rl":   "scripts/reinforcement_learning/rsl_rl/play.py",
    "skrl":     "scripts/reinforcement_learning/skrl/play.py",
}

# Research/repo-advised tuning guides (served at GET /tuning?backend=…) so a
# local model can pick hyperparameters from real ranges instead of guessing.
POLICIES_DIR = CLAW_DIR / "policies"

# Friendly tuning-knob name -> Hydra override path for RSL-RL / CusRL. train.py
# forwards any unrecognized `agent.*`/`env.*` arg to Hydra (@hydra_task_config),
# so these become real config overrides. (skrl has a different cfg tree — use
# raw `overrides` for it; friendly knobs here are rsl_rl/cusrl only.)
HYDRA_KNOBS = {
    "learning_rate":       "agent.algorithm.learning_rate",
    "lr":                  "agent.algorithm.learning_rate",
    "entropy_coef":        "agent.algorithm.entropy_coef",
    "gamma":               "agent.algorithm.gamma",
    "lambda":              "agent.algorithm.lam",
    "lam":                 "agent.algorithm.lam",
    "clip_param":          "agent.algorithm.clip_param",
    "desired_kl":          "agent.algorithm.desired_kl",
    "value_loss_coef":     "agent.algorithm.value_loss_coef",
    "num_learning_epochs": "agent.algorithm.num_learning_epochs",
    "num_mini_batches":    "agent.algorithm.num_mini_batches",
    "max_grad_norm":       "agent.algorithm.max_grad_norm",
    "num_steps_per_env":   "agent.num_steps_per_env",
    "init_noise_std":      "agent.policy.init_noise_std",
}

def knob_to_override(k, v):
    """Friendly knob -> Hydra 'key=value'. reward_<term> -> env.rewards.<term>.weight
    (best-effort: a task's __post_init__ may re-pin reward weights). Returns None if
    the knob is unknown so the caller can skip it honestly."""
    if k in HYDRA_KNOBS:
        return f"{HYDRA_KNOBS[k]}={v}"
    if k.startswith("reward_"):
        return f"env.rewards.{k[len('reward_'):]}.weight={v}"
    if k.startswith(("agent.", "env.")):   # already a raw Hydra path
        return f"{k}={v}"
    return None

# --------------------------------------------------------------------------- #
# Registries
# --------------------------------------------------------------------------- #
def load_envs():
    reg = LAB_DIR / "envs_registry.json"
    if reg.exists():
        return json.loads(reg.read_text()).get("environments", [])
    return []


def list_scenes():
    scenes_dir = SIM_DIR / "scenes"
    if not scenes_dir.exists():
        return []
    return sorted(p.name for p in scenes_dir.glob("*.usd*"))


def list_robots():
    """Best-effort friendly-name list from the catalog (no YAML dep required)."""
    if not CATALOG.exists():
        return []
    names = []
    try:
        import re
        for line in CATALOG.read_text().splitlines():
            m = re.match(r"^\s{2,}([a-zA-Z0-9_]+):\s*$", line)
            if m:
                names.append(m.group(1))
    except Exception:
        pass
    return sorted(set(names))


ENVIRONMENTS = load_envs()
VALID_IDS = {e["id"] for e in ENVIRONMENTS}

# --------------------------------------------------------------------------- #
# Single-job state machine (one GPU job at a time)
# --------------------------------------------------------------------------- #
job = {
    "process": None, "pid": None, "kind": None, "label": None,
    "start_time": None, "log_file": None,
}


def job_running():
    p = job["process"]
    if p is None:
        return False
    if p.poll() is not None:
        job["process"] = None
        return False
    return True


def tail_log(n=40):
    lf = job.get("log_file")
    if not lf or not os.path.exists(lf):
        return ""
    with open(lf) as f:
        return "".join(f.readlines()[-n:])


def start_job(kind, label, cmd, cwd):
    log_file = LOG_DIR / f"{kind}_{label}_{int(time.time())}.log".replace("/", "_")
    env = os.environ.copy()
    if LD_PRELOAD:
        env["LD_PRELOAD"] = LD_PRELOAD
    env.setdefault("ISAAC_CLAW_DIR", str(CLAW_DIR))
    with open(log_file, "w") as lf:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=lf,
                                stderr=subprocess.STDOUT)
    job.update(process=proc, pid=proc.pid, kind=kind, label=label,
               start_time=time.time(), log_file=str(log_file))
    return {"status": "started", "kind": kind, "label": label,
            "pid": proc.pid, "log_file": str(log_file)}


# --------------------------------------------------------------------------- #
# Running-sim bridge (python_server socket on 8226)
# --------------------------------------------------------------------------- #
def send_to_sim(code, timeout=120):
    """Send python source to a running Isaac Sim and return its JSON result."""
    with socket.create_connection((PY_SERVER_HOST, PY_SERVER_PORT), timeout=timeout) as s:
        s.sendall(code.encode("utf-8"))
        s.shutdown(socket.SHUT_WR)  # signal EOF (write_eof equivalent)
        chunks = []
        while True:
            b = s.recv(65536)
            if not b:
                break
            chunks.append(b)
    raw = b"".join(chunks).decode("utf-8", "replace")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"status": "ok", "output": raw}


def resolve_robot_usd(name):
    """Resolve a friendly robot name to its USD via the catalog (yaml optional)."""
    if not CATALOG.exists():
        return None
    try:
        import yaml  # optional
        data = yaml.safe_load(CATALOG.read_text())
        for cat in (data.get("categories") or {}).values():
            if isinstance(cat, dict) and name in cat:
                return cat[name].get("usd")
    except Exception:
        # crude fallback: grab the `usd:` line following the name key
        import re
        text = CATALOG.read_text()
        m = re.search(rf"^\s*{re.escape(name)}:\s*$.*?usd:\s*['\"]?([^'\"\n]+)",
                      text, re.S | re.M)
        if m:
            return m.group(1).strip()
    return None


def _spawn_code(name, usd, x, y, z):
    """In-sim python that references a robot USD (Nucleus tokens resolved) and
    places it, reusing an existing translate op instead of adding a duplicate."""
    prim = "/World/" + "".join(c for c in name.title() if c.isalnum())
    return (
        "from pxr import UsdGeom, Gf\n"
        "import omni.usd\n"
        "try:\n"
        "    from isaacsim.storage.native import get_assets_root_path\n"
        "except Exception:\n"
        "    from omni.isaac.nucleus import get_assets_root_path\n"
        f"usd = r'''{usd}'''\n"
        "root = get_assets_root_path() or ''\n"
        "usd = usd.replace('{ISAACLAB_NUCLEUS_DIR}', root + '/Isaac/IsaacLab')"
        ".replace('{ISAAC_NUCLEUS_DIR}', root + '/Isaac')"
        ".replace('{NUCLEUS_ASSET_ROOT_DIR}', root)\n"
        "stage = omni.usd.get_context().get_stage()\n"
        f"p = stage.GetPrimAtPath('{prim}')\n"
        "if not (p and p.IsValid()):\n"
        f"    p = stage.DefinePrim('{prim}', 'Xform')\n"
        "    p.GetReferences().AddReference(usd)\n"
        "xf = UsdGeom.Xformable(p)\n"
        "ops = {op.GetOpType(): op for op in xf.GetOrderedXformOps()}\n"
        "t = ops.get(UsdGeom.XformOp.TypeTranslate) or xf.AddTranslateOp()\n"
        f"t.Set(Gf.Vec3d({x}, {y}, {z}))\n"
        f"print('spawned {name} at ({x},{y},{z}) ->', usd)\n"
    )


def _spawn_when_ready(robots, log_file, ready_timeout=600):
    """Background worker: wait for the sim's :8226 bridge, then spawn each robot.

    Lets `claw open` return immediately (POST /sim/launch with a `spawn` list)
    instead of blocking the caller through the whole GPU bring-up — which a local
    model's command timeout would otherwise kill mid-flight. `log_file` is captured
    at schedule time so a later relaunch can't redirect this thread's logging.
    """
    def _log(msg):
        try:
            with open(log_file, "a") as f:
                f.write(f"[spawn-when-ready] {msg}\n")
        except Exception:
            pass

    deadline = time.time() + ready_timeout
    while time.time() < deadline:
        try:
            r = send_to_sim("print('pong')", timeout=15)
            if r.get("status") != "error":
                break
        except OSError:
            pass
        time.sleep(2)
    else:
        _log("sim never became ready; not spawning")
        return
    for spec in robots:
        name = spec.get("robot")
        usd = resolve_robot_usd(name)
        if not usd:
            _log(f"{name}: not in catalog, skipped")
            continue
        code = _spawn_code(name, usd, spec.get("x", 0.0), spec.get("y", 0.0), spec.get("z", 0.0))
        for attempt in range(6):
            try:
                send_to_sim(code)
                _log(f"{name}: spawned")
                break
            except OSError as e:
                _log(f"{name}: attempt {attempt + 1} failed ({e}); retrying")
                time.sleep(5)


# --------------------------------------------------------------------------- #
# Composition: resolve env+robot/template -> scene + placed robots (server-side,
# so a sandbox runtime like NemoClaw can /open without the `claw` CLI). Mirrors
# the resolution logic in agents/openclaw/claw.
# --------------------------------------------------------------------------- #
def _yaml_load(path):
    try:
        import yaml
        with open(path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def robot_start_z(robot):
    """z (standing height) for a robot from the catalog."""
    cat = _yaml_load(CATALOG).get("categories", {}) or {}
    for grp in cat.values():
        if isinstance(grp, dict) and robot in grp:
            try:
                return float((grp[robot] or {}).get("start_z", 0.0))
            except Exception:
                return 0.0
    return 0.0


def list_templates():
    """environments (scene + anchors) + composite templates, for GET /templates."""
    envs = _yaml_load(TPL_DIR / "environments.yaml")
    composites = {}
    if TPL_DIR.exists():
        for p in sorted(TPL_DIR.glob("*.yaml")):
            if p.name == "environments.yaml":
                continue
            t = _yaml_load(p)
            composites[p.stem] = {"environment": t.get("environment"),
                                  "robots": [r.get("robot") for r in t.get("robots", [])]}
    return {"environments": envs, "templates": composites}


def resolve_open_spec(body):
    """Return (scene, [{robot,x,y,z}]) from {template} | {env,robot,anchor} | {scene,robot}."""
    envs = _yaml_load(TPL_DIR / "environments.yaml")

    def place(robot, env, anchor, override):
        anchors = (env or {}).get("anchors") or {}
        a = anchors.get(anchor or (env or {}).get("default_anchor"), {})
        z = override.get("z")
        return {"robot": robot,
                "x": float(override.get("x", a.get("x", 0.0))),
                "y": float(override.get("y", a.get("y", 0.0))),
                "z": robot_start_z(robot) if z in (None, "") else float(z)}

    tpl = body.get("template")
    if tpl:
        t = _yaml_load(TPL_DIR / (tpl if str(tpl).endswith(".yaml") else f"{tpl}.yaml"))
        if not t:
            raise ValueError(f"no such template: {tpl}")
        env = envs.get(t.get("environment"))
        if not env:
            raise ValueError(f"template '{tpl}' references unknown environment '{t.get('environment')}'")
        robots = [place(r["robot"], env, r.get("anchor"), r) for r in t.get("robots", [])]
        return env["scene"], robots

    env_name = body.get("env")
    robot = body.get("robot")
    if env_name:
        env = envs.get(env_name)
        if not env:
            raise ValueError(f"no such environment: {env_name}")
        robots = [place(robot, env, body.get("anchor"), {"z": body.get("z")})] if robot else []
        return env["scene"], robots

    scene = body.get("scene", "warehouse.usd")
    robots = []
    if robot:
        robots = [{"robot": robot, "x": float(body.get("x", 0.0)), "y": float(body.get("y", 0.0)),
                   "z": float(body.get("z", robot_start_z(robot)))}]
    return scene, robots


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {fmt % args}")

    def _respond(self, code, data):
        body = json.dumps(data, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n)) if n else {}

    # ---- GET ----
    def do_GET(self):
        if self.path == "/envs":
            self._respond(200, {"environments": ENVIRONMENTS, "count": len(ENVIRONMENTS)})
        elif self.path == "/scenes":
            self._respond(200, {"scenes": list_scenes()})
        elif self.path == "/robots":
            self._respond(200, {"robots": list_robots()})
        elif self.path == "/templates":
            self._respond(200, list_templates())
        elif self.path == "/status":
            running = job_running()
            info = {"running": running, "kind": job["kind"], "label": job["label"], "pid": job["pid"]}
            if running and job["start_time"]:
                el = time.time() - job["start_time"]
                info["elapsed_seconds"] = round(el)
                info["elapsed_human"] = f"{int(el//3600)}h {int((el%3600)//60)}m {int(el%60)}s"
            elif not running and job["label"]:
                info["status"] = "finished"
            self._respond(200, info)
        elif self.path.startswith("/logs"):
            n = 40
            if "?" in self.path:
                q = dict(p.split("=") for p in self.path.split("?")[1].split("&") if "=" in p)
                n = int(q.get("lines", 40))
            self._respond(200, {"lines": tail_log(n), "log_file": job.get("log_file")})
        elif self.path.startswith("/tuning"):
            backend = "rsl_rl"
            if "?" in self.path:
                q = dict(p.split("=") for p in self.path.split("?")[1].split("&") if "=" in p)
                backend = q.get("backend", "rsl_rl")
            f = POLICIES_DIR / f"{backend}.md"
            if not f.exists():
                self._respond(404, {"error": f"no tuning guide for '{backend}'",
                                    "available": sorted(p.stem for p in POLICIES_DIR.glob("*.md"))})
            else:
                self._respond(200, {"backend": backend, "knobs": HYDRA_KNOBS, "guide": f.read_text()})
        else:
            self._respond(404, {"error": f"unknown GET {self.path}"})

    # ---- POST ----
    def do_POST(self):
        try:
            body = self._body()
        except Exception as e:
            return self._respond(400, {"error": f"bad json: {e}"})

        if self.path == "/open":
            return self._open(body)
        if self.path == "/sim/launch":
            return self._sim_launch(body)
        if self.path == "/scene/load":
            return self._scene_load(body)
        if self.path == "/robot/spawn":
            return self._robot_spawn(body)
        if self.path == "/exec":
            return self._exec(body)
        if self.path in ("/train", "/play", "/eval"):
            return self._rl(self.path.lstrip("/"), body)
        if self.path == "/stop":
            return self._stop()
        self._respond(404, {"error": f"unknown POST {self.path}"})

    # ---- handlers ----
    def _guard_gpu(self):
        if job_running():
            self._respond(409, {"error": "a GPU job is already running",
                                "kind": job["kind"], "label": job["label"], "pid": job["pid"]})
            return False
        return True

    def _stop_job_inline(self):
        """Stop the active job WITHOUT writing a response (for internal reuse)."""
        if job_running():
            p = job["process"]
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(timeout=15)
            except subprocess.TimeoutExpired:
                p.kill()
            job["process"] = None

    def _open(self, body):
        """One-call open: resolve {template|env+robot|scene+robot} -> launch the sim
        and spawn the robot(s) server-side when READY. This is `claw open` moved into
        the server so a sandbox runtime (NemoClaw) can open a scene over plain HTTP."""
        try:
            scene, robots = resolve_open_spec(body)
        except ValueError as e:
            return self._respond(400, {"error": str(e)})
        # Single GPU job: (re)launch. Stop a running SIM first; refuse if a
        # training/eval job owns the GPU (caller must /stop it explicitly).
        if job_running():
            if not str(job["kind"]).startswith("sim"):
                return self._respond(409, {"error": "a non-sim GPU job is running; /stop it first",
                                           "kind": job["kind"], "label": job["label"]})
            self._stop_job_inline()
        return self._sim_launch({"scene": scene, "mode": "serve",
                                 "gui": bool(body.get("gui")), "spawn": robots})

    def _sim_launch(self, body):
        if not self._guard_gpu():
            return
        scene = body.get("scene", "warehouse.usd")
        # mode 'serve' (default) = persistent sim with the :8226 bridge enabled,
        # so /scene/load and /robot/spawn work afterwards. mode 'shot' = one-shot
        # render+screenshot via launch_warehouse.py (exits when done).
        mode = body.get("mode", "serve")
        launcher = SIM_DIR / "scripts" / ("serve_sim.py" if mode == "serve" else "launch_warehouse.py")
        if not launcher.exists():
            return self._respond(500, {"error": f"launcher missing: {launcher}"})
        py = str(ISAAC_SIM_INSTALL / "python.sh") if (ISAAC_SIM_INSTALL / "python.sh").exists() else LAB_PYTHON
        cmd = [py, str(launcher), "--scene", scene]
        if body.get("gui"):                     # open a visible window (needs DISPLAY)
            cmd.append("--gui")
        if mode != "serve":
            cmd.append("--no-build")
        info = start_job("sim", f"{scene}:{mode}", cmd, str(SIM_DIR / "scripts"))
        # Optional: spawn robots server-side once the sim is ready, so the caller
        # (claw open) can return immediately instead of blocking through bring-up.
        robots = body.get("spawn") or []
        if robots:
            threading.Thread(target=_spawn_when_ready, args=(robots, info["log_file"]),
                             daemon=True).start()
            info["spawn_scheduled"] = [r.get("robot") for r in robots]
        self._respond(200, info)

    def _scene_load(self, body):
        scene = body.get("scene")
        if not scene:
            return self._respond(400, {"error": "missing 'scene'"})
        scene_path = scene if os.path.isabs(scene) else str(SIM_DIR / "scenes" / scene)
        code = ("import omni.usd\n"
                f"omni.usd.get_context().open_stage(r'{scene_path}')\n"
                f"print('opened {scene_path}')\n")
        try:
            return self._respond(200, send_to_sim(code))
        except OSError as e:
            return self._respond(502, {"error": f"no running sim on {PY_SERVER_HOST}:{PY_SERVER_PORT}: {e}"})

    def _robot_spawn(self, body):
        name = body.get("robot")
        if not name:
            return self._respond(400, {"error": "missing 'robot'"})
        usd = resolve_robot_usd(name)
        if not usd:
            return self._respond(404, {"error": f"robot '{name}' not in catalog {CATALOG}"})
        x, y, z = body.get("x", 0.0), body.get("y", 0.0), body.get("z", 0.0)
        code = _spawn_code(name, usd, x, y, z)
        try:
            return self._respond(200, send_to_sim(code))
        except OSError as e:
            return self._respond(502, {"error": f"no running sim on {PY_SERVER_HOST}:{PY_SERVER_PORT}: {e}"})

    def _exec(self, body):
        code = body.get("code")
        if not code:
            return self._respond(400, {"error": "missing 'code'"})
        try:
            return self._respond(200, send_to_sim(code))
        except OSError as e:
            return self._respond(502, {"error": f"no running sim: {e}"})

    def _rl(self, kind, body):
        if not self._guard_gpu():
            return
        task = body.get("task")
        backend = body.get("backend", "rsl_rl")
        if not task:
            return self._respond(400, {"error": "missing 'task'"})
        if VALID_IDS and task not in VALID_IDS:
            return self._respond(400, {"error": f"unknown task {task}", "hint": "GET /envs"})
        table = TRAIN_SCRIPTS if kind == "train" else PLAY_SCRIPTS
        rel = table.get(backend)
        if not rel:
            return self._respond(400, {"error": f"backend '{backend}' not available for {kind}",
                                       "valid": sorted(table)})
        script = LAB_DIR / rel
        if not script.exists():
            return self._respond(500, {"error": f"script missing: {script}"})
        # GUI vs headless is selectable per request. Headless (default) trains fast
        # with many envs; --gui opens a visible window and defaults to a SMALL env
        # count so it's watchable (needs a DISPLAY on the server, like /sim/launch).
        gui = bool(body.get("gui"))
        cmd = [LAB_PYTHON, str(script), f"--task={task}"]
        if not gui:
            cmd.append("--headless")
        default_envs = (64 if gui else 4096) if kind == "train" else (16 if gui else 32)
        cmd.append(f"--num_envs={body.get('num_envs', default_envs)}")
        # skrl picks its config entry point from --algorithm (default PPO).
        # Special tasks register a non-PPO entry point (e.g. AMP dance ->
        # skrl_amp_cfg_entry_point), so pass --algorithm amp for those.
        if backend == "skrl" and body.get("algorithm"):
            cmd.append(f"--algorithm={body['algorithm']}")
        if body.get("max_iterations"):
            cmd.append(f"--max_iterations={body['max_iterations']}")
        if body.get("seed") is not None:
            cmd.append(f"--seed={body['seed']}")
        if body.get("checkpoint"):
            cmd.append(f"--checkpoint={body['checkpoint']}")
        # Advised hyperparameters. Friendly knobs (params{}) are mapped to Hydra
        # overrides for rsl_rl/cusrl; raw Hydra overrides (overrides[]) pass through
        # for any backend. Both land in train.py's hydra_args.
        applied, skipped = [], []
        if kind == "train":
            for k, v in (body.get("params") or {}).items():
                ov = knob_to_override(k, v) if backend in ("rsl_rl", "cusrl") else None
                (applied.append(ov) if ov else skipped.append(k))
            for ov in (body.get("overrides") or []):
                applied.append(str(ov))
            cmd += applied
        info = start_job(kind, task, cmd, str(LAB_DIR))
        if kind == "train":
            info["applied_overrides"] = applied
            if skipped:
                info["skipped_params"] = skipped  # unknown knob names, honestly reported
        self._respond(200, info)

    def _stop(self):
        if not job_running():
            return self._respond(200, {"status": "no job running"})
        p = job["process"]
        p.send_signal(signal.SIGTERM)
        try:
            p.wait(timeout=15)
        except subprocess.TimeoutExpired:
            p.kill()
        out = {"status": "stopped", "kind": job["kind"], "label": job["label"], "pid": job["pid"]}
        job["process"] = None
        self._respond(200, out)


def main():
    srv = HTTPServer((HOST, PORT), Handler)
    print(f"Isaac Control Server on {HOST}:{PORT}  (isaac-claw: {CLAW_DIR})")
    print(f"  envs={len(ENVIRONMENTS)}  scenes={list_scenes()}  sim-bridge={PY_SERVER_HOST}:{PY_SERVER_PORT}")
    print("  GET  /envs /scenes /robots /templates /status /logs /tuning")
    print("  POST /open /sim/launch /scene/load /robot/spawn /exec /train /play /eval /stop")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        if job_running():
            job["process"].terminate()
        srv.server_close()


if __name__ == "__main__":
    main()
