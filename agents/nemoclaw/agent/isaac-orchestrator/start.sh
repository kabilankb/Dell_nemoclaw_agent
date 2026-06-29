#!/usr/bin/env bash
# NemoClaw sandbox entrypoint for the Isaac Agent Orchestrator.
#
# Replicates the ROLE of agents/hermes/start.sh (launch the always-on agent
# service) but is intentionally a thin, readable entrypoint — it does NOT clone
# the Hermes start.sh's security-hardened sandbox-init primitives (gateway-user
# separation, config-hash verification, Landlock setup). In a real NemoClaw
# sandbox those are provided by /usr/local/lib/nemoclaw/sandbox-init.sh; this
# script is what runs *after* that, to bring up the orchestrator's Gradio
# dashboard as the long-lived service the manifest health-probes on :7860.
set -euo pipefail

export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Repo root: inside a sandbox the repo is mounted at /sandbox/warehouse_nemoclaw;
# fall back to this file's location for host/dev runs.
REPO_ROOT="${ORCHESTRATOR_DIR:-/sandbox/warehouse_nemoclaw}"
if [ ! -d "$REPO_ROOT/agent_orchestrator" ]; then
  REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
fi
cd "$REPO_ROOT"

# Env contract (manifest env_contract). WORKSPACE_DIR defaults under the repo.
export WORKSPACE_DIR="${WORKSPACE_DIR:-$REPO_ROOT/agent_orchestrator/workspace}"
export GRADIO_SERVER_NAME="${GRADIO_SERVER_NAME:-0.0.0.0}"
export GRADIO_SERVER_PORT="${GRADIO_SERVER_PORT:-7860}"

# Load optional .env overrides (ISAAC_*/ORCH_*/NEMOCLAW_*).
ENV_FILE="${ISAAC_ORCH_CONFIG_DIR:-/sandbox/.isaac-orchestrator}/.env"
if [ -f "$ENV_FILE" ]; then
  set -a; # shellcheck disable=SC1090
  source "$ENV_FILE"; set +a
fi

PY="$REPO_ROOT/agent_orchestrator/.venv/bin/python"
[ -x "$PY" ] || PY="python3"

echo "[isaac-orchestrator] repo=$REPO_ROOT  workspace=$WORKSPACE_DIR"
echo "[isaac-orchestrator] launching Gradio dashboard on ${GRADIO_SERVER_NAME}:${GRADIO_SERVER_PORT}"
exec "$PY" -m agent_orchestrator.app
