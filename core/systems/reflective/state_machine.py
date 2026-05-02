"""Reflective-mode state machine — pure operations on world.reflective.

This module mutates `world.reflective` only. It does NOT touch
`world.game_state` — game state transitions live with their callers
(the consequence effect handler for HP=0 forced entry, the brain
cmd handler for voluntary fridge engagement). Keeps the state
machine reusable between paths and trivially unit-testable.

Operations:
- `enter(world, trigger, rng)` — pick a rule, compose pool, populate state
- `place_magnet(world, magnet)` — append to composed if magnet in pool
- `remove_magnet(world, index)` — pop from composed by index
- `commit(world)` — eval AC predicates; return True on satisfied
- `exit(world)` — reset reflective state to defaults
- `pick_rule(rng)` — select a rule id from the registry (V1: random pick)

V1 uses random rule pick (one rule registered, so always
`compose_three`). Future variety (Wario Ware DNA) emerges from
register more rules without engine change.
"""
from __future__ import annotations

import random

from core.systems.reflective import ac_predicates, magnets, rules


def enter(
    world,
    trigger: str,
    rng: random.Random | None = None,
) -> bool:
    """Enter reflective mode: pick a rule, compose pool, populate state.

    `trigger` discriminates entry path: "hp_zero" (forced via
    consequences engine) vs "voluntary" (player engaged the fridge).

    Returns True if entry succeeded, False if the rule registry is
    empty (no rules to pick from). Caller is responsible for
    `world.game_state` transition — this function is state-pure.
    """
    if rng is None:
        rng = random.Random()

    rule_id = pick_rule(rng)
    if rule_id is None:
        return False

    rule = rules.get(rule_id)
    if rule is None:
        return False

    pool = magnets.compose_pool(rng)

    world.reflective.active = True
    world.reflective.trigger = trigger
    world.reflective.current_rule_id = rule_id
    world.reflective.rule_args = dict(rule.ac_args)
    world.reflective.magnet_pool = pool
    world.reflective.composed = []
    world.reflective.attempt_count = 0
    return True


def place_magnet(world, magnet: str) -> bool:
    """Append a magnet to composed. Returns True if placed.

    Validates that the magnet exists in the current pool. V1 has no
    scarcity — duplicates allowed (the pool is the dictionary, not
    the physical magnet count). If a future rule requires scarcity,
    add a `consume_on_place` flag to PoolConfig and gate here.
    """
    if not world.reflective.active:
        return False
    if magnet not in world.reflective.magnet_pool:
        return False
    world.reflective.composed.append(magnet)
    return True


def remove_magnet(world, index: int) -> bool:
    """Pop a magnet from composed by index. Returns True if removed."""
    if not world.reflective.active:
        return False
    composed = world.reflective.composed
    if index < 0 or index >= len(composed):
        return False
    composed.pop(index)
    return True


def commit(world) -> bool:
    """Evaluate all AC predicates against the current composition.

    Returns True if every predicate in the rule's ac_predicates list
    returns True (logical AND). Increments `attempt_count` regardless.

    Does NOT exit or transition — caller decides what to do based on
    the return value (emit success event for consequence engine to
    pick up, or stay in reflective mode and try again).
    """
    if not world.reflective.active:
        return False

    rule = rules.get(world.reflective.current_rule_id)
    if rule is None:
        return False

    world.reflective.attempt_count += 1

    for pred_name in rule.ac_predicates:
        fn = ac_predicates.get(pred_name)
        if fn is None:
            # Typo'd predicate name — fail-safe: deny commit. Test
            # suite catches typos at rule-registration time.
            return False
        args = rule.ac_args.get(pred_name, {})
        if not fn(world, args, world.reflective):
            return False

    return True


def exit(world) -> None:
    """Reset reflective state to defaults. Idempotent — safe to call
    on already-exited worlds."""
    world.reflective.active = False
    world.reflective.trigger = ""
    world.reflective.current_rule_id = ""
    world.reflective.rule_args = {}
    world.reflective.magnet_pool = []
    world.reflective.composed = []
    world.reflective.attempt_count = 0


def pick_rule(rng: random.Random) -> str | None:
    """Choose a rule id from the registry. V1: uniform random pick.

    Future variety axes (rule weighting by trigger / mood / time-of-day)
    can extend this without changing callers.
    """
    available = sorted(rules.all_rules().keys())
    if not available:
        return None
    return rng.choice(available)
