"""Layer 0 — Atlas, the Master Supervisor of the robot orchestration.

Atlas monitors and validates each worker layer's execution for Isaac Sim / Isaac
Lab tasks. After a layer runs, `Supervisor.validate()` combines two signals:

* **Deterministic checks** — cheap, no-API Isaac/Lab heuristics over the layer's
  output (error signatures, claimed-file existence, empty output). These always
  run, so supervision works even in dry-run / without credentials.
* **An LLM verdict** — when enabled and not dry-run, the `orch-l0-supervisor`
  agent is run via the same executor as the layers; it inspects artifacts on
  disk and returns a `@@VERDICT:` line that refines the deterministic call.

The merged result is a `Verdict` the orchestration loop acts on: accept, retry
the same layer with feedback, or reroute to the layer that owns the fix.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator

from .config import REPO_ROOT, SETTINGS
from .runner import Event

# --- Verdict / dispatch protocol --------------------------------------------
# The supervisor agent emits these on their own line, mirroring REROUTE_TOKEN.
VERDICT_TOKEN = "@@VERDICT:"
_VERDICT_RE = re.compile(
    r"@@VERDICT:\s*(PASS|WARN|FAIL)\s*::\s*([A-Za-z0-9:_-]+)\s*::\s*(.+)", re.I
)
# Atlas emits this when it dispatches a command to an entry worker (or answers).
DISPATCH_TOKEN = "@@DISPATCH:"
_DISPATCH_RE = re.compile(r"@@DISPATCH:\s*([A-Za-z0-9_-]+)\s*::\s*(.+)", re.I)

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
ACCEPT, RETRY, REROUTE = "accept", "retry", "reroute"

# When routing is ambiguous and Atlas can't pick (e.g. dry-run, no LLM), fall
# through to the asset/catalog layer — read-friendly — never the Bash executor.
SAFE_DEFAULT_LAYER = 1


@dataclass
class Dispatch:
    target_layer: int
    reason: str = ""
    source: str = "keyword"     # keyword | llm | safe-default
    answer: str | None = None   # set when Atlas answered the query itself

    def one_line(self) -> str:
        ans = " (answered directly)" if self.answer else ""
        return f"→ L{self.target_layer}{ans} — {self.reason}"


def parse_dispatch(text: str) -> tuple[str, str] | None:
    """Pull an `@@DISPATCH:` line (key, reason) from Atlas's reply."""
    m = _DISPATCH_RE.search(text or "")
    return (m.group(1).strip().lower(), m.group(2).strip()) if m else None

# Output substrings that mean the layer hit a hard error → FAIL.
_FAIL_SIGNS: list[tuple[str, str]] = [
    (r"Traceback \(most recent call last\)", "python traceback"),
    (r"\bModuleNotFoundError\b", "missing python module"),
    (r"\bImportError\b", "import error"),
    (r"command not found", "missing command"),
    (r"No such file or directory", "missing file/path"),
    (r"\bSegmentation fault\b", "segfault"),
    (r"CUDA (?:error|out of memory)", "CUDA failure"),
    (r"\b(?:loss|reward)\b[^\n]{0,40}\bnan\b", "NaN in a training signal"),
    (r"Failed to open stage|Could not open layer|\bUSD\b[^\n]{0,30}error",
     "USD load failure"),
    (r"\bAssertionError\b", "assertion failed"),
    (r"\bRuntimeError\b", "runtime error"),
]
# Softer signatures → WARN (usable but worth recording).
_WARN_SIGNS: list[tuple[str, str]] = [
    (r"\bdeprecat", "deprecation notice"),
    (r"\bwarning\b", "warning emitted"),
    (r"flat reward|reward[^\n]{0,30}not improving", "training signal may be stuck"),
    (r"\bTODO\b|\bFIXME\b|placeholder", "unfinished placeholder left in output"),
]
# Files a layer plausibly produced — verify the claim if the path is local.
_PATH_RE = re.compile(r"(/[\w./@+-]+\.(?:py|usda?|yaml|yml|json|hdf5|h5|pt|pth|onnx))")
# Which backends keep artifacts off the local filesystem (skip existence checks).
_REMOTE_BACKENDS = {"openclaw", "nemoclaw"}


@dataclass
class Check:
    name: str
    ok: bool
    level: str          # PASS | WARN | FAIL
    detail: str = ""


@dataclass
class Verdict:
    status: str = PASS          # PASS | WARN | FAIL
    action: str = ACCEPT        # accept | retry | reroute
    target: str | None = None   # reroute key: assets | rl | il | exec
    message: str = ""
    checks: list[Check] = field(default_factory=list)
    source: str = "deterministic"   # deterministic | llm | merged

    @property
    def ok(self) -> bool:
        return self.status in (PASS, WARN)

    def badge(self) -> str:
        return {PASS: "✅ PASS", WARN: "⚠️ WARN", FAIL: "❌ FAIL"}.get(
            self.status, self.status)

    def failed_summary(self) -> str:
        bad = [c for c in self.checks if not c.ok]
        return "; ".join(f"{c.name}: {c.detail}" for c in bad) or "(no failed checks)"

    def one_line(self) -> str:
        tgt = f" → {self.target}" if self.action == REROUTE and self.target else ""
        return f"{self.badge()} · {self.action}{tgt} — {self.message}"


def parse_verdict(text: str) -> Verdict | None:
    """Pull a `@@VERDICT:` line out of the supervisor agent's reply."""
    m = _VERDICT_RE.search(text or "")
    if not m:
        return None
    status = m.group(1).upper()
    raw_action = m.group(2).strip().lower()
    message = m.group(3).strip()
    action, target = ACCEPT, None
    if raw_action.startswith("reroute"):
        action = REROUTE
        # accept "reroute:rl" or "reroute rl"
        parts = re.split(r"[:\s]+", raw_action, maxsplit=1)
        target = parts[1].strip() if len(parts) > 1 else None
    elif raw_action.startswith("retry"):
        action = RETRY
    else:
        action = ACCEPT
    return Verdict(status=status, action=action, target=target,
                   message=message, source="llm")


# --- Deterministic Isaac/Lab checks -----------------------------------------
def _deterministic_checks(layer: int, command: str, output: str,
                          backend: str | None) -> list[Check]:
    checks: list[Check] = []
    text = output or ""

    # 1. The layer must actually say something.
    if not text.strip():
        checks.append(Check("non_empty_output", False, FAIL,
                            "layer produced no output"))
        return checks
    checks.append(Check("non_empty_output", True, PASS))

    # 2. Hard error signatures.
    for pattern, label in _FAIL_SIGNS:
        if re.search(pattern, text, re.I):
            checks.append(Check("error_signature", False, FAIL, label))
    # 3. Soft signatures.
    for pattern, label in _WARN_SIGNS:
        if re.search(pattern, text, re.I):
            checks.append(Check("soft_signature", False, WARN, label))

    # 4. Claimed-file existence (only meaningful for local backends).
    if (backend or "").lower() not in _REMOTE_BACKENDS:
        seen: set[str] = set()
        for m in _PATH_RE.finditer(text):
            p = m.group(1)
            if p in seen:
                continue
            seen.add(p)
            path = Path(p)
            if not path.is_absolute():
                path = REPO_ROOT / p
            # Only judge paths the layer is expected to own (workspace / repo).
            inside = any(str(path).startswith(str(b)) for b in
                         (SETTINGS.workspace_dir, REPO_ROOT))
            if inside and not path.exists():
                checks.append(Check("artifact_exists", False, WARN,
                                    f"claimed file not found: {p}"))

    return checks


def _verdict_from_checks(layer: int, checks: list[Check]) -> Verdict:
    fails = [c for c in checks if c.level == FAIL and not c.ok]
    warns = [c for c in checks if c.level == WARN and not c.ok]
    if fails:
        return Verdict(status=FAIL, action=RETRY, message=fails[0].detail,
                       checks=checks, source="deterministic")
    if warns:
        return Verdict(status=WARN, action=ACCEPT, message=warns[0].detail,
                       checks=checks, source="deterministic")
    return Verdict(status=PASS, action=ACCEPT, message="passed sanity checks",
                   checks=checks, source="deterministic")


def _merge(det: Verdict, llm: Verdict | None) -> Verdict:
    """LLM verdict is authoritative when present, but a deterministic hard-fail
    the model missed escalates an otherwise-clean call to at least WARN."""
    if llm is None:
        return det
    llm.checks = det.checks
    llm.source = "merged"
    det_failed = det.status == FAIL
    if det_failed and llm.status == PASS:
        llm.status = WARN
        llm.message = f"{llm.message} (note: {det.message})"
    return llm


class Supervisor:
    """Atlas — the conductor. Dispatches a command to the entry worker, then
    validates each worker's execution and returns a Verdict."""

    def __init__(self, layer_num: int = 0):
        self.layer_num = layer_num

    # --- dispatch (front of the loop): pick the entry worker ----------------
    def _dispatch_prompt(self, command: str, routing) -> str:
        from .router import LAYERS  # local import avoids a cycle at import time
        menu = "\n".join(f"  - {key}  → L{n} · {title}"
                         for n, (key, title, _a) in LAYERS.items())
        scores = ", ".join(f"L{l}={s:.1f}" for l, s in routing.scores.items() if s)
        return (
            "Dispatch this orchestrator command to the worker layer that owns it.\n\n"
            f"## Command\n{command}\n\n"
            f"## Worker layers\n{menu}\n\n"
            f"Keyword router was inconclusive (scores: {scores or 'none'}). A "
            "read-only question about what assets/robots exist belongs to "
            "`assets` (it owns the catalog). Only choose `exec` for an actual "
            "run/train/inference/teleop request. End with exactly one line:\n"
            "@@DISPATCH: <assets|rl|il|exec> :: <one-line reason>"
        )

    async def dispatch(self, command: str, routing, *, llm: bool, executor
                       ) -> AsyncIterator[Event]:
        """Async-generates dispatch Events; the final Event has kind 'dispatch'
        with a Dispatch in `.payload`. Cheap by design: a confident keyword
        route is rubber-stamped; the LLM is only consulted when routing is
        ambiguous (nothing matched)."""
        from .router import resolve_reroute  # local import avoids a cycle
        yield Event("status", self.layer_num, "dispatching…")
        ambiguous = routing.scores.get(routing.layer, 0) <= 0

        if not ambiguous:
            disp = Dispatch(routing.layer, source="keyword",
                            reason="keyword route: " + ", ".join(routing.matched[:3]))
            yield Event("dispatch", self.layer_num, text=disp.one_line(), payload=disp)
            return

        if llm and executor is not None:
            buf: list[str] = []
            try:
                async for ev in executor.run(self.layer_num,
                                             self._dispatch_prompt(command, routing)):
                    if ev.kind == "text":
                        buf.append(ev.text)
                    elif ev.kind == "tool":
                        yield Event("tool", self.layer_num, ev.text)
                parsed = parse_dispatch("\n".join(buf))
                if parsed:
                    tgt = resolve_reroute(parsed[0])
                    if tgt:
                        disp = Dispatch(tgt, source="llm", reason=parsed[1])
                        yield Event("dispatch", self.layer_num,
                                    text=disp.one_line(), payload=disp)
                        return
            except Exception as e:  # noqa: BLE001 - never let dispatch crash the loop
                yield Event("text", self.layer_num,
                            f"dispatch failed ({type(e).__name__}: {e}); using safe default")

        disp = Dispatch(SAFE_DEFAULT_LAYER, source="safe-default",
                        reason="ambiguous command → asset/catalog layer (read-safe)")
        yield Event("dispatch", self.layer_num, text=disp.one_line(), payload=disp)

    def _validation_prompt(self, layer: int, command: str, output: str) -> str:
        from .router import LAYERS  # local import avoids a cycle at import time
        _key, title, _agent = LAYERS.get(layer, ("?", f"L{layer}", "?"))
        tail = (output or "")[-4000:]
        return (
            f"Validate the execution of **L{layer} · {title}**.\n\n"
            f"## Original command\n{command}\n\n"
            f"## L{layer} output (tail)\n{tail}\n\n"
            "Verify artifacts on disk where you can, run only cheap/safe static "
            "checks, then end with exactly one @@VERDICT line."
        )

    async def validate(
        self, layer: int, command: str, output: str, *,
        llm: bool, executor, backend: str | None = None,
    ) -> AsyncIterator[Event]:
        """Async-generates supervisor Events; the final Event has kind
        'verdict' with the merged Verdict in `.payload`."""
        yield Event("status", self.layer_num, f"validating L{layer}…")
        det = _verdict_from_checks(
            layer, _deterministic_checks(layer, command, output, backend))

        llm_verdict: Verdict | None = None
        if llm and executor is not None:
            buf: list[str] = []
            prompt = self._validation_prompt(layer, command, output)
            try:
                async for ev in executor.run(self.layer_num, prompt):
                    if ev.kind == "text":
                        buf.append(ev.text)
                    elif ev.kind == "tool":
                        yield Event("tool", self.layer_num, ev.text)
                    elif ev.kind == "error":
                        yield Event("text", self.layer_num,
                                    f"supervisor agent error: {ev.text}")
                llm_verdict = parse_verdict("\n".join(buf))
                if llm_verdict is None and buf:
                    yield Event("text", self.layer_num,
                                "supervisor emitted no @@VERDICT line; "
                                "falling back to deterministic checks")
            except Exception as e:  # noqa: BLE001 - never let supervision crash the loop
                yield Event("text", self.layer_num,
                            f"supervisor failed ({type(e).__name__}: {e}); "
                            "using deterministic checks")

        verdict = _merge(det, llm_verdict)
        yield Event("verdict", self.layer_num, text=verdict.one_line(),
                    target=verdict.target or "", payload=verdict)
