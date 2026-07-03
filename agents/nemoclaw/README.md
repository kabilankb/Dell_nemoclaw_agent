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
./install_skill.sh <sandbox>          # installs the OPERATIONAL set into the sandbox
```
This now mirrors OpenClaw's `deploy.sh`: it installs the same small operational set
(`task`, `inventory`, `ops`, `close`, `training`, `teleop`, `mimicgen`) from the
shared [`../../skills/`](../../skills) library — NOT the old `isaac-agent-orchestrator`.
NemoClaw drives the simulator through the same `claw` CLI and control server as
OpenClaw — same skills, same endpoints, different model.

**Host resolution is automatic.** `claw` probes `localhost` then
`host.openshell.internal`, so inside the sandbox it reaches the host control server
with no config (override with `ISAAC_CONTROL_HOST=host.openshell.internal`). The repo
must be reachable in the sandbox at `~/isaac-claw` so the skills' `claw` path resolves.
