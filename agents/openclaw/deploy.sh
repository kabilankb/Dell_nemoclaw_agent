#!/usr/bin/env bash
# Deploy isaac-claw skills into OpenClaw's workspace as REAL directories.
#
# OpenClaw's skill scanner does NOT follow symlinks, so we copy. By default we
# deploy only the small OPERATIONAL set (the skills that map to the `claw`
# command) — a small surface keeps a local 12B model from wandering into deep
# authoring skills. Use `--all` to also copy the full reference library.
#
#   ./deploy.sh           # operational set (recommended for the TUI)
#   ./deploy.sh --all     # operational + full reference library
set -euo pipefail

CLAW_DIR="${ISAAC_CLAW_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
OC_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
DEST="$OC_HOME/workspace/skills"
SRC="$CLAW_DIR/skills"
BAK="$OC_HOME/workspace/_isaac_claw_replaced_backup"
mkdir -p "$DEST" "$BAK"

# The operational set the TUI actually needs (each maps to a `claw` action).
OPERATIONAL=(task close ops training teleop mimicgen inventory)

want_all=false
[ "${1:-}" = "--all" ] && want_all=true

# 1. Clear any previous isaac-claw deployment (old symlinks + the router dir).
echo "clearing previous isaac-claw skills from $DEST ..."
for entry in "$DEST"/*; do
  [ -e "$entry" ] || continue
  name="$(basename "$entry")"
  if [ -L "$entry" ] && readlink "$entry" | grep -q "$SRC"; then
    rm -f "$entry"                       # stale symlink into the repo
  elif [ "$name" = "isaac-claw" ]; then
    rm -rf "$entry"                      # old master-router dir
  fi
done

# 2. Pick the set to deploy.
if $want_all; then
  mapfile -t SET < <(for d in "$SRC"/*/; do [ -f "${d}SKILL.md" ] && basename "$d"; done)
else
  SET=("${OPERATIONAL[@]}")
fi

# 3. Copy each as a REAL directory (dereference any internal symlinks).
n=0
for name in "${SET[@]}"; do
  [ -f "$SRC/$name/SKILL.md" ] || { echo "  skip $name (no SKILL.md)"; continue; }
  if [ -e "$DEST/$name" ] && [ ! -L "$DEST/$name" ]; then
    rm -rf "$BAK/$name"; mv "$DEST/$name" "$BAK/$name"   # preserve a non-ours dir
  fi
  rm -rf "$DEST/$name"
  cp -rL "$SRC/$name" "$DEST/$name"
  n=$((n+1)); echo "  + $name"
done

echo "deployed $n real skill dir(s) to $DEST"
$want_all || echo "(operational set only; run with --all for the full library)"
echo "NOTE: real copies — re-run this after editing skills in the repo."

# 4. Local RAG: regenerate the ground-truth inventory and seed it into OpenClaw's
#    memory store so `memory_search` / `memory_get` can ground answers about what
#    robots/environments/tasks exist (the anti-hallucination corpus). Keyword
#    retrieval works without an embedding provider; semantic if one is configured.
MEM="$OC_HOME/workspace/memory"
if [ -f "$SRC/inventory/gen_inventory.py" ]; then
  echo "refreshing ground-truth inventory + seeding memory ..."
  ISAAC_CLAW_DIR="$CLAW_DIR" python3 "$SRC/inventory/gen_inventory.py" >/dev/null 2>&1 || \
    echo "  (warn: could not regenerate INVENTORY.md — using existing copy)"
  if [ -f "$SRC/inventory/INVENTORY.md" ]; then
    mkdir -p "$MEM"
    cp "$SRC/inventory/INVENTORY.md" "$MEM/isaac-claw-inventory.md"
    echo "  + memory/isaac-claw-inventory.md (retrievable via memory_search/memory_get)"
  fi
fi

# 5. Activate skills in OpenClaw's enable-list. CRITICAL: copying dirs is NOT
#    enough — OpenClaw only exposes a skill if skills.entries.<NAME>.enabled is
#    true, and the entry key is the skill's FRONTMATTER name, not its dir name.
#    We enable exactly the operational set and disable the noise that made a
#    local model hallucinate robots/envs (mobility-gen, the orchestrators, the
#    physical-arm skills, hello_world). A tiny surface = a reliable 12B.
if command -v openclaw >/dev/null 2>&1; then
  echo "configuring OpenClaw skills.entries (enable operational, disable noise) ..."
  # NOTE: we deliberately do NOT touch commands.nativeSkills here — leave it to
  # the user's config. (Forcing it 'true' did not expose per-skill tools for the
  # local model and only caused skill_workshop misuse; 'auto' + a reasoning model
  # + a fresh session is what actually let skills fire.)
  ENABLE=(isaac-open-environment isaac-inventory isaac-claw-ops isaac-close \
          isaaclab-training isaaclab-robot-control isaac-mimicgen)
  # Everything else off → a TINY callable surface (the 7 above) keeps a 12B reliable.
  DISABLE=(hello_world mobility-gen isaac-sim-orchestrator isaac-agent-orchestrator \
           leisaac-codegen omx-control soarm-control \
           navigation-primitives physics-simulation manipulation-ik \
           urdf-mjcf-to-usd-conversion spatial-reasoning isaac-sim-sensor \
           occupancy-map data-collection-sim usd-articulation meta-skills skill-distillation)
  for s in "${ENABLE[@]}";  do openclaw config set "skills.entries.$s.enabled" true  >/dev/null 2>&1 && echo "  enable  $s"; done
  for s in "${DISABLE[@]}"; do openclaw config set "skills.entries.$s.enabled" false >/dev/null 2>&1 && echo "  disable $s"; done
  echo "  -> restart the gateway to apply (openclaw daemon restart)"
else
  echo "(openclaw CLI not found — skipping skills.entries config; run deploy.sh where openclaw is installed)"
fi
