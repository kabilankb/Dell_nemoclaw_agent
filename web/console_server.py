#!/usr/bin/env python3
"""isaac-claw web console — one page for the Nebius key, the live Isaac view, and
the claw (NemoClaw sandbox agent) chat.

    python3 web/console_server.py            # -> http://localhost:8800

Stdlib only, like isaac_control_server.py. Binds 127.0.0.1 because it can read
and write the Nebius key; it never returns the key, only a masked hint.

    GET  /                  the console page (web/console/index.html)
    GET  /api/health        which services are up (control server, sandbox, viewer)
    GET  /api/key           {configured, hint}
    POST /api/key {key}     verify against Token Factory, then save to ~/.openclaw/.env
    GET  /api/training[?log=]  metrics of the active run, or of a past run (replay)
    GET  /api/runs          past runs for the replay picker
    GET  /api/models        Token Factory chat models + the sandbox's active one
    POST /api/model {model} switch the sandbox model (nemoclaw inference set, ~45 s)
    POST /api/stop          stop the running GPU job (proxied to the control server)
    POST /api/chat {message}  start one agent turn in the NemoClaw sandbox -> {id}
    POST /api/critique {task?}  record a play clip, ask the Nebius vision model -> {id}
    GET  /api/job/<id>      progress of a chat/critique: events so far, then the result
    GET  /api/video         the clip the last critique looked at
"""
from __future__ import annotations

import base64
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import uuid
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLAW_DIR = Path(os.environ.get("ISAAC_CLAW_DIR", HERE.parent))
PAGE = HERE / "console" / "index.html"
LOG_DIR = CLAW_DIR / "isaac_sim" / "_control_logs"

HOST = os.environ.get("CONSOLE_HOST", "127.0.0.1")
PORT = int(os.environ.get("CONSOLE_PORT", "8800"))
# The control server (and the GPU) can live elsewhere, e.g. a Nebius AI Cloud VM
# reached through an SSH tunnel (demo.sh up --gpu-host user@vm).
CONTROL = os.environ.get("ISAAC_CONTROL_URL",
                         f"http://127.0.0.1:{os.environ.get('ISAAC_CONTROL_PORT', '5561')}")
VISER_PORT = int(os.environ.get("ISAAC_VISER_PORT", "8012"))

NEBIUS_URL = os.environ.get("NEBIUS_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
ENV_FILE = Path(os.environ.get("NEBIUS_ENV_FILE", "~/.openclaw/.env")).expanduser()

SANDBOX = os.environ.get("NEMOCLAW_SANDBOX", "isaacsim")
GATEWAY_PORT = os.environ.get("NEMOCLAW_GATEWAY_PORT", "8090")
CHAT_TIMEOUT = int(os.environ.get("CONSOLE_CHAT_TIMEOUT", "280"))
VISION_MODEL = os.environ.get("NEBIUS_VISION_MODEL", "nvidia/Nemotron-3.5-Super-VL")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def http_up(port: int) -> bool:
    """HTTP probe — a bare TCP connect makes viser's websocket server log a traceback."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1) as r:
            return r.status < 500
    except (urllib.error.URLError, OSError):
        return False


def control(method: str, path: str, body: dict | None = None, timeout: float = 5):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(CONTROL + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def find_exe(name: str) -> str | None:
    for d in os.environ.get("PATH", "").split(":") + [str(Path.home() / ".local/bin")]:
        p = Path(d) / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def sandbox_container() -> str | None:
    try:
        out = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for name in out.split():
        if re.match(rf"^openshell-([a-z0-9_-]+--)?{re.escape(SANDBOX)}-", name):
            return name
    return None


def sandbox_inference() -> dict:
    """The sandbox's onboarded model/provider/endpoint (no credentials) from
    NemoClaw's registry, ~/.nemoclaw/gateways/<port>/sandboxes.json."""
    reg = Path.home() / ".nemoclaw" / "gateways" / GATEWAY_PORT / "sandboxes.json"
    try:
        sb = json.loads(reg.read_text()).get("sandboxes", {}).get(SANDBOX, {})
    except (OSError, json.JSONDecodeError):
        return {}
    prov = sb.get("modelSelectionProvenance") or {}
    return {"model": sb.get("model"), "provider": sb.get("provider"),
            "endpoint": sb.get("endpointUrl"), "api": prov.get("apiFamily")}


# --- key file -----------------------------------------------------------------
def read_key() -> str:
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("NEBIUS_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def write_key(key: str) -> None:
    set_env_var("NEBIUS_API_KEY", key)


def key_hint(key: str) -> str:
    return f"…{key[-4:]}" if len(key) >= 8 else ""


def set_env_var(name: str, value: str) -> None:
    """Upsert NAME=value in ~/.openclaw/.env (mode 600); demo.sh reads it on restart."""
    lines = [l for l in (ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else [])
             if not l.startswith(f"{name}=")]
    lines.append(f"{name}={value}")
    ENV_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(ENV_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(ENV_FILE, 0o600)


def nebius_models(key: str) -> list[str]:
    req = urllib.request.Request(NEBIUS_URL.rstrip("/") + "/models",
                                 headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.loads(r.read())
    ids = sorted(m["id"] for m in data.get("data", []))
    return [i for i in ids if "nemotron" in i.lower() or i.lower().startswith("nvidia/")]


def chat_models(key: str) -> list[str]:
    """Nemotron text models the sandbox can switch to (the VL one is for the critique)."""
    return [m for m in nebius_models(key) if "nemotron" in m.lower() and "-vl" not in m.lower()]


def set_sandbox_model(model: str, key: str | None = None) -> dict:
    """Re-route the sandbox's inference (and, with `key`, its credential) through
    `nemoclaw inference set`. Restarts the agent gateway in the sandbox (~45 s)."""
    exe = find_exe("nemoclaw")
    if not exe:
        return {"error": "nemoclaw CLI not found"}
    key = key or read_key()
    env = dict(os.environ, NEMOCLAW_GATEWAY_PORT=GATEWAY_PORT, COMPATIBLE_API_KEY=key)
    try:
        proc = subprocess.run(
            [exe, "inference", "set", "--provider", "compatible-endpoint", "--model", model,
             "--sandbox", SANDBOX, "--endpoint-url", NEBIUS_URL,
             "--credential-env", "COMPATIBLE_API_KEY", "--inference-api", "openai-completions"],
            capture_output=True, text=True, env=env, timeout=240)
    except subprocess.TimeoutExpired:
        return {"error": "nemoclaw inference set timed out"}
    out_text = proc.stdout + proc.stderr
    if sandbox_inference().get("model") != model:
        return {"error": "nemoclaw inference set failed",
                "detail": out_text[-600:].replace(key, "…") if key else ""}
    set_env_var("NEBIUS_MODEL", model)
    out = {"ok": True, "model": model}
    # NemoClaw 0.0.137 often reports a gateway "health timeout" after re-routing even
    # though the route is committed and the next agent turn runs on the new model.
    if proc.returncode != 0 and "route and config were updated" in out_text:
        out["warning"] = "NemoClaw's restart health check timed out; the new model is active."
    return out


# --- claw chat ----------------------------------------------------------------
def chat_turn(_jid: str, message: str, session: str = "") -> dict:
    exe = find_exe("nemoclaw")
    if not exe:
        return {"error": "nemoclaw CLI not found (install NemoClaw first)"}
    if not sandbox_container():
        return {"error": f"sandbox '{SANDBOX}' is not running",
                "hint": f"nemoclaw {SANDBOX} start"}
    b64 = base64.b64encode(message.encode()).decode()
    # One session per console page load: the shared main session remembers every
    # earlier failure, and the model then answers from that memory instead of tools.
    sid = re.sub(r"[^a-z0-9-]", "", session.lower())[:40]
    key = f" --session-key agent:main:console-{sid}" if sid else ""
    inner = (f"echo {b64} | base64 -d > /tmp/_console_msg_{sid} && "
             f"openclaw agent --agent main{key} --json -m \"$(cat /tmp/_console_msg_{sid})\"")
    env = dict(os.environ, NEMOCLAW_GATEWAY_PORT=GATEWAY_PORT)
    t0 = time.time()
    try:
        proc = subprocess.run(
            [exe, SANDBOX, "exec", "--no-tty", "--timeout", str(CHAT_TIMEOUT), "--",
             "bash", "-lc", inner],
            capture_output=True, text=True, env=env, timeout=CHAT_TIMEOUT + 30)
    except subprocess.TimeoutExpired:
        return {"error": f"agent turn timed out after {CHAT_TIMEOUT}s"}
    elapsed = round(time.time() - t0, 1)
    raw = proc.stdout.strip()
    start = raw.find("{")
    try:
        data = json.loads(raw[start:]) if start >= 0 else {}
    except json.JSONDecodeError:
        data = {}
    meta = _find_key(data, "finalAssistantVisibleText")
    if not meta:
        tail = (proc.stderr or raw)[-800:]
        return {"error": "agent returned no reply", "detail": tail, "elapsed_s": elapsed}
    trace = meta.get("executionTrace") or {}
    tools = (meta.get("toolSummary") or {}).get("tools") or []
    return {
        "reply": meta.get("finalAssistantVisibleText", ""),
        "model": trace.get("winnerModel"),
        "fallback_used": trace.get("fallbackUsed"),
        "tools": tools,
        "elapsed_s": elapsed,
    }


# --- background jobs (chat turns, critiques) ------------------------------------
JOBS: dict[str, dict] = {}

# control-server POST path -> the isaac__ tool that sends it
TOOL_FOR_PATH = {"/train": "train_task", "/play": "play_policy", "/eval": "eval_policy",
                 "/stop": "stop_training", "/open": "open_scene"}


def control_seq() -> int:
    try:
        return control("GET", "/events?since=999999999").get("seq", 0)
    except (urllib.error.URLError, OSError):
        return 0


def start_job(kind: str, fn, *args) -> str:
    jid = uuid.uuid4().hex[:12]
    JOBS[jid] = {"kind": kind, "done": False, "events": [], "started": time.time(),
                 "seq": control_seq()}

    def run():
        try:
            JOBS[jid]["result"] = fn(jid, *args)
        except Exception as e:  # surfaced in the chat, never a silent hang
            JOBS[jid]["result"] = {"error": f"{type(e).__name__}: {e}"}
        JOBS[jid]["done"] = True
    threading.Thread(target=run, daemon=True).start()
    for old in [k for k, v in JOBS.items() if v["done"] and time.time() - v["started"] > 3600]:
        JOBS.pop(old, None)
    return jid


def job_progress(jid: str) -> dict:
    j = JOBS.get(jid)
    if not j:
        return {"error": "unknown job"}
    if not j["done"]:  # pick up tool calls the agent has made so far
        try:
            evs = control("GET", f"/events?since={j['seq']}").get("events", [])
        except (urllib.error.URLError, OSError):
            evs = []
        for e in evs:
            j["seq"] = max(j["seq"], e["seq"])
            if e["path"] in TOOL_FOR_PATH:
                args = e.get("args") or {}
                what = args.get("task") or args.get("env") or ""
                j["events"].append(f"isaac__{TOOL_FOR_PATH[e['path']]}" + (f" · {what}" if what else ""))
    out = {"done": j["done"], "events": j["events"], "elapsed_s": round(time.time() - j["started"], 1)}
    if j["done"]:
        out["result"] = j.get("result")
    return out


def note(jid: str, text: str) -> None:
    JOBS[jid]["events"].append(text)


def critique(jid: str, task: str, steps: int) -> dict:
    """Record a short clip of the trained policy, then show frames to the vision model."""
    key = read_key()
    if not key:
        return {"error": "no Nebius key saved"}
    st = control("GET", "/status")
    if st.get("running"):
        return {"error": f"the GPU is busy ({st.get('kind')} {st.get('label')}); stop it first"}
    note(jid, f"recording {steps} steps of {task} (headless)")
    r = control("POST", "/record", {"task": task, "steps": steps}, timeout=30)
    if r.get("error"):
        return {"error": r["error"]}
    t0 = time.time()
    while time.time() - t0 < 600:
        time.sleep(2)
        if not control("GET", "/status").get("running"):
            break
    req = urllib.request.Request(CONTROL + "/video/latest")
    with urllib.request.urlopen(req, timeout=60) as resp:
        if int(resp.headers.get("X-Video-Mtime", "0")) < t0 - 5:
            return {"error": "the recording produced no new video; see the run log"}
        video = resp.read()
    VIDEO_CACHE["mp4"] = video
    note(jid, "extracting frames")
    with tempfile.TemporaryDirectory() as d:
        mp4 = Path(d) / "clip.mp4"
        mp4.write_bytes(video)
        ffmpeg = find_exe("ffmpeg") or "ffmpeg"
        subprocess.run([ffmpeg, "-v", "error", "-i", str(mp4), "-vf", "fps=1.5,scale=960:-1",
                        "-frames:v", "6", str(Path(d) / "f_%02d.jpg")], check=True, timeout=60)
        frames = sorted(Path(d).glob("f_*.jpg"))
        content = [{"type": "text", "text": (
            f"These {len(frames)} frames, in time order, come from Isaac Lab playing back a trained "
            f"locomotion policy for the task '{task}'. Arrows above the robot are the commanded "
            "velocity; ignore them and any markers. Judge the gait in at most 4 short bullets: "
            "is it walking, shuffling, stumbling or falling; what looks wrong (posture, foot "
            "placement, balance, drift); and one concrete training change (a reward term or "
            "PPO knob) that would fix the worst problem.")}]
        for f in frames:
            content.append({"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(f.read_bytes()).decode()}})
    note(jid, f"asking {VISION_MODEL.split('/')[-1]} on Nebius ({len(frames)} frames)")
    body = {"model": VISION_MODEL, "messages": [{"role": "user", "content": content}],
            "max_tokens": 800, "chat_template_kwargs": {"enable_thinking": False}}
    t1 = time.time()
    req = urllib.request.Request(NEBIUS_URL.rstrip("/") + "/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        out = json.loads(resp.read())
    return {"reply": out["choices"][0]["message"].get("content") or "(no answer)",
            "model": VISION_MODEL, "tools": [], "frames": len(frames),
            "elapsed_s": round(time.time() - t1, 1), "video": "/api/video"}


VIDEO_CACHE: dict[str, bytes] = {}
MODEL_SWITCH = {"busy": False}


def _find_key(obj, key):
    """Return the dict that holds `key` anywhere inside a parsed JSON envelope."""
    if isinstance(obj, dict):
        if key in obj:
            return obj
        for v in obj.values():
            hit = _find_key(v, key)
            if hit:
                return hit
    elif isinstance(obj, list):
        for v in obj:
            hit = _find_key(v, key)
            if hit:
                return hit
    return None


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _respond(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/health":
            key = read_key()
            self._respond(200, {
                "control_server": port_open(int(CONTROL.rsplit(":", 1)[1])),
                "sandbox": bool(sandbox_container()),
                "sandbox_name": SANDBOX,
                "viewer": http_up(VISER_PORT),
                "viewer_url": f"http://localhost:{VISER_PORT}",
                "key_configured": bool(key),
                "key_hint": key_hint(key),
                "inference": sandbox_inference(),
            })
        elif self.path == "/api/key":
            key = read_key()
            self._respond(200, {"configured": bool(key), "hint": key_hint(key),
                                "endpoint": NEBIUS_URL})
        elif self.path.startswith("/api/training"):
            qs = self.path.partition("?")[2]
            try:
                self._respond(200, control("GET", "/training" + (f"?{qs}" if qs else "")))
            except (urllib.error.URLError, OSError) as e:
                self._respond(200, {"error": f"control server unreachable: {e}"})
        elif self.path == "/api/runs":
            try:
                self._respond(200, control("GET", "/runs"))
            except (urllib.error.URLError, OSError) as e:
                self._respond(200, {"runs": [], "error": str(e)})
        elif self.path == "/api/models":
            key = read_key()
            try:
                models = chat_models(key) if key else []
            except (urllib.error.URLError, OSError):
                models = []
            active = sandbox_inference().get("model")
            if active and active not in models:
                models.append(active)
            self._respond(200, {"models": models, "active": active, "switching": MODEL_SWITCH["busy"]})
        elif self.path.startswith("/api/job/"):
            self._respond(200, job_progress(self.path.rsplit("/", 1)[1]))
        elif self.path == "/api/video":
            data = VIDEO_CACHE.get("mp4")
            if not data:
                return self._respond(404, {"error": "no clip yet"})
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        body = self._body()
        if self.path == "/api/key":
            key = str(body.get("key", "")).strip()
            if not key:
                return self._respond(400, {"error": "empty key"})
            try:
                models = nebius_models(key)
            except urllib.error.HTTPError as e:
                return self._respond(400, {"error": f"Token Factory rejected the key (HTTP {e.code})"})
            except (urllib.error.URLError, OSError) as e:
                return self._respond(502, {"error": f"could not reach Token Factory: {e}"})
            write_key(key)
            out = {"ok": True, "hint": key_hint(key), "models": models, "saved_to": str(ENV_FILE)}
            # Rotation: the sandbox holds its own copy of the credential, so push the
            # new key into it too (same model), or the claw keeps using the old one.
            active = sandbox_inference().get("model")
            if active and sandbox_container() and body.get("apply_to_sandbox", True):
                r = set_sandbox_model(active, key)
                out["sandbox_updated"] = bool(r.get("ok"))
                if r.get("error"):
                    out["sandbox_error"] = r["error"]
            self._respond(200, out)
        elif self.path == "/api/stop":
            try:
                self._respond(200, control("POST", "/stop", {}, timeout=30))
            except (urllib.error.URLError, OSError) as e:
                self._respond(502, {"error": f"control server unreachable: {e}"})
        elif self.path == "/api/chat":
            msg = str(body.get("message", "")).strip()
            if not msg:
                return self._respond(400, {"error": "empty message"})
            self._respond(200, {"id": start_job("chat", chat_turn, msg, str(body.get("session", "")))})
        elif self.path == "/api/critique":
            task = str(body.get("task") or "IsaacContrib-Velocity-Flat-MicroDuck")
            self._respond(200, {"id": start_job("critique", critique, task, int(body.get("steps", 300)))})
        elif self.path == "/api/model":
            model = str(body.get("model", "")).strip()
            if not model:
                return self._respond(400, {"error": "missing model"})
            if MODEL_SWITCH["busy"]:
                return self._respond(409, {"error": "a model switch is already running"})
            MODEL_SWITCH["busy"] = True
            try:
                self._respond(200, set_sandbox_model(model))
            finally:
                MODEL_SWITCH["busy"] = False
        else:
            self._respond(404, {"error": "not found"})


def main():
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"isaac-claw console on http://{HOST}:{PORT}  (control {CONTROL}, sandbox {SANDBOX}, "
          f"viewer :{VISER_PORT})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
