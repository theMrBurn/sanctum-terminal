"""Migration runner tests — config-lock #5.

Covers discover() monotonicity enforcement, up/down orchestration, the
seed migration itself, and the shipped config's version stamp.
"""
from __future__ import annotations

import sys
import types

import pytest

from core.systems import kind_config_migrations as mig
from core.systems import kind_config_snapshot as snap


# --- Discovery -------------------------------------------------------------


def test_discover_returns_sorted_migrations() -> None:
    migrations = mig.discover()
    assert migrations, "at least the seed migration should exist"
    versions = [m.version for m in migrations]
    assert versions == sorted(versions)


def test_current_version_matches_last_migration() -> None:
    migrations = mig.discover()
    assert mig.current_version() == migrations[-1].version


def test_seed_migration_is_version_1() -> None:
    migrations = mig.discover()
    assert migrations[0].version == 1
    assert "seed" in migrations[0].name.lower()


# --- Version reading -------------------------------------------------------


def test_version_of_missing_field_returns_0() -> None:
    assert mig.version_of({"kinds": {}}) == 0


def test_version_of_non_int_raises() -> None:
    with pytest.raises(mig.MigrationError):
        mig.version_of({"schema_version": "1"})


def test_needs_migration_true_when_stale() -> None:
    assert mig.needs_migration({"schema_version": 0, "kinds": {}})


def test_needs_migration_false_when_current() -> None:
    config = {"schema_version": mig.current_version(), "kinds": {}}
    assert not mig.needs_migration(config)


# --- Forward / backward migration ------------------------------------------


def test_migrate_applies_seed_forward() -> None:
    config = {"kinds": {}}  # no schema_version = version 0
    migrated = mig.migrate(config, target=1)
    assert migrated["schema_version"] == 1
    assert migrated["kinds"] == {}


def test_migrate_reverses_on_target_zero() -> None:
    config = {"schema_version": 1, "kinds": {}}
    reversed_ = mig.migrate(config, target=0)
    assert "schema_version" not in reversed_
    assert reversed_["kinds"] == {}


def test_migrate_is_noop_when_already_at_target() -> None:
    config = {"schema_version": 1, "kinds": {"x": {"class": "c"}}}
    result = mig.migrate(config, target=1)
    assert result == config


def test_migrate_default_target_is_current_version() -> None:
    config = {"kinds": {}}
    result = mig.migrate(config)  # target=None -> current_version
    assert result["schema_version"] == mig.current_version()


def test_migrate_rejects_out_of_range_target() -> None:
    with pytest.raises(mig.MigrationError):
        mig.migrate({"kinds": {}}, target=999)


def test_migrate_does_not_mutate_input() -> None:
    config = {"kinds": {}}
    mig.migrate(config, target=1)
    assert "schema_version" not in config  # input unchanged


# --- version_mismatch_error message ---------------------------------------


def test_version_mismatch_error_none_when_current() -> None:
    config = {"schema_version": mig.current_version(), "kinds": {}}
    assert mig.version_mismatch_error(config) is None


def test_version_mismatch_error_suggests_forward_migrate() -> None:
    msg = mig.version_mismatch_error({"kinds": {}})
    assert msg is not None
    assert "migrate" in msg.lower()
    assert "--target" in msg


def test_version_mismatch_error_flags_too_new() -> None:
    msg = mig.version_mismatch_error({"schema_version": 999, "kinds": {}})
    assert msg is not None
    assert "newer" in msg.lower()


# --- Discovery hardening ---------------------------------------------------


def test_discover_rejects_version_gaps(monkeypatch) -> None:
    """Fake a package with migrations [1, 3] — gap at 2 must raise."""
    fake_pkg_name = "core.systems.migrations.kind_config"

    fake_mod_1 = types.ModuleType(f"{fake_pkg_name}.001_seed_schema_version")
    fake_mod_1.VERSION = 1
    fake_mod_1.DESCRIPTION = "first"
    fake_mod_1.up = lambda c: c
    fake_mod_1.down = lambda c: c

    fake_mod_3 = types.ModuleType(f"{fake_pkg_name}.003_gap")
    fake_mod_3.VERSION = 3
    fake_mod_3.DESCRIPTION = "third"
    fake_mod_3.up = lambda c: c
    fake_mod_3.down = lambda c: c

    # Build a fake pkgutil.iter_modules result; patch importlib to return
    # our two fake modules.
    class FakeInfo:
        def __init__(self, name):
            self.name = name

    fake_pkg = types.ModuleType(fake_pkg_name)
    fake_pkg.__path__ = []  # make it look like a package

    def fake_iter_modules(_):
        return [FakeInfo("001_seed_schema_version"), FakeInfo("003_gap")]

    def fake_import_module(name):
        if name == fake_pkg_name:
            return fake_pkg
        if name.endswith("001_seed_schema_version"):
            return fake_mod_1
        if name.endswith("003_gap"):
            return fake_mod_3
        raise ImportError(name)

    monkeypatch.setattr(mig, "pkgutil", types.SimpleNamespace(iter_modules=fake_iter_modules))
    monkeypatch.setattr(mig, "importlib", types.SimpleNamespace(import_module=fake_import_module))

    with pytest.raises(mig.MigrationError, match="monotonic"):
        mig.discover()


# --- Live config guard -----------------------------------------------------


def test_engagement_slot_migration_idempotent() -> None:
    """002_engagement_slot.up is a pure version bump — re-running it on
    a config that already has engagement fields must not duplicate or
    rewrite them."""
    config = {
        "schema_version": 1,
        "kinds": {
            "rat": {
                "class": "life",
                "engagement": {
                    "engagement_type": "compose_three",
                    "rule_args": {"target_count": 3},
                },
            },
        },
    }
    once = mig.migrate(config, target=2)
    twice = mig.migrate(once, target=2)
    assert once == twice
    assert once["kinds"]["rat"]["engagement"]["engagement_type"] == "compose_three"


def test_engagement_slot_down_strips_engagement() -> None:
    """002_engagement_slot.down removes engagement blocks — a config
    written at v2 that walks back to v1 must shed the new optional slot."""
    config = {
        "schema_version": 2,
        "kinds": {
            "rat": {
                "class": "life",
                "engagement": {"engagement_type": "compose_three"},
            },
            "stone": {"class": "geo"},  # no engagement — must stay untouched
        },
    }
    reversed_ = mig.migrate(config, target=1)
    assert "engagement" not in reversed_["kinds"]["rat"]
    assert reversed_["kinds"]["stone"] == {"class": "geo"}
    assert reversed_["schema_version"] == 1


def test_shipped_config_is_current_version() -> None:
    """config/kind_config.json must be at current_version after migrations land."""
    config = snap.load_config()
    assert mig.version_of(config) == mig.current_version(), (
        "config/kind_config.json is not at the latest schema_version. "
        "Run `python scripts/migrate_kind_config.py` to migrate forward."
    )
