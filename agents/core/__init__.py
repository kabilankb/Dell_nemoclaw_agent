"""Isaac Sim / Isaac Lab multi-layer agent orchestrator.

Layers:
  L1  Asset Placement   (agent_orchestrator/.. orch-l1-asset-placement)
  L2  RL Authoring       (orch-l2-rl-author)
  L3  Imitation Learning (orch-l3-il-author)
  L4  Execution + reroute (orch-l4-executor)

Public surface used by the Gradio app and CLI.
"""
from .config import SETTINGS, Settings  # noqa: F401
from . import catalog, router, state, agents, runner, orchestrate  # noqa: F401

__all__ = [
    "SETTINGS", "Settings",
    "catalog", "router", "state", "agents", "runner", "orchestrate",
]
