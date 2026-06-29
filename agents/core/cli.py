"""Headless CLI for the orchestrator — same loop as the UI, no browser.

Examples:
  python -m agent_orchestrator.cli "place 4 franka arms on tables" --dry-run
  python -m agent_orchestrator.cli "train cartpole for 200 iters" --layer 4
  python -m agent_orchestrator.cli --classify "write a PPO reward for spot"
"""
from __future__ import annotations

import argparse
import asyncio

from . import router
from .config import SETTINGS
from .state import OrchestratorState
from .orchestrate import orchestrate


async def _run(args):
    state = OrchestratorState()
    forced = args.layer
    allow = args.allow_execution or SETTINGS.allow_execution_default
    async for ev in orchestrate(
        args.command, state, dry_run=args.dry_run,
        allow_execution=allow, forced_layer=forced,
        backend=args.backend, supervise=not args.no_supervise,
    ):
        if ev.kind == "verdict":
            print(f"[L0 MASTER] {ev.payload.one_line()}", flush=True)
        elif ev.kind in ("text", "tool", "reroute", "error"):
            tag = ev.kind.upper()
            extra = f" → {ev.target}" if ev.kind == "reroute" else ""
            who = "L0 MASTER" if ev.layer == 0 else f"L{ev.layer} {tag}"
            print(f"[{who}{extra}] {ev.text}", flush=True)
    print("\n--- log ---")
    print(state.log_text())


def main():
    ap = argparse.ArgumentParser(description="Isaac multi-layer agent orchestrator")
    ap.add_argument("command", nargs="?", default="", help="natural-language command")
    ap.add_argument("--layer", type=int, choices=[1, 2, 3, 4], default=None,
                    help="force a layer instead of auto-routing")
    ap.add_argument("--dry-run", action="store_true",
                    help="route + plan only, no API calls")
    ap.add_argument("--allow-execution", action="store_true",
                    help="permit L4 to run Bash (training/teleop)")
    ap.add_argument("--backend", choices=["dryrun", "sdk", "openclaw", "nemoclaw"],
                    default=None, help="execution backend (default: env or sdk). "
                    "nemoclaw requires $NEMOCLAW_SANDBOX")
    ap.add_argument("--no-supervise", action="store_true",
                    help="disable the L0 master supervisor (Atlas) validation pass")
    ap.add_argument("--classify", metavar="CMD",
                    help="just print the routing decision and exit")
    args = ap.parse_args()

    if args.classify:
        print(router.classify(args.classify, default_layer=SETTINGS.default_layer).explain())
        return
    if not args.command:
        ap.error("provide a command, or use --classify")
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
