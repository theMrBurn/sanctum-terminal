"""
pool.py — Python conformance kernel for flipper/sanctum_rpg/pool.c

Reproduces pool_at_prime / pool_at / pool_step field-for-field.
Integer-only. Zero floats. Named constants at file top.

Pool is represented as a plain dataclass matching the JSON schema.
Do NOT raw-memcpy Pool across languages — use field-wise accessors.
sizeof(Pool) == 48 in C (not 42 as the header comment claims; 3 bytes padding
after rotation_bias before pedigree, 3 bytes after last_drop_slot).

Spec: sanctum-os/docs/specs/53_seed_is_truth.md §9-A
Conformance: tests/test_conformance_rng_pool.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

# ── Constants transcribed verbatim from pool.h and pool.c ────────────────────
POOL_THEMES: int = 16         # theme vocabulary size
POOL_BAG_SLOTS: int = 8       # primitive bag capacity
POOL_FAMILIES: int = 5        # creature families per biome
POOL_LOOT_KINDS: int = 7      # loot kind count
BAG_WEIGHT_FLOOR: int = 1     # minimum bag slot weight (anti-drain)
BAG_WEIGHT_MAX: int = 15      # maximum bag slot weight (cap for bump)

# Walk direction encoding (pool.h)
POOL_DIR_EAST: int = 0
POOL_DIR_WEST: int = 1
POOL_DIR_SOUTH: int = 2
POOL_DIR_NORTH: int = 3

# FNV-1a 32-bit parameters
_FNV_OFFSET_BASIS: int = 0x811C9DC5
_FNV_PRIME: int = 16777619        # 0x01000193

# FNV-1a avalanche multiplier used in fnv1a_seed (pool.c line ~30).
# LOOKALIKE HAZARD: this is 0x85EBCA6B.
# rng.c chunk-coord multiplier uses 0x85EBCA77 (different).
# rng.c fmix second constant uses 0x846CA68B (different).
_FNV_AVALANCHE_MULT: int = 0x85EBCA6B

# Biome IDs matching pool.c
_BIOME_CAVERN: int = 0
_BIOME_OUTDOOR: int = 1

# Biome primitive vocabularies (pool.c CAVERN_VOCAB / OUTDOOR_VOCAB)
_CAVERN_VOCAB: tuple[int, ...] = (0, 1, 2, 3, 4, 5)
_OUTDOOR_VOCAB: tuple[int, ...] = (0, 1, 2, 3, 4, 5)

# u32 mask
_U32_MASK: int = 0xFFFFFFFF


# ── u32 helper ───────────────────────────────────────────────────────────────

def _u32(x: int) -> int:
    """Truncate to uint32_t. Apply after every multiply."""
    return x & _U32_MASK


# ── FNV-1a internals ─────────────────────────────────────────────────────────

def _fnv1a_mix(h: int, v: int) -> int:
    """
    FNV-1a 32-bit chain mix — feeds each byte of v low-byte-first.
    Transcribed from pool.c fnv1a_mix().
    """
    h ^= (v & 0xFF);         h = _u32(h * _FNV_PRIME)
    h ^= ((v >> 8)  & 0xFF); h = _u32(h * _FNV_PRIME)
    h ^= ((v >> 16) & 0xFF); h = _u32(h * _FNV_PRIME)
    h ^= ((v >> 24) & 0xFF); h = _u32(h * _FNV_PRIME)
    return h


def _fnv1a_seed(a: int, b: int, c: int) -> int:
    """
    FNV-1a 32-bit seed from three uint32 inputs.
    Starts from offset basis, mixes a/b/c in order, then avalanche pass.
    Transcribed from pool.c fnv1a_seed().
    """
    h = _FNV_OFFSET_BASIS
    h = _fnv1a_mix(h, a)
    h = _fnv1a_mix(h, b)
    h = _fnv1a_mix(h, c)
    # avalanche: h ^= h>>16; h *= 0x85EBCA6B; h ^= h>>13
    h ^= (h >> 16)
    h = _u32(h * _FNV_AVALANCHE_MULT)
    h ^= (h >> 13)
    return h


# ── Pool dataclass ────────────────────────────────────────────────────────────

@dataclass
class Pool:
    """
    Python representation of the C Pool struct — field-wise, not packed bytes.
    All fields match the JSON schema in golden_vectors.json.
    """
    # 16 theme weights, each 0..15 (unpacked from C's nibble-packed 8-byte form)
    theme_weights: List[int] = field(default_factory=lambda: [0] * POOL_THEMES)
    # primitive_bag[slot] = [id, weight]; id 0xFF = empty
    primitive_bag: List[List[int]] = field(
        default_factory=lambda: [[0xFF, 0] for _ in range(POOL_BAG_SLOTS)]
    )
    family_bias: List[int] = field(default_factory=lambda: [0] * POOL_FAMILIES)
    loot_kind_bias: List[int] = field(default_factory=lambda: [0] * POOL_LOOT_KINDS)
    intensity: int = 0
    rotation_bias: int = 0
    pedigree: int = 0
    last_drop_slot: int = 0xFF


def pool_theme_weight(p: Pool, theme_bit: int) -> int:
    """Read theme weight at index. Returns 0 on out-of-range (mirrors C behaviour)."""
    if theme_bit < 0 or theme_bit >= POOL_THEMES:
        return 0
    return p.theme_weights[theme_bit]


def _pool_set_theme_weight(p: Pool, theme_bit: int, w: int) -> None:
    """Write theme weight, clamped to [0..15]."""
    if theme_bit < 0 or theme_bit >= POOL_THEMES:
        return
    p.theme_weights[theme_bit] = max(0, min(15, w))


# ── pool_at_prime ─────────────────────────────────────────────────────────────

def pool_at_prime(prime_seed: int, biome: int) -> Pool:
    """
    Initialize Pool at the campaign prime stamp.
    Same (prime_seed, biome) → identical Pool.
    Transcribed from pool.c pool_at_prime().
    """
    p = Pool()

    # Theme weights: 16 themes hashed to 0..15 each
    for t in range(POOL_THEMES):
        h = _fnv1a_seed(prime_seed, biome, 0xA00 | t)
        _pool_set_theme_weight(p, t, h % 16)

    # Primitive bag: biome vocabulary with hashed starting weights
    vocab = _OUTDOOR_VOCAB if biome == _BIOME_OUTDOOR else _CAVERN_VOCAB
    for slot in range(POOL_BAG_SLOTS):
        if slot < len(vocab):
            p.primitive_bag[slot][0] = vocab[slot]
            h = _fnv1a_seed(prime_seed, biome, 0xB00 | slot)
            # Weight range 4..15
            p.primitive_bag[slot][1] = 4 + (h % 12)
        else:
            p.primitive_bag[slot][0] = 0xFF
            p.primitive_bag[slot][1] = 0

    # Family bias: 5 families hashed to 0..7 each
    for f in range(POOL_FAMILIES):
        h = _fnv1a_seed(prime_seed, biome, 0xC00 | f)
        p.family_bias[f] = h % 8

    # Loot kind bias: 7 kinds hashed to 0..5 each
    for k in range(POOL_LOOT_KINDS):
        h = _fnv1a_seed(prime_seed, biome, 0xD00 | k)
        p.loot_kind_bias[k] = h % 6

    p.intensity = 0
    p.rotation_bias = 0
    p.pedigree = _fnv1a_seed(prime_seed, biome, 0)
    p.last_drop_slot = 0xFF  # spec 50 addendum §F1.A.4: no prior step

    return p


# ── pool_step ────────────────────────────────────────────────────────────────

def pool_step(p: Pool, prime_seed: int, direction: int) -> None:
    """
    Advance Pool one step in direction (POOL_DIR_*). Mutates p in place.

    Execution order MUST match pool.c exactly:
      1. pedigree advance
      2. intensity saturate
      3. rotation_bias
      4. theme drift (4 rounds, reads live array each round)
      5. family drift
      6. loot drift
      7. bag drop + bump
    """
    if direction < 0 or direction > 3:
        return

    # Step 1: pedigree — inner is dir, outer is prime_seed
    p.pedigree = _fnv1a_mix(_fnv1a_mix(p.pedigree, direction), prime_seed)

    # Step 2: intensity — saturating uint8
    if p.intensity < 255:
        p.intensity += 1

    # Step 3: rotation_bias
    p.rotation_bias = (p.rotation_bias + direction + 1) & 3

    # Step 4: theme drift — 4 rounds, each reads the LIVE array (writes visible to next round)
    for n in range(4):
        h = _fnv1a_mix(p.pedigree, 0xE00 | n)
        slot = h & 0x0F
        delta = +1 if ((h >> 8) & 1) else -1
        cur = pool_theme_weight(p, slot) + delta
        _pool_set_theme_weight(p, slot, cur)

    # Step 5: family drift — one slot ±1, clamp [0..15]
    h = _fnv1a_mix(p.pedigree, 0xF1F1)
    fam_slot = h % POOL_FAMILIES
    fam_delta = +1 if ((h >> 16) & 1) else -1
    p.family_bias[fam_slot] = max(0, min(15, p.family_bias[fam_slot] + fam_delta))

    # Step 6: loot drift — one slot ±1, clamp [0..15]
    h = _fnv1a_mix(p.pedigree, 0xF2F2)
    loot_slot = h % POOL_LOOT_KINDS
    loot_delta = +1 if ((h >> 16) & 1) else -1
    p.loot_kind_bias[loot_slot] = max(0, min(15, p.loot_kind_bias[loot_slot] + loot_delta))

    # Step 7: bag rotation — DROP then BUMP
    # --- DROP ---
    # Rotor-order scan: iterate slots in order (rotor + r) & 7.
    # Strict less-than tiebreak: earliest-in-rotor-order wins among ties.
    # Skip: id == 0xFF (empty), weight <= BAG_WEIGHT_FLOOR, slot == last_drop_slot.
    drop = -1
    low_w = 256  # sentinel above max uint8
    rotor = (p.pedigree >> 24) & 7
    for r in range(POOL_BAG_SLOTS):
        s = (rotor + r) & 7
        bag_id = p.primitive_bag[s][0]
        bag_w = p.primitive_bag[s][1]
        if bag_id == 0xFF:
            continue
        if bag_w <= BAG_WEIGHT_FLOOR:
            continue
        if s == p.last_drop_slot:
            continue
        if bag_w < low_w:  # STRICT less-than: first tie in rotor order wins
            low_w = bag_w
            drop = s

    if drop >= 0:
        p.primitive_bag[drop][1] -= 1
        p.last_drop_slot = drop
    # else: no eligible candidate — bag floor-locked this step

    # --- BUMP ---
    # h_bump selects starting slot; walk forward until occupied and != drop.
    h_bump = _fnv1a_mix(p.pedigree, 0xF3F3)
    bump = h_bump % POOL_BAG_SLOTS
    for r in range(POOL_BAG_SLOTS):
        s = (bump + r) % POOL_BAG_SLOTS
        if p.primitive_bag[s][0] == 0xFF:
            continue
        if s == drop:
            continue
        bump = s
        break

    if bump >= 0 and p.primitive_bag[bump][1] < BAG_WEIGHT_MAX:
        p.primitive_bag[bump][1] += 1


# ── pool_at ───────────────────────────────────────────────────────────────────

def pool_at(prime_seed: int, biome: int, chunk_x: int, chunk_y: int) -> Pool:
    """
    Compute Pool at chunk (chunk_x, chunk_y) via canonical X-first-then-Y walk.
    Same arguments → identical Pool. Transcribed from pool.c pool_at().
    """
    p = pool_at_prime(prime_seed, biome)

    # X first — east (+x) or west (-x)
    x_steps = chunk_x if chunk_x >= 0 else -chunk_x
    x_dir = POOL_DIR_EAST if chunk_x >= 0 else POOL_DIR_WEST
    for _ in range(x_steps):
        pool_step(p, prime_seed, x_dir)

    # Y second — south (+y) or north (-y)
    y_steps = chunk_y if chunk_y >= 0 else -chunk_y
    y_dir = POOL_DIR_SOUTH if chunk_y >= 0 else POOL_DIR_NORTH
    for _ in range(y_steps):
        pool_step(p, prime_seed, y_dir)

    return p
