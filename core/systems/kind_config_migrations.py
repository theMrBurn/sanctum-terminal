"""Migration runner for config/kind_config.json — config-lock #5.

Renames and structural reshapes are expensive when done by hand-rolled sed:
a rename of `collision_radius` to `physics.collision_radius` touched every
kind and needed the loader updated in lockstep. The migration framework
turns those edits into numbered forward/back steps, each responsible for a
single reshape, runnable via a CLI.

A migration module lives at `core/systems/migrations/kind_config/NNN_name.py`
and exports:
    VERSION = <int>             # monotonic, no gaps
    DESCRIPTION = "<short>"
    def up(config) -> config     # forward transform
    def down(config) -> config   # reverse transform

`CURRENT_VERSION` is the highest migration the code currently understands;
configs with a lower version must be migrated forward before load. Configs
with a higher version mean the repo is on an older branch than the config
— load fails with a clear message rather than silently ignoring new fields.
"""
from __future__ import annotations

import importlib
import pkgutil
import re
from dataclasses import dataclass
from typing import Any, Callable

_MIGRATIONS_PACKAGE = "core.systems.migrations.kind_config"
_FILENAME_RE = re.compile(r"^(\d{3})_[a-z0-9_]+$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    description: str
    up: Callable[[dict[str, Any]], dict[str, Any]]
    down: Callable[[dict[str, Any]], dict[str, Any]]


class MigrationError(RuntimeError):
    """Raised when migrations are missing, non-monotonic, or fail to apply."""


def discover() -> list[Migration]:
    """Load every migration module under _MIGRATIONS_PACKAGE, sorted by version.

    Raises MigrationError if version numbers aren't monotonic-from-1 with no
    gaps. Catches "forgot to increment" and "two migrations at same version"
    before they corrupt a config.
    """
    pkg = importlib.import_module(_MIGRATIONS_PACKAGE)
    migrations: list[Migration] = []
    for info in pkgutil.iter_modules(pkg.__path__):
        match = _FILENAME_RE.match(info.name)
        if not match:
            continue
        module = importlib.import_module(f"{_MIGRATIONS_PACKAGE}.{info.name}")
        migrations.append(
            Migration(
                version=int(module.VERSION),
                name=info.name,
                description=str(module.DESCRIPTION),
                up=module.up,
                down=module.down,
            )
        )
    migrations.sort(key=lambda m: m.version)
    for idx, m in enumerate(migrations, start=1):
        if m.version != idx:
            raise MigrationError(
                f"migration versions must be monotonic from 1 with no gaps: "
                f"expected {idx} at position {idx}, got {m.version} ({m.name!r})"
            )
    return migrations


def current_version() -> int:
    """Highest version the codebase knows how to produce."""
    migrations = discover()
    return migrations[-1].version if migrations else 0


def version_of(config: dict[str, Any]) -> int:
    """Return the config's declared schema_version, or 0 if pre-versioned."""
    v = config.get("schema_version", 0)
    if not isinstance(v, int):
        raise MigrationError(
            f"schema_version must be int, got {type(v).__name__}: {v!r}"
        )
    return v


def needs_migration(config: dict[str, Any]) -> bool:
    return version_of(config) != current_version()


def migrate(
    config: dict[str, Any],
    target: int | None = None,
) -> dict[str, Any]:
    """Apply up/down migrations to move config to target version.

    target=None means migrate to current_version(). Raises MigrationError
    if the target is out of range or if a migration module errors.
    """
    migrations = discover()
    max_version = migrations[-1].version if migrations else 0
    if target is None:
        target = max_version
    if target < 0 or target > max_version:
        raise MigrationError(
            f"target version {target} out of range [0, {max_version}]"
        )

    result = dict(config)
    start = version_of(result)

    if start == target:
        return result

    if start < target:
        for m in migrations:
            if start < m.version <= target:
                try:
                    result = m.up(result)
                except Exception as exc:
                    raise MigrationError(
                        f"{m.name}.up failed: {exc}"
                    ) from exc
                result["schema_version"] = m.version
    else:
        # Walk backward: apply down() of every migration strictly above target.
        for m in reversed(migrations):
            if target < m.version <= start:
                try:
                    result = m.down(result)
                except Exception as exc:
                    raise MigrationError(
                        f"{m.name}.down failed: {exc}"
                    ) from exc
                # After down(), the config is at version m.version - 1.
                new_version = m.version - 1
                if new_version > 0:
                    result["schema_version"] = new_version
                else:
                    result.pop("schema_version", None)
    return result


def version_mismatch_error(config: dict[str, Any]) -> str | None:
    """Return a human-readable error if config version != current, else None.

    Caller is expected to short-circuit (preflight, brain boot) or to run
    migrate() — this helper just formats the message.
    """
    got = version_of(config)
    want = current_version()
    if got == want:
        return None
    if got < want:
        return (
            f"config schema_version is {got}, code expects {want}. "
            f"Run `python scripts/migrate_kind_config.py --target {want}` "
            "to migrate forward."
        )
    return (
        f"config schema_version is {got} but code only supports up to {want}. "
        "The config was written by a newer branch of the code. Pull the "
        "branch that produced it, or run --target to migrate it backward."
    )
