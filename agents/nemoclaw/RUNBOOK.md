# NemoClaw × Isaac — Runbook

Drive **Isaac Sim / Isaac Lab** from the NemoClaw sandbox chat. The model is
Nemotron on **Nebius Token Factory** (OpenAI-compatible, `NEBIUS_MODEL` in
`~/.openclaw/.env`); a local Ollama model also works. You talk in plain English;
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
cd "$ISAAC_CLAW_DIR/agents/nemoclaw"

# 1. create the sandbox. Nebius Token Factory, non-interactive (key in ~/.openclaw/.env):
set -a; . ~/.openclaw/.env; set +a
COMPATIBLE_API_KEY="$NEBIUS_API_KEY" NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 \
NEMOCLAW_PROVIDER=custom NEMOCLAW_ENDPOINT_URL=https://api.tokenfactory.nebius.com/v1 \
NEMOCLAW_MODEL=nvidia/nemotron-3-super-120b-a12b NEMOCLAW_GATEWAY_PORT=8090 \
  nemoclaw onboard --name isaacsim --non-interactive
#    (or interactive `nemoclaw onboard` and pick Local Ollama + a tool-capable model)

# 2. provision it end-to-end (skills + 5561 policy + dedicated MCP tools)
./install_skill.sh isaacsim

# 3. make the host control server always-on (systemd user service)
cd ../openclaw && bash install-control-service.sh
```

Switch model any time — from the console's model picker, or:
```bash
COMPATIBLE_API_KEY="$NEBIUS_API_KEY" nemoclaw inference set --provider compatible-endpoint \
  --model nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B --sandbox isaacsim \
  --endpoint-url https://api.tokenfactory.nebius.com/v1 --credential-env COMPATIBLE_API_KEY \
  --inference-api openai-completions
```
NemoClaw 0.0.137 often ends this with a gateway "health timeout"; the route is still
committed and the next turn runs on the new model. Set `NEBIUS_MODEL` in
`~/.openclaw/.env` so `./demo.sh up` keeps it.

---

## Web console (hackathon demo)

```bash
./demo.sh check     # pre-flight: key + model answer, GPU memory/other GPU users, ports, checkpoints
./demo.sh up        # control server + NemoClaw sandbox + console → http://localhost:8800
./demo.sh status
./demo.sh down      # stops console, server, GPU job, sandbox (keeps the gateway)
```

One page (`web/console_server.py`, `web/console/index.html`) with:

- **Nebius inference** — active model, a model picker (Nano / Super / Ultra / Lightning,
  ~45 s to switch), and the key box. A new key is verified against Token Factory,
  saved to `~/.openclaw/.env` and pushed into the sandbox, so rotating needs no rebuild.
- **Live view** — the viser web viewer (`:8012`) for any `gui` run. Set
  `ISAAC_LAB3_VIZ=newton_gl` on the control server for a desktop window instead.
- **Training** — progress, reward curve, fall rate, plus:
  - **Tune it**: the claw reads `isaac__training_status` + the tuning guide, stops the
    run and restarts it with 2–3 changed params. Unknown `reward_<term>` knobs are
    dropped by the server (it knows the task's terms from earlier logs) instead of
    crashing the launch.
  - **Critique the gait**: records a headless clip of the best checkpoint, sends six
    frames to `nvidia/Nemotron-3.5-Super-VL` on Token Factory, shows clip + verdict.
  - **Replay**: animates a past run's reward curve — the fallback when the GPU or the
    network is not available on stage.
- **Claw chat** — one `openclaw agent` turn per message, in a session per page load
  (reload = fresh session), with the tool calls shown live as they hit the server.

### Duck pilot (Hermes agent: train → play → sim2real)

A second agent, `duckpilot` (Hermes in its own NemoClaw sandbox, Nemotron on Nebius),
runs the MicroDuck pipeline by itself: train → fall-rate gate → auto-tune + retrain →
play (clip + ONNX export) → verify → deploy to the real duck (`DUCK_HOST`, after the
user confirms it is on its stand). Set up with `agents/hermes/install_duckpilot.sh`;
details in `agents/hermes/README.md`. In the console, use the **Duck pilot** tab.

### Before the demo

1. Train a full policy off-stage (`train the microduck on flat ground, headless, 4096
   envs, 1500 iterations`, ~25 min). `play` and the critique use the **most-trained**
   checkpoint of the task, not the newest run folder.
2. `./demo.sh check` until it says Ready; record a fallback screen capture.
3. Rotate the Nebius key (paste the new one into the console's key box).

### Training on a Nebius AI Cloud GPU

Clone this repo and Isaac Lab 3 (`~/IsaacLab-develop`, uv) on a Nebius GPU VM, then:

```bash
./demo.sh up --gpu-host ubuntu@<vm-ip> --gpu-dir ~/isaac-claw     # or ISAAC_GPU_HOST in .env
```

`up` starts the control server on the VM and tunnels it to `:5561` here (also on the
sandbox's `host.openshell.internal`, so the claw's tools are unchanged) and the viser
viewer to `:8012`. Training metrics, checkpoints and critique clips come over the same
tunnel; the console, the sandbox and the key stay on the laptop.

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
train the microduck on flat ground, headless, 4096 envs, 1500 iterations
train the microduck on rough terrain, gui, 64 envs
play the microduck rough policy
```
- **Isaac Lab 3 tasks** run from `$ISAAC_LAB3_DIR` (default `~/IsaacLab-develop`, uv)
  via `isaaclab train --rl_library rsl_rl`, capped at 1500 iterations unless you give a
  number, with the viser web viewer for `gui`:
  MicroDuck (`IsaacContrib-Velocity-{Flat,Rough}-MicroDuck`, `presets=backlash`),
  humanoids **G1 / H1** (`Isaac-Velocity-{Flat,Rough}-G1|H1`), **Cassie**, **Go2**
  (`-UnitreeGo2`), **ANYmal-D** (`-AnymalD`).
- **robot_lab tasks** (`RobotLab-*`: XBot, GR1, Booster T1, AMP-Dance, …) need
  `ISAAC_LAB_PYTHON` with `robot_lab` installed. `/envs` marks each task `available`;
  the claw only sees runnable ones. Asking for a robot_lab G1/H1/Go2 task on a host
  without robot_lab runs the Isaac Lab 3 task for the same robot instead.
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
| Console chat answers without calling tools | Old session memory. Reload the page (new session). |
| "can't run on this host: 'robot_lab' is not installed" | Use the `Isaac-Velocity-*` task for that robot, or install robot_lab into `ISAAC_LAB_PYTHON`. |
| Critique says "no new video" | `moviepy` missing in the Isaac Lab 3 venv: `uv pip install --python ~/IsaacLab-develop/.venv/bin/python moviepy`. |
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
