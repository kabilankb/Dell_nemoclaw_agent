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

## Daily use — 2 commands
The control server auto-starts if the systemd service is installed, so launching is just:
```bash
nemoclaw <sandbox> connect            # enter the sandbox (e.g. nemoclaw isaacsim connect)
openclaw tui                          # inside it — PLAIN, no --session
```
Then just talk — sample prompts (all tested; more in [`RUNBOOK.md`](RUNBOOK.md)):
```
# inventory (read-only)
list robots
how many training tasks are available?
what can I open?
what's the sim status?

# open a scene — ANY robot in ANY environment
open the warehouse with spot
open hospital with agibot_a2d
open the office with a franka_panda at the entrance

# train (Spot is spawn-only; trainable: Go2/A1/B2/Lite3, the humanoids, …)
train the Unitree Go2 on rough terrain, headless, 4096 envs
train the Go2 rough, 500 envs, with entropy_coef 0.015, learning_rate 1e-3

# train a HUMANOID (G1 / H1 / XBot velocity tasks + the special G1 tasks)
train the Unitree G1 on rough terrain, headless, 4096 envs
train the Unitree H1 flat, headless, 4096 envs
train the XBot humanoid rough, headless, 2048 envs
train the G1 rough, gui, 64 envs            # visible window, few envs so it renders
train the G1 dance task, gui, 2 envs        # AMP dance → skrl + amp (auto — don't force a backend)
train the G1 BeyondMimic task, headless
train the G1 rough, headless, with learning_rate 1e-3, entropy_coef 0.01

# monitor / control (one GPU job at a time)
how's the training going?
play the Go2 rough policy
stop the training
close the sim
```

> **Rule:** use plain `openclaw tui`. A named `--session <name>` gets
> network-isolated and cannot reach the host control server on `:5561`.

## One-time setup (redo only if the sandbox is rebuilt)
```bash
nemoclaw onboard                      # wizard: pick a tool-capable model (nemotron-3-super:120b)
./install_skill.sh <sandbox>          # skills + :5561 egress policy + dedicated isaac__* MCP tools
cd ../openclaw && bash install-control-service.sh   # control server as an always-on systemd service
```
Full walkthrough, examples, and troubleshooting: [`RUNBOOK.md`](RUNBOOK.md).

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
