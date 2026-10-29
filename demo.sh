#!/usr/bin/env bash
# One command for the isaac-claw hackathon demo:
#   control server (:5561) + NemoClaw sandbox + web console (:8800)
#
#   ./demo.sh up                       start everything (idempotent) → http://localhost:8800
#   ./demo.sh up --gpu-host user@vm    same, but Isaac Lab runs on a remote GPU box
#                                      (e.g. a Nebius AI Cloud VM) through an SSH tunnel
#   ./demo.sh check                    pre-flight: key, model, GPU memory, ports, checkpoints
#   ./demo.sh status                   one line per service
#   ./demo.sh down                     stop the console, control server, any GPU job, sandbox
#
# Settings live next to the key in ~/.openclaw/.env (all optional except the key):
#   NEBIUS_API_KEY=…                   Token Factory key
#   NEBIUS_MODEL=nvidia/nemotron-3-super-120b-a12b    model the claw runs on
#   NEBIUS_BASE_URL=https://api.tokenfactory.nebius.com/v1
#   ISAAC_GPU_HOST=user@vm             default for --gpu-host
#   ISAAC_GPU_DIR=~/isaac-claw         repo path on the GPU host
#   DUCK_HOST=microduck@<ip>           the real duck (duck pilot deploys there; unset = dry run)
#
# `down` stops only the sandbox, not the OpenShell gateway: a full `nemoclaw stop`
# also stops the gateway, and only `nemoclaw onboard` brings that back (done
# automatically by `up`).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${NEBIUS_ENV_FILE:-$HOME/.openclaw/.env}"
[[ -f "$ENV_FILE" ]] && { set -a; . "$ENV_FILE"; set +a; }

export ISAAC_CLAW_DIR="$HERE"
export PATH="$HOME/.local/bin:$PATH"
export NEMOCLAW_GATEWAY_PORT="${NEMOCLAW_GATEWAY_PORT:-8090}"   # 8080 is often taken
export NEMOCLAW_SANDBOX="${NEMOCLAW_SANDBOX:-isaacsim}"
export DUCKPILOT_SANDBOX="${DUCKPILOT_SANDBOX:-duckpilot}"   # Hermes agent (agents/hermes)
export DISPLAY="${DISPLAY:-:1}"
NEBIUS_MODEL="${NEBIUS_MODEL:-nvidia/nemotron-3-super-120b-a12b}"
export NEBIUS_BASE_URL="${NEBIUS_BASE_URL:-https://api.tokenfactory.nebius.com/v1}"
CONTROL_PORT="${ISAAC_CONTROL_PORT:-5561}"
CONSOLE_PORT="${CONSOLE_PORT:-8800}"
VISER_PORT="${ISAAC_VISER_PORT:-8012}"
GPU_HOST="${ISAAC_GPU_HOST:-}"
GPU_DIR="${ISAAC_GPU_DIR:-~/isaac-claw}"
LOGS="$HERE/isaac_sim/_control_logs"
mkdir -p "$LOGS"

listening() { ss -ltn 2>/dev/null | grep -q ":$1 "; }
pid_on()    { ss -ltnp 2>/dev/null | grep ":$1 " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2; }
sandbox_up() { docker ps --format '{{.Names}}' | grep -qE "^openshell-([a-z0-9_-]+--)?${1:-$NEMOCLAW_SANDBOX}-"; }
pilot_registered() { grep -q "\"$DUCKPILOT_SANDBOX\"" "$HOME/.nemoclaw/gateways/$NEMOCLAW_GATEWAY_PORT/sandboxes.json" 2>/dev/null; }
say() { printf '%-16s %s\n' "$1" "$2"; }

start_bg() {  # name port command...
  local name="$1" port="$2"; shift 2
  if listening "$port"; then say "$name" "already up (:$port)"; return; fi
  setsid nohup env -u NEBIUS_API_KEY -u COMPATIBLE_API_KEY "$@" > "$LOGS/$name.log" 2>&1 < /dev/null &
  for _ in $(seq 40); do listening "$port" && break; sleep 0.25; done
  listening "$port" && say "$name" "up (:$port)" || { say "$name" "FAILED — see $LOGS/$name.log"; exit 1; }
}

stop_port() {  # name port
  local pid; pid="$(pid_on "$2")"
  if [[ -n "$pid" ]]; then kill "$pid"; say "$1" "stopped (pid $pid)"; else say "$1" "not running"; fi
}

restart_gateway() {
  # The gateway is only restartable through onboarding; with the same settings it
  # restarts the gateway and then refuses to recreate the existing sandbox.
  [[ -n "${NEBIUS_API_KEY:-}" ]] || { echo "no NEBIUS_API_KEY in $ENV_FILE" >&2; exit 1; }
  COMPATIBLE_API_KEY="$NEBIUS_API_KEY" NEMOCLAW_NON_INTERACTIVE=1 \
  NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1 NEMOCLAW_SANDBOX_NAME="$NEMOCLAW_SANDBOX" \
  NEMOCLAW_PROVIDER=custom NEMOCLAW_ENDPOINT_URL="$NEBIUS_BASE_URL" \
  NEMOCLAW_MODEL="$NEBIUS_MODEL" NEMOCLAW_POLICY_MODE=suggested \
    nemoclaw onboard --name "$NEMOCLAW_SANDBOX" --non-interactive > "$LOGS/gateway-onboard.log" 2>&1 || true
}

sandbox_model() {
  python3 - "$NEMOCLAW_GATEWAY_PORT" "$NEMOCLAW_SANDBOX" <<'PY' 2>/dev/null || true
import json, sys, pathlib
p = pathlib.Path.home() / ".nemoclaw" / "gateways" / sys.argv[1] / "sandboxes.json"
print(json.loads(p.read_text())["sandboxes"][sys.argv[2]].get("model", ""))
PY
}

sync_model() {
  # NEBIUS_MODEL in .env is the source of truth; bring the sandbox in line if it drifted.
  local cur; cur="$(sandbox_model)"
  [[ -z "$cur" || "$cur" == "$NEBIUS_MODEL" ]] && return
  say model "switching $cur → $NEBIUS_MODEL (~45 s)"
  COMPATIBLE_API_KEY="$NEBIUS_API_KEY" nemoclaw inference set --provider compatible-endpoint \
    --model "$NEBIUS_MODEL" --sandbox "$NEMOCLAW_SANDBOX" --endpoint-url "$NEBIUS_BASE_URL" \
    --credential-env COMPATIBLE_API_KEY --inference-api openai-completions \
    > "$LOGS/model-switch.log" 2>&1 || say model "switch FAILED — see $LOGS/model-switch.log"
}

gpu_tunnel() {
  # Control server on the GPU host, reached locally on :5561 (console) and on the
  # sandbox's view of this host (host.openshell.internal) so the claw's tools work
  # unchanged; the viser viewer comes back on :8012.
  local sb_ip
  sb_ip="$(docker network inspect openshell-docker --format '{{(index .IPAM.Config 0).Gateway}}' 2>/dev/null || true)"
  ssh -o BatchMode=yes -o ConnectTimeout=10 "$GPU_HOST" \
    "cd $GPU_DIR && (ss -ltn | grep -q ':$CONTROL_PORT ' || ISAAC_CONTROL_HOST=127.0.0.1 setsid nohup python3 isaac_sim/scripts/isaac_control_server.py > isaac_sim/_control_logs/control-server.log 2>&1 < /dev/null &)" \
    || { say gpu-host "FAILED to start the control server on $GPU_HOST"; exit 1; }
  local fwd=(-L "127.0.0.1:$CONTROL_PORT:127.0.0.1:$CONTROL_PORT" -L "127.0.0.1:$VISER_PORT:127.0.0.1:$VISER_PORT")
  [[ -n "$sb_ip" ]] && fwd+=(-L "$sb_ip:$CONTROL_PORT:127.0.0.1:$CONTROL_PORT")
  setsid nohup ssh -N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 \
    "${fwd[@]}" "$GPU_HOST" > "$LOGS/gpu-tunnel.log" 2>&1 < /dev/null &
  for _ in $(seq 40); do listening "$CONTROL_PORT" && break; sleep 0.25; done
  listening "$CONTROL_PORT" && say control-server "up on $GPU_HOST (tunnel :$CONTROL_PORT)" \
    || { say control-server "tunnel FAILED — see $LOGS/gpu-tunnel.log"; exit 1; }
}

check() {
  local bad=0
  ok()   { printf '  \e[32m✓\e[0m %s\n' "$1"; }
  warn() { printf '  \e[33m!\e[0m %s\n' "$1"; }
  fail() { printf '  \e[31m✗\e[0m %s\n' "$1"; bad=1; }
  echo "Pre-flight"
  if [[ -z "${NEBIUS_API_KEY:-}" ]]; then fail "no NEBIUS_API_KEY in $ENV_FILE"
  else
    local code
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 15 -H "Authorization: Bearer $NEBIUS_API_KEY" "$NEBIUS_BASE_URL/models" || echo 000)"
    [[ "$code" == 200 ]] && ok "Nebius key …${NEBIUS_API_KEY: -4} accepted by Token Factory" \
                         || fail "Token Factory returned HTTP $code for the key (network or revoked key?)"
    code="$(curl -s -o /dev/null -w '%{http_code}' -m 60 "$NEBIUS_BASE_URL/chat/completions" \
      -H "Authorization: Bearer $NEBIUS_API_KEY" -H 'Content-Type: application/json' \
      -d "{\"model\":\"$NEBIUS_MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK\"}],\"max_tokens\":5}" || echo 000)"
    [[ "$code" == 200 ]] && ok "model $NEBIUS_MODEL answers" || fail "model $NEBIUS_MODEL returned HTTP $code"
  fi
  local cur; cur="$(sandbox_model)"
  [[ -z "$cur" ]] && warn "sandbox '$NEMOCLAW_SANDBOX' not onboarded on gateway :$NEMOCLAW_GATEWAY_PORT" \
    || { [[ "$cur" == "$NEBIUS_MODEL" ]] && ok "sandbox model matches ($cur)" \
         || warn "sandbox runs $cur, .env says $NEBIUS_MODEL (up will switch it)"; }
  if [[ -z "$GPU_HOST" ]] && command -v nvidia-smi > /dev/null; then
    local used total others
    read -r used total < <(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits | head -1 | tr -d ',')
    (( total - used > 12000 )) && ok "GPU memory free: $(( (total - used) / 1024 )) GB of $(( total / 1024 )) GB" \
                               || fail "only $(( (total - used) / 1024 )) GB GPU memory free"
    others="$(nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader,nounits 2>/dev/null \
      | while IFS=', ' read -r pid mem; do
          [[ -z "$pid" ]] && continue
          printf '%s (%s MB): %s\n' "$pid" "$mem" "$(ps -o args= -p "$pid" 2>/dev/null | cut -c1-90)"
        done)"
    [[ -n "$others" ]] && { warn "other GPU processes:"; sed 's/^/      /' <<< "$others"; }
  fi
  for p in "$CONSOLE_PORT" "$VISER_PORT" "$CONTROL_PORT" "$NEMOCLAW_GATEWAY_PORT"; do
    local pid; pid="$(pid_on "$p")"
    if [[ -z "$pid" ]]; then ok "port $p free"
    else
      local cmd; cmd="$(ps -o args= -p "$pid" 2>/dev/null | cut -c1-70)"
      case "$cmd" in
        *console_server*|*isaac_control_server*|*openshell*|*ssh*|*nemoclaw*) ok "port $p: ours ($cmd)";;
        *) fail "port $p taken by pid $pid: $cmd";;
      esac
    fi
  done
  if [[ -z "$GPU_HOST" ]]; then
    local lab3="${ISAAC_LAB3_DIR:-$HOME/IsaacLab-develop}" best
    [[ -x "$lab3/.venv/bin/python" ]] && ok "Isaac Lab 3 venv at $lab3" || fail "no Isaac Lab 3 venv at $lab3"
    best="$(python3 - "$HERE" <<'PY' 2>/dev/null || true
import sys; sys.path.insert(0, sys.argv[1] + "/isaac_sim/scripts")
import isaac_control_server as c
for t in ("IsaacContrib-Velocity-Flat-MicroDuck", "Isaac-Velocity-Flat-G1"):
    r = c.lab3_checkpoints(t)
    print(f"{t}: " + (f"best run {r[0]['run']} at iteration {r[0]['iteration']}" if r else "no checkpoint"))
PY
)"
    while read -r line; do
      [[ -z "$line" ]] && continue
      case "$line" in *"no checkpoint"*|*"iteration "[0-9]|*"iteration "[0-9][0-9]|*"iteration "[0-9][0-9][0-9]) warn "$line (train ≥1000 its before the demo)";; *) ok "$line";; esac
    done <<< "$best"
  else
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$GPU_HOST" true 2>/dev/null && ok "ssh to $GPU_HOST works" || fail "cannot ssh to $GPU_HOST"
  fi
  (( bad )) && { echo "Fix the ✗ items before going on stage."; return 1; }
  echo "Ready."
}

cmd="${1:-status}"; shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --gpu-host) GPU_HOST="$2"; shift 2;;
    --gpu-dir)  GPU_DIR="$2"; shift 2;;
    *) echo "unknown option $1" >&2; exit 2;;
  esac
done

case "$cmd" in
  up)
    if [[ -n "$GPU_HOST" ]]; then
      listening "$CONTROL_PORT" && say control-server "already up (:$CONTROL_PORT)" || gpu_tunnel
    else
      start_bg control-server "$CONTROL_PORT" python3 "$HERE/isaac_sim/scripts/isaac_control_server.py"
    fi
    if sandbox_up; then
      say sandbox "already up ($NEMOCLAW_SANDBOX)"
    else
      listening "$NEMOCLAW_GATEWAY_PORT" || { say gateway "starting (:$NEMOCLAW_GATEWAY_PORT)…"; restart_gateway; }
      nemoclaw "$NEMOCLAW_SANDBOX" start > "$LOGS/sandbox-start.log" 2>&1 || true
      sandbox_up && say sandbox "up ($NEMOCLAW_SANDBOX)" \
                 || { say sandbox "FAILED — see $LOGS/sandbox-start.log"; exit 1; }
    fi
    sync_model
    if pilot_registered; then
      if sandbox_up "$DUCKPILOT_SANDBOX"; then say duck-pilot "already up ($DUCKPILOT_SANDBOX)"
      else
        nemohermes "$DUCKPILOT_SANDBOX" start > "$LOGS/duckpilot-start.log" 2>&1 || true
        sandbox_up "$DUCKPILOT_SANDBOX" && say duck-pilot "up ($DUCKPILOT_SANDBOX)" \
          || say duck-pilot "FAILED — see $LOGS/duckpilot-start.log (console still works)"
      fi
    fi
    start_bg console "$CONSOLE_PORT" python3 "$HERE/web/console_server.py"
    echo
    echo "Open http://localhost:$CONSOLE_PORT"
    ;;
  down)
    stop_port console "$CONSOLE_PORT"
    curl -s -m 20 -X POST "http://127.0.0.1:$CONTROL_PORT/stop" > /dev/null 2>&1 || true
    stop_port control-server "$CONTROL_PORT"   # with --gpu-host this closes the tunnel
    if sandbox_up; then nemoclaw "$NEMOCLAW_SANDBOX" stop > /dev/null 2>&1; say sandbox "stopped"; else say sandbox "not running"; fi
    if sandbox_up "$DUCKPILOT_SANDBOX"; then nemohermes "$DUCKPILOT_SANDBOX" stop > /dev/null 2>&1; say duck-pilot "stopped"; fi
    ;;
  check) check ;;
  status)
    listening "$CONTROL_PORT"         && say control-server "up (:$CONTROL_PORT)" || say control-server "down"
    listening "$NEMOCLAW_GATEWAY_PORT" && say gateway "up (:$NEMOCLAW_GATEWAY_PORT)" || say gateway "down"
    sandbox_up                         && say sandbox "up ($NEMOCLAW_SANDBOX, $(sandbox_model))" || say sandbox "down"
    pilot_registered && { sandbox_up "$DUCKPILOT_SANDBOX" && say duck-pilot "up ($DUCKPILOT_SANDBOX)" || say duck-pilot "down"; }
    listening "$VISER_PORT"           && say viewer "up (:$VISER_PORT)" || say viewer "down (no gui run)"
    listening "$CONSOLE_PORT"         && say console "up — http://localhost:$CONSOLE_PORT" || say console "down"
    ;;
  *) echo "usage: $0 up|down|status|check [--gpu-host user@vm] [--gpu-dir path]" >&2; exit 2 ;;
esac
