"""PR 1 smoke tests — make-brain scaffolding for nethack.

Validates:
  - import surface (package + handler + identity constants)
  - registry registration (idempotent)
  - vault profile bootstrap (vanilla seeded)
  - run lifecycle (start_run → end_run closes the row)
  - entry-point boot path (splash binding, no REPL)

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 1.
"""
from __future__ import annotations

import pytest

from core.systems import make_brain_registry
from core.systems.make_brains import nethack
from core.systems.make_brains.nethack import handler as nh_handler


# ----------------------------------------------------------------------
# Identity constants
# ----------------------------------------------------------------------


def test_identity_constants_match():
    """Package re-exports match handler module — no drift between the
    two declaration sites."""
    assert nethack.INSTANCE_ID       == nh_handler.INSTANCE_ID == "nethack"
    assert nethack.ENTRY_POINT       == nh_handler.ENTRY_POINT == "terminal:nethack"
    assert nethack.DEFAULT_PROFILE   == nh_handler.DEFAULT_PROFILE == "vanilla"
    assert nethack.STATE_EVENT_TYPES == nh_handler.STATE_EVENT_TYPES


def test_state_event_types_include_universal_lifecycle():
    """Every make-brain must declare the four universal lifecycle events
    so cross-instance telemetry tooling has a stable hook set."""
    assert "make_brain_started" in nethack.STATE_EVENT_TYPES
    assert "make_brain_ended"   in nethack.STATE_EVENT_TYPES
    assert "profile_loaded"     in nethack.STATE_EVENT_TYPES
    assert "peak_recorded"      in nethack.STATE_EVENT_TYPES


def test_state_event_types_include_nethack_specific():
    """V1 events the handler will emit once gameplay lands (PR 4-8)."""
    for kind in ("level_descended", "monster_killed", "item_picked_up",
                 "level_up", "player_died"):
        assert kind in nethack.STATE_EVENT_TYPES, f"missing event kind: {kind}"


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_registry():
    """Each test starts with a fresh make_brain_registry so registration
    assertions are deterministic across the file."""
    make_brain_registry._reset_for_tests()
    yield
    make_brain_registry._reset_for_tests()


def test_activate_registers_handler(tmp_path, monkeypatch):
    """activate(vault) registers a NetHackHandler under instance_id=nethack."""
    from core.vault import vault as Vault
    monkeypatch.setattr(Vault, "DEFAULT_DB_PATH", tmp_path / "vault.db",
                        raising=False)
    v = Vault(db_path=str(tmp_path / "vault.db"))
    spec = nethack.activate(v)
    assert spec.instance_id == "nethack"
    assert spec.entry_point == "terminal:nethack"
    assert spec.default_profile == "vanilla"
    assert isinstance(spec.handler, nh_handler.NetHackHandler)
    # And it's queryable through the public API.
    same = make_brain_registry.get("nethack")
    assert same is spec


def test_activate_is_idempotent(tmp_path):
    """Re-calling activate() returns the same spec, doesn't re-register."""
    from core.vault import vault as Vault
    v = Vault(db_path=str(tmp_path / "vault.db"))
    spec1 = nethack.activate(v)
    spec2 = nethack.activate(v)
    assert spec1 is spec2
    assert make_brain_registry.list_instances() == ["nethack"]


# ----------------------------------------------------------------------
# Vault profile bootstrap
# ----------------------------------------------------------------------


def test_vanilla_profile_seeded_on_first_activate(tmp_path):
    """First activate() seeds the vanilla profile in vault.profiles."""
    from core.vault import vault as Vault
    v = Vault(db_path=str(tmp_path / "vault.db"))
    assert v.profile_load("nethack", "vanilla") is None
    nethack.activate(v)
    row = v.profile_load("nethack", "vanilla")
    assert row is not None
    assert row["instance_id"] == "nethack"
    assert row["profile_name"] == "vanilla"
    params = row["params"]
    # Spot-check classic-NetHack starter values
    assert params["start_str"]    == 16
    assert params["start_hp"]     == 12
    assert params["start_ac"]     == 9
    assert params["start_weapon"] == "dagger"
    assert params["map_w"]        == 80
    assert params["map_h"]        == 24
    assert params["fov_radius"]   == 8


def test_vanilla_profile_not_overwritten_on_reactivate(tmp_path):
    """If the user has tweaked vanilla in vault.profiles, re-activating
    must not clobber it."""
    from core.vault import vault as Vault
    v = Vault(db_path=str(tmp_path / "vault.db"))
    nethack.activate(v)
    # Mutate the profile externally — simulate a console setter.
    v.profile_save("nethack", "vanilla",
                   params={**nh_handler.VANILLA_PARAMS, "start_hp": 999},
                   notes="user override")
    # Reset the registry so activate() actually re-runs (otherwise the
    # idempotence shortcut returns early).
    make_brain_registry._reset_for_tests()
    nethack.activate(v)
    row = v.profile_load("nethack", "vanilla")
    assert row["params"]["start_hp"] == 999, "user override clobbered"


# ----------------------------------------------------------------------
# Run lifecycle
# ----------------------------------------------------------------------


def test_start_run_opens_vault_row(tmp_path):
    from core.vault import vault as Vault
    v = Vault(db_path=str(tmp_path / "vault.db"))
    spec = nethack.activate(v)
    h = spec.handler
    assert h._run_id is None
    rid = h.start_run()
    assert rid is not None
    assert h._run_id == rid
    runs = v.runs_by_instance("nethack")
    assert len(runs) == 1
    assert runs[0]["run_id"] == rid
    assert runs[0]["terminal_state"] is None      # still in-progress


def test_start_run_idempotent_within_session(tmp_path):
    """Calling start_run twice in the same session returns the same id —
    PR 1 entry-point may call it on every boot."""
    from core.vault import vault as Vault
    v = Vault(db_path=str(tmp_path / "vault.db"))
    spec = nethack.activate(v)
    h = spec.handler
    rid1 = h.start_run()
    rid2 = h.start_run()
    assert rid1 == rid2


def test_end_run_closes_vault_row(tmp_path):
    from core.vault import vault as Vault
    v = Vault(db_path=str(tmp_path / "vault.db"))
    spec = nethack.activate(v)
    h = spec.handler
    h.start_run()
    h.end_run(terminal_state="quit", monsters_killed=3, depth_reached=5)
    runs = v.runs_by_instance("nethack")
    assert len(runs) == 1
    closed = runs[0]
    assert closed["terminal_state"] == "quit"
    assert closed["ended_at"] is not None
    assert closed["metrics"]["monsters_killed"] == 3
    assert closed["metrics"]["depth_reached"]   == 5
    assert h._run_id is None


# ----------------------------------------------------------------------
# State events
# ----------------------------------------------------------------------


def test_lifecycle_events_emitted(tmp_path):
    from core.vault import vault as Vault
    v = Vault(db_path=str(tmp_path / "vault.db"))
    spec = nethack.activate(v)
    h = spec.handler
    h.start_run()
    h.end_run(terminal_state="quit")
    events = h.drain_state_events()
    kinds = [e["kind"] for e in events]
    assert kinds == ["make_brain_started", "make_brain_ended"]


def test_drain_state_events_clears_buffer(tmp_path):
    from core.vault import vault as Vault
    v = Vault(db_path=str(tmp_path / "vault.db"))
    spec = nethack.activate(v)
    h = spec.handler
    h.start_run()
    assert h.drain_state_events()       # first drain returns the queued event
    assert h.drain_state_events() == [] # second drain is empty


# ----------------------------------------------------------------------
# Manifest snapshot
# ----------------------------------------------------------------------


def test_manifest_keys_shape(tmp_path):
    from core.vault import vault as Vault
    v = Vault(db_path=str(tmp_path / "vault.db"))
    spec = nethack.activate(v)
    h = spec.handler
    h.start_run()
    keys = h.manifest_keys()
    assert keys["instance_id"]    == "nethack"
    assert keys["active_profile"] == "vanilla"
    assert keys["run_id"]         is not None
    assert "run_metrics"          in keys
    assert keys["run_metrics"]["depth_reached"]   == 1
    assert keys["run_metrics"]["monsters_killed"] == 0
    assert "nethack_state_events" in keys


# ----------------------------------------------------------------------
# Entry point — splash boot path (no REPL)
# ----------------------------------------------------------------------


def test_entry_point_boot_returns_substrate_snapshot(tmp_path, monkeypatch):
    """nethack_terminal.boot() runs the wiring without invoking input().
    Verifies the entry-point binds to the same handler / spec the
    registry exposes."""
    import nethack_terminal as entry
    # Force the vault into tmp_path so the test doesn't litter data/vault.db.
    from core.vault import vault as Vault
    monkeypatch.setattr(entry, "Vault",
                        lambda: Vault(db_path=str(tmp_path / "vault.db")))
    snap = entry.boot()
    assert snap["instance_id"]     == "nethack"
    assert snap["entry_point"]     == "terminal:nethack"
    assert snap["active_profile"]  == "vanilla"
    assert snap["run_id"]          is not None
    assert snap["manifest"]["instance_id"] == "nethack"
