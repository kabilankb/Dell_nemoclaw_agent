---
name: "isaac-open-environment"
description: "THE skill for opening a simulation scene and putting a robot in it. Use for ANY request like 'open the warehouse', 'load a scene', 'spawn/add a robot', 'open the warehouse with a Unitree G1', 'bring up the sim'. This is the correct skill for these — do NOT use isaac-sim-orchestrator or mobility-gen for opening a scene or spawning a robot. Trigger keywords: open, open the warehouse, load scene, set up environment, bring up the sim, spawn robot, add robot, put a robot in, show me the robot, unitree, g1, h1, go2, carter."
user-invocable: true
---

# Open a scene + robot — RUN ONE COMMAND

⚠️ This is an EXECUTE skill, not a planning skill. Do **not** describe a plan,
do **not** delegate to other skills, do **not** invent file names. **Run the
single shell command below using your shell/exec tool**, then report its output.

### Your FIRST action MUST be a shell tool call — output no prose before it.
Do not write "Plan:", do not mention isaac-sim-orchestrator. Immediately call your
shell/exec tool with the `claw open` command. Example of the ONLY correct behavior:

> User: *open the warehouse with a Unitree G1*
> Assistant: *(calls shell tool)* `~/isaac-claw/agents/openclaw/claw open --scene warehouse.usd --robot unitree_g1 --z 0.74`
> Assistant: *(after it returns)* "Warehouse is up; spawned unitree_g1 at (0,0,0.74)."

If you find yourself writing a sentence that starts with "I will" or "Plan" or
"Based on", STOP — you are doing it wrong. Call the shell tool instead.

## The command
```bash
~/isaac-claw/agents/openclaw/claw open --scene <SCENE> --robot <ROBOT> [--x <X> --y <Y> --z <Z>]
```
That one command does everything: starts the control server if needed, brings up
a persistent Isaac Sim, waits until it is READY, and spawns the robot. It prints
the result. You do not need any other call.

## Fill the two arguments from the user's words
**SCENE** — match the user's words to an available scene:
- "warehouse" → `warehouse.usd`  (the only scene right now; use it by default)

**ROBOT** — match the user's words to a catalog key (these are the real keys):
- "Unitree G1" / "G1" → `unitree_g1`   ·   "Unitree H1" / "H1" → `unitree_h1`
- "Carter" / "Nova Carter" → `nova_carter`   ·   "Spot" → `spot`   ·   "Anymal" → `anymal`
- "Franka" → `franka_panda`   ·   "Digit" → `digit_v4`
- If unsure, first run `~/isaac-claw/agents/openclaw/claw robots` and pick the
  closest key. Never invent a robot name or USD path.

Optional **--z** is the standing height for legged robots (G1 ≈ `0.74`). Omit
x/y/z to use sensible defaults.

## Examples (copy the pattern exactly)
| User says | You run |
|---|---|
| open the warehouse with a Unitree G1 | `~/isaac-claw/agents/openclaw/claw open --scene warehouse.usd --robot unitree_g1 --z 0.74` |
| open the warehouse | `~/isaac-claw/agents/openclaw/claw open --scene warehouse.usd` |
| put a Spot in the warehouse | `~/isaac-claw/agents/openclaw/claw open --scene warehouse.usd --robot spot` |

## After it runs
Report what the command printed: whether the sim came up and the robot spawned
(`spawned <robot> at (...)`), or the exact error line. If it errors with the
server/sim not coming up, run `~/isaac-claw/agents/openclaw/claw up` once and
retry the open command. That is the whole procedure.
