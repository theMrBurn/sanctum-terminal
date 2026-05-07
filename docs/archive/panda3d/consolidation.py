"""
core/systems/consolidation.py

Bridge 4: ConsolidationTrigger -- rest events fire consolidation.

Staged XP converts to permanent depth at rest, session end, or milestone.
Depth thresholds unlock abilities (CORE at 0.1, EQUIPPED at 0.5, FLOW at 1.0).
"""

from __future__ import annotations


class ConsolidationTrigger:
    """
    Fires encounter consolidation on game events.

    Parameters
    ----------
    encounter_engine : EncounterEngine instance
    """

    def __init__(self, encounter_engine):
        self._encounter = encounter_engine

    def rest(self) -> dict:
        """
        Player rests. Consolidate staged XP.
        Called at shelter, campfire, or session idle timeout.
        """
        return self._encounter.consolidate(reason="rest")

    def session_end(self) -> dict:
        """
        Session ending. Consolidate everything.
        Called by SessionBoundary on exit.
        """
        return self._encounter.consolidate(reason="session_end")

    def milestone(self, milestone_id: str) -> dict:
        """
        Significant event. Consolidate with milestone reason.
        Called on: first craft, scenario chain complete, biome transition, etc.
        """
        return self._encounter.consolidate(reason=milestone_id)

    def name_day(self) -> dict:
        """
        Annual consolidation. One per real year of play.
        Bonus: consolidates all XP with maximum depth multiplier.
        """
        return self._encounter.consolidate(reason="name_day")

    @property
    def staged_xp(self) -> float:
        """Current staged XP waiting for consolidation."""
        return self._encounter.staged_xp

    @property
    def depth(self) -> float:
        """Current permanent depth."""
        return self._encounter.depth

    @property
    def abilities(self) -> list:
        """Current unlocked abilities."""
        return self._encounter.abilities
