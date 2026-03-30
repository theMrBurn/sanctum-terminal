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

from core.systems.fingerprint_engine import FingerprintEngine, DIMENSIONS
from core.systems.ghost_profile_engine import GhostProfileEngine
from core.systems.encounter_engine import EncounterEngine, _PROFILE_VERB_AFFINITY


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

    def design_key(self) -> dict:
        """
        Compute the design key -- a projection of ghost blend + fingerprint
        into procedural generator space.

        Not configured. Derived from play. The engine watches and projects.

        Returns dict with:
            archetype_weights: {survival, mystic, garden, souls, learning} → 0-1
            verb_emphasis: {THINK, ACT, MOVE, DEFEND, TOOLS} → 0-1
            resonance_bias: top 5 fingerprint dimensions by value
            pressure_curve: "gentle" | "steady" | "adaptive" | "spike"
        """
        fp = self.fingerprint.export()

        # -- Archetype weights from fingerprint dimensions ---
        archetypes = {
            "survival": (
                fp.get("endure_count", 0) +
                fp.get("food_prepared", 0) +
                fp.get("crafting_time", 0)
            ) / 3.0,
            "mystic": (
                fp.get("exploration_time", 0) +
                fp.get("objects_inspected", 0) +
                fp.get("observation_time", 0)
            ) / 3.0,
            "garden": (
                fp.get("crafting_time", 0) +
                fp.get("observation_time", 0) +
                fp.get("food_prepared", 0)
            ) / 3.0,
            "souls": (
                fp.get("combat_time", 0) +
                fp.get("overwhelm_count", 0) +
                fp.get("endure_count", 0)
            ) / 3.0,
            "learning": (
                fp.get("precision_score", 0) +
                fp.get("puzzle_attempts", 0) +
                fp.get("unknown_combinations", 0)
            ) / 3.0,
        }
        # Ensure minimum presence + normalize
        for k in archetypes:
            archetypes[k] = max(0.05, archetypes[k])
        arch_total = sum(archetypes.values())
        archetypes = {k: v / arch_total for k, v in archetypes.items()}

        # -- Verb emphasis from ghost blend ---
        verbs = {"THINK": 0.0, "ACT": 0.0, "MOVE": 0.0, "DEFEND": 0.0, "TOOLS": 0.0}
        for profile, weight in self.ghost_blend.items():
            affinity = _PROFILE_VERB_AFFINITY.get(profile, {})
            for verb, vw in affinity.items():
                if verb in verbs:
                    verbs[verb] += vw * weight
        verb_total = sum(verbs.values()) or 1.0
        verbs = {k: v / verb_total for k, v in verbs.items()}

        # -- Resonance bias: top 5 fingerprint dimensions ---
        sorted_dims = sorted(
            [(k, v) for k, v in fp.items() if v > 0],
            key=lambda x: x[1], reverse=True
        )
        resonance_bias = [k for k, v in sorted_dims[:5]]

        # -- Pressure curve from combat/overwhelm ratio ---
        combat = fp.get("combat_time", 0)
        overwhelm = fp.get("overwhelm_count", 0)
        endure = fp.get("endure_count", 0)
        if combat < 0.1 and overwhelm < 0.1:
            pressure = "gentle"
        elif overwhelm > endure and overwhelm > 0.3:
            pressure = "spike"
        elif combat > 0.3:
            pressure = "adaptive"
        else:
            pressure = "steady"

        return {
            "archetype_weights": archetypes,
            "verb_emphasis": verbs,
            "resonance_bias": resonance_bias,
            "pressure_curve": pressure,
        }
