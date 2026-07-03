#!/usr/bin/env bash
# Make a NemoClaw sandbox reliably drive Isaac by giving the local model DEDICATED
# `isaac__*` MCP tools (instead of the generic exec/code-mode bridge that small
# models mangle). Proven fix for "the model won't/can't run curl / hallucinates".
#
#   ./apply_mcp_fix.sh <sandbox>
#
# What it does inside the sandbox container (via docker exec — fast, root):
#   1. installs isaac-mcp.mjs into /sandbox/.openclaw/workspace/
#   2. edits /sandbox/.openclaw/openclaw.json:  toolSearch=false,
#      allow=[read,isaac__*], sandbox.tools.alsoAllow=[bundle-mcp],
#      mcp.servers.isaac -> node isaac-mcp.mjs, agents.defaults.models={}
#   3. appends an "Isaac Sim control" section to workspace/AGENTS.md
#   4. recomputes /sandbox/.openclaw/.config-hash (sha256  openclaw.json)
#   5. reloads with `nemoclaw <sandbox> recover`  (NOT `docker restart` — that
#      can tear a freshly-created sandbox down).
set -euo pipefail

SB="${1:-}"
[[ -z "$SB" ]] && { echo "usage: apply_mcp_fix.sh <sandbox>" >&2; exit 1; }
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_SRC="$HERE/isaac-mcp.mjs"
[[ -f "$MCP_SRC" ]] || { echo "error: $MCP_SRC not found" >&2; exit 1; }

CT="$(docker ps --format '{{.Names}}' | grep -iE "openshell-${SB}-" | head -1 || true)"
[[ -z "$CT" ]] && { echo "error: no running container for sandbox '$SB' (nemoclaw list?)" >&2; exit 1; }
echo "→ sandbox '$SB' → container $CT"

echo "  [1/5] install isaac-mcp.mjs"
docker exec "$CT" bash -lc 'mkdir -p /sandbox/.openclaw/workspace'
docker cp "$MCP_SRC" "$CT":/sandbox/.openclaw/workspace/isaac-mcp.mjs
docker exec "$CT" bash -lc 'chown sandbox:sandbox /sandbox/.openclaw/workspace/isaac-mcp.mjs && chmod 644 /sandbox/.openclaw/workspace/isaac-mcp.mjs'

echo "  [2/5] patch openclaw.json (+ [4/5] rehash)"
docker exec "$CT" bash -lc 'cat > /tmp/_mcp_patch.mjs <<"JS"
import fs from "node:fs"; import crypto from "node:crypto";
const p="/sandbox/.openclaw/openclaw.json"; const c=JSON.parse(fs.readFileSync(p,"utf8"));
c.agents=c.agents||{}; c.agents.defaults=c.agents.defaults||{}; c.agents.defaults.models={};
c.tools={toolSearch:false,profile:"coding",allow:["read","isaac__*"],sandbox:{tools:{alsoAllow:["bundle-mcp"]}}};
c.mcp={servers:{isaac:{command:"node",args:["--no-warnings","/sandbox/.openclaw/workspace/isaac-mcp.mjs"]}}};
fs.writeFileSync(p, JSON.stringify(c,null,2)+"\n");
const h=crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");
fs.writeFileSync("/sandbox/.openclaw/.config-hash", h+"  openclaw.json\n");
console.log("    sha256="+h);
JS
node /tmp/_mcp_patch.mjs && rm -f /tmp/_mcp_patch.mjs
chown sandbox:sandbox /sandbox/.openclaw/openclaw.json /sandbox/.openclaw/.config-hash'

echo "  [3/5] AGENTS.md guidance"
docker exec "$CT" bash -lc 'A=/sandbox/.openclaw/workspace/AGENTS.md; touch "$A"
if ! grep -q "Isaac Sim control (USE THESE TOOLS)" "$A"; then cat >> "$A" <<"MD"

## Isaac Sim control (USE THESE TOOLS)

Control NVIDIA Isaac Sim ONLY through the dedicated `isaac__*` tools. Do NOT use
exec, curl, node, fetch, or shell for Isaac — call the tool directly:
- list robots -> isaac__list_robots
- how many tasks / environments / what can I train -> isaac__list_environments
- what can I open / templates -> isaac__list_templates
- what scenes -> isaac__list_scenes
- status / is it running (quick) -> isaac__sim_status
- training progress / "how is the training going" / detailed status -> isaac__training_status
    (returns job info + live log tail: iteration, rewards, timesteps, ETA — report those precisely)
- open/launch the sim (e.g. "open the warehouse with spot", "open hospital with agibot_a2d")
    -> isaac__open_scene {env, robot?, anchor?}   (ANY robot works in ANY environment)
- close/stop the sim -> isaac__close_sim
- train / run a task (e.g. "train the G1 dance task, gui, 2 envs") -> isaac__train_task {task, backend?, algorithm?, num_envs?, gui?}
    * task ids come from isaac__list_environments. AMP dance (id contains "AMP-Dance")
      REQUIRES backend="skrl" and algorithm="amp".
    * only ONE GPU job at a time — close the running job first.
- stop training / cancel the run / kill the job -> isaac__stop_training
- tuned / advised-parameter training (e.g. "train the Go2, tuned for sim2real / more exploration / fix shuffling"):
    1) call isaac__tuning_guide {backend:"rsl_rl"} to read advised ranges + the symptom->knob table
    2) pick values for the requirement, then isaac__train_task {task, num_envs, params:{...}}
       (friendly knobs: learning_rate, entropy_coef, gamma, clip_param, num_steps_per_env, reward_<term>...)
    Never invent hyperparameters — take them from the guide safe ranges.
- play/evaluate (INFERENCE for) a trained policy -> isaac__play_policy / isaac__eval_policy {task, checkpoint?}
The valid env/robot/task values are supplied LIVE in each tool schema (fetched from the
control server), and isaac__list_* returns the authoritative lists. Report ONLY the JSON the
tool returns; never invent names. Count arrays for "how many".
MD
fi
chown sandbox:sandbox "$A"'

echo "  [5/5] reload via recover"
nemoclaw "$SB" recover || true

echo "✓ applied. Verify: nemoclaw $SB connect  ->  openclaw tui  ->  \"how many tasks?\" / \"list robots\""
