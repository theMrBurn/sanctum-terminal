"""CharacterDraft — event-sourced fold, finalization, replay."""
from __future__ import annotations

import pytest

from core.systems import pillars
from core.systems.character_draft import CharacterDraft, REQUIRED_PILLARS


# Build the handler dict once for tests — same pattern brain will use.
HANDLERS = pillars.all_handlers()


def test_empty_draft_state_is_empty():
    draft = CharacterDraft()
    assert draft.state(HANDLERS) == {}


def test_empty_draft_is_not_complete():
    draft = CharacterDraft()
    assert not draft.is_complete()
    assert draft.completed_pillars() == set()


def test_append_records_event():
    draft = CharacterDraft()
    draft.append("name", "Sean")
    assert len(draft.pillar_events) == 1
    assert draft.pillar_events[0].pillar == "name"
    assert draft.pillar_events[0].answer == "Sean"


def test_state_folds_through_handler_apply():
    draft = CharacterDraft()
    draft.append("name", "Sean")
    state = draft.state(HANDLERS)
    assert state == {"name": "Sean"}


def test_redo_pillar_keeps_latest():
    draft = CharacterDraft()
    draft.append("name", "Sean")
    draft.append("name", "Brother Sean")
    state = draft.state(HANDLERS)
    # Latest event wins
    assert state == {"name": "Brother Sean"}
    # But the log preserves both events
    assert len(draft.pillar_events) == 2


def test_progress_reports_completion_per_pillar():
    draft = CharacterDraft()
    draft.append("name", "Sean")
    progress = draft.progress()
    assert progress["name"] is True
    assert progress["days"] is False
    assert set(progress.keys()) == REQUIRED_PILLARS


def test_unknown_pillar_in_log_is_skipped_during_state():
    """If a handler is missing (e.g., schema migration), the fold still works."""
    draft = CharacterDraft()
    draft.append("name", "Sean")
    draft.append("unknown_pillar_v2", "future_value")
    state = draft.state(HANDLERS)
    assert state == {"name": "Sean"}  # unknown pillar dropped


def test_finalize_raises_when_incomplete():
    draft = CharacterDraft()
    draft.append("name", "Sean")
    with pytest.raises(ValueError, match="incomplete"):
        draft.finalize(HANDLERS)


def test_required_pillars_are_seven():
    """Per `design_seven_pillars`: exactly 7 pillars required."""
    assert len(REQUIRED_PILLARS) == 7
    assert REQUIRED_PILLARS == frozenset({
        "name", "days", "years", "first_path", "vow", "standing", "mark",
    })
