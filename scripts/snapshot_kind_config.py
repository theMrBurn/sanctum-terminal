#!/usr/bin/env python3
"""Show drift between config/kind_config.json and its snapshot; update on demand.

Config-lock #3. The snapshot is the last explicitly-acknowledged state of
the config; drift is anything edited since. Default mode prints the flat
diff and exits non-zero when drift exists, so scripts (pre-commit, brain
preflight) can gate on it. `--update` writes the current config to the
snapshot after printing what's about to be acknowledged.

Usage:
    python scripts/snapshot_kind_config.py            # show drift, exit 1 on drift
    python scripts/snapshot_kind_config.py --update   # acknowledge: overwrite snapshot
    python scripts/snapshot_kind_config.py --quiet    # silent on clean state
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a script without `pip install -e .`.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.systems import kind_config_snapshot as snap  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Overwrite snapshot with current config after printing drift.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the 'no drift' message (errors still print).",
    )
    args = parser.parse_args(argv)

    config = snap.load_config()

    if not snap.SNAPSHOT_PATH.exists():
        if args.update:
            snap.save_snapshot(config)
            print(f"snapshot: seeded {snap.SNAPSHOT_PATH.relative_to(_REPO_ROOT)}")
            return 0
        print(
            f"snapshot: MISSING ({snap.SNAPSHOT_PATH.relative_to(_REPO_ROOT)}). "
            "Run with --update to seed.",
            file=sys.stderr,
        )
        return 2

    d = snap.diff_against_snapshot(config)
    if snap.is_empty(d):
        if not args.quiet:
            print("snapshot: clean — no drift vs snapshot")
        return 0

    formatted = snap.format_diff(d)
    n = len(d["added"]) + len(d["removed"]) + len(d["changed"])
    header = f"snapshot: {n} change(s) vs {snap.SNAPSHOT_PATH.name}"
    if args.update:
        print(header + " — acknowledging and updating snapshot:")
        print(formatted)
        snap.save_snapshot(config)
        print(f"snapshot: updated {snap.SNAPSHOT_PATH.relative_to(_REPO_ROOT)}")
        return 0
    print(header, file=sys.stderr)
    print(formatted, file=sys.stderr)
    print(
        "\nRun `python scripts/snapshot_kind_config.py --update` to acknowledge.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
