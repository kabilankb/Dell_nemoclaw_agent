# isaac-claw — Full Structure

Single repo to drive **Isaac Sim** (simulator) and **Isaac Lab** (RL/IL) from a
local-model TUI — **OpenClaw** (Gemma) and **NemoClaw** (Nemotron). The real
simulators are referenced via `$ISAAC_SIM_DIR` / `$ISAAC_LAB_DIR`, not vendored.

## Top level
```
isaac-claw/
├── README.md            # overview + quick start
├── STRUCTURE.md         # this file
├── agents/              # the TUI runtimes + the `claw` control CLI
├── skills/              # model-facing skill library (text instructions)
├── isaac_lab/           # Isaac Lab side: robot_lab + leisaac extensions, RL/IL scripts
├── isaac_sim/           # Isaac Sim side: control server, scene templates, scenes, ext
├── policies/            # hyperparameter tuning docs (per framework)
├── sandbox/             # network egress policies + sandbox-side CLIs
└── research_papers/     # one folder per paper (paper.pdf + notes.md)
```

## The runtime flow (how a TUI prompt becomes a running sim)
```
You type in the OpenClaw TUI:  "open the warehouse with a Unitree G1"
        │
        ▼  the model picks a skill and runs ONE command
skills/task/SKILL.md  ──►  agents/openclaw/claw open --env warehouse --robot unitree_g1 --gui
        │
        ▼  HTTP :5561
isaac_sim/scripts/isaac_control_server.py   (the one host control API)
        │  POST /sim/launch ──► spawns ──►  serve_sim.py  (persistent GPU sim)
        │  POST /robot/spawn ─────────────►  python_server bridge :8226  (in the sim)
        ▼
   Isaac Sim window with the warehouse + robot
```
Close it again: `claw close`  (skills/close/SKILL.md) → `POST /stop` + frees the GPU.

---

## agents/ — runtimes & the control CLI
OpenClaw and NemoClaw differ only in **model config**; shared code lives in `core/`.
```
agents/
├── core/                       # the 4-layer orchestrator (single source of truth)
│   ├── app.py cli.py editor.py # Gradio UI / headless CLI / visual editor
│   ├── orchestrate.py router.py validator.py runner.py agents.py
│   ├── catalog.py              # reads assets/catalog.yaml (robot defaults: usd, start_z, drive)
│   ├── assets/catalog.yaml     # ◄ ROBOT TEMPLATE SOURCE (per-robot height/drive/usd)
│   ├── orchestrator.yaml       # no-code config (backend, model, paths)
│   └── workflows/ web/ workspace/
├── openclaw/                   # ◄ the OpenClaw (Gemma) entry surface — START HERE
│   ├── claw                    # THE control CLI: open/close/train/status/templates...
│   ├── tui.sh                  # launch the TUI (clean session + control server up + DISPLAY)
│   ├── clawup.sh               # idempotent: ensure control server (and optionally a sim) up
│   ├── deploy.sh               # copy operational skills into ~/.openclaw/workspace/skills
│   ├── model.json              # Gemma/Ollama model config
│   └── README.md
└── nemoclaw/                   # Nemotron sandbox runtime
    ├── blueprint-profile.yaml  # Nemotron inference profiles
    ├── agent/ skill/           # sandbox agent + skill packages
    └── install_skill.sh README.md
```
`claw` commands: `open` (launch scene + spawn robots), `close` (stop + free GPU),
`train`, `status`, `templates`, `scenes`, `robots`, `up`.

## skills/ — model-facing instructions
`skills.md` is the master router (full library). For the OpenClaw TUI only the
small **operational set** is deployed as real dirs (see `agents/openclaw/deploy.sh`).
```
skills/
├── skills.md                   # MASTER router over the whole library
│
│   ── operational set (deployed to OpenClaw; each maps to a `claw` action) ──
├── task/        SKILL.md        # open a scene + robot   → claw open --gui
├── close/       SKILL.md        # stop sim/training      → claw close
├── ops/         SKILL.md        # bootstrap / health     → clawup.sh
├── training/    SKILL.md        # RL training control    → claw train
├── teleop/      SKILL.md        # SO101 robot control
├── mimicgen/    SKILL.md        # imitation-learning data pipeline
├── articulation/SKILL.md        # import + validate a robot
│
│   ── reference library (deployed only with deploy.sh --all) ──
├── physics-simulation/ usd-pipeline/ usd-articulation/ usd-composition-architecture/
├── isaac-sim-rendering/ isaac-camera/ isaac-sim-sensor/ data-collection-sim/ mobility-gen/
├── navigation-primitives/ isaac-sim-robot-navigation/ occupancy-map/ isaac-sim-ros2-bridge/
├── manipulation-ik/ spatial-reasoning/ urdf-mjcf-to-usd-conversion/
├── isaac-sim-orchestrator/ isaac-sim-headless-deployment/ isaac-sim-remote/
├── isaac-sim-validator/ isaac-sim-troubleshooting/ profile-isaac-sim/ validation-diff-gifs/
└── meta-skills/ skill-distillation/
```
> OpenClaw's scanner does NOT follow symlinks — `deploy.sh` copies real dirs.

## isaac_lab/ — Isaac Lab side (your code; sim referenced via $ISAAC_LAB_DIR)
```
isaac_lab/
├── envs_registry.json          # canonical task list served by the control server (/envs)
├── source/
│   ├── robot_lab/               # pip-installable extension (50 RL envs; data/ gitignored)
│   │   └── source/robot_lab/robot_lab/   (nesting kept; setup.py)
│   └── leisaac/                 # SO101 devices/tasks (teleop, vision)
└── scripts/
    ├── train.py play.py eval.py            # canonical RL entrypoints (dispatch by --backend)
    ├── teleop.py annotate.py inference.py  # canonical leisaac entrypoints
    ├── reinforcement_learning/{rsl_rl,cusrl,skrl}/   # real backend train/play scripts
    ├── leisaac/{environments,mimic,convert,evaluation}/
    ├── tools/                  # training_server.py (legacy), converters, list_envs
    └── README.md               # canonical-name → real-script map
```

## isaac_sim/ — Isaac Sim side
```
isaac_sim/
├── scripts/
│   ├── isaac_control_server.py # ◄ THE host control API (:5561) — sim/scene/robot/train
│   ├── serve_sim.py            # persistent headless/GUI sim that enables the :8226 bridge
│   ├── launch_warehouse.py     # one-shot build+render+screenshot launcher
│   ├── build_warehouse.py gen_textures*.py fetch_real_textures.py   # scene authoring
│   └── rl/                     # hierarchical G1 pick-place task lib
├── templates/                  # ◄ SCENE TEMPLATES (robot × environment)
│   ├── environments.yaml       #   env → scene USD + named spawn anchors
│   ├── warehouse_g1.yaml       #   composite: env + one robot
│   ├── warehouse_fleet.yaml    #   composite: env + multi-robot fleet
│   └── README.md
├── scenes/                     # warehouse.usd + textures (gitignored, regenerable)
├── source/
│   └── isaacsim.code_editor.python_server/   # the :8226 in-sim exec extension
└── _control_logs/              # runtime logs of launched sims/jobs (gitignored)
```

## policies/ — hyperparameter tuning (Goal 3)
```
policies/
├── POLICY_TUNING.md            # front door
├── policy_skill.md             # master tuning router + cross-framework glossary
├── rsl_rl.md skrl.md           # repo-verified knob blocks + symptom→fix tables
└── rl_games.md sb3.md robomimic.md   # framework-default values (labeled as such)
```

## sandbox/ — egress policies + sandbox-side CLIs
```
sandbox/
├── policies/   isaaclab-training-policy.yaml, orchestrator-policy-additions.yaml
├── clients/    isaaclab-train, isaaclab-send/pick/place/detect
└── README.md   (port map: 5561 control, 5560 leisaac bridge, 8226 in-sim exec)
```

---

## Environment contract
| Var | Meaning | Default |
|---|---|---|
| `ISAAC_CLAW_DIR` | this repo | `~/isaac-claw` |
| `ISAAC_SIM_DIR` | Isaac Sim install (referenced) | `~/IsaacSim` |
| `ISAAC_LAB_DIR` | Isaac Lab checkout (referenced) | `~/IsaacLab` |
| `ISAAC_LAB_PYTHON` | python with isaacsim/isaaclab | `~/miniforge3/envs/env_isaaclab/bin/python` |
| `ISAAC_CONTROL_PORT` | control server port | `5561` |

## Ports
| Port | Server |
|---|---|
| 5561 | Isaac Control Server (sim / scene / robot / train) |
| 8226 | in-sim python_server bridge (scene-load / robot-spawn / exec) |
| 5557–5560 | leisaac ZMQ/HTTP teleop bridge |

## Not committed (gitignored, present on disk)
`isaac_lab/source/robot_lab/data/` (robot USDs ~450M) · `isaac_sim/scenes/*.usd`
+ `scenes/textures/` · `datasets/ *.hdf5 *.pt` · `**/logs **/outputs **/runs` ·
`isaac_sim/_control_logs/` · `__pycache__/ .venv/`
