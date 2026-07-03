---
name: "isaac-claw-ops"
description: "Bootstrap and health-check the isaac-claw host services so everything runs from the OpenClaw TUI. Use FIRST, before any sim/train/spawn request, or when a control call fails to connect. Trigger keywords: start, bring up, boot, is it running, server down, connection refused, health, status, restart, cant connect, control server, set up isaac-claw."
user-invocable: true
---

# isaac-claw Ops — make everything run from the TUI

Before any control-server request, make sure the services are up. You (the model)
can run these shell commands directly — OpenClaw runs on the host.

## 1. Ensure the control server is up (always cheap, idempotent)
```bash
~/isaac-claw/agents/openclaw/clawup.sh
```
This starts the Isaac Control Server (`http://localhost:5561`) only if it isn't
already answering. Confirm:
```bash
curl -sf http://localhost:5561/envs >/dev/null && echo UP || echo DOWN
```

## 2. Health / status
```bash
~/isaac-claw/agents/openclaw/clawup.sh status
curl -s http://localhost:5561/status        # current GPU job (sim or training)
```

## 2b. RESTART the control server (after code/config changes)
If the user says "restart the control server / reload it / it's running old code",
or after editing server code, run:
```bash
~/isaac-claw/agents/openclaw/claw restart
```
This frees the GPU, kills the old server, and brings a fresh one up (loading new
code). Needed e.g. before GUI training or after a `claw` update.

## 3. Bring up a LIVE sim (needed for scene-load / robot-spawn)
A persistent Isaac Sim with the python_server bridge (:8226) must be running for
`/scene/load`, `/robot/spawn`, `/exec`. One command does both (server + sim):
```bash
~/isaac-claw/agents/openclaw/clawup.sh --sim warehouse.usd
```
Then poll until the sim is READY:
```bash
curl -s http://localhost:5561/status        # wait for running=true, kind="sim"
```
Heavy GPU bring-up takes ~1–2 min; check `GET /logs` for `[serve_sim] READY`.

## Self-heal rule
If ANY control call returns "connection refused" / no response:
1. run `clawup.sh` (step 1),
2. retry the original call once.
If `/scene/load` or `/robot/spawn` returns a 502 "no running sim", run
`clawup.sh --sim <scene>` (step 3), wait for `running=true`, then retry.

## Endpoints recap (all on `http://localhost:5561`)
`GET /envs /scenes /robots /status /logs` ·
`POST /sim/launch /scene/load /robot/spawn /exec /train /play /eval /stop`

> One GPU job at a time: a running sim blocks `/train` (and vice-versa). Stop with
> `POST /stop` before switching. See [`task/SKILL.md`](../task/SKILL.md) for the
> open-environment flow and [`training/SKILL.md`](../training/SKILL.md) for RL.
