# NemoClaw × Isaac — Runbook

Drive **Isaac Sim / Isaac Lab** from the NemoClaw sandbox chat (local model:
`gemma4-31b` or `nemotron-3-super:120b` via Ollama). You talk in plain English;
the model calls dedicated `isaac__*` tools that hit the host **Isaac Control
Server** on `:5561`.

---

## Architecture in one line

```
NemoClaw sandbox (container)  ──isaac__ MCP tools──▶  host Control Server :5561  ──▶  Isaac Sim / Isaac Lab (host GPU)
```

- The **control server + Isaac** run on the **host** (GPU, `env_isaaclab`). They
  cannot run inside the sandbox.
- The sandbox reaches the host at `host.openshell.internal:5561`.
- The model gets **dedicated tools** (`isaac__open_scene`, `isaac__train_task`, …)
  whose valid envs/robots/tasks are fetched **live** from the server.

---

## One-time setup (already done; redo only if the sandbox is rebuilt)

```bash
cd /home/dgx-destro/isaac-claw/agents/nemoclaw

# 1. create the sandbox (interactive): pick Local Ollama + a tool-capable model
nemoclaw onboard                     # model e.g. gemma4-31b:latest or nemotron-3-super:120b

# 2. provision it end-to-end (skills + 5561 policy + dedicated MCP tools)
./install_skill.sh isaacsim

# 3. make the host control server always-on (systemd user service)
cd ../openclaw && bash install-control-service.sh
```

Switch model any time:
```bash
nemoclaw inference set --provider ollama-local --model gemma4-31b:latest --sandbox isaacsim --no-verify
nemoclaw isaacsim recover
```

---

## Daily use — 2 steps

The control server auto-starts (systemd), so you only:

```bash
nemoclaw isaacsim connect        # enter the sandbox
openclaw tui                     # plain — NO --session (main session runs on-host)
```

Then just talk (examples below).

> **Rule:** use plain `openclaw tui`. A named `--session <name>` gets network-isolated
> and cannot reach `:5561`.

---

## What to say in the TUI

### Inventory (read-only)
```
list robots
how many training tasks are available?
what can I open?
what's the sim status?
```

### Open a scene (ANY robot in ANY environment)
```
open the warehouse with spot
open hospital with agibot_a2d
open the office with a franka_panda at the entrance
```
- Environments: `warehouse, warehouse_full, warehouse_shell, warehouse_local, grid_room, office, hospital`
- Cloud scenes (office/hospital/grid_room/warehouse_full) stream ~1–2 min before the robot appears.

### Train (pick a *trainable* robot)
```
train the Unitree Go2 on rough terrain, headless, 4096 envs
train the Go2 rough, headless, 500 envs, tuned for stable locomotion
train the Go2 rough, 500 envs, with entropy_coef 0.015, learning_rate 1e-3, gamma 0.99
train the G1 dance task, gui, 2 envs           # AMP dance → skrl + amp (auto)
```
- Trainable: **Go2, A1, B2, Lite3, ZSL1, MagicDog, Agibot D1**, the humanoids
  (XBot, G1, H1, …), G1 AMP-Dance, G1 BeyondMimic, A1 Handstand, SO101 PickOrange.
- **Spot is NOT trainable** (spawn-only — no registered task).
- "tuned" → the model reads `isaac__tuning_guide` (advised ranges + symptom→knob
  table from `policies/rsl_rl.md`) and sets `params`.

### Monitor / control
```
how's the training going?        # precise: iteration, reward, timesteps, ETA
play the Go2 rough policy         # watch a trained checkpoint (RL inference)
stop the training                # frees the GPU
close the sim
```

> **One GPU job at a time.** Close a sim / stop a run before starting another.

---

## Tuning knobs (rsl_rl / cusrl)

Friendly name → what it does (safe range). Full guide: `policies/rsl_rl.md`
or ask `tuning_guide` in the TUI.

| Knob | Range | Effect |
|---|---|---|
| `learning_rate` | 1e-5–3e-3 | step size (KL-adaptive) |
| `entropy_coef` | 0.0–0.02 | exploration; raise if action noise collapses |
| `gamma` | 0.97–0.999 | discount / horizon |
| `clip_param` | 0.1–0.3 | PPO trust region |
| `num_steps_per_env` | 16–64 | rollout horizon |
| `reward_<term>` | see guide | reward weight (best-effort; task may re-pin) |

`num_envs`, `max_iterations`, `seed`, `gui` are top-level (say them plainly).

---

## Manage the always-on server

```bash
systemctl --user status  isaac-control-server
systemctl --user restart isaac-control-server     # after editing isaac_control_server.py
systemctl --user stop    isaac-control-server
journalctl --user -u isaac-control-server -f       # live log
curl -s http://localhost:5561/status               # quick health
```

---

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Model says **"Not connected"** / tool times out | You used `--session <name>` (isolated netns). Use plain `openclaw tui` (main). |
| Tools missing / model won't call them | Start a **fresh** `openclaw tui` session so the MCP server reloads. |
| Everything says server unreachable | `systemctl --user status isaac-control-server`; `restart` it; `curl :5561/status`. |
| Model hallucinates instead of calling tools | Switch to a tool-capable model (`gemma4-31b` / `nemotron-3-super:120b`). |
| "unknown task" on train | It's not registered — `list training tasks`; Spot etc. are spawn-only. |
| GUI training dies with Kit assert ("Recursion not allowed") | Train **headless**; use `play` to watch. |
| Multi-turn session wedged | Start a fresh session; the main session key runs on-host. |

---

## Key files

| File | Purpose |
|---|---|
| `agents/nemoclaw/isaac-mcp.mjs` | the dedicated `isaac__*` MCP tool server (live catalog, train/play/tuning) |
| `agents/nemoclaw/apply_mcp_fix.sh` | install MCP tools + config into a sandbox |
| `agents/nemoclaw/install_skill.sh` | full end-to-end provisioning (skills + policy + MCP) |
| `agents/openclaw/isaac-control-server.service` | systemd unit for the always-on server |
| `agents/openclaw/install-control-service.sh` | installs/enables that service |
| `isaac_sim/scripts/isaac_control_server.py` | the host control server (`:5561`) |
| `policies/rsl_rl.md`, `skrl.md`, … | advised tuning guides (served at `/tuning`) |
