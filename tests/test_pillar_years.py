"""Pillar 3 — YearsHandler binary-narrow cascade.

Tests:
  - Initial prompt builds narrow dial with 1–120 range
  - First pivot uses hint["previous_age"] when supplied, else default 40
  - Narrow answers shrink range correctly (< and >=)
  - Cascade converges to single int within ~7 questions
  - Final confirm dial returned when range collapses
  - Confirm idx 0 commits int via apply()
  - "Actually start over" restarts the cascade
  - apply() returns {"age": N} for ints, {} otherwise (defensive)
"""
from __future__ import annotations

from core.systems.character_draft import CharacterDraft
from core.systems.dial_prompt import NARROW, RITUAL, SELECT
from core.systems.pillars.years import (
    _DEFAULT_FIRST_PIVOT,
    _MAX_AGE,
    _MIN_AGE,
    YearsHandler,
)


# ── Initial prompt ──


def test_initial_prompt_is_narrow_mode():
    h = YearsHandler()
    p = h.initial_prompt(CharacterDraft())
    assert p.mode == NARROW
    assert p.register == RITUAL
    assert p.source == "pillar:years"
    assert p.label == "WALK THE RINGS"


def test_initial_pivot_defaults_to_40():
    h = YearsHandler()
    p = h.initial_prompt(CharacterDraft())
    assert p.pivot_value == _DEFAULT_FIRST_PIVOT


def test_initial_pivot_uses_previous_age_hint():
    h = YearsHandler()
    p = h.initial_prompt(CharacterDraft(), hint={"previous_age": 30})
    assert p.pivot_value == 30


def test_initial_pivot_clamps_to_valid_range():
    h = YearsHandler()
    # Out-of-bounds hints get clamped
    p_low = h.initial_prompt(CharacterDraft(), hint={"previous_age": -5})
    assert _MIN_AGE < p_low.pivot_value < _MAX_AGE
    p_high = h.initial_prompt(CharacterDraft(), hint={"previous_age": 9999})
    assert _MIN_AGE < p_high.pivot_value < _MAX_AGE


def test_initial_pivot_falls_back_on_garbage_hint():
    h = YearsHandler()
    p = h.initial_prompt(CharacterDraft(), hint={"previous_age": "not-a-number"})
    assert p.pivot_value == _DEFAULT_FIRST_PIVOT


def test_initial_range_spans_min_to_max():
    h = YearsHandler()
    p = h.initial_prompt(CharacterDraft())
    assert p.range_remaining == (_MIN_AGE, _MAX_AGE)


def test_initial_options_label_with_pivot():
    h = YearsHandler()
    p = h.initial_prompt(CharacterDraft(), hint={"previous_age": 50})
    assert p.options[0].label == "YOUNGER THAN 50"
    assert p.options[1].label == "OLDER OR EQUAL TO 50"


# ── Narrow cascade ──


def test_lt_answer_shrinks_to_lower_half():
    h = YearsHandler()
    p = h.initial_prompt(CharacterDraft(), hint={"previous_age": 50})
    follow = h.next_prompt(CharacterDraft(), p, 0)  # "<" — younger
    assert follow is not None
    assert follow.range_remaining == (_MIN_AGE, 49)


def test_ge_answer_shrinks_to_upper_half():
    h = YearsHandler()
    p = h.initial_prompt(CharacterDraft(), hint={"previous_age": 50})
    follow = h.next_prompt(CharacterDraft(), p, 1)  # ">=" — older
    assert follow is not None
    assert follow.range_remaining == (50, _MAX_AGE)


def test_cascade_converges_to_confirm_within_bounded_steps():
    """Driving the cascade toward 45 should converge within ~log2(120) ≈ 7 asks."""
    h = YearsHandler()
    target = 45
    draft = CharacterDraft()
    current = h.initial_prompt(draft)
    asks = 0
    while current is not None and current.mode == NARROW and asks < 12:
        pivot = int(current.pivot_value)
        idx = 0 if target < pivot else 1  # answer truthfully
        current = h.next_prompt(draft, current, idx)
        asks += 1
    assert asks <= 8  # should converge well under 12
    assert current is not None
    assert current.mode == SELECT  # final confirm
    # The confirm dial should reference the converged target
    assert "45" in current.label or "45" in current.options[0].label


def test_confirm_select_idx_0_returns_none():
    """Confirming the converged age sends None from next_prompt; brain commits via apply()."""
    h = YearsHandler()
    target = 23
    draft = CharacterDraft()
    current = h.initial_prompt(draft)
    while current is not None and current.mode == NARROW:
        pivot = int(current.pivot_value)
        idx = 0 if target < pivot else 1
        current = h.next_prompt(draft, current, idx)

    # Now in confirm mode
    assert current.mode == SELECT
    follow = h.next_prompt(draft, current, 0)  # YES
    assert follow is None  # brain commits


def test_confirm_select_idx_1_restarts_cascade():
    """ACTUALLY START OVER returns a fresh narrow dial at default pivot."""
    h = YearsHandler()
    draft = CharacterDraft()
    current = h.initial_prompt(draft)
    while current is not None and current.mode == NARROW:
        current = h.next_prompt(draft, current, 1)  # always older

    # Now in confirm mode
    assert current.mode == SELECT
    follow = h.next_prompt(draft, current, 1)  # ACTUALLY START OVER
    assert follow is not None
    assert follow.mode == NARROW
    assert follow.range_remaining == (_MIN_AGE, _MAX_AGE)
    assert follow.pivot_value == _DEFAULT_FIRST_PIVOT


def test_extreme_low_age_converges():
    """Walking 'younger' every time should converge near the floor."""
    h = YearsHandler()
    draft = CharacterDraft()
    current = h.initial_prompt(draft)
    while current is not None and current.mode == NARROW:
        current = h.next_prompt(draft, current, 0)  # always younger

    assert current.mode == SELECT
    final_age = current.options[0].value
    assert _MIN_AGE <= final_age <= 5  # close to floor


def test_extreme_high_age_converges():
    """Walking 'older' every time should converge near the ceiling."""
    h = YearsHandler()
    draft = CharacterDraft()
    current = h.initial_prompt(draft)
    while current is not None and current.mode == NARROW:
        current = h.next_prompt(draft, current, 1)  # always older

    assert current.mode == SELECT
    final_age = current.options[0].value
    assert _MAX_AGE - 5 <= final_age <= _MAX_AGE


# ── apply ──


def test_apply_commits_int_to_age_field():
    h = YearsHandler()
    assert h.apply(45) == {"age": 45}


def test_apply_rejects_non_int_gracefully():
    """Defensive: anything weird becomes a no-op so the draft stays clean."""
    h = YearsHandler()
    assert h.apply("restart") == {}
    assert h.apply(None) == {}
    assert h.apply([45]) == {}


def test_apply_clamps_out_of_range():
    h = YearsHandler()
    # Out-of-range ints are rejected (defensive — shouldn't happen via the
    # cascade but apply() is the boundary)
    assert h.apply(0) == {}
    assert h.apply(_MAX_AGE + 1) == {}


# ── End-to-end via full draft fold ──


def test_pillar_committed_to_draft_propagates_to_state():
    """Simulate brain-side flow: cascade → apply → draft.append → state fold."""
    from core.systems import pillars

    h = YearsHandler()
    draft = CharacterDraft()
    target = 45
    current = h.initial_prompt(draft, hint={"previous_age": 30})
    while current is not None and current.mode == NARROW:
        pivot = int(current.pivot_value)
        idx = 0 if target < pivot else 1
        current = h.next_prompt(draft, current, idx)
    # Now in confirm; commit via idx 0
    chosen_value = current.options[0].value
    draft.append("years", chosen_value)
    state = draft.state(pillars.all_handlers())
    assert state.get("age") == target
