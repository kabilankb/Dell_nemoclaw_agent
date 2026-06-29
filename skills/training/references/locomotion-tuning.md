---
name: nemoclaw-humanoid
description: Train, evaluate, and deploy humanoid locomotion policies using Robot Lab (Isaac Lab + IsaacSim 5.1). Covers RL training with CusRL/RSL-RL, 50 environments across 20+ robots, debugging, and reward tuning.
user-invocable: true
---

# NemoClaw Humanoid Agent

Use this skill when the user wants to train, evaluate, tune, deploy, or debug humanoid locomotion policies. Training runs on Isaac Lab (IsaacSim 5.1) via the Robot Lab extension.

## Project Layout

```
humanoid_nemoclaw/
├── robot_lab/                             # Isaac Lab extension (50 envs, 20+ robots)
│   ├── scripts/reinforcement_learning/
│   │   ├── cusrl/train.py, play.py        # CusRL backend (preferred)
│   │   └── rsl_rl/train.py, play.py       # RSL-RL backend (alternative)
│   ├── scripts/tools/
│   │   ├── training_server.py             # Host HTTP server for agent control
│   │   └── list_envs.py                   # Env discovery
│   └── source/robot_lab/robot_lab/
│       ├── assets/                        # Robot definitions (URDF/USD + actuators)
│       └── tasks/                         # Env configs, rewards, observations
├── nemoclaw-skill/SKILL.md                # This skill (reference + tuning)
├── nemoclaw-skill-training/               # Training controller skill
│   ├── SKILL.md                           # Agent instructions for exec commands
│   └── isaaclab-train                     # Sandbox client script
└── skilled.md                             # Full technical reference document
```

## Available Environments

When the user asks to "list envs", "show environments", "what robots can I train", or similar, display this registry. All environments support both CusRL and RSL-RL backends.

To discover environments live, run: `python scripts/tools/list_envs.py` from `robot_lab/`

### Humanoid (10 robots, 20 envs)

| # | Task Name | Robot |
|---|-----------|-------|
| 1 | `RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0` | RobotEra XBot (NemoClaw target) |
| 2 | `RobotLab-Isaac-Velocity-Rough-RobotEra-Xbot-v0` | RobotEra XBot |
| 3 | `RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0` | Unitree G1 (29 DOF) |
| 4 | `RobotLab-Isaac-Velocity-Rough-Unitree-G1-v0` | Unitree G1 |
| 5 | `RobotLab-Isaac-Velocity-Flat-Unitree-H1-v0` | Unitree H1 |
| 6 | `RobotLab-Isaac-Velocity-Rough-Unitree-H1-v0` | Unitree H1 |
| 7 | `RobotLab-Isaac-Velocity-Flat-FFTAI-GR1T1-v0` | FFTAI GR1T1 |
| 8 | `RobotLab-Isaac-Velocity-Rough-FFTAI-GR1T1-v0` | FFTAI GR1T1 |
| 9 | `RobotLab-Isaac-Velocity-Flat-FFTAI-GR1T2-v0` | FFTAI GR1T2 |
| 10 | `RobotLab-Isaac-Velocity-Rough-FFTAI-GR1T2-v0` | FFTAI GR1T2 |
| 11 | `RobotLab-Isaac-Velocity-Flat-Booster-T1-v0` | Booster T1 |
| 12 | `RobotLab-Isaac-Velocity-Rough-Booster-T1-v0` | Booster T1 |
| 13 | `RobotLab-Isaac-Velocity-Flat-Openloong-Loong-v0` | Openloong Loong |
| 14 | `RobotLab-Isaac-Velocity-Rough-Openloong-Loong-v0` | Openloong Loong |
| 15 | `RobotLab-Isaac-Velocity-Flat-RoboParty-ATOM01-v0` | RoboParty ATOM01 |
| 16 | `RobotLab-Isaac-Velocity-Rough-RoboParty-ATOM01-v0` | RoboParty ATOM01 |
| 17 | `RobotLab-Isaac-Velocity-Flat-MagicLab-Bot-Gen1-v0` | MagicLab MagicBot Gen1 |
| 18 | `RobotLab-Isaac-Velocity-Rough-MagicLab-Bot-Gen1-v0` | MagicLab MagicBot Gen1 |
| 19 | `RobotLab-Isaac-Velocity-Flat-MagicLab-Bot-Z1-v0` | MagicLab MagicBot Z1 |
| 20 | `RobotLab-Isaac-Velocity-Rough-MagicLab-Bot-Z1-v0` | MagicLab MagicBot Z1 |

### Quadruped (8 robots, 16 envs)

| # | Task Name | Robot |
|---|-----------|-------|
| 1 | `RobotLab-Isaac-Velocity-Flat-Unitree-Go2-v0` | Unitree Go2 |
| 2 | `RobotLab-Isaac-Velocity-Rough-Unitree-Go2-v0` | Unitree Go2 |
| 3 | `RobotLab-Isaac-Velocity-Flat-Unitree-A1-v0` | Unitree A1 |
| 4 | `RobotLab-Isaac-Velocity-Rough-Unitree-A1-v0` | Unitree A1 |
| 5 | `RobotLab-Isaac-Velocity-Flat-Unitree-B2-v0` | Unitree B2 |
| 6 | `RobotLab-Isaac-Velocity-Rough-Unitree-B2-v0` | Unitree B2 |
| 7 | `RobotLab-Isaac-Velocity-Flat-Deeprobotics-Lite3-v0` | Deeprobotics Lite3 |
| 8 | `RobotLab-Isaac-Velocity-Rough-Deeprobotics-Lite3-v0` | Deeprobotics Lite3 |
| 9 | `RobotLab-Isaac-Velocity-Flat-Zsibot-ZSL1-v0` | Zsibot ZSL1 |
| 10 | `RobotLab-Isaac-Velocity-Rough-Zsibot-ZSL1-v0` | Zsibot ZSL1 |
| 11 | `RobotLab-Isaac-Velocity-Flat-MagicLab-Dog-v0` | MagicLab MagicDog |
| 12 | `RobotLab-Isaac-Velocity-Rough-MagicLab-Dog-v0` | MagicLab MagicDog |
| 13 | `RobotLab-Isaac-Velocity-Flat-Agibot-D1-v0` | Agibot D1 |
| 14 | `RobotLab-Isaac-Velocity-Rough-Agibot-D1-v0` | Agibot D1 |
| 15 | `RobotLab-Isaac-Velocity-Flat-HandStand-Unitree-A1-v0` | Unitree A1 (Handstand) |
| 16 | `RobotLab-Isaac-Velocity-Rough-HandStand-Unitree-A1-v0` | Unitree A1 (Handstand) |

### Wheeled (6 robots, 12 envs)

| # | Task Name | Robot |
|---|-----------|-------|
| 1 | `RobotLab-Isaac-Velocity-Flat-Unitree-Go2W-v0` | Unitree Go2W |
| 2 | `RobotLab-Isaac-Velocity-Rough-Unitree-Go2W-v0` | Unitree Go2W |
| 3 | `RobotLab-Isaac-Velocity-Flat-Unitree-B2W-v0` | Unitree B2W |
| 4 | `RobotLab-Isaac-Velocity-Rough-Unitree-B2W-v0` | Unitree B2W |
| 5 | `RobotLab-Isaac-Velocity-Flat-Deeprobotics-M20-v0` | Deeprobotics M20 |
| 6 | `RobotLab-Isaac-Velocity-Rough-Deeprobotics-M20-v0` | Deeprobotics M20 |
| 7 | `RobotLab-Isaac-Velocity-Flat-DDTRobot-Tita-v0` | DDTRobot Tita |
| 8 | `RobotLab-Isaac-Velocity-Rough-DDTRobot-Tita-v0` | DDTRobot Tita |
| 9 | `RobotLab-Isaac-Velocity-Flat-Zsibot-ZSL1W-v0` | Zsibot ZSL1W |
| 10 | `RobotLab-Isaac-Velocity-Rough-Zsibot-ZSL1W-v0` | Zsibot ZSL1W |
| 11 | `RobotLab-Isaac-Velocity-Flat-MagicLab-Dog-W-v0` | MagicLab MagicDog-W |
| 12 | `RobotLab-Isaac-Velocity-Rough-MagicLab-Dog-W-v0` | MagicLab MagicDog-W |

### Direct RL (special)

| # | Task Name | Robot |
|---|-----------|-------|
| 1 | `RobotLab-Isaac-G1-AMP-Dance-Direct-v0` | Unitree G1 (AMP dance) |
| 2 | `RobotLab-Isaac-BeyondMimic-Flat-Unitree-G1-v0` | Unitree G1 (BeyondMimic) |

**Total: 50 registered environments** across 3 categories + 2 direct RL tasks.

## Training Commands

All commands require: `conda activate env_isaaclab && cd robot_lab`
On aarch64: prefix with `LD_PRELOAD="/lib/aarch64-linux-gnu/libgomp.so.1"`

### CusRL (preferred)
```bash
# Train XBot flat (NemoClaw target)
python scripts/reinforcement_learning/cusrl/train.py \
    --task=RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0 --headless

# Train XBot rough terrain
python scripts/reinforcement_learning/cusrl/train.py \
    --task=RobotLab-Isaac-Velocity-Rough-RobotEra-Xbot-v0 --headless

# Train Unitree G1 rough terrain
python scripts/reinforcement_learning/cusrl/train.py \
    --task=RobotLab-Isaac-Velocity-Rough-Unitree-G1-v0 --headless

# Common flags
#   --num_envs=4096          Number of parallel environments
#   --max_iterations=3000    Training iterations
#   --seed=42                RNG seed
#   --run_name=my_run        Name for logging
#   --video                  Record training videos
#   --logger=tensorboard     Logger backend (tensorboard or wandb)
```

### RSL-RL (alternative)
```bash
python scripts/reinforcement_learning/rsl_rl/train.py \
    --task=RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0 --num_envs=4096 --headless
```

### Evaluate / Play
```bash
# CusRL
python scripts/reinforcement_learning/cusrl/play.py \
    --task=RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0 --num_envs=1

# RSL-RL (with keyboard control)
python scripts/reinforcement_learning/rsl_rl/play.py \
    --task=RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0 --num_envs=1 --keyboard
```

### List All Environments
```bash
python scripts/tools/list_envs.py
```

## Architecture (Robot Lab / Isaac Lab)

### Manager-Based Environment
```python
LocomotionVelocityRoughEnvCfg(ManagerBasedRLEnvCfg):
    scene:        MySceneCfg          # Robot + terrain + sensors
    observations: ObservationsCfg     # Policy + Critic obs groups
    actions:      ActionsCfg          # Joint position targets
    commands:     CommandsCfg         # Velocity commands
    rewards:      RewardsCfg          # ~30 pluggable reward terms
    terminations: TerminationsCfg     # Time-out + illegal contact
    events:       EventCfg            # Domain randomization
    curriculum:   CurriculumCfg       # Terrain + command progression
```

### Base Simulation Settings
```
Decimation:       4
Sim dt:           0.005 s
Policy frequency: 50 Hz (4 x 0.005 = 0.02s per step)
Episode length:   20.0 s
Num environments: 4096
```

### Observation Space (Policy)
| Component | Dims | Noise | Scale |
|-----------|------|-------|-------|
| base_ang_vel | 3 | Uniform ±0.2 | 0.25 |
| projected_gravity | 3 | Uniform ±0.05 | 1.0 |
| velocity_commands | 3 | None | 1.0 |
| joint_pos (relative) | N_dof | Uniform ±0.01 | 1.0 |
| joint_vel | N_dof | Uniform ±1.5 | 0.05 |
| last_action | N_dof | None | 1.0 |

Note: For humanoid configs (G1/XBot), `base_lin_vel` and `height_scan` are disabled (not available on real hardware).

### Critic Observations
Same components as policy but with `enable_corruption = False` (no noise). This is the asymmetric actor-critic design — critic sees clean data during training.

### Action Space
```python
JointPositionActionCfg(
    asset_name="robot",
    joint_names=[".*"],
    scale=0.25,              # XBot: 0.25 uniform; G1: per-joint computed
    use_default_offset=True, # action = scale * action + default_pos
    preserve_order=True
)
```

## Key Hyperparameters

### XBot PPO Config (Robot Lab)
| Parameter | Value | Notes |
|-----------|-------|-------|
| num_envs | 4096 | Parallel environments |
| actor_hidden_dims | [512, 256, 128] | MLP layers |
| critic_hidden_dims | [512, 256, 128] | MLP layers |
| activation | ELU | Non-linearity |
| learning_rate | 1e-3 | Adaptive KL-based |
| gamma | 0.99 | Discount factor |
| lambda (GAE) | 0.95 | Advantage estimation |
| entropy_coef | 0.008 | Exploration bonus |
| clip_param | 0.2 | PPO clip range |
| num_learning_epochs | 5 | Epochs per iteration |
| num_mini_batches | 4 | Mini-batch splits |
| max_iterations | 3000 | Total training iterations |
| action_scale | 0.25 | Joint target scaling |

## Reward Functions (XBot)

All rewards include an **uprightness gate**: `reward *= clamp(-projected_gravity_z, 0, 0.7) / 0.7`

### Tracking
- `track_lin_vel_xy_exp` (2.0): exp(-error/std²), std=√0.25
- `track_ang_vel_z_exp` (2.0): exp(-error/std²), std=√0.25

### Stability
- `upward` (1.0): keep base upright
- `ang_vel_xy_l2` (-0.1): penalize roll/pitch angular velocity
- `flat_orientation_l2` (-0.2): penalize non-flat orientation

### Joint Regularization
- `joint_torques_l2` (-1e-8): minimize torque usage
- `joint_acc_l2` (-1.25e-7): smooth joint accelerations
- `joint_deviation_hip_l1` (-0.01): keep hips near default
- `joint_deviation_arms_l1` (-0.05): keep arms near default
- `joint_pos_limits` (-1.0): penalize near joint limits
- `joint_pos_penalty` (-1.0): default pose deviation

### Contact & Gait
- `feet_air_time` (2.0): promote stepping (threshold 0.4s)
- `feet_slide` (-0.4): penalize foot sliding during contact
- `is_terminated` (-200.0): large penalty on fall

### Action
- `action_rate_l2` (-0.005): temporal smoothness

## Domain Randomization

### Startup (once at env creation)
- Rigid body friction: [0.3, 1.0] static, [0.3, 0.8] dynamic
- Base mass: add [-1.0, 3.0] kg
- All body mass: scale [0.7, 1.3]x
- COM position: offset ±0.05m per body

### Per Reset
- External force/torque: ±10 N, ±10 Nm on base
- Actuator gains: scale stiffness/damping [0.5, 2.0]x
- Base velocity: ±0.5 m/s, ±0.5 rad/s

### Interval
- Push robot: ±0.5 m/s every 10-15 seconds

## Tuning Guidance

### If the robot falls forward
- Increase `upward` and `flat_orientation_l2` weights
- Reduce velocity command ranges
- Check `base_height_target` matches robot

### If the robot shuffles (doesn't lift feet)
- Increase `feet_air_time` weight (default 2.0 for XBot)
- Increase air time threshold
- Reduce `feet_slide` penalty if too aggressive

### If gait is jerky
- Increase `action_rate_l2` penalty
- Reduce action scale
- Increase `joint_acc_l2` penalty

### If sim-to-real transfer fails
- Increase domain randomization ranges
- Increase observation noise
- Verify actuator model matches hardware PD gains

## Debugging and Training Guide

### Parallel Environments and Memory

The number of parallel environments (`num_envs`) is the primary scaling knob. More envs = more rollout data per iteration = faster learning, but bounded by GPU memory.

**Memory usage scales with:**
- Number of environments (linear)
- Mesh complexity (high-fidelity collision/visual meshes cost more)
- Rendering (viewport/cameras cost significantly more than headless physics)
- Image observations (if used — buffer size x resolution x num_envs)
- Policy network size (larger networks for image-based policies)

**To reduce memory / fix OOM errors:**
1. Run headless (`--headless`) — avoid viewport rendering overhead
2. Reduce `num_envs` (most direct fix)
3. Simplify collision meshes to minimum required shapes
4. Reduce image resolution if using camera observations
5. Use `--device cuda:0` to target a specific GPU

### Scaling num_envs

| Scenario | Recommendation |
|----------|---------------|
| OOM error | Halve `num_envs` until it fits |
| Training too slow | Increase `num_envs` (watch for diminishing returns) |
| Low num_envs forced | Increase batch size or horizon length to compensate |
| Multi-GPU available | Use `--distributed` flag for parallel GPU training |
| Saturated returns | num_envs is past the sweet spot — reduce and save memory |

**Typical sweet spots on NVIDIA GB10 (92GB unified memory):**
- Simple locomotion (flat terrain, no cameras): 4096–8192 envs
- Rough terrain with height scan: 2048–4096 envs
- With rendering/cameras: 256–1024 envs

### Debugging NaN Crashes

NaNs in observation buffers crash the training pipeline. Common causes and fixes:

| Cause | Fix |
|-------|-----|
| Simulation instability from extreme actions | Tighten `clip_actions` |
| Joint/velocity limits exceeded | Verify URDF effort/velocity limits are reasonable |
| PD gains too high | Reduce Kp/Kd, especially for ankle joints |
| Physics timestep too large | Reduce `sim.dt` (default 0.005 for Robot Lab) |
| Invalid reset states | Check `init_state.pos` height, ensure robot spawns above ground |
| Solver instability | Increase `num_position_iterations` (default 4, try 8) |

### Understanding Training Output

#### RSL-RL Output
```
  Learning iteration 50/3000
  Computation: 50355 steps/s (collection: 1.106s, learning 0.195s)
  Value function loss: 22.05       # Critic prediction error — should decrease
  Surrogate loss: -0.008           # PPO policy loss — should be small negative
  Mean action noise std: 0.85      # Exploration noise — decreases as policy improves
  Mean reward: 12.5                # Primary metric — should increase
  Mean episode length: 450         # Longer = robot stays alive longer
```

**What to watch:**
- `Mean reward` trending up = learning is working
- `Mean episode length` increasing = robot survives longer
- `Value function loss` decreasing = critic is fitting
- `Mean action noise std` decreasing = policy is converging
- `Surrogate loss` should be small; large values suggest instability

#### CusRL Output
CusRL uses tensorboard logging by default. Monitor with:
```bash
tensorboard --logdir logs/cusrl/ --bind_all
```

#### Healthy Training Signs
- Reward climbs steadily for first 500–1000 iterations
- Episode length approaches max episode length
- Action noise std drops from 1.0 toward 0.3–0.5
- No NaN warnings in logs

#### Unhealthy Training Signs
- Reward flat or oscillating after 200+ iterations — check reward scales
- Episode length stuck at low values — robot keeps falling, increase stability rewards
- Noise std drops to near 0 too fast — increase `entropy_coef`
- Noise std stays at 1.0 — policy isn't learning, check observations/rewards
- `Value function loss` increasing — learning rate too high or data distribution shifting

### Common Errors and Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `CUDA out of memory` | Too many envs or large meshes | Reduce `num_envs`, run `--headless` |
| `RuntimeError: NaN` in obs | Simulation instability | See NaN section above |
| `ImportError: handle_deprecated_rsl_rl_cfg` | robot_lab/isaaclab version mismatch | Patched in local scripts (try/except fallback) |
| `ModuleNotFoundError: pxr` | Running outside IsaacSim context | Use `LD_PRELOAD` and launch via IsaacSim python |
| `LD_PRELOAD` warning on aarch64 | IsaacSim shared lib ordering | `export LD_PRELOAD="/lib/aarch64-linux-gnu/libgomp.so.1"` |
| Reward stuck at 0 | `only_positive_rewards` or uprightness gate | Normal initially — check if reward terms are firing |
