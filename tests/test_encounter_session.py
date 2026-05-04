"""End-to-end brain-side UAT: tile crossing → actions → orb turns → ceremony."""
from __future__ import annotations

import pytest

from core.systems.encounter_session import (
    EncounterSession, TILE_POSITIONS, TILE_CROSS_RADIUS,
)


# -- Spatial trigger ---------------------------------------------------------

def test_first_tile_crossing_triggers():
    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    result = s.on_camera(tx, ty)
    assert result is not None
    assert result["triggered"] is True
    assert result["tile_idx"] == 0
    assert s.engine.active_encounter is not None


def test_no_trigger_outside_radius():
    s = EncounterSession(seed=42)
    assert s.on_camera(999.0, 999.0) is None


def test_no_double_trigger_while_active():
    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    assert s.on_camera(tx, ty) is None


# -- Primitive composition ---------------------------------------------------

def test_session_builds_orb_from_scout_config():
    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    assert s.orb is not None
    assert s.orb.name == "watcher"
    assert s.orb.hp == 6
    assert s.orb.max_hp == 6


def test_opening_ceremony_in_snapshot_after_trigger():
    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    snap = s.snapshot()
    assert snap["active"]["ceremony"]["opening"]
    assert "watcher" in snap["active"]["ceremony"]["opening"].lower()


# -- Orb takes a turn after player action ------------------------------------

def test_orb_takes_turn_after_player_action():
    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    s.player = s.player._replace(str_save=20, dex_save=20, wil_save=20)
    s._roll = lambda size: 1   # player passes everything
    out = s.on_action("PROBE")
    assert "orb_turn" in out, "orb must act after player"
    assert out["orb_turn"]["intent"] in {
        "questioning", "revealing", "withholding", "offering", "threatening"
    }


# -- Victory via orb HP = 0 --------------------------------------------------

def test_victory_via_orb_hp_zero():
    """Orb HP 0 is still a valid resolution path in either mode — the session
    short-circuits to resolved when the orb is defeated, regardless of how it
    got there. Dialog mode never damages the orb itself, but the path is
    preserved so action-mode scouts reuse the same finalize code."""
    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    s.orb.hp = 0
    s.player = s.player._replace(str_save=20, dex_save=20, wil_save=20)
    s._roll = lambda size: 1
    out = s.on_action("PROBE")
    assert out["resolution"] == "resolved"
    assert s.engine.active_encounter is None


def test_victory_via_three_passes_still_works(monkeypatch):
    """Three passes whose stance reads the orb's posture close the encounter.
    Force the orb to hold 'wary' so PROBE (curious) always reads (+1 progress)."""
    from core.systems import encounter_config as _ec
    from core.systems import encounter_session as _es

    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    s.player = s.player._replace(str_save=20, dex_save=20, wil_save=20)
    s._roll = lambda size: 1

    def _force_wary(*_a, **_kw):
        return "questioning", _ec.get_dialog_intent("questioning")

    # Patch the name actually bound inside encounter_session's module scope.
    monkeypatch.setattr(_es, "choose_intent", _force_wary)
    # Re-queue the starting intent through the patched function so the first
    # action already faces "wary" (on_camera already ran above).
    s.orb.current_intent = _force_wary()
    results = [s.on_action("PROBE") for _ in range(3)]
    assert results[-1]["resolution"] == "resolved"


# -- Ceremony strings --------------------------------------------------------

def test_victory_ceremony_in_last_outcome():
    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    s.orb.hp = 0
    s.player = s.player._replace(str_save=20, dex_save=20, wil_save=20)
    s._roll = lambda size: 1
    s.on_action("PROBE")
    snap = s.snapshot()
    assert snap["last_outcome"]["ceremony"] == "victory"
    assert "yields" in snap["last_outcome"]["ceremony_text"].lower()


# -- Flavor templates applied ------------------------------------------------

def test_flavor_template_in_log_entry():
    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    s.player = s.player._replace(str_save=20, dex_save=20, wil_save=20)
    s._roll = lambda size: 1
    out = s.on_action("PROBE")
    # Pass-flavor for PROBE should appear in the log text
    text = out["log_entry"]["text"].lower()
    assert "question" in text or "frame" in text, \
        f"expected PROBE_pass flavor in log text, got: {text!r}"


# -- Orb intent flags affect next save ---------------------------------------

def test_disadvantage_flag_makes_next_save_harder():
    """Dialog verbs still honor disadvantage: with the flag set and rolls
    [3, 18] against WIL 10, we keep the worse (18) → fail."""
    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    s.player = s.player._replace(wil_save=10, str_save=10, dex_save=10)
    s.pending_flags = {"disadvantage_next": True}
    seq = iter([3, 18])
    def roll(size: int) -> int:
        try:
            return next(seq)
        except StopIteration:
            return 1
    s._roll = roll
    out = s.on_action("PROBE")
    assert out["save"] == "fail", "disadvantage should force failure"


# -- Portal + hub --------------------------------------------------------------

def test_portal_exit_consumes_tile_no_xp():
    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    out = s.on_portal()
    assert out["outcome"] == "portal_exit"
    assert out["xp_staged"] == 0.0
    assert 0 in s.consumed_tiles


def test_hub_arrival_consolidates_depth():
    s = EncounterSession(seed=42)
    s.player = s.player._replace(str_save=20, dex_save=20, wil_save=20)
    s._roll = lambda size: 1
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    # Brute-force victory via orb HP 0 so we don't fight the orb's turn RNG
    s.orb.hp = 0
    s.on_action("PROBE")
    assert s.engine.staged_xp > 0
    before = s.engine.depth
    s.on_hub_arrival()
    assert s.engine.depth > before
    assert s.engine.staged_xp == 0.0


# -- Snapshot ----------------------------------------------------------------

# -- Orb contact trigger (Tartarus mode) -------------------------------------

def test_orb_contact_begins_encounter():
    s = EncounterSession(seed=42)
    result = s.on_orb_contact(actor_id="watcher", advantage="neutral",
                              orb_id="orb#0")
    assert result["triggered"] is True
    assert s.orb is not None
    assert s.engine.active_encounter is not None


def test_contact_first_strike_skips_orb_first_turn():
    s = EncounterSession(seed=42)
    s.on_orb_contact(actor_id="watcher", advantage="first_strike")
    s.player = s.player._replace(str_save=20, dex_save=20, wil_save=20)
    s._roll = lambda size: 1
    out = s.on_action("PROBE")
    # Orb did NOT take its turn
    assert "orb_turn" not in out
    # Advantage consumed — next action should provoke a normal orb turn
    out2 = s.on_action("PROBE")
    assert "orb_turn" in out2


def test_contact_ambush_applies_disadvantage_to_first_save():
    s = EncounterSession(seed=42)
    s.on_orb_contact(actor_id="watcher", advantage="ambush")
    assert s.pending_flags.get("disadvantage_next") is True


def test_contact_applies_hp_bonus():
    s = EncounterSession(seed=42)
    base_hp = 6   # watcher max_hp per config
    s.on_orb_contact(actor_id="watcher", advantage="neutral", hp_bonus=2)
    assert s.orb.max_hp == base_hp + 2
    assert s.orb.hp == base_hp + 2


def test_contact_applies_negative_hp_bonus_clamped():
    s = EncounterSession(seed=42)
    # hp_bonus that would drop HP to 0 or less should clamp to 1
    s.on_orb_contact(actor_id="watcher", advantage="neutral", hp_bonus=-20)
    assert s.orb.max_hp >= 1
    assert s.orb.hp >= 1


def test_contact_while_active_rejects():
    s = EncounterSession(seed=42)
    s.on_orb_contact(actor_id="watcher", advantage="neutral")
    result = s.on_orb_contact(actor_id="watcher", advantage="neutral")
    assert result["triggered"] is False
    assert result["reason"] == "already_active"


def test_snapshot_shape():
    s = EncounterSession(seed=42)
    snap = s.snapshot()
    assert snap["active"] is None
    assert len(snap["tiles"]) == len(TILE_POSITIONS)
    assert snap["player"]["hp"] == s.player.max_hp

    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    snap = s.snapshot()
    assert snap["active"] is not None
    assert snap["active"]["orb"]["hp"] == 6
    assert snap["active"]["orb"]["max_hp"] == 6
    assert "intent_telegraph" in snap["active"]
    assert "flavor" not in snap["active"], "flavor lives on log entries, not the root"


# -- Path matching + effects -------------------------------------------------

def _resolve_with_history(monkeypatch, forced_posture: str, verbs: list[str]):
    """Helper: run an encounter to resolution with a fixed orb posture,
    then return the session for inspection. Player auto-passes."""
    from core.systems import encounter_config as _ec
    from core.systems import encounter_session as _es

    s = EncounterSession(seed=42)
    tx, ty = TILE_POSITIONS[0]
    s.on_camera(tx, ty)
    s.player = s.player._replace(str_save=20, dex_save=20, wil_save=20)
    s._roll = lambda size: 1

    def _force_posture(*_a, **_kw):
        # Find an intent whose posture matches forced_posture.
        for name, intent in _ec.load()["dialog_intents"].items():
            if intent["posture"] == forced_posture:
                return name, intent
        raise KeyError(f"no intent with posture {forced_posture!r}")

    monkeypatch.setattr(_es, "choose_intent", _force_posture)
    s.orb.current_intent = _force_posture()
    for v in verbs:
        s.on_action(v)
    return s


def test_default_path_selected_on_plain_resolution(monkeypatch):
    """Mixed reads against wary — no breaks, no triple-curious. dismiss wins.
    PROBE (curious) + YIELD (deferent) + PROBE — curious=2, deferent=1, 0 breaks."""
    s = _resolve_with_history(monkeypatch, "wary", ["PROBE", "YIELD", "PROBE"])
    assert s._last_outcome["path"] == "dismiss"
    assert "yields" in s._last_outcome["ceremony_text"].lower()


def test_bind_path_selected_on_two_breaks(monkeypatch):
    """Two RIDDLE breaks wary — bind path wins + flag set."""
    s = _resolve_with_history(monkeypatch, "wary", ["RIDDLE", "RIDDLE"])
    assert s._last_outcome["path"] == "bind"
    assert s.flags.get("watcher_bound") is True
    assert "wake" in s._last_outcome["ceremony_text"].lower()


def test_ally_path_selected_on_three_curious(monkeypatch):
    """Three PROBE (curious) reads against opening — ally path + flag."""
    s = _resolve_with_history(monkeypatch, "opening", ["PROBE", "PROBE", "PROBE"])
    assert s._last_outcome["path"] == "ally"
    assert s.flags.get("watcher_ally") is True


def test_unknown_effect_raises():
    """Typos in effect names must never silently no-op."""
    s = EncounterSession(seed=42)
    with pytest.raises(ValueError, match="unknown effect"):
        s._apply_effects([{"type": "nonsense"}])


def test_missing_required_param_raises():
    """Required params absent from spec must raise before handler runs."""
    s = EncounterSession(seed=42)
    with pytest.raises(ValueError, match="missing required param 'name'"):
        s._apply_effects([{"type": "give_item", "slot_cost": 1}])


def test_wrong_param_type_raises():
    """Type mismatches surface immediately, not as KeyError deep in handler."""
    s = EncounterSession(seed=42)
    with pytest.raises(ValueError, match="expected str, got int"):
        s._apply_effects([{"type": "give_item", "name": 42}])


def test_extra_param_raises():
    """Typos in optional param names (e.g. 'amounnt') get caught — would
    otherwise silently no-op since the handler reads spec.get(...)."""
    s = EncounterSession(seed=42)
    with pytest.raises(ValueError, match="unknown params"):
        s._apply_effects([{"type": "heal_player", "amounnt": 5}])


def test_set_flag_value_accepts_any_type():
    """set_flag.value uses object as the type — any value is valid."""
    s = EncounterSession(seed=42)
    s._apply_effects([{"type": "set_flag", "name": "a", "value": True}])
    s._apply_effects([{"type": "set_flag", "name": "b", "value": "hello"}])
    s._apply_effects([{"type": "set_flag", "name": "c", "value": 99}])
    assert s.flags == {"a": True, "b": "hello", "c": 99}


def test_set_flag_effect():
    s = EncounterSession(seed=42)
    s._apply_effects([{"type": "set_flag", "name": "foo", "value": 42}])
    assert s.flags["foo"] == 42


def test_heal_player_effect():
    s = EncounterSession(seed=42)
    s.player = s.player._replace(hp=3, max_hp=10)
    s._apply_effects([{"type": "heal_player", "amount": 5}])
    assert s.player.hp == 8


def test_give_take_item_effects():
    s = EncounterSession(seed=42)
    s._apply_effects([{"type": "give_item", "name": "ember", "slot_cost": 1}])
    assert any(it.name == "ember" for it in s.player.inventory)
    s._apply_effects([{"type": "take_item", "name": "ember"}])
    assert not any(it.name == "ember" for it in s.player.inventory)


def test_trigger_rest_effect():
    s = EncounterSession(seed=42)
    s.engine.staged_xp = 2.0
    before = s.engine.depth
    s._apply_effects([{"type": "trigger_rest"}])
    assert s.engine.depth > before
    assert s.engine.staged_xp == 0.0


def test_open_dialog_branch_sets_followup():
    s = EncounterSession(seed=42)
    s._apply_effects([{"type": "open_dialog_branch", "scout_id": "first_watcher"}])
    assert s.pending_followup == "first_watcher"


def test_followup_consumed_on_next_trigger(monkeypatch):
    """When a path schedules a followup scout, the NEXT encounter swaps
    to it. Here we swap first_watcher → first_watcher (same scout) so the
    test doesn't need a second authored scout — the mechanic is the same."""
    s = EncounterSession(seed=42)
    s.pending_followup = "first_watcher"
    s.scout_id = "placeholder"   # prove the swap overwrites

    # Trigger a new encounter via on_orb_contact (doesn't need a tile).
    result = s.on_orb_contact(actor_id="watcher", advantage="neutral")
    assert result["triggered"] is True
    assert s.scout_id == "first_watcher"
    assert s.pending_followup is None
