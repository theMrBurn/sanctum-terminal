"""
core/systems/campaign_engine.py

CampaignEngine -- the Wildermyth conductor.

Reads design key + session state → generates scenario chains.
Metroid rule: first encounter is always solvable (matches your top verbs).
Wildermyth rule: quests auto-resolve if player doesn't engage manually.
Elden Ring rule: the world doesn't explain. It presents.
No Man's Sky rule: every session is procedurally unique from seed.

Usage:
    campaign = CampaignEngine(pipeline, scenario_engine)
    quests = campaign.generate_session()       # on session start
    campaign.auto_resolve(quest_id)            # Wildermyth auto-play
    report = campaign.session_report()         # on session end
"""

from __future__ import annotations

import random
from typing import List


# -- Quest templates -----------------------------------------------------------
# Each archetype has scenario templates weighted by relevance.
# verb + tags are selected to match the player's resonance bias.

_ARCHETYPE_TEMPLATES = {
    "survival": [
        {"type": "fetch",  "objective": "Find materials before the cold sets in.",
         "verb": "TOOLS", "tags": ["crafting_time", "endure_count"]},
        {"type": "defend", "objective": "Something is draining heat from this area.",
         "verb": "DEFEND", "tags": ["endure_count", "combat_time"]},
        {"type": "fetch",  "objective": "There is clean water nearby. Retrieve it.",
         "verb": "MOVE",  "tags": ["exploration_time", "food_prepared"]},
    ],
    "mystic": [
        {"type": "hunt",   "objective": "Something pulses beneath the surface. Follow it.",
         "verb": "OBSERVE", "tags": ["observation_time", "objects_inspected"]},
        {"type": "fetch",  "objective": "The wayfinder remembers a path. Trace it.",
         "verb": "THINK",  "tags": ["exploration_time", "precision_score"]},
        {"type": "key",    "objective": "Two halves of the same sign. Bring them together.",
         "verb": "CRAFT",  "tags": ["precision_score", "unknown_combinations"]},
    ],
    "garden": [
        {"type": "fetch",  "objective": "Seeds from the old growth. Gather what you can.",
         "verb": "OBSERVE", "tags": ["observation_time", "crafting_time"]},
        {"type": "defend", "objective": "Frost is coming. Protect what you planted.",
         "verb": "DEFEND", "tags": ["endure_count", "crafting_time"]},
        {"type": "trade",  "objective": "Someone has what you need. You have what they need.",
         "verb": "THINK",  "tags": ["negotiate_count", "food_prepared"]},
    ],
    "souls": [
        {"type": "hunt",   "objective": "It knows you are here. Approach carefully.",
         "verb": "ACT",   "tags": ["combat_time", "precision_score"]},
        {"type": "defend", "objective": "The entropy spike won't stop. Endure it.",
         "verb": "DEFEND", "tags": ["overwhelm_count", "endure_count"]},
        {"type": "escort", "objective": "Keep the light alive through the passage.",
         "verb": "MOVE",  "tags": ["exploration_time", "endure_count"]},
    ],
    "learning": [
        {"type": "key",    "objective": "The sequence matters. Not the speed.",
         "verb": "THINK",  "tags": ["precision_score", "puzzle_attempts"]},
        {"type": "fetch",  "objective": "Observe the pattern. Retrieve what matches.",
         "verb": "OBSERVE", "tags": ["observation_time", "precision_score"]},
        {"type": "switch", "objective": "Three inputs. One output. Find the combination.",
         "verb": "CRAFT",  "tags": ["unknown_combinations", "precision_score"]},
    ],
}

# Pressure curve → quest count
_PRESSURE_QUEST_COUNT = {
    "gentle":   (2, 3),
    "steady":   (3, 4),
    "adaptive": (3, 5),
    "spike":    (4, 6),
}


class CampaignEngine:
    """
    Procedural quest conductor.

    Reads the design key every session and generates scenario chains
    that feel narrative but are seed-driven.

    Parameters
    ----------
    pipeline        : AvatarPipeline instance
    scenario_engine : ScenarioEngine instance
    """

    def __init__(self, pipeline, scenario_engine):
        self._pipeline = pipeline
        self._se       = scenario_engine
        self._session_quests = []
        self._completed = []

    def generate_session(self) -> List[dict]:
        """
        Generate quests for this session based on design key.

        Metroid rule: first quest always matches player's dominant verb.
        Wildermyth rule: quests have auto-resolve option.
        Returns list of quest dicts with scenario_ids.
        """
        key = self._pipeline.design_key()
        rng = random.Random(hash(str(key["archetype_weights"])))

        # Determine quest count from pressure curve
        count_range = _PRESSURE_QUEST_COUNT.get(key["pressure_curve"], (3, 4))
        count = rng.randint(*count_range)

        # Weight archetype selection by design key
        archetypes = list(key["archetype_weights"].keys())
        weights = [key["archetype_weights"][a] for a in archetypes]

        quests = []
        for i in range(count):
            # Select archetype (weighted random)
            arch = rng.choices(archetypes, weights=weights, k=1)[0]
            templates = _ARCHETYPE_TEMPLATES.get(arch, _ARCHETYPE_TEMPLATES["survival"])
            template = rng.choice(templates)

            # Metroid rule: first quest uses player's dominant verb
            if i == 0:
                top_verbs = sorted(
                    key["verb_emphasis"],
                    key=key["verb_emphasis"].get,
                    reverse=True
                )
                # Find a template that matches dominant verb
                dominant = top_verbs[0]
                matching = [t for t in templates if t["verb"] == dominant]
                if matching:
                    template = matching[0]

            # Blend resonance bias into tags
            quest_tags = list(template.get("tags", []))
            for bias_tag in key.get("resonance_bias", [])[:2]:
                if bias_tag not in quest_tags:
                    quest_tags.append(bias_tag)

            # Create scenario
            params = {
                "target_id": f"quest_{arch}_{i}",
                "objective": template["objective"],
            }
            sid = self._se.create(
                scenario_type=template["type"],
                params=params,
            )

            quest = {
                "scenario_id": sid,
                "type":        template["type"],
                "objective":   template["objective"],
                "verb":        template["verb"],
                "tags":        quest_tags,
                "archetype":   arch,
                "auto_resolve": True,
            }
            quests.append(quest)

        # Activate first quest (Metroid: immediately actionable)
        if quests:
            self._se.activate(quests[0]["scenario_id"])

        self._session_quests = quests
        return quests

    def auto_resolve(self, scenario_id: str) -> dict:
        """
        Wildermyth auto-resolve: complete a quest without manual play.
        Stages XP (reduced vs manual), completes scenario, returns report.
        """
        quest = next(
            (q for q in self._session_quests if q["scenario_id"] == scenario_id),
            None,
        )
        if not quest:
            return {"state": "not_found"}

        # Auto-resolve stages less XP than manual (0.3x vs 1.0x)
        tags = quest.get("tags", [])
        if tags:
            entity = {"id": quest["scenario_id"], "tags": tags, "type": "quest"}
            self._pipeline.encounter.begin(entity)
            verb = quest.get("verb", self._pipeline.encounter.dominant_verb())
            self._pipeline.encounter.choose(verb)
            result = self._pipeline.encounter.resolve()
            # Reduce auto-resolved XP
            if result["xp_staged"] > 0:
                reduction = result["xp_staged"] * 0.7
                self._pipeline.encounter.staged_xp -= reduction

        # Complete the scenario
        self._se.complete(scenario_id)
        self._completed.append(scenario_id)

        # Activate next quest in chain
        for i, q in enumerate(self._session_quests):
            if q["scenario_id"] == scenario_id and i + 1 < len(self._session_quests):
                next_q = self._session_quests[i + 1]
                self._se.activate(next_q["scenario_id"])
                break

        return {
            "state": "COMPLETE",
            "quest": quest,
            "auto": True,
        }

    def session_report(self) -> dict:
        """End-of-session summary."""
        return {
            "quests_generated": len(self._session_quests),
            "quests_completed": len(self._completed),
            "quests": [
                {
                    "id":        q["scenario_id"],
                    "type":      q["type"],
                    "objective": q["objective"],
                    "archetype": q["archetype"],
                    "completed": q["scenario_id"] in self._completed,
                }
                for q in self._session_quests
            ],
            "design_key": self._pipeline.design_key(),
        }
