"""Action → d20 save → outcome layer for encounters.

Sits on top of EncounterEngine. The engine owns resonance + staged XP +
cooldown + consolidation. This module owns per-action resolution: which stat
saves, what happens on pass/fail, how many passes close the encounter.

Two resolution modes, selected by scout.mode:

  action mode (combat) — resolve_action():
    THINK   → WIL   pass: +net, tag reveal   fail: HP -1
    ACT     → STR   pass: +net (progress)    fail: HP -1d4
    MOVE    → DEX   pass: +net (reposition)  fail: HP -1
    DEFEND  → —     no roll, halves next hit
    TOOLS   → varies per item                 (UAT-1: unused)
    CRAFT   → WIL   pass: +net               fail: HP -1
    OBSERVE → WIL   pass: half-net           fail: no cost

  dialog mode (parley) — resolve_dialog_action():
    Each verb carries a stance + save stat. On pass, the stance is matched
    against the orb's current posture: stance ∈ posture.reads → +1 progress;
    stance == posture.breaks_on → +2 progress (posture shatters). On fail or
    stance mismatch, no progress AND no HP damage. Dialog has no HP cost —
    it's attrition of understanding, not attrition of body.

Encounter resolves when net_passes >= RESOLUTION_THRESHOLD in either mode.
"""
from __future__ import annotations

from typing import Callable, Tuple

from core.systems import encounter_config as ec
from core.systems import player_state as ps
from core.systems.player_state import PlayerState

RESOLUTION_THRESHOLD = 3   # net passes to close an encounter

# action → (save_stat | None, pass_net, fail_net, fail_hp_die)
# fail_hp_die: None = no damage, int N = flat N damage, ("d", N) = 1..N roll
_ACTION_TABLE = {
    "THINK":   ("wil", +1, 0, 1),
    "ACT":     ("str", +1, 0, ("d", 4)),
    "MOVE":    ("dex", +1, 0, 1),
    "DEFEND":  (None,  0,  0, None),
    "CRAFT":   ("wil", +1, 0, 1),
    "OBSERVE": ("wil", +1, 0, None),
    "TOOLS":   ("wil", +1, 0, None),   # UAT-1 placeholder
}
_VERB_TABLE = _ACTION_TABLE    # legacy alias


def resolve_action(
    engine,
    player: PlayerState,
    action: str,
    rng: Callable[[int], int],
) -> Tuple[PlayerState, dict]:
    """Apply one action to the active encounter.

    `rng(size)` returns an int in 1..size. Must be injected for determinism.
    Returns (new_player_state, outcome_dict). Outcome includes:
        action, save (pass/fail/none), roll, stat, hp_delta, net_passes,
        resolution ∈ {"pending", "resolved", "defeated"}.

    Does NOT call engine.resolve() — caller decides when to finalize based
    on resolution status. This keeps XP staging and cooldown timing in the
    engine's hands, not the resolver's.
    """
    if action not in _ACTION_TABLE:
        raise ValueError(f"unknown action {action!r}")
    if engine.active_encounter is None:
        raise RuntimeError("no active encounter")

    enc = engine.active_encounter
    enc.setdefault("net_passes", 0)

    stat, pass_net, fail_net, fail_dmg = _ACTION_TABLE[action]

    save_result = None
    roll = stat_val = 0
    passed = True  # DEFEND is no-roll, treat as "pass" for bookkeeping

    if stat is not None:
        sr = ps.save_roll(player, stat, lambda: rng(20))
        save_result = "pass" if sr.success else "fail"
        roll, stat_val, passed = sr.roll, sr.stat, sr.success

    hp_before = player.hp
    if passed:
        enc["net_passes"] += pass_net
    else:
        enc["net_passes"] += fail_net
        if fail_dmg is not None:
            dmg = _roll_damage(fail_dmg, rng)
            player = ps.take_damage(player, dmg)

    engine.choose(action)   # records action_used on active_encounter

    if player.hp <= 0:
        resolution = "defeated"
    elif enc["net_passes"] >= RESOLUTION_THRESHOLD:
        resolution = "resolved"
    else:
        resolution = "pending"

    return player, {
        "action":      action,
        "verb":        action,          # legacy mirror
        "save":        save_result,
        "roll":        roll,
        "stat":        stat_val,
        "hp_before":   hp_before,
        "hp_after":    player.hp,
        "hp_delta":    player.hp - hp_before,
        "net_passes":  enc["net_passes"],
        "resolution":  resolution,
    }


# Legacy alias — older callers used resolve_verb
resolve_verb = resolve_action


# -- Dialog resolver ----------------------------------------------------------

def resolve_dialog_action(
    engine,
    player: PlayerState,
    verb: str,
    orb_posture: str,
    rng: Callable[[int], int],
) -> Tuple[PlayerState, dict]:
    """Dialog-mode resolver. Parley, not combat.

    verb must be a key in config dialog_verbs. orb_posture is the name of
    the posture the orb is currently holding (from its queued intent).

    Roll a d20 save on the verb's stat. On pass, compare verb.stance to
    the posture's `reads`/`breaks_on`:
        stance in posture.reads     → +1 progress
        stance == posture.breaks_on → +2 progress, posture break flagged
        otherwise                   → 0 progress (heard, but didn't land)

    On fail: no progress, no HP loss. Dialog never damages.

    Returns (unchanged player, outcome_dict). Outcome dict shape mirrors
    resolve_action — action / save / roll / stat / net_passes / resolution —
    plus dialog-specific: stance, posture, stance_match ∈ {"breaks", "reads",
    "miss", None}.
    """
    verb_cfg = ec.get_dialog_verb(verb)
    if engine.active_encounter is None:
        raise RuntimeError("no active encounter")

    enc = engine.active_encounter
    enc.setdefault("net_passes", 0)

    stat = verb_cfg["save"]
    stance = verb_cfg["stance"]

    sr = ps.save_roll(player, stat, lambda: rng(20))
    save_result = "pass" if sr.success else "fail"

    stance_match: str | None = None
    progress = 0
    if sr.success:
        try:
            posture_cfg = ec.get_posture(orb_posture)
        except KeyError:
            posture_cfg = {"reads": [], "breaks_on": None}
        if stance == posture_cfg.get("breaks_on"):
            progress = 2
            stance_match = "breaks"
        elif stance in posture_cfg.get("reads", []):
            progress = 1
            stance_match = "reads"
        else:
            stance_match = "miss"

    enc["net_passes"] += progress
    # Dialog verbs aren't in engine.ACTIONS — record directly rather than
    # going through engine.choose() (which validates against the combat set).
    enc["action_used"] = verb
    enc["verb_used"] = verb

    if enc["net_passes"] >= RESOLUTION_THRESHOLD:
        resolution = "resolved"
    else:
        resolution = "pending"

    return player, {
        "action":       verb,
        "verb":         verb,
        "save":         save_result,
        "roll":         sr.roll,
        "stat":         sr.stat,
        "hp_before":    player.hp,
        "hp_after":     player.hp,
        "hp_delta":     0,
        "net_passes":   enc["net_passes"],
        "resolution":   resolution,
        "stance":       stance,
        "posture":      orb_posture,
        "stance_match": stance_match,
        "progress_delta": progress,
    }


# -- Encounter catalog --------------------------------------------------------
# UAT-1 ships one encounter: The Watcher. Tags chosen to overlap a primed
# Philosopher-Monk fingerprint (precision_score + observation_time), which is
# also the baseline used by test_encounter_engine fixtures. A truly cold
# fingerprint (all zeros) will not trigger this — by design. The hub seeding
# ritual is expected to warm the relevant dimensions before expedition start.

WATCHER = {
    "id":            "watcher_uat1",
    "kind":          "orb",
    "tags":          ["observation_time", "precision_score"],
    "spawn_mode":    "front_fov",
    "persistence":   "one_shot",
    "orb": {
        "segments":  7,
        "solid_mode": True,
        "base": {
            "color":    [1.0, 0.08, 0.08],   # red_orb_fixture red
            "emission": 2.5,
            "pulse":    {"freq": 0.5, "amp": 0.25, "waveform": "sine"},
        },
    },
}


def _roll_damage(spec, rng: Callable[[int], int]) -> int:
    if isinstance(spec, int):
        return spec
    if isinstance(spec, tuple) and spec[0] == "d":
        return rng(spec[1])
    raise ValueError(f"bad damage spec {spec!r}")
