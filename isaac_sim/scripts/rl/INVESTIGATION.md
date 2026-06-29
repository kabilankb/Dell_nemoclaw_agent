# INVESTIGATION — existing Isaac Lab G1 envs we build on

All paths below are real files in the local checkout `/home/dgx-destro/IsaacLab`.
Findings were obtained by reading source, not by running training.

## 1. G1 velocity locomotion task (the "walk" low level)

Registration: `source/isaaclab_tasks/isaaclab_tasks/manager_based/locomotion/velocity/config/g1/__init__.py`

| gym id | env cfg | rsl_rl runner cfg |
|---|---|---|
| `Isaac-Velocity-Flat-G1-v0` | `flat_env_cfg:G1FlatEnvCfg` | `agents.rsl_rl_ppo_cfg:G1FlatPPORunnerCfg` |
| `Isaac-Velocity-Flat-G1-Play-v0` | `flat_env_cfg:G1FlatEnvCfg_PLAY` | same |
| `Isaac-Velocity-Rough-G1-v0` / `-Play-v0` | `rough_env_cfg:G1RoughEnvCfg(_PLAY)` | `G1RoughPPORunnerCfg` |

Structure (`rough_env_cfg.py` -> base `velocity/velocity_env_cfg.py`; flat overrides terrain/rewards):

- **Robot**: `G1_MINIMAL_CFG` (`isaaclab_assets/.../robots/unitree.py:380`), USD
  `g1_minimal.usd` streamed from `ISAACLAB_NUCLEUS_DIR`. 37 actuated joints
  (legs, torso, arms, fingers). Floating base.
- **Actions** (`velocity_env_cfg.py:112`): one term
  `JointPositionActionCfg(joint_names=[".*"], scale=0.5, use_default_offset=True)`
  -> applied target = `default_joint_pos + 0.5 * raw_action`.
- **Observations / PolicyCfg** (`velocity_env_cfg.py:116-148`, order preserved,
  `concatenate_terms=True`):
  `base_lin_vel(3)`, `base_ang_vel(3)`, `projected_gravity(3)`,
  `velocity_commands(3)`, `joint_pos_rel(37)`, `joint_vel_rel(37)`,
  `last_action(37)`, then `height_scan` — but **flat disables height_scan**
  (`flat_env_cfg.py`: `self.observations.policy.height_scan = None`). So the flat
  policy input is the first 7 terms only.
- **Command** (`velocity_env_cfg.py:94`): `UniformVelocityCommandCfg`
  (`base_velocity`), `heading_command=True`, ranges set in flat cfg to
  `lin_vel_x=(0,1)`, `lin_vel_y=(-0.5,0.5)`, `ang_vel_z=(-1,1)`. The policy
  tracks a commanded base-frame `[vx, vy, wz]` — exactly the hook we use to
  steer the robot to a target.
- **Rewards**: velocity tracking (`track_lin_vel_xy_yaw_frame_exp`,
  `track_ang_vel_z_world_exp`), feet air time / slide, joint-deviation and
  effort penalties, `termination_penalty=-200` (`rough_env_cfg.py:G1Rewards`).
- **rsl_rl runner** (`agents/rsl_rl_ppo_cfg.py`): `G1FlatPPORunnerCfg`,
  `experiment_name="g1_flat"`, `max_iterations=1500`, `num_steps_per_env=24`,
  actor/critic MLP `[256,128,128]`, PPO (clip 0.2, adaptive KL 0.01).

**Checkpoints**: rsl_rl `train.py` writes to
`logs/rsl_rl/<experiment_name>/<YYYY-MM-DD_HH-MM-SS>/` (relative to the Isaac Lab
repo root) — for flat that is `logs/rsl_rl/g1_flat/<timestamp>/model_*.pt`.
`play.py` re-exports the loaded checkpoint to
`<run_dir>/exported/policy.pt` (TorchScript, normalizer baked in) and
`policy.onnx` (`scripts/reinforcement_learning/rsl_rl/play.py:171-173`). We feed
`exported/policy.pt` to the hierarchical script.

## 2. G1 pick-place / loco-manip envs (the "manipulate" low level)

Package: `source/isaaclab_tasks/.../manager_based/locomanipulation/pick_place/`
(registration in its `__init__.py`):

| gym id | env cfg | control mode |
|---|---|---|
| `Isaac-PickPlace-FixedBaseUpperBodyIK-G1-Abs-v0` | `fixed_base_upper_body_ik_g1_env_cfg:FixedBaseUpperBodyIKG1EnvCfg` | **Pink IK upper body, OpenXR teleop**, fixed base |
| `Isaac-PickPlace-Locomanipulation-G1-Abs-v0` | `locomanipulation_g1_env_cfg:LocomanipulationG1EnvCfg` | **pretrained RL lower-body policy + Pink IK upper body**, OpenXR teleop; has a `robomimic_bc` entry point (IL) |

Key facts (verified in the two cfg files + `configs/pink_controller_cfg.py`,
`configs/action_cfg.py`):

- **Control is NOT from-scratch RL manipulation.** It is **Pink IK** teleoperated
  via OpenXR hand-tracking retargeters (`G1TriHandUpperBodyRetargeterCfg`,
  etc.). The `policy` observation group + `robomimic/bc_rnn_low_dim.json` exist
  to record human demos and train **imitation learning (BC-RNN)**, not PPO.
- The **Locomanipulation** env IS hierarchical and is the closest existing
  pattern to our task: its `ActionsCfg` has TWO coexisting action terms over
  disjoint joint sets —
  - `lower_body_joint_pos = AgileBasedLowerBodyActionCfg(...)` which loads a
    **pretrained locomotion policy** (`policy_path=.../Policies/Agile/agile_locomotion.pt`,
    `obs_group_name="lower_body_policy"`) and drives hips/knees/ankles;
  - `upper_body_ik = G1_UPPER_BODY_IK_ACTION_CFG` (Pink IK) drives the arms.
  This confirms the "locomotion-policy-as-action-term + IK-arm" hierarchy is a
  sanctioned Isaac Lab pattern. We reuse the *idea* but (a) substitute our own
  trained `Isaac-Velocity-Flat-G1-v0` policy, (b) use **differential IK** instead
  of Pink IK (no pink/URDF/OpenXR dependency), and (c) sequence walk vs reach in
  time (the warehouse tables are 1.2 m apart in y — out of arm reach — so a
  single simultaneous loco-manip controller cannot reach both; walking is
  required between picks).
- **Grasp mechanism**: there is **NO attach grasp** in either env. Grasping is
  done with the trihand fingers under teleop. Our simplified attach grasp
  (runtime `UsdPhysics.FixedJoint` hand<->cube) is new work.
- **Robot**: both use `G1_29DOF_CFG` (`unitree.py:388`, USD from
  `ISAAC_NUCLEUS_DIR`, has `*_wrist_pitch/roll/yaw_joint` + `*_wrist_yaw_link`
  EE frames and a tri-finger hand). This differs from the locomotion
  `G1_MINIMAL_CFG` arm (shoulder + `elbow_pitch/roll` + 7 finger joints, no
  separate wrist DOFs). **Consequence**: arm joint/EE-link names depend on which
  USD is loaded — handled by `resolve_arm()` in `g1_loco_manip_lib.py`, which
  prints and auto-resolves names at runtime.
- **Scene / object / table**: `FixedBaseUpperBodyIKG1SceneCfg` spawns a
  `PackingTable` USD at `pos=[0,0.55,-0.3]` (kinematic) and a steering-wheel
  rigid object at `[-0.35,0.45,0.6996]`, i.e. ~0.45 m in front of the pelvis —
  confirming arm reach is < ~0.6 m.

## 3. Differential-IK action term (what we use for the arm)

`source/isaaclab/isaaclab/envs/mdp/actions/task_space_actions.py:35`
(`DifferentialInverseKinematicsAction`) +
`.../actions/actions_cfg.py:263` (`DifferentialInverseKinematicsActionCfg`).
Floating-base Jacobian indexing (task_space_actions.py:75-82):
`is_fixed_base` -> `jacobi_body_idx = body_idx-1`, `jacobi_joint_ids = joint_ids`;
floating base -> `jacobi_body_idx = body_idx`, `jacobi_joint_ids = [i+6 ...]`
(first 6 columns are the free-floating base). `g1_loco_manip_lib.ArmIK`
replicates this exactly for the standalone walking script; the registered env
`Isaac-Reach-PickPlace-DiffIK-G1-Abs-v0` uses the official action term.
