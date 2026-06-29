# NemoClaw Agent — Skills Document

> Source paper: **Humanoid-Gym: Reinforcement Learning for Humanoid Robot with Zero-Shot Sim2Real Transfer**
> (arXiv:2404.05695v2 — Gu, Wang, Chen, 2024)
> Source code: `humanoid-gym/` (roboterax/humanoid-gym)

---

## 1. Overview

NemoClaw is a humanoid locomotion agent trained via massively parallel deep reinforcement learning in NVIDIA Isaac Gym. It uses PPO with an Asymmetric Actor-Critic architecture, enabling zero-shot sim-to-real transfer. The pipeline includes sim-to-sim validation through MuJoCo and extensive domain randomization.

### Core Capabilities
- Velocity-commanded bipedal walking on flat and uneven terrain
- Zero-shot transfer from Isaac Gym simulation to physical hardware
- Sim-to-sim validation (Isaac Gym -> MuJoCo) for policy robustness checks
- Gait-phase-aware contact planning with sinusoidal reference motion

---

## 2. Problem Formulation

The agent operates within a **Partially Observable Markov Decision Process (POMDP)**:

| Symbol | Definition |
|--------|-----------|
| S | Full state space (simulation only — used by critic) |
| A | Action space: 12D target joint positions for PD controller |
| T(s'\|s,a) | Transition dynamics |
| R(s,a) | Reward function |
| O | Observation space (partial — used by actor, deployable on real robot) |
| gamma | Discount factor = 0.994 |

**Policy objective**: `J = E[sum_t gamma^t * r_t]`

---

## 3. Neural Network Architecture

### 3.1 Actor (Policy Network)
```
Input: 705 dims (47 obs × 15 frame stack)
  → Linear(705, 512) → ELU
  → Linear(512, 256) → ELU
  → Linear(256, 128) → ELU
  → Linear(128, 12)
Output: 12D action mean
```
- Action distribution: `Normal(mean, std)` where `std` is a learnable parameter (init=1.0)
- Inference: deterministic (mean only, no sampling)

### 3.2 Critic (Value Network)
```
Input: 219 dims (73 privileged obs × 3 frame stack)
  → Linear(219, 768) → ELU
  → Linear(768, 256) → ELU
  → Linear(256, 128) → ELU
  → Linear(128, 1)
Output: scalar value estimate
```

### 3.3 Asymmetric Design
- **Actor** receives partial observations only (deployable on real hardware)
- **Critic** receives full privileged state (simulation-only, includes ground truth physics)
- This enables training with rich information while deploying a sensor-only policy

---

## 4. Observation Space (Actor Input)

**Single frame: 47 dimensions** — stacked 15 frames → **705 total**

Layout in tensor (from `humanoid_env.py:compute_observations`):

| Index | Component | Dims | Details |
|-------|-----------|------|---------|
| 0-1 | Clock signal | 2 | `sin(2π·phase)`, `cos(2π·phase)` |
| 2-4 | Velocity commands (scaled) | 3 | `[vx, vy, ωyaw] × obs_scales` |
| 5-16 | Joint positions | 12 | `(dof_pos - default_dof_pos) × dof_pos_scale` |
| 17-28 | Joint velocities | 12 | `dof_vel × dof_vel_scale` |
| 29-40 | Last actions | 12 | Previous policy output |
| 41-43 | Angular velocity | 3 | `base_ang_vel × ang_vel_scale` |
| 44-46 | Euler angles | 3 | `base_euler_xyz × quat_scale` |

**Observation scales** (normalization):
```
lin_vel = 2.0, ang_vel = 1.0, dof_pos = 1.0, dof_vel = 0.05, quat = 1.0
```

**Noise** (added during training, noise_level=0.6):
```
dof_pos: ±0.05, dof_vel: ±0.5, ang_vel: ±0.1, quat: ±0.03
commands/actions: no noise added
```

**Clipping**: observations clipped to [-18, 18]

---

## 5. Privileged State Space (Critic Input)

**Single frame: 73 dimensions** — stacked 3 frames → **219 total**

| Index | Component | Dims | Details |
|-------|-----------|------|---------|
| 0-4 | Command input | 5 | Same as actor (clock + velocity cmds) |
| 5-16 | Joint position delta | 12 | `(dof_pos - default_joint_pd_target) × dof_pos_scale` |
| 17-28 | Joint velocities | 12 | `dof_vel × dof_vel_scale` |
| 29-40 | Actions | 12 | Current policy output |
| 41-52 | Tracking difference | 12 | `dof_pos - ref_dof_pos` (deviation from reference trajectory) |
| 53-55 | Base linear velocity | 3 | `base_lin_vel × lin_vel_scale` |
| 56-58 | Base angular velocity | 3 | `base_ang_vel × ang_vel_scale` |
| 59-61 | Euler angles | 3 | `base_euler_xyz × quat_scale` |
| 62-63 | Push force | 2 | Random external force (x, y) |
| 64-66 | Push torque | 3 | Random external torque (x, y, z) |
| 67 | Friction | 1 | Ground friction coefficient for this env |
| 68 | Body mass | 1 | `mass / 30.0` (normalized) |
| 69-70 | Stance mask | 2 | Expected contact state [left, right] |
| 71-72 | Contact mask | 2 | Actual foot contact (`contact_force_z > 5.0`) |

---

## 6. Action Space & Control

### 6.1 Action Output
- **12-dimensional** vector of target joint position offsets
- Actions clipped to [-18, 18] before processing

### 6.2 Joint Mapping (12 DOF)
```
Index  Joint Name                  Kp    Kd
0      left_leg_roll_joint         200   10
1      left_leg_yaw_joint          200   10
2      left_leg_pitch_joint        350   10
3      left_knee_joint             350   10
4      left_ankle_pitch_joint       15   10
5      left_ankle_roll_joint        15   10
6      right_leg_roll_joint        200   10
7      right_leg_yaw_joint         200   10
8      right_leg_pitch_joint       350   10
9      right_knee_joint            350   10
10     right_ankle_pitch_joint      15   10
11     right_ankle_roll_joint       15   10
```

### 6.3 PD Controller
```
torque = Kp × (action_scale × action + default_pos - current_pos) - Kd × current_vel
```
- `action_scale = 0.25`
- `default_pos = 0.0` for all joints
- Torques clipped to `±torque_limit` (85% of URDF effort limits)

### 6.4 Timing
- **Policy frequency**: 100 Hz (every 10 sim steps)
- **PD controller / sim frequency**: 1000 Hz (dt = 0.001s)
- **Decimation**: 10 (10 physics steps per policy step)

### 6.5 Action Processing Pipeline (in `step()`)
```python
# 1. Optional: add reference action
if use_ref_actions:
    actions += ref_action

# 2. Clip
actions = clip(actions, -18, 18)

# 3. Random delay (domain randomization)
delay = rand(0, 0.5)  # per env
actions = (1 - delay) * actions + delay * previous_actions

# 4. Action noise
actions += 0.02 * randn_like(actions) * actions

# 5. Apply through PD controller for 10 substeps
for _ in range(10):
    torques = PD_control(actions)
    simulate()
```

---

## 7. Gait Design

### 7.1 Phase Calculation
```python
cycle_time = 0.64  # seconds per full gait cycle
phase = episode_step * dt / cycle_time
sin_pos = sin(2π × phase)
```

### 7.2 Stance Mask (Foot Contact Schedule)
```python
stance_mask = zeros(num_envs, 2)  # [left, right]
stance_mask[:, 0] = (sin_pos >= 0)    # left foot in stance
stance_mask[:, 1] = (sin_pos < 0)     # right foot in stance
stance_mask[|sin_pos| < 0.1] = [1, 1] # double support phase
```

### 7.3 Reference Motion Generation
```python
scale_1 = 0.17  # rad (~9.7°)
scale_2 = 0.34  # rad (~19.5°, 2× scale_1)

ref_dof_pos = zeros_like(dof_pos)

# Left leg swing (sin_pos negative half):
sin_pos_l = sin_pos.clone()
sin_pos_l[sin_pos_l > 0] = 0       # zero during left stance
ref_dof_pos[:, 2] = sin_pos_l × scale_1   # left_leg_pitch
ref_dof_pos[:, 3] = sin_pos_l × scale_2   # left_knee (2× pitch)
ref_dof_pos[:, 4] = sin_pos_l × scale_1   # left_ankle_pitch

# Right leg swing (sin_pos positive half):
sin_pos_r = sin_pos.clone()
sin_pos_r[sin_pos_r < 0] = 0       # zero during right stance
ref_dof_pos[:, 8] = sin_pos_r × scale_1   # right_leg_pitch
ref_dof_pos[:, 9] = sin_pos_r × scale_2   # right_knee
ref_dof_pos[:, 10] = sin_pos_r × scale_1  # right_ankle_pitch

# Double support — all reference positions zero:
ref_dof_pos[|sin_pos| < 0.1] = 0

ref_action = 2 × ref_dof_pos  # pre-scaled for action_scale=0.25
```

---

## 8. Reward Functions

Total reward: `r_t = sum(reward_fn_i() × scale_i × dt)` — scales are multiplied by dt at init.
Negative total rewards clipped to zero (`only_positive_rewards = True`).

### 8.1 Velocity Tracking

| Reward | Scale | Implementation |
|--------|-------|---------------|
| `tracking_lin_vel` | 1.2 | `exp(-tracking_sigma × sum((cmd_xy - vel_xy)²))`, sigma=5 |
| `tracking_ang_vel` | 1.1 | `exp(-tracking_sigma × (cmd_yaw - ω_yaw)²)`, sigma=5 |
| `track_vel_hard` | 0.5 | Combined: `(exp(-10×lin_err) + exp(-10×ang_err))/2 - 0.2×(lin_err+ang_err)` |
| `vel_mismatch_exp` | 0.5 | `(exp(-10×vz²) + exp(-5×‖ω_xy‖))/2` — penalize unwanted z/roll/pitch motion |
| `low_speed` | 0.2 | Discrete: -1.0 if too slow, +1.2 if in range, -2.0 if wrong direction |

### 8.2 Gait & Contact

| Reward | Scale | Implementation |
|--------|-------|---------------|
| `joint_pos` | 1.6 | `exp(-2×‖pos-ref_pos‖) - 0.2×clamp(‖pos-ref_pos‖, 0, 0.5)` |
| `feet_contact_number` | 1.2 | `mean(+1 if contact==stance_mask else -0.3)` |
| `feet_air_time` | 1.0 | Air time accumulator, clamped to 0.5s, triggered on first contact |
| `feet_clearance` | 1.0 | Reward for swing foot reaching target height (0.06m) within 0.01m tolerance |
| `feet_distance` | 0.2 | Penalize feet too close (<0.2m) or too far apart (>0.5m) |
| `knee_distance` | 0.2 | Same logic for knees, max_dist halved to 0.25m |

### 8.3 Base Stability

| Reward | Scale | Implementation |
|--------|-------|---------------|
| `orientation` | 1.0 | `(exp(-10×‖euler_xy‖) + exp(-20×‖projected_gravity_xy‖))/2` |
| `base_height` | 0.2 | `exp(-100×|height - 0.89|)`, height measured relative to avg stance foot z |
| `default_joint_pos` | 0.5 | `exp(-100×clamp(yaw_roll_norm-0.1, 0, 50)) - 0.01×‖joint_diff‖` |
| `base_acc` | 0.2 | `exp(-3×‖root_acc‖)` — penalize abrupt accelerations |

### 8.4 Regularization (Penalties)

| Reward | Scale | Implementation |
|--------|-------|---------------|
| `action_smoothness` | -0.002 | `‖a-a_prev‖² + ‖a+a_prevprev-2×a_prev‖² + 0.05×‖a‖₁` |
| `torques` | -1e-5 | `sum(τ²)` |
| `dof_vel` | -5e-4 | `sum(dof_vel²)` |
| `dof_acc` | -1e-7 | `sum((dof_vel-prev_dof_vel)²/dt²)` |
| `foot_slip` | -0.05 | `sum(√foot_speed × contact_bool)` |
| `feet_contact_forces` | -0.01 | `sum(clamp(‖F‖-700, 0, 400))` |
| `collision` | -1.0 | Count of penalized body parts in contact (base_link) |

---

## 9. Domain Randomization

### 9.1 Observation Noise (per step, Gaussian)
| Parameter | Range | Scale in code |
|-----------|-------|---------------|
| Joint Position | ±0.05 rad | `noise_level(0.6) × noise_scale(0.05) × obs_scale(1.0)` |
| Joint Velocity | ±0.5 rad/s | `noise_level(0.6) × noise_scale(0.5) × obs_scale(0.05)` |
| Angular Velocity | ±0.1 rad/s | `noise_level(0.6) × noise_scale(0.1) × obs_scale(1.0)` |
| Euler Angle | ±0.03 rad | `noise_level(0.6) × noise_scale(0.03) × obs_scale(1.0)` |

### 9.2 Environment Randomization (per episode/env)
| Parameter | Range | Method |
|-----------|-------|--------|
| Friction | [0.1, 2.0] | 256 buckets, randomly assigned per env at creation |
| Added Base Mass | [-5, +5] kg | Uniform, applied to link 0 |
| Random Pushes | vel ±0.2 m/s, torque ±0.4 rad/s | Every 4 seconds |
| Action Delay | [0, 0.5] | Interpolate between current and previous actions |
| Action Noise | 0.02 × randn × action | Multiplicative noise |
| DOF Reset Noise | ±0.1 rad | On environment reset |

---

## 10. Training Configuration

### 10.1 PPO Hyperparameters
| Parameter | Value |
|-----------|-------|
| Number of Environments | 4096 |
| Steps per Env per Iteration | 60 |
| Batch Size | 4096 × 60 = 245,760 transitions/iter |
| Mini-batches | 4 |
| Learning Epochs per Iteration | 2 |
| Discount Factor (gamma) | 0.994 |
| GAE Lambda | 0.9 |
| Clip Parameter | 0.2 |
| Learning Rate | 1e-5 (adaptive schedule, KL-based) |
| Entropy Coefficient | 0.001 |
| Value Loss Coefficient | 1.0 |
| Max Gradient Norm | 1.0 |
| Max Iterations | 3001 |
| Seed | 5 |

### 10.2 Adaptive Learning Rate (KL-based)
```python
if kl_mean > 2 × desired_kl:
    lr = max(1e-5, lr / 1.5)
elif kl_mean < desired_kl / 2:
    lr = min(1e-2, lr × 1.5)
# desired_kl = 0.01
```

### 10.3 Episode Configuration
| Parameter | Value |
|-----------|-------|
| Episode Length | 24 seconds (2400 steps at 100Hz) |
| Init Position | [0, 0, 0.95] meters |
| Command Resample Time | 8 seconds |
| Heading Command Mode | Yes (ang_vel computed from heading error) |
| Velocity Ranges | vx: [-0.3, 0.6], vy: [-0.3, 0.3], ωyaw: [-0.3, 0.3] m/s or rad/s |
| Small Command Zeroing | Commands zeroed if ‖vx,vy‖ < 0.2 |

---

## 11. Training Pipeline

```
┌──────────────────────────────────────────────────────────────────┐
│  Stage 1: Training in Isaac Gym                                  │
│  python humanoid/scripts/train.py --task=XBotL_ppo               │
│                                                                  │
│  - 4096 parallel envs on GPU (PhysX)                             │
│  - PPO + Asymmetric Actor-Critic                                 │
│  - Domain randomization (friction, mass, pushes, delay, noise)   │
│  - 100Hz policy → 1000Hz PD controller                           │
│  - ~3001 iterations                                              │
│  - Saves checkpoints every 100 iterations                        │
│  - Logs: logs/XBot_ppo/                                          │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Stage 2: Policy Export & Evaluation (Isaac Gym)                 │
│  python humanoid/scripts/play.py --task=XBotL_ppo                │
│                                                                  │
│  - Loads trained policy, runs 1 env                              │
│  - Exports as TorchScript JIT (.pt file)                         │
│  - Renders video, logs states                                    │
│  - Output: logs/XBot_ppo/exported/policies/policy_example.pt     │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Stage 3: Sim-to-Sim Validation (MuJoCo)                         │
│  python humanoid/scripts/sim2sim.py --load_model policy.pt       │
│                                                                  │
│  - Loads JIT policy + MuJoCo XML model                           │
│  - Reconstructs observation vector identically to training       │
│  - PD control at 1000Hz, policy at 100Hz (decimation=10)         │
│  - Fixed commands: vx=0.4, vy=0, dyaw=0                         │
│  - Duration: 60 seconds                                          │
│  - Optional: --terrain flag for uneven terrain XML               │
│  - MuJoCo models: resources/robots/XBot/mjcf/XBot-L.xml         │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Stage 4: Zero-Shot Sim-to-Real Transfer                         │
│                                                                  │
│  - Deploy JIT policy on robot computer                           │
│  - Reconstruct observation from onboard sensors (IMU, encoders)  │
│  - Actor-only (no critic needed)                                 │
│  - Same PD gains, action scale, observation normalization        │
│  - No fine-tuning required                                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## 12. Sim-to-Sim Observation Reconstruction (MuJoCo)

The `sim2sim.py` script reconstructs the exact same observation vector from MuJoCo sensor data:

```python
obs[0]  = sin(2π × t / 0.64)          # clock sin
obs[1]  = cos(2π × t / 0.64)          # clock cos
obs[2]  = cmd_vx × 2.0                # lin_vel_scale
obs[3]  = cmd_vy × 2.0                # lin_vel_scale
obs[4]  = cmd_dyaw × 1.0              # ang_vel_scale
obs[5:17]  = joint_positions × 1.0    # dof_pos_scale
obs[17:29] = joint_velocities × 0.05  # dof_vel_scale
obs[29:41] = last_actions              # unscaled
obs[41:44] = angular_velocity          # from IMU
obs[44:47] = euler_angles              # from quaternion
# Clip to [-18, 18], stack 15 frames → 705D policy input
```

---

## 13. Robot Hardware Specification (XBot-L)

| Spec | Value |
|------|-------|
| Height | 1.65 m |
| Weight | 57 kg |
| Actuated Motors | 54 total (12 used for legs) |
| Total DOF | 60 total (12 used for locomotion) |
| URDF | `resources/robots/XBot/urdf/XBot-L.urdf` |
| MuJoCo XML | `resources/robots/XBot/mjcf/XBot-L.xml` |
| Foot body name | `ankle_roll` |
| Knee body name | `knee` |
| Termination contact | `base_link` |
| Init height | 0.95 m |
| Target base height | 0.89 m |

### Terrain Configuration
- Default: flat plane (`mesh_type = 'plane'`)
- Static/dynamic friction: 0.6
- Alternative: trimesh for rough terrain curriculum

---

## 14. Code Architecture

```
humanoid-gym/
├── humanoid/
│   ├── envs/
│   │   ├── base/
│   │   │   ├── base_config.py          # BaseConfig class
│   │   │   ├── base_task.py            # BaseTask (Isaac Gym wrapper)
│   │   │   ├── legged_robot.py         # LeggedRobot (core env logic)
│   │   │   └── legged_robot_config.py  # LeggedRobotCfg defaults
│   │   └── custom/
│   │       ├── humanoid_config.py      # XBotLCfg (overrides defaults)
│   │       └── humanoid_env.py         # XBotLFreeEnv (reward fns, obs)
│   ├── algo/
│   │   └── ppo/
│   │       ├── actor_critic.py         # ActorCritic MLP model
│   │       ├── ppo.py                  # PPO algorithm
│   │       ├── on_policy_runner.py     # Training loop
│   │       └── rollout_storage.py      # Experience buffer
│   ├── scripts/
│   │   ├── train.py                    # Training entry point
│   │   ├── play.py                     # Evaluation + JIT export
│   │   └── sim2sim.py                  # MuJoCo validation
│   └── utils/
│       ├── task_registry.py            # Env/algorithm registration
│       ├── terrain.py                  # HumanoidTerrain generator
│       ├── math.py                     # Quaternion/rotation utilities
│       ├── helpers.py                  # Config parsing utilities
│       ├── logger.py                   # Logging and plotting
│       └── calculate_gait.py          # Gait analysis tools
├── resources/robots/XBot/              # URDF, MJCF, STL meshes
├── logs/XBot_ppo/exported/policies/    # Pre-trained policy
└── setup.py                            # Package installation
```

### Key Class Hierarchy
```
BaseTask (Isaac Gym interface)
  └── LeggedRobot (PD control, buffers, reset logic, termination)
        └── XBotLFreeEnv (observations, gait, 17 reward functions)
```

---

## 15. Key Implementation Details

### 15.1 Reward Scale × dt
All reward scales are multiplied by `dt` (0.01s at 100Hz) during initialization. This normalizes rewards per timestep regardless of control frequency.

### 15.2 Only Positive Rewards
`only_positive_rewards = True` — negative total rewards are clipped to zero. This prevents early termination problems where the agent learns to end episodes to avoid accumulating penalties.

### 15.3 Bootstrapping on Timeouts
When an episode times out (not a failure), the value estimate is bootstrapped: `reward += gamma × V(s) × timeout_flag`. This prevents the agent from learning that the episode boundary has zero value.

### 15.4 Heading Command Mode
Angular velocity commands are not sampled directly. Instead, a heading target is sampled from [-π, π], and the angular velocity command is computed from heading error: `ω_cmd = clip(0.5 × wrap_to_pi(heading_target - current_heading), -1, 1)`.

### 15.5 Termination Conditions
- Contact force on `base_link` > 1.0 N (robot fell)
- Episode length exceeds 24 seconds (timeout, not failure)

### 15.6 PD Control Torque Computation
```python
actions_scaled = actions × 0.25
torques = Kp × (actions_scaled + default_pos - dof_pos) - Kd × dof_vel
torques = clip(torques, -torque_limit, torque_limit)
```
Applied 10 times per policy step (1000Hz inner loop).

---

## 16. Commands for Training & Deployment

```bash
# Install
cd humanoid-gym && pip install -e .

# Train
python humanoid/scripts/train.py --task=XBotL_ppo

# Evaluate + export policy
python humanoid/scripts/play.py --task=XBotL_ppo

# Sim-to-sim (MuJoCo, flat terrain)
python humanoid/scripts/sim2sim.py --load_model logs/XBot_ppo/exported/policies/policy_example.pt

# Sim-to-sim (MuJoCo, uneven terrain)
python humanoid/scripts/sim2sim.py --load_model logs/XBot_ppo/exported/policies/policy_example.pt --terrain
```

---

## 17. Dependencies

| Component | Framework |
|-----------|-----------|
| Training simulator | NVIDIA Isaac Gym (Preview 4) |
| Validation simulator | MuJoCo + mujoco-viewer |
| RL algorithm | PPO (custom, based on rsl_rl) |
| Deep learning | PyTorch |
| Physics | PhysX (via Isaac Gym) |
| Base code | legged_gym / rsl_rl (ETH Robotic Systems Lab) |
| Robot description | URDF (Isaac Gym), MJCF XML (MuJoCo) |

---
---

# PART II — Robot Lab (Isaac Lab Extension)

> Source code: `robot_lab/` (fan-ziqi/robot_lab)
> Framework: Isaac Lab v2.3.2 + Isaac Sim 4.5/5.0/5.1

---

## 18. Robot Lab Overview

Robot Lab is a production-grade Isaac Lab extension that provides a modular, manager-based RL framework for training locomotion policies across 20+ robot morphologies. It supports multiple RL backends (RSL-RL, CusRL, SKRL), manager-based environment composition, terrain curriculum, and extensive domain randomization.

### Key Differences from Humanoid-Gym

| Feature | Humanoid-Gym | Robot Lab |
|---------|-------------|-----------|
| Simulator | Isaac Gym (Preview 4) | Isaac Lab / Isaac Sim |
| Environment style | Monolithic class | Manager-based (modular MDP) |
| Robot support | XBot-S, XBot-L | 20+ robots (10 humanoids) |
| RL backends | Custom PPO only | RSL-RL, CusRL, SKRL |
| Observations | Hand-coded tensor | Declarative ObsTerm configs |
| Rewards | Hard-coded methods | Pluggable RewTerm functions |
| Domain randomization | In-env code | EventTerm system |
| Terrain | Flat/trimesh | Procedural generator with curriculum |
| Sim-to-sim | MuJoCo pipeline | Not built-in (Isaac Lab native) |
| Asymmetric critic | frame-stacked privileged obs | Separate critic obs group |
| Physics | PhysX (GPU) | PhysX 5 (GPU) via Isaac Sim |

---

## 19. Supported Humanoid Robots

| Robot | DOF | Init Height | Foot Body | Base Body |
|-------|-----|-------------|-----------|-----------|
| Unitree G1 | 29 | 0.76 m | `*_ankle_roll_link` | `torso_link` |
| Unitree H1 | — | — | `*_ankle_link` | `pelvis` |
| RobotEra XBot | 12 (legs) | 0.95 m | `*_ankle_roll_link` | `base` |
| FFTAI GR1T1 | — | — | — | — |
| FFTAI GR1T2 | — | — | — | — |
| Booster T1 | — | — | — | — |
| Openloong Loong | — | — | — | — |
| RoboParty ATOM01 | — | — | — | — |
| MagicLab MagicBot Gen1 | — | — | — | — |
| MagicLab MagicBot Z1 | — | — | — | — |

---

## 20. Manager-Based Environment Architecture

### 20.1 Environment Composition

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

### 20.2 Base Simulation Settings
```
Decimation:       4
Sim dt:           0.005 s
Policy frequency: 50 Hz (4 × 0.005 = 0.02s per step)
Episode length:   20.0 s
Num environments: 4096
Env spacing:      2.5 m
```

---

## 21. Observation Space (Robot Lab)

### 21.1 Policy Observations (Actor)

| Component | Dims | Noise | Clip | Scale |
|-----------|------|-------|------|-------|
| base_lin_vel | 3 | Uniform ±0.1 | ±100 | 1.0 |
| base_ang_vel | 3 | Uniform ±0.2 | ±100 | 1.0 |
| projected_gravity | 3 | Uniform ±0.05 | ±100 | 1.0 |
| velocity_commands | 3 | None | ±100 | 1.0 |
| joint_pos (relative) | N_dof | Uniform ±0.01 | ±100 | 1.0 |
| joint_vel (relative) | N_dof | Uniform ±1.5 | ±100 | 1.0 |
| last_action | N_dof | None | ±100 | 1.0 |
| height_scan | 187 | Uniform ±0.1 | ±1.0 | 1.0 |

- `enable_corruption = True` (noise applied during training)
- Concatenated into a single tensor
- **Note**: For G1/XBot humanoid configs, `base_lin_vel` and `height_scan` are **disabled** (set to None)

### 21.2 Critic Observations
Same components as policy, but with `enable_corruption = False` (no noise). This is the Isaac Lab equivalent of humanoid-gym's asymmetric actor-critic.

### 21.3 Humanoid-Specific Observation Overrides (G1)
```python
# Disabled observations (set to None):
base_lin_vel = None      # Not available on real robot
height_scan = None       # No height scanner for deployment

# Rescaled observations:
base_ang_vel.scale = 0.25
joint_vel.scale = 0.05
```

---

## 22. Action Space (Robot Lab)

### 22.1 Action Configuration
```python
JointPositionActionCfg(
    asset_name="robot",
    joint_names=[".*"],        # All joints
    scale=0.5,                 # Default; overridden per robot
    use_default_offset=True,   # Action = scale × action + default_pos
    clip=None,                 # No clipping (or per-robot override)
    preserve_order=True        # Maintain URDF joint order
)
```

### 22.2 Per-Robot Action Scales

**Unitree G1 (29 DOF)**: Computed per joint as `0.25 × effort_limit / stiffness`
- This automatically adapts to each actuator's torque capacity and stiffness

**RobotEra XBot (12 DOF legs)**: Uniform `action_scale = 0.25`

---

## 23. Reward Functions (Robot Lab)

All rewards include an **uprightness gate**: `reward *= clamp(-projected_gravity_z, 0, 0.7) / 0.7`
This zeros out rewards when the robot has fallen over, preventing reward hacking while inverted.

### 23.1 Unitree G1 Reward Configuration

| Reward | Weight | Key Parameters |
|--------|--------|---------------|
| **Tracking** | | |
| track_lin_vel_xy_exp | +3.0 | std=√0.25, exp(-error/std²) |
| track_ang_vel_z_exp | +3.0 | std=√0.25, exp(-error/std²) |
| **Stability** | | |
| upward | +1.0 | `(1 - projected_gravity_z)²` |
| ang_vel_xy_l2 | -0.1 | `sum(ω_xy²)` |
| flat_orientation_l2 | -0.2 | `sum(gravity_xy²)` |
| **Joint Regularization** | | |
| joint_torques_l2 | -1.5e-7 | Applied to hip/knee/ankle only |
| joint_acc_l2 | -1.25e-7 | Applied to hip/knee only |
| joint_deviation_hip_l1 | -0.1 | Hip yaw/roll deviation from default |
| joint_deviation_arms_l1 | -0.1 | Shoulder/elbow deviation from default |
| joint_deviation_torso_l1 | -0.1 | Waist yaw deviation from default |
| joint_pos_limits | -0.5 | Penalize near joint limits |
| joint_pos_penalty | -1.0 | Default pose deviation (5× when standing) |
| **Action** | | |
| action_rate_l2 | -0.005 | `sum((a - a_prev)²)` |
| **Contact** | | |
| feet_air_time | +0.25 | threshold=0.4s, only when cmd > 0.1 |
| feet_slide | -0.2 | Foot lateral velocity × contact bool |
| **Termination** | | |
| is_terminated | -200.0 | Large penalty on fall |

### 23.2 RobotEra XBot Reward Differences (vs G1)

| Reward | XBot Weight | G1 Weight | Notes |
|--------|------------|-----------|-------|
| track_lin_vel_xy_exp | 2.0 | 3.0 | Lower tracking emphasis |
| track_ang_vel_z_exp | 2.0 | 3.0 | Lower tracking emphasis |
| feet_air_time | 2.0 | 0.25 | Much higher step incentive |
| feet_slide | -0.4 | -0.2 | Stricter no-slip penalty |
| joint_torques_l2 | -1e-8 | -1.5e-7 | More lenient torque penalty |
| joint_deviation_hip_l1 | -0.01 | -0.1 | Looser hip constraint |
| joint_deviation_arms_l1 | -0.05 | -0.1 | Looser arm constraint |
| joint_pos_limits | -1.0 | -0.5 | Stricter limit avoidance |

---

## 24. Domain Randomization (Robot Lab)

### 24.1 Startup Events (Applied Once at Env Creation)

| Event | Parameters |
|-------|-----------|
| Rigid body material | Static friction [0.3, 1.0], Dynamic friction [0.3, 0.8], Restitution [0.0, 0.5], 64 buckets |
| Base mass | Add [-1.0, 3.0] kg to base link, recompute inertia |
| All body mass | Scale [0.7, 1.3]×, recompute inertia |
| COM position | Offset ±0.05 m in x, y, z per body |

### 24.2 Reset Events (Applied Each Episode Reset)

| Event | Parameters |
|-------|-----------|
| External force/torque | ±10 N force, ±10 Nm torque on base |
| Joint reset | Scale [1.0, 1.0] × default positions (exact default) |
| Actuator gains | Scale stiffness/damping [0.5, 2.0]×, uniform distribution |
| Base pose | Position ±0.5 m (x,y), yaw [-π, π] |
| Base velocity | ±0.5 m/s (x,y,z), ±0.5 rad/s (roll,pitch,yaw) |

### 24.3 Interval Events (Applied Periodically)

| Event | Parameters |
|-------|-----------|
| Push robot | Velocity ±0.5 m/s (x,y), every 10-15 seconds |

---

## 25. PPO Configuration (Robot Lab — RSL-RL)

### 25.1 Unitree G1 PPO Hyperparameters

| Parameter | Value |
|-----------|-------|
| Actor hidden dims | [512, 256, 128] |
| Critic hidden dims | [512, 256, 128] |
| Activation | ELU |
| init_noise_std | 1.0 |
| Observation normalization | False (both actor and critic) |
| Steps per env | 24 |
| Max iterations | 3000 (rough), 1500 (flat) |
| Save interval | 50 |
| Learning rate | 1e-3 (adaptive, KL-based) |
| Num learning epochs | 5 |
| Num mini-batches | 4 |
| Gamma | 0.99 |
| Lambda (GAE) | 0.95 |
| Clip parameter | 0.2 |
| Entropy coefficient | 0.008 |
| Value loss coefficient | 1.0 |
| Desired KL | 0.01 |
| Max gradient norm | 1.0 |

### 25.2 Comparison: Robot Lab vs Humanoid-Gym PPO

| Parameter | Robot Lab (G1) | Humanoid-Gym (XBot) |
|-----------|---------------|-------------------|
| Learning rate | 1e-3 (adaptive) | 1e-5 (adaptive) |
| Gamma | 0.99 | 0.994 |
| Lambda | 0.95 | 0.9 |
| Learning epochs | 5 | 2 |
| Entropy coeff | 0.008 | 0.001 |
| Steps/env | 24 | 60 |
| Max iterations | 3000 | 3001 |
| Obs normalization | False | N/A (manual scaling) |
| Frame stacking | No | 15 (actor), 3 (critic) |

---

## 26. Terrain & Curriculum (Robot Lab)

### 26.1 Terrain Generator
- Procedural rough terrain with increasing difficulty levels
- Physics material: multiply friction/restitution mode
- Height scanner: RayCaster with 1.6m × 1.0m grid at 0.1m resolution (187 points)
- Base height scanner: 0.1m × 0.1m at 0.05m resolution

### 26.2 Curriculum System
- **Terrain levels**: Progress to harder terrains based on velocity tracking performance
- **Command levels (lin_vel)**: Expand velocity range from 10% to 100% based on `track_lin_vel_xy_exp` reward
- **Command levels (ang_vel)**: Same for angular velocity

---

## 27. Unitree G1 Actuator Model

The G1 uses physics-derived actuator parameters (not hand-tuned):

```python
NATURAL_FREQ = 62.83   # rad/s (10 Hz natural frequency)
DAMPING_RATIO = 2.0    # critically overdamped

# Per-motor computed constants:
#   stiffness = NATURAL_FREQ² × armature
#   damping = 2 × DAMPING_RATIO × NATURAL_FREQ × armature

Motor 7520-14 (hip yaw/pitch, waist yaw):
  armature = 0.010178, stiffness = 6.421, damping = 2.562

Motor 7520-22 (hip roll, knee):
  armature = 0.025102, stiffness = 15.808, damping = 6.306

Motor 5020 (ankle, waist roll/pitch):
  armature = 0.003610, stiffness = 2.270, damping = 0.908
  # Ankle uses 2× multiplier: stiffness = 4.540, damping = 1.816

Motor 4010 (arm joints):
  armature = 0.00425, stiffness = 2.681, damping = 1.069
```

---

## 28. Robot Lab Code Architecture

```
robot_lab/
├── scripts/reinforcement_learning/
│   ├── rsl_rl/                     # RSL-RL training (primary)
│   │   ├── train.py                # python train.py --task=<env_id>
│   │   ├── play.py                 # Evaluation with keyboard control
│   │   └── cli_args.py             # CLI argument parsing
│   ├── cusrl/                      # CusRL training (experimental)
│   └── skrl/                       # SKRL AMP training (G1 dance)
├── source/robot_lab/robot_lab/
│   ├── assets/                     # Robot definitions (URDF/USD refs + actuator configs)
│   │   ├── unitree.py              # G1 (29DOF), H1, Go2, A1, B2
│   │   ├── robotera.py             # XBot
│   │   ├── fftai.py                # GR1T1, GR1T2
│   │   └── ...                     # 11 manufacturer files total
│   └── tasks/
│       ├── manager_based/
│       │   └── locomotion/velocity/
│       │       ├── velocity_env_cfg.py        # Base env config (rewards, obs, events)
│       │       ├── mdp/
│       │       │   ├── rewards.py             # 30+ reward functions
│       │       │   ├── observations.py        # Observation term functions
│       │       │   ├── commands.py            # UniformThresholdVelocityCommand
│       │       │   ├── events.py              # Randomization event functions
│       │       │   └── curriculums.py         # Terrain/command curricula
│       │       └── config/
│       │           ├── humanoid/              # 10 humanoid robot configs
│       │           │   ├── unitree_g1/
│       │           │   │   ├── rough_env_cfg.py
│       │           │   │   ├── flat_env_cfg.py
│       │           │   │   ├── __init__.py    # Gym env registration
│       │           │   │   └── agents/rsl_rl_ppo_cfg.py
│       │           │   ├── robotera_xbot/
│       │           │   └── ...
│       │           ├── quadruped/             # 8 quadruped configs
│       │           └── wheeled/               # 6 wheeled configs
│       └── direct/g1_amp/                     # Direct RL: G1 AMP dance
└── config/extension.toml                      # Isaac Lab extension metadata
```

### Environment Registration Pattern
```python
# Each robot's __init__.py registers Gym environments:
gym.register(
    id="RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0",
    entry_point="isaaclab.envs:ManagerBasedRLEnv",
    kwargs={
        "env_cfg_entry_point": "...flat_env_cfg:UnitreeG1FlatEnvCfg",
        "rsl_rl_cfg_entry_point": "...rsl_rl_ppo_cfg:UnitreeG1RoughPPORunnerCfg",
    },
)
```

---

## 29. Training Commands (Robot Lab)

```bash
# Install (within Isaac Lab environment)
cd robot_lab && python -m pip install -e source/robot_lab

# Train G1 on rough terrain (RSL-RL)
python scripts/reinforcement_learning/rsl_rl/train.py \
    --task=RobotLab-Isaac-Velocity-Rough-Unitree-G1-v0 \
    --num_envs=4096 --headless

# Train XBot on flat terrain
python scripts/reinforcement_learning/rsl_rl/train.py \
    --task=RobotLab-Isaac-Velocity-Flat-RobotEra-XBot-v0 \
    --num_envs=4096 --headless

# Evaluate with keyboard control
python scripts/reinforcement_learning/rsl_rl/play.py \
    --task=RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0 \
    --num_envs=1 --keyboard

# Record video
python scripts/reinforcement_learning/rsl_rl/play.py \
    --task=RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0 \
    --video --video_length=200

# List all registered environments
python scripts/tools/list_envs.py
```

---

## 30. Framework Comparison Summary

| Aspect | Humanoid-Gym (Part I) | Robot Lab (Part II) |
|--------|----------------------|-------------------|
| **Best for** | Single-robot deep tuning, sim2real pipeline | Multi-robot experimentation, rapid prototyping |
| **Sim-to-real** | Built-in MuJoCo validation + zero-shot | Isaac Lab native (no sim2sim needed) |
| **Observation design** | Custom tensor packing, frame stacking | Declarative ObsTerm configs, no frame stacking |
| **Reward tuning** | Modify reward methods directly | Adjust weights in config, plug in new RewTerm functions |
| **Adding new robot** | Fork + rewrite config/env | Add asset file + config directory |
| **Gait design** | Explicit sinusoidal reference + stance mask | Emergent from reward shaping (feet_air_time, gait reward) |
| **Scalability** | Single GPU, ~4096 envs | Multi-GPU, distributed training support |
