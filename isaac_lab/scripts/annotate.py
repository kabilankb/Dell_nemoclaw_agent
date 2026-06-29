#!/usr/bin/env python3
"""Canonical annotate entrypoint (forwards to leisaac/mimic/annotate_demos.py)."""
import os, sys
from pathlib import Path
target = Path(__file__).resolve().parent / "leisaac/mimic/annotate_demos.py"
if not target.exists():
    sys.exit(f"target script not found: {target}")
os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])
