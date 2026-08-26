"""
core/systems/stamp_world.py

Pure-function world generation from the AUTHORED stamp library.

The world is an infinite grid of slots. Each slot picks one stamp
deterministically from CAVERN_STAMPS or OUTDOOR_STAMPS, instantiates
its members at the slot center with small per-slot rotation/jitter,
and adds tissue scatter (loose grass, gravel, leaf piles) for connector
terrain between authored stamps.

This is the "ASCII braille / QR" model — the world is a grid you can
read like a code. Each glyph is a curated mini-scene the user designed.
Walk anywhere, you see authored content. The seed IS the world.

Save state: just (seed, player_pos). The entire world rebuilds from
those few bytes. v2 will add Wang-tile edge matching for stamp adjacency.

Pure Python. No cache. No state. Recomputed every frame.

## Determinism (spec 53 §9-A)

Generation is INTEGER-ONLY. Every random draw comes from the `determinism`
kernel — the Python port of the Flipper's `rng.c`, verified byte-equal to
the C reference by `tests/test_conformance_rng_pool.py` — and every
quantity is carried in fixed-point (`determinism.fixed`, 1 unit = 1/1000)
until it crosses the emit boundary in `_make_entity`.

Float lives on exactly one side of that boundary: `get_visible` (camera
culling, a render concern) and the emitted entity dict. Nothing that
decides WHAT exists or WHERE touches a float, because IEEE-754 rounding is
not portable and the Flipper has no FPU in its generation path.

Changing anything above the emit boundary MOVES EVERY WORLD. Bump
GENERATOR_VERSION and re-record `tests/test_stamp_world_golden.py` when
you do — deliberately, never to make the test pass.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Dict, List

from core.systems.biome_data import (
    BIOME_REGISTRY,
    ORIGIN_HUB,
    ENCOUNTER_TEST,
    SHADOW_LAB,
    HARD_OBJECTS,
    PLAYER_COLLISION_RADII,
)
from core.systems.bucket_world import KIND_PROPS
from core.systems import kind_config as _kc
from core.systems.determinism.rng import Rng, rng_range, rng_chunk_seed
from core.systems.determinism.fixed import (
    FX_ONE, fx, fx_mul, fx_scale_int, emit, weighted_index,
)


# Generation-model version. Bump on ANY change above the emit boundary —
# it is the Python analogue of the C golden-master version gate (spec 43
# §14.0). v1 = the float port (random.Random + IEEE arithmetic); v2 = the
# integer kernel (spec 53 §9-A float purge).
GENERATOR_VERSION = 2

# 32-bit mask — seeds enter the C-conformant kernel as uint32.
_U32 = 0xFFFFFFFF

# fx() goes through Decimal, which is exact but slow, and stamp_at runs
# per slot per frame over authored tables with ~250 distinct offsets. The
# cache makes the quantization a one-time cost per distinct constant
# without weakening it — same input, same integer, forever.
_fxc = lru_cache(maxsize=None)(fx)

# Tissue scatter gives up after this many rejected candidate positions.
# Dropping a few scatter entries beats packing them into spike hulls.
_TISSUE_PLACE_ATTEMPTS = 6


# Spike spatial_class — nothing that isn't also a spike is allowed to spawn
# inside a spike's VISUAL hull (kind_config.physics.visual_radius). Spikes
# can overlap each other (same primitive family); companions sit OUTSIDE.
_SPIKE_KINDS_KEEPOUT = {k for k, v in _kc.all_kinds().items()
                        if v.get("spatial_class") == "spike"}

# Minimum companion-to-companion separation to prevent overlap piles.
# Small — they're meant to enhance, not stack.
_COMPANION_MIN_SEP = 0.5

# Shared with brain_server / tile_exchange — single number per kind, ×sv
# for per-instance. Walk-through threshold keeps grass/moss non-blocking
# to the player while still preserving a spawn footprint for separation.
PLAYER_STOP_THRESHOLD = 0.5
VISUAL_RADII = {k: float(v.get("visual_radius", 0.0))
                for k, v in _kc.all_kinds().items()}

# Fixed-point mirrors — the generation path reads THESE; the float tables
# above stay for brain_server / tile_exchange, which are render-side.
PLAYER_STOP_THRESHOLD_FX = fx(PLAYER_STOP_THRESHOLD)
VISUAL_RADII_FX = {k: fx(v) for k, v in VISUAL_RADII.items()}

# kind_config scale/color, quantized once at import. Authored decimals are
# lossless at 3 places — tests/test_fixed_point.py guards that.
KIND_PROPS_FX = {
    k: {
        "scale": tuple(fx(n) for n in v["scale"]),
        "color": tuple(fx(n) for n in v["color"]),
    }
    for k, v in KIND_PROPS.items()
}

# Mean per-instance scale, in fx — the 1.30 that _make_entity multiplies
# every sv by. Keep-out at stamp time uses it so hull tests match the
# hulls that actually get rendered.
_MEAN_SV_FX = fx(1.30)


def _player_collision_radius_fx(kind: str, sv_fx: int) -> int:
    """Per-instance collision radius in fx. Walk-through kinds emit 0."""
    r = fx_mul(VISUAL_RADII_FX.get(kind, 0), sv_fx)
    return r if r >= PLAYER_STOP_THRESHOLD_FX else 0


def _spike_visual_radius_fx(kind: str, sv_fx: int = _MEAN_SV_FX) -> int:
    """Spike hull radius for spawn keep-out, in fx. Reads the authored
    kind_config.physics.visual_radius directly — simple center + radius,
    one number per kind. Default sv mirrors _make_entity's mean scale so
    stamp-time keep-out matches per-instance rendered hulls."""
    return fx_mul(VISUAL_RADII_FX.get(kind, 0), sv_fx)


# Mega stamps — these get filtered out of the neighborhood around the
# origin hub so the authored hub doesn't get swallowed by adjacent mega
# anchors. The transition from hub → procedural should feel intentional.
_MEGA_STAMP_NAMES = {"obelisk_court", "column_henge", "buttress_arch"}

# Authored-slot dispatch. Keys are the slot-name strings declared in
# BIOME_REGISTRY[biome_name]["authored_slots"] values; values are the
# authored stamp + salt seed to apply at that slot.
#
# When stamp_at() hits an authored slot, it looks up the slot name here
# and runs _instantiate_authored with the stamp + salt. Adding a new
# authored scene = one entry in BIOME_REGISTRY + one entry here.
_AUTHORED_SLOT_DISPATCH = {
    "hub_origin":     (ORIGIN_HUB,     0xBADC0DE),
    "encounter_test": (ENCOUNTER_TEST, 0xB47C0DE),
    "shadow_lab":     (SHADOW_LAB,     0x5ADC0DE),
}


# Slot grid — each cell holds one stamp. 16m matches the visible radius
# (49m / 3 ≈ 16m) so the camera always sees ~3-4 slots in every direction.
SLOT_SIZE = 16.0
SLOT_SIZE_FX = fx(SLOT_SIZE)
_SLOT_HALF_FX = SLOT_SIZE_FX // 2

# Minimum companion separation, in fx (mirrors _COMPANION_MIN_SEP).
_COMPANION_MIN_SEP_FX = fx(_COMPANION_MIN_SEP)

# Tissue scatter config now lives in biome_data.TISSUE_KINDS_* and is
# exposed via BIOME_REGISTRY[biome_name]["tissue_kinds"]. See _tissue_for().


# -- Radial density curve -----------------------------------------------------
#
# Classic "old-dev" procedural trick: world feels authored by making density
# vary with distance from origin. Near spawn the world is CLEAR (player eye
# doesn't get buried in clutter). Middle distance is the current baseline.
# Frontier is heavy/dense — rewards exploration with more to see.
#
# Bands are radial in slot units. Origin is (0, 0); 1 slot = SLOT_SIZE = 16m.
# Hub itself is slot (0, 0) authored; HUB_ADJACENT_SLOTS are already mega-
# filtered. This curve extends that idea to every slot, in bands.
#
# - spawn    (< 2 slots):   no mega stamps, half tissue, half flourishes
# - near     (< 5 slots):   weight<4 only, standard tissue
# - mid      (< 9 slots):   current baseline, all stamps
# - frontier (≥ 9):         mega weights 2×, standard tissue
#
# Band transitions are hard (no smooth interpolation) — players perceive
# change after walking ~48m (3 slots), which is long enough to read as
# "different place" and short enough to be felt in a single session.

BAND_SPAWN = "spawn"
BAND_NEAR = "near"
BAND_MID = "mid"
BAND_FRONTIER = "frontier"


def _radial_band(gx: int, gy: int) -> str:
    """Return the density band for a slot. Distance from origin in slot units."""
    d_sq = gx * gx + gy * gy
    if d_sq < 4:        # < 2 slots = ~32m
        return BAND_SPAWN
    if d_sq < 25:       # < 5 slots = ~80m
        return BAND_NEAR
    if d_sq < 81:       # < 9 slots = ~144m
        return BAND_MID
    return BAND_FRONTIER


def _filter_stamps_for_band(stamps: list, band: str) -> list:
    """Per-band stamp filtering. Spawn drops heavy anchors AND densely
    authored stamps so the landing zone reads as CLEAR. Near drops the
    heavy mega stamps but keeps medium-density stamps. Frontier boosts
    mega weights so they dominate the roll. Returns a (possibly-reweighted)
    stamps list that _weighted_pick consumes."""
    if band == BAND_SPAWN:
        # Spawn must feel OPEN — reject both heavy-weight anchors AND
        # high-member-count stamps (captured grove/grotto/arch stamps are
        # 30-90 members; the player shouldn't spawn facing a visual wall).
        return [s for s in stamps
                if s.get("weight", 1) < 4
                and len(s.get("members", [])) <= 12]
    if band == BAND_NEAR:
        return [s for s in stamps if s.get("weight", 1) < 4]
    if band == BAND_FRONTIER:
        # Mega-weight boost. Copy dicts (don't mutate upstream CAVERN_STAMPS).
        return [
            dict(s, weight=s.get("weight", 1) * (2 if s.get("weight", 1) >= 4 else 1))
            for s in stamps
        ]
    return stamps


def _tissue_mult_for_band(band: str) -> int:
    """Per-band tissue scatter multiplier, in fx. Spawn band gets half
    density so the player's first few meters are CLEAR — the 'landing
    zone' feeling."""
    if band == BAND_SPAWN:
        return fx(0.5)
    return FX_ONE


# -- Landmark beacons ---------------------------------------------------------
#
# Horizon trick: every ~17th slot hashes as a beacon slot. The slot still
# rolls its normal stamp (respecting the band filter) but ALSO gets a
# guaranteed mega_column anchor injected. From the bands below, this
# beacon is always visible in the distance — the player's eye finds it
# and the feet follow. Pure deterministic — hash of slot coords.
#
# ~1 in 17 slots ≈ 6% spawn rate → roughly one beacon per ~270m² area.
# With fog.far=55, the player usually sees 1-2 beacons at any moment.
#
# Beacons are suppressed in the spawn band (player shouldn't walk INTO
# a beacon on frame 1 — the landmark should be AHEAD, not underfoot).

_BEACON_MOD = 17
_BEACON_A = 9973
_BEACON_B = 8461


def _is_beacon_slot(gx: int, gy: int) -> bool:
    """Deterministic sparse pattern — 1/17 slots are landmark anchors."""
    return (gx * _BEACON_A + gy * _BEACON_B) % _BEACON_MOD == 0


def _beacon_member(gx: int, gy: int) -> dict:
    """Beacon mega_column placed at slot center. Scale 1.1 for visual
    dominance over neighbor mega_columns that happen to land nearby."""
    return {
        "kind": "mega_column",
        "dx_fx": 0,
        "dy_fx": 0,
        "scale_mult_fx": fx(1.1),
        "hard": True,
    }


def _slot_seed(gx: int, gy: int, world_seed: int) -> int:
    """Deterministic per-slot seed, via the C reference kernel.

    Was `world_seed ^ (gx*7919) ^ (gy*6271 << 1)` — a bare XOR with no
    avalanche. `rng_chunk_seed` is the substrate the Flipper generates
    from: it mixes both coordinates through an fmix pass and promotes
    0 -> 1 so a slot can never land on the degenerate xorshift state.

    THE COORDINATE MAP IS LOAD-BEARING, and it is here because porting to
    the kernel exposed a property of the kernel itself:

        rng_chunk_seed(s, cx, cy) == rng_chunk_seed(s, -cx, -cy)
        whenever cx and cy have the same number of trailing zero bits.

    Both coordinate multipliers are odd, so cx and cy contribute terms
    whose lowest set bit is at the same position; negating both
    complements the same bit positions in each, and the XOR is unchanged.
    ~16% of coordinate pairs within +/-64 slots collide, every (n, n)
    diagonal included. Verified against the C directly, not inferred from
    this port.

    It does NOT surface in the Flipper's own worlds: `world_generate_chunk`
    also folds in `biome_of` and `pool_at`, each separately salted, so
    mirrored chunk fingerprints diverge anyway (measured). It DID surface
    here, where the slot seed is a slot's only entropy — slot (1, 1) and
    slot (-1, -1) grew the same stamp at the same rotation with the same
    per-entity jitter, mirror twins 45 m apart.

    So the map forces the two terms into disjoint trailing-zero classes
    (gx odd, gy even), making the collision unreachable by construction:
    injective over +/-256 slots (+/-4 km) at three seeds. The kernel is
    untouched — this is a call-site choice about the desktop's own slot
    grid, which the Flipper does not share.

    Changing any of this reshuffles every slot in every world. That is the
    intended, versioned consequence — see GENERATOR_VERSION.
    """
    return rng_chunk_seed(world_seed & _U32, 2 * gx + 1, 2 * gy)


def _stamps_for(biome_name: str) -> list:
    return BIOME_REGISTRY.get(biome_name, BIOME_REGISTRY["cavern"])["stamps"]


def _tissue_for(biome_name: str) -> list:
    return BIOME_REGISTRY.get(biome_name, BIOME_REGISTRY["cavern"])["tissue_kinds"]


# Per-instance jitter bands, in fx. Each is a HALF-OPEN [lo, hi) draw, so
# the upper literal is one fx unit past the authored bound. These replace
# rng.uniform(lo, hi); the C kernel's rng_range is half-open too, which is
# what makes the two implementations agree.
_SV_JITTER_LO, _SV_JITTER_HI = fx(0.75), fx(1.25) + 1
_SZ_JITTER_LO, _SZ_JITTER_HI = fx(0.80), fx(1.20) + 1
_RGB_JITTER_LO, _RGB_JITTER_HI = fx(0.85), fx(1.15) + 1
_HEADING_TENTHS = 3600      # heading is drawn in tenths of a degree
_LIGHT_HUE_COUNT = 4


def _make_entity(kind: str, x_fx: int, y_fx: int, rng: Rng,
                 scale_mult_fx: int = FX_ONE) -> Dict | None:
    """Build an entity dict from KIND_PROPS + per-instance jitter.

    THE EMIT BOUNDARY. Everything reaching this function is fixed-point;
    everything leaving it is float. `emit()` is the only division.

    collision_radius is read from kind_config.physics.visual_radius × sv.
    Walk-through kinds (visual_radius < PLAYER_STOP_THRESHOLD per instance)
    emit 0. Single source of truth shared with brain_server + tile_exchange.

    Draw order (sv, heading, sz, r, g, b, light_hue) is load-bearing: the
    slot's Rng is a single stream, so reordering these shifts every
    subsequent entity in the slot.
    """
    props = KIND_PROPS.get(kind)
    props_fx = KIND_PROPS_FX.get(kind)
    if props is None or props_fx is None:
        return None
    sv_fx = fx_mul(fx_mul(rng_range(rng, _SV_JITTER_LO, _SV_JITTER_HI),
                          _MEAN_SV_FX), scale_mult_fx)
    sx_fx, sy_fx, sz_fx = props_fx["scale"]
    r_fx, g_fx, b_fx = props_fx["color"]
    coll_fx = _player_collision_radius_fx(kind, sv_fx)
    heading_tenths = rng_range(rng, 0, _HEADING_TENTHS)
    sz_jit = rng_range(rng, _SZ_JITTER_LO, _SZ_JITTER_HI)
    r_jit = rng_range(rng, _RGB_JITTER_LO, _RGB_JITTER_HI)
    g_jit = rng_range(rng, _RGB_JITTER_LO, _RGB_JITTER_HI)
    b_jit = rng_range(rng, _RGB_JITTER_LO, _RGB_JITTER_HI)
    light_hue = rng_range(rng, 0, _LIGHT_HUE_COUNT)
    return {
        "kind": kind,
        "x": emit(x_fx, 2),
        "y": emit(y_fx, 2),
        "z": 0.0,
        "heading": emit(heading_tenths * 100, 1),
        "sv": emit(sv_fx),
        "sx": emit(fx_mul(sx_fx, sv_fx)),
        "sy": emit(fx_mul(sy_fx, sv_fx)),
        "sz": emit(fx_mul(sz_fx, sz_jit)),
        "r": emit(fx_mul(r_fx, r_jit)),
        "g": emit(fx_mul(g_fx, g_jit)),
        "b": emit(fx_mul(b_fx, b_jit)),
        "emissive": props["emissive"],
        "light_hue": light_hue,
        "collision_radius": emit(coll_fx),
        "tile_variant": "standard",
        "behavior_type": "",
        "decay_stage": 0.0,
        "_chain_index": 0,
    }


def _weighted_pick(stamps: list, rng: Rng) -> Dict:
    """Pick one stamp using its `weight` field (default 1).

    Mega stamps (obelisk_court, column_henge, buttress_arch) carry
    weight: 4 in biome_data.py so they dominate the selection — a
    claustrophobic cavern needs big anchors in ~half the slots, not
    ~a fifth.

    Weights are carried in fx so fractional author weights still work; the
    draw is exact integer cumulative selection, with none of the "does the
    float sum land above or below the last boundary" fragility the
    `return stamps[-1]` numerical-safety line used to cover.
    """
    weights_fx = [_fxc(s.get("weight", 1)) for s in stamps]
    total = sum(weights_fx)
    return stamps[weighted_index(weights_fx, rng_range(rng, 0, total))]


def _instantiate_authored(stamp: Dict, world_cx_fx: int, world_cy_fx: int,
                          seed: int, salt: int) -> List[Dict]:
    """Emit any authored stamp's members at a given world position (fx).

    Shared path for ORIGIN_HUB and ENCOUNTER_TEST — authored anchors
    skip weighted selection and tissue scatter, own their coordinate
    frame, and apply per-member scale_mult literally.
    """
    rng = Rng((seed ^ salt) & _U32)
    roster: list[Dict] = []
    for member in stamp["members"]:
        kind = member["kind"]
        x_fx = world_cx_fx + _fxc(member.get("dx", 0.0))
        y_fx = world_cy_fx + _fxc(member.get("dy", 0.0))
        scale_mult_fx = _fxc(member.get("scale_mult") or 1.0)
        ent = _make_entity(kind, x_fx, y_fx, rng, scale_mult_fx)
        if ent is not None:
            roster.append(ent)
    return roster


def stamp_at(gx: int, gy: int, seed: int, biome_name: str) -> List[Dict]:
    """Pure function: slot coords → entity list.

    Authored slots (declared in BIOME_REGISTRY[biome_name]["authored_slots"])
    are hand-placed scenes that own their slot exclusively — the origin
    hub, the encounter-test fixture, the shadow lab. All other slots
    draw procedurally via weighted selection. The mega-stamp exclusion
    set keeps specific slots off the mega-stamp pool so transitions read
    cleanly.
    """
    registry = BIOME_REGISTRY.get(biome_name, BIOME_REGISTRY["cavern"])

    # Authored slot dispatch — one table, config-driven from biome registry.
    authored_slots = registry.get("authored_slots", {})
    slot_key = authored_slots.get((gx, gy))
    if slot_key is not None:
        stamp, salt = _AUTHORED_SLOT_DISPATCH[slot_key]
        # Origin hub is always pinned to world (0, 0) regardless of slot
        # center offset; other authored scenes use the slot grid origin.
        if slot_key == "hub_origin":
            cx_fx, cy_fx = 0, 0
        else:
            cx_fx, cy_fx = gx * SLOT_SIZE_FX, gy * SLOT_SIZE_FX
        return _instantiate_authored(stamp, cx_fx, cy_fx, seed, salt)

    stamps = _stamps_for(biome_name)
    if not stamps:
        return []

    # Mega-stamp exclusion — slots near authored anchors keep the
    # periphery calm so the authored composition stays readable.
    if (gx, gy) in registry.get("mega_stamp_exclusion_slots", set()):
        stamps = [s for s in stamps if s.get("name") not in _MEGA_STAMP_NAMES]

    # Radial density band — world feels "goes somewhere" because density
    # + stamp weight class vary with distance from origin. Spawn clear,
    # frontier heavy. See band definitions above.
    band = _radial_band(gx, gy)
    stamps = _filter_stamps_for_band(stamps, band)
    if not stamps:
        # Band filter removed everything (unlikely but defensive) — fall
        # back to original list rather than returning empty.
        stamps = _stamps_for(biome_name)

    rng = Rng(_slot_seed(gx, gy, seed))
    # Slot center, exact in fx: (gx + 0.5) * SLOT_SIZE with no fraction.
    cx_fx = gx * SLOT_SIZE_FX + _SLOT_HALF_FX
    cy_fx = gy * SLOT_SIZE_FX + _SLOT_HALF_FX

    # Pick one stamp from the library via weighted selection
    stamp = _weighted_pick(stamps, rng)

    # Slot rotation — rotates the whole stamp by 0/90/180/270 to add variety
    rotation_steps = rng_range(rng, 0, 4)
    cos_r = [1, 0, -1, 0][rotation_steps]
    sin_r = [0, 1, 0, -1][rotation_steps]

    roster = []
    # Track solid positions (x, y, keep_out_radius). Spikes go first so the
    # spike hulls are populated before any companion placement can overlap.
    # Spike-on-spike overlap is allowed (same primitive family); every
    # non-spike member is tested against all already-placed spike hulls
    # and rejected if inside — per user rule "nothing spawns within the
    # internal boundaries of spike types" (applies to authored stamp
    # members too, not just procedural scatter).
    # (x_fx, y_fx, keep_out_radius_fx)
    solid_positions: list[tuple[int, int, int]] = []

    # Pass 1 — spike members (overlap allowed between spikes).
    pending_nonspike: list[tuple[str, int, int, int]] = []
    for member in stamp["members"]:
        kind = member["kind"]
        dx_local = _fxc(member.get("dx", 0.0))
        dy_local = _fxc(member.get("dy", 0.0))
        # cos_r / sin_r are exactly 0 or ±1 — a quarter-turn is integer
        # rotation, so no trig and no rounding enters placement.
        dx_world = dx_local * cos_r - dy_local * sin_r
        dy_world = dx_local * sin_r + dy_local * cos_r
        x_fx = cx_fx + dx_world
        y_fx = cy_fx + dy_world
        scale_mult_fx = _fxc(member.get("scale_mult") or 1.0)
        if kind in _SPIKE_KINDS_KEEPOUT:
            ent = _make_entity(kind, x_fx, y_fx, rng, scale_mult_fx)
            if ent is not None:
                roster.append(ent)
                solid_positions.append(
                    (x_fx, y_fx, _spike_visual_radius_fx(kind)))
        else:
            pending_nonspike.append((kind, x_fx, y_fx, scale_mult_fx))

    # Landmark beacon — if this slot's hash marks it as a beacon AND the
    # band allows it (no beacons in the spawn band; they should be AHEAD,
    # not underfoot), inject a guaranteed mega_column at slot center.
    # Spikes can overlap so this coexists with whatever stamp rolled.
    if band != BAND_SPAWN and _is_beacon_slot(gx, gy):
        beacon = _beacon_member(gx, gy)
        bx_fx, by_fx = cx_fx, cy_fx  # slot center
        b_ent = _make_entity(beacon["kind"], bx_fx, by_fx, rng,
                             beacon["scale_mult_fx"])
        if b_ent is not None:
            roster.append(b_ent)
            solid_positions.append(
                (bx_fx, by_fx, _spike_visual_radius_fx(beacon["kind"])))

    # Pass 2 — non-spike authored members. Each candidate rejected if its
    # center sits inside a spike hull from pass 1. Companions that survive
    # get registered with a small footprint so later scatter doesn't pile.
    for kind, x_fx, y_fx, scale_mult_fx in pending_nonspike:
        blocked = False
        for sx, sy, sr in solid_positions:
            # Squared compare in fx² — exact, no sqrt, no float.
            if (x_fx - sx) ** 2 + (y_fx - sy) ** 2 < sr * sr:
                blocked = True
                break
        if blocked:
            continue
        ent = _make_entity(kind, x_fx, y_fx, rng, scale_mult_fx)
        if ent is not None:
            roster.append(ent)
            solid_positions.append((x_fx, y_fx, _COMPANION_MIN_SEP_FX))

    # Tissue scatter — fills the negative space within the slot bounds.
    # Each tissue kind rolls its count, positions are within the slot square.
    # Spike hulls and neighbor companions reject candidates to keep geometry
    # from overlapping — companions enhance clusters, never pile into them.
    # Band multiplier keeps spawn zone ~half density for the "landing zone"
    # feel; mid/frontier at full (1.0) count.
    tissue_mult_fx = _tissue_mult_for_band(band)
    for kind, base_count in _tissue_for(biome_name):
        count = max(0, fx_scale_int(base_count, tissue_mult_fx))
        for _ in range(count):
            placed = False
            for _attempt in range(_TISSUE_PLACE_ATTEMPTS):
                x_fx = cx_fx + rng_range(rng, -_SLOT_HALF_FX,
                                         _SLOT_HALF_FX + 1)
                y_fx = cy_fx + rng_range(rng, -_SLOT_HALF_FX,
                                         _SLOT_HALF_FX + 1)
                too_close = False
                for sx, sy, sr in solid_positions:
                    dx = x_fx - sx
                    dy = y_fx - sy
                    if dx * dx + dy * dy < sr * sr:
                        too_close = True
                        break
                if too_close:
                    continue
                ent = _make_entity(kind, x_fx, y_fx, rng)
                if ent is not None:
                    roster.append(ent)
                    solid_positions.append(
                        (x_fx, y_fx, _COMPANION_MIN_SEP_FX))
                placed = True
                break
            if not placed:
                # All 6 attempts collided — drop this scatter slot silently.
                # Rejecting a few tissue entries is preferable to packing
                # them into spike hulls; scatter density isn't load-bearing.
                pass

    return roster


# Per-kind max render distance — the old-school trick. Tiny floor scatter
# (gravel, twigs) only meaningful within touching distance; big landmarks
# (mega_column, crystal_cluster) visible to the fog horizon. Dropping low-
# value entities past their useful range is the biggest perf wedge at
# spawn (where density spikes from the authored hub + adjacent slots).
# Values tuned against eye-height and fog.far=55. Kinds not listed fall
# back to the global visibility radius.
_KIND_MAX_DISTANCE = {
    # scatter — tiny, no silhouette beyond arm's reach
    "cave_gravel":     8.0,
    "twig_scatter":   10.0,
    "leaf_pile":      14.0,
    "rubble":         16.0,
    "bone_pile":      16.0,
    "grass_tuft":     18.0,
    "moss_patch":     18.0,
    "filament":       22.0,
    # organic — mid-distance silhouettes that matter from further
    "spore_pod":      25.0,
    "toadstool":      25.0,
    "giant_fungus":   35.0,
    # atmosphere
    "ceiling_moss":   28.0,
    "hanging_vine":   28.0,
    "firefly":        20.0,
    # structural — landmarks visible to the horizon
    "stalagmite":     40.0,
    "boulder":        40.0,
    "buttress":       45.0,
    "monolith":       45.0,
    "crystal_cluster": 50.0,
    "column":         55.0,
    "mega_column":    55.0,
    "dead_log":       30.0,
    "doorframe":      30.0,
    # life — creatures close range (they move, so aggressive cull OK)
    "beetle":         12.0,
    "spider":         15.0,
    "rat":            25.0,
    "rat_ice":        25.0,
    "rat_fire":       25.0,
    "rat_water":      25.0,
    "bat":            30.0,
    "clay_pot":       25.0,
    "treasure_chest": 25.0,
    # encounter fixtures stay visible to fog edge
    "orb":            50.0,
    "shadow_orb":     50.0,
    "exit_lure":      55.0,
}

# Scale fade — entities SMOOTHLY shrink to invisible over the last
# SCALE_FADE_BAND meters of their per-kind max_distance. Unlike the
# earlier stochastic dither, this is deterministic and continuous — no
# pop, no random flicker. Same silhouette, just scaled by dist.
SCALE_FADE_BAND = 14.0  # smooth fade window before a kind's max_distance
SCALE_MIN = 0.02        # smallest visible scale before hard cull


def _kind_scale_factor(kind: str, dist: float) -> float:
    """Per-kind smooth scale fade. Entities at full scale until fade_start,
    then linearly shrink to SCALE_MIN at max_distance, hard-culled beyond.
    Replaces the old stochastic dither — same perf benefit, no pop."""
    max_d = _KIND_MAX_DISTANCE.get(kind, 999.0)
    if dist >= max_d:
        return 0.0  # beyond kind's range — caller should drop the entity
    fade_start = max_d - SCALE_FADE_BAND
    if dist <= fade_start:
        return 1.0
    # Linear shrink over the fade band
    t = (max_d - dist) / SCALE_FADE_BAND  # 1.0 at fade_start → 0.0 at max_d
    return SCALE_MIN + (1.0 - SCALE_MIN) * t


def _scale_factor(dist: float, radius: float) -> float:
    """Distance-driven scale fade. 1.0 inside fade band, lerps to SCALE_MIN at edge."""
    fade_start = radius - SCALE_FADE_BAND
    if dist <= fade_start:
        return 1.0
    if dist >= radius:
        return SCALE_MIN
    # Smooth lerp across the fade band
    t = (radius - dist) / SCALE_FADE_BAND  # 1.0 at fade_start, 0.0 at radius
    return SCALE_MIN + (1.0 - SCALE_MIN) * t


def get_visible(cam_x: float, cam_y: float, radius: float,
                seed: int, biome_name: str) -> List[Dict]:
    """Collect all entities from slots overlapping the camera circle.

    No cache. Iterates the AABB of slots that could intersect the circle,
    calls stamp_at for each, then filters entities by exact distance.
    Applies a distance-driven scale fade so entities grow as you approach
    the visibility edge — no instant pop-in.
    """
    radius_sq = radius * radius

    gx_min = int(math.floor((cam_x - radius) / SLOT_SIZE))
    gx_max = int(math.floor((cam_x + radius) / SLOT_SIZE))
    gy_min = int(math.floor((cam_y - radius) / SLOT_SIZE))
    gy_max = int(math.floor((cam_y + radius) / SLOT_SIZE))

    visible = []
    for gx in range(gx_min, gx_max + 1):
        for gy in range(gy_min, gy_max + 1):
            for ent in stamp_at(gx, gy, seed, biome_name):
                dx = ent["x"] - cam_x
                dy = ent["y"] - cam_y
                d2 = dx * dx + dy * dy
                if d2 > radius_sq:
                    continue
                dist = math.sqrt(d2)
                # Per-kind smooth fade — tiny scatter only renders near,
                # landmarks to the horizon. Entity shrinks linearly over
                # the last SCALE_FADE_BAND meters of its max_distance, then
                # hard-culls. Deterministic, continuous, no pop.
                # Per-kind visibility cull stays — it's data-level (entity too
                # far for its kind, don't ship it). The scale-fade application
                # that USED to live here was moved out per design_brain_ground_truth
                # 2026-04-28 — it was render-hint smoothing for Godot's PBR
                # pipeline, which belongs in the renderer, not the brain.
                # Vector terminal renders raw scales; if Godot wants the
                # smooth grow-in back, it applies it client-side.
                fade = _kind_scale_factor(ent["kind"], dist)
                if fade <= 0.0:
                    continue  # beyond kind's visibility — drop
                visible.append(ent)

    return visible
