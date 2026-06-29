---
name: "isaac-open-environment"
description: "Open a simulation environment and place a robot in it from a natural-language request, for both Isaac Sim and Isaac Lab. Use when the user asks to open/load/set up a scene, bring up the sim, or put a specific robot into a world. Trigger keywords: open, load scene, set up environment, bring up the sim, warehouse, kitchen, spawn robot, add robot, put a G1 in, start the simulation, show me the robot."
user-invocable: true
---

# Open Environment + Robot (Goal 2 entry skill)

Turn a sentence like *"open the warehouse with a Unitree G1"* into control-server
calls. You decide the **scene** and the **robot**, then issue the HTTP calls. The
control server base URL is `http://host.openshell.internal:5561` from a sandbox,
or `http://localhost:5561` on the host.

## Step 1 — discover what's available
```
GET /scenes     -> {"scenes": ["warehouse.usd", ...]}
GET /robots     -> {"robots": ["unitree_g1", "nova_carter", ...]}   # from catalog
GET /envs       -> registered Isaac Lab tasks (if the user wants a task, not a free scene)
```
Pick the scene whose name best matches the user's words (warehouse, kitchen,
table…). Pick the robot by fuzzy-matching the user's words to a catalog key.

## Step 2 — bring up the sim on that scene
```
POST /sim/launch   {"scene": "warehouse.usd"}
```
This launches Isaac Sim headless and opens the scene. Poll `GET /status` until
`running` is true and the log (`GET /logs`) shows the stage opened.

> If the user wants an Isaac **Lab** task world instead of a free USD scene (e.g.
> "open the G1 velocity task"), skip /sim/launch and route to
> [`../training/SKILL.md`](../training/SKILL.md) — those worlds come up with the
> training/play script, not a standalone scene.

## Step 3 — spawn the robot
```
POST /robot/spawn  {"robot": "unitree_g1", "x": 6.0, "y": 0.0, "z": 0.0}
```
- `robot` must be a catalog key from `GET /robots`. If the user names a robot
  that isn't in the catalog, say so and offer the closest matches — do NOT invent
  a USD path.
- Use a sensible spawn pose: legged robots need `z` ≈ their standing height
  (the catalog `start_z` hint); place at the workstation or scene origin if the
  user didn't say where.

## Step 4 — confirm
Use [`../isaac-sim-remote/SKILL.md`](../isaac-sim-remote/SKILL.md) (`POST /exec`)
to frame the camera and capture a screenshot, then report back: scene loaded,
robot spawned at pose, and the next action the user can ask for (teleop, train).

## Example
User: *"set up the warehouse and drop a G1 at the pick station."*
1. `GET /scenes` → `warehouse.usd` matches.
2. `GET /robots` → `unitree_g1` matches "G1".
3. `POST /sim/launch {"scene":"warehouse.usd"}` → wait for running.
4. `POST /robot/spawn {"robot":"unitree_g1","x":6,"y":0,"z":0.74}`.
5. Screenshot via `/exec`; reply "Warehouse is up with a Unitree G1 at the pick
   station (6, 0, 0.74). Want me to teleoperate it or start training?"

## Guardrails
- One sim at a time — if `GET /status` shows a job running, ask before `/stop`.
- Never hardcode user-specific paths; everything resolves through the catalog and
  the scenes directory served by the control server.
