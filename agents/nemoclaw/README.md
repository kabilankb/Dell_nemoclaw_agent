# agents/nemoclaw — Nemotron sandbox runtime config

NemoClaw wraps OpenClaw inside an **OpenShell sandbox** with policy-controlled
network egress, routing inference to NVIDIA **Nemotron** (cloud, NCP, local NIM,
or vLLM). It is the always-on, locked-down way to drive isaac-claw.

This directory holds **only the Nemotron model/profile config and the sandbox
agent package**. All shared agent logic lives in [`../core/`](../core) — NemoClaw
and OpenClaw differ in config, not code.

## Contents
| Path | What it is |
|---|---|
| `blueprint-profile.yaml` | Nemotron inference profiles (default cloud / nim-local / vllm) to merge into the NemoClaw `blueprint.yaml`. |
| `agent/` | The sandbox agent package (manifest / start / blueprint / plugin) that deploys the isaac-claw orchestrator INTO a sandbox. |
| `skill/` | The SKILL.md package installed into the sandbox's OpenClaw so the model discovers isaac-claw. |
| `install_skill.sh` | `nemoclaw <sandbox> skill install` wrapper. |

## Setup
```bash
nemoclaw onboard                      # wizard: pick the 'default' (Nemotron) profile, create a sandbox
nemoclaw <sandbox> connect            # enter the sandbox
# inside the sandbox:
openclaw tui                          # chat with the Nemotron-backed agent
```

## Network policy (required for Goal 1)
The sandbox reaches the host **Isaac Control Server** on port 5561 only because a
policy whitelists it. The egress allowlists live in
[`../../sandbox/policies/`](../../sandbox/policies) and `blueprint-profile.yaml`
references the `isaac_control` addition. Deny-by-default: anything not listed is
blocked.

## Deploy the isaac-claw skills into the sandbox
```bash
./install_skill.sh <sandbox>          # installs skill/ into the sandbox's OpenClaw
```
Then the model loads [`../../skills/skills.md`](../../skills/skills.md) and drives
the simulator through the control server exactly like OpenClaw does — same skills,
same endpoints, different model.
