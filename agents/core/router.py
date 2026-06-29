"""Command router: classify a natural-language command to one of the 4 layers
and encode the reroute rules between them.

This is a fast, deterministic keyword classifier that gives the UI instant
routing feedback. The selected layer agent then does the deep work; Layer 4 can
emit a reroute signal (see runner.REROUTE_TOKEN) that this module validates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Canonical layer registry ---------------------------------------------------
# LAYERS holds only the *routable* worker layers (1-4). The Master Supervisor
# (Atlas, L0) is registered separately below — it is never auto-routed to; it
# wraps the loop and validates whichever worker ran.
LAYERS = {
    1: ("assets", "Asset Placement", "orch-l1-asset-placement"),
    2: ("rl", "RL Authoring", "orch-l2-rl-author"),
    3: ("il", "Imitation Learning Authoring", "orch-l3-il-author"),
    4: ("exec", "Execution", "orch-l4-executor"),
}
KEY_TO_LAYER = {v[0]: k for k, v in LAYERS.items()}

# Layer 0 — the master agent: receives the request, dispatches to a slave,
# validates the slave's output, and returns the result to the user.
SUPERVISOR_LAYER = 0
SUPERVISOR = ("supervisor", "Isaac Robot Orchestrator · Master",
              "isaac-robot-orchestrator-master-agent")
# Every layer including L0, for panels / agent loading (NOT for routing).
ALL_LAYERS = {SUPERVISOR_LAYER: SUPERVISOR, **LAYERS}

# Weighted keyword signals per layer. Higher weight = stronger signal.
_SIGNALS: dict[int, list[tuple[str, float]]] = {
    1: [
        (r"\bplace\b", 2), (r"\bspawn\b", 2), (r"\badd\b", 1.2), (r"\bput\b", 1.5),
        (r"\bposition\b", 1.5), (r"\barrange\b", 1.5), (r"\bremove\b", 1.2),
        (r"\bscene\b", 1.2), (r"\bwarehouse\b", 1), (r"\brack\b", 1),
        (r"\barticulation\b", 1.5), (r"\busd\b", 1.5), (r"\bprim\b", 1.2),
        (r"\bassets?\b", 1.5), (r"\bground\b|\bfloor\b", 0.8), (r"\benvironment\b", 1),
        (r"\blayout\b", 1.2), (r"\bgrid\b", 0.8),
        # catalog lookups ("what robots/assets are available") are L1's too.
        (r"\bcatalog\b", 1.5), (r"\brobots?\b", 0.8), (r"\bavailable\b", 0.8),
        (r"\bwhich\b|\bwhat\b.*\b(robot|asset|prop|sensor|model)s?\b", 0.8),
    ],
    2: [
        (r"\brl\b", 2.5), (r"reinforcement", 2.5), (r"\breward", 2),
        (r"\bppo\b|\bsac\b|\btd3\b|\bdqn\b", 2), (r"rsl[_-]?rl|skrl|rl[_-]?games|sb3", 2),
        (r"\bpolicy\b", 1), (r"gym\s*env|environment\s*cfg|\benvcfg\b", 1.2),
        (r"\bobservation", 1), (r"\baction space", 1.2), (r"curriculum", 1.2),
        (r"\bterminations?\b", 1), (r"manager[- ]based", 1.2),
    ],
    3: [
        (r"imitation", 2.5), (r"\bil\b", 2), (r"\blerobot\b", 2.5),
        (r"beh(?:av(?:ior|iour))?\s*clon|\bbc\b", 2), (r"diffusion policy", 2),
        (r"\bact\b\s*policy|\bact\b\s*model", 1.5), (r"\bmimic\b|robomimic|isaaclab_mimic", 2),
        (r"demonstrations?\b", 1.2), (r"\bdataset\b.*(annotat|generat)", 1),
        (r"\bteleop\b.*record|record.*\bteleop\b", 1.2),
    ],
    4: [
        (r"\btrain\b", 2), (r"\brun\b", 1.5), (r"\bexecute\b", 2), (r"\blaunch\b", 1.5),
        (r"\bplay\b", 1.5), (r"\binference\b|\beval", 1.8), (r"\brollout", 1.5),
        (r"collect.*(dataset|demos|data)", 2), (r"record.*demos?", 2),
        (r"\bteleop(?:erat)?", 1.8), (r"\bcheckpoint\b", 1), (r"resume training", 1.5),
        (r"how many (?:steps|iterations)|num_envs", 0.8),
    ],
}


@dataclass
class Routing:
    layer: int
    key: str
    title: str
    agent: str
    confidence: float
    scores: dict[int, float]
    matched: list[str] = field(default_factory=list)

    def explain(self) -> str:
        ranked = sorted(self.scores.items(), key=lambda x: x[1], reverse=True)
        bits = ", ".join(f"L{l}={s:.1f}" for l, s in ranked if s > 0)
        why = ("matched: " + ", ".join(self.matched)) if self.matched else "no strong keywords → default"
        return f"→ L{self.layer} ({self.title}) [{why}]  scores[{bits}]"


def classify(command: str, default_layer: int = 4) -> Routing:
    text = command.lower()
    scores: dict[int, float] = {k: 0.0 for k in LAYERS}
    matched: dict[int, list[str]] = {k: [] for k in LAYERS}
    for layer, sigs in _SIGNALS.items():
        for pattern, weight in sigs:
            if re.search(pattern, text):
                scores[layer] += weight
                matched[layer].append(pattern.strip("\\b").replace("\\", ""))

    best = max(scores, key=lambda k: scores[k])
    if scores[best] == 0:
        best = default_layer
    total = sum(scores.values()) or 1.0
    conf = scores[best] / total
    key, title, agent = LAYERS[best]
    return Routing(best, key, title, agent, conf, scores, matched[best])


# Reroute rules (used by Layer 4 / the orchestration loop) -------------------
REROUTE_TARGETS = {"assets": 1, "rl": 2, "il": 3, "exec": 4}


def resolve_reroute(target: str) -> int | None:
    """Map a reroute signal value (e.g. 'rl', 'assets', '2') to a layer number."""
    t = target.strip().lower()
    if t.isdigit() and int(t) in LAYERS:
        return int(t)
    return REROUTE_TARGETS.get(t)


# Optional: source the routing signals + reroute map from a no-code workflow
# graph (agent_orchestrator/workflows/*.workflow.yaml) instead of the tables
# above. Off unless routing.use_workflow is set in orchestrator.yaml; any load
# error silently keeps the built-in defaults, so this never breaks startup.
def apply_workflow(path=None):
    """Override the routing signals + reroute map from a workflow graph file.

    Returns the loaded Workflow (or None on failure). Used by the visual editor
    to route a command through a specific saved graph, and at import time for the
    config-selected default.
    """
    try:
        from .workflow import load, load_default
        wf = load(path) if path else load_default()
        sig = wf.signals_by_layer()
        if sig:
            _SIGNALS.clear()
            _SIGNALS.update(sig)
        targets = wf.reroute_targets()
        if targets:
            REROUTE_TARGETS.clear()
            REROUTE_TARGETS.update(targets)
        return wf
    except Exception:  # noqa: BLE001 - bad workflow must not break routing
        return None


def _apply_workflow_overrides() -> None:
    from .config import cfg  # lazy: avoid import cycle at module load
    if cfg("routing.use_workflow", False):
        apply_workflow()


_apply_workflow_overrides()
