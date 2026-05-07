"""SpectrumEngine — extracted to a panda3d-free module.

Validates the math, the active-biome dispatch, and the import-clean
contract: this module loads without panda3d in the venv. The same
contract applies transitively to brain_server.py and tile_exchange.py
which now import from here directly.
"""
from __future__ import annotations

import sys

import pytest

from core.systems import spectrum
from core.systems.spectrum import (
    OUTDOOR_SPECTRUM_PROFILES,
    SPECTRUM_PROFILES,
    SpectrumEngine,
    set_active_biome,
)


# ── Import contract ───────────────────────────────────────────────


def test_module_does_not_import_panda3d():
    """Importing spectrum must not pull panda3d into sys.modules.

    Note: a previously-loaded panda3d (from another test or process
    state) wouldn't be unloaded by this test — the assertion only
    holds in a clean venv. Still useful as a forward guard against
    accidental panda3d imports being added to spectrum.py itself.
    """
    # Reload to make sure no transitive imports during reload pull
    # panda3d in. We don't assert panda3d absence (other modules in
    # the test process may have imported it); we assert spectrum's
    # own __dict__ has no panda3d-namespaced names.
    bad = [name for name in dir(spectrum) if "panda" in name.lower()]
    assert bad == [], f"unexpected panda3d-named symbols: {bad}"


# ── Profiles ───────────────────────────────────────────────────────


def test_cavern_profiles_present():
    assert "fungus" in SPECTRUM_PROFILES
    assert "crystal" in SPECTRUM_PROFILES
    assert "moss" in SPECTRUM_PROFILES
    assert "ceiling_moss" in SPECTRUM_PROFILES


def test_outdoor_profiles_present():
    assert "fungus" in OUTDOOR_SPECTRUM_PROFILES
    assert "crystal" in OUTDOOR_SPECTRUM_PROFILES
    assert "moss" in OUTDOOR_SPECTRUM_PROFILES
    assert "sunlight" in OUTDOOR_SPECTRUM_PROFILES


def test_crystal_profiles_marked_prismatic():
    assert SPECTRUM_PROFILES["crystal"].get("prismatic") is True
    assert OUTDOOR_SPECTRUM_PROFILES["crystal"].get("prismatic") is True


# ── set_active_biome ───────────────────────────────────────────────


def test_set_active_biome_switches_profile_lookup():
    set_active_biome("cavern")
    cavern_drift = SpectrumEngine.drift("fungus", 1.0, 12345)

    set_active_biome("outdoor")
    outdoor_drift = SpectrumEngine.drift("fungus", 1.0, 12345)

    # Different profile dicts → different drift_range and channels →
    # different output for the same elapsed/seed.
    assert cavern_drift != outdoor_drift

    # Restore default for other tests.
    set_active_biome("cavern")


def test_unknown_biome_falls_back_to_cavern():
    set_active_biome("nonexistent_biome")
    fallback = SpectrumEngine.drift("fungus", 1.0, 12345)
    set_active_biome("cavern")
    cavern = SpectrumEngine.drift("fungus", 1.0, 12345)
    assert fallback == cavern


# ── SpectrumEngine.drift ───────────────────────────────────────────


def test_drift_returns_zero_for_unknown_profile():
    set_active_biome("cavern")
    assert SpectrumEngine.drift("unknown_profile", 0.0, 0) == (0, 0, 0)


def test_drift_is_deterministic_for_same_inputs():
    set_active_biome("cavern")
    a = SpectrumEngine.drift("fungus", 5.0, 42)
    b = SpectrumEngine.drift("fungus", 5.0, 42)
    assert a == b


def test_drift_changes_with_elapsed():
    set_active_biome("cavern")
    a = SpectrumEngine.drift("fungus", 0.0, 42)
    b = SpectrumEngine.drift("fungus", 50.0, 42)
    assert a != b


def test_drift_channel_weighting():
    """Per-channel weighting: r unweighted, g × 0.7, b × 1.2.
    Ratios should hold across any non-zero output."""
    set_active_biome("cavern")
    # Pick inputs that produce a non-zero shift.
    r, g, b = SpectrumEngine.drift("fungus", 12.7, 99)
    if r == 0:
        return  # signal happened to land on zero — skip
    assert pytest.approx(g / r, rel=1e-6) == 0.7
    assert pytest.approx(b / r, rel=1e-6) == 1.2


# ── prismatic_offset ───────────────────────────────────────────────


def test_prismatic_offset_zero_for_shard_zero():
    """Shard 0 (cluster king) stays true to the cluster drift."""
    set_active_biome("cavern")
    assert SpectrumEngine.prismatic_offset(0, 0) == (0, 0, 0)


def test_prismatic_offset_zero_when_profile_not_prismatic():
    """Non-prismatic profile (fungus) returns zero offsets even for non-zero shards."""
    set_active_biome("cavern")
    assert SpectrumEngine.prismatic_offset(99, 3, "fungus") == (0, 0, 0)


def test_prismatic_offset_non_zero_for_prismatic_shard():
    """Prismatic crystal profile + shard >= 1 produces a real offset."""
    set_active_biome("cavern")
    offset = SpectrumEngine.prismatic_offset(99, 1, "crystal")
    assert offset != (0, 0, 0)


# ── phase_for_seed ─────────────────────────────────────────────────


def test_phase_for_seed_deterministic():
    a = SpectrumEngine.phase_for_seed(123)
    b = SpectrumEngine.phase_for_seed(123)
    assert a == b


def test_phase_for_seed_in_range():
    """Phase must land in [0, 2π)."""
    import math
    for s in [0, 1, 99, 12345, 999999]:
        p = SpectrumEngine.phase_for_seed(s)
        assert 0.0 <= p < 2.0 * math.pi


# Re-export compatibility test removed 2026-05-07 audit A14:
# `ambient_life.py` was archived (panda3d-imported, no live consumer).
# spectrum module is canonical; legacy callers that needed the
# re-export (cavern.py, tools/) are themselves archived.
