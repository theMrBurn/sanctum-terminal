"""Brain-side signal pushers — write side of the consequence engine.

Predicates (in `predicates.py`) READ events; signals (here) WRITE
them. Pairing them in the same package keeps the trigger contract
visible: when you add a built-in predicate, add the matching signal
helper here so brain damage / event paths have an idempotent push site.

Per `design_virtual_hallucination`: HP=0 signals are JUST respawn
conditions. No `death` / `die` identifiers. Per
`design_render_reuse_mandate`: signals stay generic enough to be
reused — `push_hp_zero` lives in this module precisely so future
damage paths (combat, environmental) call the same helper instead of
each duplicating the dedup check.

Module is brain-independent — it operates on duck-typed worlds with
`player.hp` and `tick_events` attributes only. Tests can pass plain
dataclass fakes.
"""
from __future__ import annotations

from typing import Any, Protocol


class _PlayerLike(Protocol):
    hp: int


class _WorldLike(Protocol):
    player: Any
    tick_events: list[dict]


def push_hp_zero(world: _WorldLike) -> None:
    """Push a `hp_zero` event onto `world.tick_events` when player HP
    has reached zero.

    Called after each HP-mutator (currently `damage_self` in
    `brain_server.py`; future combat / environmental damage paths land
    here too). Single deduped push per tick — multiple damage events
    in one frame collapse to one signal.

    No-op when HP is positive. Idempotent within a tick — does not
    re-push if a `hp_zero` event already exists in `tick_events`.

    Negative HP also triggers (overkill damage) — the engine treats
    HP=0 and HP<0 identically.
    """
    if world.player.hp > 0:
        return
    for evt in world.tick_events:
        if evt.get("type") == "hp_zero":
            return
    world.tick_events.append({"type": "hp_zero"})
