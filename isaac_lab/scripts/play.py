#!/usr/bin/env python3
"""Canonical RL play entrypoint (dispatches to the backend's play.py).

    python play.py --task=<id> [--backend rsl_rl|cusrl|skrl] [--checkpoint PATH] [args...]
"""
import os, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
BACKENDS = {
    "rsl_rl": "reinforcement_learning/rsl_rl/play.py",
    "cusrl": "reinforcement_learning/cusrl/play.py",
    "skrl": "reinforcement_learning/skrl/play.py",
}
backend, passthrough = "rsl_rl", []
args = sys.argv[1:]; i = 0
while i < len(args):
    a = args[i]
    if a == "--backend":
        backend = args[i + 1]; i += 2; continue
    if a.startswith("--backend="):
        backend = a.split("=", 1)[1]; i += 1; continue
    passthrough.append(a); i += 1
if backend not in BACKENDS:
    sys.exit(f"unknown backend '{backend}' (valid: {', '.join(BACKENDS)})")
target = HERE / BACKENDS[backend]
if not target.exists():
    sys.exit(f"backend script not installed: {target}")
os.execv(sys.executable, [sys.executable, str(target), *passthrough])
