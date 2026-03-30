"""
core/systems/dungeon_campaign.py

DungeonCampaign -- tracks progression through the 7-Door Dungeon.

8 doors, 7 attempts per corridor. Find the minute detail.
Every 7 corridors, tier advances (detail type escalates).
Failure resets corridor with new detail. Depth is preserved.
The garden doesn't have dead ends. It has detours.
"""

from __future__ import annotations

from core.systems.corridor_scene import CorridorScene


class DungeonCampaign:
    """
    Manages dungeon progression state.

    Parameters
    ----------
    seed : str -- provenance seed for deterministic generation
    """

    def __init__(self, seed: str = "DUNGEON"):
        self.seed        = seed
        self.corridor    = 0
        self.tier        = 1
        self.attempts    = 7
        self.deepest     = 0      # furthest corridor reached
        self._resets     = 0      # times current corridor was reset
        self._total_tries = 0

        # Generate first corridor
        self.scene = self._make_scene()

    def _make_scene(self) -> CorridorScene:
        """Generate corridor scene from current state."""
        # Include resets in seed so detail changes on retry
        combined_seed = hash(f"{self.seed}_{self.corridor}_{self._resets}")
        return CorridorScene(
            seed=combined_seed,
            corridor_num=self.corridor,
            tier=self.tier,
        )

    def try_door(self, door_index: int) -> dict:
        """
        Attempt a door. Returns result with advancement info.
        """
        self._total_tries += 1
        result = self.scene.try_door(door_index)

        if result["success"]:
            # Advance to next corridor
            self.corridor += 1
            self.deepest = max(self.deepest, self.corridor)
            self.attempts = 7
            self._resets = 0

            # Tier advances every 7 corridors
            self.tier = (self.corridor // 7) + 1

            # Generate new corridor
            self.scene = self._make_scene()

            return {
                "advanced": True,
                "corridor": self.corridor,
                "tier": self.tier,
                "attempts_remaining": self.attempts,
                "detail_type": result.get("detail_type"),
            }
        else:
            # Wrong door -- decrement attempts
            self.attempts -= 1

            if self.attempts <= 0:
                # Reset corridor with new detail (consequence, not death)
                self._resets += 1
                self.attempts = 7
                self.scene = self._make_scene()

                return {
                    "advanced": False,
                    "reset": True,
                    "corridor": self.corridor,
                    "tier": self.tier,
                    "attempts_remaining": self.attempts,
                    "message": "The corridor shifts. The details change. Try again.",
                }
            else:
                return {
                    "advanced": False,
                    "reset": False,
                    "corridor": self.corridor,
                    "tier": self.tier,
                    "attempts_remaining": self.attempts,
                    "message": f"{self.attempts} attempts remain.",
                }

    def examine_door(self, door_index: int) -> dict:
        """Examine a door. Free action, doesn't cost an attempt."""
        return self.scene.examine(door_index)

    def report(self) -> dict:
        """Full dungeon state."""
        return {
            "corridor": self.corridor,
            "tier": self.tier,
            "attempts": self.attempts,
            "deepest": self.deepest,
            "resets": self._resets,
            "total_tries": self._total_tries,
            "detail_type": _TIER_NAMES.get(self.tier, "unknown"),
        }


_TIER_NAMES = {
    1: "visual",
    2: "spatial",
    3: "temporal",
    4: "behavioral",
}
