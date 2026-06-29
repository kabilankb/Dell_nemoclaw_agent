---
name: isaac-agent-orchestrator
description: >
  Drive the Isaac Sim / Isaac Lab robot orchestrator from a NemoClaw sandbox. A
  master agent (isaac-robot-orchestrator-master-agent) receives the request,
  dispatches it to a slave — asset agent, RL task-script+validation agent, IL
  task-script+validation agent, or execution agent — validates the result, and
  returns it. Use when the user wants to place USD assets/robots, author/validate
  an RL training script, author/validate an imitation-learning pipeline (Isaac Lab
  Mimic / robomimic / LeRobot), or execute training / dataset collection /
  inference / teleoperation. Trigger on "place / spawn / arrange a robot", "write
  an RL reward", "behavior cloning / lerobot task", "train / run / collect demos /
  teleoperate".
metadata:
  {
    "nemoclaw": { "emoji": "🤖", "requires": { "bins": ["python3"] } },
    "openclaw": { "emoji": "🤖", "requires": { "bins": ["python3"] } }
  }
---

# Isaac Agent Orchestrator (NemoClaw bridge)

This skill exposes the multi-layer Isaac Sim/Lab orchestrator that lives at
`/home/dgx-destro/warehouse_nemoclaw/agent_orchestrator`. It has its own isolated
venv (`agent_orchestrator/.venv`) because its UI deps conflict with the base
env's `lerobot`/`transformers`.

NemoClaw runs **always-on NIM sandboxes**, not one-shot local agents. This skill
is deployed *into* a sandbox with `nemoclaw <sandbox> skill install`, so the
sandbox's agent can dispatch the orchestrator. The orchestrator repo must be
reachable **inside** the sandbox at `$ORCHESTRATOR_DIR` — mount it if it is not:
```bash
nemoclaw <sandbox> share mount /home/dgx-destro/warehouse_nemoclaw  /work/warehouse_nemoclaw
```

Paths (override via the env block when they move):
- `ORCHESTRATOR_DIR = /home/dgx-destro/warehouse_nemoclaw` (host) — set to the
  sandbox mount point if different inside the sandbox.
- `ORCH_PY = $ORCHESTRATOR_DIR/agent_orchestrator/.venv/bin/python`

## Master + slaves
The **master agent** (`isaac-robot-orchestrator-master-agent`, L0) receives the
request, dispatches it to one slave, validates the slave's output, and returns the
result. Its slaves:

1. **Asset agent** (L1) — resolves names from the common catalog
   (`agent_orchestrator/assets/catalog.yaml`) and places/arranges USD assets &
   robots with correct transforms + articulation.
2. **RL task-script + validation agent** (L2) — writes **and self-validates** Isaac
   Lab RL env cfgs, rewards, PPO configs (pulls from `$ISAAC_LAB_DIR` + NVIDIA docs).
3. **IL task-script + validation agent** (L3) — writes **and self-validates**
   BC/ACT/diffusion pipelines via Isaac Lab Mimic / robomimic / **LeRobot**.
4. **Execution agent** (L4) — runs the RL/IL scripts (train, collect, infer,
   teleop) and **reroutes** to the asset/RL/IL agent when content must change.

## How to use

**Preview routing only** (no model call, free — confirm before a heavy run):
```bash
cd "$ORCHESTRATOR_DIR"
python -m agent_orchestrator.cli --classify "<user request>"
```

**Dispatch from the host, executing each layer inside a NemoClaw sandbox**
(`--backend nemoclaw` requires `$NEMOCLAW_SANDBOX`; the in-sandbox agent CLI is
`$NEMOCLAW_AGENT_CMD`, default `claude -p`):
```bash
cd "$ORCHESTRATOR_DIR"
NEMOCLAW_SANDBOX=robotcontrol \
  python -m agent_orchestrator.cli "<user request>" --backend nemoclaw --allow-execution
```

**Dispatch from inside the sandbox** (the orchestrator runs locally there; use
the SDK or OpenClaw backend the sandbox already has credentials for):
```bash
cd "$ORCHESTRATOR_DIR"
"$ORCH_PY" -m agent_orchestrator.cli "<user request>" --backend sdk --allow-execution
```
Other backends: `--backend dryrun` (plan only). Force a layer with `--layer 1|2|3|4`.

**Browse the Layer-1 asset store:**
```bash
cd "$ORCHESTRATOR_DIR"
"$ORCH_PY" -c "from agent_orchestrator import catalog; print(catalog.markdown_table())"
```

## Routing cheatsheet (what goes where)
- "place / spawn / arrange / remove / articulation / usd / scene" → **L1**
- "rl / reward / ppo / gym env / rsl_rl / policy cfg" → **L2**
- "imitation / behavior cloning / lerobot / mimic / robomimic / act / diffusion" → **L3**
- "train / run / play / inference / collect dataset / record demos / teleop" → **L4**

The `--classify` call is free — use it to confirm routing before dispatching a
heavy run. Env contract carried to every layer: `$ISAAC_SIM_DIR`,
`$ISAAC_LAB_DIR`, `$WORKSPACE_DIR`.
