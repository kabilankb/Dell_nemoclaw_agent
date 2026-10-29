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
    GET  /training        structured metrics of the active (or last) run's log
                          (?log=<name> for an older run; reward curve, fall rate…)
    GET  /runs            past train/play logs, newest first (for replay)
    GET  /events?since=N  recent POSTs (tool calls) as they happen, for live UIs
    GET  /video/latest    newest play recording (mp4) from POST /record
    GET  /checkpoints?task=  trained runs of an Isaac Lab 3 task, most-trained first

    POST /sim/launch      {scene?}            launch Isaac Sim headless on a scene
    POST /scene/load      {scene}             load a USD into the RUNNING sim (port 8226)
    POST /robot/spawn     {robot, x?,y?,z?}   spawn a catalog robot into the running sim
    POST /exec            {code}              run arbitrary python in the running sim
    POST /train           {task, backend, num_envs?, max_iterations?, seed?}
    POST /play            {task, backend?, checkpoint?, num_envs?}
    POST /eval            {task, backend?, checkpoint?, num_envs?}
    POST /record          {task, checkpoint?, steps?}  headless play that records an mp4
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
import re
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
def _default_lab_python():
    for base in ("~/miniforge3", "~/miniconda3"):
        p = os.path.expanduser(f"{base}/envs/env_isaaclab/bin/python")
        if os.path.exists(p):
            return p
    return os.path.expanduser("~/miniforge3/envs/env_isaaclab/bin/python")


LAB_PYTHON = os.environ.get("ISAAC_LAB_PYTHON") or _default_lab_python()
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

# Isaac Lab 3 checkout (uv) for tasks registered with "launcher": "isaaclab3"
# (e.g. the MicroDuck contrib tasks). Launched via its `isaaclab` CLI.
LAB3_DIR = Path(os.environ.get("ISAAC_LAB3_DIR", os.path.expanduser("~/IsaacLab-develop")))
LAB3_PYTHON = LAB3_DIR / ".venv" / "bin" / "python"
LAB3_LAUNCH = LAB_DIR / "scripts" / "isaaclab3_launch.py"
# Viewer for gui=true runs: "viser" (web, shown in web/console) or "newton_gl" (desktop window).
LAB3_VIZ = os.environ.get("ISAAC_LAB3_VIZ", "viser")
VISER_PORT = int(os.environ.get("ISAAC_VISER_PORT", "8012"))

# Optional LD_PRELOAD fix carried from robot_lab (libgomp on aarch64). Set "" to skip.
LD_PRELOAD = os.environ.get("ISAAC_LD_PRELOAD",
                            "/lib/aarch64-linux-gnu/libgomp.so.1")
if LD_PRELOAD and not os.path.exists(LD_PRELOAD):   # e.g. x86_64 hosts
    LD_PRELOAD = ""

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


def _python_has(python, module):
    try:
        return subprocess.run(
            [python, "-c", f"import importlib.util,sys; sys.exit(importlib.util.find_spec('{module}') is None)"],
            capture_output=True, timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def mark_availability(envs):
    """Tag each task with whether THIS host can run it, so the model is never offered
    a task that dies at launch (robot_lab tasks need ISAAC_LAB_PYTHON with robot_lab
    installed; isaaclab3 tasks need the Isaac Lab 3 venv)."""
    lab3_ok = LAB3_PYTHON.exists()
    lab_ok = os.path.exists(LAB_PYTHON)
    pkgs = {}
    for e in envs:
        if e.get("launcher") == "isaaclab3":
            ok, why = lab3_ok, f"Isaac Lab 3 venv missing: {LAB3_PYTHON}"
        else:
            pkg = "leisaac" if e.get("source") == "leisaac" else "robot_lab"
            if pkg not in pkgs:
                pkgs[pkg] = lab_ok and _python_has(LAB_PYTHON, pkg)
            ok = pkgs[pkg]
            why = (f"'{pkg}' is not installed in {LAB_PYTHON}" if lab_ok
                   else f"ISAAC_LAB_PYTHON not found: {LAB_PYTHON}")
        e["available"] = ok
        if not ok:
            e["unavailable_reason"] = why
    return envs


ENVIRONMENTS = mark_availability(load_envs())
VALID_IDS = {e["id"] for e in ENVIRONMENTS}
ENV_BY_ID = {e["id"]: e for e in ENVIRONMENTS}

# Recent POSTs, so a UI can show "calling isaac__train_task…" while an agent turn runs.
EVENTS = []
_event_seq = [0]


def record_event(path, body):
    _event_seq[0] += 1
    keep = {k: body[k] for k in ("task", "env", "robot", "gui", "num_envs", "max_iterations",
                                 "params", "checkpoint") if k in body}
    EVENTS.append({"seq": _event_seq[0], "t": time.time(), "path": path, "args": keep})
    del EVENTS[:-200]

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


class LaunchError(RuntimeError):
    pass


def start_job(kind, label, cmd, cwd):
    log_file = LOG_DIR / f"{kind}_{label}_{int(time.time())}.log".replace("/", "_")
    env = os.environ.copy()
    if LD_PRELOAD:
        env["LD_PRELOAD"] = LD_PRELOAD
    env.setdefault("ISAAC_CLAW_DIR", str(CLAW_DIR))
    with open(log_file, "w") as lf:
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=lf,
                                    stderr=subprocess.STDOUT)
        except OSError as e:   # e.g. a python path that doesn't exist on this host
            lf.write(f"failed to launch {cmd[0]}: {e}\n")
            raise LaunchError(f"could not launch {cmd[0]}: {e.strerror or e}") from e
    job.update(process=proc, pid=proc.pid, kind=kind, label=label,
               start_time=time.time(), log_file=str(log_file))
    return {"status": "started", "kind": kind, "label": label,
            "pid": proc.pid, "log_file": str(log_file)}


# --------------------------------------------------------------------------- #
# Training-log parsing (rsl_rl console output) for GET /training
# --------------------------------------------------------------------------- #
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ITER = re.compile(r"Learning iteration (\d+)/(\d+)")
_REWARD = re.compile(r"^\s*Mean reward:\s*(-?[\d.]+)", re.M)
_EPLEN = re.compile(r"^\s*Mean episode length:\s*(-?[\d.]+)", re.M)
_TERM = re.compile(r"Episode_Termination/(\w+):\s*(-?[\d.]+)")
_RTERM = re.compile(r"Episode_Reward/(\w+):\s*(-?[\d.]+)")
_ETA = re.compile(r"ETA:\s*([\d:]+)")
_ITER_TIME = re.compile(r"Iteration time:\s*([\d.]+)s")
_STD = re.compile(r"Mean action std:\s*([\d.]+)")
# Terminations that mean "the robot fell" (anything but running out of time).
_FALL_TERMS = ("fell_over", "base_contact", "illegal_contact", "bad_orientation", "base_height")


def list_runs():
    logs = sorted(LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
    # skip stubs from launches that died before writing anything useful
    return [p for p in logs if p.name.startswith(("train_", "play_", "record_"))
            and p.stat().st_size > 2000]


def parse_training_log(path):
    text = _ANSI.sub("", Path(path).read_text(errors="replace"))
    iters = _ITER.findall(text)
    rewards = [float(x) for x in _REWARD.findall(text)]
    terms = dict(_TERM.findall(text))       # last value of each term wins
    reward_terms = dict(_RTERM.findall(text))
    fell = sum(float(terms[k]) for k in _FALL_TERMS if k in terms) if terms else None
    pick = lambda rx: (rx.findall(text) or [None])[-1]
    out = {
        "log_file": Path(path).name,
        # log names are <kind>_<task>_<unix time>.log (see start_job)
        "kind": Path(path).name.split("_", 1)[0],
        "task": Path(path).stem.split("_", 1)[-1].rsplit("_", 1)[0],
        "iteration": int(iters[-1][0]) if iters else None,
        "max_iterations": int(iters[-1][1]) if iters else None,
        "mean_reward": rewards[-1] if rewards else None,
        "reward_history": rewards[-400:],
        "mean_episode_length": float(pick(_EPLEN)) if pick(_EPLEN) else None,
        "fell_over": round(fell, 4) if fell is not None else None,
        "terminations": {k: float(v) for k, v in terms.items()},
        "reward_terms": {k: float(v) for k, v in reward_terms.items()},
        "action_std": float(pick(_STD)) if pick(_STD) else None,
        "eta": pick(_ETA),
        "iteration_time_s": float(pick(_ITER_TIME)) if pick(_ITER_TIME) else None,
        "finished": "Training time:" in text,
    }
    # Viewer clients dropping their websocket log harmless tracebacks; only surface
    # the others (a real crash ends the log with one).
    blocks = [b for b in text.split("Traceback (most recent call last):")[1:]
              if "/websockets/" not in b]
    if blocks:
        out["error"] = ("Traceback (most recent call last):" + blocks[-1])[-1500:]
    elif text.startswith("failed to launch"):
        out["error"] = text.strip()[:500]
    return out


def lab3_checkpoints(task):
    """Isaac Lab 3 runs of `task` (matched via each run's run.json), most-trained first.
    `--checkpoint latest` would pick the NEWEST run, which is often a stub from an
    aborted run holding only model_0.pt — an untrained policy."""
    runs = []
    for rj in (LAB3_DIR / "logs").glob("*/*/*/run.json"):
        try:
            if json.loads(rj.read_text()).get("task") != task:
                continue
        except (OSError, json.JSONDecodeError):
            continue
        models = [(int(m.stem.split("_")[1]), m) for m in rj.parent.glob("model_*.pt")
                  if m.stem.split("_")[1].isdigit()]
        if models:
            it, path = max(models)
            runs.append({"run": rj.parent.name, "iteration": it, "checkpoint": str(path),
                         "mtime": path.stat().st_mtime})
    return sorted(runs, key=lambda r: (r["iteration"], r["mtime"]), reverse=True)


def resolve_checkpoint(task, requested):
    """'best' (default) -> most-trained run's last model; anything else passes through."""
    if requested and requested != "best":
        return requested
    runs = lab3_checkpoints(task)
    return runs[0]["checkpoint"] if runs else "latest"


def known_reward_terms(task):
    """Reward term names this task has logged before (Episode_Reward/<term>), or None if
    it never ran here. Used to drop reward_<term> knobs that would crash the launch."""
    for lf in sorted(LOG_DIR.glob(f"train_{task}_*.log"), key=lambda p: p.stat().st_mtime, reverse=True):
        terms = set(_RTERM_NAME.findall(lf.read_text(errors="replace")))
        if terms:
            return terms
    return None


_RTERM_NAME = re.compile(r"Episode_Reward/(\w+):")


def latest_video():
    roots = [LAB3_DIR / "logs", LAB_DIR / "logs"]
    vids = [p for r in roots if r.exists() for p in r.rglob("*.mp4")]
    return max(vids, key=lambda p: p.stat().st_mtime) if vids else None


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
        path, _, qs = self.path.partition("?")
        q = dict(p.split("=", 1) for p in qs.split("&") if "=" in p)
        if self.path == "/envs":
            avail = sum(1 for e in ENVIRONMENTS if e.get("available"))
            self._respond(200, {"environments": ENVIRONMENTS, "count": len(ENVIRONMENTS),
                                "available": avail})
        elif path == "/training":
            name = q.get("log")
            lf = (LOG_DIR / Path(name).name) if name else (
                Path(job["log_file"]) if job.get("log_file") else (list_runs() or [None])[0])
            if not lf or not Path(lf).exists():
                return self._respond(200, {"running": False, "metrics": None})
            m = parse_training_log(lf)
            running = job_running() and str(lf) == job.get("log_file")
            out = {"running": running, "kind": job["kind"] if running else None,
                   "label": job["label"] if running else m.get("task"), "metrics": m}
            if running and job["start_time"]:
                out["elapsed_seconds"] = round(time.time() - job["start_time"])
            self._respond(200, out)
        elif path == "/checkpoints":
            self._respond(200, {"task": q.get("task"), "runs": lab3_checkpoints(q.get("task"))[:20]})
        elif path == "/runs":
            self._respond(200, {"runs": [{"log": p.name, "mtime": p.stat().st_mtime,
                                          "size": p.stat().st_size} for p in list_runs()[:50]]})
        elif path == "/events":
            since = int(q.get("since", 0) or 0)
            self._respond(200, {"seq": _event_seq[0],
                                "events": [e for e in EVENTS if e["seq"] > since]})
        elif path == "/video/latest":
            v = latest_video()
            if not v:
                return self._respond(404, {"error": "no recorded video yet; POST /record first"})
            data = v.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Video-Path", str(v))
            self.send_header("X-Video-Mtime", str(int(v.stat().st_mtime)))
            self.end_headers()
            self.wfile.write(data)
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

        record_event(self.path, body if isinstance(body, dict) else {})
        try:
            return self._post(body)
        except LaunchError as e:
            return self._respond(503, {"error": str(e)})
        except Exception as e:   # never drop the connection without a reply
            return self._respond(500, {"error": f"{type(e).__name__}: {e}"})

    def _post(self, body):
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
        if self.path == "/record":
            return self._record(body)
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
        spec = ENV_BY_ID.get(task, {})
        substituted = None
        if spec and not spec.get("available", True):
            alt = spec.get("alternative")
            if not (alt and ENV_BY_ID.get(alt, {}).get("available")):
                return self._respond(503, {"error": f"task {task} can't run on this host: "
                                                    f"{spec.get('unavailable_reason')}",
                                           "hint": "GET /envs lists the runnable tasks"})
            # same robot, same terrain, on the stack this host has (robot_lab -> Isaac Lab 3)
            substituted, task, spec = task, alt, ENV_BY_ID[alt]
        if spec.get("launcher") == "isaaclab3":
            return self._rl_isaaclab3(kind, task, body, substituted)
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

    def _rl_isaaclab3(self, kind, task, body, substituted=None):
        """Isaac Lab 3 tasks: `isaaclab {train|play} --rl_library rsl_rl ...` from
        $ISAAC_LAB3_DIR via isaaclab3_launch.py. Headless is the CLI default; gui adds
        the $ISAAC_LAB3_VIZ viewer (viser web viewer by default). eval has no Lab 3
        equivalent here, so it runs play."""
        if not LAB3_PYTHON.exists():
            return self._respond(500, {"error": f"Isaac Lab 3 python missing: {LAB3_PYTHON}",
                                       "hint": "set ISAAC_LAB3_DIR to an Isaac Lab 3 uv checkout"})
        gui = bool(body.get("gui"))
        viz = body.get("viz") or LAB3_VIZ
        verb = "train" if kind == "train" else "play"
        cmd = [str(LAB3_PYTHON), str(LAB3_LAUNCH), verb, "--rl_library", "rsl_rl", f"--task={task}"]
        default_envs = (64 if gui else 4096) if kind == "train" else (16 if gui else 32)
        cmd.append(f"--num_envs={body.get('num_envs', default_envs)}")
        if gui:
            cmd.append(f"--viz={viz}")
        if kind == "train":
            # Lab 3 defaults are huge (MicroDuck: 50000 its) — always bound the run.
            cmd.append(f"--max_iterations={body.get('max_iterations', 1500)}")
        if body.get("seed") is not None:
            cmd.append(f"--seed={body['seed']}")
        if kind != "train":
            cmd.append(f"--checkpoint={resolve_checkpoint(task, body.get('checkpoint'))}")
        elif body.get("checkpoint"):   # resume training from a checkpoint
            cmd.append(f"--checkpoint={resolve_checkpoint(task, body.get('checkpoint'))}")
        applied, skipped = list(ENV_BY_ID[task].get("default_overrides", [])), []
        terms = known_reward_terms(task) if kind == "train" else None
        if kind == "train":
            for k, v in (body.get("params") or {}).items():
                if k.startswith("reward_") and terms is not None and k[len("reward_"):] not in terms:
                    skipped.append(k)   # unknown term: Hydra would abort the whole run
                    continue
                ov = knob_to_override(k, v)
                (applied.append(ov) if ov else skipped.append(k))
            applied += [str(ov) for ov in (body.get("overrides") or [])]
        cmd += applied
        os.environ.setdefault("OMNI_KIT_ACCEPT_EULA", "YES")
        info = start_job(kind, task, cmd, str(LAB3_DIR))
        info["launcher"] = "isaaclab3"
        if substituted:
            info["note"] = f"{substituted} isn't installed here; running {task} (same robot, Isaac Lab 3)"
        if gui and viz == "viser":
            info["viewer_url"] = f"http://localhost:{VISER_PORT}"
        if kind == "train":
            info["applied_overrides"] = applied
            if skipped:
                info["skipped_params"] = skipped
                if terms:
                    info["valid_reward_terms"] = sorted(terms)
        self._respond(200, info)

    def _record(self, body):
        """Headless play of a trained policy that writes an mp4 (Isaac Lab 3 --video),
        fetched afterwards from GET /video/latest — e.g. for a vision-model critique."""
        if not self._guard_gpu():
            return
        task = body.get("task")
        if ENV_BY_ID.get(task, {}).get("launcher") != "isaaclab3":
            return self._respond(400, {"error": "recording needs an Isaac Lab 3 task",
                                       "valid": [e["id"] for e in ENVIRONMENTS
                                                 if e.get("launcher") == "isaaclab3"]})
        steps = int(body.get("steps", 300))
        cmd = [str(LAB3_PYTHON), str(LAB3_LAUNCH), "play", "--rl_library", "rsl_rl",
               f"--task={task}", f"--num_envs={body.get('num_envs', 4)}",
               f"--checkpoint={resolve_checkpoint(task, body.get('checkpoint'))}",
               "--video", f"--video_length={steps}"]
        cmd += list(ENV_BY_ID[task].get("default_overrides", []))
        os.environ.setdefault("OMNI_KIT_ACCEPT_EULA", "YES")
        info = start_job("record", task, cmd, str(LAB3_DIR))
        info["video_url"] = "/video/latest"
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
