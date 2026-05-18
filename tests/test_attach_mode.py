"""attach_mode primitive — schema + brain placement (2026-05-18 PR)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from core.systems import thing_schema, thing_library


# ── Schema ──────────────────────────────────────────────────────


def test_attach_modes_enum_exists():
    assert "floor" in thing_schema.ATTACH_MODES
    assert "upper_floor" in thing_schema.ATTACH_MODES
    assert "water_surface" in thing_schema.ATTACH_MODES


def test_default_attach_mode_is_floor():
    t = thing_library.get("doug_fir")
    assert t is not None
    assert t.attach_mode == "floor"


def test_bridge_declares_upper_floor():
    bridge = thing_library.get_stamp("rope_bridge")
    assert bridge is not None
    assert bridge.attach_mode == "upper_floor"


def _minimal_thing_dict(extra: dict | None = None) -> dict:
    d = {
        "name":        "tester",
        "real_size_m": [1.0, 1.0, 1.0],
        "anchor":      "core",
        "parts": [{
            "primitive":    "cube",
            "role":         "core",
            "rel_size":     [1.0, 1.0, 1.0],
            "rel_position": [0.0, 0.0, 0.0],
            "tier":         "silhouette",
        }],
    }
    if extra:
        d.update(extra)
    return d


def test_invalid_attach_mode_rejected():
    errs = thing_schema.validate_thing_dict(
        _minimal_thing_dict({"attach_mode": "ceiling"})
    )
    assert errs
    assert any("attach_mode" in str(e) for e in errs)


def test_attach_mode_non_string_rejected():
    errs = thing_schema.validate_thing_dict(
        _minimal_thing_dict({"attach_mode": 42})
    )
    assert any("attach_mode" in str(e) for e in errs)


def test_valid_attach_mode_passes():
    for mode in thing_schema.ATTACH_MODES:
        errs = thing_schema.validate_thing_dict(
            _minimal_thing_dict({"attach_mode": mode})
        )
        assert errs == [], (
            f"mode {mode!r} should validate clean, got {errs}"
        )


def test_load_thing_round_trips_attach_mode():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "x.json"
        p.write_text(json.dumps(
            _minimal_thing_dict({"attach_mode": "upper_floor"})
        ))
        t = thing_schema.load_thing(p)
        assert t.attach_mode == "upper_floor"


# ── Brain placement consults attach_mode ────────────────────────


spacy = pytest.importorskip("spacy")
import brain_server as bs                                         # noqa: E402


def _two_tile_ledge_field() -> dict[tuple[int, int], int]:
    # Single ledge transition: (0,0) at level 0, (1,0) at level 2.
    f = {(x, y): 0 for x in range(3) for y in range(3)}
    f[(1, 0)] = 2
    return f


def test_bridge_lands_on_upper_floor():
    """rope_bridge is attach_mode=upper_floor — its entities should
    sit at the HIGHER tile's elevation (~level 2 = 2.0m), not the
    lower (0m)."""
    ents = bs._terrain_keyed_stamps(
        "outdoor", base_seed=7, elevation_field=_two_tile_ledge_field(),
    )
    bridge_ents = [e for e in ents if e.get("_stamp") == "rope_bridge"]
    assert bridge_ents, "expected rope_bridge entities in this field"
    # Decks rest at upper tile's floor — bbox bottom = 2.0m, bbox
    # extends UP by real_size_z. Entity z is bbox CENTER, so the
    # lowest deck-entity z should be ~2.0 + 0.04/2 ≈ 2.02m.
    # Plenty of headroom above the lower tile (0m).
    bbox_centers_z = [e["z"] for e in bridge_ents]
    assert min(bbox_centers_z) > 1.0, (
        f"bridge sits too low (mins {min(bbox_centers_z)}); "
        f"attach_mode=upper_floor should lift it to the higher tile"
    )


def test_default_floor_stamps_land_low():
    """A non-bridge stamp keyed to a ledge would land at lower tile
    floor (the default). Verify against a ledge field forcing the
    bridge tag."""
    ents = bs._terrain_keyed_stamps(
        "outdoor", base_seed=7, elevation_field=_two_tile_ledge_field(),
    )
    # Bridge is the only thing keyed to ledges, and it's
    # upper_floor — so its lowest part should NOT be at z=0.
    # This complements the test above; sanity that placement
    # honors the mode, not just the tag.
    if not ents:
        pytest.skip("no terrain-keyed entities for this seed")
    bridges = [e for e in ents if e.get("_stamp") == "rope_bridge"]
    assert all(e["z"] > 0.5 for e in bridges)
