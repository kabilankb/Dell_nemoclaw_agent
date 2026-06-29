"""Shared orchestrator state: per-layer status + a rolling event log that the
Gradio panels render."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field, asdict

from .router import ALL_LAYERS

STATUS_IDLE = "idle"
STATUS_ROUTING = "routing"
STATUS_RUNNING = "running"
STATUS_REROUTED = "rerouted"
STATUS_DONE = "done"
STATUS_ERROR = "error"
# Supervisor (Atlas) verdict statuses.
STATUS_VALIDATING = "validating"
STATUS_PASS = "pass"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"

_BADGE = {
    STATUS_IDLE: "⚪ idle",
    STATUS_ROUTING: "🟡 routing",
    STATUS_RUNNING: "🟢 running",
    STATUS_REROUTED: "🔵 rerouted",
    STATUS_DONE: "✅ done",
    STATUS_ERROR: "🔴 error",
    STATUS_VALIDATING: "🛰️ validating",
    STATUS_PASS: "✅ pass",
    STATUS_WARN: "⚠️ warn",
    STATUS_FAIL: "❌ fail",
}


@dataclass
class LayerState:
    layer: int
    key: str
    title: str
    status: str = STATUS_IDLE
    last_command: str = ""
    detail: str = ""

    def badge(self) -> str:
        return _BADGE.get(self.status, self.status)


@dataclass
class OrchestratorState:
    layers: dict[int, LayerState] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self):
        for num, (key, title, _agent) in ALL_LAYERS.items():
            self.layers.setdefault(num, LayerState(num, key, title))

    def set_status(self, layer: int, status: str, *, command: str | None = None,
                   detail: str | None = None) -> None:
        with self._lock:
            ls = self.layers[layer]
            ls.status = status
            if command is not None:
                ls.last_command = command
            if detail is not None:
                ls.detail = detail

    def reset_idle(self, exclude: int | None = None) -> None:
        with self._lock:
            for num, ls in self.layers.items():
                if num != exclude:
                    ls.status = STATUS_IDLE

    def append_log(self, line: str) -> None:
        with self._lock:
            self.log.append(line)
            if len(self.log) > 500:
                self.log = self.log[-500:]

    def log_text(self) -> str:
        with self._lock:
            return "\n".join(self.log[-200:])

    def panel_md(self, layer: int) -> str:
        ls = self.layers[layer]
        cmd = ls.last_command or "—"
        detail = ls.detail or ""
        return (
            f"### L{layer} · {ls.title}\n"
            f"**{ls.badge()}**\n\n"
            f"`{cmd}`\n\n{detail}"
        )

    def panel_html(self, layer: int) -> str:
        ls = self.layers[layer]
        cls, col, label, pulse = _STATUS_STYLE.get(
            ls.status, ("st-idle", "#475569", ls.status, ""))
        icon = _LAYER_ICON.get(layer, "")
        cmd = _esc(ls.last_command or "—")
        if len(cmd) > 110:
            cmd = cmd[:110] + "…"
        detail = _esc(ls.detail or "")
        if len(detail) > 420:
            detail = "…" + detail[-420:]
        return (
            f'<div class="layer-card {cls}">'
            f'<div class="lc-title"><span class="dot {pulse}" '
            f'style="background:{col}"></span>{icon} L{layer} · {ls.title}</div>'
            f'<span class="lc-badge" style="background:{col}22;color:{col};'
            f'border:1px solid {col}55">{label}</span>'
            f'<div class="lc-cmd">{cmd}</div>'
            f'<div class="lc-detail">{detail}</div>'
            f'</div>'
        )


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# status -> (card css class, accent color, label, dot pulse class)
_STATUS_STYLE = {
    STATUS_IDLE:       ("st-idle", "#64748b", "idle", ""),
    STATUS_ROUTING:    ("st-running", "#d97706", "routing", "pulse"),
    STATUS_RUNNING:    ("st-running", "#22c55e", "running", "pulse"),
    STATUS_REROUTED:   ("st-rerouted", "#3b82f6", "rerouted", ""),
    STATUS_DONE:       ("st-done", "#16a34a", "done", ""),
    STATUS_ERROR:      ("st-error", "#ef4444", "error", ""),
    STATUS_VALIDATING: ("st-running", "#06b6d4", "validating", "pulse"),
    STATUS_PASS:       ("st-done", "#16a34a", "pass", ""),
    STATUS_WARN:       ("st-rerouted", "#d97706", "warn", ""),
    STATUS_FAIL:       ("st-error", "#ef4444", "fail", ""),
}
_LAYER_ICON = {0: "🛰️", 1: "📦", 2: "🧠", 3: "🎭", 4: "⚙️"}
