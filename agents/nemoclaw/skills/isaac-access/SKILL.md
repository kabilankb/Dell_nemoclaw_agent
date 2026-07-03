---
name: "isaac-access"
description: "Access the Isaac Control Server from the NemoClaw sandbox to list robots, environments, scenes, and trainable tasks, and to open a scene / spawn a robot. Answer ONLY from the server's real JSON — never invent names. Trigger keywords: list robots, available robots, what robots, list environments, what can I open, what scenes, how many tasks, what can I train, inventory, catalog, open the warehouse, launch the sim, spawn robot, status."
user-invocable: true
---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Access Isaac from the sandbox (HTTP to the Control Server)

You are in a locked-down sandbox: **no `claw` CLI, no repo, no `localhost` sim**.
The Isaac Control Server runs on the **host** and is reachable ONLY at:

```
http://host.openshell.internal:5561
```

⚠️ **Never use `localhost` or `127.0.0.1`** — inside the sandbox those point at the
sandbox itself and the call fails with a connection error. Always use the
`host.openshell.internal` hostname above.

## How to call it — ONE `curl` via the `exec` tool

Use the **`exec`** tool to run exactly one `curl`, then report the JSON it prints.
Do not read files, do not explore, do not retry other hosts.

| The user asks… | Run this one command |
|---|---|
| list / what robots can I spawn | `curl -s http://host.openshell.internal:5561/robots` |
| list environments / what can I open | `curl -s http://host.openshell.internal:5561/templates` |
| what scenes are built | `curl -s http://host.openshell.internal:5561/scenes` |
| what / how many tasks can I train | `curl -s http://host.openshell.internal:5561/envs` |
| is the sim running / status | `curl -s http://host.openshell.internal:5561/status` |

### Open a scene + robot
```bash
curl -s -X POST http://host.openshell.internal:5561/open \
  -H 'Content-Type: application/json' \
  -d '{"env":"ENV","robot":"ROBOT","gui":true}'
```
- `ENV` — one of `warehouse` `warehouse_full` `warehouse_shell` `office` `hospital`
  `grid_room` (default `warehouse`).
- `ROBOT` — a catalog key such as `unitree_g1`, `spot`, `nova_carter`, `digit_v4`,
  `franka_panda`. **Omit the whole `"robot"` field if the user named no robot.**
- Cloud scenes (`office`, `hospital`, `grid_room`, `warehouse_full`) stream from
  NVIDIA and take ~1–2 min to become READY; the robot spawns when the sim is ready.
- One GPU job at a time — opening a scene stops any running sim.

## Rules
1. Every name you report MUST come from the curl output. If it's not there, it does
   NOT exist — never invent (no `jetbot`, no made-up scenes).
2. **Spawnable robots** (`/robots`) are DIFFERENT from **trainable robots** (the
   robot names inside `/envs` task ids). Never merge or sum them into one count.
3. For "how many", count the array in the JSON and state the number honestly.
4. If a call returns a connection error, the host Control Server is not running —
   say so plainly; do not fall back to `localhost` or guess.

## After it runs
Summarize the JSON grouped sensibly (humanoids / quadrupeds / arms for robots;
environments for `/templates`) with honest counts, then offer the next step, e.g.
"want me to open one — say 'open the warehouse with a G1'?"
