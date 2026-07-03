#!/usr/bin/env python3
"""list_tasks.py — list the trainable Isaac Lab tasks WITH their launch command.

Dependency-free (stdlib only) and offline: it reads isaac_lab/envs_registry.json,
so it works WITHOUT booting Isaac Sim or any GPU env (unlike tools/list_envs.py).
Its whole point is "list, then launch": every task is printed next to the exact
`claw train` command that runs it — copy/paste and go.

USAGE
  python3 list_tasks.py                     # all tasks, grouped, with launch cmds
  python3 list_tasks.py g1                  # filter: any task matching "g1"
  python3 list_tasks.py --humanoid          # filter by category
  python3 list_tasks.py --quadruped --rough # combine filters (category + terrain)
  python3 list_tasks.py --special           # only AMP / BeyondMimic / HandStand / IL
  python3 list_tasks.py --launch g1 flat    # print ONLY the launch command(s) that match
  python3 list_tasks.py --count             # one-line totals
  python3 list_tasks.py --json              # machine-readable

Filters: a positional word is a substring match on id/robot. Flags:
  --humanoid --quadruped --wheeled --flat --rough --special   (all AND-combine)
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CLAW_DIR = os.environ.get("ISAAC_CLAW_DIR", os.path.dirname(HERE))  # isaac_lab/.. = repo
REGISTRY = os.path.join(CLAW_DIR, "isaac_lab", "envs_registry.json")
CLAW = "~/isaac-claw/agents/openclaw/claw"


def kind_and_backend(task_id):
    """Classify a task and pick the backend its launch command needs."""
    tid = task_id
    if "AMP" in tid:
        return "amp-dance", "skrl"          # adversarial motion priors live in skrl
    if "BeyondMimic" in tid:
        return "motion-tracking", "rsl_rl"
    if "HandStand" in tid:
        return "handstand", "rsl_rl"
    if tid.startswith("LeIsaac") or "PickOrange" in tid or "Mimic" in tid:
        return "manipulation-IL", None      # imitation learning → mimicgen skill
    return "locomotion", "rsl_rl"


def launch_cmd(task_id):
    kind, backend = kind_and_backend(task_id)
    if kind == "manipulation-IL":
        return "# imitation learning — use the 'mimicgen' skill (record→annotate→train), not `claw train`"
    if kind == "amp-dance":                       # AMP registers skrl_amp_cfg_entry_point only
        return f"{CLAW} train --task {task_id} --backend skrl --algorithm AMP"
    flag = f" --backend {backend}" if backend and backend != "rsl_rl" else ""
    return f"{CLAW} train --task {task_id}{flag}"


def load():
    if not os.path.exists(REGISTRY):
        sys.exit(f"registry not found: {REGISTRY}")
    return json.load(open(REGISTRY)).get("environments", [])


def matches(e, args):
    tid, robot = e.get("id", ""), e.get("robot", "")
    cat, terr = e.get("category", ""), e.get("terrain", "")
    kind, _ = kind_and_backend(tid)
    if args.humanoid and cat != "humanoid":
        return False
    if args.quadruped and cat != "quadruped":
        return False
    if args.wheeled and cat != "wheeled":
        return False
    if args.flat and terr != "flat":
        return False
    if args.rough and terr != "rough":
        return False
    if args.special and kind == "locomotion":
        return False
    for term in args.terms:
        if term.lower() not in (tid + " " + robot).lower():
            return False
    return True


def main():
    p = argparse.ArgumentParser(add_help=True, description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("terms", nargs="*", help="substring filter on task id / robot")
    for f in ("humanoid", "quadruped", "wheeled", "flat", "rough", "special"):
        p.add_argument(f"--{f}", action="store_true")
    p.add_argument("--launch", action="store_true", help="print ONLY matching launch command(s)")
    p.add_argument("--count", action="store_true", help="one-line totals only")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args()

    envs = load()
    sel = [e for e in envs if matches(e, args)]

    if args.json:
        print(json.dumps([{**e, "kind": kind_and_backend(e["id"])[0],
                           "launch": launch_cmd(e["id"])} for e in sel], indent=2))
        return 0

    if args.count:
        from collections import Counter
        cat = Counter(e.get("category", "?") for e in sel)
        terr = Counter(e.get("terrain", "?") for e in sel)
        print(f"{len(sel)} task(s)  |  category={dict(cat)}  terrain={dict(terr)}")
        return 0

    if args.launch:
        if not sel:
            print("# no task matched your filter — run without --launch to browse"); return 1
        for e in sel:
            print(launch_cmd(e["id"]))
        return 0

    if not sel:
        print("no task matched. Try: python3 list_tasks.py            (all)\n"
              "                     python3 list_tasks.py --humanoid  (by category)")
        return 1

    # grouped, human-readable, each with its launch command
    groups = {}
    for e in sel:
        groups.setdefault(e.get("category", "other"), []).append(e)
    print(f"# {len(sel)} trainable task(s)  (run any line under 'launch:')\n")
    for cat in sorted(groups):
        print(f"== {cat} ==")
        for e in sorted(groups[cat], key=lambda x: x["id"]):
            kind, _ = kind_and_backend(e["id"])
            tag = "" if kind == "locomotion" else f"  [{kind}]"
            print(f"  {e['robot']:22s} {e.get('terrain',''):6s}{tag}")
            print(f"      {e['id']}")
            print(f"      launch: {launch_cmd(e['id'])}")
        print()
    print("Tip: filter (e.g. `list_tasks.py --humanoid --rough`) or `--launch g1 flat` "
          "to print just the command.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
