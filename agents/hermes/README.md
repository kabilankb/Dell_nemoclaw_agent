# Duck pilot — a self-running Hermes agent for MicroDuck sim-to-real

A [Hermes](https://github.com/nvidia/nemoclaw/blob/main/docs/get-started/quickstart-hermes.mdx)
agent in its own NemoClaw sandbox (`duckpilot`), on Nemotron via **Nebius Token
Factory**, that takes the MicroDuck from nothing to the real robot:

```
train ──▶ gate (fall rate) ──▶ play: record clip + export ONNX ──▶ verify ──▶ deploy
   ▲            │ fail
   └── tune ◀───┘   resume from the checkpoint, lower learning rate (up to N generations)
```

The pipeline runs **on the host**, in the control server (`POST /pipeline/start`), not
inside an agent turn, so it survives the hour a full run takes. The agent starts it,
reports on it, and handles the one step a human must approve: loading onto the robot.

| Stage | What happens | Judged by |
|---|---|---|
| train | `isaaclab train` headless, 4096 envs, `presets=backlash` | finishes without error |
| gate | end-of-training fall rate (share of episodes ending in a fall) | ≤ `max_fall_rate` (0.25) |
| tune | resume from the last checkpoint, learning rate × 0.7 | next gate |
| play | headless rollout of the gated checkpoint: mp4 + `exported/policy.onnx` | export exists |
| verify | `isaac_lab/scripts/verify_policy.py`: merge external weights into one ONNX, input 61 / output 14, ONNX ≡ TorchScript (< 1e-4), finite + bounded actions, < 64 MiB | all 9 checks |
| deploy | `scp` to `DUCK_HOST`, `robotctl policy list`; then **waits**. `duck_deploy_confirm` (only after "the duck is on its stand") runs `sudo robotctl policy load walk …` | robot lists the policy |

Without `DUCK_HOST` the run ends as a **dry run**: the verified bundle
(`isaac_sim/_deploy/<task>_<time>/policy.onnx`, `manifest.json`, `DEPLOY.md` with the
exact robot commands and the rollback) is ready to copy by hand.

## Setup

```bash
agents/hermes/install_duckpilot.sh         # onboard the sandbox (Nebius) + policy + MCP + skill
agents/hermes/install_duckpilot.sh --update  # after editing the skill or isaac-mcp.mjs
```

For the real robot, add to `~/.openclaw/.env` and restart (`./demo.sh down && ./demo.sh up`):

```bash
DUCK_HOST=microduck@192.168.1.50     # passwordless ssh key + passwordless `sudo robotctl` on the duck
DUCK_POLICY_DIR=/home/microduck       # optional
DUCK_POLICY_SLOT=walk                 # optional
```

`./demo.sh up/down/status` start and stop the duck pilot with everything else; the
console has a **Duck pilot** tab next to the Claw.

## Talking to it

| Say | It does |
|---|---|
| "run the full duck pipeline" | train 1500 its → … → deploy (or dry run) |
| "run it with 3000 iterations and at most 3 tries" | same, `iterations: 3000, max_generations: 3` |
| "ship the best policy we already have" | skips training: play → export → verify → deploy (~2 min) |
| "how is the duck doing?" | the status card |
| "the duck is on its stand, load it" | loads the staged policy on the robot |
| "stop" | stops the run / cancels a staged deploy |

Replies are a fixed card rendered by the server from the real pipeline state (the
skill makes the agent relay it verbatim), e.g.:

```
**MicroDuck · flat** — Done (dry run)

Policy     2026-10-29_15-19-26 · iteration 299 (best existing)
Verify     ✅ 9/9 checks · 786 KB · 61→14 · Δ onnx/torch 2e-06
Bundle     isaac_sim/_deploy/IsaacContrib-Velocity-Flat-MicroDuck_20261029-161204
Robot      not configured (dry run)

Next: set DUCK_HOST=microduck@<ip> in ~/.openclaw/.env, restart with ./demo.sh up, and ship again to put it on the robot.
```

From a terminal — `./duck` at the repo root (same cards, no browser):

```bash
./duck run -n 1500 --tries 2      # full pipeline, then a live card until it finishes
./duck ship                       # best checkpoint → play → verify → deploy (~1 min)
./duck status | watch | history   # card · live card · every step with times
./duck deploy                     # asks "is the duck on its stand?" before loading
./duck stop
./duck ask "how is the duck doing?"   # one message to the Hermes agent
./duck chat                           # talk to it until you type exit
```

`run/ship/status/watch/deploy/stop` call the control server directly; `ask/chat` go
through the Hermes agent in the sandbox.

## Files

| File | Purpose |
|---|---|
| `skills/duck-pilot/SKILL.md` | the skill: tool choice, safety rules, reply format |
| `install_duckpilot.sh` | onboard + provision the sandbox |
| `isaaclab-training-hermes.yaml` | egress policy: Hermes/node → `host.openshell.internal:5561` |
| `../nemoclaw/isaac-mcp.mjs` | the MCP tools, shared with the claw (`duck_pipeline_*`, `duck_deploy_confirm`) |
| `../../isaac_sim/scripts/isaac_control_server.py` | the pipeline (`/pipeline*`) |
| `../../isaac_lab/scripts/verify_policy.py` | the sim2real ONNX checks |

## Notes

- One GPU job at a time: the pipeline refuses to start while anything else trains.
- Restarting the control server forgets an in-flight pipeline (state is in memory)
  and orphans its training process — let it finish or `duck_pipeline_stop` first.
- The deploy confirmation is enforced by the server (`robot_on_stand: true`) and by
  the skill; the agent is told never to assume it.
