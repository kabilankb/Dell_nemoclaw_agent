---
name: "isaaclab-training"
description: "Train humanoid and quadruped locomotion policies on Isaac Lab. Use when the user asks to train a robot, list environments, check training status, stop training, or view training logs. Trigger keywords: train, training, list envs, environments, start training, stop training, training status, logs, XBot, G1, humanoid, quadruped, locomotion, CusRL, RSL-RL."
user-invocable: true
---

# Isaac Lab Training Control

You control RL training on the host machine via the `isaaclab-train` client. All interaction happens through the `exec` tool.

IMPORTANT: Use the `exec` tool to run all commands below. Do NOT use Read, Write, or any file tools.

## Commands

### List available environments
```bash
/sandbox/bin/isaaclab-train envs
/sandbox/bin/isaaclab-train envs humanoid    # filter by category
/sandbox/bin/isaaclab-train envs quadruped
/sandbox/bin/isaaclab-train envs wheeled
```

### Start training
```bash
/sandbox/bin/isaaclab-train start <TASK_ID> --num_envs <N> --backend <cusrl|rsl_rl>
```

Examples:
```bash
# Train XBot on flat terrain with 4096 envs (default backend: cusrl)
/sandbox/bin/isaaclab-train start RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0 --num_envs 4096

# Train Unitree G1 on rough terrain with RSL-RL
/sandbox/bin/isaaclab-train start RobotLab-Isaac-Velocity-Rough-Unitree-G1-v0 --num_envs 4096 --backend rsl_rl

# Train with custom iterations and seed
/sandbox/bin/isaaclab-train start RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0 --num_envs 2048 --max_iterations 1500 --seed 42
```

### Check training status
```bash
/sandbox/bin/isaaclab-train status
```

### View training logs
```bash
/sandbox/bin/isaaclab-train logs
/sandbox/bin/isaaclab-train logs --lines 50
```

### Stop training
```bash
/sandbox/bin/isaaclab-train stop
```

## Quick Reference: Task Name Mapping

When the user says a robot name, map it to the correct task ID:

| User says | Task ID |
|-----------|---------|
| XBot, XBot flat | `RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0` |
| XBot rough | `RobotLab-Isaac-Velocity-Rough-RobotEra-Xbot-v0` |
| G1, Unitree G1 | `RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0` |
| G1 rough | `RobotLab-Isaac-Velocity-Rough-Unitree-G1-v0` |
| H1, Unitree H1 | `RobotLab-Isaac-Velocity-Flat-Unitree-H1-v0` |
| Go2 | `RobotLab-Isaac-Velocity-Flat-Unitree-Go2-v0` |
| GR1T1, GR1T2 | `RobotLab-Isaac-Velocity-Flat-FFTAI-GR1T1-v0` / `GR1T2` |

Default parameters if user doesn't specify:
- `--num_envs 4096`
- `--backend cusrl`
- Terrain: flat (unless user says "rough" or "rough terrain")

## Behavior Guidelines

1. When user asks to "list environments" — run `envs` command and present results
2. When user asks to "train X robot" — map the name, confirm the task ID and num_envs, then run `start`
3. When user asks "how's training going" or "status" — run `status` and `logs`
4. When user asks to "stop" — run `stop` and confirm
5. Only one training run at a time (single GPU). If training is already running, tell the user and ask if they want to stop it first.
6. Always confirm the task name and parameters before starting training.
