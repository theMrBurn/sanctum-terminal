"""
core/systems/encounter_generator.py

Bridge 1: EncounterGenerator -- proximity triggers encounters automatically.

Connects InteractionEngine (REACHABLE state) to EncounterEngine (begin/resolve).
Objects with tags generate encounters when the player is near.
Respects cooldown. No duplicate encounters on the same object.
"""

from __future__ import annotations


class EncounterGenerator:
    """
    Generates encounters from world objects based on proximity.

    Parameters
    ----------
    encounter_engine : EncounterEngine instance
    """

    def __init__(self, encounter_engine):
        self._encounter = encounter_engine
        self._encountered_ids = set()  # objects already encountered this cycle

    def try_encounter(self, obj: dict) -> dict | None:
        """
        Attempt to begin an encounter with an object.
        Returns the active_encounter dict if started, None if skipped.

        Skips if:
        - obj has no tags
        - encounter engine is on cooldown
        - encounter already active
        - this object was already encountered this cycle
        """
        tags = obj.get("tags", [])
        if not tags:
            return None

        if self._encounter.on_cooldown:
            return None

        if self._encounter.active_encounter is not None:
            return None

        obj_id = obj.get("id", "")
        if obj_id in self._encountered_ids:
            return None

        entity = {"id": obj_id, "tags": tags, "type": obj.get("type", "object")}
        worth = self._encounter.begin(entity)

        if worth:
            self._encountered_ids.add(obj_id)
            verb = self._encounter.dominant_verb()
            self._encounter.choose(verb)

        return self._encounter.active_encounter

    def clear_cycle(self):
        """Reset encountered IDs. Call on biome change or session boundary."""
        self._encountered_ids.clear()
