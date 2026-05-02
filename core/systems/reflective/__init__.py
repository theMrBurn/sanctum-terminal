"""Reflective mode — fridge + magnets, AC-gated return to active play.

Per `design_reflective_loop` and `design_virtual_hallucination`:
HP=0 routes the player into reflective mode (forced); the player can
also engage voluntarily via the fridge in hub. Reflective mode is
a state, not a screen — the fridge is a tangible kind in the world.

Player composes a poem from a magnet pool under a varying rule
(Wario Ware DNA — V1 ships with just `compose_three`). On commit,
AC predicates evaluate the composition; if satisfied, the brain
emits a trigger-specific event (`reflective_committed_from_hp_zero`
or `reflective_committed_voluntary`) that the consequences engine
picks up to drive the exit chain.

Substrate (this package): ReflectiveState dataclass, AC predicate
registry, rule registry, magnet pool. State machine + brain cmd
handlers + fridge kind + client UI land in subsequent PR 3.5 steps.

Trigger semantics:
- `hp_zero` (forced) — must commit; abort not allowed in V1.
- `voluntary` (walk-up) — abort allowed any time; ambient practice.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ReflectiveState:
    """Live reflective-mode state on world.

    Session-only — not persisted in V3 save schema. `current_rule_id`
    is re-rolled on each entry; `composed` resets per attempt.
    Persistent fridge poems (writing committed poems back to a vault
    category for cross-session display on the fridge) is a post-V1
    content arc and will introduce its own V4 schema bump.

    `trigger` discriminates the entry path:
    - "hp_zero"   — forced via consequences engine after damage
    - "voluntary" — player walked up to fridge and engaged

    Different post-commit and abort semantics depending on trigger
    (see brain cmd handlers in step 8). The state itself doesn't
    enforce trigger-conditional behavior — that lives in the cmd
    handler that emits the right event onto tick_events.
    """
    active: bool = False
    trigger: str = ""
    current_rule_id: str = ""
    rule_args: dict = field(default_factory=dict)
    magnet_pool: list[str] = field(default_factory=list)
    composed: list[str] = field(default_factory=list)
    attempt_count: int = 0


# Trigger auto-registration of built-in AC predicates by importing the
# module — same pattern as `core.systems.quests.__init__`.
from core.systems.reflective import ac_predicates as _ac_predicates  # noqa: E402, F401
