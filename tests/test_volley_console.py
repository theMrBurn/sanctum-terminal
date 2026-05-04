"""Volley console — parser/executor + handler integration tests.

T7 + T8 of `feat_make-brain-ping-pong` PR 7.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.systems import make_brain_registry as reg
from core.systems import volley_console
from core.systems.make_brains import ping_pong as ping_pong_brain
from core.systems.make_brain_commands import handle_console_exec
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


# ── help / list / load ────────────────────────────────────────────────


def test_help_lists_commands(fresh_vault, handler):
    out = volley_console.execute("help", fresh_vault, handler)
    assert any("save" in line for line in out)
    assert any("load" in line for line in out)
    assert any("ball_mass" in line for line in out)


def test_empty_input_no_output(fresh_vault, handler):
    assert volley_console.execute("", fresh_vault, handler) == []
    assert volley_console.execute("   ", fresh_vault, handler) == []
    assert volley_console.execute(None, fresh_vault, handler) == []


def test_unknown_command_error_message(fresh_vault, handler):
    out = volley_console.execute("rocket_fuel 100", fresh_vault, handler)
    assert any("unknown" in line.lower() for line in out)


def test_list_shows_seeded_profiles(fresh_vault, handler):
    out = volley_console.execute("list", fresh_vault, handler)
    text = "\n".join(out)
    assert "vanilla" in text
    assert "tennis_sim" in text


def test_load_switches_active_profile(fresh_vault, handler):
    assert handler.active_profile == "vanilla"
    out = volley_console.execute("load tennis_sim", fresh_vault, handler)
    assert any("loaded" in line for line in out)
    assert handler.active_profile == "tennis_sim"


def test_load_unknown_profile_no_change(fresh_vault, handler):
    out = volley_console.execute("load ghost", fresh_vault, handler)
    assert any("unknown" in line.lower() for line in out)
    assert handler.active_profile == "vanilla"


# ── save ──────────────────────────────────────────────────────────────


def test_save_snapshots_active_params_under_new_name(fresh_vault, handler):
    out = volley_console.execute("save my_clone", fresh_vault, handler)
    assert any("saved my_clone" in line for line in out)
    row = fresh_vault.profile_load("ping_pong", "my_clone")
    assert row is not None
    assert row["params"]["gravity_y"] == 0.0      # vanilla arcade
    # Active profile switches to the new save target so subsequent
    # tweaks land on it (matches the user's intent: snapshot + edit).
    assert handler.active_profile == "my_clone"


def test_save_with_parent_inheritance(fresh_vault, handler):
    out = volley_console.execute("save zen from vanilla", fresh_vault, handler)
    assert any("saved zen" in line for line in out)
    row = fresh_vault.profile_load("ping_pong", "zen")
    assert row["parent_profile"] == "vanilla"


def test_save_with_unknown_parent_errors(fresh_vault, handler):
    out = volley_console.execute("save x from ghost", fresh_vault, handler)
    assert any("unknown parent" in line.lower() for line in out)


def test_save_bad_form_shows_usage(fresh_vault, handler):
    out = volley_console.execute("save", fresh_vault, handler)
    assert any("usage:" in line for line in out)


# ── setters ───────────────────────────────────────────────────────────


def test_setter_updates_vault_and_response_echoes(fresh_vault, handler):
    out = volley_console.execute("ball_mass 2.5", fresh_vault, handler)
    assert any("ball_mass = 2.5" in line for line in out)
    row = fresh_vault.profile_load("ping_pong", "vanilla")
    assert row["params"]["ball_mass"] == 2.5


def test_setter_int_param(fresh_vault, handler):
    out = volley_console.execute("long_rally_threshold 25", fresh_vault, handler)
    assert any("long_rally_threshold = 25" in line for line in out)
    row = fresh_vault.profile_load("ping_pong", "vanilla")
    assert row["params"]["long_rally_threshold"] == 25
    assert isinstance(row["params"]["long_rally_threshold"], int)


def test_setter_bad_value(fresh_vault, handler):
    out = volley_console.execute("ball_mass NaN_blob", fresh_vault, handler)
    assert any("bad value" in line for line in out)


def test_setter_missing_value_shows_usage(fresh_vault, handler):
    out = volley_console.execute("ball_mass", fresh_vault, handler)
    assert any("usage:" in line for line in out)


def test_setter_invalidates_solver_cache(fresh_vault, handler):
    """A console setter should make the next on_tick observe new params."""
    handler.on_serve()
    handler._ensure_solver()                    # build the cache
    cached = handler._solver
    volley_console.execute("gravity_y -9.81", fresh_vault, handler)
    handler._ensure_solver()
    assert handler._solver is not cached         # rebuilt


# ── handle_console_exec dispatch ──────────────────────────────────────


def test_dispatch_errors_when_handler_inactive(fresh_vault):
    msg = {"cmd": "console_exec", "payload": {"line": "list"}}
    ack = handle_console_exec(msg, fresh_vault)
    assert ack["ok"] is False
    assert "ping_pong" in ack["reason"]


def test_dispatch_routes_to_parser(fresh_vault):
    ping_pong_brain.activate(fresh_vault)
    msg = {"cmd": "console_exec", "payload": {"line": "list"}}
    ack = handle_console_exec(msg, fresh_vault)
    assert ack["ok"] is True
    assert any("vanilla" in line for line in ack["output"])


def test_dispatch_validates_line_is_string(fresh_vault):
    ping_pong_brain.activate(fresh_vault)
    ack = handle_console_exec({"cmd": "console_exec", "payload": {}}, fresh_vault)
    assert ack["ok"] is False
    assert "line" in ack["reason"]


def test_dispatch_setter_round_trip(fresh_vault):
    spec = ping_pong_brain.activate(fresh_vault)
    spec.handler.on_serve()
    msg = {"cmd": "console_exec", "payload": {"line": "gravity_y -9.81"}}
    ack = handle_console_exec(msg, fresh_vault)
    assert ack["ok"] is True
    # Solver rebuilds on next call — gravity drops the ball
    spec.handler.on_tick(0.5, substeps=8)
    assert spec.handler.ball is not None
    assert spec.handler.ball.vel[2] < 0.0
