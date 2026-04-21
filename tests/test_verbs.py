"""Verb taxonomy loader tests — identifiers-only contract.

Guards the shape of config/verbs.json so the brain and (future) Godot-side
readers can trust the 4 pools exist with the design_thoughts.txt:598-600
identifiers pinned. Does NOT assert tuning values — those arrive when the
renderer consumes them.
"""
from __future__ import annotations

from core.systems import verbs


def test_four_pools_present() -> None:
    assert verbs.cast_trajectories()
    assert verbs.cast_effects()
    assert verbs.contact_verbs()
    assert verbs.held_object_verbs()


def test_cast_trajectories_pinned() -> None:
    # From design_thoughts.txt:598 — the 5 trajectory types.
    expected = {"straight", "fast", "slow_float", "instant", "arc"}
    assert expected <= set(verbs.cast_trajectories().keys())


def test_cast_effects_pinned() -> None:
    # From design_thoughts.txt:598 — the 13 effect identifiers.
    expected = {
        "light", "dark", "hot", "cold", "metal", "ice", "fire", "laser",
        "bolt", "dart", "splash", "air", "electric",
    }
    assert expected <= set(verbs.cast_effects().keys())


def test_contact_verbs_pinned() -> None:
    # From design_thoughts.txt:600 — the 11 contact verbs.
    expected = {
        "touch", "hit", "kick", "bonk", "split", "chop",
        "drop", "toss", "pebble", "bump", "shrug",
    }
    assert expected <= set(verbs.contact_verbs().keys())


def test_held_object_verbs_pinned() -> None:
    # From design_thoughts.txt:600 — the 5 held-object variants.
    expected = {"stabbing", "thrusting", "slashing", "bashing", "smashing"}
    assert expected <= set(verbs.held_object_verbs().keys())


def test_doc_sentinels_stripped() -> None:
    for pool in (
        verbs.cast_trajectories(),
        verbs.cast_effects(),
        verbs.contact_verbs(),
        verbs.held_object_verbs(),
    ):
        assert not any(k.startswith("_") for k in pool.keys())


def test_validate_cast_accepts_known_pairs() -> None:
    assert verbs.validate_cast("straight", "fire")
    assert verbs.validate_cast("arc", "electric")
    assert verbs.validate_cast("instant", "laser")


def test_validate_cast_rejects_unknowns() -> None:
    assert not verbs.validate_cast("teleport", "fire")
    assert not verbs.validate_cast("straight", "sludge")


def test_validate_contact_accepts_plain_and_held() -> None:
    assert verbs.validate_contact("hit")
    assert verbs.validate_contact("hit", "slashing")


def test_validate_contact_rejects_unknowns() -> None:
    assert not verbs.validate_contact("wiggle")
    assert not verbs.validate_contact("hit", "flailing")


def test_entries_carry_label_field() -> None:
    # Label is the lowest-common shape contract — every renderer/HUD will
    # want a human-readable name.
    for pool_fn in (
        verbs.cast_trajectories,
        verbs.cast_effects,
        verbs.contact_verbs,
        verbs.held_object_verbs,
    ):
        for key, entry in pool_fn().items():
            assert "label" in entry, f"{key} missing label in {pool_fn.__name__}"
