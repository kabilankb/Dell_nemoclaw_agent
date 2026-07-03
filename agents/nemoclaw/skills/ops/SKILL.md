---
name: "isaac-claw-ops"
description: "Health / status of Isaac from the NemoClaw sandbox: is the sim running, what's the current GPU job, is the control server reachable. Use FIRST when a control call fails, or for 'is it running', 'status', 'health', 'check the server'. Trigger keywords: status, health, is it running, current job, check server, is the sim up, control server, connection."
user-invocable: true
---

# Ops / health — HTTP to the Control Server

Sandbox: no `claw`. Check Isaac health by HTTP via the **`exec`** tool:

```bash
# current GPU job (sim or training) + elapsed time
curl -s http://host.openshell.internal:5561/status

# is the control server reachable at all? (lists RL tasks)
curl -s http://host.openshell.internal:5561/envs | head -c 80
```

## Rules
- If a curl returns a connection error (not JSON), the **host control server is
  not running** — it must be started on the HOST (you cannot start it from the
  sandbox): `$ISAAC_LAB_PYTHON isaac_sim/scripts/isaac_control_server.py`. Tell the user.
- If `/status` shows `running:true`, report the `kind` (sim/train), `label`, and `elapsed_human`.

## After it runs
Report the JSON plainly. If healthy, tell the user what's running (or that the GPU
is free) and suggest the next action (open a scene / train).
