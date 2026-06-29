#!/usr/bin/env python3
"""Canonical teleop entrypoint (forwards to leisaac/environments/teleoperation/teleop_se3_agent.py)."""
import os, sys
from pathlib import Path
target = Path(__file__).resolve().parent / "leisaac/environments/teleoperation/teleop_se3_agent.py"
if not target.exists():
    sys.exit(f"target script not found: {target}")
os.execv(sys.executable, [sys.executable, str(target), *sys.argv[1:]])
