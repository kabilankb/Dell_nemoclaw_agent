---
name: "isaac-articulation"
description: "Build and validate a robot articulation for Isaac Sim / Isaac Lab: import from URDF/MJCF, set the articulation root, fix joints and drives, and verify the robot is sim-ready before it is spawned or trained. Use when the user asks to import a robot, fix an articulation, set joints/drives, check why a robot is floppy or exploding, or make a new robot spawnable. Trigger keywords: articulation, articulation root, joint, joints, drive, urdf, mjcf, import robot, rig, floppy robot, exploding robot, fixed joint, make spawnable, add robot to catalog."
user-invocable: true
---

# Articulation — build & validate a sim-ready robot

This is the **task-level** entry for getting a robot into isaac-claw correctly. It
chains the detailed reference skills; open them for the exact APIs.

## When to use
- A new robot needs to come in from URDF/MJCF/CAD.
- A spawned robot is floppy, explodes, sinks through the floor, or won't actuate.
- You need to register a robot so [`../task/SKILL.md`](../task/SKILL.md) can spawn it.

## Pipeline
1. **Convert** the source to USD →
   [`../urdf-mjcf-to-usd-conversion/SKILL.md`](../urdf-mjcf-to-usd-conversion/SKILL.md)
   (pre-expand XACRO; choose RL vs teleop drives; `make_instanceable`).
2. **Validate the articulation** →
   [`../usd-articulation/SKILL.md`](../usd-articulation/SKILL.md)
   (exactly one `ArticulationRootAPI` at the right prim; `FixedJoint` to anchor a
   fixed base; flatten before deploy).
3. **Tune physics** →
   [`../physics-simulation/SKILL.md`](../physics-simulation/SKILL.md)
   (mass/inertia, collision, joint drive stiffness/damping, solver).
4. **Place / measure** →
   [`../usd-pipeline/SKILL.md`](../usd-pipeline/SKILL.md) and
   [`../spatial-reasoning/SKILL.md`](../spatial-reasoning/SKILL.md) for bbox,
   `start_z`, and a collision-free pose.
5. **Register** the robot in `agents/core/assets/catalog.yaml` with its `usd`,
   `drive`, `start_z`, and tags — then it is resolvable by `GET /robots` and
   spawnable via `POST /robot/spawn`.

## Quick checks (fast failure signatures)
| Symptom | Likely cause | Skill |
|---|---|---|
| Robot collapses / floppy | no/duplicate ArticulationRoot, zero drive stiffness | usd-articulation, physics-simulation |
| Explodes on first step | bad mass/inertia, interpenetrating collision | physics-simulation |
| Sinks through floor | no collision API, wrong `start_z` | physics-simulation, spatial-reasoning |
| Won't actuate | drive type mismatch (position vs effort) | urdf-mjcf-to-usd-conversion |
| Not spawnable | missing/invalid catalog `usd:` path | usd-pipeline |

## Validate the result
Before declaring done, run the QA gate
[`../isaac-sim-validator/SKILL.md`](../isaac-sim-validator/SKILL.md) (rejects
deprecated `omni.isaac.core` imports, missing lights, mounting bugs).
