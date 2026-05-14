"""thing_schema + thing_renderer — reliable wireframe math.

Per the new direction (post-spec-18-pivot): things have explicit
`real_size_m` bounding box + fractional positions. Math is bounded
and predictable so descriptions → wireframes don't drift.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from core.systems import thing_renderer, thing_schema


# ── Fixtures ────────────────────────────────────────────────────


def _good_thing_dict():
    return {
        "name": "longsword",
        "real_size_m": [0.15, 0.04, 1.10],
        "anchor": "blade",
        "parts": [
            {
                "primitive":     "tapered_vertical",
                "role":          "blade",
                "rel_size":      [0.20, 0.10, 0.85],
                "rel_position":  [0.0, 0.0, 0.10],
            },
            {
                "primitive":     "banner",
                "role":          "crossguard",
                "rel_size":      [1.00, 0.10, 0.06],
                "rel_position":  [0.0, 0.0, -0.30],
            },
        ],
    }


# ── Validation: happy path ──────────────────────────────────────


def test_good_thing_validates():
    errs = thing_schema.validate_thing_dict(_good_thing_dict())
    assert errs == []


def test_parse_thing_returns_dataclass():
    t = thing_schema.parse_thing(_good_thing_dict())
    assert t.name == "longsword"
    assert t.real_size_m == (0.15, 0.04, 1.10)
    assert t.anchor == "blade"
    assert len(t.parts) == 2
    assert t.parts[0].primitive == "tapered_vertical"


# ── Validation: top-level errors ────────────────────────────────


def test_missing_name():
    d = _good_thing_dict()
    del d["name"]
    errs = thing_schema.validate_thing_dict(d)
    assert any("name" in str(e) for e in errs)


def test_real_size_too_small():
    d = _good_thing_dict()
    d["real_size_m"] = [0.001, 0.001, 0.001]      # below SIZE_MIN_M (0.02)
    errs = thing_schema.validate_thing_dict(d)
    assert any("real_size_m" in str(e) for e in errs)


def test_real_size_too_large():
    d = _good_thing_dict()
    d["real_size_m"] = [100.0, 100.0, 100.0]
    errs = thing_schema.validate_thing_dict(d)
    assert any("real_size_m" in str(e) for e in errs)


def test_real_size_wrong_arity():
    d = _good_thing_dict()
    d["real_size_m"] = [1.0, 2.0]
    errs = thing_schema.validate_thing_dict(d)
    assert any("real_size_m" in str(e) for e in errs)


def test_anchor_must_match_a_part_role():
    d = _good_thing_dict()
    d["anchor"] = "phantom_role"
    errs = thing_schema.validate_thing_dict(d)
    assert any("anchor" in str(e) and "not found" in str(e) for e in errs)


def test_no_parts():
    d = _good_thing_dict()
    d["parts"] = []
    errs = thing_schema.validate_thing_dict(d)
    assert any("parts" in str(e) for e in errs)


def test_too_many_parts():
    d = _good_thing_dict()
    d["parts"] = [d["parts"][0]] * 13      # over PARTS_MAX
    errs = thing_schema.validate_thing_dict(d)
    assert any("parts" in str(e) for e in errs)


# ── Validation: part-level errors ───────────────────────────────


def test_unknown_primitive():
    d = _good_thing_dict()
    d["parts"][0]["primitive"] = "blorbo"
    errs = thing_schema.validate_thing_dict(d)
    assert any("blorbo" in str(e) for e in errs)


def test_rel_position_out_of_bounds():
    d = _good_thing_dict()
    d["parts"][0]["rel_position"] = [0.0, 0.0, 0.99]      # > 0.5
    errs = thing_schema.validate_thing_dict(d)
    assert any("rel_position" in str(e) for e in errs)


def test_rel_size_above_one():
    d = _good_thing_dict()
    d["parts"][0]["rel_size"] = [0.5, 0.5, 1.5]
    errs = thing_schema.validate_thing_dict(d)
    assert any("rel_size" in str(e) for e in errs)


def test_rel_size_zero_rejected():
    d = _good_thing_dict()
    d["parts"][0]["rel_size"] = [0.0, 0.5, 0.5]
    errs = thing_schema.validate_thing_dict(d)
    assert any("rel_size" in str(e) for e in errs)


def test_invalid_tier():
    d = _good_thing_dict()
    d["parts"][0]["tier"] = "legendary"
    errs = thing_schema.validate_thing_dict(d)
    assert any("tier" in str(e) for e in errs)


def test_color_out_of_range():
    d = _good_thing_dict()
    d["parts"][0]["color_base"] = [1.5, 0.5, 0.5]
    errs = thing_schema.validate_thing_dict(d)
    assert any("color_base" in str(e) for e in errs)


# ── Loading from disk ────────────────────────────────────────────


def test_load_thing_from_file(tmp_path: Path):
    p = tmp_path / "longsword.json"
    p.write_text(json.dumps(_good_thing_dict()))
    t = thing_schema.load_thing(p)
    assert t.name == "longsword"


def test_load_thing_invalid_raises(tmp_path: Path):
    p = tmp_path / "bad.json"
    d = _good_thing_dict()
    d["parts"][0]["primitive"] = "bogus"
    p.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="validation"):
        thing_schema.load_thing(p)


def test_load_things_from_dir_skips_invalid(tmp_path: Path):
    good = tmp_path / "a.json"
    good.write_text(json.dumps(_good_thing_dict()))
    bad = tmp_path / "b.json"
    bad.write_text("{not even json")
    things = thing_schema.load_things_from_dir(tmp_path)
    assert "longsword" in things
    assert len(things) == 1


# ── Renderer math: expand_thing ─────────────────────────────────


def _make_thing() -> thing_schema.Thing:
    return thing_schema.parse_thing(_good_thing_dict())


def test_expand_emits_one_entity_per_part():
    t = _make_thing()
    out = thing_renderer.expand_thing(t, origin=(0.0, 0.0, 0.0))
    assert len(out) == 2


def test_expand_world_positions_are_correct():
    """blade at rel_position [0, 0, 0.10] in a thing with real_size_m
    height 1.10 → world Z offset = 0.110m. Place origin at z=0.55
    (sword's center if floored), blade Z = 0.66."""
    t = _make_thing()
    out = thing_renderer.expand_thing(t, origin=(0.0, 0.0, 0.55))
    blade = out[0]
    assert math.isclose(blade["z"], 0.55 + 0.10 * 1.10, abs_tol=1e-6)


def test_expand_world_sizes_match_real_size_times_rel():
    """blade has rel_size [0.20, 0.10, 0.85] in a thing with
    real_size_m [0.15, 0.04, 1.10]. So blade world size should be
    [0.03, 0.004, 0.935]."""
    t = _make_thing()
    out = thing_renderer.expand_thing(t, origin=(0.0, 0.0, 0.0))
    blade = out[0]
    assert math.isclose(blade["sx"], 0.15 * 0.20, abs_tol=1e-6)
    assert math.isclose(blade["sy"], 0.04 * 0.10, abs_tol=1e-6)
    assert math.isclose(blade["sz"], 1.10 * 0.85, abs_tol=1e-6)


def test_expand_to_world_z_floors_correctly():
    """expand_thing_to_world_z places the THING'S CENTER at floor_z +
    real_size_z/2 so the bottom of the bounding box sits exactly on
    floor_z."""
    t = _make_thing()
    out = thing_renderer.expand_thing_to_world_z(
        t, origin_xy=(2.0, 3.0), floor_z=0.0)
    # The thing's center should be at z = 1.10/2 = 0.55
    # The blade at rel_position[2]=0.10 should be at z = 0.55 + 0.10*1.10 = 0.66
    blade = out[0]
    assert math.isclose(blade["z"], 0.66, abs_tol=1e-6)


def test_expand_yaw_rotates_in_xy_plane():
    """A part at rel_position [0.5, 0, 0] (offset along +x) rotated by
    90° yaw should land at world +y, not +x."""
    d = _good_thing_dict()
    d["parts"][0]["rel_position"] = [0.5, 0.0, 0.0]
    d["real_size_m"] = [2.0, 2.0, 2.0]
    d["parts"] = [d["parts"][0]]
    d["anchor"] = "blade"
    t = thing_schema.parse_thing(d)
    out = thing_renderer.expand_thing(t, origin=(0.0, 0.0, 0.0), yaw_deg=90.0)
    blade = out[0]
    # Offset = 0.5 * 2.0 = 1.0 along +x in local; after 90° yaw, becomes +y
    assert math.isclose(blade["x"], 0.0, abs_tol=1e-6)
    assert math.isclose(blade["y"], 1.0, abs_tol=1e-6)


def test_expand_entity_kind_routes_to_scan_recipe():
    t = _make_thing()
    out = thing_renderer.expand_thing(t, origin=(0.0, 0.0, 0.0))
    # blade is a tapered_vertical primitive → kind contains "tapered_vertical"
    assert "scan_tapered_vertical" in out[0]["kind"]


def test_expand_emits_color_from_part():
    d = _good_thing_dict()
    d["parts"][0]["color_base"] = [0.5, 0.6, 0.7]
    t = thing_schema.parse_thing(d)
    out = thing_renderer.expand_thing(t, origin=(0.0, 0.0, 0.0))
    blade = out[0]
    assert blade["r"] == 0.5
    assert blade["g"] == 0.6
    assert blade["b"] == 0.7


def test_expand_amber_fallback_when_color_missing():
    t = _make_thing()
    out = thing_renderer.expand_thing(t, origin=(0.0, 0.0, 0.0))
    blade = out[0]
    assert 0.0 < blade["r"] <= 1.0
    assert 0.0 < blade["g"] <= 1.0


def test_expand_unique_entity_ids_per_instance():
    """Two instances of the same thing should produce non-overlapping
    entity IDs."""
    t = _make_thing()
    a = thing_renderer.expand_thing(t, (0, 0, 0), id_base=10000, instance_id=0)
    b = thing_renderer.expand_thing(t, (5, 0, 0), id_base=10000, instance_id=1)
    a_ids = {e["id"] for e in a}
    b_ids = {e["id"] for e in b}
    assert a_ids.isdisjoint(b_ids)


# ── End-to-end: longsword fixture ──────────────────────────────


# ── Tags ────────────────────────────────────────────────────────


def test_tags_optional_default_empty():
    d = _good_thing_dict()
    t = thing_schema.parse_thing(d)
    assert t.tags == []


def test_tags_parse():
    d = _good_thing_dict()
    d["tags"] = ["weapon", "blade", "medieval"]
    t = thing_schema.parse_thing(d)
    assert t.tags == ["weapon", "blade", "medieval"]


def test_tags_must_be_list():
    d = _good_thing_dict()
    d["tags"] = "weapon"
    errs = thing_schema.validate_thing_dict(d)
    assert any("tags" in str(e) for e in errs)


def test_tag_must_be_non_empty_string():
    d = _good_thing_dict()
    d["tags"] = ["weapon", "", "medieval"]
    errs = thing_schema.validate_thing_dict(d)
    assert any("tags" in str(e) for e in errs)


def test_longsword_fixture_validates():
    repo_root = Path(__file__).parent.parent
    p = repo_root / "library" / "things" / "longsword.json"
    if not p.exists():
        pytest.skip("longsword.json fixture missing")
    t = thing_schema.load_thing(p)
    assert t.name == "longsword"
    assert math.isclose(t.real_size_m[2], 1.10)
    # Verify the sword reads as a 1.10m vertical object
    parts_by_role = {p.role: p for p in t.parts}
    assert "blade" in parts_by_role
    assert "pommel" in parts_by_role
    # Blade above center, pommel below — math sanity
    assert parts_by_role["blade"].rel_position[2] > 0
    assert parts_by_role["pommel"].rel_position[2] < 0
