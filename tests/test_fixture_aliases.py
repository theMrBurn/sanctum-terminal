"""Per-biome hub-fixture aliasing — kind=behavior, visual_kind=biome skin.

Pins that the alias map per biome merges correctly into the entity dict
emitted by the brain, without changing the behavioral kind that engage
handlers in the client check.
"""
from __future__ import annotations

import pytest

from core.systems.biome_data import BIOME_REGISTRY


def _spawn_pillar(biome_name: str) -> dict:
    """Replicate the brain's pillar spawn shape — defaults + biome alias
    update. Mirrors `brain_server.py:1326-1342` so any drift here flags
    that the spawn-merge logic moved."""
    aliases = BIOME_REGISTRY.get(biome_name, {}).get("fixture_aliases", {})
    ent = {
        "id": -1100,
        "kind": "pillar_reflection",
        "x": 0.0, "y": 0.0, "z": 0.0,
        "sx": 0.6, "sy": 0.6, "sz": 3.0,
        "heading": 0.0,
        "r": 0.7, "g": 0.5, "b": 1.0,
        "collision_radius": 0.6,
    }
    ent.update(aliases.get("pillar_reflection", {}))
    return ent


def _spawn_fridge(biome_name: str) -> dict:
    aliases = BIOME_REGISTRY.get(biome_name, {}).get("fixture_aliases", {})
    ent = {
        "id": -1200,
        "kind": "fridge",
        "x": 0.0, "y": 0.0, "z": 0.0,
        "sx": 0.7, "sy": 0.4, "sz": 1.4,
        "heading": 0.0,
        "r": 0.85, "g": 0.88, "b": 0.90,
        "collision_radius": 0.7,
    }
    ent.update(aliases.get("fridge", {}))
    return ent


# ── Behavioral kind preserved across biomes ────────────────────────


@pytest.mark.parametrize("biome", ["cavern", "outdoor", "workroom"])
def test_pillar_kind_unchanged_in_every_biome(biome):
    """Engage handlers in client check `target_kind == "pillar_reflection"`
    — the alias system MUST NOT touch the kind field."""
    ent = _spawn_pillar(biome)
    assert ent["kind"] == "pillar_reflection"


@pytest.mark.parametrize("biome", ["cavern", "outdoor", "workroom"])
def test_fridge_kind_unchanged_in_every_biome(biome):
    """`engage_fridge` verb is gated on `kind == "fridge"`. Same here."""
    ent = _spawn_fridge(biome)
    assert ent["kind"] == "fridge"


# ── Visual_kind swaps per biome ────────────────────────────────────


def test_cavern_pillar_renders_as_crystal_cluster():
    """Cavern aliases pillar_reflection → crystal_cluster geometry."""
    ent = _spawn_pillar("cavern")
    assert ent["visual_kind"] == "crystal_cluster"


def test_outdoor_pillar_renders_as_dead_log():
    ent = _spawn_pillar("outdoor")
    assert ent["visual_kind"] == "dead_log"


def test_workroom_pillar_uses_no_visual_alias():
    """Workroom = canonical sandbox; placeholder visual stays."""
    ent = _spawn_pillar("workroom")
    assert "visual_kind" not in ent  # no override


def test_cavern_fridge_renders_as_boulder():
    ent = _spawn_fridge("cavern")
    assert ent["visual_kind"] == "boulder"


def test_outdoor_fridge_renders_as_boulder_too():
    """Outdoor also picks boulder — same mesh, different tint."""
    ent = _spawn_fridge("outdoor")
    assert ent["visual_kind"] == "boulder"


# ── Color / scale tints diverge per biome ──────────────────────────


def test_cavern_fridge_color_overrides_default_pale():
    """Cavern fridge is cool stone, not appliance white."""
    ent = _spawn_fridge("cavern")
    assert ent["r"] != 0.85  # was the placeholder white
    assert ent["b"] != 0.90


def test_outdoor_fridge_is_mossy_green_dominant():
    ent = _spawn_fridge("outdoor")
    assert ent["g"] > ent["r"]  # green-dominant
    assert ent["g"] > ent["b"]


def test_cavern_pillar_color_violet_in_cavern():
    """Cavern pillar leans purple — meta-pillar palette adapted to crystal."""
    ent = _spawn_pillar("cavern")
    assert ent["r"] > 0.5
    assert ent["b"] > ent["r"]   # blue-dominant violet


def test_outdoor_pillar_color_warm_brown():
    """Dead log = brown."""
    ent = _spawn_pillar("outdoor")
    assert ent["r"] > ent["g"]
    assert ent["r"] > ent["b"]


# ── Full payload preserves required fields ────────────────────────


def test_alias_does_not_drop_collision_radius():
    """Alias merge must not strip required engage fields."""
    for biome in ("cavern", "outdoor", "workroom"):
        pillar = _spawn_pillar(biome)
        assert pillar["collision_radius"] == 0.6
        fridge = _spawn_fridge(biome)
        assert fridge["collision_radius"] == 0.7


def test_alias_preserves_position():
    for biome in ("cavern", "outdoor", "workroom"):
        pillar = _spawn_pillar(biome)
        assert "x" in pillar and "y" in pillar and "z" in pillar


def test_unknown_biome_falls_through_to_defaults():
    """If a biome doesn't define fixture_aliases, defaults render unchanged."""
    aliases = BIOME_REGISTRY.get("nonexistent_biome", {}).get("fixture_aliases", {})
    assert aliases == {}
    ent = _spawn_pillar("nonexistent_biome")
    # No visual_kind, default placeholder color
    assert "visual_kind" not in ent
    assert ent["r"] == 0.7
    assert ent["b"] == 1.0


# ── Registry consistency ───────────────────────────────────────────


def test_every_real_biome_has_fixture_aliases():
    """Every biome in BIOME_REGISTRY must declare a (possibly empty)
    fixture_aliases — prevents silent drop-throughs when a future biome
    is added but forgets the override config."""
    for biome_name, cfg in BIOME_REGISTRY.items():
        assert "fixture_aliases" in cfg, (
            f"biome {biome_name!r} missing fixture_aliases entry"
        )
