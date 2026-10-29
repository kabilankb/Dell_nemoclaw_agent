# Running isaac-claw on Nebius Token Factory

The agent's brain (Nemotron) is served by **Nebius Token Factory** instead of a
local Ollama/vLLM server. Isaac Sim / Isaac Lab still run on your GPU machine;
only model inference moves to Nebius.

| Role | Model (Token Factory ID) |
|---|---|
| Agent / tool calling (default) | `nvidia/nemotron-3-super-120b-a12b` |
| Fast, cheap calls / fallback | `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` |
| Heavy planning (optional) | `nvidia/Nemotron-3-Ultra-550b-a55b` |

Endpoint: `https://api.tokenfactory.nebius.com/v1` (OpenAI-compatible).

Verified working with OpenClaw on 2026-10-27 — see [`docs/NEBIUS_TEST_REPORT.md`](docs/NEBIUS_TEST_REPORT.md).

## 1. Check your key works
```bash
export NEBIUS_API_KEY=<your key from tokenfactory.nebius.com>
pip install openai
python scripts/test_nebius.py
```
It prints the NVIDIA model IDs your key can see and a test answer from each model.
If an ID differs from the table, use the printed one in the configs below.

## 2. NemoClaw (sandboxed)
```bash
cd agents/nemoclaw
nemoclaw onboard            # choose an OpenAI-compatible / custom provider:
                            #   base URL  https://api.tokenfactory.nebius.com/v1
                            #   API key   $NEBIUS_API_KEY
                            #   model     nvidia/nemotron-3-super-120b-a12b
./install_skill.sh <sandbox>
```
The sandbox egress allowlist (`sandbox/policies/orchestrator-policy-additions.yaml`)
already permits `api.tokenfactory.nebius.com`; the `nebius` profile is in
`blueprint-profile.yaml` and the orchestrator `blueprint.yaml`.

## 3. OpenClaw (host, unsandboxed)
Merge `agents/openclaw/model.json` into `~/.openclaw/openclaw.json`. The primary
model is now `nebius/nvidia/nemotron-3-super-120b-a12b`, with Nano and local Gemma
as fallbacks. Make sure `NEBIUS_API_KEY` is exported in the shell that runs `openclaw tui`.

## Files changed for Nebius
- `agents/nemoclaw/blueprint-profile.yaml` — `nebius` inference profile (default)
- `agents/nemoclaw/agent/isaac-orchestrator/blueprint.yaml` — `nebius` profile
- `agents/nemoclaw/agent/isaac-orchestrator/manifest.yaml` — Token Factory phone-home host
- `sandbox/policies/orchestrator-policy-additions.yaml` — egress rule for Token Factory
- `agents/openclaw/model.json` — `nebius` provider, Nemotron primary
- `agents/core/orchestrator.yaml` — OpenClaw backend model → Nemotron on Nebius
- `scripts/test_nebius.py` — connection check
