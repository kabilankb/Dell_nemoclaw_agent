#!/usr/bin/env python3
"""Canonical RL training entrypoint for isaac-claw.

Thin dispatcher so a model (and the control server) can rely on one stable name,
`train.py`, regardless of framework. Forwards all remaining args to the chosen
backend's real train script.

    python train.py --task=<id> [--backend rsl_rl|cusrl|skrl] [backend args...]

Default backend: rsl_rl. See ../../policies/policy_skill.md for hyperparameters.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKENDS = {
    "rsl_rl": "reinforcement_learning/rsl_rl/train.py",
    "cusrl": "reinforcement_learning/cusrl/train.py",
    "skrl": "reinforcement_learning/skrl/train.py",
}

backend, passthrough = "rsl_rl", []
args = sys.argv[1:]
i = 0
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
