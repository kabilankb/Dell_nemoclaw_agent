---
name: "isaac-mimicgen"
description: "Imitation-learning data pipeline for Isaac Lab: record teleop demonstrations, annotate them, generate larger datasets from a few demos (Isaac Lab Mimic), and convert between HDF5 and LeRobot formats. Use when the user asks to record demos, collect demonstrations, annotate, generate a dataset, mimicgen, or prepare data for behavior cloning / ACT / diffusion policies. Trigger keywords: record demo, demonstration, collect data, annotate, mimic, mimicgen, generate dataset, augment demos, hdf5, lerobot, behavior cloning, bc, act, diffusion policy, dataset."
user-invocable: true
---

# MimicGen — Imitation-Learning Data Pipeline

Takes a handful of teleoperated demonstrations and turns them into a training
dataset. Scripts live under `isaac_lab/scripts/leisaac/` (copied from leisaac);
tuning of the resulting policies routes to
[`../../policies/robomimic.md`](../../policies/robomimic.md).

## The pipeline (record → annotate → generate → convert → train)

### 1. Record demonstrations (teleop)
Use the teleop skill with recording on — see [`../teleop/SKILL.md`](../teleop/SKILL.md).
```
isaac_lab/scripts/leisaac/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 --teleop_device=so101leader \
    --record --dataset_file=datasets/pickorange.hdf5
```
Records to HDF5 (or LeRobot format with `--lerobot`).

### 2. Annotate demonstrations
Label sub-tasks / language in the recorded demos:
```
isaac_lab/scripts/leisaac/mimic/annotate_demos.py --dataset_file=datasets/pickorange.hdf5
```

### 3. Generate a larger dataset (Isaac Lab Mimic)
Synthesize many trajectories from the annotated seed demos:
```
isaac_lab/scripts/leisaac/mimic/generate_dataset.py \
    --input_file=datasets/pickorange_annotated.hdf5 \
    --output_file=datasets/pickorange_gen.hdf5 --num_trials=1000
```

### 4. Convert format (HDF5 ↔ LeRobot)
```
isaac_lab/scripts/leisaac/convert/isaaclab2lerobot.py   # HDF5 -> LeRobot
isaac_lab/scripts/leisaac/convert/lerobot2isaaclab.py   # LeRobot -> HDF5
```

### 5. Train the policy
Behavior cloning / ACT / diffusion via LeRobot or robomimic. Set hyperparameters
from [`../../policies/robomimic.md`](../../policies/robomimic.md), then run the
LeRobot trainer or `policy_inference.py` to evaluate
(`isaac_lab/scripts/leisaac/evaluation/policy_inference.py`).

## Choosing a policy class
| Want | Use |
|---|---|
| Fast baseline from many demos | Behavior Cloning (BC / BC-RNN) — robomimic |
| Smooth multi-step manipulation | ACT (Action Chunking Transformer) — LeRobot |
| Multimodal / contact-rich | Diffusion Policy — LeRobot |

## Notes
- Datasets are large; keep them OUT of git (the repo `.gitignore` excludes
  `datasets/` and `*.hdf5`). Reference an external dataset dir via
  `--dataset_file` absolute paths.
- The hand-off into RL fine-tuning (if any) routes through
  [`../training/SKILL.md`](../training/SKILL.md).
