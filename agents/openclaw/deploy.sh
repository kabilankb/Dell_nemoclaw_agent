#!/usr/bin/env bash
# Deploy the isaac-claw skill library into OpenClaw's workspace so a local model
# (Gemma) can discover it. Non-destructive: symlinks each skill dir; any existing
# REAL directory it would shadow is moved aside to <name>.pre-isaac-claw.bak.
#
# Usage:  ./deploy.sh            # uses $ISAAC_CLAW_DIR or this repo, ~/.openclaw
#         ISAAC_CLAW_DIR=... OPENCLAW_HOME=... ./deploy.sh
set -euo pipefail

CLAW_DIR="${ISAAC_CLAW_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
OC_HOME="${OPENCLAW_HOME:-$HOME/.openclaw}"
DEST="$OC_HOME/workspace/skills"
SRC="$CLAW_DIR/skills"
# Back up shadowed dirs OUTSIDE skills/ so OpenClaw never scans them as duplicate skills.
BAK="$OC_HOME/workspace/_isaac_claw_replaced_backup"

mkdir -p "$DEST" "$BAK"
echo "isaac-claw: $CLAW_DIR"
echo "deploy ->  $DEST"

# 1) every specialized skill (a dir containing SKILL.md)
n=0
for d in "$SRC"/*/; do
  [ -f "${d}SKILL.md" ] || continue
  name="$(basename "$d")"
  tgt="$DEST/$name"
  if [ -e "$tgt" ] && [ ! -L "$tgt" ]; then
    mv "$tgt" "$BAK/$name"
    echo "  backed up existing $name -> _isaac_claw_replaced_backup/$name"
  fi
  ln -sfn "${d%/}" "$tgt"
  n=$((n+1))
done

# 2) the MASTER router (skills/skills.md) — exposed as a discoverable skill dir
#    so OpenClaw loads it like any other SKILL.md (frontmatter name: isaac-claw-skills)
mkdir -p "$DEST/isaac-claw"
ln -sfn "$SRC/skills.md" "$DEST/isaac-claw/SKILL.md"

echo "linked $n skills + master router (isaac-claw)."
echo "verify:  ls -l $DEST | grep isaac-claw"
