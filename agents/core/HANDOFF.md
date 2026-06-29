# Agent Orchestrator — Handoff

A working map of the **Isaac Sim / Isaac Lab agent orchestrator** that lives in
`agent_orchestrator/`. Written for whoever picks this up next: what it is, how
the pieces fit, how to run it, and where to look when something breaks.

> **What changed since the last handoff:** the orchestrator grew from four flat
> layers into a **supervised, configurable graph**. Three big additions:
> 1. an **L0 "Atlas" Master Supervisor** that validates every worker layer and
>    can retry/reroute it (`validator.py`, `orch-l0-supervisor.md`);
> 2. **no-code config** — `orchestrator.yaml` (setup knobs) + a drag-and-drop
>    **workflow graph** (`workflows/*.workflow.yaml`, `workflow.py`);
> 3. a **visual node editor** with a turn-by-turn **conversation mode** and
>    persistent thread memory (`editor.py`, `web/editor.html`).
> The no-match default layer is now **L1** (read-safe), not L4.

---

## 1. What it is

A **UI + keyword router** that dispatches natural-language commands to layered
Claude subagents, each with its own system prompt, tool set, and
source-of-truth. A **master supervisor (Atlas, L0)** wraps the loop: it dispatches
ambiguous commands to the right entry worker, then validates each worker's output
and steers the loop (accept / retry-with-feedback / reroute). Layer 4 (execution)
can also **reroute** work back to the authoring/placement layers.

```
 command
    │
    ▼
 router.classify ──► weighted-keyword score → entry layer
    │
    ▼
 🛰️ Atlas (L0) dispatch  ──► if routing ambiguous, pick entry worker (LLM or safe-default L1)
    │
    ▼
 orchestrate() loop ──► executor.run(layer, command) ──► stream Events
    │                                                       │
    │  ◄──── @@REROUTE: <assets|rl|il> :: <reason> ─────────┘  (L4 only)
    ▼
 🛰️ Atlas (L0) validate ──► @@VERDICT: <PASS|WARN|FAIL> :: <accept|retry|reroute> :: <reason>
    │
    ├─ PASS/WARN  → accept (follow worker reroute if any)
    ├─ FAIL+retry → re-run SAME layer, verdict reason fed back as feedback
    └─ FAIL+reroute → hand off to the layer Atlas says owns the fix
    ▼
 live layer panels + rolling log (UI)  /  printed events (CLI)
```

| # | Layer | Agent file | Owns | Source of truth |
|---|-------|-----------|------|-----------------|
| **L0** | Master Agent | `.claude/agents/isaac-robot-orchestrator-master-agent.md` | **receives** the request; **dispatches** to a slave; **validates** each slave's output; **returns** the result. Never does the work itself. | the slave output + artifacts on disk + repo skills |
| **L1** | Asset agent | `.claude/agents/orch-l1-asset-placement.md` | place / position / arrange / remove USD assets & robots; articulation; **catalog lookups** | `assets/catalog.yaml` + isaac-sim/usd skills |
| **L2** | RL task-script + validation agent | `.claude/agents/orch-l2-rl-author.md` | author **and self-validate** RL env cfgs, rewards, PPO/SAC configs, gym registration | local `$ISAAC_LAB_DIR` tasks + NVIDIA docs |
| **L3** | IL task-script + validation agent | `.claude/agents/orch-l3-il-author.md` | author **and self-validate** IL pipelines (BC / ACT / diffusion), demo recording, dataset gen | `isaaclab_mimic` + `robomimic` + LeRobot |
| **L4** | Execution | `.claude/agents/orch-l4-executor.md` | run training / dataset collection / inference / teleop; **reroute** | `$ISAAC_LAB_DIR/scripts/{reinforcement_learning,imitation_learning,tools}` |

**Single source of truth for agents:** the five `.claude/agents/orch-*.md` files
are the *same* markdown Claude Code discovers natively. `agents.py` parses their
frontmatter + body into system prompts — there is no second copy. L0 is included
(`router.ALL_LAYERS`) for loading but is **never auto-routed to**.

---

## 2. The request loop (control flow)

The heart is `orchestrate.py::orchestrate()` — an async generator that mutates a
shared `OrchestratorState` and yields after every event so the UI re-renders
live. Per command:

1. **Route.** If a layer is forced (UI dropdown / `--layer`), use it. Otherwise
   `router.classify(command)` runs a weighted-keyword model. **Default on
   no-match is L1** (read-safe asset/catalog layer), set by
   `routing.default_layer` / `SETTINGS.default_layer`.
2. **Atlas dispatch (supervised runs).** When the keyword route is *ambiguous*
   (top score ≤ 0) Atlas decides the entry worker — via the LLM supervisor agent
   if available, else `SAFE_DEFAULT_LAYER = 1`. A confident keyword route is
   rubber-stamped (no API call). Emits `@@DISPATCH: <key> :: <reason>`.
3. **Run the worker.** `get_executor(...)` returns a backend; `executor.run(layer,
   command)` streams `Event`s (`status` / `text` / `tool` / `reroute` / `result`
   / `error`). The loop updates per-layer status and appends to the log.
4. **Atlas validate.** `Supervisor.validate(layer, …)` runs after every worker:
   deterministic Isaac/Lab checks **always**, plus an optional LLM verdict. It
   yields a `verdict` Event carrying a merged `Verdict`.
5. **Act on the verdict:**
   - `FAIL + retry` (and `retries < max_retries`, default **2**) → re-run the
     **same** layer with Atlas's reason + failed-check summary fed back as
     corrective feedback.
   - `FAIL + reroute:<key>` (Atlas) **or** worker `@@REROUTE` (when verdict is
     PASS/WARN) → hand off to the target layer (bounded by `max_hops`, default
     **4**); reset retries.
   - otherwise → this layer is the end; mark done/error; log the full path
     (`■ finished. path: L1 → L4`).

A `max_iter` safety bound (`max_hops + (max_retries+1)*4 + 2`) caps the loop.

**Reroute mechanism (worker side):** only L4 emits it. The executor scans agent
output for `@@REROUTE:\s*([A-Za-z0-9]+)\s*::\s*(.+)` (`runner.REROUTE_TOKEN` /
`_REROUTE_RE`). `router.resolve_reroute()` maps the target
(`assets|rl|il|exec` or a digit) → layer number.

---

## 3. The supervisor (Atlas / L0) — `validator.py`

Atlas validation merges two signals into one `Verdict`:

- **Deterministic checks** (always on, no API, work in dry-run): empty-output
  detection; hard **error signatures** → FAIL (`Traceback`, `ModuleNotFoundError`,
  `ImportError`, `command not found`, `No such file`, segfault, `CUDA error/OOM`,
  NaN in loss/reward, `Failed to open stage`, `AssertionError`, `RuntimeError`);
  soft signatures → WARN (deprecations, generic warnings, flat reward, TODO/
  placeholder); and **claimed-file existence** under `$WORKSPACE_DIR`/repo
  (skipped for remote backends `openclaw`/`nemoclaw`).
- **LLM verdict** (only when `use_llm` and not dry-run): the `orch-l0-supervisor`
  agent runs via the same executor, inspects artifacts, and emits one
  `@@VERDICT: <PASS|WARN|FAIL> :: <accept|retry|reroute:<key>> :: <reason>` line.

`_merge()`: the **LLM verdict is authoritative** when present, but a deterministic
hard-FAIL the model missed escalates an otherwise-clean call to at least WARN.
The verdict's `message` IS the feedback handed back on a retry, so it's expected
to be specific and actionable.

Atlas also exposes `dispatch()` (the front-of-loop entry-worker picker) using the
parallel `@@DISPATCH:` protocol. Both protocols are parsed by regex in
`validator.py` (`parse_verdict`, `parse_dispatch`).

---

## 4. Files (where everything lives)

| File | Role |
|------|------|
| `app.py` | Gradio dashboard — orchestrator tab + asset-catalog tab. Entry: `python -m agent_orchestrator.app` (→ :7860) |
| `__main__.py` | `python -m agent_orchestrator` → `app.main()` |
| `cli.py` | Headless CLI — same loop, no browser. `python -m agent_orchestrator.cli ...` |
| `editor.py` | **Visual node-graph editor** (FastAPI, separate from Gradio). `python -m agent_orchestrator.editor` (→ :7870). Also hosts **conversation mode** + persistent thread memory. |
| `web/editor.html` | The drag-and-drop canvas served by `editor.py` |
| `orchestrate.py` | The loop: classify → Atlas dispatch → run worker → Atlas validate → accept/retry/reroute |
| `validator.py` | **L0 Atlas**: deterministic checks + LLM verdict; `Verdict`/`Dispatch`/`Supervisor`; `@@VERDICT` / `@@DISPATCH` parsing |
| `router.py` | Weighted-keyword classifier (`classify`) + reroute resolution (`resolve_reroute`) + layer registry (`LAYERS`, `SUPERVISOR`, `ALL_LAYERS`) + `apply_workflow()` |
| `runner.py` | The 4 executors + `Event` dataclass + reroute scanning + `get_executor()` |
| `workflow.py` | **No-code graph loader/serializer**: `Node`/`Edge`/`Workflow`, route/reroute traversal, validate, YAML round-trip. `python -m agent_orchestrator.workflow [path] [test-cmd]` to validate + preview. |
| `agents.py` | Parses the **5** `.claude/agents/orch-*.md` (L0–L4) → `AgentLayer` (system prompt, tools, permission mode) |
| `catalog.py` | Load / browse / fuzzy-resolve the L1 asset store; builds the prompt `context_blob()` |
| `state.py` | Per-layer status + rolling event log; renders UI panels (md + html) |
| `config.py` | Env-var contract + path auto-detection + **`orchestrator.yaml` loader** (`cfg()`, `SETTINGS`, `REPO_ROOT`, `PKG_ROOT`) |
| `orchestrator.yaml` | **No-code setup file** — paths, model, backend, routing, supervision, per-backend knobs (see §7) |
| `workflows/*.workflow.yaml` | Drag-and-drop agent graphs (`default`, `custom`, `examples/`). See `workflows/README.md` |
| `assets/catalog.yaml` | The L1 common asset store (robots / environments / props / sensors) |
| `assets/store/` | Locally-owned USD assets (`relative_to: repo` entries point here) |
| `workspace/` | Generated scripts / datasets / runs / logs (`$WORKSPACE_DIR`); plus `chat/` (conversation thread memory) |
| `nemoclaw/` | NemoClaw skill package + `install_skill.sh` to deploy into a sandbox |
| `.venv/` | Isolated venv for the UI (see §8 — why it's separate) |

---

## 5. Backends (how a layer actually executes)

`get_executor(dry_run, allow_execution, backend)` in `runner.py` selects one.
Resolution order: **explicit arg > env `ORCH_BACKEND` > `orchestrator.yaml`
(`runtime.backend`) > `sdk`**. Per-backend knobs come from the config's
`backends.<name>` block (`SETTINGS.backend_config`).

| Backend | Class | What it does |
|---------|-------|--------------|
| `dryrun` | `DryRunExecutor` | Routes + plans, **no API calls**. Yields what *would* run (tools, permission, cwd). Use to test wiring without spending tokens. |
| `sdk` *(default)* | `SDKExecutor` | Runs the layer via the **Claude Agent SDK** (`query` + `ClaudeAgentOptions`), `setting_sources=["project"]` so it loads this repo's `.claude` skills + agents. Streams assistant text / tool calls / result + cost. |
| `openclaw` | `OpenClawExecutor` | Runs the layer via `openclaw agent --local --json`. Carries the layer system prompt in the message body. Works without Anthropic creds. |
| `nemoclaw` | `NemoClawExecutor` | Runs the layer **inside a NemoClaw NIM sandbox** via `nemoclaw <sandbox> exec`. Prompt is base64-piped to an in-sandbox agent CLI (`backends.nemoclaw.agent_cmd` / `$NEMOCLAW_AGENT_CMD`, default `claude -p`). **Requires a sandbox** (`backends.nemoclaw.sandbox` / `$NEMOCLAW_SANDBOX`). |

**Permissions / safety** (`agents.py`): L0–L3 get `acceptEdits` (edit files only).
L4 gets `bypassPermissions` because it launches Bash (training/teleop) — but the
UI/CLI `allow_execution` flag is **off by default**; when off, the SDK executor
downgrades L4 to `acceptEdits` so it won't spawn processes.

**Per-layer tools** (`agents.py::_ALLOWED_TOOLS`): L1–L4 get Read/Write/Edit/
Glob/Grep/Bash/Skill; L2 + L3 additionally get WebSearch/WebFetch. **L0 (Atlas)**
gets Read/Write/Glob/Grep/Bash/Skill — **no Edit** (it validates, it doesn't
author).

### Local models (OpenClaw / NemoClaw + Ollama) — credential-free

The `openclaw` and `nemoclaw` backends let the whole loop — **author script →
validate → execute** — run on **local Ollama models**, no Anthropic key. This is
the configured default here (`orchestrator.yaml`):

- `runtime.backend: openclaw`, `allow_execution: true`
- `backends.openclaw.model: ollama/gemma4:12b` (passed as `--model`; also used by
  the nemoclaw `agent_cmd`)
- `supervision.use_llm: false` — local models are unreliable at the `@@VERDICT` /
  `@@REROUTE` token protocols, so Atlas runs **deterministic checks only** (these
  still catch tracebacks, missing files, etc.). Worker reroutes simply won't fire
  unless the model emits the token — acceptable.

Why it works end-to-end: OpenClaw's `tools.profile: coding` + exec policy
(`security=full, ask=off`) mean the local agent can **Write files and run Bash**.
The `OpenClawExecutor` carries the layer system prompt in the `-m` message and
pins generated files to the **absolute** `$WORKSPACE_DIR` (OpenClaw overrides that
env with its own workspace, so without pinning Atlas can't find the artifacts).

Requirements / gotchas for a local model:
1. **Pull it:** `ollama pull gemma4:12b`.
2. **Declare it** in `~/.openclaw/openclaw.json` →
   `models.providers.ollama.models` (else `openclaw --model <id>` is rejected).
   Installed here: gemma3:12b, gemma4:{12b,e4b,31b}, nemotron-3-super.
3. **Quality:** small local models often emit the **deprecated `omni.isaac.core`**
   namespace (modern is `isaacsim.core.*`) and weaker tool-use — review generated
   scripts (or run them past the `isaac-sim-validator` skill) before trusting them.
   Stronger local options: `gemma4:31b`, or `nemotron-3-super` (the only local
   model with reasoning).
4. **Per-model scope is global** — `backends.openclaw.model` applies to *all*
   layers; there is no per-layer model selection in code yet.
5. **NemoClaw** reuses the same setup *inside the sandbox*:
   `backends.nemoclaw.agent_cmd: openclaw agent --local --json --session-id
   nemo-orch -m "$(cat)"`. The executor base64-pipes the prompt to stdin; `$(cat)`
   feeds it into `-m`. The sandbox must have OpenClaw + Ollama + the model.
6. **Live Isaac/Kit** L4 runs still can't launch in this harness (GPU/Kit spawn
   kills the shell, signal 16) — run those in a real terminal.

---

## 6. How to run

```bash
# Gradio dashboard → http://localhost:7860
agent_orchestrator/.venv/bin/python -m agent_orchestrator.app

# Visual node editor + conversation mode → http://localhost:7870
agent_orchestrator/.venv/bin/python -m agent_orchestrator.editor

# Headless CLI (same loop)
python -m agent_orchestrator.cli "place 6 nova carters in the warehouse aisle" --dry-run
python -m agent_orchestrator.cli --classify "train cartpole for 200 iters"   # just print routing
python -m agent_orchestrator.cli "write a PPO reward for spot locomotion" --layer 2
python -m agent_orchestrator.cli "place 4 ur10 arms on tables" --backend openclaw --no-supervise
NEMOCLAW_SANDBOX=robotcontrol \
  python -m agent_orchestrator.cli "place 4 ur10 arms on tables" --backend nemoclaw

# Validate / preview a workflow graph (and optionally route a test command)
python -m agent_orchestrator.workflow workflows/examples/placement-and-train.workflow.yaml "train cartpole"
```

CLI flags: `--layer {1..4}` (force), `--dry-run`, `--allow-execution` (let L4 run
Bash), `--backend {dryrun,sdk,openclaw,nemoclaw}`, `--no-supervise` (turn Atlas
off), `--classify CMD`.

**First, sanity-check routing with `--classify` / `--dry-run`** before spending
tokens — it validates wiring end-to-end with zero API cost (deterministic Atlas
checks still run).

---

## 7. No-code configuration

Two editable files configure the whole orchestrator — **no Python changes**.
Precedence everywhere: **env var > the file > built-in default**.

### `orchestrator.yaml` (`config.py::cfg()`)
Optional setup file (delete it → fall back to defaults; point `$ORCH_CONFIG`
elsewhere to use another). Blocks:

- `environment` — `isaac_sim_dir`, `isaac_lab_dir`, `workspace_dir`
- `model.id` — default `claude-opus-4-8`
- `runtime` — `backend` (default `sdk`), `dry_run`, `allow_execution`, `max_turns`
- `routing` — `default_layer` (**1**), `max_hops` (4), `use_workflow`, `workflow`
- `supervision` — `enabled` (true), `use_llm` (true), `max_retries` (2)
- `backends.{openclaw,nemoclaw}` — per-backend timeouts/model/sandbox
- `auth.anthropic_api_key` — optional; env still wins (don't commit a key)
- `layers` — read-only reference block (editing it does nothing; change the
  `.claude/agents/*.md` to change behavior)

### Workflow graph (`workflow.py`, `workflows/*.workflow.yaml`)
A graph of **agent nodes** wired by **edges** instead of fixed layers:

- `trigger` node = "Command In"; `agent` nodes (one per `key` = assets/rl/il/exec);
  optional `supervisor` node (Atlas, L0, never a route target).
- Edge kinds: `route` (trigger→agent, taken by keyword match — entry routing),
  `reroute` (agent→agent, taken on `@@REROUTE`), `validate` (worker→Atlas).
- Exactly one agent node must be `default: true` (the fall-through lane).

`router.apply_workflow()` sources the routing signals + reroute map from the
graph **when `routing.use_workflow: true`**. It's defensive: **any load error or
an empty graph silently keeps the built-in tables** (the `if sig:` guard), so a
bad/empty workflow never breaks routing.

> **Heads-up:** `workflows/default.workflow.yaml` is currently an **empty stub**
> (`nodes: []`). With `use_workflow: true` in `orchestrator.yaml`, that means the
> graph contributes nothing and the **built-in keyword tables in `router.py` are
> what actually run**. `workflows/examples/placement-and-train.workflow.yaml` is a
> real, hand-authored example of the format (note it omits a `default:` node and
> uses bare palette agent names, so `wf.validate()` flags it — it's illustrative).

---

## 8. Visual editor & conversation mode (`editor.py`)

A standalone **FastAPI** app (separate from Gradio so they never collide),
serving `web/editor.html` on **:7870** (`$ORCH_EDITOR_PORT`).

- **Canvas** — drag agents (Atlas L0, L1–L4) from a palette, wire ports, mark one
  agent ★ default, **Save** (defaults to `custom.workflow.yaml`, leaving the
  curated default intact), then **Run** to dispatch a command *through the graph
  you built* (SSE stream). Endpoints: `GET /`, `GET /api/state`, `POST /api/load`,
  `POST /api/save`, `POST /api/run`.
- **Conversation mode** — `/api/session/{start,step,finish}`: runs the workflow
  **turn by turn**, shows tool calls + output, and lets the user **pick the next
  step** from the choices the LLM/Atlas proposes (retry, reroute, accept, or send
  to any layer). The recommended choice mirrors what the auto-orchestrator would
  do.
- **Persistent thread memory** — each chat thread is a JSON file under
  `$WORKSPACE_DIR/chat/<id>.json`. The running transcript survives page reloads
  **and** server restarts, and is injected into every later turn's prompt so
  chats remember earlier ones. Tunables in `editor.py`: `_MEM_MAX_TURNS` (16),
  `_MEM_SUMMARY_CHARS` (240).
- **Idle timeout** — `$ORCH_TURN_TIMEOUT` (default 120s): a stalled SDK/MCP turn
  surfaces as an error instead of hanging "running" forever.

---

## 9. Layer 1 asset store (catalog)

`assets/catalog.yaml` is one categorized store (`robots`, `environments`,
`props`, `sensors`). Each entry maps a friendly name → a USD reference plus
placement hints (`start_z`, `drive`, `separation_m`, `scale`). USD refs are
either **Isaac Lab Nucleus tokens** (`{ISAAC_NUCLEUS_DIR}/...`, resolved at sim
runtime) or **repo-relative paths** (`relative_to: repo`, pointing into
`assets/store/`).

`catalog.py` loads / fuzzy-searches it (`find()`, `get()`) and renders the
compact `context_blob()` injected into the **L1 agent's prompt** so it resolves
names from the catalog and **never invents USD paths**. Browse/search it in the
UI's **Asset Catalog** tab. Read-only catalog questions ("what robots are
available") route to L1 too (see `router._SIGNALS[1]`).

**Example L1 output** (see `workspace/generated/scene/place_ur10_in_warehouse.py`):
a non-destructive USD-composition script that sublayers the warehouse env,
references the robot as an override prim grounded at the catalog's `start_z`,
and is idempotent (re-running re-authors instead of stacking duplicate refs).

---

## 10. OpenClaw / NemoClaw integration (two-way)

Both are wired the same two ways:

1. **Discoverable as a skill** — an `isaac-agent-orchestrator` skill tells the
   host agent how to classify, dispatch, browse the catalog, and launch the UI.
   - OpenClaw: registered in `~/.openclaw/openclaw.json`. Verify:
     `openclaw skills list | grep isaac-agent-orchestrator` → `✓ ready 🤖`.
     A **dedicated OpenClaw agent** `isaac-robot-orchestrator-master` is the master
     entry point (created via `openclaw agents add`, model `ollama/gemma4:12b`,
     workspace `~/.openclaw/agents/isaac-robot-orchestrator-master/workspace` with
     an `AGENTS.md` that routes every robotics request through
     `python -m agent_orchestrator.cli … --backend openclaw`). OpenClaw routing is
     **channel-based** (`openclaw agents bind`), not keyword — so target this agent
     directly: `openclaw chat --agent isaac-robot-orchestrator-master`, or bind a
     channel to it.
   - NemoClaw: package at `agent_orchestrator/nemoclaw/skill/...`; deploy with
     `agent_orchestrator/nemoclaw/install_skill.sh <sandbox>`. The repo must be
     reachable inside the sandbox at `$ORCHESTRATOR_DIR` (mount with
     `nemoclaw <sandbox> share mount ...` if needed).
2. **Runs layers *through* the host runtime** — pick the `openclaw` or
   `nemoclaw` backend (UI dropdown / `--backend` / `ORCH_BACKEND`).

> **Known environment constraint** (from project memory): this Claude Code
> harness **cannot launch Kit / Isaac Sim itself** — a GPU/Kit spawn kills the
> Bash shell (signal 16). Renders and live Isaac launches must be run by the
> user in their own terminal. The orchestrator's L4 execution against a live sim
> is therefore best driven outside the harness.

---

## 11. Environment & setup

**The UI runs in its own venv** (`agent_orchestrator/.venv`). Reason: gradio
needs `huggingface-hub>=1.2`, which conflicts with the base env's
`lerobot`/`transformers` (`<1.0`). The layer agents shell out to Isaac Lab /
LeRobot in *their own* interpreters, so this split is intentional — don't try to
unify them.

```bash
python -m venv agent_orchestrator/.venv
agent_orchestrator/.venv/bin/pip install -r agent_orchestrator/requirements.txt
```

**Auth:** the Claude Agent SDK uses `ANTHROPIC_API_KEY` if set, else the
logged-in `claude` CLI. Model via `ORCH_MODEL` (default `claude-opus-4-8`).

**Path / runtime contract** (`config.py`, auto-detected, override via env or
`orchestrator.yaml`):

| Var | Default | Purpose |
|-----|---------|---------|
| `ISAAC_SIM_DIR` | `~/IsaacSim` or `_build/linux-x86_64/release` | Isaac Sim install |
| `ISAAC_LAB_DIR` | `~/IsaacLab` | Isaac Lab checkout (L2/L3/L4 source of truth) |
| `WORKSPACE_DIR` | `agent_orchestrator/workspace` | Generated scripts/datasets/runs/logs + chat memory |
| `ORCH_MODEL` | `claude-opus-4-8` | Model id |
| `ORCH_BACKEND` | `sdk` | Default backend if `--backend` unset |
| `ORCH_CONFIG` | `agent_orchestrator/orchestrator.yaml` | Alternate config file path |
| `ORCH_SUPERVISE` | `1` | `0` disables Atlas (L0) supervision |
| `ORCH_TURN_TIMEOUT` | `120` | Per-turn idle timeout (editor) |
| `NEMOCLAW_SANDBOX` | *(none)* | **Required** for the nemoclaw backend |

`SETTINGS.ensure_workspace()` creates `generated/{rl,il}`, `runs`, `datasets`,
`logs` under `$WORKSPACE_DIR` before a real run.

---

## 12. Where to look when X breaks

- **Wrong layer chosen** → `router.py::_SIGNALS` (weighted keyword table) and
  `classify()`. Test with `--classify "<cmd>"`. Default on no-match is **L1**.
- **Atlas keeps retrying / wrong verdict** → `validator.py` (`_FAIL_SIGNS`,
  `_WARN_SIGNS`, `_deterministic_checks`, `_merge`) and the `orch-l0-supervisor.md`
  body. Disable with `--no-supervise` / `ORCH_SUPERVISE=0` / `supervision.enabled`.
- **Supervisor makes no LLM call** → `supervision.use_llm` is false, or it's a
  dry-run (LLM verdict is skipped; deterministic checks still run).
- **Reroute ignored / loops** → `runner._REROUTE_RE` (L4 must emit the exact
  `@@REROUTE: <target> :: <reason>` line), `validator._VERDICT_RE`, and the
  `orchestrate.py` hop logic (`max_hops`, default 4) / retry logic (`max_retries`,
  default 2).
- **Workflow graph not taking effect** → `routing.use_workflow` must be true AND
  the graph non-empty; an empty/broken graph silently keeps built-ins. Validate
  with `python -m agent_orchestrator.workflow <path>`.
- **Agent has wrong tools / permissions** → `agents.py::_ALLOWED_TOOLS` /
  `_PERMISSION` (now keyed 0–4). System prompt content → the `.claude/agents/*.md`
  body.
- **"claude-agent-sdk not installed"** → install it in the `.venv`, or use
  `--dry-run` / `--backend dryrun`.
- **L4 won't run training** → `allow_execution` is off (default). Pass
  `--allow-execution` (CLI) or tick the UI checkbox.
- **Editor turn hangs** → `$ORCH_TURN_TIMEOUT`; a slow project MCP server is the
  usual culprit. Try dry-run or a single non-supervised call.
- **Nucleus paths unresolved** → expected outside Isaac; tokens resolve at sim
  runtime. Repo-relative assets are resolved by `AssetEntry.resolved_usd()`.
- **`NEMOCLAW_SANDBOX is not set`** → required for the nemoclaw backend; point it
  at a sandbox from `nemoclaw list` (or `backends.nemoclaw.sandbox`).

---

## 13. Open items / notes for the next person

- Code is currently **untracked** (`git status` shows `agent_orchestrator/`,
  `warehouse_scene/`, `.claude/agents/` as `??`). Nothing is committed yet —
  decide what to stage (exclude `.venv/`, `__pycache__/`, and arguably
  `workspace/chat/` + generated runs).
- **`workflows/default.workflow.yaml` is an empty stub** while
  `routing.use_workflow: true`. Either populate it with the real graph (mirroring
  `router._SIGNALS`) or accept that the built-in tables are authoritative. The
  example under `workflows/examples/` shows the intended schema but won't pass
  `validate()` as-is (no `default:` node; palette agent names not declared in
  `agents:`).
- `warehouse_scene/` (sibling dir) holds the standalone warehouse USD + build /
  launch / texture scripts and an `rl/` folder — it's the scene content the
  orchestrator's L1 places into, not part of the orchestrator package itself.
- The router is deliberately a cheap deterministic classifier for instant UI
  feedback; the real reasoning is in the layer agents + Atlas. Don't over-tune
  keywords — forcing a layer (and Atlas dispatch on ambiguity) is always
  available.
- `README.md` covers the same system from a user's angle and is kept current;
  this HANDOFF is the maintainer's map.
