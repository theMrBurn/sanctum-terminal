"""
core/systems/encounter_engine.py

EncounterEngine -- resonance-gated encounter resolution.
Dragon Quest style. No battle screen. Avatar acts from discipline.

Only resonant encounters teach. Silence is load-bearing.
Level = age (declared, immutable). Depth = what that level means.
Two level-45 Monks with different fingerprints are different people.

Actions (the 7-branch action tree): THINK / ACT / MOVE / DEFEND / TOOLS / CRAFT / OBSERVE
Manual resolution is default -- player chooses, engine executes.
Headless/auto mode uses dominant_action() for ScenarioRunner.

XP stages at resolution. Consolidates at rest / name day / milestone.
3 abilities max: CORE + EQUIPPED + FLOW (Frieren model).

Naming: "action" is the canonical term for the 7-branch tree. Older
callers still reference "verb"; VERBS / dominant_verb / _PROFILE_VERB_AFFINITY
are kept as aliases for back-compat and will migrate when touched.
"""

from __future__ import annotations

from typing import Optional


# -- Constants -----------------------------------------------------------------

ACTIONS = {"THINK", "ACT", "MOVE", "DEFEND", "TOOLS", "CRAFT", "OBSERVE"}
VERBS = ACTIONS   # alias — legacy callers

# Resonance threshold -- below this, encounter leaves no trace
# 0.45 = ~25% pass rate. Less frequent, more meaningful. Frieren model.
RESONANCE_THRESHOLD = 0.45

# Minimum seconds between encounters -- prevents clustering
ENCOUNTER_COOLDOWN = 60.0

# XP per resonant encounter, scaled by resonance score
XP_BASE = 1.0

# Depth shift per XP unit on consolidation
DEPTH_PER_XP = 0.01

# Ghost profile -> action affinity mapping
# All 10 profiles from ghost_profiles.json mapped to encounter actions.
# Each row sums to 1.0. Dominant actions reflect the profile's nature.
_PROFILE_ACTION_AFFINITY = {
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

_DEFAULT_ACTION_WEIGHTS = {
    "THINK": 0.3, "ACT": 0.3, "MOVE": 0.15, "DEFEND": 0.15, "TOOLS": 0.1
}

# Aliases for legacy callers (campaign_engine, avatar_pipeline, etc.)
_PROFILE_VERB_AFFINITY = _PROFILE_ACTION_AFFINITY
_DEFAULT_VERB_WEIGHTS = _DEFAULT_ACTION_WEIGHTS


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
        self._chosen_action    = None
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
            "action_used":  None,
            "verb_used":    None,        # alias, kept for legacy consumers
            "net_passes":   0,           # resolver-side progress toward threshold
        }
        self._chosen_action = None
        return worth

    def available_actions(self) -> list:
        """
        All actions available in current encounter.
        THINK always available. Others depend on encounter type.
        Future: TOOLS only if inventory has relevant item.
        """
        if self.active_encounter is None:
            return []
        return list(ACTIONS)

    # Legacy alias
    available_verbs = available_actions

    def dominant_action(self) -> str:
        """
        Action most aligned with ghost profile.
        Used by ScenarioRunner headless auto-play.
        Manual mode: player chooses, this is the suggestion.
        """
        weights = dict(_DEFAULT_ACTION_WEIGHTS)

        for profile, profile_weight in self.ghost_blend.items():
            affinity = _PROFILE_ACTION_AFFINITY.get(profile, {})
            for action, action_weight in affinity.items():
                weights[action] = weights.get(action, 0.0) + action_weight * profile_weight

        return max(weights, key=weights.get)

    # Legacy alias
    dominant_verb = dominant_action

    def choose(self, action: str) -> dict:
        """
        Manual action selection.
        Raises ValueError for unknown actions.
        Returns choice confirmation dict.
        """
        if action not in ACTIONS:
            raise ValueError(
                f"Unknown action: {action!r}. Valid: {sorted(ACTIONS)}"
            )
        self._chosen_action = action
        if self.active_encounter:
            self.active_encounter["action_used"] = action
            self.active_encounter["verb_used"] = action   # legacy mirror
        return {"action": action, "verb": action, "accepted": True}

    def resolve(self, outcome: str = "resolved") -> dict:
        """
        Resolve the active encounter.
        If WORTH_KNOWING: record to fingerprint, stage XP.
        If not: world moves on, nothing added. Silence.
        Clears active_encounter.

        outcome: "resolved" | "fled" | "defeated" | "portal_exit"
            Only "resolved" grants full staged XP. "fled" scales XP by 0.25
            (something was learned by walking away). "defeated" and
            "portal_exit" stage no XP — they're scene-ends, not wins.
        """
        if self.active_encounter is None:
            return {
                "outcome":      "no_encounter",
                "xp_staged":    0.0,
                "worth_knowing": False,
                "action_used":  None,
                "verb_used":    None,
            }

        enc          = self.active_encounter
        worth        = enc["worth_knowing"]
        r            = enc["resonance"]
        action       = (enc.get("action_used") or self._chosen_action
                        or self.dominant_action())
        xp_staged    = 0.0

        # XP scaling by outcome tag
        xp_mult = {"resolved": 1.0, "fled": 0.25,
                   "defeated": 0.0, "portal_exit": 0.0}.get(outcome, 1.0)

        if worth and xp_mult > 0:
            # Record resonant dimensions to fingerprint
            for tag in enc["entity"].get("tags", []):
                if tag in self.fingerprint.state:
                    self.fingerprint.record(tag, r)

            xp_staged = XP_BASE * r * xp_mult
            self.stage_xp(xp_staged)

        self.active_encounter = None
        self._chosen_action   = None

        # Cooldown applies only after a meaningful-resolution outcome.
        # Defeat and portal exit don't gate re-engagement — DQ rule:
        # wake at the castle, immediately re-enter the world and fight.
        if worth and outcome in ("resolved", "fled"):
            self._cooldown_remaining = ENCOUNTER_COOLDOWN

        return {
            "outcome":       outcome,
            "xp_staged":     xp_staged,
            "worth_knowing": worth,
            "action_used":   action,
            "verb_used":     action,       # legacy mirror
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
