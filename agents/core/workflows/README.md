# Workflows — no-code, drag-and-drop agent graphs

A **workflow** describes the orchestration as a *graph of agent nodes* instead
of four fixed layers. Every node is an agent you drop on a canvas; every edge is
a wire you draw between nodes. The `.workflow.yaml` files here are exactly what a
visual node editor would serialize — so you can author them by hand or with a
canvas, no code either way.

```
   ⌨️ start ──▶ 📦 place   (Asset Placement)
        ├────▶ 🧠 rl      (RL Authoring)
        ├────▶ 🎭 il      (Imitation Learning)
        └────▶ ⚙️ exec    (Execution) *default
                 │  ↪ assets ─▶ 📦 place
                 │  ↪ rl     ─▶ 🧠 rl
                 └─ ↪ il     ─▶ 🎭 il
```

## Build it visually (drag-and-drop)

You can author these files by hand, or with the node canvas:

```bash
agent_orchestrator/.venv/bin/python -m agent_orchestrator.editor   # → http://localhost:7870
```

Drag agents from the palette, wire their ports, mark the **★** default lane,
**Save** (writes `custom.workflow.yaml` by default), then type a command and
**Run** to dispatch it through the graph. See the package README's *Visual
editor* section.

## The model (node = agent, not layer)

| Concept | In the YAML | On a canvas |
|---|---|---|
| **Palette** | `agents:` map | the list of agent boxes you can drag in |
| **Node** | `nodes:` entry | a box placed at `position: {x, y}` |
| **Trigger** | node `type: trigger` | where a command enters the graph |
| **Agent node** | node `type: agent` | an agent instance with `match` keywords |
| **Route edge** | `edges:` `type: route` | a wire trigger ▶ agent (entry routing) |
| **Reroute edge** | `edges:` `type: reroute` | a wire agent ↪ agent (handoff) |
| **Supervisor** | node `type: supervisor` | the L0 "Atlas" box that validates workers |
| **Validate edge** | `edges:` `type: validate` | a wire agent ✓ Atlas (post-run check) |

**Atlas (L0)** is a special supervisor node: it is *never* a route target. After
a worker runs, its output flows along a `validate` edge to Atlas, which emits a
verdict (PASS / WARN / FAIL) and can trigger a retry or reroute — bounded by
`settings.max_retries`. Toggle it from `supervision.*` in `../orchestrator.yaml`.

**Route** edges fire by keyword: each agent node's `match` list scores the
command (`{'\bppo\b': 2}` = regex pattern → weight); the highest score wins, and
the `default: true` node catches everything else.

**Reroute** edges fire on a signal: when an agent emits
`@@REROUTE: <signal>` (only the executor does this today), the wire whose
`signal:` matches is followed — bounded by `settings.max_hops`.

The `key:` and `layer:` fields on each node bridge the graph back to the
execution loop, so a graph is a drop-in replacement for the hard-coded router.

## How to edit (the "drag-and-drop" actions)

- **Move a node** → change its `position: {x, y}`.
- **Add an agent node** → add an `agents:` palette entry (pointing at a
  `.claude/agents/*.md` file) + a `nodes:` block + the `edges:` that wire it in.
- **Rewire routing** → add/remove `route` edges and adjust `match` keywords.
- **Change handoffs** → add/remove `reroute` edges (and their `signal:`).
- **Pick the fall-through** → set `default: true` on exactly one agent node and
  its incoming route edge.

## Validate / preview a graph

```bash
# render the graph + run validation
agent_orchestrator/.venv/bin/python -m agent_orchestrator.workflow            # default graph
python -m agent_orchestrator.workflow workflows/examples/placement-and-train.workflow.yaml
# also test-route a command through the graph:
python -m agent_orchestrator.workflow workflows/default.workflow.yaml "train cartpole"
```

## Activate a graph

In `../orchestrator.yaml`:

```yaml
routing:
  use_workflow: true                                   # source routing from a graph
  workflow: agent_orchestrator/workflows/default.workflow.yaml
```

Set `use_workflow: false` to fall back to the built-in keyword tables. A graph
that fails to load is ignored (the built-in tables stay in effect), so a typo
never breaks startup.

## Files

| File | What it is |
|---|---|
| `default.workflow.yaml` | The classic 4-agent pipeline as a graph (active default). Reproduces the built-in routing exactly. |
| `examples/placement-and-train.workflow.yaml` | A rewired variant — same agents, different default + extra handoff wire. Copy-edit to make your own. |
