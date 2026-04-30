"""Persisted scenario ledger — vault.scenarios as canonical state.

Per the J6 / async-quest-refactor design conversation. Validates the
generic surface (create_pending, transition) used by both the
journal-quest bridge today AND any future side-load process (auto-
resolve daemon, encounter spawner, ScenarioChain runner). The
journal-specific deterministic hash is exercised here too.

Includes a proof-of-decoupling: transition() works on a scenario row
that has NO matching Quest in the runtime registry. The persisted
ledger is independent of the in-memory quest substrate.
"""
from __future__ import annotations

import pytest

from core.systems import scenario_ledger
from core.systems.state_events import StateEventBuffer
from core.vault import vault as Vault


# ── Fixtures ───────────────────────────────────────────────────────


@pytest.fixture
def isolated_vault(tmp_path):
    """Fresh vault.db per test — schema initialized, empty ledger."""
    return Vault(db_path=tmp_path / "vault.db")


# ── Deterministic provenance hash ──────────────────────────────────


def test_journal_provenance_hash_is_deterministic():
    h1 = scenario_ledger.journal_provenance_hash(7, "Lost my keys.")
    h2 = scenario_ledger.journal_provenance_hash(7, "Lost my keys.")
    assert h1 == h2


def test_journal_provenance_hash_distinguishes_entries():
    h_keys = scenario_ledger.journal_provenance_hash(7, "Lost my keys.")
    h_phone = scenario_ledger.journal_provenance_hash(7, "Lost my phone.")
    assert h_keys != h_phone


def test_journal_provenance_hash_distinguishes_entry_ids():
    h7 = scenario_ledger.journal_provenance_hash(7, "Lost my keys.")
    h8 = scenario_ledger.journal_provenance_hash(8, "Lost my keys.")
    assert h7 != h8


def test_journal_provenance_hash_length():
    h = scenario_ledger.journal_provenance_hash(1, "x")
    assert len(h) == 16


# ── create_pending ──────────────────────────────────────────────────


def test_create_pending_inserts_row(isolated_vault):
    prov = scenario_ledger.journal_provenance_hash(1, "raw note")
    sid = scenario_ledger.create_pending(
        isolated_vault, "journal",
        params={"raw_note": "raw note", "head_term": "raw"},
        provenance_hash=prov,
        objective="raw note",
    )
    assert sid is not None
    row = isolated_vault.scenario_by_id(sid)
    assert row is not None
    assert row["state"] == "PENDING"
    assert row["type"] == "journal"
    assert row["objective"] == "raw note"
    assert row["params"] == {"raw_note": "raw note", "head_term": "raw"}


def test_create_pending_is_idempotent(isolated_vault):
    """Same provenance hash → same row, no duplicate insert. Boot
    replay depends on this."""
    prov = scenario_ledger.journal_provenance_hash(1, "raw note")
    sid_a = scenario_ledger.create_pending(
        isolated_vault, "journal", {"raw_note": "raw note"}, prov)
    sid_b = scenario_ledger.create_pending(
        isolated_vault, "journal", {"raw_note": "raw note"}, prov)
    assert sid_a == sid_b
    rows = isolated_vault.scenarios_by_state("PENDING")
    assert len(rows) == 1


def test_create_pending_different_hashes_yield_different_rows(isolated_vault):
    sid_a = scenario_ledger.create_pending(
        isolated_vault, "journal", {"x": 1}, "deadbeef00000000")
    sid_b = scenario_ledger.create_pending(
        isolated_vault, "journal", {"x": 2}, "feedface00000000")
    assert sid_a != sid_b
    assert len(isolated_vault.scenarios_by_state("PENDING")) == 2


# ── transition ──────────────────────────────────────────────────────


def test_transition_pending_to_active(isolated_vault):
    sid = scenario_ledger.create_pending(
        isolated_vault, "journal", {}, "abc123abc1230000")
    ok = scenario_ledger.transition(
        isolated_vault, sid, scenario_ledger.ACTIVE)
    assert ok is True
    assert isolated_vault.scenario_by_id(sid)["state"] == "ACTIVE"


def test_transition_unknown_id_returns_false(isolated_vault):
    ok = scenario_ledger.transition(
        isolated_vault, "no-such-id", scenario_ledger.COMPLETE)
    assert ok is False


def test_transition_idempotent_no_event_on_same_state(isolated_vault):
    sid = scenario_ledger.create_pending(
        isolated_vault, "journal", {}, "samestate0000000")
    buf = StateEventBuffer()
    # First transition emits an event. Second (same state) is a no-op.
    scenario_ledger.transition(
        isolated_vault, sid, scenario_ledger.ACTIVE, state_events=buf)
    count_after_first = len(buf.all())
    scenario_ledger.transition(
        isolated_vault, sid, scenario_ledger.ACTIVE, state_events=buf)
    count_after_second = len(buf.all())
    assert count_after_first == 1
    assert count_after_second == 1  # no new event


def test_transition_emits_state_event(isolated_vault):
    sid = scenario_ledger.create_pending(
        isolated_vault, "journal", {}, "evt0000000000000")
    buf = StateEventBuffer()
    scenario_ledger.transition(
        isolated_vault, sid, scenario_ledger.COMPLETE, state_events=buf)
    events = buf.all()
    assert len(events) == 1
    assert events[0].kind == "scenario_state_changed"
    assert "PENDING" in events[0].label
    assert "COMPLETE" in events[0].label


def test_transition_rejects_unknown_state(isolated_vault):
    sid = scenario_ledger.create_pending(
        isolated_vault, "journal", {}, "rejstate00000000")
    with pytest.raises(ValueError):
        scenario_ledger.transition(isolated_vault, sid, "BROKEN")


# ── Decoupling proof: scenarios live without Quests ────────────────


def test_transition_works_without_a_quest_counterpart(isolated_vault):
    """Critical decoupling test: vault.scenarios is the source of truth.
    A scenario can be created and transitioned without any matching
    Quest existing in the runtime registry. This is what lets a future
    side-load process (auto-resolve daemon, encounter spawner) drive
    scenario state without touching the quest substrate."""
    sid = scenario_ledger.create_pending(
        isolated_vault,
        "fetch",  # not journal — no Quest exists for this anywhere
        params={"target_id": "river_stone_01"},
        provenance_hash="standalone0000000",
    )
    assert sid is not None
    # Transition through the full lifecycle — no Quest in sight.
    assert scenario_ledger.transition(
        isolated_vault, sid, scenario_ledger.ACTIVE) is True
    assert scenario_ledger.transition(
        isolated_vault, sid, scenario_ledger.COMPLETE) is True
    final = isolated_vault.scenario_by_id(sid)
    assert final["state"] == "COMPLETE"
    assert final["type"] == "fetch"
