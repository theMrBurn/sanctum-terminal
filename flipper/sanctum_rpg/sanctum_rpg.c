/*
 * Sanctum RPG — Flipper Zero field-instrument expression of sanctum-engage.
 *
 * Phase 2 v0.2.0: walk-around skeleton. Title → World → Title. The
 * world is a single hand-crafted 16×6 starter room. NSEW movement
 * with wall collision; one item that can be picked up; one door that
 * acknowledges itself. Autosave per move via save_io_write_character.
 *
 * Procgen chunks (spec 43 §6) replace world_starter_room in Phase 3.
 *
 * Spec: sanctum-os/docs/specs/43_app_sanctum_rpg_flipper.md
 * Read order before editing this file: AGENTS.md in sanctum-engage root.
 *
 * Hard rules (inherited):
 *   - No LLM at runtime. Procgen + author tables only.
 *   - Save state under /ext/apps_data/sanctum_rpg/. Atomic writes.
 *   - Voice: copy echoes the user's wife's writing — never D&D tutorial.
 */
#include <stdarg.h>
#include <string.h>

#include <furi.h>
#include <furi_hal_random.h>
#include <gui/gui.h>
#include <input/input.h>
#include <notification/notification_messages.h>
#include <storage/storage.h>
#include <stdint.h>
#include <stdio.h>

#include "deltas.h"
#include "fov.h"
#include "loot.h"
#include "save_io.h"
#include "world.h"

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

#define INPUT_QUEUE_DEPTH     8

#define PICKER_MAX_CAMPAIGNS  16
#define PICKER_VISIBLE_ROWS   4
#define PICKER_FIRST_BASELINE 22    /* match the tightened title layout */
#define PICKER_SCROLL_HINT_X  120

#define STATUS_BUF_SIZE       48

/* World render */
#define TILE_PX               8                       /* tile cell, 8x8 */
#define WORLD_VIEW_W          (WORLD_COLS * TILE_PX)  /* 128 px */
#define WORLD_VIEW_H          (WORLD_ROWS * TILE_PX)  /*  48 px */
#define WORLD_TILE_BASELINE_Y_OFFSET 7                /* FontSecondary baseline within 8px cell */
#define WORLD_STATUS_BASELINE 56                      /* below the grid */
#define WORLD_HINT_BASELINE   63                      /* corner hint */

/* Defaults for a fresh character on New Game. */
#define DEFAULT_HP            10
#define DEFAULT_MP            5
#define DEFAULT_LEVEL         1
#define DEFAULT_CREDITS       0
#define DEFAULT_SPAWN_X       1
#define DEFAULT_SPAWN_Y       1

/* ─── screen / menu model ─────────────────────────────────────────── */

typedef enum {
    ScreenTitle,
    ScreenLoadPicker,
    ScreenWorld,
    ScreenCodex,
} Screen;

typedef enum {
    MenuContinue = 0,
    MenuLoad,
    MenuNewGame,
    MenuCodex,
    MenuSettings,
    MenuCount,
} MenuItem;

static const char* const MENU_LABELS[MenuCount] = {
    [MenuContinue] = "Continue",
    [MenuLoad]     = "Load",
    [MenuNewGame]  = "New Game",
    [MenuCodex]    = "Codex",
    [MenuSettings] = "Settings",
};

typedef struct {
    CampaignMeta items[PICKER_MAX_CAMPAIGNS];
    int count;
    int cursor;
    int scroll_offset;
} LoadPicker;

typedef struct {
    Screen screen;
    MenuItem cursor;
    LoadPicker picker;

    /* Active campaign — populated when Continue / Load / New Game enters world. */
    World world;
    CharacterState character;
    ChunkDeltas current_deltas;  /* deltas for the chunk player is currently in */
    uint32_t campaign_seed; /* cached from meta.seed for chunk transitions */
    bool campaign_loaded;

    /* FOV (v0.3.5a) — transient per-chunk visibility. lit = within the
     * current torch radius; seen = ever-lit this chunk visit (remembered).
     * Reset on chunk entry; recomputed each move. */
    uint8_t lit[WORLD_ROWS][WORLD_COLS];
    uint8_t seen[WORLD_ROWS][WORLD_COLS];

    /* Examine mode (v0.3.5b) — the teaching channel. OK toggles a cursor
     * you move over visible tiles; the status line names what's under it.
     * Free (no turn/fuel cost) — looking isn't acting. */
    bool examining;
    int8_t examine_x, examine_y;

    /* Codex (v0.3.5c) — the logbook. codex_identified is loaded from the
     * most-recent campaign when opened from the title (no live character
     * there). The "scan→log" seed of the Metroid-Prime scan system. */
    uint64_t codex_identified;
    int codex_scroll;

    NotificationApp* notif;  /* haptic/LED/sound feedback (v0.3.5d) */
    bool muted;              /* default ON during dev; toggled in Settings */

    const char* status_line;
    char status_buf[STATUS_BUF_SIZE];
} AppState;

/* ─── status helpers ──────────────────────────────────────────────── */

static void set_status(AppState* st, const char* msg) {
    strncpy(st->status_buf, msg, sizeof(st->status_buf) - 1);
    st->status_buf[sizeof(st->status_buf) - 1] = '\0';
    st->status_line = st->status_buf;
}

static void set_statusf(AppState* st, const char* fmt, ...)
    __attribute__((format(printf, 2, 3)));

static void set_statusf(AppState* st, const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(st->status_buf, sizeof(st->status_buf), fmt, ap);
    va_end(ap);
    st->status_line = st->status_buf;
}

/* ─── character lifecycle ─────────────────────────────────────────── */

static void character_init_defaults(CharacterState* c, const char* campaign_id) {
    strncpy(c->campaign_id, campaign_id, sizeof(c->campaign_id) - 1);
    c->campaign_id[sizeof(c->campaign_id) - 1] = '\0';
    c->chunk_x = 0;
    c->chunk_y = 0;
    c->player_x = DEFAULT_SPAWN_X;
    c->player_y = DEFAULT_SPAWN_Y;
    c->hp = DEFAULT_HP;
    c->max_hp = DEFAULT_HP;
    c->mp = DEFAULT_MP;
    c->max_mp = DEFAULT_MP;
    c->level = DEFAULT_LEVEL;
    c->credits = DEFAULT_CREDITS;
    c->identified = 0;
    c->turn = 0;
    c->torch_fuel = TORCH_FUEL_MAX;
    c->schema_version = SAVE_IO_SCHEMA_VERSION;
}

/* Fire a haptic/LED/sound feedback sequence (no-op if unavailable or muted). */
static void notify(AppState* st, const NotificationSequence* seq) {
    if(st->notif && !st->muted) notification_message(st->notif, seq);
}

/* Recompute the lit set from the player's position + torch radius, and
 * OR newly-lit tiles into the seen (remembered) set. Cheap — 96 tiles. */
static void recompute_visibility(AppState* st) {
    int radius = fov_radius_for_fuel(st->character.torch_fuel);
    int px = st->character.player_x;
    int py = st->character.player_y;
    for(int y = 0; y < WORLD_ROWS; y++) {
        for(int x = 0; x < WORLD_COLS; x++) {
            bool islit = fov_is_lit(px, py, x, y, radius);
            st->lit[y][x] = islit ? 1u : 0u;
            if(islit) st->seen[y][x] = 1u;
        }
    }
}

/* Entering a chunk: forget the previous chunk's exploration, then light
 * the area around the spawn. (Persistent per-chunk memory is a later
 * refinement; for now each visit re-explores.) */
static void reset_visibility(AppState* st) {
    for(int y = 0; y < WORLD_ROWS; y++) {
        for(int x = 0; x < WORLD_COLS; x++) {
            st->seen[y][x] = 0u;
        }
    }
    recompute_visibility(st);
}

/* Enter the world for `campaign_id`. Loads meta (for seed), loads or
 * initialises character.json, generates the chunk procedurally from
 * meta.seed, stamps last_played_at, sets screen = ScreenWorld.
 *
 * New character path: spawn at world.spawn_x/spawn_y (procgen-chosen).
 * Resume path: trust saved position UNLESS it now lands in a wall
 * (generator changed or chunk coords differ), in which case snap to
 * the chunk's spawn point so the player isn't stuck. */
static bool enter_world(AppState* st, const char* campaign_id) {
    CampaignMeta meta;
    if(save_io_load_meta(campaign_id, &meta) != SaveIoOk) {
        set_status(st, "meta load failed");
        return false;
    }

    bool fresh_character = false;
    SaveIoResult r = save_io_load_character(campaign_id, &st->character);
    if(r == SaveIoNotFound) {
        character_init_defaults(&st->character, campaign_id);
        fresh_character = true;
    } else if(r != SaveIoOk) {
        set_status(st, "character load failed");
        return false;
    }

    /* Cache the campaign seed so on_world_move can regenerate adjacent
     * chunks without re-reading meta on every door crossing. */
    st->campaign_seed = meta.seed;

    /* Generate the chunk the player was last in (chunk_x/chunk_y from
     * character.json; defaults to 0,0 for fresh characters and for v0.2
     * saves that predate chunk coords). */
    world_generate_chunk(
        st->campaign_seed,
        st->character.chunk_x, st->character.chunk_y,
        &st->world);

    /* Overlay persisted mutations (items picked up, etc.) — spec 43 §4
     * delta layer; project_sanctum_rpg_flipper "finite loot" rule. */
    deltas_load(
        campaign_id,
        st->character.chunk_x, st->character.chunk_y,
        &st->current_deltas);
    deltas_apply_to_world(&st->current_deltas, &st->world);

    if(fresh_character || !world_walkable(&st->world, st->character.player_x,
                                          st->character.player_y)) {
        st->character.player_x = (int16_t)st->world.spawn_x;
        st->character.player_y = (int16_t)st->world.spawn_y;
        save_io_write_character(&st->character);  /* persist the chosen spawn */
    }

    save_io_touch_played(campaign_id);  /* best-effort; ignore failure */
    reset_visibility(st);
    st->examining = false;
    st->campaign_loaded = true;
    st->screen = ScreenWorld;
    st->status_line = NULL;
    return true;
}

/* ─── picker logic ────────────────────────────────────────────────── */

static int meta_cmp_desc(const CampaignMeta* a, const CampaignMeta* b) {
    if(a->last_played_at_unix != b->last_played_at_unix) {
        return a->last_played_at_unix > b->last_played_at_unix ? -1 : 1;
    }
    return strcmp(b->campaign_id, a->campaign_id);
}

static int picker_load(LoadPicker* p) {
    Storage* storage = furi_record_open(RECORD_STORAGE);
    File* dir = storage_file_alloc(storage);
    p->count = 0;
    if(storage_dir_open(dir, "/ext/apps_data/sanctum_rpg/campaigns")) {
        FileInfo info;
        char name[64];
        while(storage_dir_read(dir, &info, name, sizeof(name))
              && p->count < PICKER_MAX_CAMPAIGNS) {
            if(!file_info_is_dir(&info)) continue;
            if(save_io_load_meta(name, &p->items[p->count]) == SaveIoOk) {
                p->count++;
            }
        }
        storage_dir_close(dir);
    }
    storage_file_free(dir);
    furi_record_close(RECORD_STORAGE);

    for(int i = 1; i < p->count; i++) {
        CampaignMeta key = p->items[i];
        int j = i - 1;
        while(j >= 0 && meta_cmp_desc(&p->items[j], &key) > 0) {
            p->items[j + 1] = p->items[j];
            j--;
        }
        p->items[j + 1] = key;
    }
    p->cursor = 0;
    p->scroll_offset = 0;
    return p->count;
}

static void picker_move(LoadPicker* p, int delta) {
    if(p->count == 0) return;
    int next = p->cursor + delta;
    if(next < 0) next = 0;
    if(next >= p->count) next = p->count - 1;
    p->cursor = next;
    if(p->cursor < p->scroll_offset) {
        p->scroll_offset = p->cursor;
    } else if(p->cursor >= p->scroll_offset + PICKER_VISIBLE_ROWS) {
        p->scroll_offset = p->cursor - PICKER_VISIBLE_ROWS + 1;
    }
}

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

/* ─── render: world ───────────────────────────────────────────────── */

/* What's under the examine cursor — the teaching channel. Honors FOV (you
 * can't name what you can't see) + identification (loot shows its true name
 * only once known, else its unidentified appearance). Mirrors the render:
 * remembered (seen-not-lit) tiles hide loot, so they read as floor. */
static const char* examine_name(const AppState* st, int x, int y) {
    if(x == st->character.player_x && y == st->character.player_y) return "you";
    if(x < 0 || x >= WORLD_COLS || y < 0 || y >= WORLD_ROWS) return "darkness";
    bool lit = st->lit[y][x];
    bool seen = st->seen[y][x];
    if(!lit && !seen) return "darkness";
    char t = st->world.tiles[y][x];
    const KindDef* k = kind_by_glyph(t);
    if(k) {
        if(!lit) return "floor"; /* remembered: loot not currently visible */
        bool known = ((st->character.identified >> k->id) & 1ull) != 0;
        return known ? k->true_name : k->unid_name;
    }
    switch(t) {
    case TILE_WALL:        return "rock wall";
    case TILE_ROCK:        return "boulder";
    case TILE_DOOR:        return "doorway";
    case TILE_STAIRS_UP:   return "stairs up";
    case TILE_STAIRS_DOWN: return "stairs down";
    case TILE_FLOOR:
    default:
        return (st->world.biome == BIOME_OUTDOOR) ? "open ground" : "cave floor";
    }
}

/* Move the examine cursor, clamped to the chunk. */
static void examine_move(AppState* st, int dx, int dy) {
    int nx = st->examine_x + dx;
    int ny = st->examine_y + dy;
    if(nx < 0) nx = 0;
    if(nx >= WORLD_COLS) nx = WORLD_COLS - 1;
    if(ny < 0) ny = 0;
    if(ny >= WORLD_ROWS) ny = WORLD_ROWS - 1;
    st->examine_x = (int8_t)nx;
    st->examine_y = (int8_t)ny;

    /* Scanning a LIT item logs it to the Codex + reveals its true name —
     * the Metroid-Prime scan→log loop. You don't have to pick it up to
     * learn it. Marks identified + persists (rare write). */
    if(st->lit[ny][nx]) {
        const KindDef* k = kind_by_glyph(st->world.tiles[ny][nx]);
        if(k && ((st->character.identified >> k->id) & 1ull) == 0) {
            st->character.identified |= (1ull << k->id);
            save_io_write_character(&st->character);
            notify(st, &sequence_success); /* scan logged a new Codex entry */
        }
    }
}

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
            } else if(st->seen[y][x]) {
                glyph = loot_is_item_glyph(tile) ? TILE_FLOOR : tile;
            } else {
                continue; /* unseen → dark */
            }
            char buf[2] = {glyph, '\0'};
            canvas_draw_str(canvas, x * TILE_PX, y * TILE_PX + WORLD_TILE_BASELINE_Y_OFFSET, buf);
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

    /* Status line: examine name while looking; else transient status / stats. */
    if(st->examining) {
        canvas_draw_str(canvas, 0, WORLD_STATUS_BASELINE,
                        examine_name(st, st->examine_x, st->examine_y));
    } else if(st->status_line) {
        canvas_draw_str(canvas, 0, WORLD_STATUS_BASELINE, st->status_line);
    } else {
        char stats[40];
        snprintf(stats, sizeof(stats), "HP%u/%u MP%u/%u F%u",
                 st->character.hp, st->character.max_hp,
                 st->character.mp, st->character.max_mp,
                 st->character.torch_fuel);
        canvas_draw_str(canvas, 0, WORLD_STATUS_BASELINE, stats);
    }

    /* Corner hint */
    canvas_draw_str_aligned(
        canvas, SCREEN_W, WORLD_HINT_BASELINE, AlignRight, AlignBottom,
        st->examining ? FOOTER_EXAMINE : FOOTER_WORLD);
}

/* ─── render: codex (logbook) ─────────────────────────────────────── */

static void draw_codex_screen(Canvas* canvas, const AppState* st) {
    canvas_set_font(canvas, FontPrimary);
    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, TITLE_BASELINE_Y, AlignCenter, AlignBottom, "Codex");

    int discovered = 0;
    for(int i = 0; i < KIND_COUNT; i++) {
        if((st->codex_identified >> KIND_CATALOG[i].id) & 1ull) discovered++;
    }
    char hdr[16];
    snprintf(hdr, sizeof(hdr), "%d/%d", discovered, KIND_COUNT);
    canvas_set_font(canvas, FontSecondary);
    canvas_draw_str_aligned(canvas, SCREEN_W, TITLE_BASELINE_Y, AlignRight, AlignBottom, hdr);
    canvas_draw_line(canvas, 0, DIVIDER_Y, SCREEN_W - 1, DIVIDER_Y);

    int end = st->codex_scroll + PICKER_VISIBLE_ROWS;
    if(end > KIND_COUNT) end = KIND_COUNT;
    for(int row = st->codex_scroll, i = 0; row < end; row++, i++) {
        int y = PICKER_FIRST_BASELINE + i * MENU_LINE_HEIGHT;
        const KindDef* k = &KIND_CATALOG[row];
        bool known = ((st->codex_identified >> k->id) & 1ull) != 0;
        char line[40];
        if(known) {
            snprintf(line, sizeof(line), "%c  %s", k->glyph, k->true_name);
        } else {
            snprintf(line, sizeof(line), "?  ???");
        }
        canvas_draw_str(canvas, MENU_TEXT_X, y, line);
    }
    if(st->codex_scroll > 0) {
        canvas_draw_str(canvas, PICKER_SCROLL_HINT_X, PICKER_FIRST_BASELINE, "^");
    }
    if(end < KIND_COUNT) {
        canvas_draw_str(canvas, PICKER_SCROLL_HINT_X,
                        PICKER_FIRST_BASELINE + (PICKER_VISIBLE_ROWS - 1) * MENU_LINE_HEIGHT, "v");
    }
    canvas_draw_str_aligned(
        canvas, SCREEN_W / 2, FOOTER_BASELINE_Y, AlignCenter, AlignBottom, "Back done");
}

/* ─── render dispatch ─────────────────────────────────────────────── */

static void title_draw(Canvas* canvas, void* ctx) {
    const AppState* st = ctx;
    canvas_clear(canvas);
    switch(st->screen) {
    case ScreenTitle:       draw_title_screen(canvas, st); break;
    case ScreenLoadPicker:  draw_picker_screen(canvas, st); break;
    case ScreenWorld:       draw_world_screen(canvas, st); break;
    case ScreenCodex:       draw_codex_screen(canvas, st); break;
    }
}

/* ─── input plumbing ──────────────────────────────────────────────── */

static void title_input(InputEvent* event, void* ctx) {
    FuriMessageQueue* queue = ctx;
    furi_message_queue_put(queue, event, FuriWaitForever);
}

/* ─── title actions ───────────────────────────────────────────────── */

static void on_continue(AppState* st) {
    char id[SAVE_IO_CAMPAIGN_ID_MAX + 1];
    if(save_io_most_recent_campaign(id, sizeof(id)) != SaveIoOk) {
        set_status(st, "no save yet");
        return;
    }
    enter_world(st, id);
}

static void on_load(AppState* st) {
    picker_load(&st->picker);
    st->screen = ScreenLoadPicker;
}

static void on_new_game(AppState* st) {
    uint32_t seed = furi_hal_random_get();
    char id[SAVE_IO_CAMPAIGN_ID_MAX + 1];
    SaveIoResult r = save_io_new_campaign("themrburn", seed, id, sizeof(id));
    switch(r) {
    case SaveIoOk:
        enter_world(st, id);
        break;
    case SaveIoFull:
        set_status(st, "all 999 slots used");
        break;
    case SaveIoFsError:
        set_status(st, "SD write failed");
        break;
    default:
        set_status(st, "unknown error");
        break;
    }
}

static void on_picker_select(AppState* st) {
    LoadPicker* p = &st->picker;
    if(p->count == 0) return;
    enter_world(st, p->items[p->cursor].campaign_id);
}

/* Open the Codex (logbook). No live character on the title screen, so load
 * the discovery set from the most-recent campaign's save. */
static void on_codex(AppState* st) {
    st->codex_identified = 0;
    char id[SAVE_IO_CAMPAIGN_ID_MAX + 1];
    if(save_io_most_recent_campaign(id, sizeof(id)) == SaveIoOk) {
        CharacterState c;
        if(save_io_load_character(id, &c) == SaveIoOk) {
            st->codex_identified = c.identified;
        }
    }
    st->codex_scroll = 0;
    st->screen = ScreenCodex;
}

static void on_select_title(AppState* st) {
    switch(st->cursor) {
    case MenuContinue: on_continue(st); break;
    case MenuLoad:     on_load(st); break;
    case MenuNewGame:  on_new_game(st); break;
    case MenuCodex:    on_codex(st); break;
    case MenuSettings:
        /* Mute toggle (the only setting for now). Default is muted during
         * dev; flip the default in AppState init when we ship. Confirm
         * with a bleep only when turning sound ON. */
        st->muted = !st->muted;
        if(!st->muted) notify(st, &sequence_success);
        set_status(st, st->muted ? "sound: muted" : "sound: on");
        break;
    default: st->status_line = NULL; break;
    }
}

/* ─── world actions ───────────────────────────────────────────────── */

static MoveDir key_to_dir(InputKey k) {
    switch(k) {
    case InputKeyUp:    return MoveNorth;
    case InputKeyDown:  return MoveSouth;
    case InputKeyLeft:  return MoveWest;
    case InputKeyRight: return MoveEast;
    default:            return MoveNone;
    }
}

/* Cross into the neighbour chunk in direction `dir`, carrying the
 * perpendicular coordinate `perp` (the column for N/S, the row for E/W).
 * The player lands one tile inside the entry edge — far enough off it
 * that the next input doesn't immediately re-cross. Used by BOTH cavern
 * door transitions and outdoor walk-off-edge transitions. */
static void do_transition(AppState* st, MoveDir dir, int perp) {
    int cx = st->character.chunk_x;
    int cy = st->character.chunk_y;
    int new_px, new_py;

    switch(dir) {
    case MoveNorth: cy -= 1; new_px = perp;              new_py = WORLD_ROWS - 2; break;
    case MoveSouth: cy += 1; new_px = perp;              new_py = 1;              break;
    case MoveWest:  cx -= 1; new_px = WORLD_COLS - 2;    new_py = perp;           break;
    case MoveEast:  cx += 1; new_px = 1;                 new_py = perp;           break;
    default: return;
    }

    st->character.chunk_x = (int16_t)cx;
    st->character.chunk_y = (int16_t)cy;
    world_generate_chunk(st->campaign_seed, cx, cy, &st->world);

    /* Load + overlay persisted deltas for the entered chunk. */
    deltas_load(st->character.campaign_id, cx, cy, &st->current_deltas);
    deltas_apply_to_world(&st->current_deltas, &st->world);

    /* If the entry tile is unwalkable (crossed into a cavern wall at a
     * biome boundary, or a delta blocked it), snap to the safe spawn. */
    if(world_walkable(&st->world, new_px, new_py)) {
        st->character.player_x = (int16_t)new_px;
        st->character.player_y = (int16_t)new_py;
    } else {
        st->character.player_x = (int16_t)st->world.spawn_x;
        st->character.player_y = (int16_t)st->world.spawn_y;
    }
    reset_visibility(st);
    set_statusf(st, "chunk (%d, %d)", cx, cy);
}

/* Cavern door: derive the crossing direction + perpendicular coord from
 * which edge the door sits on (the player is standing on the door tile). */
static void door_transition(AppState* st) {
    int px = st->character.player_x;
    int py = st->character.player_y;
    if(py == 0)                        do_transition(st, MoveNorth, px);
    else if(py == WORLD_ROWS - 1)      do_transition(st, MoveSouth, px);
    else if(px == 0)                   do_transition(st, MoveWest, py);
    else if(px == WORLD_COLS - 1)      do_transition(st, MoveEast, py);
    else set_status(st, "interior door (no exit yet)");
}

static void on_world_move(AppState* st, MoveDir dir) {
    if(dir == MoveNone) return;
    int px = st->character.player_x;
    int py = st->character.player_y;
    char dest_glyph = '\0';
    MoveResult r = world_try_move(&st->world, dir, &px, &py, &dest_glyph);
    st->character.player_x = (int16_t)px;
    st->character.player_y = (int16_t)py;

    /* A real action (not a blocked bump) costs a turn + a unit of torch
     * fuel — the event-driven clock (§14.0). Fuel floors at 0 (never
     * fully blind; radius stays 1). */
    bool took_turn = (r != MoveBlockedByWall && r != MoveBlockedByEdge);
    if(took_turn) {
        uint16_t old_fuel = st->character.torch_fuel;
        st->character.turn++;
        st->character.torch_fuel =
            (old_fuel >= FUEL_PER_TURN) ? (uint16_t)(old_fuel - FUEL_PER_TURN) : 0;
        if(old_fuel > 0 && st->character.torch_fuel == 0) {
            /* Torch just went OUT — the deepest panic. Distinct alarm
             * (buzz + red), not the gentle band-drop pulse. */
            notify(st, &sequence_error);
        } else if(fov_radius_for_fuel(st->character.torch_fuel) <
                  fov_radius_for_fuel(old_fuel)) {
            /* Light dimmed a band → a haptic pulse: feel the dark close in. */
            notify(st, &sequence_single_vibro);
        }
    }

    switch(r) {
    case MovePickedUpItem: {
        /* Map the picked glyph → kind for value + name. A torch (fuel>0)
         * refuels instead of just scoring — the light you hunt for. */
        const KindDef* k = kind_by_glyph(dest_glyph);
        if(k) {
            st->character.credits += k->value;
            st->character.identified |= (1ull << k->id);
            if(k->fuel > 0) {
                uint32_t f = (uint32_t)st->character.torch_fuel + k->fuel;
                st->character.torch_fuel =
                    (f > TORCH_FUEL_MAX) ? (uint16_t)TORCH_FUEL_MAX : (uint16_t)f;
                set_statusf(st, "%s  +%u fuel", k->true_name, (unsigned)k->fuel);
            } else {
                set_statusf(st, "found %s +%u", k->true_name, (unsigned)k->value);
            }
        } else {
            set_status(st, "found item");
        }
        notify(st, &sequence_success); /* pickup confirm: beep + green blink */
        deltas_record(
            st->character.campaign_id, &st->current_deltas,
            px, py, TILE_FLOOR);
        break;
    }
    case MoveSteppedOnDoor:
        door_transition(st);
        break;
    case MoveWalkedOffEdge:
        do_transition(st, dir,
                      (dir == MoveNorth || dir == MoveSouth) ? px : py);
        break;
    case MoveSteppedOnStairs:
        set_status(st, "stairs (Phase 4)");
        break;
    case MoveBlockedByWall:
    case MoveBlockedByEdge:
        st->status_line = NULL;
        break;
    case MoveOk:
        st->status_line = NULL;
        break;
    }

    /* Transitions recompute visibility for the new chunk inside
     * do_transition; same-chunk actions refresh here (fuel change may
     * have shrunk/grown the lit radius). */
    if(r != MoveSteppedOnDoor && r != MoveWalkedOffEdge) {
        recompute_visibility(st);
    }

    save_io_write_character(&st->character);
}

/* ─── main loop ────────────────────────────────────────────────────── */

int32_t sanctum_rpg_app(void* p) {
    UNUSED(p);

    AppState state = {
        .screen = ScreenTitle,
        .cursor = MenuNewGame,
        .status_line = NULL,
        .campaign_loaded = false,
        .muted = true, /* dev default — quiet device; toggle on in Settings */
    };

    SaveIoResult io_init = save_io_init();
    if(io_init != SaveIoOk) {
        set_status(&state, "SD init failed");
    } else if(save_io_count_campaigns() > 0) {
        state.cursor = MenuContinue;
    }

    FuriMessageQueue* input_queue =
        furi_message_queue_alloc(INPUT_QUEUE_DEPTH, sizeof(InputEvent));
    if(!input_queue) {
        return -1;
    }

    ViewPort* view_port = view_port_alloc();
    view_port_draw_callback_set(view_port, title_draw, &state);
    view_port_input_callback_set(view_port, title_input, input_queue);

    Gui* gui = furi_record_open(RECORD_GUI);
    gui_add_view_port(gui, view_port, GuiLayerFullscreen);
    state.notif = furi_record_open(RECORD_NOTIFICATION);

    bool running = true;
    InputEvent event;
    while(running) {
        FuriStatus s =
            furi_message_queue_get(input_queue, &event, FuriWaitForever);
        if(s != FuriStatusOk) continue;
        if(event.type != InputTypeShort && event.type != InputTypeRepeat) continue;

        /* Each input is a fresh frame — transient status cleared on title/picker,
         * preserved on world only when the move sets it. */
        if(state.screen != ScreenWorld) {
            state.status_line = NULL;
        }

        switch(state.screen) {
        case ScreenTitle:
            switch(event.key) {
            case InputKeyUp:
                state.cursor = (state.cursor + MenuCount - 1) % MenuCount;
                break;
            case InputKeyDown:
                state.cursor = (state.cursor + 1) % MenuCount;
                break;
            case InputKeyOk:   on_select_title(&state); break;
            case InputKeyBack: running = false; break;
            default: break;
            }
            break;

        case ScreenLoadPicker:
            switch(event.key) {
            case InputKeyUp:    picker_move(&state.picker, -1); break;
            case InputKeyDown:  picker_move(&state.picker, +1); break;
            case InputKeyOk:    on_picker_select(&state); break;
            case InputKeyBack:  state.screen = ScreenTitle; break;
            default: break;
            }
            break;

        case ScreenCodex:
            switch(event.key) {
            case InputKeyUp:
                if(state.codex_scroll > 0) state.codex_scroll--;
                break;
            case InputKeyDown:
                if(state.codex_scroll < KIND_COUNT - PICKER_VISIBLE_ROWS)
                    state.codex_scroll++;
                break;
            case InputKeyOk:
            case InputKeyBack:
                state.screen = ScreenTitle;
                break;
            default: break;
            }
            break;

        case ScreenWorld:
            if(state.examining) {
                /* Examine mode: d-pad moves the cursor (free — no turn),
                 * OK/Back exits. */
                switch(event.key) {
                case InputKeyUp:    examine_move(&state, 0, -1); break;
                case InputKeyDown:  examine_move(&state, 0, +1); break;
                case InputKeyLeft:  examine_move(&state, -1, 0); break;
                case InputKeyRight: examine_move(&state, +1, 0); break;
                case InputKeyOk:
                case InputKeyBack:
                    state.examining = false;
                    state.status_line = NULL;
                    break;
                default: break;
                }
            } else {
                switch(event.key) {
                case InputKeyUp:
                case InputKeyDown:
                case InputKeyLeft:
                case InputKeyRight:
                    on_world_move(&state, key_to_dir(event.key));
                    break;
                case InputKeyOk:
                    /* Enter examine at the player's tile — the teaching look. */
                    state.examining = true;
                    state.examine_x = state.character.player_x;
                    state.examine_y = state.character.player_y;
                    break;
                case InputKeyBack:
                    /* Last move's autosave is on disk — safe to leave. */
                    state.screen = ScreenTitle;
                    state.campaign_loaded = false;
                    state.status_line = NULL;
                    break;
                default: break;
                }
            }
            break;
        }

        view_port_update(view_port);
    }

    gui_remove_view_port(gui, view_port);
    furi_record_close(RECORD_GUI);
    furi_record_close(RECORD_NOTIFICATION);
    view_port_free(view_port);
    furi_message_queue_free(input_queue);

    return 0;
}
