#!/usr/bin/env bash
# Install the Isaac Control Server as an always-on systemd USER service, so it
# never has to be started by hand in a terminal. After this, NemoClaw/OpenClaw
# just talk to an always-up host server on :5561.
#
#   ./install-control-service.sh          # install + enable + start
#   ./install-control-service.sh status   # show service status
#   ./install-control-service.sh logs     # follow the server log
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT="isaac-control-server.service"
DEST_DIR="$HOME/.config/systemd/user"
PORT="${ISAAC_CONTROL_PORT:-5561}"

case "${1:-install}" in
  status) systemctl --user status "$UNIT" --no-pager; exit 0 ;;
  logs)   journalctl --user -u "$UNIT" -f; exit 0 ;;
esac

mkdir -p "$DEST_DIR"
cp -f "$HERE/$UNIT" "$DEST_DIR/$UNIT"
echo "→ installed $DEST_DIR/$UNIT"

# Free :5561 if a manual/foreground server is holding it (the service will re-bind).
if curl -sf "http://localhost:$PORT/envs" >/dev/null 2>&1; then
  echo "→ a server is already on :$PORT — stopping it so the service can take over"
  pkill -f isaac_control_server.py 2>/dev/null || true
  sleep 2
fi

systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"
# Keep it running even when you're not logged in (best-effort; needs polkit).
loginctl enable-linger "$USER" 2>/dev/null || echo "  (note: enable-linger needs sudo; service still runs while logged in)"

echo "→ waiting for :$PORT ..."
for _ in $(seq 1 30); do
  curl -sf "http://localhost:$PORT/envs" >/dev/null 2>&1 && { echo "✓ control server is UP as a service ($PORT)"; break; }
  sleep 1
done
echo
echo "Manage it:"
echo "  systemctl --user status  isaac-control-server"
echo "  systemctl --user restart isaac-control-server"
echo "  systemctl --user stop    isaac-control-server"
echo "  journalctl --user -u isaac-control-server -f"
