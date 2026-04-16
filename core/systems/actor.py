"""Actor base class + Orb concrete — the encounter primitive's behavior layer.

An Actor is any entity that takes turns. Orb is the first concrete subtype;
Creature, Phantom, etc. will follow the same shape. Data for each Actor lives
in config/encounters.json — this module is the runtime carrier.

Design notes:
- Actor owns HP and turn-taking. Nothing else — keeps the base thin.
- Orb owns tags, segments, phase resolution, and intent selection.
- choose_intent() is a pure function (Orb + last-action context + rng → intent).
  Keeping it free of class-methods makes it trivially testable and reusable.
- take_turn() returns an effect payload; the EncounterSession applies it to
  its own state (progress, player HP, disadvantage flags). We don't let the
  Orb reach into the session — clean boundary for procedural composition.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.systems import encounter_config as ec
from core.systems import player_state as ps
from core.systems.player_state import PlayerState


# -- Actor base --------------------------------------------------------------

@dataclass
class Actor:
    name:   str
    hp:     int
    max_hp: int

    def is_defeated(self) -> bool:
        return self.hp <= 0

    def take_damage(self, amount: int) -> None:
        if amount <= 0:
            return
        self.hp = max(0, self.hp - amount)

    def heal(self, amount: int) -> None:
        if amount <= 0:
            return
        self.hp = min(self.max_hp, self.hp + amount)

    # take_turn is abstract — concrete actors override.
    def take_turn(self, player: PlayerState,
                  rng: Callable[[int], int]) -> Tuple[PlayerState, Dict[str, Any]]:
        raise NotImplementedError


# -- Orb concrete ------------------------------------------------------------

@dataclass
class Orb(Actor):
    tags:            List[str]           = field(default_factory=list)
    segments:        Dict[str, Any]      = field(default_factory=dict)
    visual:          Dict[str, Any]      = field(default_factory=dict)
    phase_weights:   Dict[str, Dict[str, float]] = field(default_factory=dict)
    reactive_bumps:  List[Dict[str, Any]] = field(default_factory=list)
    dialog_phase_weights:  Dict[str, Dict[str, float]] = field(default_factory=dict)
    dialog_reactive_bumps: List[Dict[str, Any]] = field(default_factory=list)
    current_intent:  Optional[Tuple[str, Dict[str, Any]]] = None   # (name, spec)

    # -- Factory -------------------------------------------------------------

    @classmethod
    def from_config(cls, actor_id: str) -> "Orb":
        """Build an Orb from config pool. Raises KeyError if unknown."""
        cfg = ec.get_actor(actor_id)
        if cfg.get("type") != "orb":
            raise ValueError(
                f"actor {actor_id!r} is type={cfg.get('type')}, not 'orb'")
        return cls(
            name=cfg.get("display_name", actor_id),
            hp=int(cfg["max_hp"]),
            max_hp=int(cfg["max_hp"]),
            tags=list(cfg.get("tags", [])),
            segments=dict(cfg.get("segments", {})),
            visual=dict(cfg.get("visual", {})),
            phase_weights={k: dict(v) for k, v in cfg["phase_weights"].items()},
            reactive_bumps=[dict(b) for b in cfg.get("reactive_bumps", [])],
            dialog_phase_weights={
                k: dict(v) for k, v in cfg.get("dialog_phase_weights", {}).items()
            },
            dialog_reactive_bumps=[
                dict(b) for b in cfg.get("dialog_reactive_bumps", [])
            ],
        )

    # -- Phase ---------------------------------------------------------------

    def hp_fraction(self) -> float:
        if self.max_hp <= 0:
            return 0.0
        return self.hp / self.max_hp

    def phase(self) -> str:
        return ec.phase_for_hp_fraction(self.hp_fraction())

    # -- Turn execution ------------------------------------------------------

    def take_turn(self, player: PlayerState,
                  rng: Callable[[int], int]) -> Tuple[PlayerState, Dict[str, Any]]:
        """Execute the currently-selected intent. Caller must set
        `current_intent` via choose_intent() before calling.

        Returns (new_player_state, log_entry). log_entry carries:
            intent, posture, narration, effect, value (optional), damage (optional),
            hp_delta (for strike).

        Session is responsible for applying non-damage effects (progress_delta,
        disadvantage_next, bonus_next_read) — those flags are in the log.
        """
        if self.current_intent is None:
            raise RuntimeError("take_turn called without current_intent")

        intent_name, intent = self.current_intent
        effect = intent.get("effect", "")
        log: Dict[str, Any] = {
            "intent":    intent_name,
            "posture":   intent.get("posture", ""),
            "effect":    effect,
            "hp_delta":  0,
        }

        new_player = player
        fmt_kwargs: Dict[str, Any] = {"actor": self.name}

        if effect == "damage":
            dspec = intent.get("damage", ["d", 4])
            dmg = _roll_damage_spec(dspec, rng)
            new_player = ps.take_damage(player, dmg)
            log["hp_delta"] = new_player.hp - player.hp
            log["damage"] = dmg
            fmt_kwargs["damage"] = dmg

        elif effect == "orb_heal":
            amt = int(intent.get("value", 1))
            self.heal(amt)
            log["value"] = amt
            fmt_kwargs["value"] = amt

        elif effect == "progress_delta":
            log["value"] = int(intent.get("value", 0))
            fmt_kwargs["value"] = log["value"]

        elif effect == "disadvantage_next":
            log["value"] = True

        elif effect == "bonus_next_read":
            log["value"] = True

        # Substitute any {actor} / {damage} / {value} placeholders in narration.
        log["narration"] = safe_fmt(intent.get("narration", ""), **fmt_kwargs)

        # Intent stays set so the session can render the posture label after
        # the turn; session's next choose_intent overwrites it.
        return new_player, log


# -- choose_intent (pure function) -------------------------------------------

def choose_intent(
    orb: Orb,
    last_action: Optional[str],
    last_save: Optional[str],
    rng: random.Random,
    mode: str = "action",
) -> Tuple[str, Dict[str, Any]]:
    """Pick the orb's next intent.

    Inputs:
        last_action — player's most recent action/verb or None
        last_save   — "pass" | "fail" | None (DEFEND has no save)
        rng         — random.Random instance; use seeded for determinism.
        mode        — "action" (combat intents) | "dialog" (dialog intents)

    Algorithm:
        1. Start from the mode-appropriate phase_weights[phase].
        2. Apply reactive_bumps (also mode-scoped) whose "when" matches.
        3. Weighted random pick by accumulated weight.

    Returns (intent_name, intent_spec). Caller typically assigns this to
    orb.current_intent before calling orb.take_turn().
    """
    phase = orb.phase()
    if mode == "dialog":
        phase_weights = orb.dialog_phase_weights
        bumps = orb.dialog_reactive_bumps
        lookup = ec.get_dialog_intent
    else:
        phase_weights = orb.phase_weights
        bumps = orb.reactive_bumps
        lookup = ec.get_intent

    weights: Dict[str, float] = dict(phase_weights.get(phase, {}))

    # Build the "when" key we'll match against reactive bumps.
    when_key = _bump_key(last_action, last_save)

    for bump in bumps:
        if bump["when"] == when_key:
            intent_name = bump["intent"]
            if intent_name in weights:
                weights[intent_name] *= float(bump.get("mult", 1.0))

    if not weights:
        raise RuntimeError(
            f"orb {orb.name!r} has no {mode} intents configured for phase {phase!r}")

    name = _weighted_choice(weights, rng)
    spec = lookup(name)
    return name, spec


def _bump_key(last_action: Optional[str], last_save: Optional[str]) -> str:
    """Build the reactive-bump `when` match key.

    Conventions:
        DEFEND  (no save)   → "DEFEND"
        <ACT>   + "pass"    → "ACT_pass"
        <ACT>   + "fail"    → "ACT_fail"
        None                → "" (nothing matches)
    """
    if last_action is None:
        return ""
    if last_action == "DEFEND":
        return "DEFEND"
    if last_save in ("pass", "fail"):
        return f"{last_action}_{last_save}"
    return last_action


def _weighted_choice(weights: Dict[str, float], rng: random.Random) -> str:
    total = sum(weights.values())
    if total <= 0:
        # Degenerate: all zeros. Return an arbitrary key deterministically.
        return next(iter(weights))
    r = rng.random() * total
    acc = 0.0
    for name, w in weights.items():
        acc += w
        if r <= acc:
            return name
    # Numerical drift fallback
    return name


def safe_fmt(template: str, **kwargs) -> str:
    """Replace {key} placeholders in template with kwargs values. Unknown keys
    are left intact (rather than raising KeyError). Useful for narration and
    telegraph strings that may reference fields only known post-roll."""
    if not template:
        return ""
    out = template
    for k, v in kwargs.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def _roll_damage_spec(spec, rng: Callable[[int], int]) -> int:
    if isinstance(spec, int):
        return spec
    if isinstance(spec, (list, tuple)) and len(spec) >= 2 and spec[0] == "d":
        return rng(int(spec[1]))
    raise ValueError(f"bad damage spec {spec!r}")
