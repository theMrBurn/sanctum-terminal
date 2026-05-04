"""RoamingPool — spawns/wanders visible encounter agents around the player."""
from __future__ import annotations

import random
import pytest

from core.systems.roaming_pool import (
    RoamingPool, RoamingAgent, CONTACT_RADIUS,
)


# -- Spawn -------------------------------------------------------------------

def test_pool_spawns_configured_count():
    pool = RoamingPool(actor_id="watcher", biome="cavern",
                       target_count=3, seed=42)
    pool.ensure_population(center=(0.0, 0.0))
    assert len(pool.agents) == 3


def test_agents_spawn_within_spawn_radius():
    pool = RoamingPool(actor_id="watcher", biome="cavern",
                       target_count=5, seed=42)
    pool.ensure_population(center=(100.0, 100.0))
    for a in pool.agents:
        dx = a.x - 100.0
        dy = a.y - 100.0
        assert dx * dx + dy * dy <= pool.spawn_radius ** 2 + 1e-6


def test_agents_carry_actor_id():
    pool = RoamingPool(actor_id="watcher", biome="cavern",
                       target_count=3, seed=42)
    pool.ensure_population(center=(0.0, 0.0))
    for a in pool.agents:
        assert a.actor_id == "watcher"


# -- Wander ------------------------------------------------------------------

def test_wander_keeps_within_patrol_radius():
    pool = RoamingPool(actor_id="watcher", biome="cavern",
                       target_count=2, seed=42)
    pool.ensure_population(center=(0.0, 0.0))
    homes = [(a.home_x, a.home_y) for a in pool.agents]
    for _ in range(200):
        pool.tick(dt=0.1)
    for agent, home in zip(pool.agents, homes):
        dx = agent.x - home[0]
        dy = agent.y - home[1]
        assert dx * dx + dy * dy <= pool.patrol_radius ** 2 + 1e-6


# -- Contact detection -------------------------------------------------------

def test_detect_contact_returns_nearest():
    pool = RoamingPool(actor_id="watcher", biome="cavern",
                       target_count=3, seed=42)
    # Hand-place agents so we know expected nearest
    pool.agents = [
        RoamingAgent(id="a", actor_id="watcher", x=10.0, y=0.0,
                     home_x=10.0, home_y=0.0),
        RoamingAgent(id="b", actor_id="watcher", x=1.0, y=0.5,
                     home_x=1.0, home_y=0.5),
        RoamingAgent(id="c", actor_id="watcher", x=-5.0, y=-5.0,
                     home_x=-5.0, home_y=-5.0),
    ]
    contact = pool.detect_contact(cam_x=0.0, cam_y=0.0)
    assert contact is not None
    assert contact.id == "b"


def test_no_contact_when_all_far():
    pool = RoamingPool(actor_id="watcher", biome="cavern",
                       target_count=1, seed=42)
    pool.agents = [
        RoamingAgent(id="a", actor_id="watcher", x=100.0, y=100.0,
                     home_x=100.0, home_y=100.0),
    ]
    assert pool.detect_contact(cam_x=0.0, cam_y=0.0) is None


def test_contact_radius_bound():
    """Agent at exactly CONTACT_RADIUS distance triggers; beyond does not."""
    pool = RoamingPool(actor_id="watcher", biome="cavern",
                       target_count=1, seed=42)
    pool.agents = [
        RoamingAgent(id="edge", actor_id="watcher",
                     x=CONTACT_RADIUS - 0.01, y=0.0,
                     home_x=0.0, home_y=0.0),
    ]
    assert pool.detect_contact(0.0, 0.0) is not None

    pool.agents[0].x = CONTACT_RADIUS + 0.1
    assert pool.detect_contact(0.0, 0.0) is None


# -- Consume + respawn -------------------------------------------------------

def test_consume_removes_agent():
    pool = RoamingPool(actor_id="watcher", biome="cavern",
                       target_count=3, seed=42)
    pool.ensure_population(center=(0.0, 0.0))
    victim = pool.agents[0]
    pool.consume(victim.id)
    assert victim.id not in [a.id for a in pool.agents]


def test_respawn_after_cooldown():
    pool = RoamingPool(actor_id="watcher", biome="cavern",
                       target_count=3, seed=42, respawn_cooldown=2.0)
    pool.ensure_population(center=(0.0, 0.0))
    pool.consume(pool.agents[0].id)
    assert len(pool.agents) == 2
    # Not enough time — still 2
    pool.tick(dt=1.0, player_pos=(0.0, 0.0))
    assert len(pool.agents) == 2
    # Past cooldown — repopulates to target
    pool.tick(dt=2.0, player_pos=(0.0, 0.0))
    assert len(pool.agents) == 3


# -- Snapshot ----------------------------------------------------------------

def test_snapshot_shape():
    pool = RoamingPool(actor_id="watcher", biome="cavern",
                       target_count=2, seed=42)
    pool.ensure_population(center=(0.0, 0.0))
    snap = pool.snapshot()
    assert isinstance(snap, list)
    assert len(snap) == 2
    for e in snap:
        assert e["kind"] == "orb"
        assert "x" in e and "y" in e
        assert "actor_id" in e
        assert "hue_shift" in e
        assert 0.0 <= e["hue_shift"] <= 1.0
        assert "hp_bonus" in e
        assert -1 <= e["hp_bonus"] <= 2


def test_agents_carry_variant_data():
    pool = RoamingPool(actor_id="watcher", biome="cavern",
                       target_count=5, seed=42)
    pool.ensure_population(center=(0.0, 0.0))
    # Variants should differ across agents (not all identical)
    hue_shifts = [a.hue_shift for a in pool.agents]
    assert len(set(hue_shifts)) > 1, "variants should vary"
