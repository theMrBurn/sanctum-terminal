"""PR 8 — telemetry tests.

vault.runs lifecycle (open on first serve, close on reset_match /
match_winner), per-rally metrics accumulation, peak tracking,
state-event emission, aggregate query helpers.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.systems import make_brain_registry as reg
from core.systems.ballistics import MotionVector
from core.systems.make_brains import ping_pong as ping_pong_brain
from core.vault import vault as Vault


@pytest.fixture(autouse=True)
def _reset_registry():
    reg._reset_for_tests()
    yield
    reg._reset_for_tests()


@pytest.fixture
def fresh_vault(tmp_path: Path):
    return Vault(db_path=tmp_path / "vault.db")


@pytest.fixture
def handler(fresh_vault):
    return ping_pong_brain.PingPongHandler(fresh_vault)


def _send_ball_out(h):
    """Drive the ball past out_of_bounds_y so on_tick resolves the rally."""
    h.ball = MotionVector(
        pos=(0.0, -2.0, 1.6),
        vel=(0.0, 0.0, 0.0),
        spin=(0.0, 0.0, 0.0),
        timestamp=0.0,
    )
    h.on_tick(1.0 / 60.0)


# ── vault.runs lifecycle ─────────────────────────────────────────────


def test_no_run_open_before_first_serve(handler, fresh_vault):
    assert handler._run_id is None
    assert fresh_vault.runs_by_instance("ping_pong") == []


def test_first_serve_opens_a_run(handler, fresh_vault):
    handler.on_serve()
    assert handler._run_id is not None
    runs = fresh_vault.runs_by_instance("ping_pong")
    assert len(runs) == 1
    assert runs[0]["profile_name"] == "vanilla"
    assert runs[0]["ended_at"] is None
    assert runs[0]["terminal_state"] is None


def test_subsequent_serves_reuse_same_run(handler, fresh_vault):
    handler.on_serve()
    rid = handler._run_id
    _send_ball_out(handler)             # rally 1 lost
    handler.on_serve()                  # rally 2
    assert handler._run_id == rid
    assert len(fresh_vault.runs_by_instance("ping_pong")) == 1


def test_reset_match_closes_run_as_aborted(handler, fresh_vault):
    handler.on_serve()
    rid = handler._run_id
    handler.reset_match()
    assert handler._run_id is None
    runs = fresh_vault.runs_by_instance("ping_pong")
    assert len(runs) == 1
    assert runs[0]["run_id"] == rid
    assert runs[0]["terminal_state"] == "aborted"
    assert runs[0]["ended_at"] is not None


def test_match_win_closes_run_as_won(handler, fresh_vault):
    """Drive a fast match to completion. Player needs to sustain the
    long rally threshold to score; we simulate that by setting
    rally_contacts directly before each out-of-bounds."""
    handler.on_serve()
    # Set threshold to 1 to make scoring fast.
    fresh_vault.profile_save(
        "ping_pong", "vanilla",
        params={**ping_pong_brain.VANILLA_PARAMS, "long_rally_threshold": 1},
    )
    # Force-resolve rallies until match ends. Each rally = 1 player point.
    while handler.match.match_winner is None:
        if handler.ball is None:
            handler.on_serve()
        handler.rally_contacts = 5      # ≥ threshold = player point
        _send_ball_out(handler)
    # Match ended → run closed
    assert handler._run_id is None
    runs = fresh_vault.runs_by_instance("ping_pong")
    assert runs[0]["terminal_state"] == "won"
    assert runs[0]["ended_at"] is not None


# ── metrics accumulation ─────────────────────────────────────────────


def test_run_metrics_capture_per_rally(handler, fresh_vault):
    handler.on_serve()
    handler.rally_contacts = 7
    _send_ball_out(handler)             # rally 1 → opp point (below default 10)
    handler.on_serve()
    handler.rally_contacts = 12
    _send_ball_out(handler)             # rally 2 → player point
    rallies = handler._run_metrics["rallies"]
    assert len(rallies) == 2
    assert rallies[0]["winner"] == "opp"
    assert rallies[0]["contacts"] == 7
    assert rallies[1]["winner"] == "player"
    assert rallies[1]["contacts"] == 12
    assert handler._run_metrics["peak_rally_length"] == 12


def test_peak_max_v_tracked_across_rallies(handler):
    handler.on_serve()
    handler._rally_max_v = 25.7         # simulate observed during tick
    handler.rally_contacts = 5
    _send_ball_out(handler)
    handler.on_serve()
    handler._rally_max_v = 12.0
    handler.rally_contacts = 5
    _send_ball_out(handler)
    assert handler._run_metrics["peak_max_v"] == 25.7


def test_in_progress_metrics_persisted_after_each_rally(handler, fresh_vault):
    handler.on_serve()
    handler.rally_contacts = 5
    _send_ball_out(handler)
    # Run is still open but metrics were persisted via _persist_run_metrics
    runs = fresh_vault.runs_by_instance("ping_pong")
    assert runs[0]["ended_at"] is None              # still in-progress
    assert len(runs[0]["metrics"]["rallies"]) == 1


# ── state events ─────────────────────────────────────────────────────


def test_first_serve_emits_make_brain_started(handler):
    handler.on_serve()
    events = handler.drain_state_events()
    kinds = [e["kind"] for e in events]
    assert "make_brain_started" in kinds
    assert "rally_started" in kinds


def test_rally_end_emits_rally_ended_and_score_changed(handler):
    handler.on_serve()
    handler.drain_state_events()         # discard serve events
    handler.rally_contacts = 12
    _send_ball_out(handler)
    events = handler.drain_state_events()
    kinds = [e["kind"] for e in events]
    assert "rally_ended" in kinds
    assert "score_changed" in kinds
    assert "peak_recorded" in kinds      # 12 > 0 = new peak


def test_drain_clears_buffer(handler):
    handler.on_serve()
    first = handler.drain_state_events()
    second = handler.drain_state_events()
    assert first != []
    assert second == []


def test_manifest_keys_carry_state_events(handler):
    handler.on_serve()
    keys = handler.manifest_keys()
    events = keys["volley_state_events"]
    assert any(e["kind"] == "rally_started" for e in events)
    # Drained — next manifest_keys returns empty
    keys2 = handler.manifest_keys()
    assert keys2["volley_state_events"] == []


# ── vault aggregate queries ──────────────────────────────────────────


def test_runs_peak_metric_returns_zero_when_no_runs(fresh_vault):
    peak, run_id = fresh_vault.runs_peak_metric("ping_pong", "peak_max_v")
    assert peak == 0.0
    assert run_id is None


def test_runs_peak_metric_finds_max_across_runs(fresh_vault, handler):
    # Run 1 — peak 25
    handler.on_serve()
    handler._rally_max_v = 25.0
    handler.rally_contacts = 5
    _send_ball_out(handler)
    handler.reset_match()                # closes run 1
    # Run 2 — peak 40
    handler.on_serve()
    handler._rally_max_v = 40.0
    handler.rally_contacts = 5
    _send_ball_out(handler)
    handler.reset_match()                # closes run 2
    peak, _ = fresh_vault.runs_peak_metric("ping_pong", "peak_max_v")
    assert peak == 40.0


def test_runs_peak_metric_filters_by_profile(fresh_vault, handler):
    handler.on_serve()
    handler._rally_max_v = 25.0
    handler.rally_contacts = 5
    _send_ball_out(handler)
    handler.reset_match()
    # Switch to tennis_sim, smaller peak
    handler.active_profile = "tennis_sim"
    handler.on_serve()
    handler._rally_max_v = 10.0
    handler.rally_contacts = 5
    _send_ball_out(handler)
    handler.reset_match()
    peak_van, _ = fresh_vault.runs_peak_metric(
        "ping_pong", "peak_max_v", profile_name="vanilla"
    )
    peak_sim, _ = fresh_vault.runs_peak_metric(
        "ping_pong", "peak_max_v", profile_name="tennis_sim"
    )
    assert peak_van == 25.0
    assert peak_sim == 10.0


def test_runs_peak_metric_skips_runs_without_metric(fresh_vault):
    """Hand-craft a run row with no peak_max_v key; query should ignore it."""
    fresh_vault.profile_save("ping_pong", "vanilla", params={})
    rid = fresh_vault.run_start("ping_pong", "vanilla")
    fresh_vault.run_end(
        "ping_pong", rid, terminal_state="aborted", metrics={"rallies": []}
    )
    peak, run_id = fresh_vault.runs_peak_metric("ping_pong", "peak_max_v")
    assert peak == 0.0
    assert run_id is None
