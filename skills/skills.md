---
name: isaac-claw-skills
description: >
  MASTER skill router for isaac-claw. Load this FIRST. It is the model-facing
  table of contents: every specialized skill is listed with its purpose,
  trigger keywords, and the control-server endpoint or script it drives. A local
  model (Gemma, Nemotron, …) reads this to decide WHICH skill to invoke and how
  to chain them. Trigger keywords: skill, help, what can you do, list skills,
  open scene, spawn robot, train, teleop, record demos, tune policy, articulate.
user-invocable: true
---

# isaac-claw — Master Skill Router

You are driving **Isaac Sim** (the simulator) and **Isaac Lab** (the RL/IL
framework) from a TUI. You do not call the simulator directly — you call the
**Isaac Control Server** (host API, default `http://host.openshell.internal:5561`
from a sandbox, `http://localhost:5561` on host). Every skill below ultimately
turns a user sentence into one of those HTTP calls or a launch script.

## How to use this file
1. Read the user's sentence. Match it against the **Trigger keywords** column.
2. Open that skill's `SKILL.md` for the exact command grammar / parameters.
3. If a task needs several skills, **chain** them in the order under "Pipelines".
4. For anything with tunable hyperparameters, route through
   [`../policies/policy_skill.md`](../policies/policy_skill.md).

## Control surface (what every skill calls)
| Verb | Endpoint | Used by |
|---|---|---|
| list tasks / scenes / robots | `GET /envs` `/scenes` `/robots` | all |
| bring up the sim on a scene | `POST /sim/launch {scene}` | scene, task |
| load a USD into a running sim | `POST /scene/load {scene}` | scene |
| spawn a robot from the catalog | `POST /robot/spawn {robot,x,y,z}` | scene, articulation |
| start / stop / watch RL | `POST /train /play /eval /stop`, `GET /status /logs` | training |
| arbitrary sim python | `POST /exec {code}` | remote, sensor, rendering |

---

## Skill catalog

### A. Operate the simulator (Goal 1 & 2 — open env + robot from a prompt)
| Skill | Purpose | Trigger keywords |
|---|---|---|
| [`task/SKILL.md`](task/SKILL.md) | **Entry skill** — turn "open the warehouse with a G1" into scene-launch + robot-spawn calls; pick the right scene & robot | open, load scene, set up, environment, warehouse, spawn, add robot, bring up the sim |
| [`isaac-sim-remote/SKILL.md`](isaac-sim-remote/SKILL.md) | Drive a *running* sim over the python_server socket (8226) → `POST /exec` | run code, screenshot, inspect prim, step sim, remote control |
| [`isaac-sim-orchestrator/SKILL.md`](isaac-sim-orchestrator/SKILL.md) | Top-level dispatcher for full sim builds; env-var contract | build a sim, orchestrate, full scene from scratch |
| [`isaac-sim-headless-deployment/SKILL.md`](isaac-sim-headless-deployment/SKILL.md) | `--no-window` launch modes, SimulationApp batch | headless, no window, batch, server render |

### B. Move / manipulate the robot (teleop, control)
| Skill | Purpose | Trigger keywords |
|---|---|---|
| [`teleop/SKILL.md`](teleop/SKILL.md) | Control an SO101 arm for pick-and-place; JSON delta-pose commands + `isaaclab-send/pick/place/detect` | pick, place, grab, move arm, gripper, forward/back/left/right, find orange, vision |
| [`manipulation-ik/SKILL.md`](manipulation-ik/SKILL.md) | Differential IK, grasp frames, FixedJoint grasping | reach, ik, grasp, end-effector, joint target |

### C. Train a policy (RL) — Goal 3 lives here
| Skill | Purpose | Trigger keywords |
|---|---|---|
| [`training/SKILL.md`](training/SKILL.md) | Train/list/status/stop locomotion policies on Isaac Lab via `POST /train` | train, training, list envs, start/stop training, status, logs, G1, XBot, locomotion, CusRL, RSL-RL |
| [`../policies/policy_skill.md`](../policies/policy_skill.md) | **Hyperparameter control panel** for RSL-RL, rl_games, skrl, SB3, robomimic | tune, hyperparameter, learning rate, reward weight, entropy, num_envs, fine-tune |

### D. Imitation learning / synthetic data (record → annotate → generate → train)
| Skill | Purpose | Trigger keywords |
|---|---|---|
| [`mimicgen/SKILL.md`](mimicgen/SKILL.md) | Record demos, annotate, generate datasets, convert HDF5↔LeRobot | record demo, demonstration, mimic, annotate, generate dataset, lerobot, bc, act, diffusion policy |
| [`data-collection-sim/SKILL.md`](data-collection-sim/SKILL.md) | Static-scene Replicator SDG (BasicWriter, PoseWriter, Kitti) | synthetic data, sdg, replicator, write images, labels |
| [`mobility-gen/SKILL.md`](mobility-gen/SKILL.md) | Mobile-robot SDG: record trajectories → replay + render | mobility gen, trajectory, mobile sdg, record and replay |

### E. Build & validate assets (articulation, USD, physics)
| Skill | Purpose | Trigger keywords |
|---|---|---|
| [`articulation/SKILL.md`](articulation/SKILL.md) | **Task entry** — import + validate + register a sim-ready robot (chains the skills below) | articulation, import robot, fix joints, floppy/exploding robot, make spawnable |
| [`urdf-mjcf-to-usd-conversion/SKILL.md`](urdf-mjcf-to-usd-conversion/SKILL.md) | URDF/MJCF → sim-ready USD; every new robot starts here | import robot, urdf, mjcf, convert to usd |
| [`usd-articulation/SKILL.md`](usd-articulation/SKILL.md) | Validate multi-link articulation, ArticulationRoot, FixedJoint | articulation, joints, articulation root, flatten |
| [`physics-simulation/SKILL.md`](physics-simulation/SKILL.md) | PhysX/Newton scene config, mass/collision/joint drives | physics, collision, mass, ccd, solver, contact |
| [`usd-pipeline/SKILL.md`](usd-pipeline/SKILL.md) | Asset discovery, bbox/shader measurement, placement | usd, asset, bbox, material, placeholder |
| [`usd-composition-architecture/SKILL.md`](usd-composition-architecture/SKILL.md) | Layered USD (root + physics + appearance payloads) | layers, payload, composition, reference |
| [`spatial-reasoning/SKILL.md`](spatial-reasoning/SKILL.md) | Transform math, collision-free grids, A*, packing, standards | transform, position, layout, grid, pack, where to place |

### F. Sensors, cameras, rendering, navigation, ROS
| Skill | Purpose | Trigger keywords |
|---|---|---|
| [`isaac-sim-sensor/SKILL.md`](isaac-sim-sensor/SKILL.md) | RGB/depth/seg, LiDAR, IMU, contact; vendor LiDAR catalog | sensor, lidar, depth, imu, camera data, scan |
| [`isaac-camera/SKILL.md`](isaac-camera/SKILL.md) | UsdGeomCamera, intrinsics, AOVs, distortion | camera, intrinsics, fov, lens, aov |
| [`isaac-sim-rendering/SKILL.md`](isaac-sim-rendering/SKILL.md) | Headless RT2 / PathTracing production rendering, ACES | render, lighting, ray tracing, path tracing, photoreal |
| [`navigation-primitives/SKILL.md`](navigation-primitives/SKILL.md) | OccupancyMap, A*, robot footprints, kinematics | navigation, path planning, occupancy, footprint |
| [`isaac-sim-robot-navigation/SKILL.md`](isaac-sim-robot-navigation/SKILL.md) | Runtime nav in scripts (RL/baked/per-frame) | drive robot, navigate, waypoint, move base |
| [`occupancy-map/SKILL.md`](occupancy-map/SKILL.md) | ROS-compatible map.yaml from USD warehouses | occupancy map, map.yaml, nav2 map |
| [`isaac-sim-ros2-bridge/SKILL.md`](isaac-sim-ros2-bridge/SKILL.md) | OmniGraph ROS 2 nodes, Nav2, multi-robot | ros, ros2, nav2, bridge, topic, namespace |

### G. Quality, debugging, meta
| Skill | Purpose | Trigger keywords |
|---|---|---|
| [`isaac-sim-validator/SKILL.md`](isaac-sim-validator/SKILL.md) | Final QA gate (black frames, deprecated imports, lighting) | validate, qa, check, is it correct |
| [`isaac-sim-troubleshooting/SKILL.md`](isaac-sim-troubleshooting/SKILL.md) | Kit hang/freeze/perf reference | hang, freeze, slow, crash, stuck |
| [`profile-isaac-sim/SKILL.md`](profile-isaac-sim/SKILL.md) | Benchmark + Tracy profiling, frame-time diff | profile, benchmark, fps, frame time, optimize |
| [`validation-diff-gifs/SKILL.md`](validation-diff-gifs/SKILL.md) | Pixel-diff GIFs vs golden for capture failures | diff, golden, image mismatch, why different |
| [`meta-skills/SKILL.md`](meta-skills/SKILL.md) | How to compose & author skills | how do skills work, compose, author a skill |
| [`skill-distillation/SKILL.md`](skill-distillation/SKILL.md) | Always-on: capture what you learned | remember this, distill, save learning |

---

## Pipelines (how to chain)

**Open an environment with a robot (Goal 2):**
`task` → `POST /sim/launch {scene}` → (sim up) → `POST /robot/spawn {robot}` → confirm with `isaac-sim-remote` screenshot.

**Train a locomotion policy:**
`training` (`GET /envs` → pick task) → `policy_skill` (set hyperparameters) → `POST /train` → poll `GET /status` + `GET /logs` → `POST /play` to watch.

**Collect imitation data → train a manipulation policy:**
`teleop` (record with `--record`) → `mimicgen` (annotate → generate dataset → convert to LeRobot) → train via LeRobot/robomimic (`policy_skill` → robomimic.md).

**Bring in a brand-new robot:**
`articulation` (task entry) → `urdf-mjcf-to-usd-conversion` → `usd-articulation` (validate) → `physics-simulation` (tune) → add to `agents/core/assets/catalog.yaml` → then it is spawnable via `task`.

---
*Skill count: 28 specialized skills + this router. New skills: drop a folder with a
`SKILL.md` (frontmatter: name, description with trigger keywords, user-invocable)
and add one row above.*
