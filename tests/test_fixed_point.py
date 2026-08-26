"""
Unit tests for core/systems/determinism/fixed.py — the float→integer
boundary of the generation path (spec 53 §9-A, FLOAT PURGE).

Two jobs:
  1. the arithmetic behaves like C integer arithmetic, not like Python's
     (truncation toward zero, sign-symmetric rounding);
  2. the AUTHORED TABLES are lossless under fx() — this is the guard that
     catches someone adding a 4th decimal to a stamp offset or a kind
     scale, which fx() would round and thereby move the world silently.
"""
from __future__ import annotations

import pytest

from core.systems.determinism.fixed import (
    FX_SCALE, FX_ONE, fx, fx_is_lossless, idiv, idiv_round, fx_mul,
    fx_scale_int, emit, weighted_index,
)


# ── ingest ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value,expected", [
    (0.0, 0), (1.0, 1000), (0.7, 700), (-0.7, -700),
    (16.0, 16000), (1.25, 1250), (0.75, 750), (1.3, 1300),
    (0.05, 50), (2.5, 2500), (-0.3, -300), (4, 4000),
])
def test_fx_quantizes_exactly(value, expected):
    assert fx(value) == expected


def test_fx_avoids_binary_float_error():
    """2.01 * 1000 == 2009.9999999999998 in IEEE-754. Going through Decimal
    is the whole point — a truncating port of the naive form would place
    that offset one millimetre off, and differently per platform."""
    assert int(2.01 * FX_SCALE) == 2009      # the trap
    assert fx(2.01) == 2010                  # what we do instead
    assert fx(8.03) == 8030 and int(8.03 * FX_SCALE) == 8029


def test_fx_rounds_half_away_from_zero():
    assert fx(0.0005) == 1
    assert fx(-0.0005) == -1


# ── the authored tables are lossless ─────────────────────────────────────────

def _authored_decimals():
    """Every authored constant that enters the generation path."""
    from core.systems.biome_data import BIOME_REGISTRY
    from core.systems.bucket_world import KIND_PROPS
    from core.systems import kind_config as _kc

    for biome in BIOME_REGISTRY.values():
        for stamp in biome.get("stamps") or []:
            for member in stamp.get("members", []):
                yield ("stamp dx", member.get("dx", 0.0))
                yield ("stamp dy", member.get("dy", 0.0))
                if member.get("scale_mult") is not None:
                    yield ("stamp scale_mult", member["scale_mult"])
            yield ("stamp weight", stamp.get("weight", 1))
    for kind, props in KIND_PROPS.items():
        for n in props["scale"]:
            yield (f"{kind} scale", n)
        for n in props["color"]:
            yield (f"{kind} color", n)
    for kind, cfg in _kc.all_kinds().items():
        yield (f"{kind} visual_radius", cfg.get("visual_radius", 0.0))


def test_authored_constants_are_lossless_under_fx():
    lossy = [(label, v) for label, v in _authored_decimals()
             if not fx_is_lossless(v)]
    assert not lossy, (
        "authored constants with >3 decimals — fx() would round these and "
        "move the world; either round them at the source or raise FX_SCALE: "
        f"{lossy[:10]}"
    )


# ── C-semantics arithmetic ───────────────────────────────────────────────────

def test_idiv_truncates_toward_zero_like_c():
    assert idiv(7, 2) == 3
    assert idiv(-7, 2) == -3      # Python's -7 // 2 is -4; C gives -3
    assert -7 // 2 == -4          # the divergence we are avoiding
    assert idiv(7, -2) == -3


def test_idiv_round_is_sign_symmetric():
    assert idiv_round(5, 10) == 1
    assert idiv_round(-5, 10) == -1
    assert idiv_round(4, 10) == 0
    assert idiv_round(-4, 10) == 0


def test_fx_mul_identity_and_symmetry():
    assert fx_mul(fx(1.3), FX_ONE) == fx(1.3)
    assert fx_mul(fx(0.5), fx(0.5)) == fx(0.25)
    assert fx_mul(fx(-0.5), fx(0.5)) == fx(-0.25)


def test_fx_mul_rounds_rather_than_drifting_down():
    """A truncating chain shrinks; a rounding chain does not."""
    v = FX_ONE
    for _ in range(50):
        v = fx_mul(v, fx(1.0))
    assert v == FX_ONE


def test_fx_scale_int():
    assert fx_scale_int(7, fx(0.5)) == 4      # 3.5 → 4, half away from zero
    assert fx_scale_int(7, FX_ONE) == 7
    assert fx_scale_int(0, fx(0.5)) == 0


# ── emit boundary ────────────────────────────────────────────────────────────

def test_emit_precision():
    assert emit(-23004, 2) == -23.0
    assert emit(-23006, 2) == -23.01
    assert emit(1154, 3) == 1.154
    assert emit(3599, 1) == 3.6


def test_emit_is_the_only_division():
    """emit() of an exact fx value reproduces the authored decimal."""
    for v in (0.7, -0.3, 16.0, 1.25):
        assert emit(fx(v)) == pytest.approx(v)


# ── weighted selection ───────────────────────────────────────────────────────

def test_weighted_index_walks_cumulatively():
    w = [fx(1), fx(1), fx(4)]          # total 6000
    assert weighted_index(w, 0) == 0
    assert weighted_index(w, 999) == 0
    assert weighted_index(w, 1000) == 1
    assert weighted_index(w, 1999) == 1
    assert weighted_index(w, 2000) == 2
    assert weighted_index(w, 5999) == 2


def test_weighted_index_respects_weight_ratio():
    """A weight-4 entry beside two weight-1 entries wins 4/6 of the rolls."""
    w = [fx(1), fx(1), fx(4)]
    total = sum(w)
    hits = [0, 0, 0]
    for roll in range(total):
        hits[weighted_index(w, roll)] += 1
    assert hits == [1000, 1000, 4000]


def test_weighted_index_degenerate_cases():
    assert weighted_index([fx(1)], 0) == 0
    assert weighted_index([0, 0], 0) == 1     # zero total → last entry
