"""
Golden master + float-purge guard for the live generation path
(core/systems/stamp_world.py). Spec 53 §9-A.

This is the Python analogue of the Flipper's `test_chunk_golden` in
flipper/sanctum_rpg/test/test_main.c, and it carries the same contract:

    A fingerprint change means the world generator changed. Every existing
    world would shift. Re-record these values ONLY with a deliberate
    GENERATOR_VERSION bump — never to "make the test pass".

The purge tests are the executable form of the AC: they fail if anyone
reintroduces `random.` or a float into the generation path, which is the
failure mode this whole phase exists to prevent (a float that works fine
on this machine and diverges on the Flipper or a future port).
"""
from __future__ import annotations

import inspect
import re

import pytest

from core.systems import stamp_world as sw
from core.systems.determinism.fixed import emit
from core.systems.determinism.rng import rng_chunk_seed


def _relative_layout(gx: int, gy: int, seed: int = 42, biome: str = "cavern"):
    """A slot's arrangement with its absolute position removed — what a
    player would recognise as "I have seen this exact place before"."""
    cx = gx * sw.SLOT_SIZE + sw.SLOT_SIZE / 2
    cy = gy * sw.SLOT_SIZE + sw.SLOT_SIZE / 2
    return [(e["kind"], round(e["x"] - cx, 2), round(e["y"] - cy, 2),
             e["heading"], e["sv"])
            for e in sw.stamp_at(gx, gy, seed, biome)]


# ── fingerprint ──────────────────────────────────────────────────────────────

_FP_FIELDS = ("kind", "x", "y", "heading", "sv", "sx", "sy", "sz",
              "r", "g", "b", "light_hue", "collision_radius")

_FNV_OFFSET = 0x811C9DC5
_FNV_PRIME = 0x01000193


def _fingerprint(entities) -> int:
    """FNV-1a over the emitted fields, in emission order. Mirrors the C
    harness's chunk fingerprint: order-sensitive, so a reordered draw
    stream is caught as loudly as a changed value."""
    h = _FNV_OFFSET
    for ent in entities:
        for field in _FP_FIELDS:
            for byte in repr(ent[field]).encode():
                h = ((h ^ byte) * _FNV_PRIME) & 0xFFFFFFFF
    return h


# GOLDEN MASTER — recorded 2026-08-25 against GENERATOR_VERSION 2 (the
# spec 53 §9-A integer kernel). Format: (seed, gx, gy, biome, count, fp).
GOLDEN_VERSION = 2
GOLDEN_SLOTS = [
    (0xCAFEBABE,  0,  0, "cavern",  57, 0x4C158547),   # authored origin hub
    (0xCAFEBABE,  1,  0, "cavern",   8, 0xEB57C39B),
    (0xDEADBEEF,  3,  4, "cavern",   9, 0x9C7A6DA3),
    (0x00000001, -3,  5, "cavern",  12, 0xDB7867D9),   # negative coords
    (0x0000002A,  7, -2, "outdoor", 13, 0x0C0F0FCF),
]


def test_generator_version_matches_goldens():
    """If the version moved and the goldens didn't, someone changed
    generation without re-recording — or re-recorded without declaring a
    version. Either way the pair has to move together."""
    assert sw.GENERATOR_VERSION == GOLDEN_VERSION


@pytest.mark.parametrize("seed,gx,gy,biome,count,fp", GOLDEN_SLOTS)
def test_slot_golden(seed, gx, gy, biome, count, fp):
    ents = sw.stamp_at(gx, gy, seed, biome)
    assert len(ents) == count, "entity count drifted"
    assert _fingerprint(ents) == fp, (
        f"world-gen fingerprint drift at seed={seed:08X} slot=({gx},{gy}) "
        f"— every existing world just moved. Bump GENERATOR_VERSION and "
        f"re-record deliberately, or revert."
    )


# ── determinism ──────────────────────────────────────────────────────────────

def test_stamp_at_is_pure():
    """Same inputs, same output — including across an interleaved call to
    a different slot, which would catch shared-RNG-state leakage."""
    a = sw.stamp_at(3, 4, 42, "cavern")
    sw.stamp_at(99, -99, 42, "cavern")
    b = sw.stamp_at(3, 4, 42, "cavern")
    assert a == b


def test_different_seeds_differ():
    assert sw.stamp_at(3, 4, 42, "cavern") != sw.stamp_at(3, 4, 43, "cavern")


# ── the kernel's point-symmetry, and the map that defeats it ────────────────
#
# rng_chunk_seed(s, cx, cy) == rng_chunk_seed(s, -cx, -cy) whenever cx and cy
# share a trailing-zero count — a property of the C substrate, verified
# against the C directly. _slot_seed maps around it rather than changing the
# kernel; these tests pin BOTH facts, so that if the substrate is ever fixed
# upstream the map can be retired deliberately instead of by accident.

def test_kernel_point_symmetry_still_exists():
    """Documents the substrate property. If this ever fails, rng.c changed —
    which is a conformance event: re-run the C golden vectors, and consider
    retiring _slot_seed's coordinate map."""
    assert rng_chunk_seed(42, 3, 5) == rng_chunk_seed(42, -3, -5)
    assert rng_chunk_seed(42, 1, 1) == rng_chunk_seed(42, -1, -1)
    assert rng_chunk_seed(42, 1, 2) != rng_chunk_seed(42, -1, -2)  # tz differs


def test_slot_seed_defeats_the_point_symmetry():
    """No slot may share a seed with its mirror through the origin."""
    for n in range(-32, 33):
        for m in range(-32, 33):
            if (n, m) == (0, 0):
                continue
            assert sw._slot_seed(n, m, 42) != sw._slot_seed(-n, -m, 42), (
                f"slot ({n},{m}) is a mirror twin of ({-n},{-m})")


def test_slot_seed_is_injective_over_the_played_world():
    """+/-64 slots is ~1 km in every direction — no two slots may collide."""
    r = range(-64, 65)
    seeds = {sw._slot_seed(gx, gy, 42) for gx in r for gy in r}
    assert len(seeds) == len(r) ** 2


def test_no_mirror_twin_stamps():
    """The user-visible form of the same bug: two slots growing an identical
    arrangement. Compared slot-relative, since absolute positions always
    differ."""
    for n, m in ((1, 1), (2, 2), (3, 3), (5, 7), (4, 8)):
        assert _relative_layout(n, m) != _relative_layout(-n, -m), \
            f"mirror twin at ({n},{m})"


def test_slot_seed_never_returns_the_degenerate_state():
    """xorshift32 collapses on state 0; rng_chunk_seed promotes it to 1."""
    assert all(sw._slot_seed(gx, gy, seed) != 0
               for seed in (0, 1, 42, 0xFFFFFFFF)
               for gx in range(-4, 5) for gy in range(-4, 5))


# ── float purge (the AC, as a test) ──────────────────────────────────────────

# Functions that make up the generation path — everything upstream of, and
# including, the emit boundary in _make_entity.
_GENERATION_PATH = (
    sw.stamp_at, sw._make_entity, sw._weighted_pick, sw._instantiate_authored,
    sw._slot_seed, sw._tissue_mult_for_band, sw._beacon_member,
    sw._is_beacon_slot, sw._radial_band, sw._filter_stamps_for_band,
    sw._player_collision_radius_fx, sw._spike_visual_radius_fx,
)

_BANNED = re.compile(r"\brandom\.|\.uniform\(|\.randint\(|\bmath\.")


def _code_lines(fn):
    """Source lines with comments and docstrings stripped — we're testing
    the code, not the prose that explains why the code looks like this."""
    src = inspect.getsource(fn)
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    return [ln.split("#", 1)[0] for ln in src.splitlines()]


@pytest.mark.parametrize("fn", _GENERATION_PATH, ids=lambda f: f.__name__)
def test_no_float_rng_in_generation_path(fn):
    hits = [ln.strip() for ln in _code_lines(fn) if _BANNED.search(ln)]
    assert not hits, (
        f"{fn.__name__} reintroduced non-integer generation: {hits}"
    )


def test_stamp_world_does_not_import_random():
    src = open(sw.__file__).read()
    assert not re.search(r"^import random$", src, re.M)
    assert not re.search(r"^from random import", src, re.M)


def test_emitted_values_came_through_the_emit_boundary():
    """Every emitted number is bit-identical to emit() of some fx integer.

    This is the proof that the value was computed in fixed-point and
    converted once, rather than accumulated in float — an equality on the
    float bits, not a tolerance, because a tolerance would pass for values
    that never went near emit()."""
    for gx, gy in ((0, 0), (3, 4), (-3, 5), (7, -2)):
        for ent in sw.stamp_at(gx, gy, 42, "cavern"):
            # Invert the emit: recover the integer, re-emit, demand identity.
            assert ent["x"] == emit(round(ent["x"] * 1000), 2)
            assert ent["y"] == emit(round(ent["y"] * 1000), 2)
            assert ent["sv"] == emit(round(ent["sv"] * 1000))
            assert ent["heading"] == emit(round(ent["heading"] * 1000), 1)
            assert 0.0 <= ent["heading"] < 360.0
            assert 0 <= ent["light_hue"] <= 3


def test_no_duplicate_arrangements_anywhere_near_spawn():
    """The general form of the mirror-twin check: no two slots in the played
    world may grow the SAME arrangement. Compared slot-relative, because
    absolute positions always differ and would mask a duplicate.

    This is the test shape that would have caught the rng_chunk_seed
    symmetry; the anti-symmetry test alone would not have."""
    seen = {}
    for gx in range(-12, 13):
        for gy in range(-12, 13):
            key = tuple(_relative_layout(gx, gy))
            if not key:
                continue
            assert key not in seen, (
                f"slot ({gx},{gy}) duplicates ({seen[key][0]},{seen[key][1]})")
            seen[key] = (gx, gy)


def test_fx_cache_stays_bounded():
    """_fxc is an unbounded lru_cache on a per-frame path. It is sized by the
    count of DISTINCT authored constants, which is small and fixed — if a
    future data table introduces per-instance decimals this grows without
    limit inside a module documented as stateless."""
    for gx in range(-20, 21):
        for gy in range(-20, 21):
            sw.stamp_at(gx, gy, 42, "cavern")
            sw.stamp_at(gx, gy, 42, "outdoor")
    assert sw._fxc.cache_info().currsize < 500, (
        "fx cache is growing per-instance, not per-constant")


# ── the shape the world still has to have ────────────────────────────────────

def test_origin_hub_is_still_authored():
    """Slot (0,0) is the authored hub — it must not have become procedural,
    and its members sit at authored offsets, not jittered ones."""
    ents = sw.stamp_at(0, 0, 42, "cavern")
    assert ents, "origin hub generated nothing"
    assert any(abs(e["x"]) < 0.01 and abs(e["y"]) < 0.01 for e in ents)


def test_spawn_band_stays_clear_of_mega_stamps():
    """The landing-zone rule: no mega anchors within 2 slots of origin."""
    for gx in range(-1, 2):
        for gy in range(-1, 2):
            assert sw._radial_band(gx, gy) == sw.BAND_SPAWN


def test_visible_world_is_populated_at_origin():
    """NO REGRESSION, at the generation layer: the camera at spawn still
    sees a populated world (the brain's own boot needs spacy, which is not
    installed here — see the Phase A notes)."""
    for biome in ("cavern", "outdoor"):
        ents = sw.get_visible(0.0, 0.0, 49.0, 42, biome)
        assert len(ents) > 20, f"{biome} spawn view is nearly empty"
        assert all(isinstance(e["x"], float) for e in ents)


def test_tissue_scatter_respects_spike_hulls():
    """Keep-out survived the fixed-point port: nothing sits inside a spike's
    visual hull."""
    for gx, gy in ((3, 4), (7, -2), (-5, 9)):
        ents = sw.stamp_at(gx, gy, 42, "cavern")
        spikes = [e for e in ents if e["kind"] in sw._SPIKE_KINDS_KEEPOUT]
        others = [e for e in ents if e["kind"] not in sw._SPIKE_KINDS_KEEPOUT]
        for s in spikes:
            r = sw.VISUAL_RADII.get(s["kind"], 0.0) * 1.3
            for o in others:
                d2 = (o["x"] - s["x"]) ** 2 + (o["y"] - s["y"]) ** 2
                assert d2 >= r * r - 1e-6, (
                    f"{o['kind']} spawned inside {s['kind']}'s hull")
