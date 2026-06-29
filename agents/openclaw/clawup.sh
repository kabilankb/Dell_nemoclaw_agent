#!/usr/bin/env bash
# Bring up the isaac-claw host services so EVERYTHING is drivable from the
# OpenClaw TUI. Idempotent: starts the Isaac Control Server only if it isn't
# already answering. The model can call this before any control request.
#
# Usage:  ./clawup.sh                 # ensure control server up
#         ./clawup.sh --sim [scene]   # also launch a persistent sim (bridge :8226)
#         ./clawup.sh status          # report what's up
set -uo pipefail

CLAW_DIR="${ISAAC_CLAW_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
PY="${ISAAC_LAB_PYTHON:-$HOME/miniforge3/envs/env_isaaclab/bin/python}"
PORT="${ISAAC_CONTROL_PORT:-5561}"
BASE="http://localhost:$PORT"
LOGDIR="$CLAW_DIR/isaac_sim/_control_logs"; mkdir -p "$LOGDIR"

up() { curl -sf "$BASE/envs" >/dev/null 2>&1; }

ensure_server() {
  if up; then echo "control server: already up ($BASE)"; return 0; fi
  echo "control server: starting ..."
  ISAAC_CLAW_DIR="$CLAW_DIR" ISAAC_LAB_PYTHON="$PY" \
    nohup "$PY" "$CLAW_DIR/isaac_sim/scripts/isaac_control_server.py" \
    >"$LOGDIR/control_server.out" 2>&1 &
  for _ in $(seq 1 30); do up && { echo "control server: up ($BASE)"; return 0; }; sleep 1; done
  echo "control server: FAILED to come up — see $LOGDIR/control_server.out"; return 1
}

case "${1:-}" in
  status)
    up && { echo "control server: UP"; curl -s "$BASE/status"; } || echo "control server: DOWN"
    ;;
  --sim)
    ensure_server || exit 1
    scene="${2:-warehouse.usd}"
    echo "launching persistent sim on scene '$scene' (bridge :8226) ..."
    curl -s -XPOST "$BASE/sim/launch" -d "{\"scene\":\"$scene\",\"mode\":\"serve\"}"
    ;;
  *)
    ensure_server
    ;;
esac
