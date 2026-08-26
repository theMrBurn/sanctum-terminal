"""
fixed.py — fixed-point arithmetic for the deterministic generation path.

Spec 53 §9-A ("FLOAT PURGE"): world generation must run on integers only.
Float is legal on the RENDER side of the emit boundary; it is illegal on
the generation side, because IEEE-754 rounding is not portable and the
Flipper-C reference implementation has no FPU in its generation path.

This module is the bridge between the two:

    authored decimal constants  ──fx()──▶  integer generation  ──emit()──▶  float
    (biome_data, kind_config)              (stamp_world, ...)               (manifest)

## The unit

One fx unit is 1/1000 of the underlying quantity — a millimetre when the
quantity is a distance in metres, a per-mille when it is a multiplier.
1000 was chosen because every authored constant in the live tables carries
at most 3 decimals (verified by `tests/test_fixed_point.py`), so `fx()` is
lossless on real data rather than a quantization that silently moves the
world.

## Why Decimal in fx()

`fx()` runs at import time over authored constants, never inside a
generation loop. It goes through `Decimal(repr(v))` so that `0.7` becomes
exactly 700 rather than 699 — binary float error at the ingest boundary
would be a per-platform difference, which is the exact class of bug this
module exists to remove. After ingest, nothing here touches float again.

## Why truncating division

`idiv()` truncates toward zero, matching C integer division, so a future
C or Julia port of the same generator produces identical values. Python's
native `//` floors toward -inf and would diverge on negative operands.

Spec: sanctum-os/docs/specs/53_seed_is_truth.md §9-A
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

# ── The scale ────────────────────────────────────────────────────────────────
# 1 fx == 1/1000 unit. See module docstring for why 1000.
FX_SCALE: int = 1000
FX_ONE: int = FX_SCALE          # the multiplicative identity, in fx
FX_HALF: int = FX_SCALE // 2

_DEC_SCALE = Decimal(FX_SCALE)


# ── Ingest: authored decimal → fx integer ────────────────────────────────────

def fx(value) -> int:
    """Quantize an authored constant to fx units. Import-time only.

    Rounds half away from zero (ROUND_HALF_UP on the absolute value), which
    is sign-symmetric and independent of the host's float rounding mode.
    Accepts int, float, str, or Decimal.
    """
    d = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    return int((d * _DEC_SCALE).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def fx_is_lossless(value) -> bool:
    """True if `value` survives fx() with no residue — i.e. it carries at
    most 3 decimals. Used by the test that guards the authored tables; a
    False here means someone authored a 4th decimal that fx() would round,
    silently moving the world."""
    d = Decimal(repr(value)) if isinstance(value, float) else Decimal(value)
    return (d * _DEC_SCALE) == (d * _DEC_SCALE).to_integral_value()


# ── Integer arithmetic in fx space ───────────────────────────────────────────

def idiv(n: int, d: int) -> int:
    """Integer division truncating toward zero (C semantics, not Python's)."""
    q = abs(n) // abs(d)
    return -q if (n < 0) != (d < 0) else q


def idiv_round(n: int, d: int) -> int:
    """Integer division rounding half away from zero. `d` must be positive."""
    if n >= 0:
        return (n + d // 2) // d
    return -((-n + d // 2) // d)


def fx_mul(a: int, b: int) -> int:
    """Multiply two fx quantities, result in fx. Rounds half away from zero.

    Rounding rather than truncating matters here: a chain of multiplies
    (jitter × base × scale_mult) truncated at every step drifts visibly
    downward, which reads in-world as everything being slightly too small.
    """
    return idiv_round(a * b, FX_SCALE)


def fx_scale_int(count: int, mult_fx: int) -> int:
    """Scale a plain integer count by an fx multiplier, rounding half away
    from zero. Used for per-band entity counts."""
    return idiv_round(count * mult_fx, FX_SCALE)


# ── Emit: fx integer → float, at the render boundary ─────────────────────────

def emit(value_fx: int, places: int = 3) -> float:
    """Convert an fx quantity to the float that crosses into the manifest.

    THIS IS THE BOUNDARY. Call it only when building the entity dict that
    leaves the generator; never mid-computation. `places` (0-3) sets the
    emitted decimal precision, applied by integer rounding BEFORE the single
    division, so the result never depends on float rounding.
    """
    if places >= 3:
        return value_fx / FX_SCALE
    divisor = 10 ** (3 - places)
    return idiv_round(value_fx, divisor) / (10 ** places)


# ── Weighted selection over integer weights ──────────────────────────────────

def weighted_index(weights_fx: list[int], roll: int) -> int:
    """Index chosen by a cumulative walk over fx weights.

    `roll` is a half-open draw in [0, sum(weights_fx)) — pass
    `rng_range(r, 0, total)`. Half-open (roll < cum) is the integer analogue
    of the float `uniform(0, total)` this replaces; the closed form would
    give the first entry a one-unit edge.
    """
    cum = 0
    for i, w in enumerate(weights_fx):
        cum += w
        if roll < cum:
            return i
    return len(weights_fx) - 1   # total was 0, or the roll landed on the end
