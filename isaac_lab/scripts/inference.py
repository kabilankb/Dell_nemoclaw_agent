#!/usr/bin/env python3
"""Canonical inference entrypoint (forwards to leisaac/evaluation/policy_inference.py)."""
import os, sys
from pathlib import Path
target = Path(__file__).resolve().parent / "leisaac/evaluation/policy_inference.py"
if not target.exists():
    sys.exit(f"target script not found: {target}")
os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])
