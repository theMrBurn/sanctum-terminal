"""Tennis match-state machine — pure transitions tests.

T6 of `feat_make-brain-ping-pong` PR 6. Pins the rules implemented in
`core.systems.volley_scoring`:

  - 0 → 15 → 30 → 40 → game progression
  - Deuce + advantage + back-to-deuce
  - Set won at 6-X with 2-game lead
  - Match won at 2 sets (best-of-3)
  - Match locks when winner is set
  - HUD score line composition
"""
from __future__ import annotations

import pytest

from core.systems.volley_scoring import (
    GAMES_TO_WIN_SET, MatchState, SETS_TO_WIN_MATCH,
    hud_score_lines, new_match, point_label, point_opp, point_player,
)


# ── new_match defaults ────────────────────────────────────────────────


def test_new_match_zero_state():
    s = new_match()
    assert s.points == (0, 0)
    assert s.games == (0, 0)
    assert s.sets_won == (0, 0)
    assert s.set_winners == ()
    assert s.match_winner is None
    assert s.server == "player"
    assert s.mode == "wall_rally"


# ── Points within a game ──────────────────────────────────────────────


def test_points_climb_15_30_40():
    s = new_match()
    s = point_player(s); assert s.points == (1, 0)    # 15-0
    s = point_player(s); assert s.points == (2, 0)    # 30-0
    s = point_player(s); assert s.points == (3, 0)    # 40-0


def test_game_won_at_4_with_2_lead():
    s = new_match()
    for _ in range(4):
        s = point_player(s)
    # 4-0 → game won → games (1, 0) and points reset.
    assert s.points == (0, 0)
    assert s.games == (1, 0)


def test_player_immutable_input():
    """Transitions return new MatchStates; original unchanged."""
    s0 = new_match()
    s1 = point_player(s0)
    assert s0.points == (0, 0)
    assert s1.points == (1, 0)


# ── Deuce + advantage ─────────────────────────────────────────────────


def test_deuce_collapse_at_4_4():
    s = new_match()
    for _ in range(3):
        s = point_player(s)
    for _ in range(3):
        s = point_opp(s)
    assert s.points == (3, 3)                    # 40-40 = deuce

    # Player gets ad
    s = point_player(s)
    assert s.points == (4, 3)
    # Opp claws back → deuce again
    s = point_opp(s)
    assert s.points == (3, 3)


def test_deuce_then_two_in_row_wins_game():
    s = new_match()
    for _ in range(3):
        s = point_player(s)
    for _ in range(3):
        s = point_opp(s)
    # 40-40
    s = point_player(s)                          # ad
    s = point_player(s)                          # game
    assert s.games == (1, 0)
    assert s.points == (0, 0)


# ── Set progression ───────────────────────────────────────────────────


def _win_game(s: MatchState, side: str) -> MatchState:
    """Drive `side` to game-won from the current points (for test plumbing)."""
    fn = point_player if side == "player" else point_opp
    while True:
        s = fn(s)
        if s.points == (0, 0):                   # game just rolled over
            return s


def test_set_won_at_6_0():
    s = new_match()
    for _ in range(GAMES_TO_WIN_SET):
        s = _win_game(s, "player")
    assert s.sets_won == (1, 0)
    assert s.set_winners == ("player",)
    assert s.games == (0, 0)


def test_set_requires_2_game_lead():
    """6-5 is NOT a set; 7-5 is. (V1 has no tiebreak; play continues
    until 2-lead.)"""
    s = new_match()
    # Drive to 5-5.
    for _ in range(5):
        s = _win_game(s, "player")
    for _ in range(5):
        s = _win_game(s, "opp")
    assert s.games == (5, 5)
    s = _win_game(s, "player")
    assert s.games == (6, 5)                     # NOT a set yet
    assert s.sets_won == (0, 0)
    s = _win_game(s, "player")
    assert s.sets_won == (1, 0)                  # 7-5 = set


def test_server_alternates_between_sets():
    s = new_match()
    assert s.server == "player"
    for _ in range(GAMES_TO_WIN_SET):
        s = _win_game(s, "player")
    assert s.server == "opp"


# ── Match progression ────────────────────────────────────────────────


def test_match_won_at_2_sets():
    s = new_match()
    # Win set 1
    for _ in range(GAMES_TO_WIN_SET):
        s = _win_game(s, "player")
    # Win set 2
    for _ in range(GAMES_TO_WIN_SET):
        s = _win_game(s, "player")
    assert s.match_winner == "player"
    assert s.sets_won == (2, 0)


def test_match_can_end_3_sets():
    """Best-of-3: lose set 1, win sets 2 + 3 → match win."""
    s = new_match()
    for _ in range(GAMES_TO_WIN_SET):
        s = _win_game(s, "opp")        # set 1 → opp
    for _ in range(GAMES_TO_WIN_SET):
        s = _win_game(s, "player")     # set 2 → player
    for _ in range(GAMES_TO_WIN_SET):
        s = _win_game(s, "player")     # set 3 → player → match
    assert s.match_winner == "player"
    assert s.sets_won == (2, 1)
    assert s.set_winners == ("opp", "player", "player")


def test_state_is_frozen_after_match_winner():
    """Once match_winner is set, point_* calls are no-ops."""
    s = new_match()
    for _ in range(GAMES_TO_WIN_SET * 2):
        s = _win_game(s, "player")
    assert s.match_winner == "player"
    snapshot = s
    s = point_player(s)
    s = point_opp(s)
    assert s == snapshot


# ── Display helpers ──────────────────────────────────────────────────


def test_point_label_normal():
    assert point_label(0, 0) == "0"
    assert point_label(1, 0) == "15"
    assert point_label(2, 1) == "30"
    assert point_label(3, 2) == "40"


def test_point_label_deuce_and_advantage():
    assert point_label(3, 3) == "DEUCE"
    assert point_label(4, 3) == "AD"
    assert point_label(3, 4) == "—"             # opp has advantage from this side


def test_hud_score_lines_in_progress():
    s = MatchState(points=(1, 2), games=(3, 4), sets_won=(1, 0))
    lines = hud_score_lines(s)
    assert any("SETS  1 - 0" in line for line in lines)
    assert any("GAMES  3 - 4" in line for line in lines)
    assert any("GAME" in line and "15" in line for line in lines)


def test_hud_score_lines_match_winner_label():
    s = MatchState(sets_won=(2, 0), match_winner="player")
    lines = hud_score_lines(s)
    assert any("MATCH" in line and "PLAYER" in line for line in lines)
