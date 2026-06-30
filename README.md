# isaac-claw

One repo for driving **NVIDIA Isaac Sim** (simulator) and **Isaac Lab** (RL/IL)
from a local-model TUI — **NemoClaw** (Nemotron) and **OpenClaw** (Gemma & other
open models). It consolidates four previously-overlapping projects
(`humanoid_nemoclaw`, `leisaac`, `warehouse_nemoclaw`, the NemoClaw/OpenClaw
runtimes) into one readable layout where a 30B-class local model can navigate by
folder name.

The actual simulators are **referenced, not vendored** — set `$ISAAC_SIM_DIR`
(`~/IsaacSim`) and `$ISAAC_LAB_DIR` (`~/IsaacLab`). This repo holds only the
custom extension code, scenes, skills, policies, and agent glue.

> 📁 **[STRUCTURE.md](STRUCTURE.md)** — full annotated layout + runtime-flow diagram.
> 🕒 **[HISTORY.md](HISTORY.md)** — complete development history (what was built and why).

## Layout
```
isaac-claw/
├── agents/              # the TUI runtimes — differ in MODEL CONFIG, not code
│   ├── core/            #   shared 4-layer orchestrator (single source of truth)
│   ├── nemoclaw/        #   Nemotron profile + sandbox agent package
│   └── openclaw/        #   Gemma/open-model config + skill-deploy
├── skills/              # model-facing skill library
│   ├── skills.md        #   ⟵ MASTER ROUTER (load first)   [Goal 5]
│   ├── task/            #   open environment + robot from a prompt  [Goal 2]
│   ├── training/        #   RL training control
│   ├── teleop/          #   SO101 robot control
│   ├── mimicgen/        #   imitation-learning data pipeline
│   └── <22 more>        #   physics, sensors, rendering, nav, USD, ROS, meta…
├── isaac_lab/           # Isaac Lab side (your code; sim referenced via $ISAAC_LAB_DIR)
│   ├── source/robot_lab/#   pip-installable extension (50 envs, kept nesting)
│   ├── source/leisaac/  #   SO101 devices/tasks (teleop, vision)
│   ├── scripts/         #   train / play / teleop / annotate / inference / convert
│   └── envs_registry.json #  canonical task list served by the control server
├── isaac_sim/           # Isaac Sim side
│   ├── source/          #   isaacsim.code_editor.python_server extension (port 8226)
│   ├── scenes/          #   warehouse.usd + textures (gitignored, regenerable)
│   └── scripts/         #   build/launch scene, RL task, isaac_control_server.py
├── policies/            # hyperparameter control panel               [Goal 3]
│   ├── policy_skill.md  #   ⟵ MASTER tuning router
│   └── rsl_rl|rl_games|skrl|sb3|robomimic.md
├── research_papers/     # one folder per paper (paper.pdf + notes.md)
└── sandbox/             # network policies + sandbox-side clients     [Goal 1/4]
    ├── policies/        #   egress allowlists (deny-by-default)
    └── clients/         #   isaaclab-train / isaaclab-send|pick|place|detect
```

## How it works (the five goals)

**Goal 1 — both runtimes operate Sim & Lab.** Every Isaac action goes through one
host API, [`isaac_sim/scripts/isaac_control_server.py`](isaac_sim/scripts/isaac_control_server.py)
(port 5561): `GET /envs /scenes /robots /status /logs`, `POST /sim/launch
/scene/load /robot/spawn /exec /train /play /eval /stop`. The sandbox reaches it
through a whitelisted policy; the simulator doesn't care which model is driving.
This generalizes the old training-only server into a full Sim+Lab control surface.

**Goal 2 — open env + robot from a prompt.** A sentence like *"open the warehouse
with a Unitree G1"* → the model loads [`skills/skills.md`](skills/skills.md),
matches [`skills/task/`](skills/task/SKILL.md), and issues `POST /sim/launch` then
`POST /robot/spawn` (robot resolved from `agents/core/assets/catalog.yaml`).

**Goal 3 — one tuning control panel.** [`policies/policy_skill.md`](policies/policy_skill.md)
routes to per-framework files (RSL-RL, rl_games, skrl, SB3, robomimic). Each has a
single fenced-YAML knob block (with safe ranges + a symptom→fix table) that the
launcher parses and the model edits.

**Goal 4 — readable structure.** The four old repos collapse into the tree above;
OpenClaw vs NemoClaw differ only under `agents/` (model config), sharing
`agents/core/`. A model navigates by folder name.

**Goal 5 — master skill router.** [`skills/skills.md`](skills/skills.md) lists
every skill with purpose + trigger keywords + the endpoint it drives, plus
chaining pipelines — the model-facing table of contents.

## Quick start
```bash
export ISAAC_CLAW_DIR=$PWD ISAAC_SIM_DIR=~/IsaacSim ISAAC_LAB_DIR=~/IsaacLab
export ISAAC_LAB_PYTHON=~/miniforge3/envs/env_isaaclab/bin/python

# 1. start the host control server (run in your own GPU terminal)
$ISAAC_LAB_PYTHON isaac_sim/scripts/isaac_control_server.py

# 2a. drive it with OpenClaw (Gemma)        — see agents/openclaw/README.md
openclaw tui
# 2b. or NemoClaw (Nemotron, sandboxed)     — see agents/nemoclaw/README.md
nemoclaw <sandbox> connect && openclaw tui
```

> ⚠️ GPU launches (Isaac Sim, training) must run in a real terminal, not inside a
> tool-call shell. The control server spawns them as host subprocesses on purpose.

## Provenance
Assembled non-destructively by copy/repurpose; the four source repos are left
intact. See each subdirectory's README for what came from where.
