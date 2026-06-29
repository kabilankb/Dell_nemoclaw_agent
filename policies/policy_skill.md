---
name: policy-tuning
description: >-
  Master router for fine-tuning RL/IL policy hyperparameters across every
  supported framework in isaac-claw. Read this first, then jump to the
  per-framework file. Trigger keywords: tune, tuning, hyperparameter,
  fine-tune, learning rate, lr, reward weight, reward scale, PPO, entropy,
  entropy_coef, gamma, discount, lambda, GAE, clip, num_envs, max_iterations,
  seed, minibatch, horizon, RSL-RL, rsl_rl, CusRL, rl_games, skrl, SB3,
  stable-baselines3, robomimic, behavior cloning, BC, BC-RNN, ACT, diffusion
  policy, LeRobot, imitation learning.
user-invocable: true
---

# Policy Tuning — Master Router

This directory is the **control panel** for every tunable knob used to train
locomotion (RL) and manipulation (imitation-learning) policies in isaac-claw.
It is written to be read by both humans and local models (Gemma, Nemotron):
each per-framework file exposes ONE canonical fenced ` ```yaml ` block that a
launcher parses directly.

The seed values below were mined from the repo's own technical references
(`skills/training/references/architecture-deep-dive.md`,
`locomotion-tuning.md`) and from the actual training scripts under
`isaac_lab/scripts/`. Values that come from a framework's published defaults
(not verified against this repo) are explicitly labelled **[framework-default]**.

## Pick your framework

| Framework | File | Use when |
|-----------|------|----------|
| **RSL-RL** (+ CusRL) | [`rsl_rl.md`](rsl_rl.md) | Default for Robot Lab locomotion (XBot, G1, H1, quadrupeds). On-policy PPO, asymmetric actor-critic, KL-adaptive LR. CusRL shares the same knobs. |
| **rl_games** | [`rl_games.md`](rl_games.md) | High-throughput PPO when you want rl_games' vectorized runner / horizon+minibatch style config. Isaac Lab standard backend. |
| **skrl** | [`skrl.md`](skrl.md) | When you need PPO / **AMP** (adversarial motion priors, e.g. G1 dance) or IPPO/MAPPO. Present in this repo under `scripts/reinforcement_learning/skrl/`. |
| **SB3 (stable-baselines3)** | [`sb3.md`](sb3.md) | Quick baselines / sanity checks with PPO or SAC and the familiar SB3 API. |
| **robomimic** | [`robomimic.md`](robomimic.md) | **Imitation learning** from demos: BC, BC-RNN. Also documents the **LeRobot** ACT / diffusion knobs used by the `leisaac` mimic pipeline. |

> The locomotion backends physically present in the local checkout are
> **rsl_rl**, **cusrl**, and **skrl** (`isaac_lab/scripts/reinforcement_learning/`).
> rl_games and SB3 are documented as Isaac Lab standard backends; their config
> blocks are **[framework-default]** unless noted.

## How a model should use this

1. **Identify the framework** from the user's task (which `train.py` they run)
   using the table above, and open that file.
2. **Find the single fenced ` ```yaml ` block.** That block is the schema of
   everything you are allowed to change.
3. **Change ONLY whitelisted knobs, and stay inside the stated range.** Every
   line has an inline `#` comment giving a safe range + what the knob does. Do
   not invent new keys, do not exceed the ranges.
4. **Match the symptom.** Use the "Symptoms -> knob to change" table in the file
   to decide which knob to move and in which direction.
5. **Hand the edited yaml block to the launcher** along with the exact launch
   command listed at the bottom of the file. The launcher overrides the
   matching config fields and starts training.

Change **one or two knobs at a time**. Re-run, read `Mean reward` and
`Mean episode length`, then adjust again. Big simultaneous changes make the
cause of a regression impossible to isolate.

## Cross-framework glossary (universal knobs)

Every framework calls these something slightly different, but the meaning is
the same. Ranges are safe defaults for Isaac Lab locomotion at ~4096 envs.

| Knob (canonical) | Typical key per framework | Safe range | What it does |
|------------------|---------------------------|-----------|--------------|
| **learning_rate** | rsl_rl `learning_rate`; rl_games `learning_rate`; skrl `learning_rate`; SB3 `learning_rate` | `1e-5 – 3e-3` | Step size of the optimizer. Repo-verified: **1e-3** (Robot Lab G1/XBot, adaptive), **1e-5** (Humanoid-Gym XBot, adaptive). Too high → value-loss blows up / NaNs; too low → no progress. Most backends adapt it from KL. |
| **gamma** (discount) | `gamma` everywhere | `0.97 – 0.999` | How far ahead reward is credited. Repo-verified: **0.99** (Robot Lab), **0.994** (Humanoid-Gym). Higher = more long-horizon/stable gait but slower credit; lower = greedy. |
| **lambda / gae_lambda** | rsl_rl `lambda`; rl_games `tau`; skrl `lambda`; SB3 `gae_lambda` | `0.9 – 0.97` | GAE bias/variance trade-off. Repo-verified: **0.95** (Robot Lab), **0.9** (Humanoid-Gym). Lower = lower variance, more bias. |
| **entropy_coef** | rsl_rl `entropy_coef`; rl_games `entropy_coef`; skrl `entropy_loss_scale`; SB3 `ent_coef` | `0.0 – 0.02` | Exploration bonus. Repo-verified: **0.008** (Robot Lab G1), **0.001** (Humanoid-Gym). Raise if noise std collapses to ~0 too early; lower if policy never converges. |
| **clip** (PPO ratio clip) | `clip_param` / `e_clip` / `ratio_clip` / `clip_range` | `0.1 – 0.3` | PPO trust region. Repo-verified: **0.2** across all backends. Smaller = more conservative updates. |
| **num_envs** | CLI `--num_envs` everywhere | `256 – 8192` | Parallel rollouts = data per iteration. Repo default **4096**. On GB10 (92 GB): flat 4096–8192, rough w/ height-scan 2048–4096, cameras 256–1024. Halve on `CUDA out of memory`. |
| **max_iterations** | CLI `--max_iterations` / config | `500 – 5000` | Total training iterations. Repo-verified: **3000** rough / **1500** flat (Robot Lab), **3001** (Humanoid-Gym). |
| **seed** | CLI `--seed` / config `seed` | any int (`-1` = random) | RNG seed for reproducibility. Repo-verified default **5** (Humanoid-Gym), **42** (training skill examples). |
| **minibatch / num_mini_batches** | rsl_rl `num_mini_batches`; rl_games `minibatch_size`; SB3 `batch_size` | `2 – 8` minibatches | Splits each rollout for SGD. Repo-verified: **4** minibatches (Robot Lab + Humanoid-Gym). |
| **horizon / steps_per_env** | rsl_rl `num_steps_per_env`; rl_games `horizon_length`; SB3 `n_steps` | `16 – 64` | Rollout length per env per iteration. Repo-verified: **24** (Robot Lab G1/XBot), **60** (Humanoid-Gym). Longer horizon = better advantage estimates, more memory. |
| **num_learning_epochs** | rsl_rl `num_learning_epochs`; rl_games `mini_epochs`; SB3 `n_epochs` | `2 – 8` | SGD passes over each rollout. Repo-verified: **5** (Robot Lab), **2** (Humanoid-Gym). More epochs = more sample reuse, risk of overfitting the batch. |
| **desired_kl** | rsl_rl `desired_kl`; rl_games `kl_threshold` | `0.005 – 0.02` | Target KL for the adaptive-LR schedule. Repo-verified: **0.01**. LR is halved when KL > 2×desired, grown when KL < desired/2. |

See [`POLICY_TUNING.md`](POLICY_TUNING.md) for the directory index.
