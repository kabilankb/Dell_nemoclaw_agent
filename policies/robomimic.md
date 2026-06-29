---
name: robomimic-il-tuning
description: >-
  Tune imitation-learning hyperparameters for manipulation in isaac-claw:
  robomimic BC / BC-RNN, plus the LeRobot ACT / diffusion-policy knobs used by
  the leisaac mimic pipeline. Trigger keywords: imitation learning, IL,
  robomimic, behavior cloning, BC, BC-RNN, GMM, RNN horizon, LeRobot, ACT,
  action chunking transformer, diffusion policy, GR00T, demos, dataset
  generation, annotate, action_horizon, chunk_size, kl_weight, policy_inference.
user-invocable: true
---

# Imitation Learning — robomimic & LeRobot Tuning

## What this trains / when to pick it

This is the **imitation-learning** side of isaac-claw: learning manipulation
policies from human/scripted **demonstrations** instead of reward-driven RL.
Two ecosystems are covered:

- **robomimic** — the standard offline-IL toolkit (BC, BC-RNN, BC-Transformer)
  that consumes Isaac Lab Mimic HDF5 datasets. Pick it for plain behavior
  cloning from a demo set.
- **LeRobot** — used by the **leisaac** pipeline (`scripts/leisaac/`). Provides
  **ACT** (Action-Chunking Transformer) and **diffusion** policies, served to
  Isaac Lab via `policy_inference.py` (also supports GR00T N1.5/1.6, openpi).

Workflow: **record demos → annotate subtasks → generate dataset → train policy
→ evaluate via policy server**. Annotation/generation knobs are env/datagen
settings; policy knobs are below.

## Canonical tunable block

robomimic values are **[framework-default]** (robomimic published BC/BC-RNN
configs). LeRobot ACT/diffusion values are **[framework-default]** from LeRobot;
the `action_horizon` default **16** is **repo-verified** from
`policy_inference.py` (`--policy_action_horizon=16`).

```yaml
# ── Imitation Learning hyperparameters ───────────────────────────────────
framework: robomimic         # robomimic | lerobot

# ---- Dataset generation (Isaac Lab Mimic / leisaac) ----
generation_num_trials: 1000  # 100–10000. Demos to synthesize from source set.
datagen_seed: 1              # any int. Seed for data generation.
num_envs: 1                  # 1–64. Parallel envs for generation/annotation.

# ---- robomimic BC (algo: bc) — [framework-default] ----
algo: bc                     # bc | bc_rnn | bc_transformer.
learning_rate: 1.0e-4        # 1e-5–1e-3. Adam LR (robomimic default 1e-4).
batch_size: 100              # 16–512. SGD batch (robomimic default 100).
num_epochs: 2000             # 200–4000. Training epochs over the dataset.
mlp_dims: [1024, 1024]       # actor MLP (robomimic default).
gmm_enabled: true            # GMM action head (robomimic default true).
gmm_num_modes: 5             # 1–10. Mixture modes (default 5).
gmm_min_std: 0.0001          # 1e-4–1e-2. Floor on action std.
l2_weight_decay: 0.0         # 0.0–1e-4. Regularization.

# ---- robomimic BC-RNN extras (algo: bc_rnn) — [framework-default] ----
rnn_enabled: false           # true for BC-RNN (temporal context).
rnn_hidden_dim: 1000         # 400–1200. LSTM hidden size (default 1000).
rnn_horizon: 10              # 5–50. Sequence length fed to the RNN (default 10).
rnn_num_layers: 2            # 1–3.

# ---- LeRobot ACT (policy_type: lerobot-act) — [framework-default] ----
act_chunk_size: 16           # 8–100. Action chunk the model predicts at once.
act_n_action_steps: 16       # ≤ chunk_size. Steps executed before re-query.
act_kl_weight: 10.0          # 1.0–100.0. VAE latent KL weight (ACT default 10).
act_dim_model: 512           # transformer width (ACT default 512).
act_n_heads: 8               # attention heads (default 8).
act_learning_rate: 1.0e-5    # 1e-6–1e-4. ACT default 1e-5.
act_batch_size: 8            # 4–64.

# ---- LeRobot Diffusion Policy (policy_type: lerobot-diffusion) ----
diff_horizon: 16             # 8–32. Prediction horizon.
diff_n_action_steps: 8       # ≤ horizon. Steps executed per inference.
diff_n_obs_steps: 2          # 1–4. Observation history length.
diff_num_train_timesteps: 100  # 50–1000. Diffusion denoising steps (train).
diff_learning_rate: 1.0e-4   # 1e-5–1e-3. Diffusion default 1e-4.

# ---- Inference / serving (policy_inference.py) — repo-verified ----
policy_action_horizon: 16    # 1–64. Actions consumed per server query (default 16).
step_hz: 60                  # 20–120. Env stepping rate during eval (default 60).
episode_length_s: 60.0       # eval episode length (default 60s).
```

## Symptoms → knob to change

| Symptom | Change |
|---------|--------|
| Policy memorizes demos, fails on new states (overfit) | Add `l2_weight_decay`; collect more demos (`generation_num_trials`); reduce `num_epochs`. |
| Jerky / non-smooth actions | Use BC-RNN or ACT (temporal context); raise `rnn_horizon` / `act_chunk_size`. |
| Multi-modal demos averaged into one bad action | Enable `gmm_enabled` / raise `gmm_num_modes`; or switch to **diffusion** (handles multimodality natively). |
| ACT ignores demo variation / collapses | Lower `act_kl_weight` (latent under-used) — or raise it if actions are too noisy. |
| ACT/diffusion stutters at chunk boundaries | Lower `n_action_steps` so it re-queries more often. |
| Task too long-horizon for BC | Use BC-RNN with larger `rnn_horizon`, or ACT/diffusion with larger horizon. |
| Eval slower/faster than real robot | Adjust `step_hz`; keep `policy_action_horizon` consistent with training chunk. |
| Too few successful demos generated | Raise `generation_num_trials`; check annotation subtasks. |

## Launch commands

Real script paths under `isaac_lab/scripts/leisaac/`:

```bash
# 1. Annotate subtasks in a recorded demo set
python isaac_lab/scripts/leisaac/mimic/annotate_demos.py \
    --task=<task_id> \
    --input_file=./datasets/dataset.hdf5 \
    --output_file=./datasets/dataset_annotated.hdf5 --auto

# 2. Generate a larger dataset from the annotated demos
python isaac_lab/scripts/leisaac/mimic/generate_dataset.py \
    --task=<task_id> \
    --input_file=./datasets/dataset_annotated.hdf5 \
    --output_file=./datasets/output_dataset.hdf5 \
    --generation_num_trials=1000 --num_envs=1

# 3a. Train BC / BC-RNN with robomimic (standard robomimic entry point)
python -m robomimic.scripts.train --config bc.json \
    --dataset ./datasets/output_dataset.hdf5

# 3b. Train an ACT / diffusion policy with LeRobot (lerobot training CLI)
python -m lerobot.scripts.train policy=act \
    dataset.repo_id=<local_dataset> training.offline_steps=100000

# 4. Evaluate in sim via the policy server (LeRobot / GR00T / openpi)
python isaac_lab/scripts/leisaac/evaluation/policy_inference.py \
    --task=<task_id> \
    --policy_type=lerobot-act \
    --policy_host=localhost --policy_port=5555 \
    --policy_action_horizon=16 --step_hz=60
```

CLI flags (verified): `generate_dataset.py` →
`--task, --input_file (required), --output_file, --generation_num_trials,
--num_envs, --task_type, --pause_subtask, --enable_pinocchio`.
`annotate_demos.py` → `--task, --input_file, --output_file, --auto`.
`policy_inference.py` → `--task, --policy_type {gr00tn1.5, gr00tn1.6,
lerobot-<type>, openpi}, --policy_host, --policy_port, --policy_action_horizon,
--step_hz, --episode_length_s, --eval_rounds, --policy_checkpoint_path`.

> robomimic `train.py` and the LeRobot `train` CLI are the upstream entry points
> (not vendored in this checkout's `scripts/leisaac/`, which covers
> record → annotate → generate → infer). Their hyperparameter blocks above are
> **[framework-default]**.
