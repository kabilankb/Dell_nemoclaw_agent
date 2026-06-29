"""Node-graph workflow loader for the agent orchestrator.

A *workflow* is a no-code, drag-and-drop description of the orchestration as a
graph of **agent nodes** wired by **edges**, instead of four hard-coded layers.
A visual editor would serialize exactly this YAML: every node is an agent box on
a canvas (with an x/y position), every edge is a wire between two ports.

Two edge kinds:
  * ``route``   — from the trigger node to an agent node, taken when the command
                  matches that node's ``match`` keywords (the entry routing).
  * ``reroute`` — a handoff wire between agent nodes, taken when an agent emits
                  the ``@@REROUTE: <signal>`` token (see runner.REROUTE_TOKEN).

This module only *reads* the graph; it stays dependency-light (config + yaml)
so it can back both the running orchestrator (router consults it when
``routing.use_workflow`` is on) and an external canvas/validator.

Run ``python -m agent_orchestrator.workflow`` to validate + render the graph.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import REPO_ROOT, PKG_ROOT, cfg

DEFAULT_WORKFLOW = PKG_ROOT / "workflows" / "default.workflow.yaml"


# --- graph model ------------------------------------------------------------
@dataclass
class Node:
    id: str
    type: str                      # "trigger" | "agent"
    title: str = ""
    key: str = ""                  # routing key (assets/rl/il/exec) for agent nodes
    layer: int | None = None       # bridge to the layer-based execution loop
    agent: str = ""                # palette entry name -> agent .md file
    position: dict = field(default_factory=lambda: {"x": 0, "y": 0})
    match: list[tuple[str, float]] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    permission: str = ""
    icon: str = ""
    color: str = ""
    default: bool = False          # the fall-through agent node when nothing matches


@dataclass
class Edge:
    src: str
    dst: str
    type: str = "route"            # "route" | "reroute"
    signal: str = ""               # reroute signal value (assets/rl/il)
    default: bool = False          # the fall-through route edge


@dataclass
class Workflow:
    name: str
    description: str
    nodes: dict[str, Node]
    edges: list[Edge]
    agents: dict[str, dict]        # palette: name -> {file, color, icon, ...}
    settings: dict

    # -- traversal --------------------------------------------------------
    def trigger(self) -> Node | None:
        for n in self.nodes.values():
            if n.type == "trigger":
                return n
        return None

    def agent_nodes(self) -> list[Node]:
        return [n for n in self.nodes.values() if n.type == "agent"]

    def supervisor_node(self) -> Node | None:
        """The L0 master/supervisor node (Atlas), if the graph defines one. It is
        never a route target — it wraps the run and validates whichever worker
        executed (see validator.py)."""
        for n in self.nodes.values():
            if n.type == "supervisor":
                return n
        return None

    def default_node(self) -> Node | None:
        for n in self.agent_nodes():
            if n.default:
                return n
        return None

    def route(self, command: str) -> tuple[Node | None, dict[str, float]]:
        """Score agent nodes by their match patterns; return (winner, scores)."""
        text = command.lower()
        scores: dict[str, float] = {}
        for n in self.agent_nodes():
            s = 0.0
            for pattern, weight in n.match:
                if re.search(pattern, text):
                    s += weight
            scores[n.id] = s
        if not scores:
            return None, scores
        best = max(scores, key=lambda k: scores[k])
        if scores[best] <= 0:
            return self.default_node(), scores
        return self.nodes[best], scores

    def reroute(self, signal: str) -> Node | None:
        """Follow a reroute wire for the given signal value."""
        sig = signal.strip().lower()
        for e in self.edges:
            if e.type == "reroute" and e.signal.lower() == sig:
                return self.nodes.get(e.dst)
        # also accept a bare node key (assets/rl/il/exec)
        for n in self.agent_nodes():
            if n.key == sig:
                return n
        return None

    # -- bridges for the layer-based router/loop --------------------------
    def signals_by_layer(self) -> dict[int, list[tuple[str, float]]]:
        out: dict[int, list[tuple[str, float]]] = {}
        for n in self.agent_nodes():
            if n.layer:
                out[n.layer] = list(n.match)
        return out

    def reroute_targets(self) -> dict[str, int]:
        return {n.key: n.layer for n in self.agent_nodes() if n.key and n.layer}

    def default_layer(self) -> int | None:
        n = self.default_node()
        return n.layer if n else None

    # -- validation + rendering ------------------------------------------
    def validate(self) -> list[str]:
        issues: list[str] = []
        ids = set(self.nodes)
        if not self.trigger():
            issues.append("no trigger node (type: trigger)")
        if not self.agent_nodes():
            issues.append("no agent nodes")
        if len([n for n in self.agent_nodes() if n.default]) != 1:
            issues.append("exactly one agent node must be default: true")
        for e in self.edges:
            if e.src not in ids:
                issues.append(f"edge from unknown node {e.src!r}")
            if e.dst not in ids:
                issues.append(f"edge to unknown node {e.dst!r}")
        checkable = self.agent_nodes()
        sup = self.supervisor_node()
        if sup:
            checkable = [*checkable, sup]
        for n in checkable:
            palette = self.agents.get(n.agent)
            if not palette:
                issues.append(f"node {n.id!r} references unknown agent {n.agent!r}")
                continue
            ref = palette.get("file", "")
            p = (REPO_ROOT / ref) if ref else None
            if not p or not p.exists():
                issues.append(f"agent file missing for {n.agent!r}: {ref}")
        return issues

    def describe(self) -> str:
        lines = [f"workflow: {self.name}", f"  {self.description}", ""]
        trig = self.trigger()
        lines.append(f"trigger: {trig.id} ({trig.title})" if trig else "trigger: <none>")
        sup = self.supervisor_node()
        if sup:
            lines.append(f"supervisor: {sup.icon} {sup.id} L{sup.layer} "
                         f"({sup.title}) — validates workers, never routed")
        lines.append("agent nodes:")
        for n in self.agent_nodes():
            star = " *default" if n.default else ""
            top = sorted(n.match, key=lambda kv: kv[1], reverse=True)[:4]
            kw = ", ".join(p.strip("\\b").replace("\\", "") for p, _ in top)
            lines.append(f"  {n.icon} {n.id:<8} L{n.layer} key={n.key:<7} "
                         f"@({n.position.get('x')},{n.position.get('y')}){star}")
            lines.append(f"      match: {kw} …")
        lines.append("edges:")
        _arrows = {"dispatch": "⇒⇒", "route": "──▶", "reroute": "↪↪", "validate": "✓✓"}
        for e in self.edges:
            arrow = _arrows.get(e.type, "──")
            tag = f" [{e.signal}]" if e.signal else (" [default]" if e.default else "")
            lines.append(f"  {e.src:>8} {arrow} {e.dst:<8} ({e.type}){tag}")
        return "\n".join(lines)


# --- loading ----------------------------------------------------------------
def _parse_match(raw) -> list[tuple[str, float]]:
    """Accept ['kw', {'\\bppo\\b': 2}, ...] -> [(pattern, weight), ...]."""
    out: list[tuple[str, float]] = []
    for item in raw or []:
        if isinstance(item, dict):
            for pattern, weight in item.items():
                out.append((str(pattern), float(weight)))
        else:
            out.append((str(item), 1.0))
    return out


def _from_dict(data: dict, name_fallback: str = "workflow") -> Workflow:
    nodes: dict[str, Node] = {}
    for raw in data.get("nodes", []):
        nid = raw["id"]
        nodes[nid] = Node(
            id=nid,
            type=raw.get("type", "agent"),
            title=raw.get("title", nid),
            key=raw.get("key", ""),
            layer=raw.get("layer"),
            agent=raw.get("agent", ""),
            position=raw.get("position", {"x": 0, "y": 0}),
            match=_parse_match(raw.get("match")),
            tools=raw.get("tools", []),
            permission=raw.get("permission", ""),
            icon=raw.get("icon", ""),
            color=raw.get("color", ""),
            default=bool(raw.get("default", False)),
        )
    edges = [
        Edge(src=e["from"], dst=e["to"], type=e.get("type", "route"),
             signal=e.get("signal", ""), default=bool(e.get("default", False)))
        for e in data.get("edges", [])
    ]
    return Workflow(
        name=data.get("name", name_fallback),
        description=data.get("description", ""),
        nodes=nodes,
        edges=edges,
        agents=data.get("agents", {}),
        settings=data.get("settings", {}),
    )


def load(path: str | Path | None = None) -> Workflow:
    p = Path(path).expanduser() if path else DEFAULT_WORKFLOW
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    data = yaml.safe_load(p.read_text()) or {}
    return _from_dict(data, p.stem)


def load_dict(data: dict) -> Workflow:
    """Build a Workflow from a plain dict (e.g. JSON from the visual editor)."""
    return _from_dict(data, data.get("name", "workflow"))


def load_default() -> Workflow:
    """Load the workflow the running orchestrator should use (config-driven)."""
    return load(cfg("routing.workflow") or DEFAULT_WORKFLOW)


# --- serialization (graph -> YAML, for the visual editor's Save) ------------
def to_dict(wf: Workflow) -> dict:
    """Round-trippable plain dict (same shape as a .workflow.yaml file)."""
    def node_d(n: Node) -> dict:
        d: dict = {"id": n.id, "type": n.type, "title": n.title}
        if n.key:
            d["key"] = n.key
        if n.layer is not None:
            d["layer"] = n.layer
        if n.agent:
            d["agent"] = n.agent
        if n.default:
            d["default"] = True
        if n.permission:
            d["permission"] = n.permission
        if n.tools:
            d["tools"] = list(n.tools)
        if n.icon:
            d["icon"] = n.icon
        if n.color:
            d["color"] = n.color
        d["position"] = {"x": n.position.get("x", 0), "y": n.position.get("y", 0)}
        if n.match:
            d["match"] = [{p: w} for p, w in n.match]
        return d

    def edge_d(e: Edge) -> dict:
        d = {"from": e.src, "to": e.dst, "type": e.type}
        if e.signal:
            d["signal"] = e.signal
        if e.default:
            d["default"] = True
        return d

    return {
        "name": wf.name,
        "description": wf.description,
        "agents": wf.agents,
        "nodes": [node_d(n) for n in wf.nodes.values()],
        "edges": [edge_d(e) for e in wf.edges],
        "settings": wf.settings,
    }


def dump(wf: Workflow | dict, path: str | Path) -> Path:
    """Write a workflow (or its dict) to a .workflow.yaml file."""
    data = to_dict(wf) if isinstance(wf, Workflow) else wf
    p = Path(path).expanduser()
    if not p.is_absolute():
        p = (REPO_ROOT / p).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))
    return p


def main() -> None:
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else None
    wf = load(path)
    print(wf.describe())
    issues = wf.validate()
    print("\nvalidation:", "OK ✓" if not issues else "")
    for i in issues:
        print(f"  ✗ {i}")
    if len(sys.argv) > 2:  # optional: route a test command
        node, scores = wf.route(sys.argv[2])
        ranked = ", ".join(f"{k}={v:.1f}" for k, v in
                            sorted(scores.items(), key=lambda x: -x[1]) if v)
        print(f"\nroute({sys.argv[2]!r}) -> "
              f"{node.id if node else '∅'}   scores[{ranked}]")


if __name__ == "__main__":
    main()
