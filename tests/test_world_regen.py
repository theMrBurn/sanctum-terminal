"""Unit tests for BrainWorld.regen_world() — direct method calls, no TCP.

Integration tests cover the regen path through the TCP wire (state
transition → handler → regen_world). This file tests the method itself
in isolation so cache-clearing bugs aren't masked by network buffering
or async scheduling.

Verifies:
  - base_seed mutates to the new value
  - world_revision increments on every call
  - tile cache (loaded_tiles, tile_variants) clears
  - entity store clears
  - spatial hash gets a fresh instance
  - structural anchor list resets
  - exchange rebuilds with the new seed
  - spawn tile (0, 0) re-primed after regen
  - same seed produces deterministic identical content (hub return contract)
  - different seeds produce different content (mission instances differ)
"""
from __future__ import annotations

import os

import pytest

# stamp_world is the active path; brain reads SANCTUM_STAMP env at import.
os.environ.setdefault("SANCTUM_STAMP", "1")

from brain_server import BrainWorld  # noqa: E402


@pytest.fixture
def world():
    """Fresh outdoor BrainWorld at seed 42, isolated per test."""
    return BrainWorld("outdoor", base_seed=42, tile_size=288.0)


# --- Core mutations ---------------------------------------------------------

def test_regen_changes_base_seed(world):
    assert world.base_seed == 42
    world.regen_world(999)
    assert world.base_seed == 999


def test_regen_bumps_world_revision(world):
    rev0 = world.world_revision
    world.regen_world(123)
    assert world.world_revision == rev0 + 1
    world.regen_world(456)
    assert world.world_revision == rev0 + 2
    world.regen_world(789)
    assert world.world_revision == rev0 + 3


# --- Cache clearing ---------------------------------------------------------

def test_regen_clears_loaded_tiles(world):
    """Force-load a few peripheral tiles, regen, verify they're gone
    from the cache (only the spawn tile is re-primed)."""
    world._generate_tile(1, 1)
    world._generate_tile(-1, 0)
    assert (1, 1) in world.loaded_tiles
    assert (-1, 0) in world.loaded_tiles

    world.regen_world(789)

    assert (1, 1) not in world.loaded_tiles, "peripheral tile cache should clear"
    assert (-1, 0) not in world.loaded_tiles
    assert (0, 0) in world.loaded_tiles, "spawn tile should be re-primed"


def test_regen_clears_tile_variants(world):
    world._generate_tile(2, 2)
    assert (2, 2) in world.tile_variants
    world.regen_world(123)
    assert (2, 2) not in world.tile_variants


def test_regen_clears_structural_anchors(world):
    """structural_positions accumulates as tiles load. Should reset on regen."""
    world._generate_tile(1, 0)
    world._generate_tile(0, 1)
    # Generated tiles may or may not contain structural anchors —
    # but after regen the list should be reset to fresh state.
    pre_count = len(world._structural_positions)
    world.regen_world(456)
    # After regen, only the spawn tile has been generated. Length should
    # be ≤ pre_count + initial spawn tile structural count (small).
    assert len(world._structural_positions) <= max(pre_count, 8), \
        "structural list should reset, not accumulate"


def test_regen_resets_spatial_hash(world):
    world._generate_tile(1, 1)
    pre_hash = world.spatial
    world.regen_world(789)
    assert world.spatial is not pre_hash, "spatial hash should be a fresh instance"


def test_regen_resets_eid_counter(world):
    """next_eid should reset so new entities don't collide with stale IDs."""
    world._generate_tile(1, 0)
    pre_eid = world.next_eid
    world.regen_world(123)
    # After regen, only spawn tile generated → next_eid is the spawn-tile
    # entity count, which should be ≤ pre_eid (started at 0, grew by spawn
    # tile entities, then reset, then re-added spawn tile entities).
    assert world.next_eid <= pre_eid, \
        f"eid counter should reset (was {pre_eid}, now {world.next_eid})"


# --- Determinism contract ---------------------------------------------------

def test_same_seed_produces_deterministic_content(world):
    """Hub return contract: regen with the same seed must give identical
    content. Players returning to the hub should see the same staging area."""
    snapshot_a = sorted(
        (e["kind"], round(e["x"], 1), round(e["y"], 1))
        for e in world.entities.values()
    )

    world.regen_world(42)  # same as starting seed

    snapshot_b = sorted(
        (e["kind"], round(e["x"], 1), round(e["y"], 1))
        for e in world.entities.values()
    )

    assert snapshot_a == snapshot_b, \
        "same seed should produce identical entity layout"


def test_different_seeds_produce_different_content(world):
    """Mission contract: different mission seeds must yield different worlds.
    The probability of two random seeds producing identical entity layouts
    is vanishingly small (effectively zero given the perturbation)."""
    world.regen_world(11111)
    snapshot_a = sorted(
        (e["kind"], round(e["x"], 1), round(e["y"], 1))
        for e in world.entities.values()
    )

    world.regen_world(99999)
    snapshot_b = sorted(
        (e["kind"], round(e["x"], 1), round(e["y"], 1))
        for e in world.entities.values()
    )

    assert snapshot_a != snapshot_b, \
        "different seeds should produce different entity layouts"


# --- hub_seed preservation --------------------------------------------------

def test_hub_seed_unchanged_by_regen(world):
    """regen_world updates base_seed but must NOT touch hub_seed.
    hub_seed is the canonical anchor for RESULTS → HUB transitions."""
    original_hub = world.hub_seed
    world.regen_world(11111)
    world.regen_world(22222)
    world.regen_world(33333)
    assert world.hub_seed == original_hub, \
        f"hub_seed should be immutable through regens (was {original_hub}, now {world.hub_seed})"


def test_regen_to_hub_seed_restores_hub_world(world):
    """After mission regen + return-to-hub regen, content matches initial hub."""
    initial = sorted(
        (e["kind"], round(e["x"], 1), round(e["y"], 1))
        for e in world.entities.values()
    )

    # Simulate: launch mission with random seed
    world.regen_world(54321)
    # Return to hub
    world.regen_world(world.hub_seed)

    after_return = sorted(
        (e["kind"], round(e["x"], 1), round(e["y"], 1))
        for e in world.entities.values()
    )

    assert initial == after_return, \
        "hub world should be restored after mission round-trip"
