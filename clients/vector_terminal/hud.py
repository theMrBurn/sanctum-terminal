"""HUD rendering — top-left game state stack, encounter panel, crosshair.

All draws happen in 2D screen space (after end_mode_3d). Manifest fields
sourced per brain_server.py:876-928. VT323 font preferred; falls back to
raylib's default if assets/VT323.ttf isn't present.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pyray as rl

from clients.vector_terminal import config as cfg
from clients.vector_terminal.inputs import action_for_key_index


_FONT: Any = None


def load_font() -> None:
    """Load VT323 from assets/ once. Falls back to raylib default if missing."""
    global _FONT
    if _FONT is not None:
        return
    path = Path(__file__).parent / "assets" / "VT323.ttf"
    if path.exists():
        _FONT = rl.load_font_ex(str(path), cfg.HUD_FONT_SIZE, None, 0)
    else:
        _FONT = rl.get_font_default()


def font():
    return _FONT


def draw_crosshair(width: int, height: int, color) -> None:
    cx = width // 2
    cy = height // 2
    half = cfg.CROSSHAIR_SIZE // 2
    rl.draw_rectangle(cx - half, cy, cfg.CROSSHAIR_SIZE, 1, color)
    rl.draw_rectangle(cx, cy - half, 1, cfg.CROSSHAIR_SIZE, color)


def draw_hud(manifest: dict, color) -> None:
    """Top-left field stack. Identity from `character_sheet` (when sealed)
    leads; live status (HP / TENSION / PHASE / EXPED / EQUIP / INV / MSG)
    follows. A divider separates them so identity and state are visually
    distinct."""
    if _FONT is None:
        load_font()
    x = cfg.HUD_X
    y = cfg.HUD_Y
    line = cfg.HUD_LINE_HEIGHT

    fields: list[str] = []

    # ── Make-brain identity (volley chamber, future archery, etc.) ──
    # Trumps the character_sheet identity since make-brain biomes are
    # standalone test rigs, not the main game. Per
    # `feat_make-brain-ping-pong.md` PR 3.
    mb_iid = manifest.get("instance_id")
    if mb_iid == "ping_pong":
        active_profile = manifest.get("active_profile") or "?"
        fields.append(f"VOLLEY CHAMBER — {active_profile}")
        fields.extend(_volley_score_lines(manifest))
        fields.extend(_brick_score_lines(manifest))
        fields.append("---")

    # ── Identity block (only when character_sheet present) ──
    sheet = manifest.get("character_sheet")
    if sheet:
        name = sheet.get("name", "?")
        level = sheet.get("level", sheet.get("age", "?"))
        background = sheet.get("background", "")
        fields.append(f"{name.upper()} | LEVEL {level}")
        if background:
            fields.append(f"  {background}")
        stats = sheet.get("stats") or {}
        if stats:
            fields.append(
                f"  DEX {stats.get('DEX','?')}  WIS {stats.get('WIS','?')}  "
                f"INT {stats.get('INT','?')}  CHA {stats.get('CHA','?')}"
            )
        abilities = sheet.get("selected_abilities") or []
        if abilities:
            fields.append(f"  ABL {_truncate(', '.join(abilities), cfg.HUD_INV_MAX_CHARS)}")
        verbs = sheet.get("verbs_known") or []
        if verbs:
            fields.append(f"  VRB {' | '.join(verbs)}")
        fields.append("---")

    # ── Live status block ──
    player = manifest.get("player", {})
    hp = player.get("hp", 0)
    max_hp = player.get("max_hp", 0)
    equipped = player.get("equipped") or "-"
    inventory = player.get("inventory", [])
    inv_text = ", ".join(
        f"{item.get('name', '?')}x1" for item in inventory
    ) if inventory else "-"
    inv_text = _truncate(inv_text, cfg.HUD_INV_MAX_CHARS)

    tension_state = manifest.get("tension_state", "?")
    tension_budget = manifest.get("tension_budget", 0.0)

    game_state = manifest.get("game_state", {})
    phase = game_state.get("state") or game_state.get("phase") or "?"

    expedition = manifest.get("expedition", {})
    obj = expedition.get("objective_text", "")
    msg = expedition.get("last_message_text", "") or expedition.get("last_message", "")

    fields.extend([
        f"HP {hp}/{max_hp}",
        f"TENSION {tension_state} {tension_budget:.2f}",
        f"PHASE {phase}",
        f"EXPED {_truncate(obj, cfg.HUD_OBJECTIVE_MAX_CHARS)}",
        f"EQUIP {equipped}",
        f"INV {inv_text}",
        f"MSG {_truncate(str(msg), cfg.HUD_MSG_MAX_CHARS)}",
    ])

    # ── Active quest rows (PR 4) ─────────────────────────────────
    # `[NE] Quest Name` — bearing prefix for quests whose predicate
    # has a target in the world. Quests without a target (journal_followup,
    # or destroy_kind with all entities gone) render without prefix.
    # Cap at 3 rows + "+N more" overflow line; full list in J overlay.
    quest_rows = _build_active_quest_rows(manifest)
    if quest_rows:
        fields.append("---")
        fields.extend(quest_rows)

    for i, text in enumerate(fields):
        _draw(text, x, y + i * line, color)


def _volley_score_lines(manifest: dict) -> list[str]:
    """Compose the score block under the VOLLEY CHAMBER header.

    Reads `manifest.match_state`. Mirrors `volley_scoring.hud_score_lines`
    but adds the live rally counter so the player can chase the long-rally
    threshold in real time. Per `feat_make-brain-ping-pong.md` PR 6.
    """
    ms = manifest.get("match_state") or {}
    if not ms:
        return []
    sets_won  = ms.get("sets_won")  or [0, 0]
    games     = ms.get("games")     or [0, 0]
    points    = ms.get("points")    or [0, 0]
    rally     = int(ms.get("rally_contacts") or 0)
    winner    = ms.get("match_winner")
    last      = ms.get("last_rally") or {}

    lines: list[str] = []
    lines.append(f"  SETS  {sets_won[0]} - {sets_won[1]}      "
                 f"GAMES  {games[0]} - {games[1]}")
    if winner:
        lines.append(f"  MATCH  {str(winner).upper()} WINS")
    else:
        p_label = _point_label(points[0], points[1])
        o_label = _point_label(points[1], points[0])
        lines.append(f"  GAME  {p_label} - {o_label}      RALLY {rally}")
    if last:
        rc = int(last.get("rally_contacts") or 0)
        thr = int(last.get("threshold") or 0)
        w = str(last.get("winner") or "?").upper()
        lines.append(f"  LAST RALLY  {rc} hits → {w} (≥{thr} = player)")
    return lines


def _brick_score_lines(manifest: dict) -> list[str]:
    """Brick Attack score + round telemetry block. Per V1 close-out 2026-05-04.

    Shows: current score / threshold + WIN banner, live round (hits, time
    elapsed), recent N rounds, aggregate summary (avg hits, avg time),
    AND a per-set summary table for combat-math experimental harness.
    """
    bricks = manifest.get("bricks") or {}
    items = bricks.get("items") or []
    if not items:
        return []
    score = int(bricks.get("score") or 0)
    threshold = int(bricks.get("threshold") or 0)
    win = bool(bricks.get("win"))
    set_name = str(bricks.get("set") or "?")
    intact = sum(1 for b in items if not b.get("destroyed"))
    total = len(items)

    out: list[str] = []
    out.append(f"  SET: {set_name}   (`mode <name>` to switch)")
    if win:
        out.append(f"  *** WIN! *** SCORE {score}      press SHIFT+R to reset / R for next round")
    else:
        out.append(f"  BRICKS {total - intact}/{total} hit    SCORE {score}/{threshold}")

    # Live round
    rnd = bricks.get("round") or {}
    rid = int(rnd.get("id") or 0)
    rcontacts = int(rnd.get("contacts") or 0)
    rdur = float(rnd.get("duration_s") or 0.0)
    if rid:
        out.append(f"  ROUND {rid}: {rcontacts} hits, {rdur:.1f}s")

    # Per-set summary table
    sets = bricks.get("sets") or []
    if sets:
        out.append("  SETS  ")
        for s in sets:
            marker = "▶" if s.get("active") else " "
            base = (f"  {marker} {s['name']:<14} {s['wins']:>3}/{s['target']:>3}")
            if "avg_contacts" in s:
                base += f"  avg {s['avg_contacts']}h / {s['avg_duration_s']}s"
            out.append(base)

    return out


def _point_label(side_pts: int, opp_pts: int) -> str:
    """Tennis-style label — duplicates volley_scoring.point_label so the
    HUD doesn't import a brain-side module."""
    if side_pts >= 3 and opp_pts >= 3:
        if side_pts == opp_pts:
            return "DEUCE"
        if side_pts > opp_pts:
            return "AD"
        return "—"
    return ("0", "15", "30", "40")[min(side_pts, 3)]


def _build_active_quest_rows(manifest: dict, max_rows: int = 3) -> list[str]:
    """Compose HUD row strings for the manifest's active quests.

    Reads `manifest.quests.{active, registry, bearings}` and produces
    `[NE] Quest Name` rows (or just "Quest Name" when no bearing).
    Up to `max_rows`; if more, appends a `+N more` summary line.
    """
    quests_block = manifest.get("quests") or {}
    active: list = list(quests_block.get("active") or [])
    if not active:
        return []
    registry: dict = quests_block.get("registry") or {}
    bearings: dict = quests_block.get("bearings") or {}

    rows: list[str] = []
    for qid in active[:max_rows]:
        meta = registry.get(qid) or {}
        name = str(meta.get("name", qid))
        bearing = str(bearings.get(qid, ""))
        if bearing:
            rows.append(f"[{bearing}] {_truncate(name, cfg.HUD_OBJECTIVE_MAX_CHARS)}")
        else:
            rows.append(f"     {_truncate(name, cfg.HUD_OBJECTIVE_MAX_CHARS)}")
    overflow = len(active) - max_rows
    if overflow > 0:
        rows.append(f"     +{overflow} more")
    return rows


def draw_encounter_panel(manifest: dict, color) -> None:
    """Encounter section below main HUD — only when action_options is non-empty."""
    encounter = manifest.get("encounter", {})
    options = encounter.get("action_options") or []
    if not options:
        return
    x = cfg.HUD_X
    y = cfg.HUD_ENCOUNTER_Y
    line = cfg.HUD_LINE_HEIGHT

    name = encounter.get("name") or encounter.get("kind") or "encounter"
    foe_hp = encounter.get("foe_hp")
    foe_max = encounter.get("foe_max_hp")

    rows = [f"ENCOUNTER {name}"]
    if foe_hp is not None and foe_max is not None:
        rows.append(f"FOE HP {foe_hp}/{foe_max}")
    rows.append("ACTIONS:")
    for i in range(min(len(options), 9)):
        action = action_for_key_index(options, i) or "?"
        rows.append(f"[{i + 1}] {action}")
    for i, text in enumerate(rows):
        _draw(text, x, y + i * line, color)


def _truncate(s: str, max_chars: int) -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars - 3] + "..."


def _draw(text: str, x: int, y: int, color) -> None:
    rl.draw_text_ex(_FONT, text, rl.Vector2(x, y), cfg.HUD_FONT_SIZE, 1.0, color)


def draw_inventory_modal(manifest: dict, color, screen_w: int, screen_h: int) -> None:
    """Full-screen modal: dim background + amber-bordered inventory list."""
    if _FONT is None:
        load_font()
    rl.draw_rectangle(0, 0, screen_w, screen_h, (0, 0, 0, 200))
    panel_w = 480
    panel_h = 360
    px = (screen_w - panel_w) // 2
    py = (screen_h - panel_h) // 2
    rl.draw_rectangle(px, py, panel_w, panel_h, (0, 0, 0, 240))
    rl.draw_rectangle_lines(px, py, panel_w, panel_h, color)

    inner_x = px + 24
    line = cfg.INV_MODAL_LINE_HEIGHT
    _draw("INVENTORY", inner_x, py + 20, color)
    player = manifest.get("player", {})
    equipped = player.get("equipped") or "-"
    inventory = player.get("inventory", [])
    _draw(f"EQUIPPED  {equipped}", inner_x, py + 20 + line, color)
    _draw("---", inner_x, py + 20 + line * 2, color)
    if not inventory:
        _draw("(empty)", inner_x, py + 20 + line * 3, color)
    else:
        for i, item in enumerate(inventory[:10]):
            name = item.get("name", "?")
            slot_cost = item.get("slot_cost", 1)
            _draw(f"{i + 1}. {name}  [{slot_cost} slot]", inner_x, py + 20 + line * (3 + i), color)


def draw_status_chip(text: str, screen_w: int, color) -> None:
    """Tiny right-aligned status chip (e.g. NOCLIP indicator)."""
    if _FONT is None:
        load_font()
    rl.draw_text_ex(_FONT, text, rl.Vector2(screen_w - 120, 12), cfg.HUD_FONT_SIZE, 1.0, color)


def draw_build_overlay(lines: list[str], color) -> None:
    """Render BUILD-mode HUD lines at top-left. Drawn AFTER `draw_hud`
    so it overlays the live status block — visually announces that
    normal play input is suspended in favor of authoring.

    Caller composes the lines via `build_mode.hud_lines()`. Empty list
    is a no-op (caller passes empty when BUILD is inactive)."""
    if not lines:
        return
    if _FONT is None:
        load_font()
    x = cfg.HUD_X
    y = cfg.HUD_Y
    line_h = cfg.HUD_LINE_HEIGHT
    # Solid backing rectangle so the BUILD block reads on top of the
    # existing identity/status fields without bleed-through.
    height = line_h * len(lines) + 12
    rl.draw_rectangle(x - 6, y - 6, 540, height, (0, 0, 0, 220))
    for i, text in enumerate(lines):
        _draw(text, x, y + i * line_h, color)
