"""RoamingPool — visible encounter agents that wander the world.

Persona-3 / Tartarus model: a small pool of roaming orbs drifts around
the player. On camera contact, the brain begins an EncounterSession with
the agent's actor_id. Consumed agents are removed; the pool re-populates
after a cooldown so the cavern never empties.

This module is independent of the stamp density table — stamps place
static terrain, this module spawns ambient agents. Brain_server constructs
one pool per Godot connection (paired with the EncounterSession) and calls
tick() + detect_contact() each frame.

All state is brain-authoritative. The snapshot() method returns a list of
entity dicts ready to concatenate into manifest['entities'].
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# Tuning knobs
CONTACT_RADIUS: float = 1.8           # meters — camera-to-orb trigger distance
SPAWN_RADIUS: float = 24.0            # meters — orbs spawn within this of center
PATROL_RADIUS: float = 10.0           # meters — each orb wanders this far from home
WANDER_SPEED: float = 0.9             # m/s
WANDER_TURN_HZ: float = 0.4           # rate of heading changes
RESPAWN_COOLDOWN: float = 60.0        # seconds between consume and new spawn


@dataclass
class RoamingAgent:
    id:        str
    actor_id:  str
    x:         float
    y:         float
    home_x:    float
    home_y:    float
    heading:   float = 0.0            # radians, facing direction
    # Procedural variant — cheap color + HP shift from a single base actor.
    # Old-dev trick: one sprite, infinite "species" via palette + stat offsets.
    hue_shift: float = 0.0            # 0..1, hue rotation applied in Godot
    hp_bonus:  int = 0                # added to base HP at encounter start
    _turn_t:   float = 0.0
    _target_heading: float = 0.0


class RoamingPool:
    """Manages a population of roaming agents for one encounter kind.

    Future: could be extended to a MultiPool that holds several RoamingPool
    instances, each with its own actor_id, and picks per-biome which to
    activate. For now one pool = one actor id (Watcher).
    """

    def __init__(self, actor_id: str, biome: str,
                 target_count: int = 3,
                 seed: int = 0,
                 spawn_radius: float = SPAWN_RADIUS,
                 patrol_radius: float = PATROL_RADIUS,
                 respawn_cooldown: float = RESPAWN_COOLDOWN):
        self.actor_id = actor_id
        self.biome = biome
        self.target_count = target_count
        self.spawn_radius = spawn_radius
        self.patrol_radius = patrol_radius
        self.respawn_cooldown = respawn_cooldown

        self._rng = random.Random(seed)
        self._next_id = 0
        self._respawn_timer: float = 0.0

        self.agents: List[RoamingAgent] = []

    # -- Spawn ---------------------------------------------------------------

    def ensure_population(self, center: Tuple[float, float]) -> None:
        """Fill the pool to target_count. Called once at startup and when
        respawn cooldown elapses after a consumption."""
        while len(self.agents) < self.target_count:
            self.agents.append(self._spawn_one(center))

    def _spawn_one(self, center: Tuple[float, float]) -> RoamingAgent:
        # Random point in a disc of spawn_radius centered on the player.
        r = math.sqrt(self._rng.random()) * self.spawn_radius
        theta = self._rng.random() * math.tau
        x = center[0] + r * math.cos(theta)
        y = center[1] + r * math.sin(theta)
        agent_id = f"orb#{self._next_id}"
        self._next_id += 1
        # Variant dice — small hue rotation and +/- 1 HP. Keeps the Watcher
        # lineage readable while no two feel identical.
        hue_shift = self._rng.random()                    # 0..1 full hue space
        hp_bonus = self._rng.randint(-1, 2)               # -1, 0, 1, or 2
        return RoamingAgent(
            id=agent_id,
            actor_id=self.actor_id,
            x=x, y=y, home_x=x, home_y=y,
            heading=self._rng.random() * math.tau,
            hue_shift=hue_shift,
            hp_bonus=hp_bonus,
            _target_heading=self._rng.random() * math.tau,
        )

    # -- Tick ----------------------------------------------------------------

    def tick(self, dt: float,
             player_pos: Optional[Tuple[float, float]] = None) -> None:
        """Advance wander + respawn timer.

        If player_pos is given, respawn recenters on it (so new orbs fade
        in near the current location, not the stale startup center)."""
        for a in self.agents:
            self._wander(a, dt)

        if len(self.agents) < self.target_count:
            self._respawn_timer += dt
            if self._respawn_timer >= self.respawn_cooldown:
                self._respawn_timer = 0.0
                center = player_pos if player_pos is not None else (0.0, 0.0)
                self.agents.append(self._spawn_one(center))
        else:
            self._respawn_timer = 0.0

    def _wander(self, a: RoamingAgent, dt: float) -> None:
        # Every so often, pick a new target heading. Between picks, drift
        # heading toward target to make motion curvy rather than jittery.
        a._turn_t += dt
        if a._turn_t >= 1.0 / WANDER_TURN_HZ:
            a._turn_t = 0.0
            a._target_heading = self._rng.random() * math.tau

        # Smooth heading toward target
        d = _shortest_angle(a._target_heading - a.heading)
        a.heading += d * min(1.0, dt * 3.0)

        # Move forward
        a.x += math.cos(a.heading) * WANDER_SPEED * dt
        a.y += math.sin(a.heading) * WANDER_SPEED * dt

        # Clamp to patrol radius
        dx = a.x - a.home_x
        dy = a.y - a.home_y
        d2 = dx * dx + dy * dy
        if d2 > self.patrol_radius * self.patrol_radius:
            # Snap to patrol boundary + turn back home
            scale = self.patrol_radius / math.sqrt(d2)
            a.x = a.home_x + dx * scale
            a.y = a.home_y + dy * scale
            # Flip heading toward home
            a._target_heading = math.atan2(-dy, -dx)

    # -- Contact detection ---------------------------------------------------

    def detect_contact(self, cam_x: float, cam_y: float
                       ) -> Optional[RoamingAgent]:
        """Return the nearest agent within CONTACT_RADIUS, else None."""
        best = None
        best_d2 = CONTACT_RADIUS * CONTACT_RADIUS
        for a in self.agents:
            dx = a.x - cam_x
            dy = a.y - cam_y
            d2 = dx * dx + dy * dy
            if d2 <= best_d2:
                best_d2 = d2
                best = a
        return best

    # -- Consumption ---------------------------------------------------------

    def consume(self, agent_id: str) -> None:
        """Remove an agent from the pool. Starts respawn cooldown."""
        self.agents = [a for a in self.agents if a.id != agent_id]
        self._respawn_timer = 0.0

    # -- Snapshot (for manifest) --------------------------------------------

    def snapshot(self) -> List[dict]:
        """Return entity-dict list for manifest['entities'] concatenation.
        Each orb renders with kind='orb' — see kind_config.json for visual."""
        out = []
        for a in self.agents:
            out.append({
                "id":        a.id,
                "kind":      "orb",
                "actor_id":  a.actor_id,
                "x":         a.x,
                "y":         a.y,
                "z":         0.8,
                "sx":        1.0,
                "sy":        1.0,
                "sz":        1.0,
                "heading":   math.degrees(a.heading),
                "hue_shift": a.hue_shift,
                "hp_bonus":  a.hp_bonus,
            })
        return out


def _shortest_angle(diff: float) -> float:
    """Wrap an angle difference into [-pi, pi]."""
    while diff > math.pi:
        diff -= math.tau
    while diff < -math.pi:
        diff += math.tau
    return diff
