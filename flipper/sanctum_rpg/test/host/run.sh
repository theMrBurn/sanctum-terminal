#!/bin/sh
# Run every test/host script through a sanctum_host binary into OUT:
# OUT/<script>.trace, from a fresh stand-in SD card (OUT/root/<script>),
# with the script's fixture (a "# fixture: NAME" line) copied in first.
#   test/host/run.sh BIN OUT
set -e
BIN=$1; OUT=$2
HERE=$(dirname "$0")
mkdir -p "$OUT/root"
for s in "$HERE"/scripts/*.txt; do
  n=$(basename "$s" .txt)
  root="$OUT/root/$n"
  rm -rf "$root"; mkdir -p "$root"
  fx=$(sed -n 's/^# fixture: \([a-z_]*\).*/\1/p' "$s" | head -1)
  if [ -n "$fx" ]; then cp -R "$HERE/fixtures/$fx/." "$root/"; fi
  "$BIN" "$s" "$root" "$OUT/$n.trace"
done
