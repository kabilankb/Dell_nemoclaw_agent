---
name: "isaac-inventory"
description: "Answer ANY question about what is available in the NemoClaw sandbox: 'what robots/environments do I have', 'how many tasks', 'list robots', 'what can I train', 'what can I open'. Answer ONLY from the Isaac Control Server — never guess. Trigger keywords: available, what robots, what environments, how many tasks, list robots, list environments, list tasks, catalog, inventory, what can I open, what can I train, options."
user-invocable: true
---

# Inventory — ANSWER ONLY FROM THE CONTROL SERVER (never guess)

You are in a sandbox with no `claw` and no repo. Get the real lists by HTTP from
`http://host.openshell.internal:5561`. Use the **`exec`** tool to run `curl`
(`tool_search` "exec" then `tool_call` if needed). Report the JSON output —
do NOT invent names, and do NOT merge lists.

## Which endpoint for which question
| User asks | Run via exec |
|---|---|
| what robots can I spawn | `curl -s http://host.openshell.internal:5561/robots` |
| what environments / what can I open | `curl -s http://host.openshell.internal:5561/templates` |
| what scenes are built | `curl -s http://host.openshell.internal:5561/scenes` |
| what / how many tasks can I train | `curl -s http://host.openshell.internal:5561/envs` |

## Rules
1. Every name you report MUST come from the curl output. If it is not there, it
   does NOT exist — never invent (no `jetbot`, no made-up scenes).
2. **Spawnable robots** (`/robots`) are DIFFERENT from **trainable robots** (the
   robot names inside `/envs` task ids). Never merge them or sum them into one count.
3. `/templates` lists the openable environments (warehouse, office, hospital,
   grid_room, …). Those are what `open` accepts.
4. For "how many", count the array in the JSON and state the number honestly.

## After it runs
Summarize the JSON grouped sensibly (e.g. humanoids / quadrupeds / arms for robots;
environments for /templates) with honest counts. Then offer the next step, e.g.
"want me to open one — say 'open the warehouse with a G1'?"
