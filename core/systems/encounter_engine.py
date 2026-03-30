"""
core/systems/encounter_engine.py

EncounterEngine -- resonance-gated encounter resolution.
Dragon Quest style. No battle screen. Avatar acts from discipline.

Only resonant encounters teach. Silence is load-bearing.
Level = age (declared, immutable). Depth = what that level means.
Two level-45 Monks with different fingerprints are different people.

Verbs: THINK / ACT / MOVE / DEFEND / TOOLS
Manual resolution is default -- player chooses, engine executes.
Headless/auto mode uses dominant_verb() for ScenarioRunner.

XP stages at resolution. Consolidates at rest / name day / milestone.
3 abilities max: CORE + EQUIPPED + FLOW (Frieren model).
"""

from __future__ import annotations

from typing import Optional


# -- Constants -----------------------------------------------------------------

VERBS = {"THINK", "ACT", "MOVE", "DEFEND", "TOOLS", "CRAFT", "OBSERVE"}

# Resonance threshold -- below this, encounter leaves no trace
# 0.45 = ~25% pass rate. Less frequent, more meaningful. Frieren model.
RESONANCE_THRESHOLD = 0.45

# Minimum seconds between encounters -- prevents clustering
ENCOUNTER_COOLDOWN = 60.0

# XP per resonant encounter, scaled by resonance score
XP_BASE = 1.0

# Depth shift per XP unit on consolidation
DEPTH_PER_XP = 0.01

# Ghost profile -> verb affinity mapping
# All 10 profiles from ghost_profiles.json mapped to encounter verbs.
# Each row sums to 1.0. Dominant verbs reflect the profile's nature.
_PROFILE_VERB_AFFINITY = {
    "PRECISION_HAND":   {"THINK": 0.30, "ACT":   0.30, "CRAFT": 0.15, "OBSERVE": 0.10, "MOVE":  0.05, "DEFEND": 0.05, "TOOLS": 0.05},
    "SEEKER":           {"THINK": 0.30, "OBSERVE":0.25, "MOVE":  0.20, "ACT":    0.10, "CRAFT": 0.05, "DEFEND": 0.05, "TOOLS": 0.05},
    "RHYTHM_KEEPER":    {"ACT":   0.30, "CRAFT": 0.20, "THINK": 0.20, "MOVE":   0.10, "OBSERVE":0.10, "DEFEND": 0.05, "TOOLS": 0.05},
    "MAKER":            {"CRAFT": 0.35, "TOOLS": 0.25, "ACT":   0.15, "THINK":  0.10, "OBSERVE":0.05, "DEFEND": 0.05, "MOVE":  0.05},
    "ENDURANCE_BODY":   {"DEFEND":0.40, "THINK": 0.15, "MOVE":  0.15, "ACT":    0.10, "OBSERVE":0.10, "CRAFT": 0.05, "TOOLS": 0.05},
    "GUARDIAN":         {"DEFEND":0.35, "OBSERVE":0.20, "THINK": 0.15, "ACT":    0.15, "MOVE":  0.05, "CRAFT": 0.05, "TOOLS": 0.05},
    "SYSTEMS_THINKER":  {"THINK": 0.30, "OBSERVE":0.25, "TOOLS": 0.15, "CRAFT":  0.15, "ACT":   0.10, "MOVE":  0.03, "DEFEND":0.02},
    "NATURALIST":       {"OBSERVE":0.30,"THINK": 0.20, "MOVE":  0.20, "CRAFT":  0.15, "ACT":   0.05, "TOOLS": 0.05, "DEFEND":0.05},
    "PERFORMER":        {"ACT":   0.35, "MOVE":  0.20, "THINK": 0.15, "CRAFT":  0.10, "OBSERVE":0.10, "DEFEND": 0.05, "TOOLS": 0.05},
    "FORCE_MULTIPLIER": {"ACT":   0.35, "DEFEND":0.20, "THINK": 0.15, "MOVE":   0.10, "CRAFT": 0.05, "OBSERVE":0.05, "TOOLS": 0.10},
}

_DEFAULT_VERB_WEIGHTS = {
    "THINK": 0.3, "ACT": 0.3, "MOVE": 0.15, "DEFEND": 0.15, "TOOLS": 0.1
}


class EncounterEngine:
    """
    Manages encounter lifecycle for the Sanctum avatar.

    Parameters
    ----------
    fingerprint  : FingerprintEngine instance
    ghost_blend  : dict of {profile_name: weight} from GhostProfileEngine
    age          : int -- declared in interview, immutable, base level
    """

    def __init__(self, fingerprint, ghost_blend: dict, age: int = 0):
        self.fingerprint       = fingerprint
        self.ghost_blend       = ghost_blend
        self.age               = age

        self.staged_xp         = 0.0
        self.depth             = 0.0          # shifts on consolidation
        self.abilities         = []           # max 3: CORE + EQUIPPED + FLOW
        self.active_encounter  = None
        self._chosen_verb      = None
        self._consolidation_count = 0
        self._cooldown_remaining = 0.0        # seconds until next encounter allowed

    # -- Resonance -------------------------------------------------------------

    def resonance(self, tags: list) -> float:
        """
        Pure function. No side effects.
        Returns 0.0-1.0 overlap between encounter tags and fingerprint.
        High resonance = this encounter speaks to who the Monk already is.
        """
        if not tags:
            return 0.0
        total = sum(
            self.fingerprint.state.get(tag, 0.0)
            for tag in tags
            if tag in self.fingerprint.state
        )
        return total / len(tags)

    # -- Encounter lifecycle ---------------------------------------------------

    def tick_cooldown(self, dt: float) -> None:
        """Advance cooldown timer. Call every frame."""
        if self._cooldown_remaining > 0:
            self._cooldown_remaining = max(0.0, self._cooldown_remaining - dt)

    @property
    def on_cooldown(self) -> bool:
        """True if the engine is in post-encounter cooldown."""
        return self._cooldown_remaining > 0

    def begin(self, entity: dict) -> bool:
        """
        Begin an encounter with an entity.
        entity: {"id": str, "tags": list, "type": str}

        Returns True if WORTH_KNOWING (resonance > threshold AND not on cooldown).
        Cooldown prevents encounter clustering -- the world digests before speaking again.
        Sets active_encounter regardless (for tracking), but worth_knowing is False on cooldown.
        """
        tags         = entity.get("tags", [])
        r            = self.resonance(tags)
        worth        = r > RESONANCE_THRESHOLD and not self.on_cooldown

        self.active_encounter = {
            "entity":       entity,
            "resonance":    r,
            "worth_knowing": worth,
            "verb_used":    None,
        }
        self._chosen_verb = None
        return worth

    def available_verbs(self) -> list:
        """
        All verbs available in current encounter.
        THINK always available. Others depend on encounter type.
        Future: TOOLS only if inventory has relevant item.
        """
        if self.active_encounter is None:
            return []
        return list(VERBS)

    def dominant_verb(self) -> str:
        """
        Verb most aligned with ghost profile.
        Used by ScenarioRunner headless auto-play.
        Manual mode: player chooses, this is the suggestion.
        """
        weights = dict(_DEFAULT_VERB_WEIGHTS)

        for profile, profile_weight in self.ghost_blend.items():
            affinity = _PROFILE_VERB_AFFINITY.get(profile, {})
            for verb, verb_weight in affinity.items():
                weights[verb] = weights.get(verb, 0.0) + verb_weight * profile_weight

        return max(weights, key=weights.get)

    def choose(self, verb: str) -> dict:
        """
        Manual verb selection.
        Raises ValueError for unknown verbs.
        Returns choice confirmation dict.
        """
        if verb not in VERBS:
            raise ValueError(
                f"Unknown verb: {verb!r}. Valid: {sorted(VERBS)}"
            )
        self._chosen_verb = verb
        if self.active_encounter:
            self.active_encounter["verb_used"] = verb
        return {"verb": verb, "accepted": True}

    def resolve(self) -> dict:
        """
        Resolve the active encounter.
        If WORTH_KNOWING: record to fingerprint, stage XP.
        If not: world moves on, nothing added. Silence.
        Clears active_encounter.
        """
        if self.active_encounter is None:
            return {
                "outcome":      "no_encounter",
                "xp_staged":    0.0,
                "worth_knowing": False,
                "verb_used":    None,
            }

        enc          = self.active_encounter
        worth        = enc["worth_knowing"]
        r            = enc["resonance"]
        verb         = enc.get("verb_used") or self._chosen_verb or self.dominant_verb()
        xp_staged    = 0.0

        if worth:
            # Record resonant dimensions to fingerprint
            for tag in enc["entity"].get("tags", []):
                if tag in self.fingerprint.state:
                    self.fingerprint.record(tag, r)

            # Stage XP scaled by resonance
            xp_staged = XP_BASE * r
            self.stage_xp(xp_staged)

        self.active_encounter = None
        self._chosen_verb     = None

        # Start cooldown after a resonant encounter
        if worth:
            self._cooldown_remaining = ENCOUNTER_COOLDOWN

        return {
            "outcome":       "resolved",
            "xp_staged":     xp_staged,
            "worth_knowing": worth,
            "verb_used":     verb,
            "resonance":     r,
        }

    # -- XP + consolidation ----------------------------------------------------

    def stage_xp(self, amount: float) -> None:
        """Accumulate XP for next consolidation."""
        self.staged_xp += amount

    def consolidate(self, reason: str = "rest") -> dict:
        """
        Convert staged XP to permanent depth shift.
        Called at: rest / name day / world_age milestone.

        reason: "rest" | "name_day" | "milestone"

        Depth increases. Level (age) never changes.
        Ability slots checked -- max 3 (Frieren model).
        """
        xp      = self.staged_xp
        shift   = xp * DEPTH_PER_XP
        checked = []

        if xp > 0:
            self.depth      += shift
            self.staged_xp   = 0.0
            self._consolidation_count += 1

            # Apply fingerprint decay -- surface behavior fades, core persists
            self.fingerprint.apply_decay(self._consolidation_count * 86400)

            # Ability unlock check (Frieren model: depth unlocks, not grinding)
            checked = self._check_ability_unlocks()

        return {
            "reason":           reason,
            "xp_consumed":      xp,
            "depth_shift":      shift,
            "depth_total":      self.depth,
            "abilities_checked": checked,
            "ability_count":    len(self.abilities),
        }

    def _check_ability_unlocks(self) -> list:
        """
        Check if depth threshold unlocks a new ability slot.
        Max 3: CORE (always) + EQUIPPED + FLOW.
        New abilities derived from dominant fingerprint dimensions.
        """
        checked = []

        # CORE -- unlocked at depth 0.1 (first meaningful consolidation)
        if self.depth >= 0.1 and "CORE" not in [a["slot"] for a in self.abilities]:
            ability = self._derive_ability("CORE")
            self.abilities.append(ability)
            checked.append(ability)

        # EQUIPPED -- unlocked at depth 0.5
        if self.depth >= 0.5 and "EQUIPPED" not in [a["slot"] for a in self.abilities]:
            ability = self._derive_ability("EQUIPPED")
            self.abilities.append(ability)
            checked.append(ability)

        # FLOW -- unlocked at depth 1.0
        if self.depth >= 1.0 and "FLOW" not in [a["slot"] for a in self.abilities]:
            ability = self._derive_ability("FLOW")
            self.abilities.append(ability)
            checked.append(ability)

        # Hard cap -- 3 max
        self.abilities = self.abilities[:3]
        return checked

    def _derive_ability(self, slot: str) -> dict:
        """
        Derive ability from dominant fingerprint dimension.
        The Monk's practice becomes his power.
        """
        dominant_dim = max(
            self.fingerprint.state,
            key=lambda k: self.fingerprint.state[k]
        )
        return {
            "slot":      slot,
            "source":    dominant_dim,
            "depth":     round(self.depth, 3),
        }
