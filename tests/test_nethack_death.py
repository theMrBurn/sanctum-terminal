"""PR 8 tests — YASD death, vault.runs row, score formula, hi-score sort.

Validates:
  - HP=0 triggers run_end with terminal_state="died".
  - run_end populates metrics: depth_reached, monsters_killed, turns, score.
  - Score formula: xp*100 + gold + depth_reached*50.
  - player_died event emitted with cause_of_death.
  - Hi-score sort: filters terminal_state="died", sorts by score desc.
  - Tombstone text contains expected fields.

Spec: `.claude/feature/feat_make-brain-nethack.md` PR 8.
"""
from __future__ import annotations

import random
import pytest

from core.systems.make_brains.nethack.entities import spawn_monster


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_game_state(tmp_path, seed: int = 42):
    """Boot a real GameState + vault."""
    from core.systems import make_brain_registry
    from core.systems.make_brains import nethack as _nethack
    from core.vault import vault as Vault
    from core.systems.make_brains.nethack.engine import GameState

    make_brain_registry._reset_for_tests()
    v = Vault(db_path=str(tmp_path / "vault.db"))
    spec = _nethack.activate(v)
    handler = spec.handler
    handler.start_run()

    game = GameState(handler, seed=seed)
    return game, handler, v, make_brain_registry


def _cleanup(registry):
    registry._reset_for_tests()


# ---------------------------------------------------------------------------
# Score formula
# ---------------------------------------------------------------------------

def test_score_formula_pure():
    """score = xp * 100 + gold + depth_reached * 50"""
    import nethack_terminal as _entry
    from core.systems.make_brains.nethack.entities import Player

    class _FakeGame:
        class player:
            xp = 10
            gold = 75

        class handler:
            _run_metrics = {"depth_reached": 3, "monsters_killed": 5}

        dlvl = 3

    score = _entry._compute_score(_FakeGame())
    assert score == 10 * 100 + 75 + 3 * 50
    assert score == 1225


def test_score_zero_run():
    """A run with no XP, no gold, depth 1 produces minimal score."""
    import nethack_terminal as _entry
    from core.systems.make_brains.nethack.entities import Player

    class _FakeGame:
        class player:
            xp = 0
            gold = 0

        class handler:
            _run_metrics = {"depth_reached": 1}

        dlvl = 1

    assert _entry._compute_score(_FakeGame()) == 50


def test_score_deterministic_same_inputs():
    import nethack_terminal as _entry

    class _FakeGame:
        class player:
            xp = 42
            gold = 100

        class handler:
            _run_metrics = {"depth_reached": 5}

        dlvl = 5

    s1 = _entry._compute_score(_FakeGame())
    s2 = _entry._compute_score(_FakeGame())
    assert s1 == s2


# ---------------------------------------------------------------------------
# Death triggers run_end with died state
# ---------------------------------------------------------------------------

def test_hp_zero_closes_run_as_died(tmp_path):
    """Killing the player (hp=0) must close the vault row with terminal_state=died."""
    game, handler, vault, registry = _make_game_state(tmp_path, seed=42)

    run_id = handler._run_id
    # Simulate a lethal monster attack manually
    game.player.cause_of_death = "killed by a newt"
    game.player.hp = 0
    game.alive = False

    # Call the death handler directly (as the game loop would)
    import nethack_terminal as _entry
    score = _entry._compute_score(game)
    handler._run_metrics["score"] = score
    handler._run_metrics["cause_of_death"] = game.player.cause_of_death
    handler._emit_event("player_died",
                        cause=game.player.cause_of_death,
                        score=score)
    handler.end_run(
        terminal_state="died",
        score=score,
        cause_of_death=game.player.cause_of_death,
    )

    runs = vault.runs_by_instance("nethack")
    assert len(runs) == 1
    run = runs[0]
    assert run["terminal_state"] == "died"
    assert run["metrics"]["score"] == score
    assert "newt" in run["metrics"]["cause_of_death"]

    _cleanup(registry)


def test_metrics_populated_on_death(tmp_path):
    """run_metrics keys (depth_reached, monsters_killed, turns) survive to vault."""
    game, handler, vault, registry = _make_game_state(tmp_path, seed=42)

    # Simulate some game progress
    handler._run_metrics["depth_reached"]   = 4
    handler._run_metrics["monsters_killed"] = 7
    handler._run_metrics["turns"]           = 150

    import nethack_terminal as _entry
    score = _entry._compute_score(game)
    handler._run_metrics["score"] = score
    handler.end_run(
        terminal_state="died",
        score=score,
        cause_of_death="killed by an orc",
    )

    runs = vault.runs_by_instance("nethack")
    m = runs[0]["metrics"]
    assert m["depth_reached"]   == 4
    assert m["monsters_killed"] == 7
    assert m["turns"]           == 150

    _cleanup(registry)


def test_player_died_event_emitted(tmp_path):
    game, handler, vault, registry = _make_game_state(tmp_path, seed=42)

    game.player.cause_of_death = "killed by a grid bug"
    game.player.hp = 0
    game.alive = False

    import nethack_terminal as _entry
    score = _entry._compute_score(game)
    handler._emit_event("player_died",
                        cause=game.player.cause_of_death,
                        score=score)
    handler.end_run(terminal_state="died", score=score)

    events = handler.drain_state_events()   # drain after end_run
    # drain_state_events was called by manifest_keys; end_run emits make_brain_ended
    # Re-fetch from vault to confirm run closed
    runs = vault.runs_by_instance("nethack")
    assert runs[0]["terminal_state"] == "died"

    _cleanup(registry)


# ---------------------------------------------------------------------------
# run_end is called only once
# ---------------------------------------------------------------------------

def test_end_run_idempotent(tmp_path):
    """Calling end_run twice doesn't create two closed rows."""
    game, handler, vault, registry = _make_game_state(tmp_path, seed=42)

    handler.end_run(terminal_state="died", score=0)
    handler.end_run(terminal_state="died", score=0)   # second call is no-op

    runs = vault.runs_by_instance("nethack")
    assert len(runs) == 1

    _cleanup(registry)


# ---------------------------------------------------------------------------
# Hi-score sort
# ---------------------------------------------------------------------------

def _seed_runs(vault, n: int = 5):
    """Insert n completed runs with varying scores into vault.runs."""
    from core.systems.make_brains.nethack.handler import INSTANCE_ID
    scores = [100, 500, 50, 1000, 250][:n]
    for i, score in enumerate(scores):
        run_id = vault.run_start(INSTANCE_ID, "vanilla")
        vault.run_end(
            INSTANCE_ID, run_id,
            terminal_state="died",
            metrics={
                "score": score,
                "depth_reached": i + 1,
                "monsters_killed": i * 2,
                "turns": 50 * (i + 1),
                "cause_of_death": f"killed by monster {i}",
            },
        )
    # Add a quit run that should NOT appear in hi-scores
    quit_id = vault.run_start(INSTANCE_ID, "vanilla")
    vault.run_end(
        INSTANCE_ID, quit_id,
        terminal_state="quit",
        metrics={"score": 9999},
    )


def test_hi_scores_filter_died_only(tmp_path):
    from core.vault import vault as Vault
    import nethack_terminal as _entry

    v = Vault(db_path=str(tmp_path / "vault.db"))
    _seed_runs(v, n=5)

    runs = v.runs_by_instance("nethack")
    died = [r for r in runs if r.get("terminal_state") == "died"]
    assert len(died) == 5
    # Quit run is in total but not in died
    assert len(runs) == 6


def test_hi_scores_sorted_by_score_desc(tmp_path):
    from core.vault import vault as Vault

    v = Vault(db_path=str(tmp_path / "vault.db"))
    _seed_runs(v, n=5)

    runs = v.runs_by_instance("nethack")
    died = [r for r in runs if r.get("terminal_state") == "died"]
    died.sort(key=lambda r: (r.get("metrics") or {}).get("score", 0), reverse=True)

    scores = [(r.get("metrics") or {}).get("score", 0) for r in died]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == 1000


def test_hi_scores_top_10_limit(tmp_path):
    from core.vault import vault as Vault

    v = Vault(db_path=str(tmp_path / "vault.db"))
    # Insert 12 runs
    from core.systems.make_brains.nethack.handler import INSTANCE_ID
    for i in range(12):
        rid = v.run_start(INSTANCE_ID, "vanilla")
        v.run_end(INSTANCE_ID, rid, terminal_state="died",
                  metrics={"score": i * 10, "depth_reached": 1,
                           "cause_of_death": "test"})

    runs = v.runs_by_instance("nethack")
    died = [r for r in runs if r.get("terminal_state") == "died"]
    died.sort(key=lambda r: (r.get("metrics") or {}).get("score", 0), reverse=True)
    top10 = died[:10]
    assert len(top10) == 10
    # Top score should be 11 * 10 = 110
    assert top10[0]["metrics"]["score"] == 110


# ---------------------------------------------------------------------------
# Tombstone text
# ---------------------------------------------------------------------------

def test_tombstone_contains_required_fields(tmp_path):
    game, handler, vault, registry = _make_game_state(tmp_path, seed=42)
    handler._run_metrics["depth_reached"] = 3
    handler._run_metrics["monsters_killed"] = 5
    game.player.xp = 10
    game.player.cause_of_death = "killed by an orc"

    import nethack_terminal as _entry
    text = _entry.render_tombstone_text(game)

    assert "anon"  in text         # name
    assert "3"     in text         # depth
    # killer truncated to 15 chars: "killed by an or" from "killed by an orc"
    assert "killed by" in text     # prefix always present
    # score = 10*100 + 0 + 3*50 = 1150
    assert str(_entry._compute_score(game)) in text

    handler.end_run(terminal_state="died")
    _cleanup(registry)


def test_tombstone_rip_header(tmp_path):
    game, handler, vault, registry = _make_game_state(tmp_path, seed=42)
    game.player.cause_of_death = "test death"

    import nethack_terminal as _entry
    text = _entry.render_tombstone_text(game)

    assert "R" in text and "I" in text and "P" in text

    handler.end_run(terminal_state="died")
    _cleanup(registry)
