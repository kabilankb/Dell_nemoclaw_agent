#!/usr/bin/env bash
# Launch the OpenClaw TUI with the isaac-claw control server guaranteed up.
# Use this INSTEAD of bare `openclaw tui` so you never hit "connection refused".
#
#   ~/isaac-claw/agents/openclaw/tui.sh
#
# Tip: add an alias so it's the default:
#   echo "alias claw-tui='~/isaac-claw/agents/openclaw/tui.sh'" >> ~/.bashrc
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export ISAAC_CLAW_DIR="${ISAAC_CLAW_DIR:-$(cd "$HERE/../.." && pwd)}"
export ISAAC_SIM_DIR="${ISAAC_SIM_DIR:-$HOME/IsaacSim}"
export ISAAC_LAB_DIR="${ISAAC_LAB_DIR:-$HOME/IsaacLab}"
export ISAAC_LAB_PYTHON="${ISAAC_LAB_PYTHON:-$HOME/miniforge3/envs/env_isaaclab/bin/python}"
# So `claw open --gui` can open a window: propagate a display to the control
# server (and the sim it spawns). Override by exporting DISPLAY before running.
export DISPLAY="${DISPLAY:-:0}"

echo "[claw-tui] ensuring control server ($DISPLAY for GUI) ..."
"$HERE/claw" up || echo "[claw-tui] WARNING server not confirmed; the TUI can still run 'claw up'"

# Use a dedicated, clean session (NOT the default "main", which may carry stale
# context from earlier failed attempts). Override with: SESSION=foo tui.sh
SESSION="${SESSION:-isaac-claw}"
echo "[claw-tui] launching OpenClaw TUI (session: $SESSION)"
exec openclaw tui --session "$SESSION" "$@"
