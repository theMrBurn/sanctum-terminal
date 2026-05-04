"""volley_chamber biome + PingPongHandler activation — PR 3 tests.

Pins the contract that:
  - volley_chamber is registered as a make-brain biome in BIOME_REGISTRY
  - PingPongHandler.activate() registers with make_brain_registry idempotently
  - First activation seeds vanilla + tennis_sim profiles in the vault
  - Handler.manifest_keys() returns the expected top-level keys
  - brain_server._make_brain_manifest_keys() returns {} for legacy biomes
    and the handler's keys when ping_pong is activated
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.vault import vault as Vault
from core.systems import make_brain_registry as reg
from core.systems.biome_data import BIOME_REGISTRY
from core.systems.make_brains import ping_pong as ping_pong_brain


@pytest.fixture(autouse=True)
def _reset_registry():
    """Each test starts with an empty make-brain registry."""
    reg._reset_for_tests()
    yield
    reg._reset_for_tests()


@pytest.fixture
def fresh_vault(tmp_path: Path):
    db = tmp_path / "vault.db"
    return Vault(db_path=db)


# ── Biome registration ────────────────────────────────────────────────


def test_volley_chamber_is_registered_in_biome_registry():
    assert "volley_chamber" in BIOME_REGISTRY
    entry = BIOME_REGISTRY["volley_chamber"]
    assert entry["make_brain_instance_id"] == "ping_pong"
    # Sanity: minimal-biome shape (mirrors workroom)
    assert entry["density"] == []
    assert entry["stamps"] == []
    assert entry["macro_stamps"] == []
    assert entry["spawn_mode"] == "legacy_landmark"


def test_volley_chamber_has_dedicated_palette_and_lights():
    entry = BIOME_REGISTRY["volley_chamber"]
    assert entry["default_light_state"] == "chamber"
    assert "chamber" in entry["light_states"]
    palette = entry["palette"]
    # Cooler than workroom's neutral tone — distinguishable
    assert palette["floor"][2] > palette["floor"][0]    # blue > red


# ── PingPongHandler ───────────────────────────────────────────────────


def test_handler_constructor_seeds_vanilla_and_tennis_sim(fresh_vault):
    assert fresh_vault.profile_load("ping_pong", "vanilla") is None
    assert fresh_vault.profile_load("ping_pong", "tennis_sim") is None

    ping_pong_brain.PingPongHandler(fresh_vault)

    vanilla = fresh_vault.profile_load("ping_pong", "vanilla")
    sim = fresh_vault.profile_load("ping_pong", "tennis_sim")
    assert vanilla is not None
    assert sim is not None
    # Vanilla = arcade defaults — gravity 0, drag 0, restitution 1.0
    assert vanilla["params"]["gravity_y"] == 0.0
    assert vanilla["params"]["ball_drag_coeff"] == 0.0
    assert vanilla["params"]["wall_restitution"] == 1.0
    # tennis_sim inherits from vanilla
    assert sim["parent_profile"] == "vanilla"
    assert sim["params"]["gravity_y"] == -9.81


def test_handler_constructor_is_idempotent_across_calls(fresh_vault):
    ping_pong_brain.PingPongHandler(fresh_vault)
    # User edits vanilla mid-session
    fresh_vault.profile_save(
        "ping_pong", "vanilla",
        params={"_target": "user override", "ball_mass": 99.0},
    )
    # Reconstructing the handler MUST NOT clobber user edits
    ping_pong_brain.PingPongHandler(fresh_vault)
    vanilla = fresh_vault.profile_load("ping_pong", "vanilla")
    assert vanilla["params"]["ball_mass"] == 99.0    # user value preserved


def test_handler_manifest_keys_shape(fresh_vault):
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    keys = h.manifest_keys()
    assert keys["instance_id"] == "ping_pong"
    assert keys["active_profile"] == "vanilla"
    chamber = keys["chamber"]
    assert chamber["size"] == [12.0, 12.0, 12.0]
    assert chamber["origin"] == [0.0, 0.0, 0.0]
    assert len(chamber["color"]) == 3


def test_handler_resolves_active_profile_via_vault(fresh_vault):
    """Resolving the handler's active_profile should yield a merged
    arcade-default param dict — proving vault round-trips the profile
    PingPongHandler seeded."""
    ping_pong_brain.PingPongHandler(fresh_vault)
    merged = fresh_vault.profile_resolve("ping_pong", "vanilla")
    assert merged["gravity_y"] == 0.0
    assert merged["ball_radius"] == 0.15
    assert merged["paddle_arm_length"] == 0.7


# ── activate() ────────────────────────────────────────────────────────


def test_activate_registers_with_make_brain_registry(fresh_vault):
    spec = ping_pong_brain.activate(fresh_vault)
    assert spec.instance_id == "ping_pong"
    assert spec.entry_point == "biome:volley_chamber"
    assert spec.default_profile == "vanilla"
    assert "make_brain_started" in spec.state_event_types
    assert "time_scale_changed" in spec.state_event_types
    assert "ball_struck" in spec.state_event_types

    # Registry now knows the instance
    assert reg.get("ping_pong").handler is spec.handler


def test_activate_is_idempotent(fresh_vault):
    spec1 = ping_pong_brain.activate(fresh_vault)
    spec2 = ping_pong_brain.activate(fresh_vault)
    assert spec1 is spec2    # second call returns the same registered spec


# ── brain_server._make_brain_manifest_keys() ──────────────────────────


def test_manifest_keys_helper_returns_empty_for_legacy_biome(fresh_vault):
    from brain_server import _make_brain_manifest_keys
    assert _make_brain_manifest_keys("cavern") == {}
    assert _make_brain_manifest_keys("outdoor") == {}
    assert _make_brain_manifest_keys("workroom") == {}


def test_manifest_keys_helper_returns_empty_when_handler_not_activated(fresh_vault):
    from brain_server import _make_brain_manifest_keys
    # volley_chamber binds the instance_id, but if activate() never ran,
    # the registry has no handler — silent fallback to {}.
    assert _make_brain_manifest_keys("volley_chamber") == {}


def test_manifest_keys_helper_returns_handler_keys_when_active(fresh_vault):
    from brain_server import _make_brain_manifest_keys
    ping_pong_brain.activate(fresh_vault)
    out = _make_brain_manifest_keys("volley_chamber")
    assert out["instance_id"] == "ping_pong"
    assert out["active_profile"] == "vanilla"
    assert out["chamber"]["size"] == [12.0, 12.0, 12.0]


# ── PR 4 — ball lifecycle on the handler ─────────────────────────────


def test_handler_starts_with_no_active_ball(fresh_vault):
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    assert h.ball is None
    keys = h.manifest_keys()
    assert keys["ball"] == {"exists": False}


def test_on_serve_spawns_stationary_ball_at_serve_offset(fresh_vault):
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    ball = h.on_serve()
    assert ball is not None
    assert ball.vel == (0.0, 0.0, 0.0)        # stationary per AC
    # serve_offset in vanilla is [0.0, 1.6, 1.5] (lateral, eye_height, forward)
    # Mapped to brain space: x=0, y=1.5 (forward), z=1.6 (up)
    assert ball.pos == (0.0, 1.5, 1.6)


def test_on_serve_ball_is_visible_in_manifest(fresh_vault):
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    h.on_serve()
    keys = h.manifest_keys()
    assert keys["ball"]["exists"] is True
    assert keys["ball"]["radius"] == 0.15
    assert keys["ball"]["vx"] == 0.0
    assert keys["ball"]["vy"] == 0.0
    assert keys["ball"]["vz"] == 0.0


def test_on_tick_with_arcade_vanilla_keeps_ball_stationary(fresh_vault):
    """Vanilla = gravity 0, drag 0, magnus 0 → stationary ball stays put."""
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    h.on_serve()
    pos_before = h.ball.pos
    for _ in range(60):
        h.on_tick(1.0 / 60.0)
    assert h.ball.pos == pos_before


def test_on_tick_with_no_ball_is_safe(fresh_vault):
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    contacts = h.on_tick(1.0 / 60.0)
    assert contacts == []
    assert h.ball is None


def test_clear_ball_removes_active_ball(fresh_vault):
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    h.on_serve()
    assert h.ball is not None
    h.clear_ball()
    assert h.ball is None
    assert h.manifest_keys()["ball"] == {"exists": False}


def test_solver_rebuilds_when_active_profile_changes(fresh_vault):
    """Switching to tennis_sim should swap in the realistic-physics
    solver — the handler caches per-profile."""
    h = ping_pong_brain.PingPongHandler(fresh_vault)
    h.on_serve()
    # Vanilla: stationary ball stays stationary
    for _ in range(10):
        h.on_tick(1.0 / 60.0)
    assert h.ball.vel == (0.0, 0.0, 0.0)
    # Switch to tennis_sim — gravity_y = -9.81 should pull the ball down
    h.active_profile = "tennis_sim"
    for _ in range(10):
        h.on_tick(1.0 / 60.0)
    assert h.ball.vel[2] < 0.0                # gained downward velocity


# ── PR 4 — volley_serve brain command ────────────────────────────────


def test_handle_volley_serve_returns_error_when_handler_not_active(fresh_vault):
    from core.systems.make_brain_commands import handle_volley_serve
    ack = handle_volley_serve({"cmd": "volley_serve"}, fresh_vault)
    assert ack["ok"] is False
    assert "ping_pong" in ack["reason"]


def test_handle_volley_serve_spawns_ball(fresh_vault):
    from core.systems.make_brain_commands import handle_volley_serve
    ping_pong_brain.activate(fresh_vault)
    ack = handle_volley_serve({"cmd": "volley_serve"}, fresh_vault)
    assert ack["ok"] is True
    assert ack["ball"]["x"] == 0.0
    assert ack["ball"]["vx"] == 0.0
    # Verify handler now has a ball
    spec = reg.get("ping_pong")
    assert spec.handler.ball is not None
