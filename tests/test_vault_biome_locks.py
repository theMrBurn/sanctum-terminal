"""biome_locks vault table + helpers (variant_deck PR 2026-05-17)."""
from __future__ import annotations

import os
import tempfile

import pytest

from core import vault as vault_mod


@pytest.fixture
def vault():
    """Fresh isolated vault per test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    v = vault_mod.vault(db_path=path)
    yield v
    os.unlink(path)


def test_unlocked_biome_returns_none(vault):
    assert vault.biome_locked_seed("phantom_biome") is None


def test_lock_then_read(vault):
    vault.biome_lock("cavern", 12345)
    assert vault.biome_locked_seed("cavern") == 12345


def test_lock_upserts_existing(vault):
    vault.biome_lock("cavern", 1)
    vault.biome_lock("cavern", 2)
    assert vault.biome_locked_seed("cavern") == 2


def test_unlock_returns_true_when_locked(vault):
    vault.biome_lock("outdoor", 99)
    assert vault.biome_unlock("outdoor") is True
    assert vault.biome_locked_seed("outdoor") is None


def test_unlock_returns_false_when_unlocked(vault):
    assert vault.biome_unlock("never_was_locked") is False


def test_locks_are_per_biome(vault):
    vault.biome_lock("cavern", 1)
    vault.biome_lock("outdoor", 2)
    assert vault.biome_locked_seed("cavern") == 1
    assert vault.biome_locked_seed("outdoor") == 2


def test_biome_locks_all(vault):
    vault.biome_lock("a", 11)
    vault.biome_lock("b", 22)
    locks = vault.biome_locks_all()
    assert locks == {"a": 11, "b": 22}


def test_seed_stored_as_int(vault):
    """Vault should coerce numeric inputs to int — sql layer is strict."""
    vault.biome_lock("cavern", "42")          # type: ignore[arg-type]
    assert vault.biome_locked_seed("cavern") == 42
    assert isinstance(vault.biome_locked_seed("cavern"), int)
