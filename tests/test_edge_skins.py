"""Edge skins — pure-function tests for noise + palette + skin profiles.

Per `core/systems/edge_skins.py`: helpers and 5 profiles are pure
math. UAT covers the visual outcome; these tests pin the contract:
determinism, bounds, segment shape, registry membership.
"""
from __future__ import annotations

import pytest

from core.systems.edge_skins import (
    cosine_palette,
    decay,
    get_skin,
    ice,
    metal,
    prismatic,
    rust,
    skin_names,
    value_fbm,
    value_noise,
    worley_noise,
)


# ── Noise helpers ────────────────────────────────────────────────────


def test_worley_deterministic():
    """Same inputs → same output every call."""
    a = worley_noise(1.23, 4.56, seed=42)
    b = worley_noise(1.23, 4.56, seed=42)
    assert a == b


def test_worley_seed_changes_output():
    """Different seed → different output (almost surely)."""
    a = worley_noise(1.23, 4.56, seed=1)
    b = worley_noise(1.23, 4.56, seed=999)
    assert a != b


def test_worley_in_expected_range():
    """Worley distance on a unit grid stays well below sqrt(2). Sample
    a sweep so we catch any pathological cell."""
    for i in range(50):
        x = i * 0.137
        y = i * 0.219
        n = worley_noise(x, y, seed=11)
        assert 0.0 <= n <= 1.5


def test_value_noise_in_unit_range():
    for i in range(50):
        x = i * 0.137
        y = i * 0.219
        n = value_noise(x, y, seed=3)
        assert 0.0 <= n <= 1.0


def test_value_noise_deterministic():
    assert value_noise(0.5, 0.5, seed=7) == value_noise(0.5, 0.5, seed=7)


def test_value_fbm_in_unit_range():
    for i in range(30):
        n = value_fbm(i * 0.31, i * 0.17, seed=5, octaves=4)
        assert 0.0 <= n <= 1.0


# ── Cosine palette ───────────────────────────────────────────────────


def test_cosine_palette_returns_triple():
    rgb = cosine_palette(0.5, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5),
                         (1.0, 1.0, 1.0), (0.0, 0.33, 0.67))
    assert len(rgb) == 3


def test_cosine_palette_deterministic():
    args = (0.3, (0.5, 0.5, 0.5), (0.5, 0.5, 0.5),
            (1.0, 1.0, 1.0), (0.0, 0.10, 0.20))
    assert cosine_palette(*args) == cosine_palette(*args)


def test_cosine_palette_periodic_on_t():
    """t and t+1 with c=(1,1,1) produce the same color (cosine periodicity)."""
    args = ((0.5, 0.5, 0.5), (0.5, 0.5, 0.5),
            (1.0, 1.0, 1.0), (0.0, 0.0, 0.0))
    a = cosine_palette(0.25, *args)
    b = cosine_palette(1.25, *args)
    for x, y in zip(a, b):
        assert abs(x - y) < 1e-9


# ── Skin profile contract ────────────────────────────────────────────


_EDGE_A = (-0.6, 0.0, -0.6)
_EDGE_B = (1.0, 1.0, -1.0)


@pytest.mark.parametrize("skin", [rust, ice, metal, prismatic])
def test_skin_returns_single_segment(skin):
    """rust / ice / metal / prismatic emit one segment per edge spanning
    the original endpoints with an RGBA color tuple."""
    out = skin(_EDGE_A, _EDGE_B, time=1.0, seed=42)
    assert len(out) == 1
    seg_a, seg_b, color = out[0]
    assert seg_a == _EDGE_A
    assert seg_b == _EDGE_B
    assert len(color) == 4
    for c in color:
        assert 0 <= c <= 255


def test_decay_returns_subdivided_segments():
    """decay subdivides into <=7 sub-segments, each a strict slice of
    the original edge. May return fewer than 7 (some skipped) but at
    least one for typical input."""
    out = decay(_EDGE_A, _EDGE_B, time=0.0, seed=42)
    assert 1 <= len(out) <= 7
    for seg_a, seg_b, color in out:
        assert len(seg_a) == 3
        assert len(seg_b) == 3
        assert len(color) == 4


def test_decay_can_return_empty_for_uniform_field():
    """A degenerate edge (zero length) all sampled at one point can
    plausibly be entirely skipped if that point falls below threshold.
    Not asserting empty here — just asserting the shape stays a list."""
    out = decay(_EDGE_A, _EDGE_A, time=0.0, seed=99)
    assert isinstance(out, list)


def test_metal_responds_to_edge_orientation():
    """Vertical edge and horizontal edge produce different palette samples."""
    vertical = metal((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), time=0.0, seed=0)
    horizontal = metal((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), time=0.0, seed=0)
    assert vertical[0][2] != horizontal[0][2]


def test_ice_drifts_with_time():
    """Same edge sampled at two times → different colors (slow drift)."""
    t0 = ice(_EDGE_A, _EDGE_B, time=0.0, seed=1)
    t1 = ice(_EDGE_A, _EDGE_B, time=120.0, seed=1)
    assert t0[0][2] != t1[0][2]


def test_prismatic_drifts_with_time():
    t0 = prismatic(_EDGE_A, _EDGE_B, time=0.0, seed=1)
    t1 = prismatic(_EDGE_A, _EDGE_B, time=2.5, seed=1)
    assert t0[0][2] != t1[0][2]


# ── Registry ─────────────────────────────────────────────────────────


def test_skin_registry_lists_all_five():
    names = skin_names()
    for n in ("rust", "ice", "metal", "decay", "prismatic"):
        assert n in names


def test_get_skin_returns_callable():
    fn = get_skin("rust")
    assert fn is not None
    out = fn(_EDGE_A, _EDGE_B, 0.0, 0)
    assert len(out) == 1


def test_get_skin_unknown_returns_none():
    assert get_skin("does_not_exist") is None
