# Hierarchical G1 walk + pick-place (RL authoring)

Authoring-only deliverable. **Do not run training on the agent harness** — it
kills GPU/Kit processes (signal 16). Run every command below in **your own
terminal** with the display exported:

```bash
export DISPLAY=:10
```

Layers (hierarchical):
1. **Walk** — a PPO velocity policy (`Isaac-Velocity-Flat-G1-v0`, rsl_rl) drives
   the whole body; a heading planner turns it into "walk to (x,y)".
2. **Manipulate** — differential IK on the G1 right arm reaches the cube; the
   legs keep balancing under the velocity policy at zero command.
3. **Grasp** — simplified attach grasp: a runtime `UsdPhysics.FixedJoint`
   between the hand link and the cube (removed to release). No dexterous contact.

See `INVESTIGATION.md` for how the stock Isaac Lab G1 envs are structured and
exactly which files/lines this builds on.

## Paths / launcher

```bash
ISAAC_LAB=/home/dgx-destro/IsaacLab
PYTHON=/home/dgx-destro/IsaacSim/_build/linux-aarch64/release/python.sh
RL=/home/dgx-destro/warehouse_nemoclaw/warehouse_scene/rl
```

`$ISAAC_LAB/_isaac_sim` is a symlink to that Isaac Sim release, so
`$ISAAC_LAB/isaaclab.sh -p <script>` and `$PYTHON <script>` use the **same**
interpreter. We use `$PYTHON` directly, per project instruction.

## num_envs guidance (DGX GB10, ~120 GB unified)

| task | recommended `--num_envs` | notes |
|---|---|---|
| `Isaac-Velocity-Flat-G1-v0` (train) | **4096** | stock default; comfortable. Push to 8192 if GPU util is low. |
| `Isaac-Velocity-Rough-G1-v0` (train) | 4096 | heavier (terrain + height scan) |
| `-Play-v0` (verify) | 32-50 | cfg default is 50 |
| `Isaac-Reach-PickPlace-DiffIK-G1-Abs-v0` | 1-16 | scripted IK demo |
| `hierarchical_pick_place.py` | 1 | single demo robot |

Before a big run, check headroom (read-only, safe on the harness):
`nvidia-smi --query-gpu=memory.used,memory.total --format=csv`.

---

## STEP 1 — Train the locomotion policy (PPO, rsl_rl)

Run **from the Isaac Lab repo root** so checkpoints land in
`$ISAAC_LAB/logs/rsl_rl/g1_flat/<timestamp>/`:

```bash
cd $ISAAC_LAB
$PYTHON scripts/reinforcement_learning/rsl_rl/train.py \
    --task Isaac-Velocity-Flat-G1-v0 \
    --num_envs 4096 \
    --headless
```

- `experiment_name="g1_flat"`, `max_iterations=1500` (see
  `.../config/g1/agents/rsl_rl_ppo_cfg.py:G1FlatPPORunnerCfg`). ~15-30 min on this
  GPU; reward plateaus well before 1500 iters.
- Resume: add `--resume --load_run <timestamp>` (or `--checkpoint <path/model.pt>`).
- TensorBoard: `tensorboard --logdir $ISAAC_LAB/logs/rsl_rl/g1_flat`.

**No config tweak is needed for "walk to a target."** The flat task already
exposes a base-frame `[vx, vy, wz]` velocity command with `heading_command=True`
(`velocity_env_cfg.py:base_velocity`). The hierarchical script computes that
command from the robot->target vector each step, so any well-trained velocity
policy walks to a goal. (If you want a wider lateral gait, widen
`commands.base_velocity.ranges.lin_vel_y` in `flat_env_cfg.py` before training.)

## STEP 2 — Verify walking + export the checkpoint

`play.py` loads the latest checkpoint, runs it, **and** writes
`<run_dir>/exported/policy.pt` (TorchScript with the normalizer baked in):

```bash
cd $ISAAC_LAB
$PYTHON scripts/reinforcement_learning/rsl_rl/play.py \
    --task Isaac-Velocity-Flat-G1-Play-v0 \
    --num_envs 32
# headless screenshot variant: add --headless --video --video_length 200
```

Locate the export (newest run):

```bash
ls -t $ISAAC_LAB/logs/rsl_rl/g1_flat/*/exported/policy.pt | head -1
```

Keep that path; it is the `--policy` argument in Steps 4-5. (`play.py` resolves
the latest run automatically; pass `--checkpoint` to pin a specific one.)

## STEP 3 — (optional) Differential-IK reach env, manager-based

A clean, registered manager-based env that validates the low-level diff-IK
action + our cube/table layout (single reachable table; fixed base):

- id: `Isaac-Reach-PickPlace-DiffIK-G1-Abs-v0`
- cfg: `$RL/envs/g1_two_table_ik_env_cfg.py` (`G1TwoTableIKEnvCfg`)
- registration: `$RL/envs/__init__.py`

To use it you `import envs` (to register) then `gym.make` and step it with EE
pose commands. The env intentionally carries no reward (control is scripted IK,
not learned). Reach is < ~0.6 m, which is **why** the 1.2 m table-to-table move
needs locomotion — handled in Step 4. The standalone Step-4 script with
`--mode manip_only` exercises the same diff-IK + attach-grasp without gym.

## STEP 4 — Manipulation only (no walking), standalone

Robot stands at the source table, reaches, attach-grasps the cube, lifts, places,
releases. Good for tuning IK/grasp before adding locomotion:

```bash
cd $RL
# In manip_only the robot does not walk/turn, so place the cube in FRONT (+x):
$PYTHON hierarchical_pick_place.py \
    --mode manip_only \
    --policy "$(ls -t $ISAAC_LAB/logs/rsl_rl/g1_flat/*/exported/policy.pt | head -1)" \
    --source_xy 0.45 0.0 --dest_xy 0.45 -0.25 \
    --max_steps 3000
# add --headless for a screenshot run
```

On first launch the script PRINTS `robot.joint_names`, `robot.body_names`, and
the resolved arm EE link / joint ids — confirm they look right (see Risks).

## STEP 5 — Full hierarchical demo (walk + pick + place)

Walk to the SOURCE table -> reach + attach-grasp -> lift -> walk to the DEST
table -> place + release. Defaults match the warehouse layout (tables at
y = -1.2 / +1.2, top z = 0.62, cube 0.16 m):

```bash
cd $RL
$PYTHON hierarchical_pick_place.py \
    --policy "$(ls -t $ISAAC_LAB/logs/rsl_rl/g1_flat/*/exported/policy.pt | head -1)" \
    --source_xy 0.0 -1.2 --dest_xy 0.0 1.2 \
    --table_top_z 0.62 --cube_size 0.16 \
    --max_steps 8000
# headless screenshot: add --headless
```

Every loop is bounded by `--max_steps` and `simulation_app.is_running()`, so
Ctrl-C / window-close stops it cleanly.

### Visualizing in the warehouse (optional, NOT for training)

Training and this demo use a lightweight flat scene (two box tables + cube). To
showcase the result in `warehouse_scene/warehouse.usd`, drive the same FSM/policy
against that stage with the `isaac-sim-remote` skill (port 8226) or by adapting
`design_scene()` to load the warehouse USD instead of spawning boxes — keep the
robot start at world (6, 0) and the tables at (6, ±1.2). The streamed warehouse
is far too heavy to clone thousands of times, hence the separate training scene.

---

## Files in this deliverable

- `INVESTIGATION.md` — findings + exact source citations.
- `README.md` — this file.
- `g1_loco_manip_lib.py` — shared helpers: `LocomotionPolicy` (obs rebuild +
  TorchScript load), `ArmIK` (floating-base differential IK), `AttachGrasp`
  (FixedJoint), scene/table/cube cfg builders.
- `hierarchical_pick_place.py` — the orchestration FSM (Steps 4-5).
- `envs/g1_two_table_ik_env_cfg.py` + `envs/__init__.py` — registered
  manager-based diff-IK env (Step 3).

## Risks / assumptions (read before running)

1. **Two G1 USDs, two arm kinematics.** The locomotion policy trains on
   `G1_MINIMAL_CFG` (USD `g1_minimal.usd`: shoulder + `elbow_pitch/roll` +
   finger joints, **no wrist DOFs**). The manager env (Step 3) uses
   `G1_29DOF_CFG` (`g1.usd`: adds `*_wrist_*_joint` and `*_wrist_yaw_link`).
   `resolve_arm()` auto-resolves the EE link/joints for whichever USD loads and
   the script prints them — if the printed EE link is not the hand you expect,
   pass a different side or adjust the `ee_candidates` list in
   `g1_loco_manip_lib.py`. The minimal arm has only ~5 DOF, enough for
   positional IK (the script uses `command_type="position"`).
2. **Standing-while-reaching stability.** During reach the velocity policy is
   commanded zero base velocity and only the arm targets are overridden. On flat
   ground the G1 holds its crouched default stance, but a large arm excursion can
   perturb balance. If it tips, reduce `--cube_size`/reach, lower the table, or
   add a short "settle" by raising the `REACH_*` `state_timer` thresholds.
3. **Attach-grasp prim path.** `AttachGrasp` resolves the hand rigid-body prim by
   name under `/World/Robot`. If your robot root prim path differs, update the
   call in `hierarchical_pick_place.py`.
4. **Reach vs distance.** Fixed-base arm reach is < ~0.6 m. The standalone demo
   defaults put the cube within reach of the approach pose; if you change
   `APPROACH_STANDOFF` make sure the cube stays reachable from the stand point.
5. **Not executed here.** All APIs were verified by reading the Isaac Lab
   checkout, not by running (harness GPU limitation). Expect to iterate on IK
   gains (`ik_method="dls"`), standoff, and timer thresholds on first real run.
