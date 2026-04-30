"""Persisted scenario ledger — vault.scenarios as the canonical state.

Per the J6 / async-quest-refactor design conversation: vault.scenarios
is the single source of truth for scenario lifecycle (PENDING → ACTIVE
→ COMPLETE / FAILED). This module is the thin write/transition surface;
both quest-driven mutations and any future side-load process (auto-
resolve daemon, procedural encounter spawner, ScenarioChain runner) go
through the same two functions. Same code path either way — that's
what keeps the door open for the side-load story without coupling B's
implementation to A's existence.

Scenario rows are SELF-CONTAINED: params dict carries everything a
reader needs (raw_note, head_term, kind_match, entry_id, objective for
journal-derived; whatever shape future types adopt). A reader of
vault.scenarios can act on a row without ever consulting the Quest
that may or may not be tracking it. Quest references scenario_id;
scenario does NOT reference quest_id. One-way dependency.

Scope:
- create_pending(vault, type, params, provenance_hash) -> sid | None
- transition(vault, sid, new_state, *, state_events=None) -> bool

Both are general. Journal-specific helpers (deterministic hash from
entry_id + raw_note) live alongside the journal callers — see
core/systems/quests/from_journal.py.

Out of scope: scheduling, win-condition evaluation, encounter spawn.
The runtime engine (quest_tick, brain main loop, future side-load
process) is the consumer; this module just owns the persistence
mechanics + the StateEvent emission that a consumer can subscribe to.
"""
from __future__ import annotations

import hashlib
import uuid
from typing import Any


# Scenario lifecycle states. Mirrors core/systems/scenario_engine.py
# ScenarioState enum values; kept as plain strings here because vault
# stores them as strings anyway (no Python enum round-trip needed).
PENDING  = "PENDING"
ACTIVE   = "ACTIVE"
COMPLETE = "COMPLETE"
FAILED   = "FAILED"

VALID_STATES = {PENDING, ACTIVE, COMPLETE, FAILED}


def journal_provenance_hash(entry_id: int, raw_note: str) -> str:
    """Deterministic provenance hash for a journal-derived scenario.
    SHA256 of "{entry_id}:{raw_note}", first 16 chars. Stable across
    boots — boot replay re-derives the same hash for the same entry,
    which is what write_scenario_if_absent's INSERT OR IGNORE keys on.

    Diverges from ScenarioEngine._hash() which mixes time.time() into
    the payload (good for procedural encounters, useless for replay).
    Each scenario type that wants deterministic hashes computes its
    own; this is the journal flavor.
    """
    payload = f"{int(entry_id)}:{raw_note}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def create_pending(
    vault,
    scenario_type: str,
    params: dict,
    provenance_hash: str,
    *,
    objective: str = "",
) -> str | None:
    """Insert a PENDING scenario row, idempotently.

    Returns the scenario_id of the row that lives in the ledger after
    this call — either the freshly inserted id (new row) or the
    pre-existing row's id (replay path). Returns None only if the
    underlying write fails for an unexpected reason; callers can treat
    None as "skip" without crashing the loop.

    `provenance_hash` MUST be deterministic for replay-safe paths —
    journal callers should use journal_provenance_hash. Procedural
    callers may use any unique string; the contract is
    "same hash means same scenario."
    """
    fresh_id = str(uuid.uuid4())
    scenario = {
        "id":              fresh_id,
        "type":            scenario_type,
        "state":           PENDING,
        "objective":       objective,
        "provenance_hash": provenance_hash,
        "params":          dict(params or {}),
    }
    inserted = vault.write_scenario_if_absent(scenario)
    if inserted:
        return fresh_id
    # Already present — look up the canonical id by hash so the caller
    # gets the existing row's id rather than the throwaway uuid above.
    existing = vault.scenario_by_hash(provenance_hash)
    return existing["id"] if existing else None


def transition(
    vault,
    scenario_id: str,
    new_state: str,
    *,
    state_events: Any = None,
    register: str = "loop",
) -> bool:
    """Move a scenario to a new state. Returns True if the transition
    landed (row existed and state wrote), False if the scenario_id is
    unknown.

    On a successful transition, emits a `scenario_state_changed`
    StateEvent into the supplied buffer (when provided). The event
    carries `from`, `to`, `scenario_id`, `type`. This is the
    observability surface a future side-load process subscribes to —
    same primitive the manifest already streams to clients.

    The transition is permissive — caller is responsible for the
    PENDING→ACTIVE→COMPLETE/FAILED ordering. SQL doesn't enforce a
    state machine; either the brain enforces it (today) or a richer
    helper does (later).
    """
    if new_state not in VALID_STATES:
        raise ValueError(
            f"unknown scenario state {new_state!r}; "
            f"expected one of {sorted(VALID_STATES)}"
        )
    existing = vault.scenario_by_id(scenario_id)
    if existing is None:
        return False
    old_state = existing.get("state", PENDING)
    if old_state == new_state:
        # No-op — idempotent. Don't emit a noise event for replays
        # writing the same state back.
        return True
    vault.update_scenario_state(scenario_id, new_state)
    if state_events is not None:
        try:
            state_events.emit(
                "scenario_state_changed",
                f"SCENARIO {old_state} → {new_state}",
                f"{existing.get('type', '?')}: {scenario_id[:8]}",
                register,
            )
        except Exception:
            # Never let an event-bus glitch kill a state write.
            pass
    return True
