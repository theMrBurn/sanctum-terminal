"""Rule registry — the variety axis of reflective mode.

Each rule is one Wario-Ware-shape micro-game inside the fridge. V1
ships `compose_three` (smallest possible). Future rules add acrostic
constraints, theme matching, rhyme requirements, spatial arrangement,
subtraction puzzles — see `design_reflective_loop` for the variety
table.

A rule is data: an id, player-facing copy, and a list of AC
predicate references with their args. The brain picks a rule on
reflective entry; the predicate chain evaluates on commit.

Per `design_render_reuse_mandate`: same registry shape as quests,
consequences, AC predicates. Pattern is repetitive on purpose —
each subsystem is one drop-in plus its built-ins.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Rule:
    """Registered shape of a reflective-mode rule.

    `ac_predicates` lists predicate ids that must ALL return True for
    commit to succeed. `ac_args[predicate_id]` is the args dict passed
    to that predicate. Missing entries default to {} — the predicate
    handles its own defaults.
    """
    id: str
    name: str               # short label ("Compose")
    instructions: str       # one-line player copy ("Place three magnets...")
    ac_predicates: list[str] = field(default_factory=list)
    ac_args: dict = field(default_factory=dict)


_REGISTRY: dict[str, Rule] = {}


def register(rule: Rule) -> None:
    if rule.id in _REGISTRY:
        raise ValueError(f"rule already registered: {rule.id!r}")
    _REGISTRY[rule.id] = rule


def get(rule_id: str) -> Rule | None:
    return _REGISTRY.get(rule_id)


def all_rules() -> dict[str, Rule]:
    """Snapshot of the registry. Tests + brain rule picker both consume this."""
    return dict(_REGISTRY)


def clear() -> None:
    """Test-only — reset the registry."""
    _REGISTRY.clear()
