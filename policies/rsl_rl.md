---
name: rsl-rl-tuning
description: >-
  Tune RSL-RL (and CusRL) PPO hyperparameters and locomotion reward weights for
  Robot Lab humanoid/quadruped policies in isaac-claw. Trigger keywords: rsl_rl,
  RSL-RL, cusrl, CusRL, PPO, learning rate, entropy_coef, gamma, lambda, GAE,
  clip_param, num_mini_batches, num_learning_epochs, num_steps_per_env,
  desired_kl, reward weight, reward scale, feet_air_time, action_rate,
  flat_orientation, upward, falls forward, shuffling gait, jerky gait, sim2real.
user-invocable: true
---

# RSL-RL / CusRL Tuning

## What this trains / when to pick it

RSL-RL is the **default** on-policy PPO backend for Robot Lab velocity-tracking
locomotion (RobotEra XBot, Unitree G1/H1, quadrupeds). It uses an **asymmetric
actor-critic** (actor sees deployable obs, critic sees privileged state), a
**KL-adaptive learning rate**, and ELU MLPs `[512, 256, 128]`. **CusRL** is the
repo's preferred experimental sibling and shares the *same* hyperparameter
schema (only the runner/logging differ), so this file applies to both.

Pick RSL-RL/CusRL when: training any registered
`RobotLab-Isaac-Velocity-*` env, you want zero-shot-transferable locomotion,
or you are following the repo's locomotion-tuning guidance.

## Canonical tunable block

Values below are **repo-verified** from
`skills/training/references/architecture-deep-dive.md` (Robot Lab / Unitree G1
PPO config) unless marked otherwise. The reward weights are the **XBot**
locomotion set (NemoClaw target). The launcher overrides matching fields in the
task's `agents/rsl_rl_ppo_cfg.py`.

```yaml
# ── RSL-RL / CusRL PPO (Robot Lab locomotion) ───────────────────────────
framework: rsl_rl            # or "cusrl" — identical knobs

# Rollout / scaling (mostly CLI overrides)
num_envs: 4096               # 256–8192. Parallel envs = data/iter. Halve on OOM.
max_iterations: 3000         # 500–5000. 3000 rough / 1500 flat (repo-verified).
num_steps_per_env: 24        # 16–64. Horizon per env per iter (repo: 24).
seed: 42                     # any int; -1 = random.

# PPO core
learning_rate: 1.0e-3        # 1e-5–3e-3. Adaptive (KL-based). G1/XBot=1e-3.
schedule: adaptive           # "adaptive" (KL-driven) or "fixed".
desired_kl: 0.01             # 0.005–0.02. Target KL for adaptive LR.
gamma: 0.99                  # 0.97–0.999. Discount. Higher=longer horizon.
lambda: 0.95                 # 0.9–0.97. GAE. Lower=less variance.
clip_param: 0.2              # 0.1–0.3. PPO ratio clip / trust region.
entropy_coef: 0.008          # 0.0–0.02. Exploration. Raise if std collapses.
value_loss_coef: 1.0         # 0.5–2.0. Critic loss weight.
num_learning_epochs: 5       # 2–8. SGD passes per rollout.
num_mini_batches: 4          # 2–8. Minibatch splits of the rollout.
max_grad_norm: 1.0           # 0.5–2.0. Gradient clipping.
init_noise_std: 1.0          # 0.5–1.5. Initial action-noise std (exploration).

# Network (rarely changed)
actor_hidden_dims: [512, 256, 128]   # ELU MLP
critic_hidden_dims: [512, 256, 128]
activation: elu                      # elu | relu | tanh

# ── Locomotion reward weights (XBot; see architecture-deep-dive §23.2) ──
# Tracking
reward_track_lin_vel_xy_exp: 2.0     # 1.0–4.0. Follow commanded x/y velocity.
reward_track_ang_vel_z_exp: 2.0      # 1.0–4.0. Follow commanded yaw rate.
# Stability
reward_upward: 1.0                   # 0.5–2.0. Keep base upright.
reward_flat_orientation_l2: -0.2     # -1.0–0.0. Penalize non-flat base.
reward_ang_vel_xy_l2: -0.1           # -0.5–0.0. Penalize roll/pitch rate.
# Gait / contact
reward_feet_air_time: 2.0            # 0.25–3.0. Promote real steps (XBot=2.0).
reward_feet_slide: -0.4              # -0.6–0.0. Penalize foot sliding in stance.
# Regularization
reward_action_rate_l2: -0.005        # -0.02–0.0. Temporal action smoothness.
reward_joint_acc_l2: -1.25e-7        # -1e-6–0.0. Smooth joint accelerations.
reward_joint_torques_l2: -1.0e-8     # -1e-6–0.0. Minimize torque (XBot lenient).
reward_joint_pos_limits: -1.0        # -2.0–0.0. Avoid joint limits.
reward_is_terminated: -200.0         # -300–-50. Penalty on fall/termination.
```

> All reward terms carry an **uprightness gate**
> `reward *= clamp(-projected_gravity_z, 0, 0.7)/0.7`, so rewards are ~0 while
> fallen — a reward stuck near 0 early in training is normal.

## Symptoms → knob to change

Pairs below are pulled from `skills/training/references/locomotion-tuning.md`
and the training SKILL's tuning guidance.

| Symptom | Change |
|---------|--------|
| **Robot falls forward** | Raise `reward_upward` and make `reward_flat_orientation_l2` more negative; reduce velocity command ranges; verify base-height target matches the robot. |
| **Shuffling gait (feet don't lift)** | Raise `reward_feet_air_time` (XBot baseline 2.0); raise the air-time threshold; reduce the magnitude of `reward_feet_slide` if it's over-penalizing. |
| **Jerky / twitchy gait** | Make `reward_action_rate_l2` more negative; reduce `action_scale`; make `reward_joint_acc_l2` more negative. |
| **Sim-to-real transfer fails** | Increase domain-randomization ranges; increase observation noise; verify actuator PD gains match hardware. |
| **Noise std collapses to ~0 too fast** | Raise `entropy_coef` (e.g. 0.008 → 0.015). |
| **Noise std stays pinned at 1.0 (no learning)** | Check obs/rewards are firing; lower `learning_rate` is *not* the fix — usually a reward/observation bug. |
| **Reward flat/oscillating after 200+ iters** | Re-check reward scales; lower `learning_rate` or raise `desired_kl` cautiously. |
| **Value function loss increasing** | `learning_rate` too high or distribution shift — lower LR / keep `schedule: adaptive`. |
| **Episode length stuck low (keeps falling)** | Increase stability rewards (`upward`, `flat_orientation_l2`); make `reward_is_terminated` less punishing if it dominates. |
| **NaN in obs / sim instability** | Tighten `clip_actions`; reduce PD gains (esp. ankles); reduce `sim.dt`; raise solver `num_position_iterations` 4→8. |
| **CUDA out of memory** | Halve `num_envs`; run `--headless`. |

## Launch commands

Real script paths under `isaac_lab/scripts/reinforcement_learning/`:

```bash
# RSL-RL — train XBot flat (NemoClaw target)
python isaac_lab/scripts/reinforcement_learning/rsl_rl/train.py \
    --task=RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0 \
    --num_envs=4096 --max_iterations=3000 --seed=42 --headless

# RSL-RL — train Unitree G1 rough terrain
python isaac_lab/scripts/reinforcement_learning/rsl_rl/train.py \
    --task=RobotLab-Isaac-Velocity-Rough-Unitree-G1-v0 \
    --num_envs=4096 --headless

# CusRL — same task, preferred experimental backend (identical knobs)
python isaac_lab/scripts/reinforcement_learning/cusrl/train.py \
    --task=RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0 --headless

# Evaluate / export a trained policy (RSL-RL, keyboard control)
python isaac_lab/scripts/reinforcement_learning/rsl_rl/play.py \
    --task=RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0 \
    --num_envs=1 --keyboard
```

CLI flags that override the yaml block (from `rsl_rl/train.py` + `cli_args.py`):
`--num_envs`, `--max_iterations`, `--seed`, `--run_name`, `--experiment_name`,
`--resume`, `--load_run`, `--checkpoint`, `--logger {tensorboard,wandb,neptune}`,
`--distributed`, `--video`. Per-knob PPO values (lr, gamma, entropy, …) live in
the task's `agents/rsl_rl_ppo_cfg.py` and are set via Hydra-style overrides.
