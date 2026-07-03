---
name: "isaac-close"
description: "Stop / close the running Isaac Sim simulation OR Isaac Lab training and free the GPU, from the NemoClaw sandbox. Use for: close the sim, stop training, stop the lab, free the gpu, close isaac, end the session, close the warehouse. Trigger keywords: close, stop, shut down, stop training, free gpu, close sim, close the warehouse, end simulation."
user-invocable: true
---

# Close / Stop — ONE HTTP CALL

Sandbox: no `claw`. Stop whatever GPU job is running (a sim OR a training run) by
HTTP to the Isaac Control Server. Use the **`exec`** tool to run:

```bash
curl -s -X POST http://host.openshell.internal:5561/stop
```

The server SIGTERMs the active job and frees the GPU (and the :8226 bridge).

## After it runs
Report the JSON (`status`, what was stopped). Confirm with
`curl -s http://host.openshell.internal:5561/status` → `running:false`.
