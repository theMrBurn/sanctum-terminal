"""Pillar 3 — Pillar of Years (interactive binary-narrow cascade).

Per `design_seven_pillars` + `design_dial_input`: the canonical narrow-mode
pillar. Player answers ~7 binary questions ("older or younger than X?")
to converge on their age 1-100. Final confirm dial commits the int.

Pattern setter for any future continuous-numeric pillar (Pillar 6
Standing's stat bands, future age/weight/depth scalars). Same code shape;
just different range.

First-pivot heuristic: if `hint["previous_age"]` is provided (re-do flow
via Pillar of Reflection), use that as the starting pivot — convergence
happens in 3-4 questions instead of 7. Falls back to 40 (median guess)
otherwise.

Verb: MARK (per `design_seven_pillars`). Register: ritual.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.systems import pillars
from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import (
    DialOption,
    DialPrompt,
    NARROW,
    RITUAL,
    SELECT,
)


# Range bounds. Anyone outside this is reading a different game.
_MIN_AGE = 1
_MAX_AGE = 120

# Default first pivot when no hint is supplied (median-ish, slightly low
# to bias the early questions toward common adult range).
_DEFAULT_FIRST_PIVOT = 40

# Sentinel string values for narrow-cascade options. Brain's dial_response
# handler reads them via current.options[idx].value.
_LT = "<"   # younger than pivot
_GE = ">="  # older or equal to pivot

# Sentinel for the final confirm "actually start over" branch.
_RESTART = "restart"


def _narrow_dial(low: int, high: int, pivot: int) -> DialPrompt:
    """Build one binary-narrow ask: 'YOUNGER THAN N' vs 'OLDER OR EQUAL TO N'.

    Default index 0 (the "younger" option) — somewhat arbitrary but
    consistent. The right narrowing direction comes from the player's
    answer; default just picks one without bias toward either tail.
    """
    return DialPrompt(
        source="pillar:years",
        label="WALK THE RINGS",
        mode=NARROW,
        options=[
            DialOption(label=f"YOUNGER THAN {pivot}", value=_LT,
                       bias=f"range {low}–{pivot - 1}"),
            DialOption(label=f"OLDER OR EQUAL TO {pivot}", value=_GE,
                       bias=f"range {pivot}–{high}"),
        ],
        default_index=0,
        register=RITUAL,
        pivot_value=pivot,
        range_remaining=(low, high),
    )


def _confirm_dial(age: int) -> DialPrompt:
    """Final select-mode confirm. The chosen option's value is the int age,
    so the brain's dial_response handler can commit it directly via apply()."""
    return DialPrompt(
        source="pillar:years",
        label=f"YOU ARE {age}",
        mode=SELECT,
        options=[
            DialOption(label=f"YES, I AM {age}", value=age,
                       bias="seal"),
            DialOption(label="ACTUALLY, START OVER", value=_RESTART,
                       bias="reset narrow"),
        ],
        default_index=0,
        register=RITUAL,
    )


@dataclass
class YearsHandler:
    pillar_id: str = "years"

    def initial_prompt(
        self,
        draft: CharacterDraft,
        hint: dict | None = None,
    ) -> DialPrompt:
        prev = (hint or {}).get("previous_age")
        try:
            pivot = int(prev) if prev is not None else _DEFAULT_FIRST_PIVOT
        except (TypeError, ValueError):
            pivot = _DEFAULT_FIRST_PIVOT
        pivot = max(_MIN_AGE + 1, min(_MAX_AGE - 1, pivot))
        return _narrow_dial(_MIN_AGE, _MAX_AGE, pivot)

    def next_prompt(
        self,
        draft: CharacterDraft,
        current: DialPrompt,
        answer_idx: int,
    ) -> DialPrompt | None:
        # Final confirm: idx 0 ("YES, I AM N") commits the int via apply();
        # idx 1 ("ACTUALLY, START OVER") restarts the cascade.
        if current.mode == SELECT:
            chosen = current.options[answer_idx].value
            if chosen == _RESTART:
                return _narrow_dial(_MIN_AGE, _MAX_AGE, _DEFAULT_FIRST_PIVOT)
            return None  # idx 0: brain commits the int via apply()

        # Narrow cascade: shrink range based on which side player picked.
        low, high = current.range_remaining
        pivot = int(current.pivot_value)
        chosen = current.options[answer_idx].value

        if chosen == _LT:
            new_low, new_high = low, pivot - 1
        else:  # _GE
            new_low, new_high = pivot, high

        # Guard against degenerate ranges (shouldn't happen with valid pivots
        # but defensive — if low > high somehow, treat as converged).
        if new_low >= new_high:
            return _confirm_dial(new_low)

        # Range still has multiple ints; emit next narrow ask at midpoint.
        new_pivot = (new_low + new_high) // 2
        # Edge case: midpoint equals one of the bounds (range size 2).
        # Bump pivot up to force progress.
        if new_pivot == new_low:
            new_pivot = new_low + 1

        return _narrow_dial(new_low, new_high, new_pivot)

    def apply(self, answer: Any) -> dict:
        # Confirm-mode commit sends int. Anything else (restart sentinel,
        # accidental string) falls through to no-op so the draft stays
        # unchanged and the cascade can continue.
        if isinstance(answer, int) and _MIN_AGE <= answer <= _MAX_AGE:
            return {"age": answer}
        return {}


pillars.register(YearsHandler())
