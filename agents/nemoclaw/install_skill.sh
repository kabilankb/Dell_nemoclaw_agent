#!/usr/bin/env bash
# Provision a NemoClaw sandbox to drive Isaac — END TO END, one command.
#
#   ./install_skill.sh <sandbox>
#   NEMOCLAW_SANDBOX=robotcontrol ./install_skill.sh
#
# Prereqs: the sandbox already exists (`nemoclaw onboard`, model = a tool-capable
# one like nemotron-3-super:120b) and the HOST control server is running.
#
# What this does, in order:
#   1. installs the operational skill docs (supplementary context / triggers)
#   2. adds the isaaclab-training egress policy (opens node -> host:5561)
#   3. applies the DEDICATED MCP TOOLS fix (apply_mcp_fix.sh) — the part that
#      actually makes the local model reliably reach the control server:
#      isaac__* MCP tools + toolSearch=false + proxy-first/direct-fallback transport.
#      (The curl-based skills alone do NOT work under NemoClaw code-mode — the MCP
#       tools are the real driver; the skills just add trigger keywords/context.)
set -euo pipefail

SANDBOX="${1:-${NEMOCLAW_SANDBOX:-}}"
if [[ -z "$SANDBOX" ]]; then
  echo "usage: install_skill.sh <sandbox>   (list them with: nemoclaw list)" >&2
  exit 1
fi

HERE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE_DIR/../.." && pwd)"
# NemoClaw uses SANDBOX-NATIVE skills (HTTP to the control server), NOT the
# claw-based OpenClaw skills — the sandbox has no `claw` CLI, no repo, no shell-repo.
SRC="$HERE_DIR/skills"
POLICY_FILE="$REPO_ROOT/sandbox/policies/isaaclab-training-policy.yaml"
NEMOCLAW="$(command -v nemoclaw || echo "$HOME/.local/bin/nemoclaw")"
if [[ ! -x "$NEMOCLAW" ]]; then
  echo "error: nemoclaw CLI not found on PATH or ~/.local/bin" >&2
  exit 1
fi

# The operational set — each maps to an HTTP call to the Isaac Control Server.
OPERATIONAL=(task inventory ops close training)

echo "→ installing isaac-claw operational skills into sandbox '$SANDBOX'"
n=0
for s in "${OPERATIONAL[@]}"; do
  if [[ -f "$SRC/$s/SKILL.md" ]]; then
    echo "  + $s"
    "$NEMOCLAW" "$SANDBOX" skill install "$SRC/$s"
    n=$((n+1))
  else
    echo "  skip $s (no SKILL.md)"
  fi
done
echo "✓ installed $n skill doc(s) into '$SANDBOX'."

# 2) egress policy — open node -> host.openshell.internal:5561
echo "→ [policy] adding isaaclab-training egress (host:5561)"
if [[ -f "$POLICY_FILE" ]]; then
  "$NEMOCLAW" "$SANDBOX" policy-add isaaclab-training --from-file "$POLICY_FILE" --yes
else
  echo "  ⚠ policy file not found: $POLICY_FILE (skipping — add it manually)" >&2
fi

# 3) the real driver — dedicated isaac__ MCP tools + toolSearch off + transport
echo "→ [mcp] applying dedicated-tools fix"
"$HERE_DIR/apply_mcp_fix.sh" "$SANDBOX"

echo
echo "✓ '$SANDBOX' is provisioned end-to-end. Before chatting, make sure the HOST"
echo "  control server is running (real GPU terminal):"
echo "      \$ISAAC_LAB_PYTHON \$ISAAC_CLAW_DIR/isaac_sim/scripts/isaac_control_server.py"
echo "Then:  nemoclaw $SANDBOX connect   →   openclaw tui   (plain — NO --session; named sessions cannot reach :5561)"
echo "  try: \"list robots\" / \"how many tasks?\" / \"open the warehouse with spot\""
