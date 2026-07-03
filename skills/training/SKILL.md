---
name: "isaaclab-training"
description: "THE skill for RL training on Isaac Lab: train a locomotion policy, list training tasks, check status, view logs, or stop training. Use for 'train a G1', 'train XBot on rough terrain', 'list training tasks', 'how's training going', 'stop training'. Trigger keywords: train, training, start training, stop training, training status, training logs, list tasks, locomotion, policy, RL, XBot, G1, H1, Go2, A1, humanoid, quadruped, wheeled, flat, rough, AMP, dance, motion priors, BeyondMimic, mimic, handstand, manipulation, rsl_rl, cusrl, skrl, num_envs, iterations, seed, gui, headless, watch training, show training, in a window."
user-invocable: true
---

# Isaac Lab Training — RUN ONE COMMAND

⚠️ This is an EXECUTE skill. Do **not** describe a plan and do **not** invent task
ids. **Run the single command below with your shell/exec tool**, then report its
output. Every command goes through `claw` (the same CLI as opening scenes).

## STANDARD EXECUTION TEMPLATE  (emit exactly ONE of these)
```bash
# start training
~/isaac-claw/agents/openclaw/claw train --task <TASK_ID> [--backend <BACKEND>] [--gui] [--num_envs <N>]

# inspect / control a run
~/isaac-claw/agents/openclaw/claw status        # is a job running + elapsed
~/isaac-claw/agents/openclaw/claw logs           # tail the training log
~/isaac-claw/agents/openclaw/claw close          # STOP training, free the GPU
```

### Headless (default) vs GUI — pick from the user's words
- **No window phrase → omit `--gui`** (DEFAULT): headless, fast, 4096 envs. This is
  what "train a G1" means. Best for real training.
- **"with gui" / "watch" / "show me it training" / "in a window" → add `--gui`**:
  opens a visible window and uses few envs (default 64) so it's watchable — slower,
  for demos/debugging, needs a display. Override the count with `--num_envs <N>`.

**Slots — fill from the user's words, nothing invented:**
| Slot | Allowed values | Rule |
|---|---|---|
| `<TASK_ID>` | a real id from `claw tasks` (51 tasks) | NEVER invent. To browse + get the launch line, run `claw tasks [--humanoid\|--quadruped\|--special\|<word>]` (see `isaac_lab/scripts/LIST_TASKS.md`) |
| `<BACKEND>` | `rsl_rl` (default, **all tasks**) · `cusrl` (most) · `skrl` (AMP only) | omit for `rsl_rl` |
| `<N>` | env count | omit for `4096` |

Optional: `--max_iterations <N>`, `--seed <N>`, `--algorithm <amp>` (skrl only).

### Backend support is PER-TASK (don't guess)
- **`rsl_rl` works for every task** — it's the safe default. Use it unless asked otherwise.
- `cusrl` works for most locomotion tasks.
- `skrl` is NOT available for plain locomotion — it's only for special tasks. The
  AMP dance MUST be `--backend skrl --algorithm AMP` (it registers `skrl_amp_cfg_entry_point`,
  not the PPO one). Don't offer `--backend skrl` for a Velocity task — it will error.
- When in doubt, the launch line printed by `claw tasks` already has the right
  backend/algorithm for that task — just run it.

## CRITICAL — one GPU job at a time
Training and a running sim are **mutually exclusive** (single GPU). If a sim is up,
`claw train` returns **409**. So if the user has a scene open, run `claw close`
FIRST, then `claw train`. Likewise only one training run at a time — check
`claw status` before starting another.

## Training varieties (the 51 tasks are NOT all the same — run `claw envs`)
Isaac Lab / robot_lab here supports several training types. Pick the right id AND
the right backend:

- **Locomotion RL (most tasks)** — `...-Velocity-Flat-...` / `...-Velocity-Rough-...`
  across **humanoid / quadruped / wheeled** robots. Backend `rsl_rl` (default) or `cusrl`.
- **Motion / style RL (special — exact ids, note the backend):**
  - AMP dance (G1): `RobotLab-Isaac-G1-AMP-Dance-Direct-v0` — **use `--backend skrl`**
    (adversarial motion priors live in skrl; rsl_rl can't run it).
  - BeyondMimic (G1): `RobotLab-Isaac-BeyondMimic-Flat-Unitree-G1-v0` — motion tracking.
  - Handstand (A1): `RobotLab-Isaac-Velocity-Flat-HandStand-Unitree-A1-v0` (+ `-Rough-`).
- **Manipulation / imitation learning** — `LeIsaac-SO101-PickOrange-v0` is demo-driven.
  For recording demos + BC / ACT / diffusion training, that's a DIFFERENT skill:
  use **mimicgen**, and tune via `policies/policy_skill.md` → `robomimic.md`.

If the user asks for something that isn't locomotion (dance, mimic, manipulation,
in-hand), match it to the special ids above or to mimicgen — don't force it into a
Velocity task. Always confirm the exact id with `claw envs`.

## Picking the TASK_ID (ground it in `claw envs`)
Task ids look like `RobotLab-Isaac-Velocity-<Flat|Rough>-<Robot>-v0`. `Flat` =
flat ground, `Rough` = rough terrain. Map the user's words, then VERIFY against
`claw envs` (do not guess a robot that isn't in the list):

| User says | Task id |
|---|---|
| XBot / XBot flat | `RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0` |
| XBot rough | `RobotLab-Isaac-Velocity-Rough-RobotEra-Xbot-v0` |
| G1 / Unitree G1 | `RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0` |
| G1 rough | `RobotLab-Isaac-Velocity-Rough-Unitree-G1-v0` |
| H1 / Unitree H1 | `RobotLab-Isaac-Velocity-Flat-Unitree-H1-v0` |
| Go2 | `RobotLab-Isaac-Velocity-Flat-Unitree-Go2-v0` |
| A1 | `RobotLab-Isaac-Velocity-Flat-Unitree-A1-v0` |
| GR1T1 / GR1T2 | `RobotLab-Isaac-Velocity-Flat-FFTAI-GR1T1-v0` / `...-GR1T2-v0` |

If the user names a robot not above, run `claw envs` and pick the matching id; if
there is none, say so — do not substitute a different robot.

## Examples (copy the pattern exactly)
| User says | You run |
|---|---|
| train a G1 | `~/isaac-claw/agents/openclaw/claw train --task RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0` |
| train a G1 and let me watch / with gui | `~/isaac-claw/agents/openclaw/claw train --task RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0 --gui` |
| watch G1 train with 32 envs | `~/isaac-claw/agents/openclaw/claw train --task RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0 --gui --num_envs 32` |
| train G1 on rough terrain | `~/isaac-claw/agents/openclaw/claw train --task RobotLab-Isaac-Velocity-Rough-Unitree-G1-v0` |
| train XBot with cusrl, 2048 envs | `~/isaac-claw/agents/openclaw/claw train --task RobotLab-Isaac-Velocity-Flat-RobotEra-Xbot-v0 --backend cusrl --num_envs 2048` |
| train the G1 dance (AMP) | `~/isaac-claw/agents/openclaw/claw train --task RobotLab-Isaac-G1-AMP-Dance-Direct-v0 --backend skrl --algorithm AMP` |
| train the A1 handstand | `~/isaac-claw/agents/openclaw/claw train --task RobotLab-Isaac-Velocity-Flat-HandStand-Unitree-A1-v0` |
| list training tasks | `~/isaac-claw/agents/openclaw/claw tasks` |
| list humanoid tasks on rough terrain | `~/isaac-claw/agents/openclaw/claw tasks --humanoid --rough` |
| what G1 tasks can I train | `~/isaac-claw/agents/openclaw/claw tasks g1` |
| how's training going | `~/isaac-claw/agents/openclaw/claw status` then `~/isaac-claw/agents/openclaw/claw logs` |
| stop training | `~/isaac-claw/agents/openclaw/claw close` |

## Hyperparameters
For learning rate, reward weights, entropy, gamma, minibatch, etc., DON'T guess —
route to the tuning control panel: `~/isaac-claw/policies/policy_skill.md`
(per-framework knob blocks for rsl_rl / cusrl / skrl / sb3 / robomimic).

## After it runs
Report what the command printed: the started job (task + backend + pid) or the
error line. Training is headless and long-running — tell the user to watch it with
`claw status` / `claw logs`, and stop with `claw close`. (Watching a trained policy
afterwards is a separate "play" step run from the Isaac Lab scripts, not `claw`.)
