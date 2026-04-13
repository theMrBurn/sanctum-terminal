"""Phase 2/5 collision radius contract: kind_config physics.collision_radius
holds the canonical values. Post-Phase-5 the HARD_OBJECTS dict is itself
derived from kind_config, so comparing them would be trivially true.
Instead this test asserts the EXPECTED RADII inline — a frozen contract
that catches accidental edits to load-bearing collision values.
"""
from __future__ import annotations

import pytest

from core.systems import kind_config


# Frozen collision-radius contract. Edits here are deliberate — these
# values feed world_gen clearance/spacing AND brain's COLLISION_RADII
# (player push-out). Changing any of them changes hub composition and
# walkable space.
EXPECTED_COLLISION_RADII = {
    "boulder":          2.5,
    "column":           4.0,
    "mega_column":      5.0,
    "buttress":         3.0,
    "stalagmite":       1.2,
    "giant_fungus":     1.2,
    "crystal_cluster":  1.0,
    "dead_log":         0.8,
    "bone_pile":        0.4,
    "horizon_form":     3.0,
    "horizon_mid":      2.0,
    "horizon_near":     1.0,
    "rat":              0.6,
    "rat_ice":          0.6,
    "rat_fire":         0.6,
    "clay_pot":         1.2,
    "treasure_chest":   1.5,
}


@pytest.mark.parametrize("name,expected_radius", sorted(EXPECTED_COLLISION_RADII.items()))
def test_collision_radius_contract(name, expected_radius):
    """Every load-bearing kind has physics.collision_radius matching the
    frozen contract above."""
    cfg = kind_config.kind(name)
    actual = cfg.get("physics", {}).get("collision_radius")
    assert actual is not None, (
        f"{name}: physics.collision_radius missing from kind_config")
    assert actual == expected_radius, (
        f"{name}: collision_radius drift — "
        f"kind_config={actual} vs contract={expected_radius}. "
        "If this is intentional, update EXPECTED_COLLISION_RADII.")


def test_brain_collision_lookup_uses_kind_config():
    """The brain's _collision_radius_for() helper reads kind_config."""
    from brain_server import _collision_radius_for
    assert _collision_radius_for("rat") == 0.6
    assert _collision_radius_for("boulder") == 2.5
    # Unknown kind returns 0.0 (no physics block, no fallback)
    assert _collision_radius_for("__not_a_kind__") == 0.0


def test_hard_objects_is_derived_from_kind_config():
    """biome_data.HARD_OBJECTS must now be the kind_config-derived shim,
    not a literal dict. Sanity check that Phase 5 deletion stuck."""
    from core.systems.biome_data import HARD_OBJECTS
    # Every entry in HARD_OBJECTS must have a kind_config physics.collision_radius
    for name, radius in HARD_OBJECTS.items():
        cfg_radius = kind_config.kind(name).get("physics", {}).get("collision_radius")
        assert cfg_radius == radius, (
            f"HARD_OBJECTS[{name}]={radius} but kind_config says {cfg_radius} — "
            "shim conversion broken")

