---
name: skrl-tuning
description: >-
  Tune skrl PPO / AMP / IPPO / MAPPO hyperparameters for Isaac Lab in
  isaac-claw. Trigger keywords: skrl, PPO, AMP, adversarial motion priors, IPPO,
  MAPPO, rollouts, learning_epochs, mini_batches, ratio_clip, discount_factor,
  lambda, entropy_loss_scale, value_loss_scale, kl_threshold, learning_rate,
  grad_norm_clip, G1 dance, motion imitation.
user-invocable: true
---

# skrl Tuning

## What this trains / when to pick it

skrl is a modular RL library present in this repo under
`scripts/reinforcement_learning/skrl/`. The `train.py` here exposes
`--algorithm {AMP, PPO, IPPO, MAPPO}` (default PPO). Pick skrl when you need:

- **AMP** (Adversarial Motion Priors) — style/motion imitation such as the
  Unitree **G1 AMP dance** direct task. This is skrl's distinctive capability.
- **PPO** with skrl's config schema, or multi-agent **IPPO / MAPPO**.
- **JAX** as well as Torch (`--ml_framework {torch, jax, jax-numpy}`).

skrl config is a nested dict (`agent`, `trainer`, `models`, `seed`). Note the
launcher maps `--max_iterations` to `trainer.timesteps = max_iterations *
agent.rollouts` (verified in `skrl/train.py`).

## Canonical tunable block

PPO values below are **[framework-default]** skrl PPO settings aligned to Isaac
Lab locomotion; AMP-specific knobs are flagged.

```yaml
# ── skrl PPO (agent block) — [framework-default], Isaac-Lab-aligned ──────
framework: skrl
algorithm: PPO               # PPO | AMP | IPPO | MAPPO (CLI --algorithm)
ml_framework: torch          # torch | jax | jax-numpy
seed: 42                     # any int; -1 = random.

# Rollout / scaling
num_envs: 4096               # 256–8192. CLI --num_envs.
rollouts: 24                 # 16–64. Steps per env per update (~horizon).
learning_epochs: 5           # 2–8. SGD passes per rollout.
mini_batches: 4              # 2–8. Minibatch splits.
# trainer.timesteps = max_iterations * rollouts (set via --max_iterations)

# PPO core
learning_rate: 1.0e-3        # 1e-5–3e-3.
learning_rate_scheduler: KLAdaptiveLR   # KL-adaptive schedule.
kl_threshold: 0.01           # 0.005–0.02. Target KL (scheduler).
discount_factor: 0.99        # 0.97–0.999. == gamma.
lambda: 0.95                 # 0.9–0.97. GAE.
ratio_clip: 0.2              # 0.1–0.3. PPO ratio clip.
value_clip: 0.2              # 0.1–0.3. Value-function clip.
clip_predicted_values: true
entropy_loss_scale: 0.008    # 0.0–0.02. == entropy_coef.
value_loss_scale: 1.0        # 0.5–2.0.
grad_norm_clip: 1.0          # 0.5–2.0. Gradient clipping.
state_preprocessor: RunningStandardScaler   # obs normalization.
value_preprocessor: RunningStandardScaler   # value normalization.

# Network
hidden_sizes: [512, 256, 128]   # actor/critic MLP.
activation: elu                 # elu | relu | tanh.

# ── AMP-only (algorithm: AMP) ────────────────────────────────────────────
amp_batch_size: 512              # 256–1024. AMP replay minibatch.
discriminator_loss_scale: 5.0    # 1.0–10.0. Style-discriminator weight.
task_reward_weight: 0.0          # 0.0–1.0. Goal reward vs. style reward mix.
style_reward_weight: 1.0         # 0.0–1.0. Motion-imitation reward weight.
discriminator_reward_scale: 2.0  # 1.0–5.0. Scales discriminator output reward.
```

## Symptoms → knob to change

| Symptom | Change |
|---------|--------|
| PPO converges then collapses | Lower `learning_rate`; tighten `kl_threshold`. |
| Exploration dies early | Raise `entropy_loss_scale`. |
| Updates too aggressive | Lower `ratio_clip`. |
| **AMP**: motion looks robotic / off-style | Raise `style_reward_weight` / `discriminator_reward_scale`; lower `task_reward_weight`. |
| **AMP**: ignores the goal/command | Raise `task_reward_weight` toward 0.3–0.5. |
| **AMP**: discriminator overpowers policy | Lower `discriminator_loss_scale`. |
| Robot falls / shuffles / jerky | Fix **env reward weights** (see [`rsl_rl.md`](rsl_rl.md)); backend knobs won't reshape gait. |
| OOM | Lower `num_envs`. |

## Launch commands

Real script path: `isaac_lab/scripts/reinforcement_learning/skrl/`.

```bash
# skrl PPO — locomotion
python isaac_lab/scripts/reinforcement_learning/skrl/train.py \
    --task=RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0 \
    --algorithm=PPO --num_envs=4096 --max_iterations=3000 --seed=42 --headless

# skrl AMP — Unitree G1 dance (direct task)
python isaac_lab/scripts/reinforcement_learning/skrl/train.py \
    --task=RobotLab-Isaac-G1-AMP-Dance-Direct-v0 \
    --algorithm=AMP --num_envs=4096 --headless

# JAX backend variant
python isaac_lab/scripts/reinforcement_learning/skrl/train.py \
    --task=<task_id> --algorithm=PPO --ml_framework=jax --headless

# Play / evaluate
python isaac_lab/scripts/reinforcement_learning/skrl/play.py \
    --task=<task_id> --num_envs=32 --checkpoint=/path/to/agent.pt
```

CLI flags (from `skrl/train.py`): `--task`, `--algorithm {AMP,PPO,IPPO,MAPPO}`,
`--ml_framework {torch,jax,jax-numpy}`, `--num_envs`, `--max_iterations`,
`--seed`, `--checkpoint`, `--distributed`, `--video`, `--agent` (override the
agent cfg entry point).
