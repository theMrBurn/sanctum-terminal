"""Stateful wrapper around combat.resolve_round.

A session holds participants across rounds, tracks round index, and
detects end conditions (victory / defeat / fled). The math stays in
combat.resolve_round — this module adds the bookkeeping.

Callers drive it like:

    session = CombatSession([player, rat1, rat2], attack_lib, roll_die)
    while not session.ended:
        actions = gather_actions_from_ui(session)
        log = session.resolve(actions)
        render(log, session.participants)
    if session.outcome == "victory":
        award_xp(...)

No I/O. Testable in isolation with ScriptedRoller.
"""
from __future__ import annotations

from typing import Callable, Dict, List

from core.systems.combat import (
    Action, AttackDef, Participant, resolve_round,
)


_VALID_OUTCOMES = {"active", "victory", "defeat", "fled"}


class CombatSession:
    def __init__(self,
                 participants: List[Participant],
                 attack_lib: Dict[str, AttackDef],
                 roll_die: Callable[[int], int]):
        self.participants: List[Participant] = list(participants)
        self.attack_lib = attack_lib
        self.roll_die = roll_die
        self.round: int = 0
        self.outcome: str = "active"

    @property
    def ended(self) -> bool:
        return self.outcome != "active"

    def living_players(self) -> List[Participant]:
        return [p for p in self.participants if p.side == "player" and p.alive]

    def living_enemies(self) -> List[Participant]:
        return [p for p in self.participants if p.side == "enemy" and p.alive]

    def resolve(self, actions: List[Action]) -> list:
        """Advance one round. Returns the event log. Noop if already ended."""
        if self.ended:
            return []
        new_parts, log = resolve_round(
            self.participants, actions, self.attack_lib, self.roll_die)
        self.participants = new_parts
        self.round += 1
        self._update_outcome(log)
        return log

    def _update_outcome(self, log: list) -> None:
        # Flee first — successful flee ends combat regardless of survivors.
        for event in log:
            if event.get("verb") == "flee" and event.get("result") == "fled":
                self.outcome = "fled"
                return
        if not self.living_players():
            self.outcome = "defeat"
            return
        if not self.living_enemies():
            self.outcome = "victory"
            return
        self.outcome = "active"
