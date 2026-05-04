"""Tennis match-state machine — pure data + pure functions.

Universal scoring substrate. V1 wall rally and V2 NPC opponent both
fold rally outcomes through this module. The handler owns one
MatchState; on rally end it calls `point_player()` or `point_opp()`
which returns a new MatchState.

Per `.claude/feature/feat_make-brain-ping-pong.md` PR 6.

## Standard tennis rules implemented

- Points within a game: 0 → 15 → 30 → 40 → game.
- Deuce at 40-40: must win 2 in a row from deuce. After deuce, leading
  side has "advantage"; their next point wins the game; opp's next
  point returns to deuce.
- Sets: first to 6 games with a 2-game lead.
- Match: best of 3 sets (first to 2 sets won).

## V1 simplifications

- **Tiebreak (6-6) deferred.** Real tennis goes to a 7-point tiebreaker
  at 6-6. V1 just keeps playing until one side hits 2-game lead. Note
  this can theoretically run forever; tunable cap added later.
- **Match-loop after match wins is undefined.** When `match_winner` is
  set, `point_*` calls become no-ops until reset.

## Mode

`MatchState` carries a `mode` field:
  - `"wall_rally"` — solo against the chamber. Player can score by
    sustaining ≥long_rally_threshold contacts before missing; below
    threshold = opp point.
  - `"vs_npc"` — V2+. Either side can win a rally. Reserved.

The wall_rally tally rule lives in the *handler* (where rally length
is tracked). This module is rules-agnostic — it just transitions state.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Literal


# The numeric "point score" inside a game — index into _POINT_LABELS
# below. 0=love, 1=15, 2=30, 3=40, 4+=advantage/win zone (handled by
# deuce logic).
_POINT_LABELS = ("0", "15", "30", "40")

# How many sets to win = match. Best-of-3 → 2 sets.
SETS_TO_WIN_MATCH = 2

# Games-per-set threshold. First to N with 2-lead wins.
GAMES_TO_WIN_SET = 6

Side = Literal["player", "opp"]


@dataclass(frozen=True)
class MatchState:
    """Immutable snapshot of where the match stands.

    `points`        — current game's running points, (player, opp). Each
                       value 0..3 normally; equal at 3 = deuce; values
                       jump to 4+ during advantage.
    `games`         — current set's running games, (player, opp).
    `sets_won`      — completed sets won by each side.
    `match_winner`  — 'player' / 'opp' / None.
    `set_winners`   — log of who won each completed set, in order.
    `mode`          — see module docstring.
    """
    points:       tuple[int, int]              = (0, 0)
    games:        tuple[int, int]              = (0, 0)
    sets_won:     tuple[int, int]              = (0, 0)
    set_winners:  tuple[Side, ...]             = ()
    match_winner: Side | None                  = None
    server:       Side                         = "player"
    mode:         Literal["wall_rally", "vs_npc"] = "wall_rally"


# ----------------------------------------------------------------------
# Pure transitions
# ----------------------------------------------------------------------


def new_match(mode: Literal["wall_rally", "vs_npc"] = "wall_rally") -> MatchState:
    """Fresh match. Player serves first."""
    return MatchState(mode=mode)


def _award_point(state: MatchState, side: Side) -> MatchState:
    """Apply one point to `side`. Roll over to game/set/match as needed."""
    if state.match_winner is not None:
        return state                            # frozen after match

    p_p, p_o = state.points
    if side == "player":
        p_p += 1
    else:
        p_o += 1

    # Game-won decision.
    # Standard rule: first to 4 points (= "game") AND ≥2-point margin.
    # Handles deuce naturally — 4-3 → no game (margin 1) → next point
    # either wins (4-2, margin 2 → game) or returns to deuce (3-4 → 4-4).
    # Tennis convention: at deuce, you collapse 4-4 back to 3-3 visually.
    # We collapse here so points don't grow unbounded.
    if (p_p >= 4 or p_o >= 4) and abs(p_p - p_o) >= 2:
        # Game won.
        winner: Side = "player" if p_p > p_o else "opp"
        return _award_game(replace(state, points=(0, 0)), winner)
    if p_p >= 4 and p_o >= 4 and p_p == p_o:
        # Bounced back to deuce — collapse to (3, 3).
        return replace(state, points=(3, 3))
    return replace(state, points=(p_p, p_o))


def _award_game(state: MatchState, side: Side) -> MatchState:
    """Increment games for `side`, roll over to set/match."""
    g_p, g_o = state.games
    if side == "player":
        g_p += 1
    else:
        g_o += 1

    # Set-won decision: first to GAMES_TO_WIN_SET with 2-game lead.
    # V1 simplification: no tiebreak at 6-6; play continues to 2-lead.
    if (g_p >= GAMES_TO_WIN_SET or g_o >= GAMES_TO_WIN_SET) \
            and abs(g_p - g_o) >= 2:
        set_winner: Side = "player" if g_p > g_o else "opp"
        return _award_set(replace(state, games=(0, 0)), set_winner)
    return replace(state, games=(g_p, g_o))


def _award_set(state: MatchState, side: Side) -> MatchState:
    """Increment set count, roll over to match if applicable."""
    s_p, s_o = state.sets_won
    if side == "player":
        s_p += 1
    else:
        s_o += 1

    new_log = state.set_winners + (side,)

    # Match-won decision: first to SETS_TO_WIN_MATCH.
    if s_p >= SETS_TO_WIN_MATCH or s_o >= SETS_TO_WIN_MATCH:
        winner: Side = "player" if s_p > s_o else "opp"
        return replace(
            state,
            sets_won=(s_p, s_o),
            set_winners=new_log,
            match_winner=winner,
        )
    # Server alternates set-by-set in real tennis. V1 keeps it simple
    # and just toggles between sets.
    new_server: Side = "opp" if state.server == "player" else "player"
    return replace(
        state,
        sets_won=(s_p, s_o),
        set_winners=new_log,
        server=new_server,
    )


def point_player(state: MatchState) -> MatchState:
    """Award one point to the player. Returns a new MatchState."""
    return _award_point(state, "player")


def point_opp(state: MatchState) -> MatchState:
    """Award one point to the opponent. Returns a new MatchState."""
    return _award_point(state, "opp")


# ----------------------------------------------------------------------
# Display helpers
# ----------------------------------------------------------------------


def point_label(side_points: int, opp_points: int) -> str:
    """Tennis-style point label for display.

    0/15/30/40 for normal play. At deuce returns "DEUCE". With one side
    leading from deuce, "AD" (advantage). After game, n/a (handled by
    caller).
    """
    if side_points >= 3 and opp_points >= 3:
        if side_points == opp_points:
            return "DEUCE"
        if side_points > opp_points:
            return "AD"
        return "—"                              # opp has advantage
    if side_points <= 3:
        return _POINT_LABELS[side_points]
    return _POINT_LABELS[3]                     # fallback


def hud_score_lines(state: MatchState) -> list[str]:
    """Compact 2-line score block for HUD overlay."""
    s_p, s_o = state.sets_won
    g_p, g_o = state.games
    lines = [f"SETS  {s_p} - {s_o}      GAMES  {g_p} - {g_o}"]
    if state.match_winner:
        lines.append(f"MATCH  {state.match_winner.upper()} WINS")
    else:
        lines.append(
            f"GAME  {point_label(state.points[0], state.points[1])} - "
            f"{point_label(state.points[1], state.points[0])}"
        )
    return lines
