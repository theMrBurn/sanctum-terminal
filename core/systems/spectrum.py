"""SpectrumEngine — polyrhythmic hue drift, panda3d-free.

Extracted from `core/systems/ambient_life.py` to break the panda3d
import bleed into the live brain pipeline. `ambient_life.py` is the
legacy Panda3D viewer's behavior-loop module; importing it forces
panda3d into any process that uses spectrum drift, even though the
math itself is pure Python.

Live consumers (`brain_server.py`, `core/systems/tile_exchange.py`)
import directly from this module. `ambient_life.py` re-exports these
names so legacy / tooling consumers (`cavern.py`, `tools/*`) keep
working without code change. Single source of truth lives here;
the active-biome global owns its state in this module too.

Per `feedback_audit_oversells_legacy` and the live-vs-legacy boundary
documented in `LIVE_PIPELINE_MAP.md`. This is one targeted slice; the
broader audit of panda3d bleed is a separate effort.
"""
from __future__ import annotations

import math
import random


# ── Spectrum profiles per biome ─────────────────────────────────────
# Polyrhythmic — multiple sine channels at incommensurate frequencies
# so no two entities ever sync. Per-entity phase from seed scatters
# things further. Saturn/PS1 trick: read a 256-entry sine LUT instead
# of calling math.sin per frame.

SPECTRUM_PROFILES = {
    "fungus": {
        "base_hue": (0.22, 0.06, 0.30),
        "drift_range": 0.18,
        "channels": [
            {"freq": 0.017, "amp": 1.0},    # ~60s full cycle
            {"freq": 0.011, "amp": 0.6},    # ~90s, polyrhythmic offset
            {"freq": 0.007, "amp": 0.3},    # ~140s, deep slow drift
        ],
    },
    "crystal": {
        "base_hue": (0.15, 0.18, 0.35),
        "drift_range": 0.12,
        "channels": [
            {"freq": 0.013, "amp": 1.0},    # ~77s cycle
            {"freq": 0.0087, "amp": 0.5},   # ~115s
            {"freq": 0.0053, "amp": 0.25},  # ~188s
        ],
        "prismatic": True,                   # per-shard facet offsets
        "facet_spread": 0.12,                # ±12% channel offset per shard
    },
    "moss": {
        "base_hue": (0.08, 0.35, 0.06),
        "drift_range": 0.10,
        "channels": [
            {"freq": 0.009, "amp": 1.0},    # ~111s — slowest, most organic
            {"freq": 0.006, "amp": 0.4},    # ~167s
        ],
    },
    "ceiling_moss": {
        "base_hue": (0.80, 0.55, 0.15),
        "drift_range": 0.08,
        "channels": [
            {"freq": 0.012, "amp": 1.0},
            {"freq": 0.0073, "amp": 0.5},
        ],
    },
}

# Outdoor — same drift engine, PNW palette. Bioluminescence becomes
# natural light. Slower drift = weather/wind, not metabolism.
OUTDOOR_SPECTRUM_PROFILES = {
    "fungus": {  # giant_fungus → large bush / rhododendron
        "base_hue": (0.12, 0.28, 0.08),    # forest green
        "drift_range": 0.08,                 # subtle — wind, not glow
        "channels": [
            {"freq": 0.008, "amp": 1.0},    # ~125s — breeze cycle
            {"freq": 0.005, "amp": 0.4},    # ~200s — slow sway
        ],
    },
    "crystal": {  # crystal_cluster → flowering shrub / wildflower
        "base_hue": (0.35, 0.20, 0.12),    # warm flower
        "drift_range": 0.10,
        "channels": [
            {"freq": 0.010, "amp": 1.0},    # ~100s
            {"freq": 0.006, "amp": 0.5},    # ~167s
        ],
        "prismatic": True,                   # per-petal color variation
        "facet_spread": 0.08,
    },
    "moss": {  # moss_patch → natural ground moss
        "base_hue": (0.06, 0.22, 0.04),    # deep natural green
        "drift_range": 0.05,                 # almost static
        "channels": [
            {"freq": 0.004, "amp": 1.0},    # ~250s — moisture cycle
        ],
    },
    "sunlight": {  # outdoor-only — dappled sun on forest floor
        "base_hue": (0.45, 0.38, 0.15),    # warm gold
        "drift_range": 0.12,                 # cloud shadows passing
        "channels": [
            {"freq": 0.015, "amp": 1.0},    # ~67s — cloud drift
            {"freq": 0.009, "amp": 0.6},    # ~111s — canopy sway
            {"freq": 0.004, "amp": 0.3},    # ~250s — time of day
        ],
    },
}


# Biome → spectrum-profiles lookup. ambient_life's BIOME_REGISTRY
# mirrors this for legacy purposes; this is the live source.
_BIOME_SPECTRUM = {
    "cavern": SPECTRUM_PROFILES,
    "outdoor": OUTDOOR_SPECTRUM_PROFILES,
}


# ── Active biome state ──────────────────────────────────────────────
# Module-global mirrors the ambient_life convention so the API surface
# stays drop-in compatible. Mutations go through set_active_biome().

_active_biome: str = "cavern"


def set_active_biome(biome: str) -> None:
    """Set the active biome. Spectrum drift / prismatic offset lookups
    will read from the matching profile dict afterward."""
    global _active_biome
    _active_biome = biome


def _profiles_for_active_biome() -> dict:
    """Return the spectrum-profiles dict for the current biome.
    Falls back to cavern if biome unknown — same behavior as
    ambient_life.biome_config('spectrum')."""
    return _BIOME_SPECTRUM.get(_active_biome, _BIOME_SPECTRUM["cavern"])


# ── SpectrumEngine ──────────────────────────────────────────────────


class SpectrumEngine:
    """Polyrhythmic hue drift + prismatic facet offsets.

    Each bio-lit entity gets a phase (from seed) and drifts through a
    color gradient on overlapping sine waves. No two entities sync.

    Prismatic mode (crystals): per-shard offsets on top of the drift,
    so facets shimmer independently while the cluster moves as a family.

    LUT mode: pre-computed 256-entry sine table. Zero trig at runtime —
    Saturn/PS1 trick.
    """

    # Pre-computed sine LUT — 256 entries covering 0..2π.
    _SIN_LUT = [math.sin(i * 2.0 * math.pi / 256.0) for i in range(256)]

    @staticmethod
    def phase_for_seed(seed: int) -> float:
        """Deterministic phase offset from entity seed — desynchronizes
        all entities. Golden-ratio scatter."""
        return (seed * 0.618033) % (2.0 * math.pi)

    @staticmethod
    def drift(profile_name: str, elapsed: float, seed: int) -> tuple:
        """Calculate hue shift for an entity at a given time.

        Returns `(r_shift, g_shift, b_shift)` to ADD to base colorScale.
        Uses LUT lookup instead of math.sin() — zero trig per frame.
        """
        profile = _profiles_for_active_biome().get(profile_name)
        if not profile:
            return (0, 0, 0)
        phase = SpectrumEngine.phase_for_seed(seed)
        lut = SpectrumEngine._SIN_LUT
        total = 0.0
        for ch in profile["channels"]:
            idx = int(
                (elapsed * ch["freq"] + phase * 0.15915494) * 256.0
            ) & 0xFF
            total += lut[idx] * ch["amp"]
        max_amp = sum(ch["amp"] for ch in profile["channels"])
        if max_amp > 0:
            total /= max_amp
        dr = profile["drift_range"]
        # Per-channel weighting: green shifts less (warmth), blue more
        # (cool/warm oscillation).
        r_shift = total * dr
        g_shift = total * dr * 0.7
        b_shift = total * dr * 1.2
        return (r_shift, g_shift, b_shift)

    @staticmethod
    def prismatic_offset(
        seed: int,
        shard_index: int,
        profile_name: str = "crystal",
    ) -> tuple:
        """Per-shard color offset for prismatic crystals.

        Shard 0 (king) stays true to the cluster drift. Others shift
        ± on one channel — reads as prismatic refraction.
        Returns `(r_off, g_off, b_off)` to ADD to shard colorScale.
        """
        profile = _profiles_for_active_biome().get(profile_name, {})
        if shard_index == 0 or not profile.get("prismatic"):
            return (0, 0, 0)
        spread = profile.get("facet_spread", 0.10)
        rng = random.Random(seed + shard_index * 73)
        channel = rng.randint(0, 2)
        amount = rng.uniform(-spread, spread)
        offsets = [0.0, 0.0, 0.0]
        offsets[channel] = amount
        # Subtle complementary shift on another channel.
        other = (channel + 1) % 3
        offsets[other] = -amount * 0.3
        return tuple(offsets)
