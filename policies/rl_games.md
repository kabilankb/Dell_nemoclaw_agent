---
name: rl-games-tuning
description: >-
  Tune rl_games PPO hyperparameters for Isaac Lab locomotion in isaac-claw.
  Trigger keywords: rl_games, rlgames, PPO, horizon_length, minibatch_size,
  mini_epochs, e_clip, tau, gamma, learning_rate, kl_threshold, entropy_coef,
  grad_norm, gae, num_envs, max_epochs, central_value, asymmetric critic.
user-invocable: true
---

# rl_games Tuning

## What this trains / when to pick it

rl_games is a high-throughput vectorized PPO/SAC library and an Isaac Lab
**standard backend**. Pick it when you want rl_games' runner and its
horizon-length + minibatch-size config style, or to reproduce NVIDIA Isaac Lab
baselines that ship rl_games configs. It supports an asymmetric **central
value** network (the rl_games equivalent of the privileged critic).

> The local checkout ships **rsl_rl / cusrl / skrl** under
> `scripts/reinforcement_learning/`. rl_games is the Isaac Lab standard PPO
> backend; the values below are **[framework-default]** PPO settings tuned for
> Isaac Lab locomotion and should be validated against your task before a long
> run.

## Canonical tunable block

rl_games nests PPO settings under `params.config`. Keys use rl_games' own
names; the cross-framework glossary maps them back to the universal knobs.

```yaml
# ── rl_games PPO (params.config) — [framework-default] for Isaac Lab loco ──
framework: rl_games
name: ppo                    # algorithm: a2c_continuous (PPO) | sac

# Rollout / scaling
num_actors: 4096             # 256–8192. == --num_envs. Data per iter.
horizon_length: 24           # 16–64. Steps per env per iter (~rsl_rl horizon).
minibatch_size: 24576        # = num_actors*horizon / num_mini_batches (~4 mb).
mini_epochs: 5               # 2–8. SGD passes per rollout.
max_epochs: 3000             # 500–5000. Total iterations.
seed: 42                     # any int.

# PPO core
learning_rate: 1.0e-3        # 1e-5–3e-3. Use with adaptive KL scheduler.
lr_schedule: adaptive        # adaptive | linear | constant.
kl_threshold: 0.01           # 0.005–0.02. Target KL for adaptive LR.
gamma: 0.99                  # 0.97–0.999. Discount.
tau: 0.95                    # 0.9–0.97. GAE lambda (rl_games calls it tau).
e_clip: 0.2                  # 0.1–0.3. PPO ratio clip.
entropy_coef: 0.008          # 0.0–0.02. Exploration bonus.
critic_coef: 2.0             # 1.0–4.0. Value loss weight (rl_games default 2.0).
grad_norm: 1.0               # 0.5–2.0. Gradient clipping.
truncate_grads: true         # clip grads to grad_norm.
clip_value: true             # clip the value-function loss too.
normalize_input: true        # running obs normalization.
normalize_value: true        # running value normalization.
normalize_advantage: true    # per-minibatch advantage normalization.
bounds_loss_coef: 0.0001     # 0.0–0.001. Soft action-bound penalty.

# Asymmetric critic (privileged state)
central_value: false         # true to feed privileged obs to a separate critic.

# Network
mlp_units: [512, 256, 128]   # actor/critic hidden sizes.
activation: elu              # elu | relu | tanh.
sigma_init: 1.0              # 0.5–1.5. Initial action-noise std.
```

## Symptoms → knob to change

(General PPO/rl_games guidance; the locomotion symptom→reward fixes in
[`rsl_rl.md`](rsl_rl.md) apply identically since the reward terms are the
env's, not the backend's.)

| Symptom | Change |
|---------|--------|
| Policy converges then collapses | Lower `learning_rate` or tighten `kl_threshold`; keep `lr_schedule: adaptive`. |
| Exploration dies early (sigma → 0) | Raise `entropy_coef`; raise `sigma_init`. |
| Value loss huge / unstable | Raise `critic_coef` slightly, ensure `normalize_value: true`, lower LR. |
| Updates too aggressive | Lower `e_clip` (0.2 → 0.1). |
| Slow / noisy advantages | Raise `horizon_length`; keep `normalize_advantage: true`. |
| OOM | Lower `num_actors`; raise `minibatch_size` divisor isn't the fix — reduce envs. |
| Robot falls / shuffles / jerky | Edit the **reward weights in the env config** (see [`rsl_rl.md`](rsl_rl.md) symptom table); backend knobs won't fix gait shape. |

## Launch commands

> rl_games is not shipped in this checkout's `reinforcement_learning/` folder
> (which has `rsl_rl`, `cusrl`, `skrl`). If an rl_games entry point is added it
> follows the Isaac Lab convention below; the config lives in the task's
> `agents/rl_games_ppo_cfg.yaml`.

```bash
# Isaac Lab standard path convention (add backend if absent):
python isaac_lab/scripts/reinforcement_learning/rl_games/train.py \
    --task=<RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0> \
    --num_envs=4096 --max_iterations=3000 --seed=42 --headless

# Play / evaluate a checkpoint
python isaac_lab/scripts/reinforcement_learning/rl_games/play.py \
    --task=<task_id> --num_envs=32 --checkpoint=/path/to/run.pth
```
