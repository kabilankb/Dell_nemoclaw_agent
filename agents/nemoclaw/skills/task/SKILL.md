---
name: "isaac-open-environment"
description: "Opens an Isaac Sim scene and puts a robot in it from the NemoClaw sandbox by calling the Isaac Control Server over HTTP. Use when the user asks to open or launch a simulation scene, bring up the sim, or spawn/add a robot. Trigger keywords - open the warehouse, launch the sim, open the office, open the hospital, open the grid room, load scene, spawn robot, add robot, put a robot in, open isaac scene, bring up the sim."
---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Open an Isaac Sim Scene with a Robot

## Gotchas

- The sandbox has **no `claw` CLI and no repo**. Drive Isaac ONLY by HTTP to the control server at `http://host.openshell.internal:5561`.
- Run exactly ONE `curl` with the `exec` tool, then report the JSON. Do not read skill files, do not explore the filesystem, do not retry other paths.
- Cloud scenes (`office`, `hospital`, `grid_room`, `warehouse_full`) stream from NVIDIA and take ~1–2 min to become READY; the robot spawns when the sim is ready.
- One GPU job at a time — opening a scene stops any running sim.

## Prerequisites

- The host Isaac Control Server must be reachable at `http://host.openshell.internal:5561` (allowed by the `isaaclab-training` network policy). If a call returns a connection error, tell the user the host control server is not running.

## Procedure

Use the `exec` tool to run this single command, substituting the slots:

```bash
curl -s -X POST http://host.openshell.internal:5561/open \
  -H 'Content-Type: application/json' \
  -d '{"env":"ENV","robot":"ROBOT","gui":true}'
```

Fill the slots from the user's words (never invent a name):

- `ENV` — one of `warehouse` `warehouse_full` `warehouse_shell` `office` `hospital` `grid_room`. Default `warehouse`.
- `ROBOT` (optional) — a catalog key such as `unitree_g1`, `spot`, `nova_carter`, `digit_v4`, `franka_panda`. **Omit the `"robot"` field entirely if the user named no robot.**
- `gui` — `true` opens a visible window on the host; `false` for headless.

Example — *"open the warehouse"*:

```bash
curl -s -X POST http://host.openshell.internal:5561/open -H 'Content-Type: application/json' -d '{"env":"warehouse","gui":true}'
```

The server resolves the scene, the robot's height (catalog), and its spawn position (env anchor), launches the sim, and spawns the robot when READY. It returns immediately with JSON such as `{"status":"started","pid":...,"spawn_scheduled":["spot"]}`. Report that JSON; track progress with `curl -s http://host.openshell.internal:5561/status`.

## References

- Load [references/isaac-control-server.md](references/isaac-control-server.md) for the full endpoint list (open/train/status/stop/list), all environment and robot names, presets, and examples.
