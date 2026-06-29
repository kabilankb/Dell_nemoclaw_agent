#!/usr/bin/env bash
# Deploy the Isaac agent-orchestrator skill into a NemoClaw sandbox.
#
# Usage:
#   agent_orchestrator/nemoclaw/install_skill.sh <sandbox>
#   NEMOCLAW_SANDBOX=robotcontrol agent_orchestrator/nemoclaw/install_skill.sh
#
# Mirrors the OpenClaw integration: there, the skill lives under
# ~/.openclaw/workspace/skills/. NemoClaw instead pushes a skill *into* a named
# sandbox via `nemoclaw <sandbox> skill install <path>`.
set -euo pipefail

SANDBOX="${1:-${NEMOCLAW_SANDBOX:-}}"
if [[ -z "$SANDBOX" ]]; then
  echo "error: pass a sandbox name or set NEMOCLAW_SANDBOX (see: nemoclaw list)" >&2
  exit 1
fi

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/skill/isaac-agent-orchestrator" && pwd)"
NEMOCLAW="$(command -v nemoclaw || echo "$HOME/.local/bin/nemoclaw")"
if [[ ! -x "$NEMOCLAW" ]]; then
  echo "error: nemoclaw CLI not found on PATH or ~/.local/bin" >&2
  exit 1
fi

echo "→ installing skill 'isaac-agent-orchestrator' into sandbox '$SANDBOX'"
echo "  from: $SKILL_DIR"
"$NEMOCLAW" "$SANDBOX" skill install "$SKILL_DIR"
echo "✓ done. Verify inside the sandbox; mount the repo if \$ORCHESTRATOR_DIR is absent:"
echo "  nemoclaw $SANDBOX share mount /home/dgx-destro/warehouse_nemoclaw /work/warehouse_nemoclaw"
