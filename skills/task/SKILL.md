---
name: "isaac-open-environment"
description: "THE skill for opening a simulation scene and putting a robot in it. Use for ANY request like 'open the warehouse', 'load a scene', 'spawn/add a robot', 'open the warehouse with a Unitree G1', 'bring up the sim'. This is the correct skill for these — do NOT use isaac-sim-orchestrator or mobility-gen for opening a scene or spawning a robot. Trigger keywords: open, open the warehouse, open the office, open the hospital, open the grid room, load scene, set up environment, bring up the sim, spawn robot, add robot, put a robot in, show me the robot, warehouse, warehouse_full, office, hospital, grid_room, unitree, g1, h1, go2, carter, spot, digit."
user-invocable: true
---

# Open a scene + robot — RUN ONE COMMAND

⚠️ This is an EXECUTE skill, not a planning skill. Do **not** describe a plan,
do **not** delegate to other skills, do **not** invent file names. **Run the
single shell command below using your shell/exec tool**, then report its output.

### Your FIRST action MUST be a shell tool call — output no prose before it.
Do not write "Plan:", do not mention isaac-sim-orchestrator. Immediately call your
shell/exec tool with the `claw open` command. Example of the ONLY correct behavior:

> User: *open the warehouse with a Unitree G1*
> Assistant: *(calls shell tool)* `~/isaac-claw/agents/openclaw/claw open --env warehouse --robot unitree_g1 --gui`
> Assistant: *(after it returns)* "Warehouse is open in a window; spawned unitree_g1 at the pick station (6,0,0.74)."

If you find yourself writing a sentence that starts with "I will" or "Plan" or
"Based on", STOP — you are doing it wrong. Call the shell tool instead.

## STANDARD EXECUTION TEMPLATE  (always emit exactly ONE of these shapes)
```bash
# A. environment + robot (the normal case)
~/isaac-claw/agents/openclaw/claw open --env <ENV> [--robot <ROBOT>] [--anchor <ANCHOR>] --gui

# B. a named preset bundle (env + robot(s) already chosen)
~/isaac-claw/agents/openclaw/claw open --template <TEMPLATE> --gui
```

**Slots — fill from the user's words, nothing invented:**
| Slot | Allowed values | Rule |
|---|---|---|
| `<ENV>` | `warehouse` · `warehouse_full` · `warehouse_shell` · `warehouse_local` · `office` · `hospital` · `grid_room` | default `warehouse`; if unsure run `claw templates` |
| `<ROBOT>` | a key from `claw robots` (e.g. `unitree_g1`, `spot`, `nova_carter`, `digit_v4`) | **omit the whole `--robot` flag if the user named no robot** — don't guess one |
| `<ANCHOR>` | a named spawn point of that env | optional; omit to use the env's default |
| `<TEMPLATE>` | `warehouse_g1` · `warehouse_fleet` | use only when the user asks for that preset |
| `--gui` | — | **ALWAYS include**; drop only if the user explicitly says "headless" / "for training" |

**Procedure:** (1) map the sentence → slots, (2) emit the single command, (3) report
what it printed. One command does everything: starts the control server if needed,
launches a persistent Isaac Sim, and the robot spawns automatically when the sim is
READY (~1-2 min; cloud scenes — office/hospital/grid_room — stream and take longer,
so check `claw status` / `claw logs`). Robot height (catalog) and spawn position
(env anchor) are filled in for you — no pose math, same robot works in any env.

## Fill the arguments from the user's words
**ENV** — match the user's words to ANY of these environments (run
`~/isaac-claw/agents/openclaw/claw templates` for the live list — never invent one):
- "warehouse" → `warehouse` (default)   ·   "full warehouse" → `warehouse_full`   ·   "warehouse shell" → `warehouse_shell`
- "office" → `office`   ·   "hospital" → `hospital`   ·   "empty / grid / ground" → `grid_room`
- If the user names an environment you don't see here, run `claw templates` and
  pick the closest key; if there's no match, say so — do not fall back to warehouse silently.

**TEMPLATE** (optional shortcut) — a preset bundle:
- "warehouse with a G1" → `warehouse_g1`   ·   "warehouse fleet" → `warehouse_fleet`

**ROBOT** — match the user's words to a catalog key (these are the real keys):
- "Unitree G1" / "G1" → `unitree_g1`   ·   "Unitree H1" / "H1" → `unitree_h1`
- "Carter" / "Nova Carter" → `nova_carter`   ·   "Spot" → `spot`   ·   "Anymal" → `anymal`
- "Franka" → `franka_panda`   ·   "Digit" → `digit_v4`
- If unsure, first run `~/isaac-claw/agents/openclaw/claw robots` and pick the
  closest key. Never invent a robot name or USD path.

Optional **--z** is the standing height for legged robots (G1 ≈ `0.74`). Omit
x/y/z to use sensible defaults.

## Examples (copy the pattern exactly)
  | User says | You run |
  |---|---|
  | open the warehouse with a Unitree G1 | `~/isaac-claw/agents/openclaw/claw open --env warehouse --robot unitree_g1 --gui` |
  | open the warehouse with a G1 (preset) | `~/isaac-claw/agents/openclaw/claw open --template warehouse_g1 --gui` |
  | open the warehouse | `~/isaac-claw/agents/openclaw/claw open --env warehouse --gui` |
  | put a Spot in the warehouse at the dock | `~/isaac-claw/agents/openclaw/claw open --env warehouse --robot spot --anchor dock --gui` |
  | open the warehouse with the fleet | `~/isaac-claw/agents/openclaw/claw open --template warehouse_fleet --gui` |
  | open the office with a Spot | `~/isaac-claw/agents/openclaw/claw open --env office --robot spot --gui` |
  | open the hospital with a Carter | `~/isaac-claw/agents/openclaw/claw open --env hospital --robot nova_carter --gui` |
  | open an empty grid room with a G1 | `~/isaac-claw/agents/openclaw/claw open --env grid_room --robot unitree_g1 --gui` |
  | open the full warehouse with a Digit | `~/isaac-claw/agents/openclaw/claw open --env warehouse_full --robot digit_v4 --gui` |
  | open the warehouse headless (for training) | `~/isaac-claw/agents/openclaw/claw open --env warehouse --robot unitree_g1` |

## After it runs
Report what the command printed: whether the sim came up and the robot spawned
(`spawned <robot> at (...)`), or the exact error line. If it errors with the
server/sim not coming up, run `~/isaac-claw/agents/openclaw/claw up` once and
retry the open command. That is the whole procedure.
