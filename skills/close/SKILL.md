---
name: "isaac-close"
description: "Close / stop / shut down the running Isaac Sim simulation AND any Isaac Lab training, freeing the GPU. Use whenever the user wants to end the simulation or a training run: close the sim, stop the simulation, shut it down, kill the sim, stop training, close isaac, end the session, free the GPU, quit. Trigger keywords: close, stop, shut down, shutdown, kill the sim, end, quit, stop the simulation, stop training, stop the lab, close isaac sim, free gpu, close the warehouse."
user-invocable: true
---

# Close the Simulation / Training — RUN ONE COMMAND

⚠️ EXECUTE skill, not a planning skill. Do NOT explain or plan. **Run the single
command below with your shell/exec tool**, then report what it printed.

## The command
```bash
~/isaac-claw/agents/openclaw/claw close
```
That stops whatever is running — a sim OR an Isaac Lab training run (only one runs
at a time) — and frees the GPU and the `:8226` bridge. Safe to run anytime; if
nothing is running it just reports that.

### Your FIRST action MUST be a shell tool call — no prose first.
> User: *close the sim*  ·  *stop the simulation*  ·  *shut it down*  ·  *stop training*
> Assistant: *(calls shell tool)* `~/isaac-claw/agents/openclaw/claw close`
> Assistant: *(after it returns)* "Closed — the sim is stopped and the GPU is free."

## After it runs
Report the result: `closed — GPU free` means it's down. If it says a sim is still
shutting down, run `~/isaac-claw/agents/openclaw/claw close` once more.

## Related
- Open a scene + robot: [`../task/SKILL.md`](../task/SKILL.md)
- Check what's running first: `~/isaac-claw/agents/openclaw/claw status`
