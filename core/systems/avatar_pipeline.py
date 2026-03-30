"""
core/systems/avatar_pipeline.py

AvatarPipeline -- wires Interview → GhostProfile → Fingerprint → EncounterEngine.

Single construction point for a Monk's encounter identity.
Interview answers seed the initial ghost blend.
Fingerprint updates it over time (behavioral > declared).
EncounterEngine consumes the blend for verb selection and resonance gating.

Usage:
    pipeline = AvatarPipeline(answers=interview.answers, age=45)
    pipeline.encounter.begin(entity)
    pipeline.encounter.choose("THINK")
    result = pipeline.encounter.resolve()

    # After gameplay, refresh blend from fingerprint
    pipeline.refresh_blend()
"""

from __future__ import annotations

from core.systems.fingerprint_engine import FingerprintEngine
from core.systems.ghost_profile_engine import GhostProfileEngine
from core.systems.encounter_engine import EncounterEngine


class AvatarPipeline:
    """
    Wires the full avatar identity stack.

    Parameters
    ----------
    answers     : dict -- interview answers (q1, q5, q6, q8, etc.)
    age         : int  -- declared age, immutable, becomes encounter level
    seed        : str  -- world seed (default "BURN")
    fingerprint : FingerprintEngine -- optional, created if not provided
    """

    def __init__(
        self,
        answers: dict,
        age: int = 0,
        seed: str = "BURN",
        fingerprint: FingerprintEngine | None = None,
    ):
        self.seed        = seed
        self.fingerprint = fingerprint or FingerprintEngine()
        self.ghost       = GhostProfileEngine()

        # Initial blend from interview answers
        self._interview_blend = self.ghost.map_interview(answers)
        self.ghost_blend      = dict(self._interview_blend)

        # Wire encounter engine
        self.encounter = EncounterEngine(
            fingerprint = self.fingerprint,
            ghost_blend = self.ghost_blend,
            age         = age,
        )

    def refresh_blend(self) -> dict:
        """
        Re-blend ghost profile from interview + fingerprint.
        Fingerprint weight (0.6) dominates interview (0.4) over time.
        Updates encounter engine's blend in place.
        """
        fp_blend = self.ghost.update_from_fingerprint(self.fingerprint.export())
        merged   = self.ghost.merge_blends(
            self._interview_blend, fp_blend,
            weight_a=0.4, weight_b=0.6,
        )
        self.ghost_blend.clear()
        self.ghost_blend.update(merged)
        return self.ghost_blend
