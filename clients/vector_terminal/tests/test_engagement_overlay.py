"""engagement overlay — dispatcher + manifest reading (no raylib input).

Per `.claude/feature/feat_creature-engagement.md` PR 5 T5: dispatcher
routes correctly and the overlay reads the right fields from the
manifest. Actual key-press handling lives behind pyray and is
exercised via UAT.
"""
from __future__ import annotations

import pytest

from clients.vector_terminal import engagement


# ── is_active / engagement_type ─────────────────────────────────────


def test_is_active_false_when_no_engagement_block():
    assert engagement.is_active({}) is False


def test_is_active_false_when_engagement_state_is_none():
    assert engagement.is_active({"engagement_state": None}) is False


def test_is_active_true_when_engagement_state_populated():
    manifest = {"engagement_state": {"engagement_type": "compose_three"}}
    assert engagement.is_active(manifest) is True


def test_engagement_type_returns_empty_when_absent():
    assert engagement.engagement_type({}) == ""


def test_engagement_type_returns_type_string():
    manifest = {"engagement_state": {"engagement_type": "compose_three"}}
    assert engagement.engagement_type(manifest) == "compose_three"


# ── Cursor clamping ─────────────────────────────────────────────────


def test_state_init_cursor_zero():
    s = engagement.EngagementState()
    assert s.tray_cursor == 0


# ── Dispatcher — unknown types fall through ──────────────────────────


def test_handle_input_returns_none_for_unknown_type(monkeypatch):
    """Unsupported engagement_types must not crash — they fall through."""
    manifest = {"engagement_state": {
        "engagement_type": "rhythm_three",
        "pool": [], "composed": [],
    }}
    state = engagement.EngagementState()
    action, payload = engagement.handle_input(manifest, state)
    assert action is None
    assert payload is None


def test_handle_input_returns_none_when_no_engagement_state():
    state = engagement.EngagementState()
    action, payload = engagement.handle_input({}, state)
    assert action is None
    assert payload is None
