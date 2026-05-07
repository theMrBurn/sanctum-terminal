"""Turn-based combat resolution — one round = all participants submit
actions, then everything resolves in speed order.

Data-driven on purpose. Attacks live in a library (dict keyed by name);
formulas are structured records, not strings; element modifiers ride on
each participant. Status effects, crits, skill trees, and item effects
slot in without signature churn — all consumed as attributes on the
participants + attacks.

Pure function resolve_round(...) → (new_participants, log). RNG is
injected as a callable: roll_die(size) → int in [1, size]. Tests supply
a scripted roller for exact-outcome pinning; runtime supplies a
random-backed one.

No I/O. Coordinate-agnostic (positional combat lives above this layer).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, NamedTuple, Optional, Tuple


# --- Participant shape -------------------------------------------------------
# Wide enough to carry future additions (status counters, per-element
# mods, inventory, skills) without breaking the resolve_round signature.

@dataclass(frozen=True)
class Participant:
    id: str
    name: str
    hp: int
    max_hp: int
    str_: int
    dex: int
    wil: int
    speed: int
    defense: int
    element_mods: Dict[str, float]     # per-element damage multiplier; default 1.0
    side: str                          # "player" | "enemy"
    inventory: Tuple                   # tuple of Items — tight coupling to player_state avoided
    status: Dict[str, object]          # per-round flags: {"defending": True, "burning": 2}
    alive: bool


# --- Attack library (data-only) ----------------------------------------------

class Formula(NamedTuple):
    dice: Tuple[int, int]     # (num, sides) — (1, 20) = 1d20
    stat: Optional[str]       # attribute on actor to add to roll (e.g. "str_")
    const: int = 0            # flat bonus


class AttackDef(NamedTuple):
    name: str
    verb: str                 # "attack" | "magic" | "skill" | "item"
    element: str              # "physical" | "fire" | "ice" | "electric" | "light"
    hit_formula: Formula
    damage_formula: Formula
    target_stat: str          # attribute on target the hit roll must meet
    status: Optional[str]     # status effect applied on successful hit


class Action(NamedTuple):
    actor_id: str
    verb: str                 # "attack" | "magic" | "skill" | "item" | "defend" | "flee"
    attack_name: str          # key into attack_lib; ignored for defend/flee/item
    target_id: str            # ignored for defend/flee


# --- RNG ---------------------------------------------------------------------

class ScriptedRoller:
    """Test helper. roll_die(sides) pops the next value. Raises on empty
    so we catch 'more rolls than the test planned'."""
    def __init__(self, rolls):
        self._rolls = list(rolls)

    def __call__(self, sides: int) -> int:
        if not self._rolls:
            raise AssertionError("ScriptedRoller out of rolls")
        v = self._rolls.pop(0)
        return v


# --- Resolution --------------------------------------------------------------

LogEvent = Dict[str, object]


def _roll_formula(f: Formula, actor: Participant,
                  roll_die: Callable[[int], int]) -> int:
    n, sides = f.dice
    total = sum(roll_die(sides) for _ in range(n))
    if f.stat is not None:
        total += getattr(actor, f.stat)
    total += f.const
    return total


def _find(participants: List[Participant], pid: str) -> Optional[Participant]:
    for p in participants:
        if p.id == pid:
            return p
    return None


def _replace(p: Participant, **kw) -> Participant:
    # dataclasses.replace shim that preserves the frozen contract.
    import dataclasses
    return dataclasses.replace(p, **kw)


def _kill_if_zero(p: Participant) -> Participant:
    if p.hp <= 0 and p.alive:
        return _replace(p, hp=0, alive=False)
    return p


def resolve_round(
    participants: List[Participant],
    actions: List[Action],
    attack_lib: Dict[str, AttackDef],
    roll_die: Callable[[int], int],
) -> Tuple[List[Participant], List[LogEvent]]:
    """Resolve one round. Returns (new_participants, log). See module docstring."""
    # Snapshot state — we mutate a local list, never the inputs.
    state: List[Participant] = list(participants)
    log: List[LogEvent] = []

    # Reset per-round status flags before resolving (e.g. defending from
    # last round doesn't carry; persistent statuses like burning have
    # their own tick — deferred to the status-effect pass).
    state = [_replace(p, status={k: v for k, v in p.status.items()
                                  if k != "defending"})
             for p in state]

    # Apply all `defend` actions FIRST regardless of speed so the flag is
    # visible to attackers resolving later in the order.
    defending_ids: set = set()
    for act in actions:
        if act.verb != "defend":
            continue
        actor = _find(state, act.actor_id)
        if actor is None or not actor.alive:
            log.append({"actor": act.actor_id, "verb": "defend",
                        "result": "skipped_dead" if actor else "unknown_actor"})
            continue
        defending_ids.add(actor.id)
        idx = state.index(actor)
        state[idx] = _replace(actor,
                              status={**actor.status, "defending": True})
        log.append({"actor": actor.id, "verb": "defend", "result": "defending"})

    # Sort remaining actions by actor speed (desc), stable on id for ties.
    # Dead actors filter happens at resolution time (an actor may die mid-round).
    non_defend = [a for a in actions if a.verb != "defend"]
    action_order = sorted(
        non_defend,
        key=lambda a: (
            -(getattr(_find(state, a.actor_id), "speed", 0) or 0),
            a.actor_id,
        ),
    )

    for act in action_order:
        actor = _find(state, act.actor_id)
        if actor is None:
            log.append({"actor": act.actor_id, "verb": act.verb,
                        "result": "unknown_actor"})
            continue
        if not actor.alive:
            log.append({"actor": actor.id, "verb": act.verb,
                        "result": "skipped_dead"})
            continue

        if act.verb == "flee":
            # DEX save, Cairn-flavored: d20 ≤ dex = success.
            roll = roll_die(20)
            success = roll <= actor.dex
            log.append({
                "actor": actor.id, "verb": "flee",
                "result": "fled" if success else "flee_failed",
                "roll": roll, "stat": actor.dex,
            })
            continue

        if act.verb == "item":
            # Item use framework lives here; v1 stub — a session layer will
            # look up the item's effect (heal/damage/buff) and call back.
            log.append({"actor": actor.id, "verb": "item",
                        "result": "noop", "note": "item effects deferred"})
            continue

        # attack / magic / skill — all share the hit → damage path, driven
        # by the AttackDef. Skill is just another attack entry in the lib.
        atk = attack_lib.get(act.attack_name)
        if atk is None:
            log.append({"actor": actor.id, "verb": act.verb,
                        "result": "unknown_attack",
                        "attack_name": act.attack_name})
            continue

        target = _find(state, act.target_id)
        if target is None or not target.alive:
            log.append({"actor": actor.id, "verb": act.verb,
                        "result": "target_gone",
                        "attack": atk.name})
            continue

        # Hit roll vs target_stat
        hit_total = _roll_formula(atk.hit_formula, actor, roll_die)
        target_threshold = getattr(target, atk.target_stat, 0)
        if hit_total < target_threshold:
            log.append({
                "actor": actor.id, "verb": act.verb, "target": target.id,
                "attack": atk.name, "element": atk.element,
                "result": "miss",
                "hit_roll": hit_total, "target_stat": target_threshold,
            })
            continue

        # Damage roll, element multiplier, defend halving
        raw = _roll_formula(atk.damage_formula, actor, roll_die)
        elem_mult = float(target.element_mods.get(atk.element, 1.0))
        damage = int(raw * elem_mult)
        if target.id in defending_ids:
            damage //= 2

        new_hp = max(0, target.hp - damage)
        idx = state.index(target)
        state[idx] = _kill_if_zero(_replace(target, hp=new_hp))

        log.append({
            "actor": actor.id, "verb": act.verb, "target": target.id,
            "attack": atk.name, "element": atk.element,
            "result": "hit",
            "hit_roll": hit_total, "target_stat": target_threshold,
            "damage": damage, "damage_raw": raw,
            "element_mult": elem_mult,
        })

    return state, log
