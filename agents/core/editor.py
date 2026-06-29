"""Visual workflow editor — a drag-and-drop node canvas for the agent graph.

Like Isaac Sim's Action Graph / OmniGraph, but the nodes are *agents*: drag a
worker (L1-L4) or the Atlas supervisor onto the canvas, wire them up, Save, then
type a command and hit Run to dispatch the action through the graph you built.

This is a standalone FastAPI app (separate from app.py) so it never collides
with the Gradio dashboard. Launch:

    agent_orchestrator/.venv/bin/python -m agent_orchestrator.editor
    # → http://localhost:7870

Endpoints:
    GET  /                serve the canvas (web/editor.html)
    GET  /api/state       palette + current graph + workflow list + settings
    POST /api/save        write the canvas graph to a .workflow.yaml
    POST /api/run         dispatch a command through a saved graph (SSE stream)
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from . import router, workflow, catalog
from .config import SETTINGS, PKG_ROOT, REPO_ROOT
from .state import OrchestratorState
from .orchestrate import orchestrate
from .runner import get_executor
from .validator import Supervisor, FAIL, RETRY, REROUTE

WEB_DIR = PKG_ROOT / "web"
WORKFLOWS_DIR = PKG_ROOT / "workflows"
DEFAULT_REL = "agent_orchestrator/workflows/default.workflow.yaml"
CUSTOM_REL = "agent_orchestrator/workflows/custom.workflow.yaml"
# Max seconds to wait for the next event from an agent turn before declaring it
# stuck (a slow/hanging project MCP server is the usual culprit).
_TURN_IDLE_TIMEOUT = int(os.environ.get("ORCH_TURN_TIMEOUT", "120"))

app = FastAPI(title="Agent Workflow Editor")


# --- palette: the agent boxes you can drag onto the canvas ------------------
def _palette() -> list[dict]:
    """Built from the active graph's agent definitions + the 5 known node types,
    so dragging in a node always maps to a real .claude/agents/*.md."""
    wf = workflow.load_default()
    # node-type templates (id-prefix, defaults) keyed by routing key
    templates = {
        "supervisor": {"type": "supervisor", "layer": 0, "icon": "🛰️",
                       "color": "#38bdf8", "title": "Master Agent"},
        "assets": {"type": "agent", "layer": 1, "icon": "📦", "color": "#a78bfa",
                   "title": "Asset Placement"},
        "rl": {"type": "agent", "layer": 2, "icon": "🧠", "color": "#34d399",
               "title": "RL Authoring"},
        "il": {"type": "agent", "layer": 3, "icon": "🎭", "color": "#f472b6",
               "title": "Imitation Learning"},
        "exec": {"type": "agent", "layer": 4, "icon": "⚙️", "color": "#fbbf24",
                 "title": "Execution"},
    }
    # carry the real agent palette name + match keywords from the active graph
    by_key = {n.key: n for n in wf.nodes.values() if n.key}
    out = [{
        "kind": "trigger", "type": "trigger", "title": "Command In",
        "icon": "⌨️", "color": "#94a3b8", "key": "", "layer": None,
        "agent": "", "match": [],
    }]
    for key, tpl in templates.items():
        node = by_key.get(key)
        agent_name = node.agent if node else ""
        match = [{p: w} for p, w in (node.match if node else [])]
        file = wf.agents.get(agent_name, {}).get("file", "")
        out.append({
            "kind": key, **tpl, "key": key, "agent": agent_name,
            "file": file, "match": match,
        })
    return out


def _workflow_files() -> list[str]:
    rels = []
    for p in sorted(WORKFLOWS_DIR.rglob("*.workflow.yaml")):
        rels.append(str(p.relative_to(REPO_ROOT)))
    return rels


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    return HTMLResponse((WEB_DIR / "editor.html").read_text())


@app.get("/api/state")
def api_state() -> JSONResponse:
    wf = workflow.load_default()
    return JSONResponse({
        "palette": _palette(),
        "graph": workflow.to_dict(wf),
        "active_path": str(Path(workflow.DEFAULT_WORKFLOW).relative_to(REPO_ROOT))
        if str(workflow.DEFAULT_WORKFLOW).startswith(str(REPO_ROOT)) else DEFAULT_REL,
        "workflows": _workflow_files(),
        "default_save": CUSTOM_REL,
        "settings": {
            "model": SETTINGS.model,
            "backend": SETTINGS.backend or "sdk",
            "supervise": SETTINGS.supervise_default,
            "isaac_lab": str(SETTINGS.isaac_lab_dir or "NOT FOUND"),
        },
    })


@app.post("/api/load")
async def api_load(request: Request) -> JSONResponse:
    body = await request.json()
    rel = body.get("path") or DEFAULT_REL
    try:
        wf = workflow.load(rel)
        return JSONResponse({"ok": True, "graph": workflow.to_dict(wf),
                             "issues": wf.validate()})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"})


@app.post("/api/save")
async def api_save(request: Request) -> JSONResponse:
    body = await request.json()
    graph = body.get("graph") or {}
    rel = (body.get("path") or CUSTOM_REL).strip()
    try:
        wf = workflow.load_dict(graph)
        issues = wf.validate()
        path = workflow.dump(wf, rel)
        return JSONResponse({"ok": True, "path": str(path.relative_to(REPO_ROOT)),
                             "issues": issues})
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"})


@app.post("/api/run")
async def api_run(request: Request) -> StreamingResponse:
    body = await request.json()
    command = (body.get("command") or "").strip()
    rel = body.get("path") or CUSTOM_REL
    backend = (body.get("backend") or "dryrun").lower()
    dry_run = backend == "dryrun"
    allow_exec = bool(body.get("allow_execution", False))
    supervise = bool(body.get("supervise", SETTINGS.supervise_default))

    async def sse():
        def pack(event: str, data: dict) -> str:
            return f"event: {event}\ndata: {json.dumps(data)}\n\n"

        if not command:
            yield pack("error", {"text": "empty command"})
            return
        # Route this run through the graph the user just built/saved.
        wf = router.apply_workflow(rel)
        if wf is None:
            yield pack("error", {"text": f"could not load workflow {rel!r}"})
            return
        # Keep execution's fall-through in sync with the graph's ★ default node,
        # so a 0-score command (e.g. a typo) lands where the preview says — not on
        # a stale SETTINGS.default_layer captured at server start.
        dl = wf.default_layer()
        if dl:
            SETTINGS.default_layer = dl
        node, scores = wf.route(command)
        yield pack("route", {"node": node.id if node else None,
                             "title": node.title if node else "",
                             "scores": scores})
        state = OrchestratorState()
        # Iterate with an idle timeout so a stalled SDK call surfaces as an error
        # instead of an endless "running" (parity with the chat path).
        agen = orchestrate(command, state, dry_run=dry_run, allow_execution=allow_exec,
                           backend=None if dry_run else backend,
                           supervise=supervise).__aiter__()
        while True:
            try:
                ev = await asyncio.wait_for(agen.__anext__(), timeout=_TURN_IDLE_TIMEOUT)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                yield pack("error", {"text": (f"No agent response for {_TURN_IDLE_TIMEOUT}s — "
                    "the SDK turn looks stuck. Try Dry-run, or uncheck Master to make a single call.")})
                break
            except Exception as e:  # noqa: BLE001
                yield pack("error", {"text": f"{type(e).__name__}: {e}"})
                break
            payload = {"kind": ev.kind, "layer": ev.layer, "text": ev.text,
                       "target": ev.target}
            if ev.kind == "verdict" and ev.payload is not None:
                payload["text"] = ev.payload.one_line()
            yield pack(ev.kind, payload)
            await asyncio.sleep(0)
        yield pack("done", {"log": state.log_text()})

    return StreamingResponse(sse(), media_type="text/event-stream")


# ===========================================================================
#  Conversation mode — run the workflow turn by turn, show tools + outputs,
#  and let the user SELECT the next step from the choices the LLM proposes.
# ===========================================================================
SESSIONS: dict[str, dict] = {}
_LAYER_TITLE = {n: t for n, (_k, t, _a) in router.LAYERS.items()}
# include Atlas (L0) so a user can target the supervisor directly from the box
_AGENT_TITLE = {0: router.SUPERVISOR[1], **_LAYER_TITLE}

# --- persistent thread memory (like Claude Code / OpenClaw) -----------------
# Each chat thread is a JSON file under $WORKSPACE_DIR/chat/<id>.json holding the
# running transcript. Memory survives page reloads AND server restarts, and is
# injected into every agent turn so later chats remember earlier ones.
CHAT_DIR = SETTINGS.workspace_dir / "chat"
THREADS: dict[str, dict] = {}
_MEM_MAX_TURNS = 16          # how many past turns to feed forward
_MEM_SUMMARY_CHARS = 240     # per-turn output snippet length


def _thread_path(tid: str) -> Path:
    return CHAT_DIR / f"{tid}.json"


def _load_thread(tid: str) -> dict:
    if tid in THREADS:
        return THREADS[tid]
    data = {"id": tid, "turns": []}
    p = _thread_path(tid)
    if p.exists():
        try:
            data = json.loads(p.read_text()) or data
        except Exception:  # noqa: BLE001
            pass
    THREADS[tid] = data
    return data


def _save_thread(tid: str) -> None:
    CHAT_DIR.mkdir(parents=True, exist_ok=True)
    _thread_path(tid).write_text(json.dumps(THREADS.get(tid, {"id": tid, "turns": []})))


def _append_turn(tid: str, *, layer: int, command: str, output: str,
                 verdict: str) -> None:
    t = _load_thread(tid)
    snippet = " ".join((output or "").split())[:_MEM_SUMMARY_CHARS]
    t["turns"].append({"layer": layer, "title": _AGENT_TITLE.get(layer, f"L{layer}"),
                       "command": command[:300], "summary": snippet, "verdict": verdict})
    _save_thread(tid)


def _memory_block(tid: str | None) -> str:
    if not tid:
        return ""
    turns = _load_thread(tid).get("turns", [])
    if not turns:
        return ""
    lines = ["## Conversation memory (this thread — earlier turns; continue the same project)"]
    for i, t in enumerate(turns[-_MEM_MAX_TURNS:], 1):
        v = f" [{t['verdict']}]" if t.get("verdict") else ""
        lines.append(f"{i}. (L{t['layer']} {t['title']}) user: {t['command']!r} "
                     f"→ {t['summary']}{v}")
    lines.append("Use this context; the user may refer back to earlier steps.\n")
    return "\n".join(lines)


def _sess(sid: str) -> dict | None:
    return SESSIONS.get(sid)


def _build_command(s: dict, mode: str, layer: int, reason: str) -> str:
    """Construct the prompt for the next turn, mirroring the auto-loop's wording
    so a user-driven path behaves like the orchestrator's. Persistent thread
    memory is prepended so each agent remembers earlier chats in the thread."""
    orig = s["command"]
    tail = (s.get("last_output") or "")[-800:]
    prev = s.get("last_layer")
    mem = _memory_block(s.get("thread"))
    pre = (mem + "\n") if mem else ""
    if mode == "retry":
        base = s.get("layer_base") or orig
        return (f"{pre}{base}\n\n[Master REJECTED the previous attempt — "
                f"fix and redo]\nReason: {reason}\nPrevious output tail:\n{tail}")
    if mode == "reroute":
        return (f"{pre}{reason}\n\n(Context: original command was {orig!r}. "
                f"Previous L{prev} output tail:\n{tail})")
    if mode == "manual" and prev:
        return (f"{pre}{orig}\n\n(Handed off from L{prev}. Previous output tail:\n{tail})")
    return f"{pre}{orig}"  # first run of a layer


def _choices(s: dict, layer: int, verdict, worker_reroute, retries: int) -> list[dict]:
    """The selectable next steps. `recommended: True` marks the one the
    auto-orchestrator would pick — i.e. the LLM/Atlas's own choice."""
    items: list[dict] = []
    rec: str | None = None

    if verdict is not None and verdict.status == FAIL and verdict.action == RETRY \
            and retries < s["max_retries"]:
        items.append({"id": "retry", "kind": "retry", "layer": layer,
                      "label": f"↻ Retry L{layer} with Master's feedback",
                      "reason": verdict.message})
        rec = "retry"
    if verdict is not None and verdict.action == REROUTE and verdict.target:
        tgt = router.resolve_reroute(verdict.target)
        if tgt:
            items.append({"id": "reroute_atlas", "kind": "reroute", "layer": tgt,
                          "signal": verdict.target, "reason": verdict.message,
                          "label": f"↪ Master: reroute → L{tgt} · {_LAYER_TITLE.get(tgt,'')}"})
            rec = rec or "reroute_atlas"
    if worker_reroute and (verdict is None or verdict.ok):
        key, reason = worker_reroute
        tgt = router.resolve_reroute(key)
        if tgt and tgt != layer:
            items.append({"id": "reroute_worker", "kind": "reroute", "layer": tgt,
                          "signal": key, "reason": reason,
                          "label": f"↪ Worker suggests → L{tgt} · {_LAYER_TITLE.get(tgt,'')}"})
            rec = rec or "reroute_worker"

    items.append({"id": "accept", "kind": "finish", "label": "✅ Accept & finish"})
    rec = rec or "accept"

    # manual override: send to any other worker layer
    for n, title in _LAYER_TITLE.items():
        if n != layer:
            items.append({"id": f"to_L{n}", "kind": "manual", "layer": n,
                          "label": f"→ Send to L{n} · {title}"})
    for it in items:
        it["recommended"] = (it["id"] == rec)
    return items


@app.post("/api/session/start")
async def session_start(request: Request) -> JSONResponse:
    body = await request.json()
    graph = body.get("graph") or {}
    rel = (body.get("path") or CUSTOM_REL).strip()
    command = (body.get("command") or "").strip()
    if not command:
        return JSONResponse({"ok": False, "error": "type a command first"})
    try:
        wf = workflow.load_dict(graph)
        path = workflow.dump(wf, rel)
        rel = str(path.relative_to(REPO_ROOT))
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"save failed: {e}"})
    applied = router.apply_workflow(rel)
    dl = applied.default_layer() if applied else None
    if dl:
        SETTINGS.default_layer = dl          # keep fall-through = graph's ★ node
    node, scores = wf.route(command)
    routed = node.layer if node and node.layer else SETTINGS.default_layer
    backend = (body.get("backend") or "dryrun").lower()

    # Optional: user forced a specific agent via the chat dropdown.
    forced = body.get("agent")
    forced_layer = None
    if forced not in (None, "", "auto"):
        try:
            forced_layer = int(forced)
        except (TypeError, ValueError):
            forced_layer = router.KEY_TO_LAYER.get(str(forced).lower())

    # Thread = persistent memory scope (created if new). Memory survives reloads.
    tid = (body.get("thread") or secrets.token_hex(6)).strip()
    _load_thread(tid)

    sid = secrets.token_hex(8)
    SESSIONS[sid] = {
        "command": command, "path": rel, "backend": backend, "thread": tid,
        "dry_run": backend == "dryrun",
        "allow_execution": bool(body.get("allow_execution", False)),
        "supervise": bool(body.get("supervise", SETTINGS.supervise_default)),
        "max_retries": SETTINGS.max_retries, "max_hops": SETTINGS.max_hops,
        "last_output": "", "last_layer": None, "layer_base": command,
        "hops": 0, "retries": 0,
    }
    target = forced_layer if forced_layer in _AGENT_TITLE else routed
    # First "choice set" = the routing recommendation (or the forced agent).
    items = [{"id": f"to_L{target}", "kind": "manual", "layer": target,
              "label": f"▶ Run L{target} · {_AGENT_TITLE.get(target,'')}",
              "recommended": True}]
    for n, title in _AGENT_TITLE.items():
        if n != target:
            items.append({"id": f"to_L{n}", "kind": "manual", "layer": n,
                          "label": f"→ Run L{n} · {title}", "recommended": False})
    return JSONResponse({
        "ok": True, "session": sid, "thread": tid, "routed": target,
        "forced": forced_layer is not None,
        "title": _AGENT_TITLE.get(target, ""),
        "scores": scores, "choices": items,
        "memory_turns": len(_load_thread(tid).get("turns", [])),
    })


@app.post("/api/session/step")
async def session_step(request: Request) -> StreamingResponse:
    body = await request.json()
    sid = body.get("session", "")
    s = _sess(sid)
    layer = int(body.get("layer", 0))
    mode = body.get("mode", "run")
    reason = body.get("reason", "")

    async def sse():
        def pack(ev, d):
            return f"event: {ev}\ndata: {json.dumps(d)}\n\n"

        if s is None:
            yield pack("error", {"text": "session expired — restart the chat"}); return
        if layer not in _AGENT_TITLE:
            yield pack("error", {"text": f"no such agent L{layer}"}); return

        # entering a fresh layer (not a retry) resets the per-layer retry count
        if mode != "retry":
            s["retries"] = 0
            s["layer_base"] = _build_command(s, mode, layer, reason)
            current = s["layer_base"]
        else:
            s["retries"] += 1
            current = _build_command(s, "retry", layer, reason)

        title = _AGENT_TITLE.get(layer, "")
        yield pack("turn_start", {"layer": layer, "title": title,
                                  "retry": s["retries"], "command": current})

        executor = get_executor(s["dry_run"], allow_execution=s["allow_execution"],
                                backend=None if s["dry_run"] else s["backend"])
        final_text, worker_reroute, errored = "", None, False
        # Iterate manually so a stalled SDK turn surfaces as an error instead of
        # an infinite "running". Tune with $ORCH_TURN_TIMEOUT (seconds).
        agen = executor.run(layer, current).__aiter__()
        while True:
            try:
                ev = await asyncio.wait_for(agen.__anext__(), timeout=_TURN_IDLE_TIMEOUT)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                errored = True
                yield pack("error", {"layer": layer,
                    "text": (f"No response from the agent for {_TURN_IDLE_TIMEOUT}s — the "
                             "SDK turn looks stuck (slow agent startup, a hanging MCP "
                             "server, or auth). Try the Dry-run backend, or pick a "
                             "specific agent and a simpler command.")})
                break
            except Exception as e:  # noqa: BLE001
                errored = True
                yield pack("error", {"layer": layer, "text": f"{type(e).__name__}: {e}"})
                break
            if ev.kind == "status":
                yield pack("status", {"layer": layer, "text": ev.text})
            elif ev.kind == "text":
                final_text = ev.text
                yield pack("text", {"layer": layer, "text": ev.text})
            elif ev.kind == "tool":
                yield pack("tool", {"layer": layer, "text": ev.text})
            elif ev.kind == "reroute":
                if router.resolve_reroute(ev.target):
                    worker_reroute = (ev.target, ev.text)
                    yield pack("reroute", {"layer": layer, "target": ev.target,
                                           "text": ev.text})
            elif ev.kind == "result":
                if ev.text:
                    final_text = ev.text
                yield pack("result", {"layer": layer, "text": ev.text,
                                      "cost": ev.cost_usd})
            elif ev.kind == "error":
                errored = True
                yield pack("error", {"layer": layer, "text": ev.text})
            await asyncio.sleep(0)

        s["last_output"], s["last_layer"] = final_text, layer

        # ---- Atlas validation (skip when the user ran Atlas itself) ----------
        verdict = None
        if s["supervise"] and layer != 0:
            # If the worker stalled/failed, skip the LLM verdict (it would hang
            # the same way) and use only the fast deterministic checks.
            use_llm = SETTINGS.supervisor_use_llm and not s["dry_run"] and not errored
            backend_name = "dryrun" if s["dry_run"] else s["backend"]
            yield pack("atlas_start", {"layer": layer})
            sgen = Supervisor().validate(layer, s["layer_base"], final_text,
                                         llm=use_llm, executor=executor,
                                         backend=backend_name).__aiter__()
            while True:
                try:
                    sev = await asyncio.wait_for(sgen.__anext__(),
                                                 timeout=_TURN_IDLE_TIMEOUT)
                except StopAsyncIteration:
                    break
                except (asyncio.TimeoutError, Exception) as e:  # noqa: BLE001
                    yield pack("atlas_text", {"text": f"supervisor skipped ({type(e).__name__})"})
                    break
                if sev.kind == "status":
                    yield pack("status", {"layer": 0, "text": sev.text})
                elif sev.kind == "tool":
                    yield pack("atlas_tool", {"text": sev.text})
                elif sev.kind == "text":
                    yield pack("atlas_text", {"text": sev.text})
                elif sev.kind == "verdict":
                    verdict = sev.payload
                    yield pack("verdict", {"text": sev.payload.one_line(),
                                           "status": sev.payload.status,
                                           "action": sev.payload.action,
                                           "target": sev.payload.target or ""})
                await asyncio.sleep(0)

        # persist this turn into the thread's memory (survives reloads/restarts).
        # Record the raw user command — never the memory-prefixed prompt — so the
        # stored transcript can't nest earlier memory blocks inside itself.
        _append_turn(s["thread"], layer=layer, command=s["command"],
                     output=final_text, verdict=(verdict.one_line() if verdict else ""))

        items = _choices(s, layer, verdict, worker_reroute, s["retries"])
        yield pack("choices", {"items": items})
        yield pack("done", {})

    return StreamingResponse(sse(), media_type="text/event-stream")


@app.post("/api/session/finish")
async def session_finish(request: Request) -> JSONResponse:
    """Mark a conversation done (the client opens a fresh chat after this). The
    thread memory is already persisted per-turn; return its size for the UI."""
    body = await request.json()
    s = _sess(body.get("session", ""))
    tid = s.get("thread") if s else body.get("thread")
    turns = len(_load_thread(tid).get("turns", [])) if tid else 0
    return JSONResponse({"ok": True, "thread": tid, "memory_turns": turns})


def main() -> None:
    import uvicorn  # noqa: PLC0415
    port = int(os.environ.get("ORCH_EDITOR_PORT", "7870"))
    print(f"⌨️  Agent Workflow Editor → http://localhost:{port}")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
