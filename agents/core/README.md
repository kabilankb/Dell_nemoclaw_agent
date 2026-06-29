# Isaac Sim / Lab — Multi-Layer Robot Orchestration

A Gradio UI + router that orchestrates **four layered skill-agents** for Isaac
Sim and Isaac Lab, under a **master supervisor robot, Atlas (L0)**, that monitors
and validates every layer's execution. Each layer is a real Claude subagent (run
via the Claude Agent SDK) with its own system prompt, tool set, and
source-of-truth.

```
            ┌──────────────────────────── Gradio UI (app.py) ───────────────────────────┐
  command → │  router.classify → dispatch → stream events → live layer panels + log     │
            └───────────────────────────────────────────────────────────────────────────┘
                                            │
       ┌──────────────────────── 🛰️ L0 · Atlas · Master Supervisor ──────────────────────┐
       │  after each worker layer: validate output → accept | retry+feedback | reroute    │
       └──────────────────────────────────────────────────────────────────────────────────┘
                                            │
        ┌───────────────┬───────────────────┼───────────────────┬───────────────┐
        ▼               ▼                   ▼                   ▼
   L1 Asset         L2 RL              L3 Imitation         L4 Execution
   Placement        Authoring          Learning Authoring   (+ reroute)
   catalog.yaml     Isaac Lab + NVIDIA  Isaac Lab Mimic /    runs L2/L3 scripts;
   → place USD      docs → train.py     robomimic + LeRobot  reroutes to L1/L2/L3
        ▲               ▲                   ▲                   │
        └───────────────┴───────────────────┴───────────────────┘
              reroute (@@REROUTE: …)  ·  Atlas verdict (@@VERDICT: …)
```

## L0 · Atlas — the master supervisor
Atlas wraps the orchestration loop. After every worker layer runs, it validates
that the layer actually did its job for the Isaac Sim/Lab task, then steers the
loop. Validation combines two signals (`validator.py`):

- **Deterministic Isaac/Lab checks** (always on, no API, works in dry-run): error
  signatures (traceback, `ModuleNotFoundError`, `Failed to open stage`, CUDA
  OOM, NaN/flat reward, segfault…), empty-output detection, and claimed-file
  existence under `$WORKSPACE_DIR`.
- **An LLM verdict** (when not dry-run and enabled): the `orch-l0-supervisor`
  agent inspects artifacts on disk and emits one
  `@@VERDICT: <PASS|WARN|FAIL> :: <accept|retry|reroute:<key>> :: <reason>` line.

The loop then acts on the merged verdict:

| Verdict | Action |
|---|---|
| **PASS / WARN** | accept; follow the worker's own `@@REROUTE` if it emitted one |
| **FAIL · retry** | re-run the **same** layer, Atlas's reason fed back as corrective feedback (bounded by `max_retries`, default 2) |
| **FAIL · reroute:`<key>`** | hand off to the layer Atlas says owns the fix (bounded by `max_hops`) |

Toggle it with the **🛰️ Atlas supervise** UI checkbox, `--no-supervise` on the
CLI, or `ORCH_SUPERVISE=0` / `supervision.*` in `orchestrator.yaml`
(`enabled`, `use_llm`, `max_retries`).

## The four layers

| # | Agent (`.claude/agents/…`) | Owns | Source of truth |
|---|---|---|---|
| **L1** | `orch-l1-asset-placement` | Place / position / arrange / remove USD assets & robots; articulation | `assets/catalog.yaml` + `isaac-sim-orchestrator`, `usd-pipeline`, `usd-articulation` skills |
| **L2** | `orch-l2-rl-author` | Author RL env cfgs, rewards, PPO configs, gym registration | local `$ISAAC_LAB_DIR` tasks + NVIDIA Isaac Lab docs |
| **L3** | `orch-l3-il-author` | Author imitation-learning pipelines (BC / ACT / diffusion) | `isaaclab_mimic` + `robomimic` + **LeRobot** package & docs |
| **L4** | `orch-l4-executor` | Run training / dataset collection / inference / teleop; **reroute** | `$ISAAC_LAB_DIR/scripts/{reinforcement_learning,imitation_learning,tools}` |

The agent definitions are plain markdown under `.claude/agents/` — the *same*
files Claude Code discovers natively. The orchestrator parses their frontmatter
+ body into system prompts (`agents.py`), so there is one source of truth.

### Routing & reroute
- `router.py` classifies each command to a layer with a weighted keyword model
  (instant UI feedback; you can also force a layer in the dropdown).
- **L4 reroutes**: when execution needs a change it doesn't own, the executor
  emits `@@REROUTE: <assets|rl|il> :: <reason>` on its own line. `orchestrate.py`
  detects it and hands the task to the right layer (bounded to `max_hops`):
  - RL content to change → **L2**
  - imitation-learning content to change → **L3**
  - USD placement / articulation to change → **L1**

## Layer-1 asset store
`assets/catalog.yaml` — one categorized store (`robots`, `environments`,
`props`, `sensors`). Each entry maps a friendly name to a USD reference
(Isaac Lab Nucleus tokens or a repo-relative path) plus placement hints
(`start_z`, `drive`, `separation_m`, `scale`). The L1 agent resolves names from
here and never invents paths. Browse/search it in the **Asset Catalog** tab.

## Setup

UI deps (gradio) need `huggingface-hub>=1.2`, which conflicts with the base
env's `lerobot`/`transformers` (`<1.0`). So the **UI runs in its own venv**; the
agents shell out to Isaac Lab / LeRobot in their own interpreters.

```bash
python -m venv agent_orchestrator/.venv
agent_orchestrator/.venv/bin/pip install -r agent_orchestrator/requirements.txt
```

Auth: the Claude Agent SDK uses `ANTHROPIC_API_KEY` if set, otherwise the
logged-in `claude` CLI. Override the model with `ORCH_MODEL` (default
`claude-opus-4-8`).

Environment contract (auto-detected, override via env): `ISAAC_SIM_DIR`
(`~/IsaacSim`), `ISAAC_LAB_DIR` (`~/IsaacLab`), `WORKSPACE_DIR`
(`agent_orchestrator/workspace`). Generated scripts/datasets/runs land under
`$WORKSPACE_DIR`.

## No-code configuration

Two editable files configure the whole orchestrator — no Python changes:

- **`orchestrator.yaml`** — initial-setup knobs: Isaac paths, model, default
  backend, dry-run / allow-execution defaults, routing defaults, per-backend
  settings (openclaw/nemoclaw), and supervision (Atlas L0). Precedence is
  **env var > orchestrator.yaml > built-in default**, so an env var always wins
  for one-off runs. The file is optional; delete it and everything falls back to
  defaults. Point `$ORCH_CONFIG` elsewhere to use an alternate file.

- **`workflows/*.workflow.yaml`** — a drag-and-drop **agent graph**: nodes are
  agents (not layers), edges are wires. `route` edges do entry routing by
  keyword, `reroute` edges are agent↔agent handoffs, `validate` edges send a
  worker's output to Atlas. Turn it on with `routing.use_workflow: true`; the
  default graph reproduces the built-in routing exactly. Validate / preview with
  `python -m agent_orchestrator.workflow [path] [test-command]`. See
  [`workflows/README.md`](workflows/README.md).

### Visual editor (drag-and-drop, like the Isaac Sim Action Graph)

For a fully no-code experience, launch the node canvas and build the graph by
dragging agents and wiring ports — then type a command and hit **Run** to
dispatch the action through the graph you just built:

```bash
agent_orchestrator/.venv/bin/python -m agent_orchestrator.editor   # → http://localhost:7870
```

- Drag agents (Atlas L0, L1–L4) from the palette onto the canvas.
- Wire ports: trigger ▶ agent = *route*, agent ▶ agent = *reroute*,
  agent ▶ Atlas = *validate*. Mark one agent **★** as the default lane.
- **Save** writes a `.workflow.yaml` (defaults to `workflows/custom.workflow.yaml`,
  so the curated `default.workflow.yaml` is left intact).
- **Run** auto-saves, routes the command *through your graph*, and streams the
  worker output + Atlas verdict live. Defaults to dry-run; switch the backend and
  tick **L4 exec** to actually run training/teleop.

A standalone FastAPI app (`editor.py` + `web/editor.html`), separate from the
Gradio dashboard.

## Run

```bash
# UI  → http://localhost:7860
agent_orchestrator/.venv/bin/python -m agent_orchestrator.app

# Headless CLI (same loop, no browser)
python -m agent_orchestrator.cli "place 6 nova carters in the warehouse aisle" --dry-run
python -m agent_orchestrator.cli --classify "train cartpole for 200 iters"
python -m agent_orchestrator.cli "write a PPO reward for spot locomotion" --layer 2
```

- **Dry-run** (UI checkbox / `--dry-run`): routes and plans, **no API calls** —
  use to test wiring without spending tokens.
- **Allow L4 execution** (UI checkbox / `--allow-execution`): lets the executor
  run Bash (training/teleop). Off by default for safety; when off, L4 falls back
  to `acceptEdits` and won't launch processes.

## OpenClaw integration

The orchestrator is wired into **OpenClaw** both ways:

1. **Discoverable as an OpenClaw skill** — `~/.openclaw/workspace/skills/`
   `isaac-agent-orchestrator/SKILL.md` tells the OpenClaw agent how to classify,
   dispatch, browse the catalog, and launch the UI. It's registered + enabled in
   `~/.openclaw/openclaw.json` under `skills.entries.isaac-agent-orchestrator`
   (with the `ISAAC_*` / `ORCHESTRATOR_DIR` env). Verify:
   ```bash
   openclaw skills list | grep isaac-agent-orchestrator   # → ✓ ready 🤖
   ```

2. **Runs layers *through* OpenClaw** — pick the **OpenClaw runtime** backend
   (UI dropdown, `--backend openclaw`, or `ORCH_BACKEND=openclaw`). Each layer is
   executed via `openclaw agent --local` using OpenClaw's configured models +
   workspace, so it works without Anthropic credentials.

Backends: `dryrun` (plan only), `sdk` (Claude Agent SDK), `openclaw` (OpenClaw
runtime), `nemoclaw` (NemoClaw NIM sandbox). The OpenClaw agent itself can invoke
the orchestrator headlessly:
```bash
cd /home/dgx-destro/warehouse_nemoclaw
python -m agent_orchestrator.cli "place 4 ur10 arms on tables" --backend openclaw
```

## NemoClaw integration

Wired the same two ways as OpenClaw, but adapted to NemoClaw's model: it runs
**always-on NIM sandboxes** rather than a one-shot local agent, so there is no
`agent --local`. Each layer executes *inside a named sandbox*.

1. **Discoverable as a NemoClaw skill** — the skill package lives in-repo at
   `agent_orchestrator/nemoclaw/skill/isaac-agent-orchestrator/`. Deploy it into
   a sandbox:
   ```bash
   agent_orchestrator/nemoclaw/install_skill.sh <sandbox>        # or NEMOCLAW_SANDBOX=…
   # under the hood: nemoclaw <sandbox> skill install <skill-dir>
   ```
   The orchestrator repo must be reachable inside the sandbox at
   `$ORCHESTRATOR_DIR`; mount it if not:
   ```bash
   nemoclaw <sandbox> share mount /home/dgx-destro/warehouse_nemoclaw /work/warehouse_nemoclaw
   ```

2. **Runs layers *through* a NemoClaw sandbox** — pick the **NemoClaw sandbox**
   backend (UI dropdown, `--backend nemoclaw`, or `ORCH_BACKEND=nemoclaw`). Each
   layer is run via `nemoclaw <sandbox> exec` against an in-sandbox agent CLI,
   feeding it the layer's system prompt + task (base64-piped, so multi-line
   content needs no quoting).

   Env contract for this backend:
   | Var | Purpose | Default |
   |---|---|---|
   | `NEMOCLAW_SANDBOX` | **required** target sandbox (`nemoclaw list`) | *(none — errors if unset)* |
   | `NEMOCLAW_AGENT_CMD` | in-sandbox agent CLI fed the prompt on stdin | `claude -p` |
   | `NEMOCLAW_MODEL` | appended as `--model <m>` to the agent CLI | unset |

   ```bash
   cd /home/dgx-destro/warehouse_nemoclaw
   NEMOCLAW_SANDBOX=robotcontrol \
     python -m agent_orchestrator.cli "place 4 ur10 arms on tables" --backend nemoclaw
   ```

## Files
| File | Role |
|---|---|
| `app.py` | Gradio dashboard (orchestrator + asset catalog tabs) |
| `cli.py` | Headless CLI |
| `orchestrate.py` | The loop: classify → run layer → **Atlas validates** → accept/retry/reroute |
| `validator.py` | **L0 Atlas**: deterministic Isaac/Lab checks + LLM verdict (`@@VERDICT`) |
| `router.py` | Keyword classifier + reroute resolution (+ L0 supervisor registry) |
| `runner.py` | Claude Agent SDK executor (+ dry-run), streaming, reroute scan |
| `agents.py` | Loads the 5 `.claude/agents/*.md` (L0–L4) into system prompts |
| `catalog.py` | Load / search / resolve the asset store |
| `state.py` | Per-layer status + event log for the panels |
| `config.py` | Env-var contract + path resolution |
| `assets/catalog.yaml` | The Layer-1 common asset store |
| `nemoclaw/skill/…/SKILL.md` | NemoClaw skill package (deploy with `skill install`) |
| `nemoclaw/install_skill.sh` | Push the skill into a NemoClaw sandbox |
```
