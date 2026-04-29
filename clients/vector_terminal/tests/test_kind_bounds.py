"""Kind→bounds lookup against the live config/kind_config.json."""
from __future__ import annotations

from clients.vector_terminal.kind_bounds import bounds_for, class_for, _coerce, _FALLBACK


def test_unknown_kind_falls_back_to_unit_cube():
    assert bounds_for("definitely-not-a-real-kind") == _FALLBACK


def test_known_kind_returns_three_floats():
    bounds = bounds_for("rat")
    assert isinstance(bounds, tuple)
    assert len(bounds) == 3
    assert all(isinstance(v, float) for v in bounds)


def test_coerce_list_of_three():
    assert _coerce([2.0, 3.0, 4.0]) == (2.0, 3.0, 4.0)


def test_coerce_tuple_of_three():
    assert _coerce((1.5, 2.5, 3.5)) == (1.5, 2.5, 3.5)


def test_coerce_scalar_broadcasts():
    assert _coerce(2.0) == (2.0, 2.0, 2.0)
    assert _coerce(3) == (3.0, 3.0, 3.0)


def test_coerce_garbage_falls_back():
    assert _coerce(None) == _FALLBACK
    assert _coerce("nope") == _FALLBACK
    assert _coerce([1.0, 2.0]) == _FALLBACK  # wrong arity
    assert _coerce([1.0, 2.0, "x"]) == _FALLBACK


def test_class_for_known_kinds():
    assert class_for("spore_cloud") == "atmosphere"
    assert class_for("boulder") == "geological"
    assert class_for("horizon_near") == "horizon"
    assert class_for("rat") == "life"


def test_class_for_unknown_returns_empty():
    assert class_for("definitely-not-a-real-kind") == ""
