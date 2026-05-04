"""Paddle strike — solver math + handler hitbox + brain command tests.

T5 of `feat_make-brain-ping-pong` PR 5. Pins:

  - BallisticsSolver.paddle_strike reflection math
    v_n' = (1+e)·v_paddle_n − e·v_ball_n
    v_t' = v_ball_t + friction·v_paddle_t
  - PingPongHandler.on_strike hitbox gate (returns None on miss)
  - handle_volley_strike command — payload validation + hit/miss ack
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.systems import make_brain_registry as reg
from core.systems.ballistics import (
    BallisticsParams, BallisticsSolver, MotionVector, chamber_walls,
)
from core.systems.make_brain_commands import handle_volley_strike
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


VANILLA = {
    "ball_mass":         1.0,
    "ball_radius":       0.15,
    "ball_drag_coeff":   0.0,
    "ball_magnus_coeff": 0.0,
    "gravity_y":         0.0,
    "wall_restitution":  1.0,
}

CHAMBER_12 = {"size": [12.0, 12.0, 12.0], "origin": [0.0, 0.0, 0.0]}


def _solver(profile=VANILLA):
    walls = chamber_walls(tuple(CHAMBER_12["size"]), tuple(CHAMBER_12["origin"]))
    return BallisticsSolver(BallisticsParams.from_profile(profile), walls)


def _ball(pos=(0.0, 0.0, 1.6), vel=(0.0, 0.0, 0.0)) -> MotionVector:
    return MotionVector(pos=pos, vel=vel, spin=(0.0, 0.0, 0.0), timestamp=0.0)


# ── Solver: paddle_strike math ────────────────────────────────────────


def test_paddle_strike_with_zero_paddle_vel_e1_inverts_normal():
    """e=1, paddle stationary → v_n' = -v_n. Pure elastic bounce."""
    s = _solver()
    ball = _ball(vel=(0.0, -5.0, 0.0))             # ball coming at +y normal
    new, contact = s.paddle_strike(
        ball,
        paddle_pos      = (0.0, 0.0, 1.6),
        paddle_normal   = (0.0,  1.0, 0.0),         # paddle face pointing +y
        paddle_velocity = (0.0,  0.0, 0.0),
        coupling=1.0, friction=1.0,
    )
    assert new.vel == (0.0, 5.0, 0.0)
    assert contact.contact_kind == "paddle_strike"


def test_paddle_strike_transfers_paddle_velocity_into_ball():
    """Paddle moving +y at 10 m/s, e=1, stationary ball → ball pushed
    forward at 2·v_paddle_n = 20 m/s along normal."""
    s = _solver()
    ball = _ball(vel=(0.0, 0.0, 0.0))
    new, _ = s.paddle_strike(
        ball,
        paddle_pos      = (0.0, 0.0, 1.6),
        paddle_normal   = (0.0,  1.0, 0.0),
        paddle_velocity = (0.0, 10.0, 0.0),
        coupling=1.0, friction=1.0,
    )
    assert abs(new.vel[1] - 20.0) < 1e-6
    assert abs(new.vel[0]) < 1e-9
    assert abs(new.vel[2]) < 1e-9


def test_paddle_strike_e_zero_dampens():
    """e=0 → ball loses normal-component velocity entirely (clay)."""
    s = _solver()
    ball = _ball(vel=(0.0, -5.0, 0.0))
    new, _ = s.paddle_strike(
        ball,
        paddle_pos      = (0.0, 0.0, 1.6),
        paddle_normal   = (0.0,  1.0, 0.0),
        paddle_velocity = (0.0,  0.0, 0.0),
        coupling=0.0, friction=0.0,
    )
    # v_n' = (1+0)*0 - 0*(-5) = 0
    assert abs(new.vel[1]) < 1e-9


def test_paddle_strike_tangential_picks_up_paddle_tangential():
    """friction=1, paddle moves tangentially +x → ball gains +x tangential."""
    s = _solver()
    ball = _ball(vel=(0.0, -5.0, 0.0))
    new, _ = s.paddle_strike(
        ball,
        paddle_pos      = (0.0, 0.0, 1.6),
        paddle_normal   = (0.0,  1.0, 0.0),
        paddle_velocity = (3.0,  0.0, 0.0),     # purely tangential
        coupling=1.0, friction=1.0,
    )
    # Normal: v_n' = (1+1)*0 - 1*(-5) = 5 (ball reverses)
    # Tangential: v_t' = (0,*,0) + 1·(3,0,0) = (3,0,0)
    assert abs(new.vel[0] - 3.0) < 1e-6
    assert abs(new.vel[1] - 5.0) < 1e-6


def test_paddle_strike_friction_zero_no_tangential_transfer():
    s = _solver()
    ball = _ball(vel=(0.0, -5.0, 0.0))
    new, _ = s.paddle_strike(
        ball,
        paddle_pos      = (0.0, 0.0, 1.6),
        paddle_normal   = (0.0,  1.0, 0.0),
        paddle_velocity = (3.0,  0.0, 0.0),
        coupling=1.0, friction=0.0,
    )
    assert abs(new.vel[0]) < 1e-9                # tangential zero (preserved 0 from ball)
    assert abs(new.vel[1] - 5.0) < 1e-6


def test_paddle_strike_normalizes_input_normal():
    """Caller can pass an un-normalized normal — solver scales it."""
    s = _solver()
    ball = _ball(vel=(0.0, -5.0, 0.0))
    new, contact = s.paddle_strike(
        ball,
        paddle_pos      = (0.0, 0.0, 1.6),
        paddle_normal   = (0.0,  3.0, 0.0),     # length 3
        paddle_velocity = (0.0,  0.0, 0.0),
        coupling=1.0, friction=1.0,
    )
    # Should still produce v_n' = 5 (normalized internally)
    assert abs(new.vel[1] - 5.0) < 1e-6
    # Reported normal is unit-length
    n = contact.paddle_normal
    n_len = (n[0]**2 + n[1]**2 + n[2]**2) ** 0.5
    assert abs(n_len - 1.0) < 1e-6


def test_paddle_strike_contact_carries_incoming_and_outgoing():
    s = _solver()
    ball = _ball(vel=(0.0, -5.0, 0.0))
    _, contact = s.paddle_strike(
        ball, (0.0, 0.0, 1.6), (0.0, 1.0, 0.0), (0.0, 0.0, 0.0),
        coupling=1.0, friction=1.0,
    )
    assert contact.incoming.vel == (0.0, -5.0, 0.0)
    assert contact.outgoing.vel == (0.0,  5.0, 0.0)
    assert contact.contact_kind == "paddle_strike"
    assert contact.coupling_factor == 1.0


# ── Handler: on_strike hitbox + state update ─────────────────────────


def test_on_strike_returns_none_when_no_ball(fresh_vault):
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    out = h.on_strike((0.0, 0.0, 1.6), (0.0, 1.0, 0.0), (0.0, 5.0, 0.0))
    assert out is None


def test_on_strike_returns_none_when_ball_outside_hitbox(fresh_vault):
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    h.on_serve()                                   # ball at (0.0, 1.5, 1.6)
    # Paddle 5m away — outside default 0.6 hitbox
    out = h.on_strike((5.0, 1.5, 1.6), (0.0, -1.0, 0.0), (0.0, -5.0, 0.0))
    assert out is None
    # Ball state unchanged
    assert h.ball.vel == (0.0, 0.0, 0.0)


def test_on_strike_hits_and_updates_ball_velocity(fresh_vault):
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    h.on_serve()                                   # ball at (0.0, 1.5, 1.6)
    # Paddle right next to ball, normal pointing +y, paddle moving +y at 10 m/s
    contact = h.on_strike(
        paddle_pos      = (0.0, 1.5, 1.6),
        paddle_normal   = (0.0, 1.0, 0.0),
        paddle_velocity = (0.0, 10.0, 0.0),
    )
    assert contact is not None
    assert contact.contact_kind == "paddle_strike"
    # Vanilla coupling = 1.0; e=1, friction=1 → v_n' = 2·10 = 20 along +y
    assert abs(h.ball.vel[1] - 20.0) < 1e-6


def test_on_strike_hitbox_radius_from_profile(fresh_vault):
    """Profile's paddle_hitbox_radius gates the hit/miss decision."""
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    h.on_serve()                                   # ball at (0.0, 1.5, 1.6)
    # Save a profile with a tiny hitbox
    fresh_vault.profile_save(
        "ping_pong", "tight",
        params={**ping_pong_brain.VANILLA_PARAMS, "paddle_hitbox_radius": 0.01},
    )
    h.active_profile = "tight"
    out = h.on_strike((0.0, 1.4, 1.6), (0.0, 1.0, 0.0), (0.0, 0.0, 0.0))
    assert out is None                              # 0.1m away, hitbox 0.01 → miss


# ── handle_volley_strike command ─────────────────────────────────────


def test_handle_strike_errors_when_ping_pong_not_active(fresh_vault):
    msg = {"cmd": "volley_strike", "payload": {
        "paddle_pos":      [0.0, 0.0, 1.6],
        "paddle_normal":   [0.0, 1.0, 0.0],
        "paddle_velocity": [0.0, 0.0, 0.0],
    }}
    ack = handle_volley_strike(msg, fresh_vault)
    assert ack["ok"] is False
    assert "ping_pong" in ack["reason"]


def test_handle_strike_validates_paddle_pos_present(fresh_vault):
    ping_pong_brain.activate(fresh_vault)
    msg = {"cmd": "volley_strike", "payload": {
        "paddle_normal":   [0.0, 1.0, 0.0],
        "paddle_velocity": [0.0, 0.0, 0.0],
    }}
    ack = handle_volley_strike(msg, fresh_vault)
    assert ack["ok"] is False
    assert "paddle_pos" in ack["reason"]


def test_handle_strike_validates_paddle_normal_present(fresh_vault):
    ping_pong_brain.activate(fresh_vault)
    msg = {"cmd": "volley_strike", "payload": {
        "paddle_pos":      [0.0, 0.0, 1.6],
        "paddle_velocity": [0.0, 0.0, 0.0],
    }}
    ack = handle_volley_strike(msg, fresh_vault)
    assert ack["ok"] is False
    assert "paddle_normal" in ack["reason"]


def test_handle_strike_velocity_defaults_to_zero(fresh_vault):
    """paddle_velocity is optional — missing ⇒ (0,0,0) (poke strike)."""
    spec = ping_pong_brain.activate(fresh_vault)
    spec.handler.on_serve()                        # ball stationary at (0,1.5,1.6)
    msg = {"cmd": "volley_strike", "payload": {
        "paddle_pos":    [0.0, 1.5, 1.6],
        "paddle_normal": [0.0, 1.0, 0.0],
    }}
    ack = handle_volley_strike(msg, fresh_vault)
    # Stationary ball + stationary paddle = v_ball stays (0,0,0); ack hits
    # but the velocity transfer is zero.
    assert ack["ok"] is True
    assert ack["hit"] is True
    assert ack["ball"]["vy"] == 0.0


def test_handle_strike_miss_returns_hit_false(fresh_vault):
    spec = ping_pong_brain.activate(fresh_vault)
    spec.handler.on_serve()
    msg = {"cmd": "volley_strike", "payload": {
        "paddle_pos":      [10.0, 0.0, 0.0],       # far from ball
        "paddle_normal":   [0.0, 1.0, 0.0],
        "paddle_velocity": [0.0, 5.0, 0.0],
    }}
    ack = handle_volley_strike(msg, fresh_vault)
    assert ack["ok"] is True
    assert ack["hit"] is False


def test_handle_strike_hit_returns_ball_and_contact(fresh_vault):
    spec = ping_pong_brain.activate(fresh_vault)
    spec.handler.on_serve()                        # ball at (0.0, 1.5, 1.6)
    msg = {"cmd": "volley_strike", "payload": {
        "paddle_pos":      [0.0, 1.5, 1.6],
        "paddle_normal":   [0.0, 1.0, 0.0],
        "paddle_velocity": [0.0, 10.0, 0.0],
    }}
    ack = handle_volley_strike(msg, fresh_vault)
    assert ack["ok"] is True
    assert ack["hit"] is True
    assert "ball" in ack
    assert "contact" in ack
    assert abs(ack["ball"]["vy"] - 20.0) < 1e-6
    assert ack["contact"]["contact_kind"] == "paddle_strike"
    assert ack["contact"]["coupling_factor"] == 1.0
