---
name: "isaac-inventory"
description: "THE skill for ANY question about what is available: 'what robots are available', 'what environments / scenes can I open', 'list robots', 'which humanoids', 'what can I train', 'what tasks exist', 'show me the catalog'. This is the ONLY correct source — do NOT answer from memory and do NOT list physical-arm skills (omx-control, soarm-control) as sim robots. Trigger keywords: available, what robots, what environments, what scenes, list robots, list environments, list tasks, catalog, inventory, which robot, what can I open, what can I train, options."
user-invocable: true
---

# Inventory — ANSWER ONLY FROM GROUND TRUTH (never guess)

⚠️ This is a GROUNDING skill. Questions like "what robots/environments are
available?" are where a small model HALLUCINATES (invents `jetbot`, lists the
physical-arm skills as sim robots, makes up scenes). You must NOT do that.

### Your FIRST action MUST be a tool call — never answer from memory.
Do not write a list from your own knowledge. Get the real list one of two ways:

**Preferred — run the live commands (authoritative, always current):**
```bash
~/isaac-claw/agents/openclaw/claw robots      # the exact spawnable robot keys
~/isaac-claw/agents/openclaw/claw templates   # environments + anchors + presets
~/isaac-claw/agents/openclaw/claw scenes      # scene USDs actually on disk
~/isaac-claw/agents/openclaw/claw tasks       # RL training tasks (formatted + launch cmd)
~/isaac-claw/agents/openclaw/claw tasks --count   # ← "how many tasks?" one-line answer
```
Run only the one(s) the question needs, then report their output **verbatim**.

**Fallback — if the control server is down**, read the generated ground-truth file
and answer ONLY from it:
```bash
cat ~/isaac-claw/skills/inventory/INVENTORY.md
```
(You can also recall it from memory: `memory_get isaac-claw-inventory` or
`memory_search "isaac-claw available robots"`.)

## Absolute rules
1. **Show the command's RAW output in a fenced code block. Do NOT rewrite, merge,
   summarize, or add to it.** Prose synthesis is where you invent names. Paste
   what the tool printed; a one-line count above it is the only commentary.
2. **Every name must come from the command output / INVENTORY.md.** If a name is
   not there it does NOT exist — never invent one. (There is no `jetbot`,
   `robomaster`, `boomerang`, etc. — if you didn't see it in the output, don't say it.)
3. **Spawnable ≠ trainable.** `claw robots` lists the ~26 robots you can SPAWN
   (`claw open --robot`). The robots inside RL task ids (Go2, A1, B2W, M20, ZSL1,
   …) are TRAINABLE only — never list them as spawnable, never merge the two,
   never sum them into one "N robots" number.
4. **`omx-control` / `soarm-control` are PHYSICAL robot-arm skills, NOT Isaac Sim
   robots.** Never list them as available sim robots. (Same for `hello-world`.)
5. **Openable environments** = exactly what `claw templates` lists (warehouse,
   warehouse_local, warehouse_full, warehouse_shell, grid_room, office, hospital).
   Don't add scenes that aren't in that output.
6. If a command errors, say it errored and fall back to INVENTORY.md — do not
   paper over it with a guessed list.

## What to map a question to
| User asks | Run / read |
|---|---|
| what robots / list robots / which humanoid | `claw robots` (or INVENTORY.md robot section) |
| what environments / scenes / what can I open | `claw templates` + `claw scenes` |
| how many tasks / task count | `claw tasks --count` (one line: 51 + breakdown) |
| what can I train / what tasks / locomotion tasks | `claw tasks` (formatted, launch-ready) |
| everything / full inventory | `cat skills/inventory/INVENTORY.md` |

## After it runs
Summarize the real output grouped sensibly (humanoids / quadrupeds / arms;
openable environments vs not-yet-wired), with honest counts. Then offer the
obvious next step, e.g. "want me to `claw open --env warehouse --robot <key>`?"
