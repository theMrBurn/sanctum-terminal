"""config/encounters.json loader + schema checks."""
from __future__ import annotations

import pytest

from core.systems import encounter_config as ec


# -- Load --------------------------------------------------------------------

def test_loads():
    cfg = ec.load()
    assert isinstance(cfg, dict)
    assert cfg["_schema_version"] == 2


def test_top_level_pools_present():
    cfg = ec.load()
    for key in ("intents", "actors", "environments", "objects", "scouts",
                "phases", "dialog_intents", "dialog_verbs", "postures"):
        assert key in cfg, f"missing pool: {key}"


# -- Intents ------------------------------------------------------------------

def test_intents_well_formed():
    cfg = ec.load()
    for name, intent in cfg["intents"].items():
        assert "posture" in intent, f"{name} missing posture"
        assert "telegraph" in intent, f"{name} missing telegraph"
        assert "narration" in intent, f"{name} missing narration"
        assert "effect" in intent, f"{name} missing effect"


def test_get_intent_accessor():
    intent = ec.get_intent("strike")
    assert intent["posture"] == "coiling"
    assert intent["effect"] == "damage"


def test_unknown_intent_raises():
    with pytest.raises(KeyError):
        ec.get_intent("nonsense")


# -- Actors -------------------------------------------------------------------

def test_watcher_actor_well_formed():
    actor = ec.get_actor("watcher")
    assert actor["type"] == "orb"
    assert actor["max_hp"] == 6
    assert "phase_weights" in actor
    assert "reactive_bumps" in actor


def test_watcher_phase_weights_cover_three_phases():
    actor = ec.get_actor("watcher")
    phases = actor["phase_weights"]
    assert set(phases.keys()) == {"composed", "pressured", "desperate"}


def test_watcher_intents_match_intent_pool():
    """Every intent referenced in phase_weights must exist in the intents pool."""
    cfg = ec.load()
    actor = ec.get_actor("watcher")
    intent_pool = set(cfg["intents"].keys())
    for phase, weights in actor["phase_weights"].items():
        for intent_name in weights:
            assert intent_name in intent_pool, \
                f"{phase} references unknown intent {intent_name!r}"


def test_reactive_bumps_reference_known_intents():
    cfg = ec.load()
    actor = ec.get_actor("watcher")
    intent_pool = set(cfg["intents"].keys())
    for bump in actor["reactive_bumps"]:
        assert bump["intent"] in intent_pool
        assert "when" in bump
        assert "mult" in bump


# -- Scouts -------------------------------------------------------------------

def test_scout_references_resolvable():
    """A scout must point at an actor, environment, and objects that exist."""
    cfg = ec.load()
    scout = ec.get_scout("first_watcher")
    assert scout["actor"] in cfg["actors"]
    assert scout["environment"] in cfg["environments"]
    for obj_id in scout["objects"]:
        assert obj_id in cfg["objects"]


def test_scout_ceremony_and_flavor_present():
    scout = ec.get_scout("first_watcher")
    assert scout["mode"] == "dialog"
    for key in ("opening", "victory", "defeat", "fled"):
        assert key in scout["ceremony"]
    # Dialog scouts carry flavor keyed by dialog verbs × {pass, fail}.
    flavor = scout["flavor"]
    for verb in ("PROBE", "PRESS", "YIELD", "RIDDLE", "LISTEN"):
        assert f"{verb}_pass" in flavor, f"missing {verb}_pass flavor"
        assert f"{verb}_fail" in flavor, f"missing {verb}_fail flavor"


# -- Dialog pools -----------------------------------------------------------

def test_postures_well_formed():
    cfg = ec.load()
    for name, p in cfg["postures"].items():
        if name.startswith("_"):
            continue
        assert "reads" in p, f"{name} missing reads"
        assert "breaks_on" in p, f"{name} missing breaks_on"


def test_dialog_verbs_well_formed():
    cfg = ec.load()
    for name, v in cfg["dialog_verbs"].items():
        if name.startswith("_"):
            continue
        assert "stance" in v
        assert "save" in v
        assert v["save"] in ("str", "dex", "wil")


def test_dialog_intents_reference_valid_postures():
    cfg = ec.load()
    posture_pool = {k for k in cfg["postures"] if not k.startswith("_")}
    for name, intent in cfg["dialog_intents"].items():
        assert intent["posture"] in posture_pool, \
            f"dialog_intent {name!r} references unknown posture"


def test_watcher_dialog_weights_reference_valid_intents():
    cfg = ec.load()
    actor = ec.get_actor("watcher")
    intent_pool = set(cfg["dialog_intents"].keys())
    for phase, weights in actor["dialog_phase_weights"].items():
        for iname in weights:
            assert iname in intent_pool, \
                f"{phase} references unknown dialog_intent {iname!r}"


def test_get_dialog_verb_accessor():
    v = ec.get_dialog_verb("PROBE")
    assert v["stance"] == "curious"
    assert v["save"] == "wil"


def test_get_posture_accessor():
    p = ec.get_posture("wary")
    assert "curious" in p["reads"]


def test_get_dialog_intent_accessor():
    i = ec.get_dialog_intent("questioning")
    assert i["posture"] == "wary"


def test_doc_keys_not_treated_as_members():
    with pytest.raises(KeyError):
        ec.get_posture("_doc")
    with pytest.raises(KeyError):
        ec.get_dialog_verb("_doc")


# -- Phases -------------------------------------------------------------------

def test_phase_thresholds_ordered():
    cfg = ec.load()
    composed = cfg["phases"]["composed"]["hp_min_frac"]
    pressured = cfg["phases"]["pressured"]["hp_min_frac"]
    desperate = cfg["phases"]["desperate"]["hp_min_frac"]
    assert composed > pressured > desperate


def test_phase_for_hp_fraction():
    assert ec.phase_for_hp_fraction(1.0) == "composed"
    assert ec.phase_for_hp_fraction(0.9) == "composed"
    assert ec.phase_for_hp_fraction(0.6) == "pressured"
    assert ec.phase_for_hp_fraction(0.4) == "pressured"
    assert ec.phase_for_hp_fraction(0.3) == "desperate"
    assert ec.phase_for_hp_fraction(0.0) == "desperate"
