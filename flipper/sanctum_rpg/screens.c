/* screens.c — every screen of the Flipper RPG, drawn from the game's state
 * (game.h) onto a Flipper Canvas. Reads the state; never changes it.
 * Moved out of sanctum_rpg.c unchanged (2026-11-06).
 */

#include "screens.h"

#include <gui/gui.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "render_fpv.h"

/* ─── tunables (no hardcoded literals in render code — per AGENTS.md) ─── */

#define SCREEN_W              128
#define SCREEN_H              64

#define TITLE_TEXT            "SANCTUM"
/* Layout tuned to fit 5 menu items (Continue/Load/New Game/Codex/Settings)
 * + the footer hint within 64px with no overlap. Header pulled up, line
 * height tightened: items land at 21,29,37,45,53; footer at 63. */
#define TITLE_BASELINE_Y      10
#define DIVIDER_Y             13

#define MENU_FIRST_BASELINE_Y 21
#define MENU_LINE_HEIGHT      8
#define MENU_TEXT_X           8
#define MENU_HIGHLIGHT_INSET  2

#define FOOTER_BASELINE_Y     63
#define FOOTER_TITLE          "OK select  Back quit"
#define FOOTER_PICKER         "OK pick  Back cancel"
#define FOOTER_PICKER_EMPTY   "Back cancel"
#define FOOTER_WORLD          "OK look  Back menu"
#define FOOTER_EXAMINE        "move  OK/Back done"
#define PICKER_FIRST_BASELINE 22    /* match the tightened title layout */
#define PICKER_SCROLL_HINT_X  120

/* World render */
#define TILE_PX               8                       /* tile cell, 8x8 */
#define WORLD_VIEW_W          (WORLD_COLS * TILE_PX)  /* 128 px */
#define WORLD_VIEW_H          (WORLD_ROWS * TILE_PX)  /*  48 px */
#define WORLD_TILE_BASELINE_Y_OFFSET 7                /* FontSecondary baseline within 8px cell */
#define WORLD_STATUS_BASELINE 56                      /* below the grid */
#define WORLD_HINT_BASELINE   63                      /* corner hint */

static const char* const MENU_LABELS[MenuCount] = {
    [MenuContinue] = "Continue",
    [MenuLoad]     = "Load",
    [MenuNewGame]  = "New Game",
    [MenuCodex]    = "Codex",
    [MenuSettings] = "Settings",
};

/* ─── render: title ───────────────────────────────────────────────── */

static void draw_title_screen(Canvas* canvas, const AppState* st) {
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, TITLE_BASELINE_Y, AlignCenter, AlignBottom, TITLE_TEXT);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    canvas_set_font(canvas, FontSecondary);
    for(MenuItem i = 0; i < MenuCount; i++) {
        int y = MENU_FIRST_BASELINE_Y + i * MENU_LINE_HEIGHT;
        bool selected = (i == st->cursor);
        /* The Settings row shows + toggles the sound state inline. */
        const char* label = (i == MenuSettings)
                                ? (st->muted ? "Sound: muted" : "Sound: on")
                                : MENU_LABELS[i];
        if(selected) {
            canvas_draw_box(
                canvas,
                MENU_HIGHLIGHT_INSET,
                y - (MENU_LINE_HEIGHT - 2),
                SCREEN_W - 2 * MENU_HIGHLIGHT_INSET,
                MENU_LINE_HEIGHT);
            canvas_invert_color(canvas);
            canvas_draw_str(canvas, MENU_TEXT_X, y, label);
            canvas_invert_color(canvas);
        } else {
            canvas_draw_str(canvas, MENU_TEXT_X, y, label);
        }
    }

    const char* footer = st->status_line ? st->status_line : FOOTER_TITLE;
    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom, footer);
}

/* ─── render: load picker ─────────────────────────────────────────── */

static void draw_picker_screen(Canvas* canvas, const AppState* st) {
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, TITLE_BASELINE_Y, AlignCenter, AlignBottom, "Load");
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    canvas_set_font(canvas, FontSecondary);
    const LoadPicker* p = &st->picker;

    if(p->count == 0) {
        canvas_draw_str_aligned(
            canvas, SCREEN_W / 2, SCREEN_H / 2,
            AlignCenter, AlignCenter, "no saves yet");
        canvas_draw_str_aligned(
            canvas, SCREEN_W / 2, FOOTER_BASELINE_Y,
            AlignCenter, AlignBottom, FOOTER_PICKER_EMPTY);
        return;
    }

    int end = p->scroll_offset + PICKER_VISIBLE_ROWS;
    if(end > p->count) end = p->count;
    for(int row = p->scroll_offset, i = 0; row < end; row++, i++) {
        int y = PICKER_FIRST_BASELINE + i * MENU_LINE_HEIGHT;
        bool selected = (row == p->cursor);
        char line[40];
        snprintf(line, sizeof(line), "%s  %s",
                 p->items[row].campaign_id, p->items[row].character_name);
        if(selected) {
            canvas_draw_box(
                canvas,
                MENU_HIGHLIGHT_INSET,
                y - (MENU_LINE_HEIGHT - 2),
                SCREEN_W - 2 * MENU_HIGHLIGHT_INSET,
                MENU_LINE_HEIGHT);
            canvas_invert_color(canvas);
            canvas_draw_str(canvas, MENU_TEXT_X, y, line);
            canvas_invert_color(canvas);
        } else {
            canvas_draw_str(canvas, MENU_TEXT_X, y, line);
        }
    }

    if(p->scroll_offset > 0) {
        canvas_draw_str(canvas, PICKER_SCROLL_HINT_X, PICKER_FIRST_BASELINE, "^");
    }
    if(end < p->count) {
        canvas_draw_str(
            canvas, PICKER_SCROLL_HINT_X,
            PICKER_FIRST_BASELINE + (PICKER_VISIBLE_ROWS - 1) * MENU_LINE_HEIGHT, "v");
    }

    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y,
        AlignCenter, AlignBottom, FOOTER_PICKER);
}

/* The status strip's right-hand readouts (weather glyph, facing, bearing)
 * share a baseline with the message. They step aside rather than overlap
 * it: a message is transient, and they return on the next step. True if a
 * readout `w` px wide ending at `right` fits clear of the message. */
#define HUD_GAP 3
static bool hud_fits(Canvas* canvas, const AppState* st, int right, int w) {
    if(!st->status_line) return true;
    int used = canvas_string_width(canvas, st->status_line);
    if(st->status_rune) used += 10 + st->status_marks * 3;   /* the clue's rune and marks */
    return used + HUD_GAP <= right - w;
}

/* The foul patch, top-down: a sparse stipple unlike the haze's. */
static const uint8_t FOUL_XBM[8] = {0x00, 0x24, 0x00, 0x81, 0x00, 0x24, 0x00, 0x81};

static void draw_world_screen(Canvas* canvas, const AppState* st) {
    canvas_set_font(canvas, FontSecondary);

    /* Tile grid with FOV: lit = full glyph; seen-but-unlit = remembered
     * terrain (loot hidden — you don't see current state of dark tiles);
     * never-seen = dark (drawn nothing). The lit-vs-remembered dimming is
     * identical on the font renderer; the dither distinction arrives with
     * the render engine. The visible mechanic now is the pool of light
     * vs darkness that shrinks as fuel burns down. */
    for(int y = 0; y < WORLD_ROWS; y++) {
        for(int x = 0; x < WORLD_COLS; x++) {
            char tile = st->world.tiles[y][x];
            char glyph;
            if(st->lit[y][x]) {
                glyph = tile;
                /* Atmosphere: rain/storm overlay — replace the glyph on
                 * a fraction of lit floor cells per turn so motion is
                 * visible. The overlay only shows on FLOOR-like tiles
                 * to keep terrain stamps + creatures readable. */
                if(tile == TILE_FLOOR &&
                   weather_tile_has_overlay(
                       &st->current_weather, st->character.turn, x, y)) {
                    /* Glyph by weather kind:
                     *   RAIN       → ' (drop)
                     *   STORM      → " (heavier rain)
                     *   HEAT       → ~ (shimmer line — only collides with
                     *                   deadfall on deadfall tiles, never on FLOOR)
                     *   DUST_STORM → _ (low blowing dust) */
                    glyph = weather_overlay_glyph((WeatherKind)st->current_weather.kind);
                }
            } else if(st->seen[y][x]) {
                glyph = loot_is_item_glyph(tile) ? TILE_FLOOR : tile;
            } else {
                continue; /* unseen → dark */
            }
            /* An edge closed by corruption: the haze under the glyph (spec 58). */
            if(world_cell_in_haze(&st->world, x, y))
                canvas_draw_xbm(canvas, x * TILE_PX, y * TILE_PX, TILE_PX, TILE_PX, WORLD_HAZE_XBM);
            /* A bloated one's foul patch, while it lasts (spec 50 Q1 §Q.3). */
            if(st->lit[y][x] && foul_at(&st->foul, x, y, st->character.turn))
                canvas_draw_xbm(canvas, x * TILE_PX, y * TILE_PX, TILE_PX, TILE_PX, FOUL_XBM);
            /* A hollow's mouth: a broken line under it (spec 58 §58.15). */
            if(st->world.hollow_open && x == st->world.hollow_x && y == st->world.hollow_y)
                for(int k = 0; k < TILE_PX; k += 2)
                    canvas_draw_dot(canvas, x * TILE_PX + k, y * TILE_PX + TILE_PX - 1);
            /* A sealed site: a bar under it, the seal you set (spec 58 §58.8). */
            if(x == st->world.site_x && y == st->world.site_y &&
               st->world.site_state == SITE_SHOWS_SEALED)
                canvas_draw_line(canvas, x * TILE_PX, y * TILE_PX + TILE_PX - 1,
                                 x * TILE_PX + TILE_PX - 1, y * TILE_PX + TILE_PX - 1);
            /* A terrain row or item kind may carry its own top-down form
             * (map_icon) where the glyph alone would mislead or spill. */
            const uint8_t* icon = terrain_map_icon(glyph);
            if(!icon) icon = loot_map_icon(glyph);
            if(icon) {
                canvas_draw_xbm(canvas, x * TILE_PX, y * TILE_PX, TILE_PX, TILE_PX, icon);
                continue;
            }
            char buf[2] = {glyph, '\0'};
            canvas_draw_str(canvas, x * TILE_PX, y * TILE_PX + WORLD_TILE_BASELINE_Y_OFFSET, buf);
        }
    }

    /* Creatures — only where currently lit (you see one only if you can see
     * it now; never in seen-but-dark memory, since they move). Over terrain,
     * under the player. v0.4.0b: static glyph; movement + state cues land
     * with the FSM tick slice. */
    for(int i = 0; i < st->creature_count; i++) {
        const Creature* c = &st->creatures[i];
        if(!c->alive || !st->lit[c->y][c->x]) continue;
        const Family* f = creature_family(c->family_id);
        char cbuf[2] = {f ? f->glyph : '?', '\0'};
        int gx = c->x * TILE_PX;
        int gy = c->y * TILE_PX + WORLD_TILE_BASELINE_Y_OFFSET;
        /* Flight reads as hovering — 1px bob on even turns. */
        if(f && (f->move_flags & CF_FLIGHT) && (st->character.turn & 1u) == 0) gy -= 1;
        if(c->state == CR_APPROACH || c->state == CR_ENGAGE) {
            /* Closing/aggro → inverted cell (the heavy "threat" cue). */
            canvas_draw_box(canvas, c->x * TILE_PX, c->y * TILE_PX, TILE_PX, TILE_PX);
            canvas_invert_color(canvas);
            canvas_draw_str(canvas, gx, gy, cbuf);
            canvas_invert_color(canvas);
        } else {
            canvas_draw_str(canvas, gx, gy, cbuf);
            /* Fleeing → 1px corner pip (light "disengaging" cue). */
            if(c->state == CR_FLEE) {
                canvas_draw_dot(canvas, c->x * TILE_PX + TILE_PX - 1, c->y * TILE_PX);
            }
        }
    }

    /* Player overlay (always visible) */
    canvas_draw_str(
        canvas,
        st->character.player_x * TILE_PX,
        st->character.player_y * TILE_PX + WORLD_TILE_BASELINE_Y_OFFSET,
        "@");

    /* Examine cursor — a frame around the inspected cell. */
    if(st->examining) {
        canvas_draw_frame(
            canvas, st->examine_x * TILE_PX, st->examine_y * TILE_PX, TILE_PX, TILE_PX);
    }

    /* Separator between the world grid (y < WORLD_VIEW_H) and the status
     * strip — keeps row-5 glyphs from visually colliding with status text. */
    canvas_draw_line(canvas, 0, WORLD_VIEW_H, SCREEN_W - 1, WORLD_VIEW_H);

    /* Status line: examine name while looking; else transient status / stats. */
    if(st->examining) {
        canvas_draw_str(canvas, 0, WORLD_STATUS_BASELINE,
                        examine_name(st, st->examine_x, st->examine_y));
    } else if(st->status_line) {
        canvas_draw_str(canvas, 0, WORLD_STATUS_BASELINE, st->status_line);
        if(st->status_rune) {   /* a seen clue: the rune, and its place as marks */
            int x = canvas_string_width(canvas, st->status_line) + 3;
            canvas_draw_xbm(canvas, x, WORLD_STATUS_BASELINE - 7, 8, 8, st->status_icon);
            for(int k = 0; k < st->status_marks; k++)
                canvas_draw_box(canvas, x + 10 + k * 3, WORLD_STATUS_BASELINE - 2, 2, 2);
        }
    } else {
        char stats[40];
        snprintf(stats, sizeof(stats), "HP%u/%u MP%u/%u F%u",
                 st->character.hp, st->character.max_hp,
                 st->character.mp, st->character.max_mp,
                 st->character.torch_fuel);
        canvas_draw_str(canvas, 0, WORLD_STATUS_BASELINE, stats);
    }

    /* Persistent weather indicator (slice 2026-06-03b — make weather
     * strategic). Right-anchored on the status strip so it's visible
     * EVERY frame even after the chunk-enter hint times out. CLEAR
     * weather draws nothing — absence reads as clarity. */
    {
        char wg = weather_hud_glyph(&st->current_weather);
        char wbuf[2] = {wg, '\0'};
        if(wg != '\0' && !st->examining &&
           hud_fits(canvas, st, SCREEN_W, canvas_string_width(canvas, wbuf))) {
            canvas_draw_str_aligned(
                canvas, SCREEN_W, WORLD_STATUS_BASELINE,
                AlignRight, AlignBottom, wbuf);
        }
    }

    /* Persistent home-bearing indicator (slice 2026-06-03d follow-up:
     * the vault at chunk (0,0) is useless if you can't find your way
     * back). Direction + Chebyshev distance to (0,0), e.g. "NE3", "W1".
     * Right-anchored at SCREEN_W-8 so the weather glyph's 1-char slot
     * sits cleanly to its right. Hidden when at home — the vault tile
     * itself is the "you're here" cue. */
    {
        int8_t sx, sy;
        uint16_t dist;
        bearing_to_home(
            (int)st->character.chunk_x, (int)st->character.chunk_y,
            &sx, &sy, &dist);
        char hbuf[8];
        snprintf(hbuf, sizeof(hbuf), "%s%u", bearing_label(sx, sy), (unsigned)dist);
        if(dist > 0 && !st->examining &&
           hud_fits(canvas, st, SCREEN_W - 8, canvas_string_width(canvas, hbuf))) {
            canvas_draw_str_aligned(
                canvas, SCREEN_W - 8, WORLD_STATUS_BASELINE,
                AlignRight, AlignBottom, hbuf);
        }
    }

    /* Corner hint */
    canvas_draw_str_aligned(
        canvas, SCREEN_W, WORLD_HINT_BASELINE, AlignRight, AlignBottom,
        st->examining ? FOOTER_EXAMINE : FOOTER_WORLD);
}

static void draw_codex_screen(Canvas* canvas, const AppState* st) {
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, TITLE_BASELINE_Y, AlignCenter, AlignBottom, "Codex");

    int loot_found = 0;
    for(int i = 0; i < KIND_COUNT; i++) {
        if((st->codex_identified >> KIND_CATALOG[i].id) & 1ull) loot_found++;
    }
    int beasts_found = 0;
    for(int i = 0; i < CREATURE_FAMILY_COUNT; i++) {
        if(creature_bestiary_grade(st->codex_bestiary, (uint8_t)i) > 0) beasts_found++;
    }
    char hdr[48];
    snprintf(
        hdr, sizeof(hdr), "L%d/%d B%d/%d", loot_found, KIND_COUNT, beasts_found,
        CREATURE_FAMILY_COUNT);
    canvas_set_font(canvas, FontSecondary);
    canvas_draw_str_aligned(canvas, SCREEN_W, TITLE_BASELINE_Y, AlignRight, AlignBottom, hdr);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    /* One scrolling list: loot kinds, the creature bestiary, then the ledger. */
    int total = codex_rows(st);
    int end = st->codex_scroll + PICKER_VISIBLE_ROWS;
    if(end > total) end = total;
    for(int row = st->codex_scroll, i = 0; row < end; row++, i++) {
        int y = PICKER_FIRST_BASELINE + i * MENU_LINE_HEIGHT;
        char line[40];
        if(row < KIND_COUNT) {
            const KindDef* k = &KIND_CATALOG[row];
            bool known = ((st->codex_identified >> k->id) & 1ull) != 0;
            if(known) {
                snprintf(line, sizeof(line), "%c  %s", k->glyph, k->true_name);
            } else {
                snprintf(line, sizeof(line), "?  ???");
            }
        } else if(row >= KIND_COUNT + CREATURE_FAMILY_COUNT) {
            if(!arc_ledger_line(st->codex_seed, &st->region_book, st->codex_words,
                                row - KIND_COUNT - CREATURE_FAMILY_COUNT, line, sizeof(line)))
                line[0] = '\0';
        } else {
            int fam = row - KIND_COUNT;
            const Family* f = creature_family((uint8_t)fam);
            int grade = creature_bestiary_grade(st->codex_bestiary, (uint8_t)fam);
            if(grade > 0 && f) {
                const char* g =
                    (grade >= 3) ? "mastered" : (grade == 2 ? "studied" : "seen");
                snprintf(line, sizeof(line), "%c  %s (%s)", f->glyph, f->root, g);
            } else {
                snprintf(line, sizeof(line), "?  ?????");
            }
        }
        canvas_draw_str(canvas, MENU_TEXT_X, y, line);
    }
    if(st->codex_scroll > 0) {
        canvas_draw_str(canvas, PICKER_SCROLL_HINT_X, PICKER_FIRST_BASELINE, "^");
    }
    if(end < total) {
        canvas_draw_str(canvas, PICKER_SCROLL_HINT_X,
                        PICKER_FIRST_BASELINE + (PICKER_VISIBLE_ROWS - 1) * MENU_LINE_HEIGHT, "v");
    }
    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom, "Back done");
}
static const char* const CV_LABEL[CV_COUNT] = {"STRIKE", "FLEE", "SKILL", "THROW"};

/* Combat encounter (v0.4.1) — foe name + HP bar + STRIKE/FLEE menu + log. */
static void draw_combat_screen(Canvas* canvas, const AppState* st) {
    if(st->combat_foe < 0 || st->combat_foe >= st->creature_count) return;
    const Creature* foe = &st->creatures[st->combat_foe];
    CreatureDef d;
    creature_compose(foe->family_id, foe->trait_id, &d);
    char nm[24];
    creature_name(&d, nm, sizeof(nm));

    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, nm);

    canvas_set_font(canvas, FontSecondary);
    char hp[16];
    snprintf(hp, sizeof(hp), "%u/%u", (unsigned)st->combat_foe_hp, (unsigned)d.hp);
    canvas_draw_str_aligned(canvas, SCREEN_W, TITLE_BASELINE_Y, AlignRight, AlignBottom, hp);

    int bw = 90, bh = 6, by = 16;  /* HP bar shortened by 10px to clear the foe portrait */
    canvas_draw_frame(canvas, 0, by, bw, bh);
    int filled = (d.hp > 0) ? (int)((bw - 2) * (int)st->combat_foe_hp / (int)d.hp) : 0;
    if(filled > 0) canvas_draw_box(canvas, 1, by + 1, filled, bh - 2);
    canvas_draw_line(canvas, 0, 24, SCREEN_W - 1, 24);

    /* Foe portrait — Atlus pattern. 32x32 on the right, below the HP bar,
     * beside the verb menu. COMPOSED from the foe's family x trait (figure.h)
     * in its strike pose — it is fighting you — stepping its frame each turn.
     * Opaque: the mask is laid down in background first, then the ink. */
    {
        static uint8_t fig_ink[FIGURE_PLANE_BYTES], fig_mask[FIGURE_PLANE_BYTES];
        if(figure_compose(&RENDER_BUDGET_FLIPPER_1BIT, foe->family_id, foe->trait_id,
                          POSE_STRIKE, (uint8_t)(st->character.turn & 1u),
                          fig_ink, fig_mask)) {
            canvas_set_color(canvas, ColorWhite);
            canvas_draw_xbm(canvas, 96, 26, 32, 32, fig_mask);
            canvas_set_color(canvas, ColorBlack);
            canvas_draw_xbm(canvas, 96, 26, 32, 32, fig_ink);
        }
    }

    uint8_t verbs[CV_COUNT];
    int nverbs = combat_verbs(st, verbs);
    for(int i = 0; i < nverbs; i++) {
        int y = 34 + i * MENU_LINE_HEIGHT;
        if(i == st->combat_cursor) {
            canvas_draw_box(
                canvas, MENU_HIGHLIGHT_INSET, y - (MENU_LINE_HEIGHT - 2), 50, MENU_LINE_HEIGHT);
            canvas_invert_color(canvas);
            canvas_draw_str(canvas, MENU_TEXT_X, y, CV_LABEL[verbs[i]]);
            canvas_invert_color(canvas);
        } else {
            canvas_draw_str(canvas, MENU_TEXT_X, y, CV_LABEL[verbs[i]]);
        }
    }

    if(st->status_line) {
        canvas_draw_str(canvas, 0, WORLD_STATUS_BASELINE, st->status_line);
    }
    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom, "OK act  Back flee");
}

/* Class picker (slice 1c): one card at a time, d-pad cycles through 4. */
static void draw_class_pick_screen(Canvas* canvas, const AppState* st) {
    const ClassDef* cls = class_def(st->pending_class_id);
    if(!cls) return;

    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, cls->name);

    canvas_set_font(canvas, FontSecondary);
    char counter[12];
    snprintf(
        counter, sizeof(counter), "%u/%u",
        (unsigned)(st->pending_class_id + 1), (unsigned)CLASS_COUNT);
    canvas_draw_str_aligned(
        canvas, SCREEN_W, TITLE_BASELINE_Y, AlignRight, AlignBottom, counter);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    canvas_draw_str(canvas, 0, 22, cls->tagline);

    if(st->pending_class_id == CLASS_WANDERER) {
        canvas_draw_str(canvas, 0, 34, "(custom build —");
        canvas_draw_str(canvas, 0, 42, "pick to allocate)");
    } else {
        /* Slice 48.F1 — axes BODY/CRAFT/SIGHT/MIND/HEART/WILL replace
         * STR/DEX/WIS/INT/CHA/CON. Labels are truncated to fit the row
         * (4-char names: BODY/CRFT/SGHT/MIND/HRT/WILL — 4 chars max for
         * "%-4s %2u" within 60px). */
        char line[24];
        snprintf(
            line, sizeof(line), "BODY %2u  CRFT %2u",
            (unsigned)cls->body, (unsigned)cls->craft);
        canvas_draw_str(canvas, 0, 34, line);
        snprintf(
            line, sizeof(line), "SGHT %2u  MIND %2u",
            (unsigned)cls->sight, (unsigned)cls->mind);
        canvas_draw_str(canvas, 0, 42, line);
        snprintf(
            line, sizeof(line), "HRT  %2u  WILL %2u",
            (unsigned)cls->heart, (unsigned)cls->will);
        canvas_draw_str(canvas, 0, 50, line);
    }

    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom,
        "OK pick  Back exit");
}

/* Stat point-buy (slice 1c): 6 stats in a 2-col grid, L/R adjust selected. */
/* Profile review (slice 48.F3 — formerly "Build") — shows the user's name
 * + the 6 axes, editable within the 66-point budget. Replaces ScreenClassPick
 * in the New-Game flow; the only PC class is CLASS_YOU. */
static void draw_stat_buy_screen(Canvas* canvas, const AppState* st) {
    canvas_set_font(canvas, FontPrimary);
    /* Title = user's display name (slice 48.F2 — "You ARE the player").
     * Falls back to the class name "You" if the display_name slot is empty
     * (pre-first-launch path before finalize_new_character runs). */
    const char* header = (st->display_name[0] != '\0') ? st->display_name : "You";
    canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, header);

    canvas_set_font(canvas, FontSecondary);
    int total = (int)st->character.body  + (int)st->character.craft +
                (int)st->character.sight + (int)st->character.mind  +
                (int)st->character.heart + (int)st->character.will;
    int budget = 66 - total;
    char hdr[24];
    snprintf(hdr, sizeof(hdr), "pts %d", budget);
    canvas_draw_str_aligned(
        canvas, SCREEN_W, TITLE_BASELINE_Y, AlignRight, AlignBottom, hdr);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    /* Slice 48.F1 — axis labels BODY/CRFT/SGHT/MIND/HRT/WILL (4-char names
     * to fit the 60-px grid cell). Cursor order matches the §1 axis order:
     * BODY first, WILL last. */
    static const char* const STAT_NAMES[6] = {
        "BODY", "CRFT", "SGHT", "MIND", "HRT", "WILL"};
    const uint8_t stats[6] = {
        st->character.body,  st->character.craft, st->character.sight,
        st->character.mind,  st->character.heart, st->character.will,
    };
    for(int i = 0; i < 6; i++) {
        int row = i / 2;
        int col = i % 2;
        int x = col * 64;
        int y = 24 + row * 10;
        bool selected = (st->stat_buy_cursor == i);
        char line[16];
        snprintf(line, sizeof(line), "%s %2u", STAT_NAMES[i], (unsigned)stats[i]);
        if(selected) {
            canvas_draw_box(canvas, x, y - 7, 60, 9);
            canvas_invert_color(canvas);
            canvas_draw_str(canvas, x + 2, y, line);
            canvas_invert_color(canvas);
        } else {
            canvas_draw_str(canvas, x + 2, y, line);
        }
    }

    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom,
        "L/R adj  OK done");
}

/* Stash screen: two columns showing inv_qty vs vault_qty per kind.
 * Cursor selects a row; focus toggles Bag/Vault; OK transfers one. */
/* FPV world view (slice 2026-06-03e) — Etrian-style first-person live
 * render of the current chunk from the player's facing. Reuses the
 * existing status strip / bearing / weather HUD so the world feels
 * unified across views. */
static void draw_fpv_world_screen(Canvas* canvas, const AppState* st) {
    render_fpv_world(
        canvas, &st->world,
        (int)st->character.player_x, (int)st->character.player_y,
        st->character.facing,
        st->creatures, st->creature_count);
    /* Divider + status strip, identical to draw_world_screen so the
     * HUD doesn't visibly shift between view modes. */
    canvas_draw_line(canvas, 0, WORLD_VIEW_H, SCREEN_W - 1, WORLD_VIEW_H);
    canvas_set_font(canvas, FontSecondary);
    if(st->status_line) {
        canvas_draw_str(canvas, 0, WORLD_STATUS_BASELINE, st->status_line);
    } else {
        char stats[40];
        snprintf(stats, sizeof(stats), "HP%u/%u F%u",
                 st->character.hp, st->character.max_hp,
                 st->character.torch_fuel);
        canvas_draw_str(canvas, 0, WORLD_STATUS_BASELINE, stats);
    }
    /* Weather glyph (right edge, matches world view). */
    {
        char wg = weather_hud_glyph(&st->current_weather);
        char wbuf[2] = {wg, '\0'};
        if(wg != '\0' && hud_fits(canvas, st, SCREEN_W, canvas_string_width(canvas, wbuf))) {
            canvas_draw_str_aligned(
                canvas, SCREEN_W, WORLD_STATUS_BASELINE,
                AlignRight, AlignBottom, wbuf);
        }
    }
    /* Facing indicator + bearing — bottom-right corner. */
    {
        static const char* face_lbl[4] = {"N", "E", "S", "W"};
        int8_t sx, sy;
        uint16_t dist;
        bearing_to_home(
            (int)st->character.chunk_x, (int)st->character.chunk_y,
            &sx, &sy, &dist);
        char fbuf[16];
        if(dist > 0) {
            snprintf(fbuf, sizeof(fbuf), "%s %s%u",
                     face_lbl[st->character.facing & 3u],
                     bearing_label(sx, sy), (unsigned)dist);
        } else {
            snprintf(fbuf, sizeof(fbuf), "%s",
                     face_lbl[st->character.facing & 3u]);
        }
        if(hud_fits(canvas, st, SCREEN_W - 8, canvas_string_width(canvas, fbuf)))
            canvas_draw_str_aligned(
                canvas, SCREEN_W - 8, WORLD_STATUS_BASELINE,
                AlignRight, AlignBottom, fbuf);
    }
}

static void draw_stash_screen(Canvas* canvas, const AppState* st) {
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, "Vault");
    canvas_set_font(canvas, FontSecondary);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    /* Column headers: BAG | VAULT.  Highlight the focused one. */
    const int col_bag_x = 12;
    const int col_vault_x = 70;
    const char* bag_label = "BAG";
    const char* vault_label = "VAULT";
    int hdr_y = 22;
    if(st->stash_focus == 0) {
        canvas_draw_box(canvas, col_bag_x - 2, hdr_y - 7, 24, 8);
        canvas_invert_color(canvas);
        canvas_draw_str(canvas, col_bag_x, hdr_y, bag_label);
        canvas_invert_color(canvas);
        canvas_draw_str(canvas, col_vault_x, hdr_y, vault_label);
    } else {
        canvas_draw_str(canvas, col_bag_x, hdr_y, bag_label);
        canvas_draw_box(canvas, col_vault_x - 2, hdr_y - 7, 28, 8);
        canvas_invert_color(canvas);
        canvas_draw_str(canvas, col_vault_x, hdr_y, vault_label);
        canvas_invert_color(canvas);
    }

    /* Rows — one per KIND_COUNT entry, glyph + qty in each column.
     * Up to 4 visible at once; scroll keeps cursor in view. */
    int n = KIND_COUNT;
    int cursor = st->stash_cursor;
    if(cursor < 0) cursor = 0;
    if(cursor >= n) cursor = n - 1;
    int first = 0;
    if(cursor > 3) first = cursor - 3;
    int last = first + 4;
    if(last > n) last = n;
    for(int row = first, i = 0; row < last; row++, i++) {
        const KindDef* k = kind_by_id((uint8_t)row);
        if(!k) continue;
        int y = 32 + i * 8;
        char line_bag[20], line_vault[20];
        snprintf(line_bag,   sizeof(line_bag),   "%c x%u",
                 k->glyph, (unsigned)st->character.inv_qty[row]);
        snprintf(line_vault, sizeof(line_vault), "%c x%u",
                 k->glyph, (unsigned)st->character.vault_qty[row]);
        if(row == cursor) {
            canvas_draw_box(canvas, 0, y - 7, SCREEN_W, 8);
            canvas_invert_color(canvas);
            canvas_draw_str(canvas, col_bag_x,   y, line_bag);
            canvas_draw_str(canvas, col_vault_x, y, line_vault);
            canvas_invert_color(canvas);
        } else {
            canvas_draw_str(canvas, col_bag_x,   y, line_bag);
            canvas_draw_str(canvas, col_vault_x, y, line_vault);
        }
    }

    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom,
        st->stash_focus == 0 ? "OK stash  <> focus  Back" : "OK take  <> focus  Back");
}

/* Forge (slice 4 + Thread B animation) — single-recipe card view; during a
 * pull, the recipe card is overlaid with a 3-reel slot animation that
 * cycles glyphs and settles on a tier-appropriate pattern. */
static void draw_craft_screen(Canvas* canvas, const AppState* st) {
    if(st->craft_cursor == RECIPE_COUNT) {   /* the experiment card (spec 50 Q1 §Q.10.2) */
        canvas_set_font(canvas, FontPrimary);
        canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, "Forge");
        canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);
        canvas_set_font(canvas, FontSecondary);
        canvas_draw_str_aligned(canvas, SCREEN_W / 2, 32, AlignCenter, AlignBottom, AF_LINE_DARK);
        if(st->status_line) canvas_draw_str(canvas, 0, 52, st->status_line);
        canvas_draw_str_aligned(canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom,
                                "OK try  <> card  Back");
        return;
    }
    const RecipeDef* r = recipe_def((uint8_t)st->craft_cursor);
    if(!r) return;

    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, "Forge");

    /* Thread B — animation overlay. When craft_anim_frame > 0, replace
     * the recipe card with the 3 slot reels + a spinning hint. The reel
     * glyphs are updated each frame in craft_pull's animation loop. */
    if(st->craft_anim_frame > 0) {
        canvas_set_font(canvas, FontSecondary);
        canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);
        /* Centered text label by phase. */
        const char* phase = (st->craft_anim_frame < CRAFT_ANIM_SPIN_FRAMES)
                                ? "the work turns"
                                : "...";
        canvas_draw_str_aligned(
            canvas, SCREEN_W / 2, 22, AlignCenter, AlignBottom, phase);
        /* 3 reel boxes — big glyphs centered. Each ~18px wide, 24px tall,
         * spaced ~30px apart, baseline at y=50. */
        canvas_set_font(canvas, FontPrimary);
        for(int slot = 0; slot < 3; slot++) {
            int cx = 24 + slot * 40;     /* centers at 24, 64, 104 */
            int x = cx - 9;               /* box top-left x */
            int y = 30;                   /* box top-left y */
            canvas_draw_frame(canvas, x, y, 18, 18);
            char buf[2] = {st->craft_reel_glyphs[slot], '\0'};
            canvas_draw_str_aligned(
                canvas, cx, y + 14, AlignCenter, AlignBottom, buf);
        }
        canvas_set_font(canvas, FontSecondary);
        canvas_draw_str_aligned(
            canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom,
            "rolling...");
        return; /* skip the recipe card while animating */
    }

    canvas_set_font(canvas, FontSecondary);
    /* The card's place among the recipes you KNOW: a hidden recipe is
     * never counted (no numbers that tell you there's more, 43 §17.10). */
    int known = 0, place = 0;
    for(int i = 0; i < RECIPE_COUNT; i++)
        if(recipe_known((uint8_t)i, st->character.recipes_known)) {
            known++;
            if(i == st->craft_cursor) place = known;
        }
    char counter[24];
    snprintf(counter, sizeof(counter), "%d/%d", place, known);
    canvas_draw_str_aligned(
        canvas, SCREEN_W, TITLE_BASELINE_Y, AlignRight, AlignBottom, counter);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    canvas_draw_str(canvas, 0, 22, r->name);

    char line[48];
    /* Input A */
    const KindDef* ka = kind_by_id(r->input_kind_a);
    int have_a = (r->input_kind_a < SAVE_INV_KINDS_MAX)
                     ? (int)st->character.inv_qty[r->input_kind_a]
                     : 0;
    if(ka) {
        snprintf(
            line, sizeof(line), "%dx %c %s (%d)", (int)r->input_qty_a,
            ka->glyph, ka->true_name, have_a);
        canvas_draw_str(canvas, 0, 30, line);
    }
    /* Input B (optional) */
    if(r->input_kind_b != RECIPE_NO_INPUT) {
        const KindDef* kb = kind_by_id(r->input_kind_b);
        int have_b = (r->input_kind_b < SAVE_INV_KINDS_MAX)
                         ? (int)st->character.inv_qty[r->input_kind_b]
                         : 0;
        if(kb) {
            snprintf(
                line, sizeof(line), "%dx %c %s (%d)", (int)r->input_qty_b,
                kb->glyph, kb->true_name, have_b);
            canvas_draw_str(canvas, 0, 38, line);
        }
    }
    /* Output */
    const KindDef* out = kind_by_id(r->output_kind);
    if(out) {
        snprintf(line, sizeof(line), "-> %c %s", out->glyph, out->true_name);
        canvas_draw_str(canvas, 0, 48, line);
    }
    /* Status (ready / need materials) — show status_line if a pull just landed,
     * else the readiness hint. */
    if(st->status_line) {
        canvas_draw_str(canvas, 0, 56, st->status_line);
    } else {
        int ready = recipe_craftable(
            r, st->character.inv_qty, SAVE_INV_KINDS_MAX);
        canvas_draw_str(canvas, 0, 56, ready ? "[ready]" : "[need more]");
    }

    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom,
        "OK pull  Back done");
}

/* Shop — buy/sell list. Two flavors:
 *   shop_is_vendor=false (from inventory→Down): SELL only, scrap price
 *   shop_is_vendor=true  (stepped onto V):     SELL + BUY, chunk-priced
 * shop_mode 0=SELL list, 1=BUY list (BUY available only at vendor). */
static void draw_shop_screen(Canvas* canvas, const AppState* st) {
    bool buy_mode = (st->shop_mode == 1) && st->shop_is_vendor;
    canvas_set_font(canvas, FontPrimary);
    const char* title = st->shop_is_vendor
                            ? (buy_mode ? "Vendor: Buy" : "Vendor: Sell")
                            : "Scrap";
    canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, title);
    canvas_set_font(canvas, FontSecondary);
    char balance[24];
    snprintf(balance, sizeof(balance), "%u *", (unsigned)purse(st));
    canvas_draw_str_aligned(
        canvas, SCREEN_W, TITLE_BASELINE_Y, AlignRight, AlignBottom, balance);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    uint8_t list[KIND_COUNT];
    int n = buy_mode
                ? build_buyable_list((uint8_t)st->world.biome, list, KIND_COUNT)
                : build_sellable_list(&st->character, list, KIND_COUNT);
    int cursor = st->shop_cursor;
    if(cursor < 0) cursor = 0;
    if(n > 0 && cursor >= n) cursor = n - 1;

    if(n == 0) {
        canvas_draw_str(canvas, 0, 32,
                        buy_mode ? "(vendor empty)" : "(nothing to sell)");
    } else {
        int first = 0;
        if(cursor > 3) first = cursor - 3;
        int last = first + 4;
        if(last > n) last = n;
        for(int row = first, i = 0; row < last; row++, i++) {
            int y = 22 + i * 8;
            uint8_t id = list[row];
            const KindDef* k = kind_by_id(id);
            if(!k) continue;
            uint16_t price = shop_price_for(st, id, k->value, buy_mode);
            char line[40];
            if(buy_mode) {
                snprintf(line, sizeof(line), "%c %s  %u*",
                         k->glyph, k->true_name,
                         (unsigned)trade_shards_owed(price));
            } else {
                snprintf(line, sizeof(line), "%c %s x%u  %u*",
                         k->glyph, k->true_name,
                         (unsigned)st->character.inv_qty[id],
                         (unsigned)trade_shards_earned(price));
            }
            if(row == cursor) {
                canvas_draw_box(canvas, 0, y - 7, SCREEN_W, 8);
                canvas_invert_color(canvas);
                canvas_draw_str(canvas, 2, y, line);
                canvas_invert_color(canvas);
            } else {
                canvas_draw_str(canvas, 2, y, line);
            }
        }
    }

    const char* footer;
    if(st->shop_is_vendor) {
        footer = buy_mode ? "OK buy   <> sell  Back" : "OK sell  <> buy   Back";
    } else {
        footer = "OK sell  Back done";
    }
    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom,
        footer);
}

/* Quest (slice 49.F5) — surfaces when entering an anchored chunk. Shows
 * intro + two branch labels; player chooses; resolution feeds the deeds
 * log (axis growth) and the codex (lore line via the status strip for v1). */
static void draw_quest_screen(Canvas* canvas, const AppState* st) {
    if(st->pending_quest_entry < 0 ||
       st->pending_quest_entry >= MOCK_PO_ENTRY_COUNT ||
       st->pending_quest_template < 0 ||
       st->pending_quest_template >= QUEST_TEMPLATE_COUNT) {
        canvas_set_font(canvas, FontPrimary);
        canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, "(no quest)");
        return;
    }
    const PoEntry* e = &MOCK_PO_ENTRIES[st->pending_quest_entry];
    const QuestTemplate* t = &QUEST_TEMPLATES[st->pending_quest_template];

    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, "you remember");

    canvas_set_font(canvas, FontSecondary);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    /* Intro text — substituted at draw-time; bounded buffer. Wrap by hand:
     * 21 chars per line at FontSecondary on a 128-px line. */
    char intro[128];
    narrative_substitute(intro, sizeof(intro), t->intro, e);
    /* Quick wrap: split on word boundary near col 21. */
    int len = (int)strlen(intro);
    if(len <= 21) {
        canvas_draw_str(canvas, 0, 24, intro);
    } else {
        int brk = 21;
        while(brk > 0 && intro[brk] != ' ') brk--;
        if(brk == 0) brk = 21;
        char a[24], b[64];
        int al = brk < 23 ? brk : 23;
        memcpy(a, intro, al); a[al] = '\0';
        strncpy(b, intro + brk + (intro[brk] == ' ' ? 1 : 0), sizeof(b) - 1);
        b[sizeof(b) - 1] = '\0';
        canvas_draw_str(canvas, 0, 24, a);
        canvas_draw_str(canvas, 0, 32, b);
    }

    /* Two branches, side by side. Selected one inverted. */
    bool sel_a = (st->quest_choice == 0);
    char la[16], lb[16];
    snprintf(la, sizeof(la), " %s ", t->branch_a_label);
    snprintf(lb, sizeof(lb), " %s ", t->branch_b_label);
    int wa = (int)strlen(la) * 5;  /* approx; FontSecondary ~5px/char */
    int wb = (int)strlen(lb) * 5;
    int xa = 0, xb = SCREEN_W - wb;
    if(sel_a) {
        canvas_draw_box(canvas, xa, 44, wa + 2, 10);
        canvas_invert_color(canvas);
        canvas_draw_str(canvas, xa + 1, 52, la);
        canvas_invert_color(canvas);
        canvas_draw_str(canvas, xb, 52, lb);
    } else {
        canvas_draw_str(canvas, xa, 52, la);
        canvas_draw_box(canvas, xb - 1, 44, wb + 2, 10);
        canvas_invert_color(canvas);
        canvas_draw_str(canvas, xb, 52, lb);
        canvas_invert_color(canvas);
    }

    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom,
        "L/R  OK confirm");
}

/* Inventory (slice 2) — glyph grid + HUD for the selected slot. L/R scrolls
 * cursor; OK equips/consumes; Back returns to world. */
static void draw_inventory_screen(Canvas* canvas, const AppState* st) {
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, "Bag");

    canvas_set_font(canvas, FontSecondary);
    int held = 0;
    for(int i = 0; i < KIND_COUNT; i++) {
        if(st->character.inv_qty[i] > 0) held++;
    }
    char hdr[24];
    snprintf(hdr, sizeof(hdr), "%d/%d", held, (int)KIND_COUNT);
    canvas_draw_str_aligned(
        canvas, SCREEN_W, TITLE_BASELINE_Y, AlignRight, AlignBottom, hdr);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    /* Grid: one row of BAG_COLS slots, 16px pitch — slot i is kind id i, and
     * the row shown is the cursor's (schema 9 holds more kinds than fit one
     * row: < > mark the other rows). Equipped slot = inverted cell; cursor =
     * frame. A kind with a top-down form is drawn by it, else by its glyph. */
    const int CELL_W = 16, CELL_H = 12, BAG_COLS = 8;
    const int GRID_Y = 18;
    int first = (st->inv_cursor / BAG_COLS) * BAG_COLS;
    if(first > 0) canvas_draw_str(canvas, 0, GRID_Y + 20, "<");
    if(first + BAG_COLS < KIND_COUNT) canvas_draw_str_aligned(canvas, SCREEN_W, GRID_Y + 20, AlignRight, AlignBottom, ">");
    for(int i = first; i < KIND_COUNT && i < first + BAG_COLS; i++) {
        const KindDef* k = kind_by_id((uint8_t)i);
        if(!k) continue;
        int x = (i - first) * CELL_W;
        int y = GRID_Y;
        bool selected = (st->inv_cursor == i);
        bool eq = is_equipped(&st->character, (uint8_t)i);
        char gbuf[2] = {k->glyph, '\0'};
        if(st->character.inv_qty[i] > 0) {
            if(eq) {
                canvas_draw_box(canvas, x, y, CELL_W, CELL_H);
                canvas_invert_color(canvas);
            }
            if(k->map_icon) canvas_draw_xbm(canvas, x + 4, y + 2, 8, 8, k->map_icon);
            else canvas_draw_str(canvas, x + 5, y + 9, gbuf);
            if(eq) canvas_invert_color(canvas);
        } else {
            /* empty slot indicator */
            canvas_draw_str(canvas, x + 6, y + 9, ".");
        }
        if(selected) canvas_draw_frame(canvas, x, y, CELL_W, CELL_H);
    }

    /* HUD: selected item info. */
    const KindDef* sel = kind_by_id((uint8_t)st->inv_cursor);
    if(sel) {
        unsigned qty = (st->inv_cursor < SAVE_INV_KINDS_MAX)
                           ? (unsigned)st->character.inv_qty[st->inv_cursor]
                           : 0;
        bool eq = is_equipped(&st->character, (uint8_t)st->inv_cursor);
        char line1[48];
        if(qty > 0) {
            snprintf(line1, sizeof(line1), "%s x%u%s", sel->true_name, qty,
                     eq ? "  EQ" : "");
        } else {
            snprintf(line1, sizeof(line1), "%s (none)", sel->true_name);
        }
        canvas_draw_str(canvas, 0, 44, line1);
        const char* type_label = (sel->flags & KF_EQUIP)        ? "equipment"
                                 : (sel->flags & KF_CONSUMABLE) ? "consumable"
                                                                : "material";
        char line2[48];
        snprintf(line2, sizeof(line2), "%s  %s", type_label,
                 sel->effect ? sel->effect : "");
        canvas_draw_str(canvas, 0, 54, line2);
    }

    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom,
        "OK use  Back done");
}

/* Character sheet (slice 1c → 5 → 48.F2/F3) — read-only display: name,
 * level, hp/mp, 6 axes, effective ATK/DEF, fuel. Opened by examining the
 * player @ tile. Header is YOUR NAME (display_name), not the class label
 * "You" — under the You-only contract, identity is who you are, not the
 * archetype slot. The class is always CLASS_YOU = id 0. */
static void draw_char_sheet_screen(Canvas* canvas, const AppState* st) {
    const ClassDef* cls = class_def(st->character.class_id);
    const char* name = (st->display_name[0] != '\0')
                           ? st->display_name
                           : (cls ? cls->name : "You");

    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, name);

    canvas_set_font(canvas, FontSecondary);
    char hdr[16];
    snprintf(hdr, sizeof(hdr), "Lv %u", (unsigned)st->character.level);
    canvas_draw_str_aligned(
        canvas, SCREEN_W, TITLE_BASELINE_Y, AlignRight, AlignBottom, hdr);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    char line[48];
    snprintf(
        line, sizeof(line), "HP %u/%u  MP %u/%u",
        (unsigned)st->character.hp, (unsigned)st->character.max_hp,
        (unsigned)st->character.mp, (unsigned)st->character.max_mp);
    canvas_draw_str(canvas, 0, 22, line);

    /* Slice 48.F1 axes + slice 48.F6 deltas: when deeds.delta[axis] > 0,
     * suffix the line with the delta. Format `BODY 12+1`, no parens (every
     * char counts on 128px). 4-char axis names already fit; the suffix only
     * shows when there's actual growth, so the resting state stays clean. */
    int8_t db = (int8_t)st->deeds.delta[DEED_AXIS_BODY];
    int8_t dc = (int8_t)st->deeds.delta[DEED_AXIS_CRAFT];
    int8_t ds = (int8_t)st->deeds.delta[DEED_AXIS_SIGHT];
    int8_t dm = (int8_t)st->deeds.delta[DEED_AXIS_MIND];
    int8_t dh = (int8_t)st->deeds.delta[DEED_AXIS_HEART];
    int8_t dw = (int8_t)st->deeds.delta[DEED_AXIS_WILL];
    char bb[8], cb[8], sb[8], mb[8], hb[8], wb[8];
    if(db > 0) snprintf(bb, sizeof(bb), "%u+%d", (unsigned)st->character.body, (int)db);
    else       snprintf(bb, sizeof(bb), "%2u",   (unsigned)st->character.body);
    if(dc > 0) snprintf(cb, sizeof(cb), "%u+%d", (unsigned)st->character.craft, (int)dc);
    else       snprintf(cb, sizeof(cb), "%2u",   (unsigned)st->character.craft);
    if(ds > 0) snprintf(sb, sizeof(sb), "%u+%d", (unsigned)st->character.sight, (int)ds);
    else       snprintf(sb, sizeof(sb), "%2u",   (unsigned)st->character.sight);
    if(dm > 0) snprintf(mb, sizeof(mb), "%u+%d", (unsigned)st->character.mind, (int)dm);
    else       snprintf(mb, sizeof(mb), "%2u",   (unsigned)st->character.mind);
    if(dh > 0) snprintf(hb, sizeof(hb), "%u+%d", (unsigned)st->character.heart, (int)dh);
    else       snprintf(hb, sizeof(hb), "%2u",   (unsigned)st->character.heart);
    if(dw > 0) snprintf(wb, sizeof(wb), "%u+%d", (unsigned)st->character.will, (int)dw);
    else       snprintf(wb, sizeof(wb), "%2u",   (unsigned)st->character.will);
    snprintf(line, sizeof(line), "BODY %-5s CRFT %s", bb, cb);
    canvas_draw_str(canvas, 0, 32, line);
    snprintf(line, sizeof(line), "SGHT %-5s MIND %s", sb, mb);
    canvas_draw_str(canvas, 0, 40, line);
    snprintf(line, sizeof(line), "HRT  %-5s WILL %s", hb, wb);
    canvas_draw_str(canvas, 0, 48, line);

    /* Effective ATK/DEF (slice 5) — what the combat resolver actually sees,
     * inclusive of equipped bonuses. Keeps Fuel visible since it bears on
     * vision range; OBS skill moves to the dedicated skill list later. */
    snprintf(
        line, sizeof(line), "ATK %d  DEF %d  Fuel %u",
        player_atk(&st->character, &st->deeds),
        player_def(&st->character, &st->deeds),
        (unsigned)st->character.torch_fuel);
    canvas_draw_str(canvas, 0, 56, line);

    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom,
        "Back done");
}
static const char* const SITE_ACT_LABEL[] = {"set a seal", "disturb it", "the rite", "leave"};

static void draw_row(Canvas* canvas, int y, const char* text, bool sel) {
    if(sel) {
        canvas_draw_box(canvas, 0, y - 7, SCREEN_W, 8);
        canvas_invert_color(canvas);
        canvas_draw_str(canvas, 2, y, text);
        canvas_invert_color(canvas);
    } else {
        canvas_draw_str(canvas, 2, y, text);
    }
}

static void draw_title(Canvas* canvas, const char* title) {
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str(canvas, 0, TITLE_BASELINE_Y, title);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);
    canvas_set_font(canvas, FontSecondary);
}

static void draw_footer(Canvas* canvas, const char* footer) {
    canvas_draw_str_aligned(canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom, footer);
}

static void draw_site_screen(Canvas* canvas, const AppState* st) {
    int rx, ry;
    arc_region_here(st, &rx, &ry);
    if(st->site_k >= 0) {
        draw_title(canvas, SITE_TABLE[st->site_kind % SITE_KIND_COUNT].name);
        bool sealed = arc_site_sealed(&st->region_book, rx, ry, st->site_k);
        canvas_draw_str(canvas, 0, 23, sealed ? ARC_LINE_SEALED : ARC_LINE_CORRUPT);
    } else {
        const char* nm = terrain_name(st->world.tiles[st->site_y][st->site_x], NULL);
        draw_title(canvas, nm ? nm : "grave");
    }
    uint8_t acts[4];
    int n = site_actions(st, acts);
    for(int i = 0; i < n; i++)
        draw_row(canvas, 35 + i * 9, SITE_ACT_LABEL[acts[i]], i == st->site_cursor);
    draw_footer(canvas, "OK do  Back leave");
}

static void draw_rite_screen(Canvas* canvas, const AppState* st) {
    int rx, ry;
    arc_region_here(st, &rx, &ry);
    draw_title(canvas, "the rite");
    uint8_t ways[WAY_COUNT];
    int n = rite_ways(st, ways);
    if(n == 0) {
        canvas_draw_str(canvas, 0, 30, ARC_LINE_MISSING);
    } else {
        for(int i = 0; i < n; i++)
            draw_row(canvas, 23 + i * 8, arc_way_name((RitualWay)ways[i]), i == st->rite_cursor);
        RitualWay w = (RitualWay)ways[st->rite_cursor < n ? st->rite_cursor : 0];
        const char* line = ARC_LINE_MISSING;
        if(arc_way_ready(st->campaign_seed, rx, ry, w, &st->character, &st->region_book)) {
            RegionRite rite;
            region_rite(st->campaign_seed, rx, ry, &rite);
            EffortTask t = ritual_task(&rite, w);
            EffortBody b = rite_body(st, w);
            /* Each rite turn is also a world turn, which burns the light too:
             * tell the odds against what will be left. */
            uint16_t burn = (uint16_t)(t.turns * (FUEL_PER_TURN + st->current_weather.fuel_burn_extra));
            b.fuel = b.fuel > burn ? (uint16_t)(b.fuel - burn) : 0;
            line = effort_odds_line(&t, &b);
        }
        canvas_draw_str(canvas, 0, 55, line);
    }
    draw_footer(canvas, "OK begin  Back");
}

static void draw_vigil_screen(Canvas* canvas, const AppState* st) {
    draw_title(canvas, "the vigil");
    canvas_draw_str(canvas, 0, 25, ARC_LINE_VIGIL);
    /* The vigil's turns: a mark per turn kept. Counting is fine here: it
     * is the length of a wait, not a meter of the world (43 §17.10). */
    int turns = st->rite_run.task.turns;
    for(int i = 0; i < turns; i++) {
        int x = 4 + i * 10;
        if(i < st->rite_run.turns_done) canvas_draw_box(canvas, x, 32, 6, 6);
        else canvas_draw_frame(canvas, x, 32, 6, 6);
    }
    char stats[24];
    snprintf(stats, sizeof(stats), "HP%u F%u", st->character.hp, st->character.torch_fuel);
    canvas_draw_str(canvas, 0, 52, stats);
    draw_footer(canvas, "OK wait  Back stop");
}

/* A rune at 2x: 16x16 from its 8x8 form. */
static void draw_rune_2x(Canvas* canvas, int x, int y, uint8_t shape, uint8_t turn) {
    uint8_t icon[8];
    rune_icon(shape, turn, icon);
    for(int ry = 0; ry < 8; ry++)
        for(int rx = 0; rx < 8; rx++)
            if(icon[ry] & (1u << rx)) canvas_draw_box(canvas, x + rx * 2, y + ry * 2, 2, 2);
}

static void draw_runes_screen(Canvas* canvas, const AppState* st) {
    const RunePuzzle* p = &st->runes;
    canvas_set_font(canvas, FontSecondary);
    int span = p->count * 26;
    int x0 = (SCREEN_W - span) / 2 + 5;
    for(int i = 0; i < p->count; i++) {
        int x = x0 + i * 26;
        draw_rune_2x(canvas, x, 12, p->shape[i], st->rune_turn[i]);
        if(i == st->rune_sel) canvas_draw_frame(canvas, x - 3, 9, 22, 22);
        for(int k = 0; k < st->rune_ntouched; k++)
            if(st->rune_touched[k] == i)
                for(int d = 0; d <= k; d++) canvas_draw_box(canvas, x + d * 4, 34, 2, 2);
    }
    if(st->status_line) canvas_draw_str(canvas, 0, 50, st->status_line);
    draw_footer(canvas, p->kind == PUZZLE_TURN    ? "<> pick  ^v turn  OK try"
                        : p->kind == PUZZLE_ORDER ? "<> pick  OK touch  Back"
                                                  : "^v turn  OK touch  Back");
}

void screens_draw(Canvas* canvas, void* ctx) {
    const AppState* st = ctx;
    canvas_clear(canvas);
    switch(st->screen) {
    case ScreenTitle:       draw_title_screen(canvas, st); break;
    case ScreenLoadPicker:  draw_picker_screen(canvas, st); break;
    case ScreenWorld:
        if(st->view_mode == 1) draw_fpv_world_screen(canvas, st);
        else                   draw_world_screen(canvas, st);
        break;
    case ScreenCodex:       draw_codex_screen(canvas, st); break;
    case ScreenCombat:      draw_combat_screen(canvas, st); break;
    case ScreenClassPick:   draw_class_pick_screen(canvas, st); break;
    case ScreenStatBuy:     draw_stat_buy_screen(canvas, st); break;
    case ScreenCharSheet:   draw_char_sheet_screen(canvas, st); break;
    case ScreenInventory:   draw_inventory_screen(canvas, st); break;
    case ScreenCraft:       draw_craft_screen(canvas, st); break;
    case ScreenShop:        draw_shop_screen(canvas, st); break;
    case ScreenStash:       draw_stash_screen(canvas, st); break;
    case ScreenQuest:       draw_quest_screen(canvas, st); break;
    case ScreenFpvDemo:     /* deprecated; FPV is now a view-mode of
                             * ScreenWorld. Kept enum for save compat. */
                            break;
    case ScreenSite:        draw_site_screen(canvas, st); break;
    case ScreenRite:        draw_rite_screen(canvas, st); break;
    case ScreenVigil:       draw_vigil_screen(canvas, st); break;
    case ScreenRunes:       draw_runes_screen(canvas, st); break;
    }
}
