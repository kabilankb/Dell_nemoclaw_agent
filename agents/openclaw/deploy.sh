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
OPERATIONAL=(task ops training teleop mimicgen)

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
