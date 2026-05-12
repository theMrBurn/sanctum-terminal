"""Brain dispatch wiring for creature engagement — feat/creature-engagement PR 4.

Exercises the open/close flow with a stub world (no full BrainWorld
setup), verifying:
  - _open_engagement transitions state, dispatches to the handler,
    opens a vault row, populates world.active_engagement
  - _close_engagement closes the row, transitions back, drains handler
  - _engagement_state_manifest reflects the live handler session
  - Outcome metrics persist through close
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

# Re-importing brain_server runs heavy boot-time wiring (kind_config load,
# loaders, etc.). Importing the specific helpers is cheaper and matches
# the rest of the test suite.
import brain_server
from core.systems import game_state as gs
from core.systems import make_brain_registry
from core.systems.make_brains import compose_three
from core.vault import vault as Vault


@pytest.fixture
def fresh_vault(tmp_path: Path):
    return Vault(db_path=tmp_path / "vault.db")


@pytest.fixture
def world_at_hub():
    """Minimal stub world with the fields _open / _close touch."""
    return SimpleNamespace(
        game_state=gs.GameState.initial(),
        active_engagement=None,
    )


@pytest.fixture
def registered_handler(fresh_vault, monkeypatch):
    """Register compose_three handler against fresh_vault.

    Patches brain_server._get_vault to return our test vault so
    `engagement_open` lands in the same db the handler is wired to.
    """
    make_brain_registry._reset_for_tests()
    compose_three.activate(fresh_vault)
    monkeypatch.setattr(brain_server, "_get_vault", lambda: fresh_vault)
    yield
    make_brain_registry._reset_for_tests()


# ── Open ──────────────────────────────────────────────────────────────


def test_open_engagement_transitions_to_engagement_state(
    world_at_hub, fresh_vault, registered_handler,
):
    brain_server._open_engagement(
        world_at_hub,
        kind="rat",
        agent_id="rat_001",
        engagement_cfg={
            "engagement_type": "compose_three",
            "rule_args": {"target_count": 3, "max_attempts": 3},
        },
    )
    assert world_at_hub.game_state.state == gs.GameStateName.ENGAGEMENT


def test_open_engagement_populates_active_engagement(
    world_at_hub, fresh_vault, registered_handler,
):
    brain_server._open_engagement(
        world_at_hub,
        kind="rat",
        agent_id="rat_001",
        engagement_cfg={"engagement_type": "compose_three", "rule_args": {}},
    )
    eng = world_at_hub.active_engagement
    assert eng is not None
    assert eng["engagement_type"] == "compose_three"
    assert eng["kind"] == "rat"
    assert eng["agent_id"] == "rat_001"
    assert isinstance(eng["engagement_id"], int)
    assert eng["engagement_id"] > 0


def test_open_engagement_opens_vault_row(
    world_at_hub, fresh_vault, registered_handler,
):
    brain_server._open_engagement(
        world_at_hub,
        kind="rat",
        agent_id="rat_001",
        engagement_cfg={"engagement_type": "compose_three", "rule_args": {}},
    )
    rows = fresh_vault.engagements_by_kind("rat")
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "rat_001"
    assert rows[0]["ended_at"] is None      # still open


def test_open_engagement_unknown_type_raises(world_at_hub, registered_handler):
    with pytest.raises(LookupError):
        brain_server._open_engagement(
            world_at_hub, kind="rat", agent_id="rat_001",
            engagement_cfg={"engagement_type": "ghost_type"},
        )


# ── Manifest ──────────────────────────────────────────────────────────


def test_manifest_is_none_when_no_active_engagement():
    assert brain_server._engagement_state_manifest(None) is None


def test_manifest_reflects_handler_session(
    world_at_hub, fresh_vault, registered_handler,
):
    brain_server._open_engagement(
        world_at_hub, kind="rat", agent_id="rat_001",
        engagement_cfg={"engagement_type": "compose_three", "rule_args": {}},
    )
    payload = brain_server._engagement_state_manifest(
        world_at_hub.active_engagement)
    assert payload is not None
    assert payload["engagement_type"] == "compose_three"
    assert payload["kind"] == "rat"
    assert payload["agent_id"] == "rat_001"
    assert payload["target_count"] == 3
    assert payload["attempt_count"] == 0
    assert isinstance(payload["pool"], list)


# ── Close ─────────────────────────────────────────────────────────────


def test_close_engagement_transitions_back_to_hub(
    world_at_hub, fresh_vault, registered_handler,
):
    brain_server._open_engagement(
        world_at_hub, kind="rat", agent_id="rat_001",
        engagement_cfg={"engagement_type": "compose_three", "rule_args": {}},
    )
    brain_server._close_engagement(world_at_hub, terminal_state="won")
    assert world_at_hub.game_state.state == gs.GameStateName.HUB
    assert world_at_hub.active_engagement is None


def test_close_engagement_writes_terminal_state_to_vault(
    world_at_hub, fresh_vault, registered_handler,
):
    brain_server._open_engagement(
        world_at_hub, kind="rat", agent_id="rat_001",
        engagement_cfg={"engagement_type": "compose_three", "rule_args": {}},
    )
    brain_server._close_engagement(world_at_hub, terminal_state="won")
    rows = fresh_vault.engagements_by_kind("rat")
    assert rows[0]["terminal_state"] == "won"
    assert rows[0]["ended_at"] is not None


def test_close_engagement_is_noop_when_inactive(world_at_hub):
    """Calling close without an active engagement must not crash."""
    brain_server._close_engagement(world_at_hub, terminal_state="won")
    assert world_at_hub.active_engagement is None


def test_close_engagement_persists_handler_metrics(
    world_at_hub, fresh_vault, registered_handler,
):
    """After a win commit, close() should persist the attempt count
    + composed length on the vault row."""
    brain_server._open_engagement(
        world_at_hub, kind="rat", agent_id="rat_001",
        engagement_cfg={"engagement_type": "compose_three", "rule_args": {}},
    )
    # Drive the handler to a win via place + commit
    handler = make_brain_registry.get("compose_three").handler
    pool = handler.session["pool"]
    handler.place_magnet(pool[0])
    handler.place_magnet(pool[1])
    handler.place_magnet(pool[2])
    outcome = handler.commit()
    assert outcome == "win"
    brain_server._close_engagement(world_at_hub, terminal_state="won")
    rows = fresh_vault.engagements_by_kind("rat")
    metrics = rows[0]["metrics"]
    assert metrics.get("attempts") == 1
    assert metrics.get("composed_len") == 3
    assert metrics.get("target_count") == 3
