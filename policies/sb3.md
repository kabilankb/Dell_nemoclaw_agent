---
name: sb3-tuning
description: >-
  Tune Stable-Baselines3 (SB3) PPO / SAC hyperparameters for Isaac Lab quick
  baselines in isaac-claw. Trigger keywords: sb3, stable-baselines3,
  stable_baselines3, PPO, SAC, n_steps, batch_size, n_epochs, gae_lambda,
  gamma, clip_range, ent_coef, vf_coef, learning_rate, max_grad_norm,
  target_kl, baseline, sanity check.
user-invocable: true
---

# Stable-Baselines3 (SB3) Tuning

## What this trains / when to pick it

SB3 is a well-documented, batteries-included RL library and an Isaac Lab
**standard backend**. Pick it for **quick baselines and sanity checks** with the
familiar SB3 API (PPO for on-policy locomotion, SAC for off-policy) — not for
maximum throughput. SB3 has **no built-in KL-adaptive LR** (use a fixed or
linearly-decaying LR, optionally with a soft `target_kl` early-stop).

> The local checkout ships **rsl_rl / cusrl / skrl**. SB3 is the Isaac Lab
> standard SB3 backend; values below are **SB3's published PPO defaults**
> **[framework-default]**, lightly adapted to Isaac Lab's many-env regime. They
> are starting points, not repo-tuned values.

## Canonical tunable block

```yaml
# ── SB3 PPO — [framework-default] (SB3 docs), Isaac-Lab-adapted ──────────
framework: sb3
algorithm: PPO               # PPO (on-policy) | SAC (off-policy).

# Rollout / scaling
n_envs: 4096                 # 256–8192. CLI --num_envs (vectorized envs).
n_steps: 24                  # 16–64. Steps per env per update (~horizon).
batch_size: 24576            # = n_envs*n_steps / num_minibatches (~4).
n_epochs: 5                  # 2–8. SGD passes per rollout (SB3 default 10).
total_timesteps: 300000000   # n_envs * n_steps * max_iterations.
seed: 42                     # any int.

# PPO core (SB3 defaults shown; tuned column in comments)
learning_rate: 3.0e-4        # 1e-5–1e-3. SB3 default 3e-4 (no KL-adaptive LR).
gamma: 0.99                  # 0.97–0.999. Discount (SB3 default 0.99).
gae_lambda: 0.95             # 0.9–0.97. GAE (SB3 default 0.95).
clip_range: 0.2              # 0.1–0.3. PPO ratio clip (SB3 default 0.2).
clip_range_vf: null          # null or 0.1–0.3. Value clip (off by default).
ent_coef: 0.008              # 0.0–0.02. Exploration (SB3 default 0.0 — raise!).
vf_coef: 0.5                 # 0.5–1.0. Value loss weight (SB3 default 0.5).
max_grad_norm: 1.0           # 0.5–2.0. Gradient clipping (SB3 default 0.5).
target_kl: 0.02              # null or 0.005–0.03. Soft early-stop on KL.
normalize_advantage: true    # SB3 default true.

# Network
net_arch: [512, 256, 128]    # actor/critic MLP (SB3 default [64, 64]).
activation_fn: elu           # elu | relu | tanh (SB3 default tanh).
log_std_init: 0.0            # log of initial action-noise std (~std 1.0).
```

For **SAC** instead of PPO, the relevant knobs are `buffer_size`, `tau`
(target smoothing, ~0.005), `train_freq`, `gradient_steps`, `learning_starts`,
and `ent_coef: auto` (automatic temperature) — all **[framework-default]**.

## Symptoms → knob to change

| Symptom | Change |
|---------|--------|
| No exploration / premature convergence | Raise `ent_coef` (SB3 default 0.0 is too low for locomotion). |
| Training diverges / value loss explodes | Lower `learning_rate`; set `clip_range_vf: 0.2`; lower `max_grad_norm`. |
| Updates too aggressive (KL spikes) | Lower `clip_range`; set `target_kl` to early-stop epochs. |
| Underfitting / slow | Raise `n_epochs` or `n_steps`; widen `net_arch`. |
| Robot falls / shuffles / jerky | Fix the **env reward weights** (see [`rsl_rl.md`](rsl_rl.md)). |
| OOM | Lower `n_envs`. |

## Launch commands

> SB3 is not present in this checkout's `reinforcement_learning/` folder
> (`rsl_rl`, `cusrl`, `skrl`). If an SB3 entry point is added it follows the
> Isaac Lab convention below; config lives in `agents/sb3_ppo_cfg.yaml`.

```bash
# Isaac Lab standard path convention (add backend if absent):
python isaac_lab/scripts/reinforcement_learning/sb3/train.py \
    --task=<RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0> \
    --num_envs=4096 --seed=42 --headless

# Play / evaluate a checkpoint
python isaac_lab/scripts/reinforcement_learning/sb3/play.py \
    --task=<task_id> --num_envs=32 --checkpoint=/path/to/model.zip
```
