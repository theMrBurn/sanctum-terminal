#!/usr/bin/env python3
"""Run schema migrations against config/kind_config.json — config-lock #5.

Default: no-op info dump (current vs target version + migration list). Pass
`--target N` to migrate forward or backward to that version; pass `--list`
to dump the available migrations; pass `--status` for a one-liner.

The config is rewritten in place. A `.pre-migrate` backup is written beside
it first so you can diff or revert without git magic. Use `--no-backup` to
skip (e.g. in CI where the commit history is the revert path).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from core.systems import kind_config_migrations as mig  # noqa: E402
from core.systems import kind_config_snapshot as snap  # noqa: E402


def cmd_status() -> int:
    config = snap.load_config()
    got = mig.version_of(config)
    want = mig.current_version()
    marker = "OK" if got == want else "DRIFT"
    print(f"kind_config: schema_version={got} (code expects {want}) [{marker}]")
    return 0 if got == want else 1


def cmd_list() -> int:
    migrations = mig.discover()
    if not migrations:
        print("(no migrations registered)")
        return 0
    for m in migrations:
        print(f"  {m.version:03d}  {m.name}  — {m.description}")
    return 0


def cmd_migrate(target: int, backup: bool) -> int:
    config = snap.load_config()
    start = mig.version_of(config)
    if start == target:
        print(f"kind_config: already at version {target}, nothing to do")
        return 0

    migrated = mig.migrate(config, target)

    if backup:
        backup_path = snap.CONFIG_PATH.with_suffix(
            snap.CONFIG_PATH.suffix + ".pre-migrate"
        )
        shutil.copy2(snap.CONFIG_PATH, backup_path)
        print(f"  backup: {backup_path.relative_to(_REPO_ROOT)}")

    # ensure_ascii=False preserves em-dashes etc. as-is; the hand-maintained
    # config uses unicode punctuation in _doc fields and escaping it would
    # produce noisy diffs on every migration run.
    with snap.CONFIG_PATH.open("w") as f:
        json.dump(migrated, f, indent=2, ensure_ascii=False)

    print(f"kind_config: migrated {start} -> {target}")
    print(
        "  Next: run `python scripts/snapshot_kind_config.py --update` "
        "to refresh the snapshot against the migrated config."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target",
        type=int,
        default=None,
        help="Migrate to this schema_version (omit to use current_version()).",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Print current vs expected schema_version and exit.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List every registered migration and exit.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip the .pre-migrate backup file when rewriting.",
    )
    args = parser.parse_args(argv)

    if args.list:
        return cmd_list()
    if args.status:
        return cmd_status()

    target = args.target if args.target is not None else mig.current_version()
    return cmd_migrate(target=target, backup=not args.no_backup)


if __name__ == "__main__":
    sys.exit(main())
