"""
rng.py — Python conformance kernel for flipper/sanctum_rpg/rng.c

Reproduces rng_seed / rng_next / rng_range / rng_chunk_seed byte-for-byte.
Integer-only. Zero floats. Zero random module. Named constants at file top.

Spec: sanctum-os/docs/specs/53_seed_is_truth.md §9-A
Conformance: tests/test_conformance_rng_pool.py
"""
from __future__ import annotations

# ── Constants transcribed verbatim from rng.c ────────────────────────────────
# Chunk-coord mixing multipliers (Knuth-style golden-ratio-derived).
_COORD_MULT_X: int = 0x9E3779B1  # (uint32_t)chunk_x multiplier
_COORD_MULT_Y: int = 0x85EBCA77  # (uint32_t)chunk_y multiplier — note: differs from avalanche const below

# fmix pass constants (transcribed from rng.c lines 45-46).
# WARNING: these differ from canonical MurmurHash3 fmix32 — do NOT substitute.
# rng.c comment says "fmix32 from MurmurHash3" but constants diverge.
_FMIX_MULT_1: int = 0x7FEB352D   # first fmix multiply
_FMIX_MULT_2: int = 0x846CA68B   # second fmix multiply
# Lookalike hazard: pool.c fnv1a_seed avalanche uses 0x85EBCA6B (one hex digit apart).

# xorshift32 shift amounts
_XS_SHIFT_A: int = 13
_XS_SHIFT_B: int = 17
_XS_SHIFT_C: int = 5

# fmix shift amounts (shifts 16/15/16 — NOT the 16/13/16 of canonical MurmurHash3)
_FMIX_SHIFT_1: int = 16
_FMIX_SHIFT_2: int = 15
_FMIX_SHIFT_3: int = 16

# 2^32 — used for rejection-sampling boundary
_U32_MOD: int = 0x100000000

# Mask for uint32_t
_U32_MASK: int = 0xFFFFFFFF


# ── u32 helper ───────────────────────────────────────────────────────────────

def u32(x: int) -> int:
    """Truncate to 32-bit unsigned integer. Apply after every left-shift and multiply."""
    return x & _U32_MASK


# ── Rng state ────────────────────────────────────────────────────────────────

class Rng:
    """Xorshift32 PRNG state. Seed 0 is silently promoted to 1."""
    __slots__ = ("state",)

    def __init__(self, seed: int = 1) -> None:
        self.state: int = 0
        rng_seed(self, seed)


def rng_seed(r: Rng, s: int) -> None:
    """Seed the PRNG. state 0 → 1 (xorshift collapses on all-zero state)."""
    r.state = s if s != 0 else 1


def rng_next(r: Rng) -> int:
    """
    xorshift32 — next 32 random bits.

    Transcribed from rng.c:
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;

    Python gotcha: left-shifts are unbounded; MASK every one.
    """
    x = r.state
    x ^= u32(x << _XS_SHIFT_A)
    x ^= (x >> _XS_SHIFT_B)
    x ^= u32(x << _XS_SHIFT_C)
    r.state = x
    return x


def rng_range(r: Rng, lo: int, hi: int) -> int:
    """
    Rejection-sampled uniform in [lo, hi).  Returns lo if hi <= lo.

    Critical Python gotcha for rejection threshold:
        C:      (uint32_t)(-span) % span  == 2^32 % span
        Python: (-span) % span            == 0 for any positive span
    Must use (0x100000000 - span) % span — do NOT use (-span) % span.
    """
    if hi <= lo:
        return lo
    span = hi - lo
    # Rejection removes modulo bias — see rng.c comment.
    # (0x100000000 - span) % span  ==  (2^32) % span in C arithmetic.
    reject = (_U32_MOD - span) % span
    while True:
        x = rng_next(r)
        if x >= reject:
            break
    return lo + (x % span)


def rng_chunk_seed(base: int, chunk_x: int, chunk_y: int) -> int:
    """
    Mix base seed with chunk coordinates.

    Negative chunk_x / chunk_y are C int cast to uint32_t before multiply,
    which is two's-complement wrapping: (chunk_x & 0xFFFFFFFF).

    fmix pass uses constants 0x7FEB352D / 0x846CA68B, shifts 16/15/16.
    These are NOT canonical MurmurHash3 — transcribed verbatim from rng.c.
    """
    s = base
    s ^= u32(u32(chunk_x & _U32_MASK) * _COORD_MULT_X)
    s ^= u32(u32(chunk_y & _U32_MASK) * _COORD_MULT_Y)
    # fmix pass
    s ^= (s >> _FMIX_SHIFT_1)
    s = u32(s * _FMIX_MULT_1)
    s ^= (s >> _FMIX_SHIFT_2)
    s = u32(s * _FMIX_MULT_2)
    s ^= (s >> _FMIX_SHIFT_3)
    return s if s != 0 else 1
