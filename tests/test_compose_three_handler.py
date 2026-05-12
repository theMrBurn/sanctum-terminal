"""compose_three make-brain handler — round-trip + lifecycle.

Per `.claude/feature/feat_creature-engagement.md` PR 2 T2:
- handler init seeds the default profile in vault.profiles
- registration round-trips through make_brain_registry
- begin → place → commit happy path returns "win"
- AC failure path returns "retry" until attempts exhausted
- abort emits engagement_aborted; end clears session
- pool size respects max_pool_size cap
- rule_args override profile defaults per-engagement
"""
from __future__ import annotations

import random
from pathlib import Path

import pytest

from core.systems import make_brain_registry
from core.systems.make_brains import compose_three
from core.systems.reflective import definitions as reflective_defs
from core.vault import vault as Vault


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test starts with a clean make_brain_registry."""
    make_brain_registry._reset_for_tests()
    yield
    make_brain_registry._reset_for_tests()


@pytest.fixture(autouse=True)
def _ensure_magnet_pool_loaded():
    """compose_three depends on the reflective magnets pool. Auto-load
    once so tests don't see an empty pool."""
    reflective_defs.load_magnets_from_json()


@pytest.fixture
def vault_with_handler(tmp_path: Path):
    db = tmp_path / "vault.db"
    v = Vault(db_path=db)
    handler = compose_three.ComposeThreeHandler(v)
    return v, handler


# ── Init + profile seeding ────────────────────────────────────────────


def test_init_seeds_default_profile(vault_with_handler):
    v, _ = vault_with_handler
    row = v.profile_load(compose_three.INSTANCE_ID, compose_three.DEFAULT_PROFILE)
    assert row is not None
    assert row["params"]["target_count"] == 3
    assert row["params"]["max_attempts"] == 3


def test_init_does_not_duplicate_profile_on_second_handler(tmp_path: Path):
    """Two handler inits on the same vault must not duplicate the row."""
    v = Vault(db_path=tmp_path / "vault.db")
    compose_three.ComposeThreeHandler(v)
    compose_three.ComposeThreeHandler(v)
    profiles = v.profile_list(compose_three.INSTANCE_ID)
    assert len(profiles) == 1


# ── Registration ──────────────────────────────────────────────────────


def test_activate_registers_handler(tmp_path: Path):
    v = Vault(db_path=tmp_path / "vault.db")
    spec = compose_three.activate(v)
    assert spec.instance_id == "compose_three"
    assert spec.entry_point == "creature_engagement"
    assert "engagement_won" in spec.state_event_types
    assert "compose_three" in make_brain_registry.list_instances()


def test_activate_is_idempotent(tmp_path: Path):
    v = Vault(db_path=tmp_path / "vault.db")
    spec1 = compose_three.activate(v)
    spec2 = compose_three.activate(v)
    assert spec1 is spec2


# ── Session lifecycle ─────────────────────────────────────────────────


def test_begin_opens_session_with_pool(vault_with_handler):
    _, h = vault_with_handler
    ok = h.begin("rat_001", "rat", rng=random.Random(7))
    assert ok is True
    assert h.session is not None
    assert h.session["agent_id"] == "rat_001"
    assert h.session["kind"] == "rat"
    assert h.session["target_count"] == 3
    assert h.session["composed"] == []
    assert len(h.session["pool"]) > 0


def test_begin_emits_engagement_open(vault_with_handler):
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    events = h.drain_state_events()
    assert any(e["type"] == "engagement_open" for e in events)


def test_begin_refuses_second_open_while_active(vault_with_handler):
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    second = h.begin("rat_002", "rat", rng=random.Random(7))
    assert second is False
    assert h.session["agent_id"] == "rat_001"


def test_place_magnet_appends_to_composed(vault_with_handler):
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    first_magnet = h.session["pool"][0]
    assert h.place_magnet(first_magnet) is True
    assert h.session["composed"] == [first_magnet]


def test_place_rejects_magnet_not_in_pool(vault_with_handler):
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    assert h.place_magnet("not_a_real_magnet_xyz") is False
    assert h.session["composed"] == []


def test_remove_magnet_pops_by_index(vault_with_handler):
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    pool = h.session["pool"]
    h.place_magnet(pool[0])
    h.place_magnet(pool[1])
    assert h.remove_magnet(0) is True
    assert h.session["composed"] == [pool[1]]


def test_remove_rejects_out_of_range(vault_with_handler):
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    h.place_magnet(h.session["pool"][0])
    assert h.remove_magnet(5) is False
    assert h.remove_magnet(-1) is False


# ── Commit outcomes ───────────────────────────────────────────────────


def test_commit_win_when_target_count_reached(vault_with_handler):
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    pool = h.session["pool"]
    h.place_magnet(pool[0])
    h.place_magnet(pool[1])
    h.place_magnet(pool[2])
    assert h.commit() == "win"
    assert h.session["outcome"] == "win"


def test_commit_retry_when_below_target_with_attempts_remaining(vault_with_handler):
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    pool = h.session["pool"]
    h.place_magnet(pool[0])
    assert h.commit() == "retry"
    # Retry clears composition so the player rebuilds.
    assert h.session["composed"] == []
    assert h.session["attempt_count"] == 1


def test_commit_exhausted_when_attempts_run_out(vault_with_handler):
    _, h = vault_with_handler
    h.begin(
        "rat_001", "rat",
        rule_args={"max_attempts": 2},
        rng=random.Random(7),
    )
    pool = h.session["pool"]
    h.place_magnet(pool[0])
    assert h.commit() == "retry"
    h.place_magnet(pool[0])
    assert h.commit() == "exhausted"
    assert h.session["outcome"] == "exhausted"


def test_commit_returns_inactive_with_no_session(vault_with_handler):
    _, h = vault_with_handler
    assert h.commit() == "inactive"


# ── End / abort ───────────────────────────────────────────────────────


def test_end_emits_won_on_win(vault_with_handler):
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    pool = h.session["pool"]
    for m in pool[:3]:
        h.place_magnet(m)
    h.commit()
    h.drain_state_events()  # drop open
    closed = h.end()
    assert closed["outcome"] == "win"
    assert h.session is None
    events = h.drain_state_events()
    assert any(e["type"] == "engagement_won" for e in events)


def test_end_emits_lost_when_no_outcome(vault_with_handler):
    """End without commit reaching a terminal outcome emits engagement_lost."""
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    h.drain_state_events()
    h.end()
    events = h.drain_state_events()
    assert any(e["type"] == "engagement_lost" for e in events)


def test_abort_marks_aborted_and_emits_event(vault_with_handler):
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    h.drain_state_events()
    assert h.abort() is True
    assert h.session["outcome"] == "aborted"
    events = h.drain_state_events()
    assert any(e["type"] == "engagement_aborted" for e in events)


def test_abort_then_end_does_not_double_emit(vault_with_handler):
    _, h = vault_with_handler
    h.begin("rat_001", "rat", rng=random.Random(7))
    h.drain_state_events()
    h.abort()
    h.end()
    events = h.drain_state_events()
    aborted_events = [e for e in events if e["type"] == "engagement_aborted"]
    assert len(aborted_events) == 1


def test_end_returns_none_with_no_session(vault_with_handler):
    _, h = vault_with_handler
    assert h.end() is None


# ── Rule-args overrides ───────────────────────────────────────────────


def test_rule_args_override_target_count(vault_with_handler):
    _, h = vault_with_handler
    h.begin(
        "rat_001", "rat",
        rule_args={"target_count": 5},
        rng=random.Random(7),
    )
    assert h.session["target_count"] == 5


def test_max_pool_size_caps_pool(vault_with_handler):
    _, h = vault_with_handler
    h.begin(
        "rat_001", "rat",
        rule_args={"max_pool_size": 4},
        rng=random.Random(7),
    )
    assert len(h.session["pool"]) == 4


def test_pool_label_stored_for_future_per_pool_routing(vault_with_handler):
    _, h = vault_with_handler
    h.begin(
        "rat_001", "rat",
        rule_args={"pool": "rat_postures"},
        rng=random.Random(7),
    )
    assert h.session["pool_label"] == "rat_postures"
