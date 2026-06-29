"""Execute a layer agent via the Claude Agent SDK, streaming events.

Pluggable: if `claude-agent-sdk` isn't installed (or dry-run is requested) the
DryRunExecutor yields the planned routing/command without calling the model, so
the UI is usable for wiring/testing without spending tokens.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import AsyncIterator

from .config import SETTINGS, REPO_ROOT
from .agents import get_layer, AgentLayer
from .catalog import context_blob

# Layer 4 emits this on its own line to hand control to another layer.
REROUTE_TOKEN = "@@REROUTE:"
_REROUTE_RE = re.compile(r"@@REROUTE:\s*([A-Za-z0-9]+)\s*::\s*(.+)")


@dataclass
class Event:
    # "status" | "text" | "tool" | "reroute" | "result" | "error" | "verdict"
    kind: str
    layer: int
    text: str = ""
    target: str = ""   # for reroute: target layer key
    cost_usd: float | None = None
    payload: object | None = None   # for "verdict": the validator.Verdict


def _build_prompt(layer: AgentLayer, command: str) -> str:
    extra = ""
    if layer.layer == 1:
        extra = "\n\n" + context_blob()
    return (
        f"Orchestrator command for {layer.name}:\n\n{command}\n"
        f"{extra}\n\n"
        "Work within the env contract ($ISAAC_SIM_DIR, $ISAAC_LAB_DIR, "
        "$WORKSPACE_DIR). When you must hand off, emit the @@REROUTE line."
    )


def scan_reroute(text: str) -> tuple[str, str] | None:
    m = _REROUTE_RE.search(text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None


# --- Dry-run (no API) -------------------------------------------------------
class DryRunExecutor:
    async def run(self, layer_num: int, command: str) -> AsyncIterator[Event]:
        layer = get_layer(layer_num)
        yield Event("status", layer_num, "running (dry-run)")
        await asyncio.sleep(0)
        yield Event(
            "text", layer_num,
            f"[dry-run] {layer.name} would handle:\n  {command}\n"
            f"  tools={layer.allowed_tools}\n  permission={layer.permission_mode}\n"
            f"  cwd={REPO_ROOT}",
        )
        yield Event("result", layer_num, "dry-run complete", cost_usd=0.0)


# --- Real SDK executor ------------------------------------------------------
class SDKExecutor:
    def __init__(self, model: str | None = None, max_turns: int = 30,
                 allow_execution: bool = True):
        self.model = model or SETTINGS.model
        self.max_turns = max_turns
        self.allow_execution = allow_execution

    async def run(self, layer_num: int, command: str) -> AsyncIterator[Event]:
        try:
            from claude_agent_sdk import (  # noqa: PLC0415
                query, ClaudeAgentOptions, AssistantMessage, ResultMessage,
            )
        except ImportError as e:
            yield Event("error", layer_num,
                        f"claude-agent-sdk not installed ({e}). "
                        "pip install claude-agent-sdk, or use Dry-run mode.")
            return

        layer = get_layer(layer_num)
        SETTINGS.ensure_workspace()
        # L4 needs Bash for training; downgrade if execution is disabled in UI.
        perm = layer.permission_mode
        if not self.allow_execution and perm == "bypassPermissions":
            perm = "acceptEdits"

        options = ClaudeAgentOptions(
            system_prompt=layer.system_prompt,
            allowed_tools=layer.allowed_tools,
            cwd=str(REPO_ROOT),
            permission_mode=perm,
            model=self.model,
            max_turns=self.max_turns,
            setting_sources=["project"],  # load this repo's .claude skills + agents
            env=SETTINGS.as_env(),
        )

        yield Event("status", layer_num, "running")
        prompt = _build_prompt(layer, command)
        buffer: list[str] = []
        try:
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in getattr(message, "content", []):
                        txt = getattr(block, "text", None)
                        if txt:
                            buffer.append(txt)
                            yield Event("text", layer_num, txt)
                            rr = scan_reroute(txt)
                            if rr:
                                yield Event("reroute", layer_num,
                                            text=rr[1], target=rr[0])
                        elif getattr(block, "name", None):
                            yield Event("tool", layer_num,
                                        f"⚙ {block.name}")
                elif isinstance(message, ResultMessage):
                    cost = getattr(message, "total_cost_usd", None)
                    result = getattr(message, "result", "") or ""
                    rr = scan_reroute(result) or scan_reroute("\n".join(buffer))
                    if rr:
                        yield Event("reroute", layer_num, text=rr[1], target=rr[0])
                    yield Event("result", layer_num, result, cost_usd=cost)
        except Exception as e:  # noqa: BLE001 - surface any SDK/runtime failure
            yield Event("error", layer_num, f"{type(e).__name__}: {e}")


# --- OpenClaw executor (run layers through the OpenClaw agent runtime) -------
def _find_openclaw() -> str | None:
    exe = shutil.which("openclaw")
    if exe:
        return exe
    cand = Path.home() / ".npm-global" / "bin" / "openclaw"
    return str(cand) if cand.exists() else None


class OpenClawExecutor:
    """Run a layer via `openclaw agent --local`, so the orchestrator is usable
    from / compatible with OpenClaw (its models, workspace, skills)."""

    def __init__(self, model: str | None = None, timeout: int = 600):
        self.model = model
        self.timeout = timeout

    async def run(self, layer_num: int, command: str) -> AsyncIterator[Event]:
        exe = _find_openclaw()
        if not exe:
            yield Event("error", layer_num,
                        "openclaw CLI not found on PATH or ~/.npm-global/bin.")
            return
        layer = get_layer(layer_num)
        SETTINGS.ensure_workspace()
        # OpenClaw doesn't load this repo's .claude agents, so carry the layer's
        # system prompt in the message body. OpenClaw also overrides $WORKSPACE_DIR
        # with its OWN workspace, so pin generated files to the project's absolute
        # path — otherwise Atlas (which checks the orchestrator's workspace) can't
        # find the artifacts and the run fails validation.
        message = (
            f"[System role for this turn]\n{layer.system_prompt}\n\n"
            f"[Task]\n{_build_prompt(layer, command)}\n\n"
            f"[Workspace] Write ALL generated files under the ABSOLUTE path "
            f"{SETTINGS.workspace_dir} (subdirs: generated/scene, generated/rl, "
            f"generated/il, runs, datasets). Do NOT use $WORKSPACE_DIR — the "
            f"runtime may override it. Operate from {REPO_ROOT}."
        )
        # OpenClaw (>=2026.5) requires a session selector. Use a fresh per-turn
        # session id so each layer runs as a clean one-shot. Override the agent
        # binding with $ORCH_OPENCLAW_AGENT to route through a configured agent.
        argv = [exe, "agent", "--local", "--json", "-m", message]
        oc_agent = os.environ.get("ORCH_OPENCLAW_AGENT")
        if oc_agent:
            argv += ["--agent", oc_agent]
        else:
            argv += ["--session-id", f"orch-l{layer_num}-{os.urandom(4).hex()}"]
        if self.model:
            argv += ["--model", self.model]
        yield Event("status", layer_num, "running (openclaw)")
        env = SETTINGS.as_env()
        env["PATH"] = env.get("PATH", "") + ":" + str(Path(exe).parent)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=env, cwd=str(REPO_ROOT),
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout)
        except asyncio.TimeoutError:
            yield Event("error", layer_num, f"openclaw timed out after {self.timeout}s")
            return
        except Exception as e:  # noqa: BLE001
            yield Event("error", layer_num, f"{type(e).__name__}: {e}")
            return

        text = out.decode(errors="replace").strip()
        reply = text
        try:  # OpenClaw --json: unwrap the reply text from the envelope
            data = json.loads(text)
            # 2026.5 shape: {"payloads": [{"text": "..."}], ...}
            payloads = data.get("payloads") if isinstance(data, dict) else None
            if payloads:
                reply = "\n".join(p.get("text", "") for p in payloads
                                  if isinstance(p, dict)).strip() or json.dumps(data)
            else:
                reply = (data.get("reply") or data.get("text")
                         or data.get("message") or json.dumps(data))
        except (json.JSONDecodeError, AttributeError):
            pass
        if proc.returncode != 0 and not reply:
            yield Event("error", layer_num, err.decode(errors="replace")[-800:])
            return
        yield Event("text", layer_num, reply)
        rr = scan_reroute(reply)
        if rr:
            yield Event("reroute", layer_num, text=rr[1], target=rr[0])
        yield Event("result", layer_num, reply)


# --- NemoClaw executor (run layers inside a NemoClaw NIM sandbox) ------------
def _find_nemoclaw() -> str | None:
    exe = shutil.which("nemoclaw")
    if exe:
        return exe
    for cand in (Path.home() / ".local" / "bin" / "nemoclaw",
                 Path.home() / ".npm-global" / "bin" / "nemoclaw"):
        if cand.exists():
            return str(cand)
    return None


class NemoClawExecutor:
    """Run a layer inside a NemoClaw sandbox via `nemoclaw <sandbox> exec`.

    Unlike OpenClaw, NemoClaw has no one-shot `agent --local`; it manages
    always-on NIM sandboxes. We exec an in-sandbox agent CLI (default `claude
    -p`, override via $NEMOCLAW_AGENT_CMD) and feed it the layer system prompt +
    task on stdin. The prompt is base64-piped so multi-line content needs no
    shell quoting. The target sandbox is required ($NEMOCLAW_SANDBOX) — there is
    deliberately no default.
    """

    def __init__(self, sandbox: str | None = None, model: str | None = None,
                 agent_cmd: str | None = None, timeout: int | None = None):
        ncfg = SETTINGS.backend_config("nemoclaw")
        self.sandbox = sandbox or os.environ.get("NEMOCLAW_SANDBOX") or ncfg.get("sandbox")
        self.model = model or os.environ.get("NEMOCLAW_MODEL") or ncfg.get("model")
        self.agent_cmd = (agent_cmd or os.environ.get("NEMOCLAW_AGENT_CMD")
                          or ncfg.get("agent_cmd") or "claude -p")
        self.timeout = timeout or int(ncfg.get("timeout", 900))

    async def run(self, layer_num: int, command: str) -> AsyncIterator[Event]:
        exe = _find_nemoclaw()
        if not exe:
            yield Event("error", layer_num,
                        "nemoclaw CLI not found on PATH, ~/.local/bin, or "
                        "~/.npm-global/bin.")
            return
        if not self.sandbox:
            yield Event("error", layer_num,
                        "NEMOCLAW_SANDBOX is not set. Point it at a sandbox "
                        "(`nemoclaw list`), e.g. NEMOCLAW_SANDBOX=robotcontrol.")
            return
        layer = get_layer(layer_num)
        SETTINGS.ensure_workspace()
        # The sandbox doesn't load this repo's .claude agents, so carry the
        # layer's system prompt in the message body (same as OpenClaw).
        message = (
            f"[System role for this turn]\n{layer.system_prompt}\n\n"
            f"[Task]\n{_build_prompt(layer, command)}"
        )
        agent_cmd = self.agent_cmd
        if self.model:
            agent_cmd += f" --model {self.model}"
        import base64  # noqa: PLC0415 - local, only this backend needs it
        b64 = base64.b64encode(message.encode()).decode()
        inner = f"echo {b64} | base64 -d | {agent_cmd}"
        argv = [exe, self.sandbox, "exec", "--no-tty",
                "--timeout", str(self.timeout), "--", "bash", "-lc", inner]
        yield Event("status", layer_num, f"running (nemoclaw:{self.sandbox})")
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=SETTINGS.as_env(),
                cwd=str(REPO_ROOT),
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=self.timeout + 30)
        except asyncio.TimeoutError:
            yield Event("error", layer_num, f"nemoclaw exec timed out after {self.timeout}s")
            return
        except Exception as e:  # noqa: BLE001
            yield Event("error", layer_num, f"{type(e).__name__}: {e}")
            return

        text = out.decode(errors="replace").strip()
        reply = text
        try:  # tolerate agent CLIs that emit a JSON envelope
            data = json.loads(text)
            reply = (data.get("reply") or data.get("text")
                     or data.get("result") or data.get("message") or json.dumps(data))
        except (json.JSONDecodeError, AttributeError):
            pass
        if proc.returncode != 0 and not reply:
            yield Event("error", layer_num, err.decode(errors="replace")[-800:])
            return
        yield Event("text", layer_num, reply)
        rr = scan_reroute(reply)
        if rr:
            yield Event("reroute", layer_num, text=rr[1], target=rr[0])
        yield Event("result", layer_num, reply)


def get_executor(dry_run: bool, allow_execution: bool = True,
                 backend: str | None = None):
    """backend: 'dryrun' | 'sdk' | 'openclaw' | 'nemoclaw'.

    Resolution order: explicit arg > env ORCH_BACKEND > orchestrator.yaml
    (runtime.backend) > 'sdk'. Per-backend knobs come from the config's
    backends.<name> block.
    """
    backend = (backend or os.environ.get("ORCH_BACKEND") or SETTINGS.backend or "").lower()
    if dry_run or backend == "dryrun":
        return DryRunExecutor()
    if backend == "openclaw":
        ocfg = SETTINGS.backend_config("openclaw")
        return OpenClawExecutor(
            model=os.environ.get("ORCH_OPENCLAW_MODEL") or ocfg.get("model"),
            timeout=int(ocfg.get("timeout", 600)),
        )
    if backend == "nemoclaw":
        return NemoClawExecutor()
    return SDKExecutor(allow_execution=allow_execution, max_turns=SETTINGS.max_turns)
