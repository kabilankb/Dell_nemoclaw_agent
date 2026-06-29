"""Load the 4 layer agent definitions from .claude/agents/*.md.

Single source of truth: the same markdown files Claude Code discovers natively
are parsed here into AgentLayer objects the SDK runner turns into system prompts.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .config import REPO_ROOT
from .router import ALL_LAYERS

AGENTS_DIR = REPO_ROOT / ".claude" / "agents"

# Per-layer execution policy. Generation layers only edit files; the executor
# needs to launch processes, so it gets a broader permission mode. L0 (Atlas)
# only reads/validates and may write a small report — never launches training.
_PERMISSION = {
    0: "acceptEdits",
    1: "acceptEdits",
    2: "acceptEdits",
    3: "acceptEdits",
    4: "bypassPermissions",  # L4 runs Bash (training/teleop); gate via UI toggle
}
_ALLOWED_TOOLS = {
    0: ["Read", "Write", "Glob", "Grep", "Bash", "Skill"],
    1: ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill"],
    2: ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch", "Skill"],
    3: ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "WebSearch", "WebFetch", "Skill"],
    4: ["Read", "Write", "Edit", "Glob", "Grep", "Bash", "Skill"],
}


@dataclass
class AgentLayer:
    layer: int
    name: str
    description: str
    system_prompt: str
    allowed_tools: list[str]
    permission_mode: str


def _parse_md(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    if text.startswith("---"):
        _, fm, body = text.split("---", 2)
        return yaml.safe_load(fm) or {}, body.strip()
    return {}, text.strip()


@lru_cache(maxsize=1)
def load_layers() -> dict[int, AgentLayer]:
    out: dict[int, AgentLayer] = {}
    for num, (_key, _title, agent_name) in ALL_LAYERS.items():
        path = AGENTS_DIR / f"{agent_name}.md"
        fm, body = _parse_md(path)
        out[num] = AgentLayer(
            layer=num,
            name=fm.get("name", agent_name),
            description=" ".join(str(fm.get("description", "")).split()),
            system_prompt=body,
            allowed_tools=_ALLOWED_TOOLS[num],
            permission_mode=_PERMISSION[num],
        )
    return out


def get_layer(num: int) -> AgentLayer:
    return load_layers()[num]
