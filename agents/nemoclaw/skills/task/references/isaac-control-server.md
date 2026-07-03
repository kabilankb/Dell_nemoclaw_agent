<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Isaac Control Server — HTTP reference (from the NemoClaw sandbox)

Base URL: `http://host.openshell.internal:5561` (allowed by the `isaaclab-training` policy).
Drive everything with the `exec` tool running `curl`. The server runs on the host and
owns the GPU; the sandbox only sends HTTP.

## Endpoints

| Method / path | Body | Does |
|---|---|---|
| `POST /open` | `{env, robot?, anchor?, gui?}` or `{template, gui?}` or `{scene, robot?, x?,y?,z?}` | launch scene + spawn robot(s) when READY |
| `GET /robots` | — | spawnable robot keys (catalog) |
| `GET /templates` | — | openable environments + composite templates |
| `GET /scenes` | — | built scene USDs on disk |
| `GET /envs` | — | RL training task ids |
| `GET /status` | — | current GPU job (sim or train) + elapsed |
| `GET /logs?lines=N` | — | tail the active job log |
| `POST /train` | `{task, backend?, num_envs?, algorithm?, gui?}` | start RL training |
| `POST /stop` | — | stop the active GPU job, free the GPU |

## Environments (`env` for /open)

`warehouse` (local, default) · `warehouse_local` · `warehouse_full` · `warehouse_shell` ·
`office` · `hospital` · `grid_room`. The last five stream from NVIDIA's cloud (slower first open).
Confirm the live list with `GET /templates`.

## Robots (`robot` for /open)

Humanoids: `unitree_g1` `unitree_h1` `digit_v4` `cassie` `fourier_gr1t2` `agibot_a2d` `galbot_one_charlie` …
Quadruped/legged: `spot` `anymal` · Mobile: `nova_carter` · Arms: `franka_panda` `ur10` `ur5e` `kinova_gen3` …
Confirm the live list with `GET /robots`. Never invent a key.

## Presets (`template` for /open)

`warehouse_g1` (G1) · `warehouse_fleet` (unitree_g1 + nova_carter + spot).

## Examples

```bash
# open the warehouse (headless-less GUI window on host)
curl -s -X POST http://host.openshell.internal:5561/open -H 'Content-Type: application/json' -d '{"env":"warehouse","gui":true}'
# spot on the grid room
curl -s -X POST http://host.openshell.internal:5561/open -H 'Content-Type: application/json' -d '{"env":"grid_room","robot":"spot","gui":true}'
# the fleet preset
curl -s -X POST http://host.openshell.internal:5561/open -H 'Content-Type: application/json' -d '{"template":"warehouse_fleet","gui":true}'
# train a G1
curl -s -X POST http://host.openshell.internal:5561/train -H 'Content-Type: application/json' -d '{"task":"RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0","backend":"rsl_rl"}'
# the G1 AMP dance (needs skrl + algorithm AMP)
curl -s -X POST http://host.openshell.internal:5561/train -H 'Content-Type: application/json' -d '{"task":"RobotLab-Isaac-G1-AMP-Dance-Direct-v0","backend":"skrl","algorithm":"AMP"}'
# status / stop
curl -s http://host.openshell.internal:5561/status
curl -s -X POST http://host.openshell.internal:5561/stop
```

## Gotchas

- One GPU job at a time: `/open` while training is up returns 409 (and vice-versa). Use `/stop` first.
- Cloud scenes take ~1–2 min to be READY; the robot spawns then. Poll `/status`.
- If a call returns a connection error (not JSON), the host control server isn't running — say so; it can't be started from the sandbox.
