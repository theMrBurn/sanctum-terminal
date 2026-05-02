"""HUD active-quest rows builder (PR 4 step 4d).

Validates the pure `_build_active_quest_rows(manifest, max_rows)`
helper. Render itself (`draw_hud`) requires a graphical context
and is covered by visual UAT.
"""
from __future__ import annotations

from clients.vector_terminal.hud import _build_active_quest_rows


def _manifest(active=None, registry=None, bearings=None):
    return {
        "quests": {
            "active": list(active or []),
            "registry": dict(registry or {}),
            "bearings": dict(bearings or {}),
        }
    }


# ── Empty cases ───────────────────────────────────────────────────


def test_no_quests_block_returns_empty():
    assert _build_active_quest_rows({}) == []


def test_no_active_quests_returns_empty():
    assert _build_active_quest_rows(_manifest()) == []


# ── Bearing prefix ───────────────────────────────────────────────


def test_active_quest_with_bearing_renders_prefix():
    m = _manifest(
        active=["q1"],
        registry={"q1": {"name": "Hunt the pots"}},
        bearings={"q1": "NE"},
    )
    rows = _build_active_quest_rows(m)
    assert rows == ["[NE] Hunt the pots"]


def test_active_quest_without_bearing_renders_pad():
    """Quests without a bearing get whitespace padding so column
    alignment with bearing-prefixed rows stays clean."""
    m = _manifest(
        active=["q1"],
        registry={"q1": {"name": "Reflect on rain"}},
        bearings={},  # no bearing for this quest
    )
    rows = _build_active_quest_rows(m)
    assert rows == ["     Reflect on rain"]


def test_mixed_bearing_and_no_bearing():
    m = _manifest(
        active=["q1", "q2"],
        registry={
            "q1": {"name": "Hunt the pots"},
            "q2": {"name": "Reflect on rain"},
        },
        bearings={"q1": "E"},  # only q1 has a bearing
    )
    rows = _build_active_quest_rows(m)
    assert rows == [
        "[E] Hunt the pots",
        "     Reflect on rain",
    ]


def test_falls_back_to_qid_when_name_missing():
    m = _manifest(
        active=["unknown_qid"],
        registry={},  # no entry
        bearings={"unknown_qid": "S"},
    )
    rows = _build_active_quest_rows(m)
    assert rows == ["[S] unknown_qid"]


# ── Overflow ──────────────────────────────────────────────────────


def test_caps_at_max_rows_with_overflow_line():
    m = _manifest(
        active=["q1", "q2", "q3", "q4", "q5"],
        registry={
            f"q{i}": {"name": f"Quest {i}"} for i in range(1, 6)
        },
        bearings={"q1": "N", "q2": "E", "q3": "S", "q4": "W", "q5": "NE"},
    )
    rows = _build_active_quest_rows(m, max_rows=3)
    assert rows == [
        "[N] Quest 1",
        "[E] Quest 2",
        "[S] Quest 3",
        "     +2 more",
    ]


def test_exact_max_rows_no_overflow_line():
    m = _manifest(
        active=["q1", "q2", "q3"],
        registry={
            "q1": {"name": "A"},
            "q2": {"name": "B"},
            "q3": {"name": "C"},
        },
        bearings={"q1": "N", "q2": "E", "q3": "S"},
    )
    rows = _build_active_quest_rows(m, max_rows=3)
    assert rows == ["[N] A", "[E] B", "[S] C"]


def test_under_max_rows_no_overflow():
    m = _manifest(
        active=["q1"],
        registry={"q1": {"name": "Solo"}},
        bearings={"q1": "W"},
    )
    rows = _build_active_quest_rows(m, max_rows=3)
    assert rows == ["[W] Solo"]


# ── Robustness ────────────────────────────────────────────────────


def test_handles_none_quests_block():
    """Manifest without `quests` key (early connect, not yet populated)."""
    assert _build_active_quest_rows({"quests": None}) == []


def test_handles_missing_registry():
    """Brain ships active without registry — defensive fallback to qid."""
    m = {"quests": {"active": ["q1"], "bearings": {}}}
    rows = _build_active_quest_rows(m)
    assert rows == ["     q1"]
