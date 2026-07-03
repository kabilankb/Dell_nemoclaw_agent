# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

isaac-claw drives **NVIDIA Isaac Sim** (simulator) and **Isaac Lab** (RL/IL) from a
local-model TUI — **OpenClaw** (Gemma) and **NemoClaw** (Nemotron). The simulators are
**referenced, not vendored** (`$ISAAC_SIM_DIR`, `$ISAAC_LAB_DIR`); this repo holds only
custom extension code, scenes, skills, policies, and the agent glue.

Read these first — they are kept current and go deeper than this file:
- `README.md` — overview, the five design goals, quick start.
- `STRUCTURE.md` — full annotated tree, runtime-flow diagram, port/env tables.
- `HISTORY.md` — why things are the way they are (the bugs that shaped the design).

## Environment contract

Nothing works without these (defaults shown). `tui.sh` / `clawup.sh` export them:

| Var | Default | Meaning |
|---|---|---|
| `ISAAC_CLAW_DIR` | repo root | this repo |
| `ISAAC_SIM_DIR` | `~/IsaacSim` | Isaac Sim install (referenced) |
| `ISAAC_LAB_DIR` | `~/IsaacLab` | Isaac Lab checkout (referenced) |
| `ISAAC_LAB_PYTHON` | `~/miniforge3/envs/env_isaaclab/bin/python` | python with isaacsim+isaaclab |
| `ISAAC_CONTROL_PORT` | `5561` | control server port |

Ports: **5561** control server · **8226** in-sim python bridge · **5557–5560** leisaac teleop bridge.

## Architecture: two control paths

There are **two distinct ways** the model→simulator flow is wired. Know which one you're touching.

**1. The `claw` deterministic path (the production TUI path).** A small local model cannot
reliably chain five HTTP calls, so the entire flow is collapsed into ONE command:

```
TUI prompt → skill picks ONE `claw` command → Isaac Control Server (:5561)
           → spawns serve_sim.py (persistent GPU sim, enables :8226 bridge)
           → /robot/spawn etc. sent as python over the :8226 socket
```

- `agents/openclaw/claw` — the single CLI. `open` resolves a spec (template | env+robot |
  scene+robot), ensures the server, (re)launches the sim, polls the **:8226 bridge** for
  real readiness (not log-scraping), then spawns each robot with retries. Also `close`,
  `train`, `up`, `status`, `templates`, `scenes`, `robots`, `envs`.
- `isaac_sim/scripts/isaac_control_server.py` — THE host API (stdlib-only). `GET /envs
  /scenes /robots /status /logs`; `POST /sim/launch /scene/load /robot/spawn /exec /train
  /play /eval /stop`. Single-job state machine: **only one GPU job at a time** (sim OR RL);
  a second returns 409. Scene/robot/exec are python sent over the :8226 socket to an
  already-running sim.

**2. The 4-layer agent orchestrator (`agents/core/`).** A more autonomous multi-agent
system: **Atlas (L0 supervisor)** routes to worker layers (L1 Asset Placement … L4
Execution), validates each layer's output, and retries/reroutes. Configured entirely via
`agents/core/orchestrator.yaml` (no code changes): backend (`dryrun`/`sdk`/`openclaw`/
`nemoclaw`), model, paths, routing graph. Entry points: `app.py` (Gradio UI), `cli.py`
(headless). This is separate from the `claw` path above.

## Key data files (edit these, not code, to add robots/scenes/tuning)

- `agents/core/assets/catalog.yaml` — **robot template source**. Maps friendly name →
  USD (with Nucleus tokens like `{ISAACLAB_NUCLEUS_DIR}`, resolved in-sim at spawn) +
  `start_z`/`drive`. Add a robot here to make it spawnable.
- `isaac_sim/templates/environments.yaml` — environments: scene USD + named spawn
  **anchors** (x/y). Robot height/drive come from the catalog, position from the anchor,
  so the **same robot drops into any environment** with no pose math.
- `isaac_sim/templates/*.yaml` (e.g. `warehouse_g1`, `warehouse_fleet`) — composite
  templates pairing an environment with one or more robots.
- `isaac_lab/envs_registry.json` — canonical RL task list served at `/envs` and validated
  against by `/train`.

## Common commands

```bash
# Start the host control server (run in a REAL GPU terminal — see GPU note below)
$ISAAC_LAB_PYTHON isaac_sim/scripts/isaac_control_server.py
# …or idempotently ensure it (optionally also a sim):
agents/openclaw/clawup.sh            # ensure server   |  clawup.sh --sim [scene]  |  clawup.sh status

# Drive it deterministically
agents/openclaw/claw open --template warehouse_fleet --gui    # env + robots, visible window
agents/openclaw/claw open --env warehouse --robot unitree_g1 --anchor pick_station --gui
agents/openclaw/claw close                                    # stop sim/training, free GPU + :8226
agents/openclaw/claw train --task <id> --backend rsl_rl --num_envs 4096
agents/openclaw/claw status | templates | robots | scenes

# Launch the OpenClaw TUI (use this, NOT bare `openclaw tui`)
agents/openclaw/tui.sh               # ensures server up + DISPLAY + a CLEAN --session isaac-claw
agents/openclaw/deploy.sh            # copy operational skills into ~/.openclaw/workspace/skills
                                     #   (--all for the full reference library)

# Isaac Lab RL/IL entrypoints (canonical names dispatch to real backend scripts)
$ISAAC_LAB_PYTHON isaac_lab/scripts/train.py --task=<id> --backend rsl_rl --headless
$ISAAC_LAB_PYTHON isaac_lab/scripts/play.py  --task=<id> --checkpoint <path>
# also: eval.py, teleop.py (--teleop_device --record), annotate.py, inference.py
# canonical-name → real-script map: isaac_lab/scripts/README.md
```

There is no top-level test/lint/build harness; "build" here means generating scenes
(`isaac_sim/scripts/build_warehouse.py` + `gen_textures*.py`). The `robot_lab` extension is
pip-installable (`isaac_lab/source/robot_lab/setup.py`).

## Critical constraints (these caused real bugs — see HISTORY.md)

- **GPU launches must run in a real terminal, not a tool-call shell.** The agent harness
  cannot spawn or kill Isaac Sim (Kit) — signal 16 kills the shell. The control server and
  `claw` (run in the *user's* process tree) handle GPU lifecycle; the harness can only talk
  to an *already-running* sim over the :8226 socket.
- **OpenClaw's skill scanner does NOT follow symlinks.** `deploy.sh` copies real dirs.
  Re-run it after editing any skill. It deploys only a *small operational set* on purpose —
  a tiny surface keeps a 12B model from wandering into deep authoring skills.
- **Local models execute best with ONE deterministic command.** Skills are written
  imperatively ("run this one command"), not as multi-step plans. Don't reintroduce
  multi-call flows into the TUI path.
- **Start failed work in a fresh `--session`** — OpenClaw sessions persist context and the
  model will "recall" earlier failures. `tui.sh` uses a clean `isaac-claw` session.

## Skills & policies (model-facing markdown, not code)

- `skills/skills.md` — MASTER router; every skill with purpose + trigger keywords + the
  endpoint/script it drives. Load first. Operational set: `task` (open), `close`, `ops`,
  `training`, `teleop`, `mimicgen`, `articulation`; the rest is a reference library.
- `policies/policy_skill.md` — MASTER tuning router → per-framework files (`rsl_rl`,
  `skrl`, `rl_games`, `sb3`, `robomimic`), each with one fenced-YAML knob block (safe
  ranges + symptom→fix table) that launchers parse and the model edits. Backends physically
  present: **rsl_rl, cusrl, skrl**.

## Conventions

- OpenClaw and NemoClaw differ **only** in model config under `agents/`; shared logic lives
  in `agents/core/`. Don't fork core behavior per-runtime.
- Heavy assets are gitignored but present on disk: robot USDs
  (`isaac_lab/source/robot_lab/data/`), built scenes + textures (`isaac_sim/scenes/`),
  datasets/checkpoints. Regenerate scenes rather than committing them.
- The repo was assembled non-destructively from four source repos; each subdirectory's
  README records provenance.
