# Listing & launching training tasks

`list_tasks.py` is the fast, offline way to see **what you can train** and the
**exact command to launch it**. It reads `isaac_lab/envs_registry.json` directly —
no Isaac Sim boot, no GPU, no extra deps — so it answers "what tasks are available?"
instantly, and every task is printed next to its ready-to-run `claw train` line.

## Two ways to run it
```bash
# via the claw CLI (recommended — same tool you launch with)
~/isaac-claw/agents/openclaw/claw tasks [filters]

# or directly
python3 ~/isaac-claw/isaac_lab/scripts/list_tasks.py [filters]
```

## The "list → launch" flow (the big advantage)
Listing and launching use the same command, so it's copy-paste:
```bash
claw tasks --humanoid --rough      # browse → each task shows its `launch:` line
claw tasks --launch g1 flat        # print ONLY the command(s) that match
#   → ~/isaac-claw/agents/openclaw/claw train --task RobotLab-Isaac-Velocity-Flat-Unitree-G1-v0
```
Pipe it straight to a shell if you want one match to just run:
```bash
claw tasks --launch g1 flat | head -1 | bash
```

## Filters (all AND-combine)
| Filter | Meaning |
|---|---|
| `<word>` (positional) | substring match on task id / robot (e.g. `g1`, `unitree`, `xbot`) |
| `--humanoid` `--quadruped` `--wheeled` | by category |
| `--flat` `--rough` | by terrain |
| `--special` | only AMP / BeyondMimic / HandStand / manipulation-IL |
| `--count` | one-line totals (e.g. `51 task(s) | category=… terrain=…`) |
| `--launch` | print ONLY the launch command(s), nothing else |
| `--json` | machine-readable (id, robot, category, terrain, kind, launch) |

## What it knows about each task (so the launch command is correct)
| Kind | How it's launched |
|---|---|
| locomotion (`Velocity-Flat/Rough`) | `claw train --task <id>` (backend rsl_rl) |
| amp-dance (`...AMP...`) | `claw train --task <id> --backend skrl` ← AMP needs skrl |
| motion-tracking (`BeyondMimic`), handstand | `claw train --task <id>` |
| manipulation-IL (`LeIsaac` / `PickOrange`) | NOT `claw train` — it's imitation learning → use the **mimicgen** skill |

## Examples
```bash
claw tasks                      # everything, grouped by category, with launch lines
claw tasks --count              # 51 task(s) | category={humanoid:20,...} terrain={flat:26,...}
claw tasks xbot                 # just XBot tasks
claw tasks --quadruped --flat   # quadrupeds on flat terrain
claw tasks --special            # AMP dance, BeyondMimic, handstand, PickOrange
claw tasks --launch a1 handstand
```

> The trainable set is exactly what's in `envs_registry.json` (the `claw train`
> endpoint validates against it). To add more task families, extend that file.
