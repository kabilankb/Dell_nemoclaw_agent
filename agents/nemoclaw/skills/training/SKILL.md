---
name: "isaaclab-training"
description: "RL training on Isaac Lab from the NemoClaw sandbox: train a locomotion policy, list tasks, check status, view logs, stop training. Use for 'train a G1', 'train the g1 dance', 'list training tasks', 'how's training going', 'stop training'. Trigger keywords: train, training, start training, stop training, training status, logs, locomotion, policy, RL, G1, H1, Go2, XBot, AMP, dance, rsl_rl, cusrl, skrl."
user-invocable: true
---

# Isaac Lab Training — HTTP to the Control Server

Sandbox: no `claw`. Drive training by HTTP to `http://host.openshell.internal:5561`
using the **`exec`** tool to run `curl`.

## Start training (ONE curl)
```bash
curl -s -X POST http://host.openshell.internal:5561/train \
  -H 'Content-Type: application/json' \
  -d '{"task":"<TASK_ID>","backend":"rsl_rl","num_envs":4096}'
```

## Slots (ground them — never invent a task id)
- `<TASK_ID>`: a real id from `curl http://host.openshell.internal:5561/envs`
  (51 tasks). e.g. `RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0`.
- `backend`: `rsl_rl` (default, works for ALL tasks) · `cusrl` (most) · `skrl`
  (only special tasks). **The AMP dance MUST use** `"backend":"skrl","algorithm":"AMP"`.
- `num_envs`: default 4096. Optional: `max_iterations`, `seed`, `"gui":true` (few envs, visible).

## GPU rule
One GPU job at a time. If a sim is open, `/train` returns 409 — stop it first:
`curl -s -X POST http://host.openshell.internal:5561/stop`.

## Examples
| User says | body POSTed to /train |
|---|---|
| train a G1 | `{"task":"RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0"}` |
| train G1 on rough terrain | `{"task":"RobotLab-Isaac-Velocity-Rough-Unitree-G1-v0"}` |
| train the g1 dance | `{"task":"RobotLab-Isaac-G1-AMP-Dance-Direct-v0","backend":"skrl","algorithm":"AMP"}` |
| watch a G1 train | `{"task":"RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0","gui":true,"num_envs":64}` |

## Monitor / stop
- status: `curl -s http://host.openshell.internal:5561/status`
- logs:   `curl -s "http://host.openshell.internal:5561/logs?lines=40"`
- stop:   `curl -s -X POST http://host.openshell.internal:5561/stop`

## After it runs
Report the JSON: started job (task/backend/pid) or the error. Training is headless
and long; tell the user to watch with /status and /logs, stop with /stop.
