"""Layer-1 common asset store: load, browse, and resolve catalog entries.

The catalog (assets/catalog.yaml) is the single categorized store the asset
placement agent consults to turn a friendly name ("nova carter", "warehouse")
into a resolvable USD path plus placement hints.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from .config import REPO_ROOT, PKG_ROOT

CATALOG_PATH = PKG_ROOT / "assets" / "catalog.yaml"


@dataclass
class AssetEntry:
    name: str
    category: str
    usd: str
    relative_to: str | None
    attrs: dict

    def resolved_usd(self) -> str:
        """Repo-relative entries become absolute; Nucleus tokens stay symbolic.

        Nucleus tokens ({ISAAC_NUCLEUS_DIR}, ...) are resolved by Isaac Lab at
        sim runtime, so we deliberately leave them intact for the agent to emit
        into a script that runs inside Isaac.
        """
        if self.relative_to == "repo":
            return str((REPO_ROOT / self.usd).resolve())
        return self.usd

    def as_dict(self) -> dict:
        d = {"name": self.name, "category": self.category, "usd": self.usd}
        d.update(self.attrs)
        return d


@lru_cache(maxsize=1)
def _raw() -> dict:
    with open(CATALOG_PATH) as f:
        return yaml.safe_load(f)


def reload() -> None:
    _raw.cache_clear()


def categories() -> list[str]:
    return list(_raw().get("categories", {}).keys())


def entries(category: str | None = None) -> list[AssetEntry]:
    out: list[AssetEntry] = []
    cats = _raw().get("categories", {})
    for cat, items in cats.items():
        if category and cat != category:
            continue
        for name, attrs in (items or {}).items():
            attrs = dict(attrs)
            out.append(
                AssetEntry(
                    name=name,
                    category=cat,
                    usd=attrs.pop("usd", ""),
                    relative_to=attrs.pop("relative_to", None),
                    attrs=attrs,
                )
            )
    return out


def get(name: str) -> AssetEntry | None:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    for e in entries():
        if e.name == key:
            return e
    return None


def find(query: str, n: int = 5) -> list[AssetEntry]:
    """Fuzzy search by name + tags; the placement agent uses this to resolve
    loose phrasing ("carter", "the amr") to a concrete entry."""
    q = query.strip().lower()
    all_entries = entries()
    scored: list[tuple[float, AssetEntry]] = []
    for e in all_entries:
        hay = " ".join([e.name, e.category, " ".join(e.attrs.get("tags", []))]).lower()
        score = 0.0
        if q in e.name:
            score += 2.0
        if q in hay:
            score += 1.0
        for tok in q.split():
            if tok and tok in hay:
                score += 0.5
        score += difflib.SequenceMatcher(None, q, e.name).ratio()
        scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for s, e in scored[:n] if s > 0.4]


def markdown_table(category: str | None = None) -> str:
    rows = ["| Name | Category | Tags | USD |", "|---|---|---|---|"]
    for e in entries(category):
        tags = ", ".join(e.attrs.get("tags", []))
        usd = e.usd if len(e.usd) < 60 else "…" + e.usd[-57:]
        rows.append(f"| `{e.name}` | {e.category} | {tags} | `{usd}` |")
    return "\n".join(rows)


def context_blob() -> str:
    """Compact catalog rendering injected into the L1 agent's prompt."""
    lines = ["# Asset catalog (resolve names from here; do not invent USD paths)"]
    cats = _raw().get("categories", {})
    for cat, items in cats.items():
        lines.append(f"\n## {cat}")
        for name, attrs in (items or {}).items():
            attrs = attrs or {}
            hint = []
            for k in ("drive", "start_z", "separation_m", "scale"):
                if k in attrs:
                    hint.append(f"{k}={attrs[k]}")
            hint_s = f"  ({', '.join(hint)})" if hint else ""
            lines.append(f"- {name}: {attrs.get('usd','')}{hint_s}")
    return "\n".join(lines)
