#!/usr/bin/env python3
"""signal_map single-source-of-truth guard.

The signal_map.json config was duplicated byte-for-byte across three separate,
independent repos (sanctum-nethack / sanctum-terminal / sanctum-engage) — all
proofs of concept. Three copies in three repos = guaranteed drift the moment one
is edited. This makes ONE canonical and the others GUARDED COPIES, exactly the
`make check-protocol` doctrine used for the CLAUDE.md/GEMINI.md protocol files:
executable-over-prose, a rule that is also a test cannot silently rot.

CANONICAL (source of truth): sanctum-nethack/config/signal_map.json
  New signal_map nodes (e.g. KitbashEngine) are declared HERE and synced out.

Usage:
  signal_map_sync.py            # --check (default): non-zero exit if a sibling diverges
  signal_map_sync.py --write    # push canonical -> each existing sibling copy

Independent-clone-safe: a sibling repo that isn't checked out beside this one is
skipped, not treated as an error. No third-party deps (air-gap clean; no LLM).
"""
import hashlib
import shutil
import sys
from pathlib import Path

# Canonical lives in THIS repo; siblings are peer repos under the same parent dir.
CANONICAL = Path(__file__).resolve().parents[1] / "config" / "signal_map.json"
GIT_ROOT = CANONICAL.parents[2]                        # the dir holding the sibling repos
SIBLINGS = [
    GIT_ROOT / "sanctum-terminal" / "config" / "signal_map.json",
    GIT_ROOT / "sanctum-engage" / "config" / "signal_map.json",
]


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    write = "--write" in sys.argv[1:]
    if not CANONICAL.is_file():
        print(f"FATAL: canonical missing: {CANONICAL}", file=sys.stderr)
        return 2
    canon = _digest(CANONICAL)
    drift = 0
    for sib in SIBLINGS:
        if not sib.is_file():
            print(f"skip  (absent): {sib}")
            continue
        if _digest(sib) == canon:
            print(f"ok    (in sync): {sib}")
            continue
        if write:
            shutil.copyfile(CANONICAL, sib)
            print(f"wrote (synced): {sib}")
        else:
            print(f"DRIFT (differs): {sib}   <- run with --write to reconcile")
            drift += 1
    if drift and not write:
        print(f"\n{drift} sibling(s) diverged from canonical {CANONICAL}", file=sys.stderr)
        return 1
    print("\nsignal_map: single source of truth intact." if not write else "\nsignal_map: siblings synced from canonical.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
