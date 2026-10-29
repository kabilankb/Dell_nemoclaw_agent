#!/usr/bin/env bash
# Create + provision the duck-pilot agent: a Hermes agent in a NemoClaw sandbox,
# on Nemotron via Nebius Token Factory, that trains, plays and deploys the MicroDuck
# through the isaac MCP tools (agents/nemoclaw/isaac-mcp.mjs → control server :5561).
#
#   agents/hermes/install_duckpilot.sh            onboard (if needed) + provision
#   agents/hermes/install_duckpilot.sh --update   re-copy the MCP server + skill only
#
# Needs NEBIUS_API_KEY (and optionally NEBIUS_MODEL) in ~/.openclaw/.env, and the
# NemoClaw gateway that demo.sh uses (NEMOCLAW_GATEWAY_PORT, default 8090).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SB="${DUCKPILOT_SANDBOX:-duckpilot}"
ENV_FILE="${NEBIUS_ENV_FILE:-$HOME/.openclaw/.env}"
[[ -f "$ENV_FILE" ]] && { set -a; . "$ENV_FILE"; set +a; }
export PATH="$HOME/.local/bin:$PATH"
export NEMOCLAW_GATEWAY_PORT="${NEMOCLAW_GATEWAY_PORT:-8090}"
MODEL="${DUCKPILOT_MODEL:-nvidia/nemotron-3-super-120b-a12b}"
BASE="${NEBIUS_BASE_URL:-https://api.tokenfactory.nebius.com/v1}"

container() { docker ps --format '{{.Names}}' | grep -E "^openshell-([a-z0-9_-]+--)?${SB}-" | head -1 || true; }
in_sb() { docker exec -u sandbox -e HOME=/sandbox -e HERMES_HOME=/sandbox/.hermes "$CT" bash -lc "$1"; }

if [[ "${1:-}" != "--update" ]] && [[ -z "$(container)" ]]; then
  [[ -n "${NEBIUS_API_KEY:-}" ]] || { echo "no NEBIUS_API_KEY in $ENV_FILE" >&2; exit 1; }
  echo "→ [1/5] onboarding Hermes sandbox '$SB' ($MODEL on Nebius)"
  COMPATIBLE_API_KEY="$NEBIUS_API_KEY" NEMOCLAW_AGENT=hermes NEMOCLAW_NON_INTERACTIVE=1 \
  NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 NEMOCLAW_SANDBOX_NAME="$SB" NEMOCLAW_PROVIDER=custom \
  NEMOCLAW_ENDPOINT_URL="$BASE" NEMOCLAW_MODEL="$MODEL" NEMOCLAW_POLICY_MODE=suggested \
  NEMOCLAW_DISABLE_TELEMETRY=1 \
    nemohermes onboard --agent hermes --name "$SB" --non-interactive --no-gpu --yes
fi
CT="$(container)"
[[ -n "$CT" ]] || { echo "sandbox '$SB' is not running (nemohermes $SB start?)" >&2; exit 1; }
echo "→ sandbox '$SB' → $CT"

if [[ "${1:-}" != "--update" ]]; then
  echo "→ [2/5] egress policy: Hermes + node → host.openshell.internal:5561"
  nemohermes "$SB" policy add isaaclab-training-hermes \
    --from-file "$HERE/isaaclab-training-hermes.yaml" --yes > /dev/null
fi

echo "→ [3/5] isaac MCP server"
docker exec "$CT" mkdir -p /sandbox/.hermes/mcp /sandbox/.hermes/skills/duck-pilot
docker cp "$REPO/agents/nemoclaw/isaac-mcp.mjs" "$CT":/sandbox/.hermes/mcp/isaac-mcp.mjs
echo "→ [4/5] duck-pilot skill"
docker cp "$HERE/skills/duck-pilot/SKILL.md" "$CT":/sandbox/.hermes/skills/duck-pilot/SKILL.md
docker exec "$CT" chown -R sandbox:sandbox /sandbox/.hermes/mcp /sandbox/.hermes/skills/duck-pilot
if ! in_sb 'grep -q "^  isaac:" /sandbox/.hermes/config.yaml'; then
  # `mcp add` connects, lists the tools and asks to enable them; it doubles as the egress test
  in_sb 'printf "Y\n" | hermes mcp add isaac --command node --args --no-warnings /sandbox/.hermes/mcp/isaac-mcp.mjs' \
    | grep -E "Saved|Error|error" || true
fi

echo "→ [5/5] check"
in_sb 'hermes mcp list 2>&1 | grep -E "^\s*isaac"; hermes skills list 2>&1 | grep -o "duck-pilot.*enabled" | head -1'
echo "✓ duck pilot ready. Talk to it in the console (Duck pilot tab) or:"
echo "  nemohermes $SB exec --no-tty -- bash -lc 'HOME=/sandbox HERMES_HOME=/sandbox/.hermes hermes chat -Q -s duck-pilot -q \"how is the duck doing?\"'"
