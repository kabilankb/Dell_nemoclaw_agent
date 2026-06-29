"""Environment + path contract for the Isaac agent orchestrator.

Honors the repo's env-var contract (`$ISAAC_SIM_DIR`, `$ISAAC_LAB_DIR`,
`$WORKSPACE_DIR`) documented in skills/SKILLS.md, falling back to the standard
local install locations discovered on this machine.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PKG_ROOT = Path(__file__).resolve().parent

# No-code setup file (see orchestrator.yaml). Optional: if absent or unparseable
# every value falls back to the built-in default. Override the path via
# $ORCH_CONFIG. Precedence everywhere: env var > this file > built-in default.
CONFIG_PATH = Path(
    os.environ.get("ORCH_CONFIG") or (PKG_ROOT / "orchestrator.yaml")
).expanduser()


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        import yaml  # noqa: PLC0415 - optional dependency, already required by pkg
        with open(CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001 - a bad config must never crash startup
        return {}


_CFG = _load_config()


def cfg(path: str, default=None):
    """Read a dotted key from orchestrator.yaml, e.g. cfg('runtime.backend')."""
    cur = _CFG
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return default if cur is None else cur


def _first_existing(*candidates: str | os.PathLike) -> Path | None:
    for c in candidates:
        if c and Path(c).expanduser().exists():
            return Path(c).expanduser()
    return None


def _resolve_workspace() -> Path:
    raw = (os.environ.get("WORKSPACE_DIR")
           or cfg("environment.workspace_dir")
           or (PKG_ROOT / "workspace"))
    p = Path(raw).expanduser()
    if not p.is_absolute():           # repo-relative values resolve against the repo
        p = (REPO_ROOT / p).resolve()
    return p


@dataclass
class Settings:
    """Resolved environment for every layer agent."""

    isaac_sim_dir: Path | None = field(
        default_factory=lambda: _first_existing(
            os.environ.get("ISAAC_SIM_DIR", ""),
            cfg("environment.isaac_sim_dir", ""),
            Path.home() / "IsaacSim",
            REPO_ROOT / "_build/linux-x86_64/release",
        )
    )
    isaac_lab_dir: Path | None = field(
        default_factory=lambda: _first_existing(
            os.environ.get("ISAAC_LAB_DIR", ""),
            cfg("environment.isaac_lab_dir", ""),
            Path.home() / "IsaacLab",
        )
    )
    workspace_dir: Path = field(default_factory=_resolve_workspace)
    model: str = os.environ.get("ORCH_MODEL") or cfg("model.id", "claude-opus-4-8")
    # When set, the SDK executor runs; otherwise the UI falls back to dry-run.
    dry_run_default: bool = (
        os.environ.get("ORCH_DRY_RUN", "0") == "1" or bool(cfg("runtime.dry_run", False))
    )
    # Default backend / runtime knobs (env var still overrides at call sites).
    backend: str = (os.environ.get("ORCH_BACKEND") or cfg("runtime.backend", "") or "").lower()
    allow_execution_default: bool = bool(cfg("runtime.allow_execution", False))
    max_turns: int = int(cfg("runtime.max_turns", 30))
    # No-match fallback. L1 (asset/catalog) is read-friendly; never default to
    # L4, which can run Bash. When supervised, Atlas re-decides ambiguous cases.
    default_layer: int = int(cfg("routing.default_layer", 1))
    max_hops: int = int(cfg("routing.max_hops", 4))
    # Master Supervisor (Atlas, L0): validate every worker layer's execution.
    supervise_default: bool = (
        os.environ.get("ORCH_SUPERVISE", "1") != "0"
        and bool(cfg("supervision.enabled", True))
    )
    supervisor_use_llm: bool = bool(cfg("supervision.use_llm", True))
    max_retries: int = int(cfg("supervision.max_retries", 2))

    def backend_config(self, name: str) -> dict:
        """Per-backend settings block from orchestrator.yaml (backends.<name>)."""
        return dict(cfg(f"backends.{name}", {}) or {})

    def as_env(self) -> dict[str, str]:
        """Env dict passed to spawned agents/subprocesses."""
        env = dict(os.environ)
        if self.isaac_sim_dir:
            env["ISAAC_SIM_DIR"] = str(self.isaac_sim_dir)
        if self.isaac_lab_dir:
            env["ISAAC_LAB_DIR"] = str(self.isaac_lab_dir)
        env["WORKSPACE_DIR"] = str(self.workspace_dir)
        # Let the config supply the key only when the environment doesn't.
        key = cfg("auth.anthropic_api_key")
        if key and not env.get("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = str(key)
        return env

    def ensure_workspace(self) -> Path:
        for sub in ("generated/rl", "generated/il", "runs", "datasets", "logs"):
            (self.workspace_dir / sub).mkdir(parents=True, exist_ok=True)
        return self.workspace_dir

    def summary(self) -> str:
        return (
            f"ISAAC_SIM_DIR = {self.isaac_sim_dir or 'NOT FOUND'}\n"
            f"ISAAC_LAB_DIR = {self.isaac_lab_dir or 'NOT FOUND'}\n"
            f"WORKSPACE_DIR = {self.workspace_dir}\n"
            f"model         = {self.model}"
        )


SETTINGS = Settings()
