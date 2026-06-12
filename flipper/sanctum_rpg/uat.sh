#!/usr/bin/env bash
# UAT build/flash for the world-edge-coherence work. Run with the Flipper
# connected over USB. Self-bootstraps ufbt into a private venv (the system
# `ufbt` command isn't required), reusing the cached SDK in ~/.ufbt, so this
# just works after a reboot or a fresh shell.
#
#   ./uat.sh            build + flash + launch on the connected Flipper
#   ./uat.sh build      build only (produces dist/sanctum_rpg.fap), no device
set -euo pipefail
cd "$(dirname "$0")"

# Resolve ufbt: prefer one already on PATH; otherwise bootstrap a persistent
# venv next to the cached SDK (survives reboots, unlike a /tmp venv).
if command -v ufbt >/dev/null 2>&1; then
  UFBT="ufbt"
else
  VENV="${HOME}/.ufbt-venv"
  if [ ! -x "${VENV}/bin/ufbt" ]; then
    echo ">> ufbt not found — bootstrapping ${VENV} (one-time; reuses ~/.ufbt SDK)"
    python3 -m venv "${VENV}"
    "${VENV}/bin/python" -m pip install -q --upgrade pip ufbt
  fi
  UFBT="${VENV}/bin/ufbt"
fi

if [ "${1:-launch}" = "build" ]; then
  echo ">> building .fap only (no device needed)"
  exec $UFBT
fi

echo ">> building + flashing + launching on the connected Flipper"
exec $UFBT launch

# ── UAT checklist (what this branch changed) ──────────────────────────────
#  1. DOOR=DOOR: walk from open ground toward a cavern/room. You should hit a
#     WALL and only cross at a single door — never phase through the rock. The
#     door you exit lines up with the door you enter.
#  2. WALL=WALL: walking at a wall is blocked ("blocked." on the status strip),
#     not a transition.
#  3. COMPOSER LOOK: terrain clusters grow OUT FROM CENTER (vs your
#     Screenshot 2026-04-07 drawing). Tune compose.c STAMP_BUDGET_PER_CHUNK (4).
#  4. SECRETS: a '%' in a wall is a hidden passage (top-down tell). It opens
#     only once the gating growth axis's effective value hits the threshold
#     (sanctum_rpg.c SECRET_AXIS_THRESHOLD = 16). Until then: "the stone here
#     rings hollow." Tune the threshold to taste.
#  5. EXISTING SAVE: load your current campaign — if your old spot is now a
#     wall, you wake at the chunk spawn (expected; not a bug).
