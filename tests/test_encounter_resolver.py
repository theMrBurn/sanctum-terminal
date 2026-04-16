"""Tests for encounter_resolver — verb → d20 save → outcome."""
from __future__ import annotations

import pytest

from core.systems import encounter_resolver as er
from core.systems.encounter_engine import EncounterEngine
from core.systems.fingerprint_engine import FingerprintEngine
from core.systems.player_state import PlayerState


@pytest.fixture
def primed_fingerprint():
    fp = FingerprintEngine()
    for _ in range(5):
        fp.record("observation_time", 0.9)
        fp.record("precision_score", 0.9)
    return fp


@pytest.fixture
def engine(primed_fingerprint):
    e = EncounterEngine(
        fingerprint=primed_fingerprint,
        ghost_blend={"SEEKER": 1.0},
        age=45,
    )
    assert e.begin(dict(er.WATCHER)) is True, \
        "Watcher must resonate with primed fingerprint"
    return e


@pytest.fixture
def player():
    # Max out saves so forced-pass rolls succeed; we control rng per test.
    p = PlayerState.new(name="T", seed=0, max_hp=10)
    return p._replace(str_save=20, dex_save=20, wil_save=20)


def _rng_pass():
    # d20 roll of 1 always passes (roll ≤ stat)
    return lambda size: 1


def _rng_fail():
    # d20 roll of 20 against a 20 succeeds — force 21 via stat override elsewhere
    # but for stat=20 even a 20 passes. Tests that want fails lower stat to 1.
    return lambda size: size   # max roll


# -- Verb table -------------------------------------------------------------

def test_think_pass_increments_net(engine, player):
    p2, out = er.resolve_action(engine, player, "THINK", _rng_pass())
    assert out["save"] == "pass"
    assert out["net_passes"] == 1
    assert out["hp_delta"] == 0
    assert p2.hp == player.hp


def test_think_fail_costs_hp(engine):
    p = PlayerState.new(seed=0, max_hp=10)._replace(wil_save=1, str_save=1, dex_save=1)
    p2, out = er.resolve_action(engine, p, "THINK", _rng_fail())
    assert out["save"] == "fail"
    assert out["net_passes"] == 0
    assert p2.hp == p.hp - 1


def test_act_fail_rolls_d4(engine):
    p = PlayerState.new(seed=0, max_hp=10)._replace(str_save=1, wil_save=1, dex_save=1)
    # rng(20)=20 fails save; next rng(4) for damage returns min of (4,20)=4
    seq = iter([20, 4])
    rng = lambda size: next(seq)
    p2, out = er.resolve_action(engine, p, "ACT", rng)
    assert out["save"] == "fail"
    assert p2.hp == p.hp - 4


def test_defend_no_roll(engine, player):
    p2, out = er.resolve_action(engine, player, "DEFEND", lambda s: 99)
    assert out["save"] is None
    assert out["net_passes"] == 0
    assert p2.hp == player.hp


def test_observe_fail_safe(engine):
    p = PlayerState.new(seed=0, max_hp=10)._replace(wil_save=1, str_save=1, dex_save=1)
    p2, out = er.resolve_action(engine, p, "OBSERVE", _rng_fail())
    assert out["save"] == "fail"
    assert p2.hp == p.hp, "OBSERVE fail never costs HP"


def test_unknown_verb_raises(engine, player):
    with pytest.raises(ValueError):
        er.resolve_action(engine, player, "YEET", _rng_pass())


def test_no_active_encounter_raises(primed_fingerprint, player):
    e = EncounterEngine(primed_fingerprint, {"SEEKER": 1.0}, age=45)
    with pytest.raises(RuntimeError):
        er.resolve_action(e, player, "THINK", _rng_pass())


# -- Resolution flow --------------------------------------------------------

def test_three_passes_resolve(engine, player):
    p = player
    statuses = []
    for _ in range(3):
        p, out = er.resolve_action(engine, p, "THINK", _rng_pass())
        statuses.append(out["resolution"])
    assert statuses == ["pending", "pending", "resolved"]
    assert out["net_passes"] == er.RESOLUTION_THRESHOLD


def test_hp_zero_marks_defeated(engine):
    p = PlayerState.new(seed=0, max_hp=1)._replace(
        str_save=1, dex_save=1, wil_save=1)
    # Force fail then d4=4 damage → HP 1 - 4 = 0
    seq = iter([20, 4])
    rng = lambda s: next(seq)
    p2, out = er.resolve_action(engine, p, "ACT", rng)
    assert out["resolution"] == "defeated"
    assert p2.hp == 0


# -- Engine integration -----------------------------------------------------

def test_resolve_outcome_tag_scales_xp(engine, player):
    p = player
    for _ in range(3):
        p, _ = er.resolve_action(engine, p, "THINK", _rng_pass())
    resolved = engine.resolve(outcome="resolved")
    assert resolved["outcome"] == "resolved"
    assert resolved["xp_staged"] > 0


def test_fled_outcome_stages_partial_xp(engine, player):
    _, _ = er.resolve_action(engine, player, "THINK", _rng_pass())
    r_full = engine.resonance(er.WATCHER["tags"])

    out = engine.resolve(outcome="fled")
    assert out["outcome"] == "fled"
    # fled multiplier is 0.25
    assert out["xp_staged"] == pytest.approx(1.0 * r_full * 0.25, rel=1e-6)


def test_defeated_outcome_stages_no_xp(engine, player):
    _, _ = er.resolve_action(engine, player, "THINK", _rng_pass())
    out = engine.resolve(outcome="defeated")
    assert out["xp_staged"] == 0.0


def test_consolidate_shifts_depth(engine, player):
    p = player
    for _ in range(3):
        p, _ = er.resolve_action(engine, p, "THINK", _rng_pass())
    engine.resolve(outcome="resolved")
    before = engine.depth
    result = engine.consolidate(reason="rest")
    assert engine.depth > before
    assert result["xp_consumed"] > 0
    assert engine.staged_xp == 0.0


# -- Watcher catalog --------------------------------------------------------

def test_watcher_resonates_with_primed_monk(primed_fingerprint):
    e = EncounterEngine(primed_fingerprint, {"SEEKER": 1.0}, age=45)
    r = e.resonance(er.WATCHER["tags"])
    assert r > 0.45, f"Watcher must clear threshold for UAT; got {r}"


def test_defeat_does_not_set_cooldown():
    """DQ rule: losing should let the player re-engage immediately."""
    from core.systems.fingerprint_engine import FingerprintEngine
    fp = FingerprintEngine()
    for _ in range(5):
        fp.record("observation_time", 0.9)
        fp.record("precision_score", 0.9)
    e = EncounterEngine(fp, {"SEEKER": 1.0}, age=45)
    e.begin(dict(er.WATCHER))
    e.resolve(outcome="defeated")
    assert not e.on_cooldown, "defeat must not lock future encounters"


def test_resolved_sets_cooldown():
    from core.systems.fingerprint_engine import FingerprintEngine
    fp = FingerprintEngine()
    for _ in range(5):
        fp.record("observation_time", 0.9)
        fp.record("precision_score", 0.9)
    e = EncounterEngine(fp, {"SEEKER": 1.0}, age=45)
    e.begin(dict(er.WATCHER))
    e.resolve(outcome="resolved")
    assert e.on_cooldown, "resolved encounters trigger cooldown"


def test_cooldown_ticks_down():
    from core.systems.fingerprint_engine import FingerprintEngine
    from core.systems.encounter_engine import ENCOUNTER_COOLDOWN
    fp = FingerprintEngine()
    for _ in range(5):
        fp.record("observation_time", 0.9)
        fp.record("precision_score", 0.9)
    e = EncounterEngine(fp, {"SEEKER": 1.0}, age=45)
    e.begin(dict(er.WATCHER))
    e.resolve(outcome="resolved")
    assert e.on_cooldown
    # Tick past the full cooldown — must unlock.
    e.tick_cooldown(ENCOUNTER_COOLDOWN + 0.1)
    assert not e.on_cooldown


def test_watcher_silent_for_cold_monk():
    fp = FingerprintEngine()   # all zeros
    e = EncounterEngine(fp, {"SEEKER": 1.0}, age=45)
    assert e.begin(dict(er.WATCHER)) is False


# -- Dialog resolver --------------------------------------------------------

def test_dialog_pass_with_reads_match_grants_one(engine, player):
    # PROBE (curious) reads "wary" → +1 progress on pass
    _, out = er.resolve_dialog_action(engine, player, "PROBE", "wary",
                                      _rng_pass())
    assert out["save"] == "pass"
    assert out["stance_match"] == "reads"
    assert out["progress_delta"] == 1
    assert out["net_passes"] == 1
    assert out["hp_delta"] == 0


def test_dialog_pass_with_breaks_on_match_grants_two(engine, player):
    # RIDDLE (cryptic) breaks "wary" → +2 progress on pass
    _, out = er.resolve_dialog_action(engine, player, "RIDDLE", "wary",
                                      _rng_pass())
    assert out["save"] == "pass"
    assert out["stance_match"] == "breaks"
    assert out["progress_delta"] == 2
    assert out["net_passes"] == 2


def test_dialog_pass_with_no_stance_match_grants_zero(engine, player):
    # PRESS (aggressive) neither reads nor breaks "wary" → 0 progress
    _, out = er.resolve_dialog_action(engine, player, "PRESS", "wary",
                                      _rng_pass())
    assert out["save"] == "pass"
    assert out["stance_match"] == "miss"
    assert out["progress_delta"] == 0
    assert out["net_passes"] == 0


def test_dialog_fail_grants_no_progress_no_damage(engine):
    p = PlayerState.new(seed=0, max_hp=10)._replace(
        wil_save=1, str_save=1, dex_save=1)
    _, out = er.resolve_dialog_action(engine, p, "PROBE", "wary", _rng_fail())
    assert out["save"] == "fail"
    assert out["progress_delta"] == 0
    assert out["net_passes"] == 0
    assert out["hp_delta"] == 0, "dialog never damages"


def test_dialog_unknown_verb_raises(engine, player):
    with pytest.raises(KeyError):
        er.resolve_dialog_action(engine, player, "THINK", "wary", _rng_pass())


def test_dialog_two_breaks_resolve_encounter(engine, player):
    # Two breaks_on matches = +4 progress, above threshold (3)
    p, out1 = er.resolve_dialog_action(engine, player, "RIDDLE", "wary",
                                       _rng_pass())
    assert out1["resolution"] == "pending"
    _, out2 = er.resolve_dialog_action(engine, p, "RIDDLE", "wary",
                                       _rng_pass())
    assert out2["resolution"] == "resolved"
