"""Tests for core.systems.encounter_builder.build_encounter.

Contract:
    build_encounter(bumped_ent, visible_ents, kind_cfgs) → list[Participant]

    - Always includes the bumped creature as the first enemy participant.
    - If the kind's combat_profile.pack_size_max > 1, scans visible_ents
      for other creatures of the SAME kind within pack_radius_m and
      includes up to pack_size_max total (bumped + packmates).
    - Solo kinds (pack_size_max == 1) never pull packmates.
    - Participants built from combat_profile; stable ids derived from (kind, x, y).
    - Missing combat_profile → creature excluded from encounter building
      (returns empty list; caller should check).

    Pure function. No I/O.
"""
from __future__ import annotations

import pytest

from core.systems.encounter_builder import build_encounter


def _creature(kind: str, x: float, y: float) -> dict:
    return {"kind": kind, "x": x, "y": y}


# Minimal kind_cfgs fixture — shape matches kind_config.json's "kinds" block.
KIND_CFGS = {
    "rat": {
        "class": "life",
        "combat_profile": {
            "hp": 3, "max_hp": 3, "str_": 4, "dex": 12, "wil": 4,
            "speed": 14, "defense": 10,
            "element_mods": {"fire": 1.3},
            "default_attack": "rat_bite",
            "tier": "pack",
            "pack_size_min": 2, "pack_size_max": 4, "pack_radius_m": 4.0,
            "xp_reward": 1,
        },
    },
    "spider": {
        "class": "life",
        "combat_profile": {
            "hp": 4, "max_hp": 4, "str_": 5, "dex": 14, "wil": 5,
            "speed": 11, "defense": 12,
            "element_mods": {},
            "default_attack": "spider_venom",
            "tier": "solo",
            "pack_size_min": 1, "pack_size_max": 1, "pack_radius_m": 0.0,
            "xp_reward": 3,
        },
    },
    "boulder": {
        "class": "geological",
        # no combat_profile — not a creature
    },
}


# --- Solo / pack decisions ---------------------------------------------------

def test_solo_kind_never_pulls_packmates():
    bumped = _creature("spider", 0.0, 0.0)
    others = [_creature("spider", 1.0, 0.0), _creature("spider", 0.5, 0.5)]
    parts = build_encounter(bumped, [bumped] + others, KIND_CFGS)
    enemies = [p for p in parts if p.side == "enemy"]
    assert len(enemies) == 1
    assert enemies[0].name.lower().startswith("spider")


def test_pack_kind_pulls_nearby_packmates():
    bumped = _creature("rat", 0.0, 0.0)
    pack = [
        _creature("rat", 1.0, 1.0),     # within radius
        _creature("rat", -2.0, 0.5),    # within radius
        _creature("rat", 3.5, 0.0),     # within radius (3.5 < 4.0)
    ]
    parts = build_encounter(bumped, [bumped] + pack, KIND_CFGS)
    enemies = [p for p in parts if p.side == "enemy"]
    # 4 total (bumped + 3), capped by pack_size_max = 4. All rats within 4m.
    assert len(enemies) == 4


def test_pack_out_of_radius_ignored():
    bumped = _creature("rat", 0.0, 0.0)
    far = [_creature("rat", 10.0, 10.0), _creature("rat", 0.0, 5.0)]
    parts = build_encounter(bumped, [bumped] + far, KIND_CFGS)
    enemies = [p for p in parts if p.side == "enemy"]
    assert len(enemies) == 1


def test_pack_size_capped_at_max():
    bumped = _creature("rat", 0.0, 0.0)
    # 6 rats within radius, but pack_size_max=4
    pack = [_creature("rat", 0.5 * i, 0.5 * i) for i in range(1, 7)]
    parts = build_encounter(bumped, [bumped] + pack, KIND_CFGS)
    enemies = [p for p in parts if p.side == "enemy"]
    assert len(enemies) == 4


def test_pack_does_not_include_different_kinds():
    bumped = _creature("rat", 0.0, 0.0)
    mixed = [_creature("spider", 1.0, 0.0), _creature("rat", 1.0, 1.0)]
    parts = build_encounter(bumped, [bumped] + mixed, KIND_CFGS)
    enemies = [p for p in parts if p.side == "enemy"]
    # Two rats (bumped + rat at 1,1). Spider isn't same kind.
    assert len(enemies) == 2
    assert all(p.name.lower().startswith("rat") for p in enemies)


def test_non_creature_bumped_returns_empty():
    bumped = _creature("boulder", 0.0, 0.0)
    parts = build_encounter(bumped, [bumped], KIND_CFGS)
    assert parts == []


def test_encounter_includes_player_placeholder_when_provided():
    """build_encounter accepts an optional player Participant to put on
    the roster — otherwise the caller injects their own."""
    bumped = _creature("rat", 0.0, 0.0)
    from core.systems.combat import Participant
    player = Participant(
        id="player", name="Hero", hp=10, max_hp=10,
        str_=12, dex=10, wil=10, speed=10, defense=11,
        element_mods={}, side="player",
        inventory=(), status={}, alive=True,
    )
    parts = build_encounter(bumped, [bumped], KIND_CFGS, player=player)
    assert any(p.side == "player" for p in parts)
    assert any(p.side == "enemy" for p in parts)


# --- Participant construction from combat_profile ---------------------------

def test_participant_fields_from_combat_profile():
    bumped = _creature("rat", 2.0, 3.0)
    parts = build_encounter(bumped, [bumped], KIND_CFGS)
    rat = parts[0]
    prof = KIND_CFGS["rat"]["combat_profile"]
    assert rat.hp == prof["hp"]
    assert rat.max_hp == prof["max_hp"]
    assert rat.str_ == prof["str_"]
    assert rat.dex == prof["dex"]
    assert rat.wil == prof["wil"]
    assert rat.speed == prof["speed"]
    assert rat.defense == prof["defense"]
    assert rat.element_mods == prof["element_mods"]
    assert rat.side == "enemy"
    assert rat.alive is True


def test_participant_ids_unique_for_same_kind_pack():
    bumped = _creature("rat", 0.0, 0.0)
    pack = [_creature("rat", 1.0, 0.0), _creature("rat", 0.0, 1.0)]
    parts = build_encounter(bumped, [bumped] + pack, KIND_CFGS)
    ids = [p.id for p in parts if p.side == "enemy"]
    assert len(set(ids)) == len(ids), f"duplicate ids: {ids}"


# --- Purity ------------------------------------------------------------------

def test_original_visible_list_unmutated():
    bumped = _creature("rat", 0.0, 0.0)
    pack = [_creature("rat", 1.0, 0.0)]
    visible = [bumped] + pack
    snapshot = [dict(e) for e in visible]
    build_encounter(bumped, visible, KIND_CFGS)
    assert visible == snapshot
