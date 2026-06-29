# agents/openclaw — open-model runtime config (Gemma & friends)

OpenClaw runs **open local models** (Gemma, Nemotron-via-Ollama, …) directly on
the host, unsandboxed. It is the lightweight way to drive isaac-claw.

This directory holds **only the model/agent config**. All shared agent logic
lives in [`../core/`](../core) — OpenClaw and NemoClaw differ in config, not code.

## Setup
```bash
ollama pull gemma4:12b                       # the default model
# point OpenClaw at it: merge model.json into ~/.openclaw/openclaw.json
#   (or symlink the 'models'/'agents' blocks)
```

## Deploy the isaac-claw skills into OpenClaw
OpenClaw discovers skills under `~/.openclaw/workspace/skills/`. Symlink the
master library so the model can find every skill:
```bash
ln -s "$ISAAC_CLAW_DIR/skills"/* ~/.openclaw/workspace/skills/
```
The model loads [`../../skills/skills.md`](../../skills/skills.md) first (master
router), then opens individual `SKILL.md` files on demand.

## Run the TUI
```bash
openclaw tui                                 # interactive chat
openclaw agent --local -m "open the warehouse with a G1"   # one-shot
```
A prompt → the model matches it against the skill router → the skill issues
HTTP calls to the **Isaac Control Server** (`http://localhost:5561`, started from
`isaac_sim/scripts/isaac_control_server.py`).

## Pick the model at runtime
```bash
openclaw agent --local --model ollama/gemma4:31b -m "train a G1 to walk"
```
