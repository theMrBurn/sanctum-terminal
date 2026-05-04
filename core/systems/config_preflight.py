"""Session-opener preflight — config-lock #6.

Orchestrates #1 (schema) + #5 (migration version) + #3 (snapshot drift)
into a single check. Runs on brain boot via `assert_valid_config_state()`
and as a standalone CLI via `python -m core.systems.config_preflight` so
you can verify the config without spinning up the whole server.

Severity levels:
  ERROR — brain cannot proceed. Schema failure or version mismatch.
  WARN  — proceed with visibility. Snapshot drift (intentional edits are
          normal; the warning just ensures you've seen what changed).
  OK    — silent pass.

CLI exits 0 on OK/WARN, 1 on any ERROR. Brain boot raises on ERROR.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.systems import kind_config_migrations as mig
from core.systems import kind_config_schema as schema
from core.systems import kind_config_snapshot as snap


_SKIP_ENV = "SANCTUM_SKIP_CONFIG_VALIDATION"


@dataclass
class PreflightResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def merge(self, other: "PreflightResult") -> None:
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


class PreflightError(RuntimeError):
    """Raised by assert_valid_config_state when any ERROR is present."""


# --- Individual checks ------------------------------------------------------


def check_schema(config: dict[str, Any]) -> PreflightResult:
    result = PreflightResult()
    errors = schema.validate(config)
    if errors:
        result.errors.append(
            f"schema: {len(errors)} validation error(s):\n  - "
            + "\n  - ".join(errors)
        )
    return result


def check_version(config: dict[str, Any]) -> PreflightResult:
    result = PreflightResult()
    msg = mig.version_mismatch_error(config)
    if msg:
        result.errors.append(f"version: {msg}")
    return result


def check_snapshot(config: dict[str, Any]) -> PreflightResult:
    result = PreflightResult()
    if not snap.SNAPSHOT_PATH.exists():
        result.warnings.append(
            "snapshot: no snapshot file — run "
            "`python scripts/snapshot_kind_config.py --update` to seed."
        )
        return result
    try:
        d = snap.diff_against_snapshot(config)
    except Exception as exc:
        result.warnings.append(f"snapshot: could not compute diff ({exc})")
        return result
    if not snap.is_empty(d):
        n = len(d["added"]) + len(d["removed"]) + len(d["changed"])
        result.warnings.append(
            f"snapshot: {n} value drift(s) vs "
            f"{snap.SNAPSHOT_PATH.name}:\n"
            + snap.format_diff(d)
            + "\n  Run `python scripts/snapshot_kind_config.py --update` "
            "to acknowledge."
        )
    return result


# --- Orchestration ---------------------------------------------------------


def run(
    config: dict[str, Any] | None = None,
    *,
    include_snapshot: bool = True,
) -> PreflightResult:
    """Run all enabled checks and return the aggregated result.

    If `config` is None, reads config/kind_config.json off disk. Pass
    `include_snapshot=False` to skip the snapshot diff (useful when
    booting brain in a context where snapshot drift is expected and
    acceptable, e.g. during migration work).
    """
    result = PreflightResult()
    if config is None:
        try:
            config = snap.load_config()
        except FileNotFoundError as exc:
            result.errors.append(f"config: file not found ({exc})")
            return result
        except Exception as exc:
            result.errors.append(f"config: could not parse JSON ({exc})")
            return result

    result.merge(check_schema(config))
    if result.errors:
        # Don't run later checks on a structurally broken config — their
        # output would just be noise on top of the real issue.
        return result

    result.merge(check_version(config))
    if include_snapshot:
        result.merge(check_snapshot(config))
    return result


def assert_valid_config_state(
    config: dict[str, Any] | None = None,
    *,
    include_snapshot: bool = True,
    print_warnings: bool = True,
) -> PreflightResult:
    """Run preflight; raise PreflightError on ERROR, print warnings on WARN.

    Intended for brain boot. Honors SANCTUM_SKIP_CONFIG_VALIDATION=1 — in
    that mode every check is downgraded to a warning so schema iteration
    isn't blocked.
    """
    result = run(config, include_snapshot=include_snapshot)

    if os.environ.get(_SKIP_ENV):
        # Downgrade: move errors into warnings so nothing blocks boot.
        result.warnings = ["(downgraded) " + e for e in result.errors] + result.warnings
        result.errors = []

    if print_warnings:
        for w in result.warnings:
            print(f"preflight WARN: {w}", file=sys.stderr)

    if result.errors:
        raise PreflightError(
            "preflight FAILED:\n"
            + "\n".join(f"  - {e}" for e in result.errors)
        )
    return result


# --- CLI -------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-snapshot",
        action="store_true",
        help="Skip the snapshot drift check.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the 'all checks passed' message on clean state.",
    )
    args = parser.parse_args(argv)

    result = run(include_snapshot=not args.no_snapshot)

    for w in result.warnings:
        print(f"WARN: {w}", file=sys.stderr)
    for e in result.errors:
        print(f"ERROR: {e}", file=sys.stderr)

    if result.errors:
        return 1
    if not args.quiet and not result.warnings:
        print("preflight: OK (schema + version" + ("" if args.no_snapshot else " + snapshot") + ")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
