"""stamp_library — library/stamps/ loader + tag filter."""
from __future__ import annotations

from core.systems import thing_library


# ── Loader ──────────────────────────────────────────────────────


def test_stamps_dir_resolves():
    d = thing_library.stamps_dir()
    assert d.name == "stamps"
    assert d.parent.name == "library"


def test_get_all_stamps_loads_fixtures():
    stamps = thing_library.get_all_stamps()
    assert "wooden_ladder" in stamps
    assert "stone_staircase" in stamps
    assert "rope_bridge" in stamps
    assert "wooden_door" in stamps


def test_list_stamp_names_sorted():
    names = thing_library.list_stamp_names()
    assert names == sorted(names)
    assert "wooden_ladder" in names


def test_get_stamp_returns_thing():
    s = thing_library.get_stamp("rope_bridge")
    assert s is not None
    assert s.name == "rope_bridge"
    assert len(s.parts) > 0


def test_get_stamp_unknown_returns_none():
    assert thing_library.get_stamp("nonexistent_stamp_xyz") is None


# ── Tag filter ──────────────────────────────────────────────────


def test_find_stamps_by_tags_architecture():
    arch = thing_library.find_stamps_by_tags(include=["architecture"])
    assert len(arch) == 4


def test_find_stamps_by_tags_exclude():
    no_pnw = thing_library.find_stamps_by_tags(
        include=["architecture"], exclude=["pnw"],
    )
    # All current stamps are PNW; exclude should drop them all.
    assert no_pnw == []


def test_find_stamps_by_tags_match_all():
    rope = thing_library.find_stamps_by_tags(
        include=["bridge", "rope"], match_all=True,
    )
    assert len(rope) == 1
    assert rope[0].name == "rope_bridge"


def test_find_stamps_no_filter_returns_all():
    everything = thing_library.find_stamps_by_tags()
    assert len(everything) == 4


# ── Schema sanity ───────────────────────────────────────────────


def test_stamps_are_multi_meter():
    """Stamps are architecture — at least one dimension ≥ 1.5m."""
    stamps = thing_library.get_all_stamps()
    for s in stamps.values():
        max_dim = max(s.real_size_m)
        assert max_dim >= 1.5, (
            f"stamp {s.name!r} max dim {max_dim} too small to be "
            f"'architecture' — looks like a thing"
        )


def test_stamp_anchor_resolves_to_part():
    """Per thing_schema validation, anchor role must match a part."""
    stamps = thing_library.get_all_stamps()
    for s in stamps.values():
        roles = {p.role for p in s.parts}
        assert s.anchor in roles, (
            f"stamp {s.name!r} anchor {s.anchor!r} not in parts {roles}"
        )
