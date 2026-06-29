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

echo "[claw-tui] ensuring control server ..."
"$HERE/claw" up || echo "[claw-tui] WARNING server not confirmed; the TUI can still run 'claw up'"

echo "[claw-tui] launching OpenClaw TUI (model: gemma4:12b)"
exec openclaw tui "$@"
