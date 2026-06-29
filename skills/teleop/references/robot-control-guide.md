# LeIsaac Robot Control Guide

LeIsaac is a simulation-based imitation learning platform built on NVIDIA IsaacLab. It provides teleoperation, data collection, policy training, and inference for robot manipulation tasks using SO101/LeKiwi robots.

---

## Table of Contents

1. [Installation](#1-installation)
2. [Asset Preparation](#2-asset-preparation)
3. [Supported Robots](#3-supported-robots)
4. [Supported Tasks](#4-supported-tasks)
5. [Teleoperation Devices](#5-teleoperation-devices)
6. [Running Teleoperation](#6-running-teleoperation)
7. [Keyboard Controls Reference](#7-keyboard-controls-reference)
8. [Gamepad Controls Reference](#8-gamepad-controls-reference)
9. [Recording Demonstrations](#9-recording-demonstrations)
10. [Dataset Replay](#10-dataset-replay)
11. [Data Conversion (HDF5 to LeRobot)](#11-data-conversion-hdf5-to-lerobot)
12. [Policy Training](#12-policy-training)
13. [Policy Inference](#13-policy-inference)
14. [LeRobot Recorder (Direct Recording)](#14-lerobot-recorder-direct-recording)
15. [OpenClaw Integration](#15-openclaw-integration)
16. [Troubleshooting](#16-troubleshooting)

---

## 1. Installation

### Install from Source (Recommended)

```bash
git clone https://github.com/LightwheelAI/leisaac.git --recursive
```

```bash
conda create -n leisaac python=3.11
conda activate leisaac

# CUDA toolkit
conda install -c "nvidia/label/cuda-12.8.1" cuda-toolkit

# PyTorch (CUDA 12.8)
pip install -U torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128

# IsaacSim
pip install --upgrade pip
pip install "isaacsim[all,extscache]==5.1.0" --extra-index-url https://pypi.nvidia.com

# IsaacLab
sudo apt install cmake build-essential
cd leisaac/dependencies/IsaacLab
./isaaclab.sh --install

# LeIsaac
cd ../..
pip install -e source/leisaac
```

### Optional Dependencies

```bash
# LeRobot (data conversion, dataset recorder, model inference)
pip install -e "source/leisaac[lerobot]"
pip install numpy==1.26.0

# GR00T N1.5/N1.6 policy inference
pip install -e "source/leisaac[gr00t]"

# LeRobot async inference
pip install -e "source/leisaac[lerobot-async]"

# OpenPI policy inference
pip install -e "source/leisaac[openpi]"
```

### Version Compatibility

| Dependency | IsaacSim 4.5 | IsaacSim 5.0 | IsaacSim 5.1 |
|------------|-------------|-------------|-------------|
| Python     | 3.10        | 3.11        | 3.11        |
| IsaacLab   | v2.1.1      | v2.2.1      | v2.3.0      |
| CUDA       | 11.8        | 12.8        | 12.8        |
| PyTorch    | 2.5.1       | 2.7.0       | 2.7.0       |

---

## 2. Asset Preparation

Download scene assets from the [Releases page](https://github.com/LightwheelAI/leisaac/releases) or [HuggingFace](https://huggingface.co/LightwheelAI/leisaac_env/tree/main) and extract into the `assets/` directory.

| Scene | Download |
|-------|----------|
| Kitchen with Orange | [v0.1.0](https://github.com/LightwheelAI/leisaac/releases/tag/v0.1.0) |
| Lightwheel Toyroom | [v0.1.1](https://github.com/LightwheelAI/leisaac/releases/tag/v0.1.1) |
| Table with Cube | [v0.1.2](https://github.com/LightwheelAI/leisaac/releases/tag/v0.1.2) |
| Lightwheel Bedroom | [v0.2.0](https://github.com/LightwheelAI/leisaac/releases/tag/v0.2.0) |
| Lightwheel Loft | [v0.3.0](https://github.com/LightwheelAI/leisaac/releases/tag/v0.3.0) |

Expected directory structure:
```
assets/
├── robots/
│   └── so101_follower.usd
└── scenes/
    └── kitchen_with_orange/
        ├── scene.usd
        ├── assets/
        └── objects/
            ├── Orange001
            ├── Orange002
            ├── Orange003
            └── Plate
```

---

## 3. Supported Robots

| Robot | Description |
|-------|-------------|
| Single-Arm SO101 Follower | Single-arm 6-DOF manipulator with gripper |
| Bi-Arm SO101 Follower | Dual-arm system with two SO101 Followers |
| LeKiwi | Mobile robot with omnidirectional base + single arm |

---

## 4. Supported Tasks

List all available tasks:
```bash
python scripts/environments/list_envs.py
```

| Task | Environment ID | Description | Robot |
|------|----------------|-------------|-------|
| Pick Orange | `LeIsaac-SO101-PickOrange-v0` | Pick 3 oranges, place on plate | Single-Arm |
| Pick Orange (Direct) | `LeIsaac-SO101-PickOrange-Direct-v0` | Same task, DirectRL env | Single-Arm |
| Lift Cube | `LeIsaac-SO101-LiftCube-v0` | Lift the red cube | Single-Arm |
| Lift Cube (Direct) | `LeIsaac-SO101-LiftCube-Direct-v0` | Same task, DirectRL env | Single-Arm |
| Clean Toy Table | `LeIsaac-SO101-CleanToyTable-v0` | Pick objects into box | Single-Arm |
| Clean Toy Table (Bi-Arm) | `LeIsaac-SO101-CleanToyTable-BiArm-v0` | Same task with two arms | Bi-Arm |
| Clean Toy Table (Bi-Arm Direct) | `LeIsaac-SO101-CleanToyTable-BiArm-Direct-v0` | DirectRL env | Bi-Arm |
| Fold Cloth (Bi-Arm) | `LeIsaac-SO101-FoldCloth-BiArm-v0` | Fold cloth | Bi-Arm |
| Fold Cloth (Bi-Arm Direct) | `LeIsaac-SO101-FoldCloth-BiArm-Direct-v0` | DirectRL env | Bi-Arm |
| Cleanup Trash | `LeIsaac-LeKiwi-CleanupTrash-v0` | Pick trash from floor | LeKiwi |

**Task-Device Constraints:**
- `BiArm` tasks require `--teleop_device=bi-so101leader`
- `LeKiwi` tasks require `--teleop_device=lekiwi-leader`, `lekiwi-keyboard`, or `lekiwi-gamepad`
- `Direct` tasks require `--teleop_device=so101leader` or `bi-so101leader`

---

## 5. Teleoperation Devices

| Device | Flag | Hardware Required | Robot Support |
|--------|------|-------------------|---------------|
| Keyboard | `--teleop_device=keyboard` | None | Single-Arm |
| Gamepad | `--teleop_device=gamepad` | Xbox controller | Single-Arm |
| SO101 Leader | `--teleop_device=so101leader` | Physical SO101 Leader arm | Single-Arm |
| Bi-SO101 Leader | `--teleop_device=bi-so101leader` | Two SO101 Leader arms | Bi-Arm |
| LeKiwi Leader | `--teleop_device=lekiwi-leader` | SO101 Leader + keyboard | LeKiwi |
| LeKiwi Keyboard | `--teleop_device=lekiwi-keyboard` | None | LeKiwi |
| LeKiwi Gamepad | `--teleop_device=lekiwi-gamepad` | Xbox controller | LeKiwi |
| OpenClaw | `--teleop_device=openclaw` | OpenClaw ZMQ bridge | Single-Arm |

---

## 6. Running Teleoperation

### Basic Command

```bash
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=keyboard \
    --num_envs=1 \
    --device=cuda
```

### With SO101 Leader Hardware

```bash
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=so101leader \
    --port=/dev/ttyACM0 \
    --num_envs=1 \
    --device=cuda \
    --enable_cameras
```

### With Bi-Arm Leader

```bash
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-CleanToyTable-BiArm-v0 \
    --teleop_device=bi-so101leader \
    --left_arm_port=/dev/ttyACM0 \
    --right_arm_port=/dev/ttyACM1 \
    --device=cuda \
    --enable_cameras
```

### LeKiwi Mobile Robot

```bash
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-LeKiwi-CleanupTrash-v0 \
    --teleop_device=lekiwi-keyboard \
    --device=cuda
```

### Full Parameter Reference

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--task` | None | Task environment ID |
| `--teleop_device` | `keyboard` | Control device type |
| `--port` | `/dev/ttyACM0` | Serial port (so101leader, lekiwi-leader) |
| `--left_arm_port` | `/dev/ttyACM0` | Left arm port (bi-so101leader) |
| `--right_arm_port` | `/dev/ttyACM1` | Right arm port (bi-so101leader) |
| `--num_envs` | `1` | Number of parallel environments |
| `--device` | `cpu` | Compute device (`cpu` or `cuda`) |
| `--seed` | None | Random seed |
| `--sensitivity` | `1.0` | Control sensitivity multiplier |
| `--step_hz` | `60` | Simulation stepping rate |
| `--enable_cameras` | off | Enable camera rendering |
| `--quality` | off | Enable high-quality rendering |
| `--recalibrate` | off | Force recalibration of leader arm |
| `--record` | off | Enable data recording |
| `--dataset_file` | `./datasets/dataset.hdf5` | Output dataset path |
| `--resume` | off | Resume recording to existing file |
| `--num_demos` | `0` | Stop after N demos (0 = infinite) |
| `--use_lerobot_recorder` | off | Record directly in LeRobot format |
| `--lerobot_dataset_repo_id` | None | HuggingFace repo ID for LeRobot |
| `--lerobot_dataset_fps` | `30` | LeRobot dataset FPS |
| `--openclaw_endpoint` | `tcp://0.0.0.0:5557` | ZMQ endpoint for OpenClaw |

### Operating Instructions

1. Launch the script and wait for the IsaacLab simulator window to appear
2. Press **`B`** to begin teleoperation
3. Control the robot using your selected device
4. Press **`R`** to reset (marks episode as **failed**)
5. Press **`N`** to reset (marks episode as **successful**)
6. Press **Ctrl+C** to exit cleanly

---

## 7. Keyboard Controls Reference

### Single-Arm SO101 (--teleop_device=keyboard)

Keyboard teleoperation uses target-frame-based control. Keys command the gripper link frame directly.

**Translation:**

| Key | Action |
|-----|--------|
| `W` / `S` | Forward / backward |
| `A` / `D` | Left / right |
| `Q` / `E` | Up / down |

**Rotation:**

| Key | Action |
|-----|--------|
| `J` / `L` | Yaw left / right |
| `K` / `I` | Pitch up / down |

**Gripper:**

| Key | Action |
|-----|--------|
| `U` / `O` | Open / close gripper |

**System:**

| Key | Action |
|-----|--------|
| `B` | Begin teleoperation |
| `R` | Reset environment (mark failed) |
| `N` | Reset environment (mark success) |

### LeKiwi Base (--teleop_device=lekiwi-keyboard or lekiwi-leader)

| Key | Action |
|-----|--------|
| Arrow Up / Down | Move forward / backward |
| Arrow Left / Right | Move left / right |
| `Z` / `X` | Rotate left / right |
| `1` / `2` / `3` | Speed: slow / medium / fast |

---

## 8. Gamepad Controls Reference

### Single-Arm SO101 (--teleop_device=gamepad)

| Control | Action |
|---------|--------|
| Left stick forward/back | Forward / backward |
| Left stick left/right | Left / right |
| Right stick forward/back | Up / down |
| Right stick left/right | Yaw left / right |
| LB / LT | Pitch up / down |
| RT / RB | Gripper open / close |

### LeKiwi Base (--teleop_device=lekiwi-gamepad)

| Control | Action |
|---------|--------|
| D-pad up/down | Move forward / backward |
| D-pad left/right | Move left / right |
| X / B | Rotate left / right |
| Y / A | Increase / decrease speed |

---

## 9. Recording Demonstrations

### Record to HDF5

```bash
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=so101leader \
    --port=/dev/ttyACM0 \
    --num_envs=1 \
    --device=cuda \
    --enable_cameras \
    --record \
    --dataset_file=./datasets/dataset.hdf5
```

### Resume Recording to Existing Dataset

```bash
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=so101leader \
    --port=/dev/ttyACM0 \
    --device=cuda \
    --enable_cameras \
    --record \
    --resume \
    --dataset_file=./datasets/dataset.hdf5
```

### Record with Demo Limit

```bash
# Stop automatically after 50 successful demonstrations
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=so101leader \
    --port=/dev/ttyACM0 \
    --device=cuda \
    --enable_cameras \
    --record \
    --num_demos=50 \
    --dataset_file=./datasets/dataset.hdf5
```

### Recording Workflow

1. Start the teleoperation script with `--record`
2. Press **`B`** to begin control - recording starts automatically when you move
3. Complete the task successfully
4. Press **`N`** to mark success and reset (episode saved as successful)
5. Press **`R`** to discard and reset (episode saved as failed)
6. Only successful episodes are used for policy training
7. Press **Ctrl+C** when done - data is finalized and flushed to disk

---

## 10. Dataset Replay

Replay collected demonstrations in simulation:

```bash
python scripts/environments/teleoperation/replay.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --num_envs=1 \
    --device=cuda \
    --enable_cameras \
    --replay_mode=action \
    --dataset_file=./datasets/dataset.hdf5 \
    --select_episodes 1 2
```

| Parameter | Description |
|-----------|-------------|
| `--replay_mode` | `action` (replay actions) or `state` (replay states) |
| `--task_type` | Set to `keyboard` or `gamepad` if data was collected with those devices |
| `--select_episodes` | Episode indices to replay (empty = all) |

---

## 11. Data Conversion (HDF5 to LeRobot)

### Convert to LeRobot v2 Format

```bash
pip install lerobot==0.3.3
pip install numpy==1.26.0

python scripts/convert/isaaclab2lerobot.py \
    --task_name=LeIsaac-SO101-PickOrange-v0 \
    --repo_id=your-username/your-dataset-name \
    --hdf5_root=./datasets \
    --hdf5_files=dataset.hdf5
```

### Convert to LeRobot v3 Format

```bash
pip install lerobot==0.4.2
pip install numpy==1.26.0

python scripts/convert/isaaclab2lerobotv3.py \
    --task_name=LeIsaac-SO101-PickOrange-v0 \
    --repo_id=your-username/your-dataset-name \
    --hdf5_root=./datasets \
    --hdf5_files=dataset.hdf5
```

### Conversion Parameters

| Parameter | Description |
|-----------|-------------|
| `--task_name` | Task environment ID |
| `--task_type` | Set to `keyboard`/`gamepad` if collected with those devices |
| `--repo_id` | HuggingFace repo ID (e.g., `username/dataset-name`) |
| `--fps` | Dataset FPS |
| `--hdf5_root` | Directory containing HDF5 files |
| `--hdf5_files` | Comma-separated HDF5 filenames |
| `--task_description` | Task description text |
| `--push_to_hub` | Upload dataset to HuggingFace Hub |

---

## 12. Policy Training

### GR00T N1.5 Fine-Tuning

After converting data to LeRobot format, fine-tune GR00T N1.5:

1. Follow [NVIDIA GR00T N1.5 SO101 tuning guide](https://huggingface.co/blog/nvidia/gr00t-n1-5-so101-tuning)
2. Use your collected LeRobot dataset for training
3. This produces a checkpoint for inference

### Pre-trained Examples

| Resource | Link |
|----------|------|
| Dataset (Pick Orange) | https://huggingface.co/datasets/LightwheelAI/leisaac-pick-orange |
| Policy (Pick Orange) | https://huggingface.co/LightwheelAI/leisaac-pick-orange-v0 |

---

## 13. Policy Inference

### GR00T N1.5

```bash
pip install -e "source/leisaac[gr00t]"

# Start the GR00T N1.5 inference server first (see GR00T docs)
# Then run inference:
python scripts/evaluation/policy_inference.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --eval_rounds=10 \
    --policy_type=gr00tn1.5 \
    --policy_host=localhost \
    --policy_port=5555 \
    --policy_timeout_ms=5000 \
    --policy_action_horizon=16 \
    --policy_language_instruction="Pick up the orange and place it on the plate" \
    --device=cuda \
    --enable_cameras
```

### GR00T N1.6

```bash
python scripts/evaluation/policy_inference.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --eval_rounds=10 \
    --policy_type=gr00tn1.6 \
    --policy_host=localhost \
    --policy_port=5555 \
    --policy_timeout_ms=5000 \
    --policy_action_horizon=16 \
    --policy_language_instruction="Pick up the orange and place it on the plate" \
    --device=cuda \
    --enable_cameras
```

### LeRobot Official Policy (SmolVLA)

```bash
pip install -e "source/leisaac[lerobot-async]"

python scripts/evaluation/policy_inference.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --policy_type=lerobot-smolvla \
    --policy_host=localhost \
    --policy_port=8080 \
    --policy_timeout_ms=5000 \
    --policy_language_instruction="Pick the orange to the plate" \
    --policy_checkpoint_path=outputs/smolvla/leisaac-pick-orange/checkpoints/last/pretrained_model \
    --policy_action_horizon=50 \
    --device=cuda \
    --enable_cameras
```

### OpenPI Policy

```bash
pip install -e "source/leisaac[openpi]"

python scripts/evaluation/policy_inference.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --policy_type=openpi \
    --policy_host=localhost \
    --policy_port=8000 \
    --policy_timeout_ms=5000 \
    --policy_language_instruction="Pick the orange to the plate" \
    --device=cuda \
    --enable_cameras
```

### Inference Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `--task` | - | Task environment ID |
| `--eval_rounds` | `0` | Number of evaluation rounds (0 = run until manual stop) |
| `--episode_length_s` | `60` | Episode length in seconds |
| `--policy_type` | `gr00tn1.5` | Policy type: `gr00tn1.5`, `gr00tn1.6`, `lerobot-<model>`, `openpi` |
| `--policy_host` | `localhost` | Policy server host |
| `--policy_port` | `5555` | Policy server port |
| `--policy_timeout_ms` | `5000` | Server timeout (ms) |
| `--policy_action_horizon` | `16` | Actions predicted per inference |
| `--policy_language_instruction` | - | Natural language task description |
| `--policy_checkpoint_path` | - | Path to policy checkpoint |

---

## 14. LeRobot Recorder (Direct Recording)

Skip the HDF5 conversion step by recording directly in LeRobot format:

```bash
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=so101leader \
    --port=/dev/ttyACM0 \
    --num_envs=1 \
    --device=cuda \
    --enable_cameras \
    --record \
    --use_lerobot_recorder \
    --lerobot_dataset_repo_id=your-username/your-dataset \
    --lerobot_dataset_fps=30
```

The first 5 frames of each episode are automatically skipped to avoid initial-state instability. Only successful episodes (marked with `N`) are saved.

---

## 15. OpenClaw Integration

Control the simulated robot from NemoClaw/OpenClaw via ZMQ:

```bash
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=openclaw \
    --openclaw_endpoint=tcp://0.0.0.0:5557 \
    --step_hz=60 \
    --device=cuda
```

---

## 16. Troubleshooting

### Serial Port Permission Error

```bash
# Temporary fix
sudo chmod 666 /dev/ttyACM0

# Permanent fix (requires restart)
sudo usermod -aG dialout $USER
```

### SO101 Leader Calibration

If no calibration file exists, the system prompts you automatically. Force recalibration with:
```bash
--recalibrate
```

See [calibration docs](https://huggingface.co/docs/lerobot/so101#calibration-video) for the procedure.

### Keyboard/Gamepad Datasets

When replaying or converting datasets recorded with keyboard or gamepad, always set:
```bash
--task_type=keyboard   # or --task_type=gamepad
```

---

## Quick Start: Complete Workflow

```bash
# 1. Collect demonstrations
python scripts/environments/teleoperation/teleop_se3_agent.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --teleop_device=keyboard \
    --device=cuda \
    --enable_cameras \
    --record \
    --dataset_file=./datasets/pick_orange.hdf5

# 2. Replay and verify
python scripts/environments/teleoperation/replay.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --device=cuda \
    --enable_cameras \
    --replay_mode=action \
    --dataset_file=./datasets/pick_orange.hdf5 \
    --task_type=keyboard

# 3. Convert to LeRobot format
python scripts/convert/isaaclab2lerobotv3.py \
    --task_name=LeIsaac-SO101-PickOrange-v0 \
    --task_type=keyboard \
    --repo_id=your-username/pick-orange-data \
    --hdf5_root=./datasets \
    --hdf5_files=pick_orange.hdf5

# 4. Train policy (GR00T N1.5 — see NVIDIA docs)

# 5. Run inference
python scripts/evaluation/policy_inference.py \
    --task=LeIsaac-SO101-PickOrange-v0 \
    --policy_type=gr00tn1.5 \
    --policy_host=localhost \
    --policy_port=5555 \
    --policy_action_horizon=16 \
    --policy_language_instruction="Pick up the orange and place it on the plate" \
    --device=cuda \
    --enable_cameras
```
