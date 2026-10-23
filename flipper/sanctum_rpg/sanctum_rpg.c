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
#include <furi_hal_rtc.h>
#include <datetime/datetime.h>
#include <gui/gui.h>
#include <input/input.h>
#include <notification/notification_messages.h>
#include <storage/storage.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdio.h>

#include "biome.h"
#include "classes.h"
#include "creatures.h"
#include "deeds.h"
#include "deltas.h"
#include "fov.h"
#include "terrain.h"
#include "loot.h"
#include "narrative.h"
#include "pool.h"
#include "recipes.h"
#include "save_io.h"
#include "stamps.h"
#include "bearing.h"
#include "names.h"
#include "render_fpv.h"
#include "figure.h"
#include "trade.h"
#include "region.h"
#include "quirk.h"
#include "corruption.h"
#include "arc.h"
#include "dead.h"
#include "afflict.h"
#include "cast.h"
#include "effort.h"
#include "ritual.h"
#include "sky.h"
#include "weather.h"
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

/* Region gates (spec 58 §58.4). Live since the rite can be performed
 * (spec 58 step 5): the waking region is always open, and every region's
 * rite is reachable with what the region itself places (test_rituals_solvable,
 * test_arc_route1). */
#define REGION_GATES_LIVE 1
#define WORLD_VIEW_W          (WORLD_COLS * TILE_PX)  /* 128 px */
#define WORLD_VIEW_H          (WORLD_ROWS * TILE_PX)  /*  48 px */
#define WORLD_TILE_BASELINE_Y_OFFSET 7                /* FontSecondary baseline within 8px cell */
#define WORLD_STATUS_BASELINE 56                      /* below the grid */
#define WORLD_HINT_BASELINE   63                      /* corner hint */

/* Defaults for a fresh character on New Game. */
#define DEFAULT_HP            10
#define DEFAULT_MP            5
#define DEFAULT_LEVEL         1
#define DEFAULT_SHARDS        0  /* starting purse, in shards (kind 0) */
#define DEFAULT_SPAWN_X       1
#define DEFAULT_SPAWN_Y       1

/* ─── screen / menu model ─────────────────────────────────────────── */

typedef enum {
    ScreenTitle,
    ScreenLoadPicker,
    ScreenWorld,
    ScreenCodex,
    ScreenCombat,
    ScreenClassPick, /* slice 1c — New Game class picker (unreachable; spec 48.F2) */
    ScreenStatBuy,   /* slice 1c → 48.F3 — Profile Review (only PC builder) */
    ScreenCharSheet, /* slice 1c — read-only sheet (examine @ to open) */
    ScreenInventory, /* slice 2 — bag/equipment grid (from sheet, OK opens) */
    ScreenCraft,     /* slice 4 — the Forge: slot-machine recipe pull */
    ScreenShop,      /* slice 4 — sell items for shards */
    ScreenStash,     /* slice 2026-06-03d/C — home-chunk vault deposit/withdraw */
    ScreenQuest,     /* slice 49.F5 — quest surfaced, branch A/B choice */
    ScreenFpvDemo,   /* slice 2026-06-03e — Etrian-style FPV prototype (UAT) */
    ScreenSite,      /* spec 58 — a bumped site: seal, the rite */
    ScreenRite,      /* spec 58 §58.7 — the ways open to you */
    ScreenVigil,     /* spec 58 — the kept way, turn by turn */
    ScreenRunes,     /* spec 58 §58.7.2 — the seen way's puzzle */
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

    /* Live creatures in the current chunk (v0.4.0b) — RAM-only, regenerated
     * on chunk entry from the chunk seed (spec 45 §4.5-4.8). */
    Creature creatures[CREATURES_MAX];
    RegionRituals rituals;  /* regions whose ritual is done (spec 58); rituals.txt */
    RegionBook region_book; /* what the player has done in each region (spec 58 §58.10); regions.txt */

    /* The risen dead (spec 58 §58.6): saved in risen.txt. */
    RisenBook risen;
    /* What the dead leave and the dark crafts do (spec 50 Q1 §Q.4). RAM-only. */
    FoulField foul;              /* the bloated's patches, with expiry; cleared per chunk */
    uint8_t coating;             /* hits left on a sour-draught edge */
    uint8_t combat_foe_poison;   /* rounds of poison left on the foe */
    bool fell;                   /* set by player_fall: a rite in progress stops */
    /* A rising armed by chance: it lands next turn (the tell's one turn). */
    bool rise_pending;
    int8_t rise_x, rise_y;
    uint32_t rise_due;

    /* The corruption arc's screens (spec 58 §58.17). RAM-only. */
    int8_t site_k;           /* the bumped site's index in its region (ScreenSite); -1 = a plain grave */
    int8_t site_x, site_y;   /* the bumped tile */
    uint8_t site_kind;
    int8_t site_cursor;
    int8_t rite_cursor;      /* ScreenRite: row among the open ways */
    uint8_t rite_way;        /* the way being performed */
    EffortRun rite_run;      /* the vigil's / the runes' effort, turn by turn */
    RunePuzzle runes;        /* ScreenRunes */
    uint8_t rune_turn[RUNES_MAX];
    uint8_t rune_touched[RUNES_MAX];
    uint8_t rune_ntouched;
    int8_t rune_sel;
    /* A rune shown after the status line (a seen clue, spec 58 §58.7.2). */
    bool status_rune;
    uint8_t status_icon[8];
    uint8_t status_marks;
    QuirkPending quirk;     /* an armed cave-in (spec 50 Q1); RAM-only, cleared on leaving the chunk */
    uint32_t moon_said_night; /* sky_night_id the moon was last named on (0 = never); RAM-only */
    int creature_count;

    /* Examine mode (v0.3.5b) — the teaching channel. OK toggles a cursor
     * you move over visible tiles; the status line names what's under it.
     * Free (no turn/fuel cost) — looking isn't acting. */
    bool examining;
    int8_t examine_x, examine_y;

    /* Codex (v0.3.5c) — the logbook. codex_identified is loaded from the
     * most-recent campaign when opened from the title (no live character
     * there). The "scan→log" seed of the Metroid-Prime scan system. */
    uint64_t codex_identified;
    uint16_t codex_bestiary;
    int codex_scroll;

    /* Combat (v0.4.1, spec 46 §5.2) — a modal melee encounter vs one adjacent
     * hostile. Transient (RAM); the foe's live HP lives here, not on Creature. */
    int combat_foe;        /* index into creatures[]; -1 = not in combat */
    uint16_t combat_foe_hp;
    int combat_cursor;     /* verb: 0 STRIKE, 1 FLEE */
    uint16_t combat_round; /* per-encounter action counter (flee-roll variation) */
    uint8_t combat_grace;  /* turns combat is suppressed after a fall (anti-spiral) */

    /* New Game flow (slice 1c) — pending state held in memory during class
     * pick / stat buy, before the campaign is created on disk. Cancelling via
     * Back from class pick → no save artifact left behind. */
    uint32_t pending_seed;
    uint8_t pending_class_id;
    int8_t stat_buy_cursor; /* 0..5 = BODY CRAFT SIGHT MIND HEART WILL (slice 48.F1) */
    int8_t inv_cursor;      /* slice 2 — selected slot in ScreenInventory */
    int8_t craft_cursor;    /* slice 4 — recipe index in ScreenCraft */
    int8_t shop_cursor;     /* slice 4 — sellable-list index in ScreenShop */
    /* Slice 2026-06-03d (economy bundle, B): shop opens in two flavors.
     * `shop_is_vendor` = entered by stepping onto a TILE_VENDOR — full
     * chunk-modulated prices + buy/sell toggle. Else = inventory→Down
     * scrap dealer (half price, sell-only). `shop_mode` 0=SELL 1=BUY,
     * BUY available only when shop_is_vendor. */
    bool shop_is_vendor;
    uint8_t shop_mode;
    /* Slice 2026-06-03e — Etrian-style FPV view. Transient (per-session;
     * we don't bother persisting across sessions yet). 0=top-down,
     * 1=FPV. Toggled by long-press OK from ScreenWorld. */
    uint8_t view_mode;
    /* Slice 2026-06-03d/C — Stash screen state. `stash_cursor` indexes
     * a row that represents one kind id (rows are KIND_COUNT-shaped).
     * `stash_focus` 0=Bag, 1=Vault — which column is selected for the
     * deposit/withdraw verb. */
    int8_t stash_cursor;
    uint8_t stash_focus;

    NotificationApp* notif;  /* haptic/LED/sound feedback (v0.3.5d) */
    bool muted;              /* default ON during dev; toggled in Settings */

    /* Thread B — Forge slot-machine animation. View_port handle so the
     * animation can force redraw frames during a blocking pull. craft_
     * anim_frame > 0 puts the craft screen in animation mode; the draw
     * function shows cycling reels instead of the static recipe card. */
    ViewPort* view_port;
    uint8_t craft_anim_frame; /* 0 = idle; 1..ANIM_TOTAL = animating */
    char craft_reel_glyphs[3]; /* current reel symbols during animation */
    PullTier craft_pending_tier; /* computed at pull start, applied on reveal */

    /* Display name shown on the character sheet (slice 48.F2/F3 — "You ARE
     * the player"). Populated from CampaignMeta.character_name on enter_world;
     * persists for the duration of the campaign session. Empty string =
     * fall back to CLASS_YOU.name "You" on the sheet. */
    char display_name[32];

    /* Tensura ledger (slice 48.F4/F5/F6 — "You GROW through what you do").
     * In-RAM rollup of lifetime axis growth, scanned from
     * /ext/apps_data/sanctum_rpg/deeds_<real_self>/log.txt on app open. */
    DeedsState deeds;

    /* Atmosphere — current chunk's weather. Recomputed on chunk-enter
     * from RTC day + (campaign_seed × chunk_xy). Drives FOV cap, rain
     * overlay, and per-turn fuel burn. */
    Weather current_weather;

    /* Quest state (slice 49.F4/F5 — "world refers to your life"). pending_
     * quest_entry/template are -1 when no quest is surfaced; otherwise the
     * MOCK_PO_ENTRIES + QUEST_TEMPLATES indices for the active quest.
     * resolved_mask is a session bitmap (bit per entry) preventing the same
     * entry re-surfacing within this app run. */
    int8_t pending_quest_entry;
    int8_t pending_quest_template;
    int8_t quest_choice; /* 0 = branch A, 1 = branch B */
    uint32_t resolved_mask;

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
    c->inv_qty[TRADE_NUMERAIRE_KIND] = DEFAULT_SHARDS;
    c->identified = 0;
    c->turn = 0;
    c->torch_fuel = TORCH_FUEL_MAX;
    c->observe = 20; /* basic scan skill — common creatures readable at the start */
    c->bestiary = 0;
    /* Class + 6-axis block (slice 48.F1: BODY/CRAFT/SIGHT/MIND/HEART/WILL,
     * was STR/DEX/WIS/INT/CHA/CON). Wanderer baseline 10×6 + starting verbs.
     * Class picker / point-buy can override these before the first save. */
    c->class_id = CLASS_WANDERER;
    c->body = 10;
    c->craft = 10;
    c->sight = 10;
    c->mind = 10;
    c->heart = 10;
    c->will = 10;
    c->verbs_mask = VERBS_STARTING_MASK;
    /* Inventory + equipment (slice 2): empty bag, nothing equipped. */
    for(int i = 0; i < SAVE_INV_KINDS_MAX; i++) c->inv_qty[i] = 0;
    c->equipped_weapon = SAVE_EQUIP_NONE;
    c->equipped_light = SAVE_EQUIP_NONE;
    c->equipped_armor = SAVE_EQUIP_NONE;
    /* Thread C — D&D-style equipment expertise. Every kind starts at 25
     * (basic familiarity); use grows it +1 per equipped action. Bonus
     * scales linearly: effective = base × expertise / 100. At 25 you get
     * 1/4 of the bonus; at 100 you get full; at 0 you get nothing (legacy
     * unloaded saves). */
    for(int i = 0; i < SAVE_INV_KINDS_MAX; i++) c->expertise[i] = 25;
    c->words_known = 0;   /* schema 9: the corruption arc, per seed */
    c->recipes_known = 0;
    c->bleed = 0;
    c->chill = 0;
    c->casts_known = 0;   /* schema 10: earned by deep scans (spec 46 §5.1) */
    c->schema_version = SAVE_IO_SCHEMA_VERSION;
}

/* Apply a class's axis block + starting verbs to a character. Used by the
 * class picker to sync `st->character` to the highlighted class. */
static void character_apply_class(CharacterState* c, uint8_t class_id) {
    const ClassDef* cls = class_def(class_id);
    if(!cls) cls = class_def(CLASS_WANDERER);
    c->class_id = class_id;
    c->body  = cls->body;
    c->craft = cls->craft;
    c->sight = cls->sight;
    c->mind  = cls->mind;
    c->heart = cls->heart;
    c->will  = cls->will;
    c->verbs_mask = cls->verbs_mask;
}

/* Fire a haptic/LED/sound feedback sequence (no-op if unavailable or muted). */
static void notify(AppState* st, const NotificationSequence* seq) {
    if(st->notif && !st->muted) notification_message(st->notif, seq);
}

/* Linear scan for a live creature on a tile (small per-chunk N). */
static const Creature* creature_at(const AppState* st, int x, int y) {
    for(int i = 0; i < st->creature_count; i++) {
        const Creature* c = &st->creatures[i];
        if(c->alive && c->x == (uint8_t)x && c->y == (uint8_t)y) return c;
    }
    return NULL;
}

/* (Re)spawn the current chunk's creatures from its seed (RAM-only). Called
 * after every world_generate_chunk + delta overlay. */
/* Refresh st->current_weather for the current chunk + today's date.
 * Called on chunk-enter (transition + initial world entry). Same chunk
 * on the same day → byte-equal weather. Day rollover advances the
 * pattern naturally because RTC day changes. */
static void refresh_weather(AppState* st) {
    DateTime now;
    furi_hal_rtc_get_datetime(&now);
    uint64_t now_unix = datetime_datetime_to_timestamp(&now);
    uint32_t day = (uint32_t)(now_unix / 86400u);
    /* Indoors is attenuated by ENCLOSURE, not realm: a manor's hall hears
     * the rain above like a cavern does (weather.h). */
    uint8_t wbiome = (world_terrain(&st->world) == TERRAIN_WALLED)
                         ? STAMP_BIOME_CAVERN : STAMP_BIOME_OUTDOOR;
    weather_at(st->campaign_seed,
               (int)st->character.chunk_x, (int)st->character.chunk_y,
               day, wbiome, &st->current_weather);
}

static void populate_creatures(AppState* st) {
    uint32_t cs = rng_chunk_seed(
        st->campaign_seed, st->character.chunk_x, st->character.chunk_y);
    /* Slice 50.F2: compute the Pool for this chunk and pass it through
     * so the family roll reads pool->family_bias. Same canonical walk as
     * world.c uses for the stamp composer — byte-equal Pool. */
    Pool pool;
    uint8_t pool_biome = biome_pool(st->world.biome);
    pool_at(st->campaign_seed, pool_biome,
            (int)st->character.chunk_x, (int)st->character.chunk_y, &pool);
    st->creature_count = creatures_populate_pooled(
        cs, st->world.biome, &st->world, st->character.player_x,
        st->character.player_y, &pool, st->creatures, CREATURES_MAX);
    /* Apply persisted kills (slice 1b) — defeated creatures stay defeated
     * across chunk re-entry. Keyed by deterministic spawn position. */
    for(int k = 0; k < st->current_deltas.kill_count; k++) {
        creatures_mark_dead_at_spawn(
            st->creatures, st->creature_count,
            st->current_deltas.kills[k].spawn_x,
            st->current_deltas.kills[k].spawn_y);
    }
    /* The risen are still up where they rose (spec 50 Q1 §Q.1.2). */
    dead_restore(&st->risen, st->character.chunk_x, st->character.chunk_y, &st->world,
                 st->character.player_x, st->character.player_y, st->creatures,
                 &st->creature_count, CREATURES_MAX);
}

/* Recompute the lit set from the player's position + torch radius, and
 * OR newly-lit tiles into the seen (remembered) set. Cheap — 96 tiles. */
static void recompute_visibility(AppState* st) {
    int radius = fov_radius_for_fuel(st->character.torch_fuel);
    /* Atmosphere: fog/storm caps the FOV. weather_apply_fov clamps to
     * a minimum of 1 so the player is never blinded outright. */
    radius = weather_apply_fov(&st->current_weather, radius);
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
/* Phase 2 of campaign entry: world gen + deltas + creatures + screen switch.
 * Caller has already populated `st->character` + `st->campaign_seed`. Shared
 * by `enter_world` (Continue/Load) and `finalize_new_character` (New Game). */
/* The corruption arc's records (spec 58 §58.10): the rituals done and the
 * region book, each a small text file next to character.json. A missing
 * file is a fresh campaign; a bad one loads what it can (tolerant saves). */
static void arc_load(AppState* st, const char* campaign_id) {
    region_rituals_clear(&st->rituals);
    region_book_clear(&st->region_book);
    risen_book_clear(&st->risen);
    st->rise_pending = false;
    char* buf = malloc(REGION_BOOK_TEXT_MAX);
    if(!buf) return;
    if(save_io_read_text(campaign_id, "risen.txt", buf, REGION_BOOK_TEXT_MAX) == SaveIoOk)
        risen_book_parse(buf, &st->risen);
    if(save_io_read_text(campaign_id, "rituals.txt", buf, REGION_BOOK_TEXT_MAX) == SaveIoOk)
        region_rituals_parse(buf, &st->rituals);
    if(save_io_read_text(campaign_id, "regions.txt", buf, REGION_BOOK_TEXT_MAX) == SaveIoOk)
        region_book_parse(buf, &st->region_book);
    free(buf);
}

static void arc_save(AppState* st) {
    char* buf = malloc(REGION_BOOK_TEXT_MAX);
    if(!buf) return;
    size_t n = region_rituals_format(&st->rituals, buf, REGION_BOOK_TEXT_MAX);
    save_io_write_text(st->character.campaign_id, "rituals.txt", buf, n);
    n = region_book_format(&st->region_book, buf, REGION_BOOK_TEXT_MAX);
    save_io_write_text(st->character.campaign_id, "regions.txt", buf, n);
    n = risen_book_format(&st->risen, buf, REGION_BOOK_TEXT_MAX);
    save_io_write_text(st->character.campaign_id, "risen.txt", buf, n);
    free(buf);
}

/* Mark this chunk's edges into closed regions (the haze, spec 58 §58.4).
 * The waking region seems pristine until its rot is found (§58.3.1): no
 * haze there until then, and its closed edges refuse quietly. */
static bool arc_region_found(const AppState* st, int rx, int ry) {
    const RegionRecord* r = region_book_get(&st->region_book, rx, ry);
    return region_depth(st->campaign_seed, rx, ry) > 0 || (r && (r->flags & RR_FOUND));
}

static void arc_mark_edges(AppState* st) {
    if(!REGION_GATES_LIVE) return;
    int cx = st->character.chunk_x, cy = st->character.chunk_y;
    region_mark_world_edges(st->campaign_seed, &st->rituals, cx, cy, &st->world);
    if(!arc_region_found(st, region_of(cx), region_of(cy))) st->world.closed_edges = 0;
}

static void enter_world_phase2(
    AppState* st, const char* campaign_id, bool fresh_character) {
    world_generate_chunk(
        st->campaign_seed,
        st->character.chunk_x, st->character.chunk_y,
        &st->world);
    arc_mark_edges(st);

    deltas_load(
        campaign_id,
        st->character.chunk_x, st->character.chunk_y,
        &st->current_deltas);
    deltas_apply_to_world(&st->current_deltas, &st->world);

    if(fresh_character || !world_walkable(&st->world, st->character.player_x,
                                          st->character.player_y)) {
        st->character.player_x = (int16_t)st->world.spawn_x;
        st->character.player_y = (int16_t)st->world.spawn_y;
        save_io_write_character(&st->character);
    }
    /* Atmosphere — refresh weather BEFORE FOV recompute so the cap takes
     * effect on the first frame in the new chunk. */
    refresh_weather(st);
    populate_creatures(st);

    save_io_touch_played(campaign_id);
    reset_visibility(st);
    st->examining = false;
    st->campaign_loaded = true;
    st->screen = ScreenWorld;
    /* Initial chunk-enter status: weather hint precedence, then procgen
     * place name. Mirrors do_transition (see chunk-transition handler). */
    {
        const char* hint = weather_enter_hint(&st->current_weather);
        if(hint) {
            set_status(st, hint);
        } else {
            char place[NAME_MAX_LEN];
            name_for_chunk(
                st->campaign_seed,
                st->character.chunk_x, st->character.chunk_y,
                (uint8_t)st->world.style, place, sizeof(place));
            set_statusf(st, "%s", place);
        }
    }

    /* Slice 49.F4 — surface a quest on initial chunk arrival too (not just
     * on chunk transitions). Same picker as do_transition; if this chunk
     * is the anchor for an unresolved entry, open ScreenQuest. */
    if(st->pending_quest_entry < 0) {
        /* Slice 50.F4: Pool-biased narrative pick — themes whose Pool
         * weight is "foreground" boost the picked template's score. */
        Pool npool;
        uint8_t nbiome = biome_pool(st->world.biome);
        pool_at(st->campaign_seed, nbiome,
                (int)st->character.chunk_x, (int)st->character.chunk_y, &npool);
        uint8_t qe, qt;
        if(narrative_pick_for_chunk_pooled(
               st->campaign_seed,
               (int)st->character.chunk_x, (int)st->character.chunk_y,
               st->resolved_mask, &npool, &qe, &qt)) {
            st->pending_quest_entry = (int8_t)qe;
            st->pending_quest_template = (int8_t)qt;
            st->quest_choice = 0;
            st->screen = ScreenQuest;
        }
    }
}

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

    st->campaign_seed = meta.seed;
    arc_load(st, campaign_id);
    /* Carry meta.character_name into the in-session display_name (slice 48.F2/F3).
     * The character sheet shows YOU by your name, not by class label. */
    strncpy(st->display_name, meta.character_name, sizeof(st->display_name) - 1);
    st->display_name[sizeof(st->display_name) - 1] = '\0';
    enter_world_phase2(st, campaign_id, fresh_character);
    return true;
}

/* Finalize the New Game flow (slice 1c) — the campaign isn't created on disk
 * until the player confirms in class pick / stat buy. `st->character` already
 * holds the picked class + stats; here we allocate the campaign id, bind it,
 * persist, and enter the world. Cancelling earlier leaves no disk artifact. */
static void finalize_new_character(AppState* st) {
    char id[SAVE_IO_CAMPAIGN_ID_MAX + 1];
    /* The user's real-self name is the character name (slice 48.F2 — You-only).
     * Stays hardcoded until the profile.json read-side lands (slice 48.F8 /
     * dock work); when it does, this string sources from profile.name. */
    const char* real_self_name = "themrburn";
    SaveIoResult r = save_io_new_campaign(
        real_self_name, st->pending_seed, id, sizeof(id));
    if(r != SaveIoOk) {
        st->screen = ScreenTitle;
        set_status(
            st, r == SaveIoFull ? "all 999 slots used" : "SD write failed");
        return;
    }
    strncpy(
        st->character.campaign_id, id, sizeof(st->character.campaign_id) - 1);
    st->character.campaign_id[sizeof(st->character.campaign_id) - 1] = '\0';
    /* Stamp the display_name for the in-session sheet header. */
    strncpy(st->display_name, real_self_name, sizeof(st->display_name) - 1);
    st->display_name[sizeof(st->display_name) - 1] = '\0';
    st->campaign_seed = st->pending_seed;
    save_io_write_character(&st->character);
    enter_world_phase2(st, id, true);
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
    /* A creature you can currently see names over terrain/loot. */
    if(lit) {
        const Creature* c = creature_at(st, x, y);
        if(c) {
            static char cbuf[24];
            CreatureDef d;
            creature_compose(c->family_id, c->trait_id, &d);
            creature_name(&d, cbuf, (int)sizeof(cbuf));
            return cbuf;
        }
    }
    char t = st->world.tiles[y][x];
    const KindDef* k = kind_by_glyph(t);
    if(k) {
        if(!lit) return "floor"; /* remembered: loot not currently visible */
        bool known = ((st->character.identified >> k->id) & 1ull) != 0;
        return known ? k->true_name : k->unid_name;
    }
    /* Terrain is named by its TERRAIN row; walls by the region's style. */
    const char* tn = terrain_name(t, STYLE_TABLE[world_wall_style(&st->world, x, y)].wall_name);
    if(tn) return tn;
    switch(t) {
    case TILE_DOOR:        return "doorway";
    case TILE_VENDOR:      return "vendor";
    case TILE_VAULT:       return "vault";
    case TILE_STAIRS_UP:   return "stairs up";
    case TILE_STAIRS_DOWN: return "stairs down";
    case TILE_FLOOR:
    default: {
        /* Examine on empty ground → the chunk's procedural name + coords,
         * so navigation remains possible (the status line shows the name
         * alone, no coords; examine is where the player keeps both). */
        /* NAME_MAX_LEN + " (-12345, -12345)" worst case + headroom. */
        static char fbuf[NAME_MAX_LEN + 24];
        char place[NAME_MAX_LEN];
        name_for_chunk(
            st->campaign_seed,
            st->character.chunk_x, st->character.chunk_y,
            (uint8_t)st->world.style, place, sizeof(place));
        snprintf(fbuf, sizeof(fbuf), "%s (%d, %d)",
                 place,
                 (int)st->character.chunk_x, (int)st->character.chunk_y);
        return fbuf;
    }
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

/* ─── render: codex (logbook) ─────────────────────────────────────── */

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

    /* One scrolling list: loot kinds first, then the creature bestiary. */
    int total = KIND_COUNT + CREATURE_FAMILY_COUNT;
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

    static const char* const VERBS[3] = {"STRIKE", "FLEE", "THROW"};
    int nverbs = afflict_throwable(&st->character) != 0xFFu ? 3 : 2;   /* THROW only with a flask */
    for(int i = 0; i < nverbs; i++) {
        int y = 34 + i * MENU_LINE_HEIGHT;
        if(i == st->combat_cursor) {
            canvas_draw_box(
                canvas, MENU_HIGHLIGHT_INSET, y - (MENU_LINE_HEIGHT - 2), 50, MENU_LINE_HEIGHT);
            canvas_invert_color(canvas);
            canvas_draw_str(canvas, MENU_TEXT_X, y, VERBS[i]);
            canvas_invert_color(canvas);
        } else {
            canvas_draw_str(canvas, MENU_TEXT_X, y, VERBS[i]);
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

/* Is the given kind id equipped in any slot? (slice 2) */
static bool is_equipped(const CharacterState* c, uint8_t kind_id) {
    return c->equipped_weapon == kind_id || c->equipped_light == kind_id ||
           c->equipped_armor == kind_id;
}

/* Use the selected inventory slot: equip/unequip if KF_EQUIP, consume +heal
 * if KF_CONSUMABLE, no-op otherwise. (slice 2) */
static void inventory_use(AppState* st) {
    int idx = st->inv_cursor;
    if(idx < 0 || idx >= KIND_COUNT || idx >= SAVE_INV_KINDS_MAX) return;
    uint8_t qty = st->character.inv_qty[idx];
    if(qty == 0) {
        set_status(st, "(empty slot)");
        return;
    }
    const KindDef* k = kind_by_id((uint8_t)idx);
    if(!k) return;

    if(k->flags & KF_EQUIP) {
        /* Route to the correct slot via KindDef.equip_slot (slice 5).
         * Weapon = atk_bonus contributor; armor = def_bonus; light = future
         * vision-radius extender. A future lantern kind drops into the
         * catalog with equip_slot=EQ_LIGHT and lands here for free. */
        uint8_t* slot = NULL;
        switch((EquipSlot)k->equip_slot) {
        case EQ_WEAPON: slot = &st->character.equipped_weapon; break;
        case EQ_ARMOR:  slot = &st->character.equipped_armor;  break;
        case EQ_LIGHT:  slot = &st->character.equipped_light;  break;
        default: break;
        }
        if(!slot) {
            /* KF_EQUIP set but no slot — data error; surface, do not crash. */
            set_status(st, "(no slot)");
            return;
        }
        if(*slot == (uint8_t)idx) {
            *slot = SAVE_EQUIP_NONE;
            set_statusf(st, "unequipped %s", k->true_name);
        } else {
            *slot = (uint8_t)idx;
            set_statusf(st, "equipped %s", k->true_name);
        }
        notify(st, &sequence_success);
    } else if(idx == AF_KIND_DRAUGHT) {
        /* A sour draught coats your edge: the next hits that land poison. */
        st->character.inv_qty[idx]--;
        st->coating = COATING_HITS;
        set_status(st, AF_LINE_COATED);
        notify(st, &sequence_success);
    } else if((k->flags & KF_CONSUMABLE) && k->heal > 0) {
        /* Consume → +heal HP (clamped to max_hp). Decrement count. */
        int new_hp = (int)st->character.hp + (int)k->heal;
        if(new_hp > (int)st->character.max_hp) new_hp = (int)st->character.max_hp;
        st->character.hp = (uint16_t)new_hp;
        st->character.inv_qty[idx]--;
        set_statusf(st, "used %s +%u HP", k->true_name, (unsigned)k->heal);
        notify(st, &sequence_success);
    } else {
        set_status(st, "no use here");
    }
    save_io_write_character(&st->character);
}

/* ── The purse (spec 43 §17.1) ────────────────────────────────────────
 * `credits` is deleted; the shard (kind 0) IS the money, so the wallet is
 * the bag slot. These three helpers are the ONLY places that touch it, so
 * the uint8 cap is honored in one spot instead of at four call sites. */
static uint16_t purse(const AppState* st) {
    return (uint16_t)st->character.inv_qty[TRADE_NUMERAIRE_KIND];
}

/* Would `shards` more fit? Callers that are about to give something up in
 * exchange MUST ask first — see shop_sell. */
static bool purse_has_room(const AppState* st, uint16_t shards) {
    return (uint32_t)purse(st) + shards <= 255u;
}

/* Add shards, saturating at the slot cap. Returns what actually fit. Only
 * safe to ignore the return where room was checked first. */
static uint16_t purse_add(AppState* st, uint16_t shards) {
    uint32_t held = (uint32_t)purse(st) + shards;
    if(held > 255u) held = 255u;
    uint16_t gained = (uint16_t)(held - purse(st));
    st->character.inv_qty[TRADE_NUMERAIRE_KIND] = (uint8_t)held;
    return gained;
}

/* Spend shards. Returns false (and spends nothing) if the purse is short. */
static bool purse_take(AppState* st, uint16_t shards) {
    if(purse(st) < shards) return false;
    st->character.inv_qty[TRADE_NUMERAIRE_KIND] =
        (uint8_t)(purse(st) - shards);
    return true;
}

/* Build the list of sellable kind ids (qty > 0 and value > 0). Returns count.
 * The Shop screen's cursor is an index INTO this list, not a kind id. */
static int build_sellable_list(const CharacterState* c, uint8_t* out, int max) {
    int n = 0;
    for(int i = 0; i < KIND_COUNT && n < max && i < SAVE_INV_KINDS_MAX; i++) {
        const KindDef* k = kind_by_id((uint8_t)i);
        if(!k) continue;
        if(c->inv_qty[i] == 0) continue;
        if(k->value == 0) continue;
        /* §17.3 #1 — the money is not stock; spec 58 — nor is an artifact.
         * Excluded, not priced at 0. */
        if(trade_kind_untradeable((uint8_t)i)) continue;
        out[n++] = (uint8_t)i;
    }
    return n;
}

/* The Forge pull (slice 4) — consume inputs, roll the tier, apply outcome. */
/* Thread B — Forge slot-machine constants. The animation runs blocking
 * inside the input handler, repeatedly redrawing while furi_delay_ms
 * paces frames. Total ~600ms — long enough to feel like a draw, short
 * enough not to make you wait. */
#define CRAFT_ANIM_SPIN_FRAMES   10  /* fast cycling */
#define CRAFT_ANIM_SETTLE_FRAMES  2  /* brief pause on result before status */
#define CRAFT_ANIM_TOTAL         (CRAFT_ANIM_SPIN_FRAMES + CRAFT_ANIM_SETTLE_FRAMES)
#define CRAFT_ANIM_FRAME_MS      50  /* 50ms × 12 frames = 600ms */

/* The pool of glyphs the reels cycle through during the spin. Drawn from
 * the recipe inputs + output so the reels visually pull from the work. */
static char craft_reel_pool(const RecipeDef* r, int idx) {
    char pool[] = {'*', '&', 'u', '!', '(', 'i', 'T'};
    /* If we have a real recipe, bias the pool toward its kinds. */
    if(r) {
        const KindDef* k = kind_by_id(r->output_kind);
        if(k) pool[0] = k->glyph;
        if(r->input_kind_a < SAVE_INV_KINDS_MAX) {
            const KindDef* ki = kind_by_id(r->input_kind_a);
            if(ki) pool[1] = ki->glyph;
        }
    }
    return pool[idx % (int)(sizeof(pool) / sizeof(pool[0]))];
}

static void craft_pull(AppState* st) {
    const RecipeDef* r = recipe_def((uint8_t)st->craft_cursor);
    if(!r) return;
    if(!recipe_craftable(r, st->character.inv_qty, SAVE_INV_KINDS_MAX)) {
        set_status(st, "need more materials");
        return;
    }
    /* Consume inputs. */
    if(r->input_kind_a < SAVE_INV_KINDS_MAX) {
        st->character.inv_qty[r->input_kind_a] -= r->input_qty_a;
    }
    if(r->input_kind_b != RECIPE_NO_INPUT &&
       r->input_kind_b < SAVE_INV_KINDS_MAX) {
        st->character.inv_qty[r->input_kind_b] -= r->input_qty_b;
    }
    /* Roll — deterministic from (chunk × turn × craft_cursor). */
    Rng pull_rng;
    rng_seed(
        &pull_rng,
        rng_chunk_seed(
            st->campaign_seed, st->character.chunk_x, st->character.chunk_y) ^
            (st->character.turn * 2654435761u) ^
            ((uint32_t)st->craft_cursor * 40503u) ^ 0xF09EA1A1u);
    PullTier tier = recipe_pull(&pull_rng, r);
    st->craft_pending_tier = tier;

    const KindDef* output = kind_by_id(r->output_kind);
    const char* out_name = output ? output->true_name : "??";
    char out_glyph = output ? output->glyph : '?';

    /* Thread B — slot-machine animation. The tier is already computed
     * (deterministic), but we don't reveal it until the reels settle.
     * Reel glyphs cycle from a recipe-relevant pool; on the final frame
     * they lock to a tier-appropriate pattern:
     *   JACKPOT → three matching output glyphs
     *   HIT     → two output glyphs + one fill
     *   FLOOR   → one output glyph + two dots */
    Rng spin_rng;
    rng_seed(&spin_rng, st->character.turn ^ (uint32_t)st->craft_cursor);
    for(int f = 1; f <= CRAFT_ANIM_TOTAL; f++) {
        st->craft_anim_frame = (uint8_t)f;
        if(f < CRAFT_ANIM_SPIN_FRAMES) {
            /* Spinning: random glyphs from the pool each frame. */
            for(int slot = 0; slot < 3; slot++) {
                uint32_t k = rng_range(&spin_rng, 0, 7);
                st->craft_reel_glyphs[slot] = craft_reel_pool(r, (int)k);
            }
        } else {
            /* Settled — show tier-appropriate final pattern. */
            switch(tier) {
            case PULL_JACKPOT:
                st->craft_reel_glyphs[0] = out_glyph;
                st->craft_reel_glyphs[1] = out_glyph;
                st->craft_reel_glyphs[2] = out_glyph;
                break;
            case PULL_HIT:
                st->craft_reel_glyphs[0] = out_glyph;
                st->craft_reel_glyphs[1] = out_glyph;
                st->craft_reel_glyphs[2] = '-';
                break;
            case PULL_FLOOR:
            default:
                st->craft_reel_glyphs[0] = '.';
                st->craft_reel_glyphs[1] = out_glyph;
                st->craft_reel_glyphs[2] = '.';
                break;
            }
        }
        if(st->view_port) view_port_update(st->view_port);
        furi_delay_ms(CRAFT_ANIM_FRAME_MS);
    }
    st->craft_anim_frame = 0; /* end animation; back to recipe card */

    /* Apply tier effects + sanctum-voice reveal messaging. */
    switch(tier) {
    case PULL_JACKPOT:
        if(r->output_kind < SAVE_INV_KINDS_MAX) {
            int q = (int)st->character.inv_qty[r->output_kind] + 2;
            st->character.inv_qty[r->output_kind] = (uint8_t)(q > 255 ? 255 : q);
            st->character.identified |= (1ull << r->output_kind);
        }
        set_statusf(st, "the %s sings  x2", out_name);
        notify(st, &sequence_success);
        deeds_record(&st->deeds, "themrburn",
                     st->character.campaign_id, st->character.turn,
                     DEED_FORGE_JACKPOT);
        break;
    case PULL_HIT:
        if(r->output_kind < SAVE_INV_KINDS_MAX &&
           st->character.inv_qty[r->output_kind] < 255) {
            st->character.inv_qty[r->output_kind]++;
            st->character.identified |= (1ull << r->output_kind);
        }
        set_statusf(st, "the %s takes shape", out_name);
        notify(st, &sequence_success);
        deeds_record(&st->deeds, "themrburn",
                     st->character.campaign_id, st->character.turn,
                     DEED_FORGE_HIT);
        break;
    case PULL_FLOOR: {
        /* §17.3 #3 — the floor pays a sellable OBJECT, never currency.
         * Same guarded add as the HIT branch, so the uint8 cap holds. */
        const KindDef* odd = kind_by_id(r->oddment_kind);
        if(r->oddment_kind < SAVE_INV_KINDS_MAX &&
           st->character.inv_qty[r->oddment_kind] < 255) {
            st->character.inv_qty[r->oddment_kind]++;
            st->character.identified |= (1ull << r->oddment_kind);
        }
        set_statusf(st, "the work resists  %s",
                    odd ? odd->true_name : "scrap");
        notify(st, &sequence_single_vibro);
        /* No deed on FLOOR — the oddment IS the consolation; growth waits
         * for HIT. */
        break;
    }
    }
    save_io_write_character(&st->character);
}

/* ─── Stash (home-chunk vault) helpers ──────────────────────────────────
 * The vault holds a parallel inventory (`vault_qty[]`) persisted across
 * sessions in the character save (schema 7). Deposit/withdraw moves one
 * unit at a time between `inv_qty` and `vault_qty` for the focused kind.
 * Capacity per slot: 255 (uint8). */

static void stash_deposit(AppState* st) {
    if(st->stash_cursor < 0 || st->stash_cursor >= SAVE_INV_KINDS_MAX) return;
    uint8_t id = (uint8_t)st->stash_cursor;
    if(st->character.inv_qty[id] == 0) {
        set_status(st, "(none in bag)");
        return;
    }
    if(st->character.vault_qty[id] >= 255) {
        set_status(st, "(vault full)");
        return;
    }
    st->character.inv_qty[id]--;
    st->character.vault_qty[id]++;
    const KindDef* k = kind_by_id(id);
    set_statusf(st, "stashed %s", k ? k->true_name : "?");
    notify(st, &sequence_success);
    save_io_write_character(&st->character);
}

static void stash_withdraw(AppState* st) {
    if(st->stash_cursor < 0 || st->stash_cursor >= SAVE_INV_KINDS_MAX) return;
    uint8_t id = (uint8_t)st->stash_cursor;
    if(st->character.vault_qty[id] == 0) {
        set_status(st, "(none in vault)");
        return;
    }
    if(st->character.inv_qty[id] >= 255) {
        set_status(st, "(bag full)");
        return;
    }
    st->character.vault_qty[id]--;
    st->character.inv_qty[id]++;
    const KindDef* k = kind_by_id(id);
    set_statusf(st, "took %s", k ? k->true_name : "?");
    notify(st, &sequence_success);
    save_io_write_character(&st->character);
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

/* Build the list of kinds this vendor sells in THIS chunk. A first-cut
 * stock model: every catalog kind that's pickupable + has a value + has
 * biome affinity matching the vendor's chunk biome. Carrying capacity
 * (8 inventory slots) is the natural throttle; per-vendor finite stock
 * lands in a later slice. */
static int build_buyable_list(uint8_t biome, uint8_t* out, int max) {
    int n = 0;
    uint8_t bbit = BIOME_BIT((Biome)biome);
    for(int i = 0; i < KIND_COUNT && n < max; i++) {
        const KindDef* k = kind_by_id((uint8_t)i);
        if(!k) continue;
        if(!(k->flags & KF_PICKUPABLE)) continue;
        if(k->value == 0) continue;
        if(!(k->biomes & bbit)) continue;
        /* §17.3 #1 — a vendor never sells you money (nor an artifact, spec 58). */
        if(trade_kind_untradeable((uint8_t)i)) continue;
        out[n++] = (uint8_t)i;
    }
    return n;
}

/* Current shop's price for a given kind. At a vendor: sell uses
 * trade_sell_price (vendor bid), buy uses trade_buy_price (vendor ask).
 * From inventory→Down (no vendor): scrap_price for sells only — buy
 * mode is unreachable there. */
static uint16_t shop_price_for(
    const AppState* st, uint8_t kind_id, uint16_t base, bool is_buy) {
    if(st->shop_is_vendor) {
        int8_t delta = chunk_price_delta(
            st->campaign_seed,
            (int)st->character.chunk_x,
            (int)st->character.chunk_y,
            kind_id);
        return is_buy ? trade_buy_price(kind_id, base, delta)
                      : trade_sell_price(kind_id, base, delta);
    }
    /* Scrap dealer is sell-only; the BUY branch never reaches here in
     * normal flow, but if it did, treat as the same scrap rate. */
    return trade_scrap_price(kind_id, base);
}

/* Sell one of the cursor's item at the shop's current bid price. */
static void shop_sell(AppState* st) {
    uint8_t sellable[KIND_COUNT];
    int n = build_sellable_list(&st->character, sellable, KIND_COUNT);
    if(n == 0) {
        set_status(st, "bag empty");
        return;
    }
    if(st->shop_cursor < 0) st->shop_cursor = 0;
    if(st->shop_cursor >= n) st->shop_cursor = (int8_t)(n - 1);
    uint8_t id = sellable[st->shop_cursor];
    const KindDef* k = kind_by_id(id);
    if(!k) return;
    uint16_t price = shop_price_for(st, id, k->value, false);
    if(price == TRADE_NO_PRICE) return; /* numeraire — never listed anyway */
    /* §17.5 — prices are in `value`; payment is in whole shards, and the
     * remainder is the player's loss (§17.5a rule 1). Cheap items are not
     * individually worth selling; you sell in lots. */
    uint16_t paid = trade_shards_earned(price);
    if(paid == 0) {
        set_statusf(st, "%s is not worth a shard alone", k->true_name);
        notify(st, &sequence_error);
        return;
    }
    /* §17.3 #8 — the 255 cap is ACCEPTED as the encumbrance mechanic, which
     * means a sale that would not fit is REFUSED, never partially paid. The
     * buy path already bails before spending; this is the same discipline on
     * the other side. Paying what fits and dropping the rest would take the
     * item and silently eat the difference. */
    if(!purse_has_room(st, paid)) {
        set_status(st, "you have nowhere to put it");
        notify(st, &sequence_error);
        return;
    }
    st->character.inv_qty[id]--;
    purse_add(st, paid);
    set_statusf(st, "sold %s", k->true_name);
    notify(st, &sequence_success);
    save_io_write_character(&st->character);
}

/* Buy one of the cursor's item at the vendor's ask price. Vendor only —
 * the scrap dealer (inventory→Down) doesn't expose BUY mode. */
static void shop_buy(AppState* st) {
    if(!st->shop_is_vendor) return;
    uint8_t buyable[KIND_COUNT];
    int n = build_buyable_list((uint8_t)st->world.biome, buyable, KIND_COUNT);
    if(n == 0) {
        set_status(st, "(vendor has nothing for you)");
        return;
    }
    if(st->shop_cursor < 0) st->shop_cursor = 0;
    if(st->shop_cursor >= n) st->shop_cursor = (int8_t)(n - 1);
    uint8_t id = buyable[st->shop_cursor];
    const KindDef* k = kind_by_id(id);
    if(!k) return;
    uint16_t price = shop_price_for(st, id, k->value, true);
    if(price == TRADE_NO_PRICE) return; /* numeraire — never listed anyway */
    /* A part-shard debt costs a whole shard (§17.5a rule 1). */
    uint16_t cost = trade_shards_owed(price);
    if(purse(st) < cost) {
        set_statusf(st, "need %u more", (unsigned)(cost - purse(st)));
        notify(st, &sequence_error);
        return;
    }
    if(id >= SAVE_INV_KINDS_MAX || st->character.inv_qty[id] >= 255) {
        set_status(st, "bag full");
        return;
    }
    if(!purse_take(st, cost)) return;
    st->character.inv_qty[id]++;
    st->character.identified |= (1ull << id); /* you bought it — you know it */
    set_statusf(st, "bought %s", k->true_name);
    notify(st, &sequence_success);
    save_io_write_character(&st->character);
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

/* REMEMBER outbox writer (slice 49.F6). Auto-fires on quest_resolve in v1;
 * a future polish slice can split it out as a separate explicit REMEMBER
 * verb. Format per spec 49 §I.4.2:
 *   OUTBOX_SCHEMA 1
 *   REMEMBER <LINE_ID> <unix_ts> <campaign> <turn> <subject> | <theme_hex> | <sev>
 *
 * LINE_ID is a 16-hex-char idempotency key derived from (ts, campaign,
 * turn, subject) via FNV-64-flavored hash — not SHA-256 yet, but the
 * shape matches and the bridge can adjust when sha is wired.
 *
 * On the desktop side (slice 49.D3 — `sanctum bridge pull-outbox`), the
 * bridge reads this file on dock, publishes each REMEMBER line as a PO
 * `add-entry` command, then truncates. Until that lands, lines accumulate
 * safely on the SD (append-only, idempotent). */
static void sync_outbox_append(
    const char* real_self, const char* campaign, uint32_t turn,
    const char* subject, uint16_t theme_mask, uint8_t severity) {
    DateTime now_dt;
    furi_hal_rtc_get_datetime(&now_dt);
    uint64_t now_unix = datetime_datetime_to_timestamp(&now_dt);

    /* Derive a 64-bit idempotency key — two 32-bit FNV walks over the
     * canonical (ts | campaign | turn | subject) tuple. Same inputs →
     * byte-equal key, so re-running pull-outbox skips already-ingested
     * lines without re-publishing. */
    uint32_t k1 = 0x811C9DC5u, k2 = 0x9E3779B1u;
    char tsbuf[24];
    snprintf(tsbuf, sizeof(tsbuf), "%llu", (unsigned long long)now_unix);
    const char* parts[] = {tsbuf, "|", campaign ? campaign : "-",
                           "|", "", "|", subject ? subject : "-"};
    char turn_str[16];
    snprintf(turn_str, sizeof(turn_str), "%lu", (unsigned long)turn);
    parts[4] = turn_str;
    for(size_t i = 0; i < sizeof(parts) / sizeof(parts[0]); i++) {
        for(const char* p = parts[i]; *p; p++) {
            k1 = (k1 ^ (uint8_t)*p) * 16777619u;
            k2 = (k2 ^ (uint8_t)*p) * 0x85EBCA77u;
        }
    }
    char line_id[17];
    snprintf(line_id, sizeof(line_id), "%08lx%08lx",
             (unsigned long)k1, (unsigned long)k2);

    /* Outbox file: ensure base dir, open in append, write header on first
     * write, then write the REMEMBER line. */
    Storage* storage = furi_record_open(RECORD_STORAGE);
    storage_common_mkdir(storage, "/ext/apps_data/sanctum_rpg");
    const char* path = "/ext/apps_data/sanctum_rpg/sync_outbox.txt";

    /* Peek at file size — if zero/missing, we need to emit the header. */
    FileInfo info;
    bool need_header =
        (storage_common_stat(storage, path, &info) != FSE_OK) || info.size == 0;

    File* file = storage_file_alloc(storage);
    if(storage_file_open(file, path, FSAM_WRITE, FSOM_OPEN_APPEND)) {
        if(need_header) {
            const char* hdr = "OUTBOX_SCHEMA 1\n";
            storage_file_write(file, hdr, strlen(hdr));
        }
        char buf[160];
        int n = snprintf(
            buf, sizeof(buf),
            "REMEMBER %s %llu %s %lu %s | 0x%04x | %u\n",
            line_id,
            (unsigned long long)now_unix,
            campaign ? campaign : "-",
            (unsigned long)turn,
            subject ? subject : "-",
            (unsigned)theme_mask, (unsigned)severity);
        if(n > 0) storage_file_write(file, buf, (size_t)n);
        storage_file_close(file);
    }
    storage_file_free(file);
    furi_record_close(RECORD_STORAGE);
    (void)real_self; /* real_self_id is implicit in the file path tier */
}

/* Resolve the pending quest. Records the chosen branch's deed event
 * (HEART or WILL +2 per spec 49 §L.6), drops a codex/lore status line,
 * marks the entry resolved (session bitmap), AUTO-WRITES the REMEMBER
 * outbox line (slice 49.F6 — closes the loop back to PO), clears
 * pending_quest_*. */
static void quest_resolve(AppState* st) {
    if(st->pending_quest_entry < 0 || st->pending_quest_template < 0) return;
    const PoEntry* e = &MOCK_PO_ENTRIES[st->pending_quest_entry];
    const QuestTemplate* t = &QUEST_TEMPLATES[st->pending_quest_template];
    DeedEvent ev = (st->quest_choice == 0) ? t->branch_a_deed : t->branch_b_deed;
    deeds_record(&st->deeds, "themrburn", st->character.campaign_id,
                 st->character.turn, ev);

    /* Slice 49.F6 — REMEMBER write-back. The lemma is the subject; the
     * theme bitmask + severity carry the entry's metadata. Auto-fired
     * on resolve in v1 (a future polish slice splits this out as an
     * explicit REMEMBER verb the player presses optionally). */
    sync_outbox_append(
        "themrburn", st->character.campaign_id, st->character.turn,
        e->lemma, e->theme_mask, e->severity);

    char lore[96];
    narrative_substitute(
        lore, sizeof(lore),
        (st->quest_choice == 0) ? t->resolution_a : t->resolution_b, e);
    set_status(st, lore);
    notify(st, &sequence_success);
    st->resolved_mask |= (1u << st->pending_quest_entry);
    st->pending_quest_entry = -1;
    st->pending_quest_template = -1;
    st->screen = ScreenWorld;
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

/* Forward decls — the character sheet (slice 5 → 48.F6) wants effective
 * ATK/DEF + deeds-aware axis reads, which live with the combat block farther
 * down. Pure read-only queries so the call from a draw function is safe.
 *
 * Slice 48.F5: player_atk/def now take a DeedsState* alongside the character
 * so the combat math uses the EFFECTIVE axis (base + lifetime delta). */
static int player_atk(const CharacterState* c, const DeedsState* d);
static int player_def(const CharacterState* c, const DeedsState* d);

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

/* ─── render dispatch ─────────────────────────────────────────────── */

/* ─── render: the corruption arc (spec 58 §58.17) ─────────────────── */

static uint8_t character_base_axis(const CharacterState* c, uint8_t axis_id);

typedef enum { SITE_ACT_SEAL = 0, SITE_ACT_DISTURB, SITE_ACT_RITE, SITE_ACT_LEAVE } SiteAct;
static const char* const SITE_ACT_LABEL[] = {"set a seal", "disturb it", "the rite", "leave"};

static void arc_region_here(const AppState* st, int* rx, int* ry) {
    *rx = region_of(st->character.chunk_x);
    *ry = region_of(st->character.chunk_y);
}

/* The six effective axes: base + deed growth. */
static void effective_axes(const AppState* st, uint8_t* axes) {
    for(uint8_t a = 0; a < DEED_AXIS_COUNT; a++)
        axes[a] = deeds_effective_axis(&st->deeds, character_base_axis(&st->character, a), a);
}

/* May the dead be called out here? While the region is restless and its
 * pool holds dead, never in the home chunk (spec 58 §58.6). */
static bool can_disturb(const AppState* st) {
    int rx, ry;
    arc_region_here(st, &rx, &ry);
    if(st->character.chunk_x == 0 && st->character.chunk_y == 0) return false;
    return dead_restless(st->campaign_seed, rx, ry, &st->region_book, &st->rituals) &&
           dead_dormant(st->campaign_seed, rx, ry, &st->region_book, &st->risen) > 0;
}

/* What the bumped place offers. A site: seal while unsealed, disturb while
 * unsealed and restless, the rite once the region is cleansed and this site
 * sealed. A plain grave: disturb. Always leave. */
static int site_actions(const AppState* st, uint8_t* acts) {
    int rx, ry, n = 0;
    arc_region_here(st, &rx, &ry);
    bool sealed = st->site_k >= 0 && arc_site_sealed(&st->region_book, rx, ry, st->site_k);
    if(st->site_k >= 0 && !sealed) acts[n++] = SITE_ACT_SEAL;
    if(!sealed && can_disturb(st)) acts[n++] = SITE_ACT_DISTURB;
    if(sealed && arc_region_cleansed(st->campaign_seed, rx, ry, &st->region_book) &&
       !region_ritual_done(&st->rituals, rx, ry))
        acts[n++] = SITE_ACT_RITE;
    acts[n++] = SITE_ACT_LEAVE;
    return n;
}

/* The ways of the rite open to this player, in way order. */
static int rite_ways(const AppState* st, uint8_t* ways) {
    int rx, ry, n = 0;
    arc_region_here(st, &rx, &ry);
    uint8_t axes[DEED_AXIS_COUNT];
    effective_axes(st, axes);
    uint8_t open = arc_ways_open(st->campaign_seed, rx, ry, axes);
    for(int w = 0; w < WAY_COUNT; w++)
        if(open & WAY_BIT(w)) ways[n++] = (uint8_t)w;
    return n;
}

static EffortBody rite_body(const AppState* st, RitualWay way) {
    uint8_t axes[DEED_AXIS_COUNT];
    effective_axes(st, axes);
    EffortBody b = {st->character.torch_fuel, st->character.hp, ritual_way_axis(way, axes)};
    return b;
}

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

static void title_draw(Canvas* canvas, void* ctx) {
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
    /* Slice 48.F2/F3 — You-only pivot. No class picker; New Game goes
     * directly to ScreenStatBuy (the profile-review screen) with the
     * character pre-set to CLASS_YOU + baseline 10×6 axes. Cancellation
     * (Back from the review) then leaves no disk artifact behind, exactly
     * as the slice-1c contract guaranteed. */
    memset(&st->character, 0, sizeof(st->character));
    character_init_defaults(&st->character, ""); /* CLASS_YOU baseline 10×6 */
    st->pending_seed = furi_hal_random_get();
    st->pending_class_id = CLASS_YOU;
    st->stat_buy_cursor = 0;
    /* Pre-stamp display_name so the profile-review header shows your name
     * even before finalize. Real-self string is the same fallback that
     * finalize_new_character will write to meta. */
    strncpy(st->display_name, "themrburn", sizeof(st->display_name) - 1);
    st->display_name[sizeof(st->display_name) - 1] = '\0';
    st->screen = ScreenStatBuy;
    st->status_line = NULL;
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
    st->codex_bestiary = 0;
    char id[SAVE_IO_CAMPAIGN_ID_MAX + 1];
    if(save_io_most_recent_campaign(id, sizeof(id)) == SaveIoOk) {
        CharacterState c;
        if(save_io_load_character(id, &c) == SaveIoOk) {
            st->codex_identified = c.identified;
            st->codex_bestiary = c.bestiary;
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

    /* An edge into a region still closed by corruption refuses the crossing
     * (spec 58). The haze on that edge already shows it. */
    if(REGION_GATES_LIVE && region_edge_closed(st->campaign_seed, &st->rituals, cx, cy, dir)) {
        set_status(st, arc_region_found(st, region_of(cx), region_of(cy)) ? ARC_LINE_REFUSED : "blocked.");
        return;
    }
    int from_rx = region_of(cx), from_ry = region_of(cy);

    switch(dir) {
    case MoveNorth: cy -= 1; new_px = perp;              new_py = WORLD_ROWS - 2; break;
    case MoveSouth: cy += 1; new_px = perp;              new_py = 1;              break;
    case MoveWest:  cx -= 1; new_px = WORLD_COLS - 2;    new_py = perp;           break;
    case MoveEast:  cx += 1; new_px = 1;                 new_py = perp;           break;
    default: return;
    }

    st->character.chunk_x = (int16_t)cx;
    st->character.chunk_y = (int16_t)cy;
    st->quirk.active = false;   /* an armed quirk belongs to the chunk you left */
    st->rise_pending = false;   /* so does an armed rising */
    foul_clear(&st->foul);      /* and the foul patches (RAM, per chunk) */
    if(dead_calm_outside(&st->risen, region_of(cx), region_of(cy))) arc_save(st);   /* left their region: they calm */
    world_generate_chunk(st->campaign_seed, cx, cy, &st->world);
    arc_mark_edges(st);

    /* Load + overlay persisted deltas for the entered chunk. */
    deltas_load(st->character.campaign_id, cx, cy, &st->current_deltas);
    deltas_apply_to_world(&st->current_deltas, &st->world);

    /* If the entry tile is blocked (a rock landed on it, or a delta blocked
     * the tile), scan the entry edge outward from `perp` for the nearest
     * walkable tile — a single blocker on the entry tile felt like teleporting
     * through a wall (playtest 2026-05-29). Snap to spawn only if the whole
     * entry edge is blocked. */
    if(!world_walkable(&st->world, new_px, new_py)) {
        bool found = false;
        if(dir == MoveNorth || dir == MoveSouth) {
            for(int d = 1; d < WORLD_COLS && !found; d++) {
                int nx_l = perp - d;
                int nx_r = perp + d;
                if(nx_l >= 0 && world_walkable(&st->world, nx_l, new_py)) {
                    new_px = nx_l;
                    found = true;
                } else if(nx_r < WORLD_COLS && world_walkable(&st->world, nx_r, new_py)) {
                    new_px = nx_r;
                    found = true;
                }
            }
        } else {
            for(int d = 1; d < WORLD_ROWS && !found; d++) {
                int ny_u = perp - d;
                int ny_d = perp + d;
                if(ny_u >= 0 && world_walkable(&st->world, new_px, ny_u)) {
                    new_py = ny_u;
                    found = true;
                } else if(ny_d < WORLD_ROWS && world_walkable(&st->world, new_px, ny_d)) {
                    new_py = ny_d;
                    found = true;
                }
            }
        }
        if(!found) {
            new_px = st->world.spawn_x;
            new_py = st->world.spawn_y;
        }
    }
    st->character.player_x = (int16_t)new_px;
    st->character.player_y = (int16_t)new_py;
    /* Atmosphere — refresh weather before populate so visibility cap applies. */
    refresh_weather(st);
    populate_creatures(st); /* after player placement — never spawn on the player */
    reset_visibility(st);
    /* Weather chunk-enter hint wins over the place name; the rain begins
     * is the more interesting line. CLEAR weather falls through to the
     * procgen name ("Vethal Hollow") — coords remain reachable via the
     * examine cursor on any empty floor tile. */
    {
        const char* hint = weather_enter_hint(&st->current_weather);
        if(hint) {
            set_status(st, hint);
        } else {
            char place[NAME_MAX_LEN];
            name_for_chunk(
                st->campaign_seed, cx, cy, (uint8_t)st->world.style,
                place, sizeof(place));
            set_statusf(st, "%s", place);
        }
    }
    /* Entering a region still held by its corruption: one observed line,
     * and its rot counts as found (spec 58 §58.8). A cleansed one is quiet. */
    {
        int rx = region_of(cx), ry = region_of(cy);
        if((rx != from_rx || ry != from_ry) && region_depth(st->campaign_seed, rx, ry) > 0 &&
           !region_ritual_done(&st->rituals, rx, ry)) {
            set_status(st, ARC_LINE_ENTER);
            RegionRecord* r = region_book_touch(&st->region_book, rx, ry);
            if(r && !(r->flags & RR_FOUND)) {
                r->flags |= RR_FOUND;
                arc_save(st);
            }
        }
    }

    /* Slice 49.F4 — quest surfacing on chunk arrival. If this chunk is
     * an anchor for an unresolved entry, set pending_quest and open the
     * quest screen. Deterministic per (campaign_seed × entry_id) so the
     * SAME chunk always anchors the SAME quest within a campaign. */
    if(st->pending_quest_entry < 0) {
        /* Slice 50.F4: Pool-biased narrative pick on chunk transition. */
        Pool npool;
        uint8_t nbiome = biome_pool(st->world.biome);
        pool_at(st->campaign_seed, nbiome, cx, cy, &npool);
        uint8_t qe, qt;
        if(narrative_pick_for_chunk_pooled(st->campaign_seed, cx, cy,
                                           st->resolved_mask, &npool,
                                           &qe, &qt)) {
            st->pending_quest_entry = (int8_t)qe;
            st->pending_quest_template = (int8_t)qt;
            st->quest_choice = 0;
            st->screen = ScreenQuest;
        }
    }
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

/* Advance the world one turn: burn torch fuel, fire the light alarms, tick
 * creatures. The caller has already committed whatever action paid the turn
 * (a player move, or one tick of a scan). */
static void player_fall(AppState* st);

static void advance_turn(AppState* st) {
    uint16_t old_fuel = st->character.torch_fuel;
    st->character.turn++;
    /* The dead's area kinds, felt once a turn (spec 50 Q1 §Q.3): the
     * withered burn your light, the spectral chill, rot spoils what you carry. */
    AreaFelt felt;
    afflict_area(st->creatures, st->creature_count, st->character.player_x,
                 st->character.player_y, &felt);
    st->character.chill = felt.chill;
    if(felt.rot) {
        uint8_t spoiled = afflict_rot(st->campaign_seed, st->character.chunk_x,
                                      st->character.chunk_y, st->character.turn, &st->character);
        const KindDef* k = spoiled == 0xFFu ? NULL : kind_by_id(spoiled);
        if(k) set_statusf(st, AF_LINE_SPOIL, k->true_name);
    }
    /* Atmosphere: rain/storm bleed extra fuel per turn. Indoor weather
     * is already attenuated upstream, so this naturally applies less. */
    uint16_t burn = FUEL_PER_TURN +
                    (uint16_t)st->current_weather.fuel_burn_extra +
                    (felt.wither ? WITHER_FUEL_EXTRA : 0);
    uint16_t fuel = (old_fuel >= burn) ? (uint16_t)(old_fuel - burn) : 0;
    st->character.torch_fuel = fuel;
    /* MP comes back slowly: one point every MP_REGEN_TURNS (spec 46 §5.1). */
    st->character.mp = cast_mp_regen(st->character.mp, st->character.max_mp, st->character.turn);

    /* Creatures act on the same clock (cohesion keystone). Deterministic per
     * (chunk_seed, turn, slot) — never perturbs the world golden-master. Light
     * radius = the awareness zone (spec 45 §5.5). A hostile reaching you opens
     * the combat encounter (maybe_start_combat, after the turn) — that replaces
     * the old contact fuel-"flicker". */
    creatures_tick(
        st->creatures, st->creature_count, &st->world, st->character.player_x,
        st->character.player_y, fov_radius_for_fuel(fuel),
        rng_chunk_seed(st->campaign_seed, st->character.chunk_x, st->character.chunk_y),
        st->character.turn, &st->current_weather);

    /* A bleed, and a foul patch underfoot, cost health (spec 50 Q1 §Q.4). */
    afflict_bleed_tick(&st->character);   /* -1 HP while a bleed runs */
    int hurt = foul_step(&st->foul, st->character.player_x, st->character.player_y, st->character.turn);
    if(hurt) st->character.hp = st->character.hp > hurt ? (uint16_t)(st->character.hp - hurt) : 0;
    if(st->character.hp == 0 && st->screen != ScreenCombat) {
        player_fall(st);
        return;
    }

    /* Light alarms: torch out, or dimmed a band. */
    uint16_t newf = st->character.torch_fuel;
    if(old_fuel > 0 && newf == 0) {
        notify(st, &sequence_error); /* torch out — the deepest panic */
    } else if(fov_radius_for_fuel(newf) < fov_radius_for_fuel(old_fuel)) {
        notify(st, &sequence_single_vibro); /* dimmed a band */
    }
}

/* ─── combat (v0.4.1, spec 46 §5.2) ───────────────────────────────────
 * Melee encounter: a modal screen vs one adjacent hostile. The clock PAUSES
 * during a fight (classic JRPG battle pause); ticking rounds into the global
 * vital clock is the spec-45 cohesion refinement, deferred. Player atk/def
 * derive from level until the 6-stat block lands (spec 45 §5; tunable). */
static int player_atk(const CharacterState* c, const DeedsState* d) {
    /* BODY contributes (slice 48.F1) + Tensura deeds-delta (48.F5). Thread C:
     * weapon bonus scales by expertise — base × min(100, expertise) / 100.
     * Egalitarian access (any item can be equipped) but bonuses earned
     * through use (D&D proficiency, sanctum Tensura). */
    uint8_t eff_body = deeds_effective_axis(d, c->body, DEED_AXIS_BODY);
    int atk = (int)eff_body / 3 + (int)c->level;
    if(c->equipped_weapon != SAVE_EQUIP_NONE) {
        const KindDef* w = kind_by_id(c->equipped_weapon);
        if(w) {
            uint8_t xp = (c->equipped_weapon < SAVE_INV_KINDS_MAX)
                             ? c->expertise[c->equipped_weapon] : 0;
            if(xp > 100) xp = 100;
            atk += ((int)w->atk_bonus * (int)xp) / 100;
        }
    }
    return atk;
}
static int player_def(const CharacterState* c, const DeedsState* d) {
    /* WILL contributes (slice 48.F1) + deeds-delta (48.F5). Thread C: armor
     * bonus scales by expertise on the equipped armor's kind. */
    uint8_t eff_will = deeds_effective_axis(d, c->will, DEED_AXIS_WILL);
    int def = (int)eff_will / 2 + 8 + (int)c->level;
    if(c->equipped_armor != SAVE_EQUIP_NONE) {
        const KindDef* a = kind_by_id(c->equipped_armor);
        if(a) {
            uint8_t xp = (c->equipped_armor < SAVE_INV_KINDS_MAX)
                             ? c->expertise[c->equipped_armor] : 0;
            if(xp > 100) xp = 100;
            def += ((int)a->def_bonus * (int)xp) / 100;
        }
    }
    return def;
}

/* No permadeath: you fall, then wake dimmer and elsewhere — a real consequence,
 * not a game-over. Placeholder until the DeathType table (spec 45 §6 / v0.4.3). */
static void player_fall(AppState* st) {
    st->fell = true;
    st->character.hp = (uint16_t)(st->character.max_hp / 2);
    if(st->character.hp < 1) st->character.hp = 1;
    st->character.torch_fuel = (uint16_t)(st->character.torch_fuel / 2);
    st->character.player_x = (int16_t)st->world.spawn_x;
    st->character.player_y = (int16_t)st->world.spawn_y;
    st->combat_foe = -1;
    st->combat_grace = 2; /* a breath to escape the spawn before re-engaging */
    /* Reset aggro on every creature in the chunk so a respawn near a still-
     * provoked foe isn't an instant death loop (2026-06-01 fix). Provoked
     * creatures calm; you get a real recovery window. They can re-provoke if
     * you crowd them again, per spec 45 §4.8. */
    for(int i = 0; i < st->creature_count; i++) {
        st->creatures[i].aggro = 0;
    }
    st->screen = ScreenWorld;
    recompute_visibility(st);
    set_status(st, "you fall, wake elsewhere"); /* concise — fits 128px */
    notify(st, &sequence_error);
    save_io_write_character(&st->character);
}

/* If a hostile is adjacent at the end of a turn, open the encounter (replaces
 * the old contact fuel-"flicker"). Returns whether combat started. */
static bool maybe_start_combat(AppState* st) {
    if(st->combat_grace > 0) {
        st->combat_grace--;
        /* Slice 48.F5: when the grace counter ticks to ZERO (you survived
         * the recovery window without re-engaging), record a fall-clean
         * WILL deed. Capped 2/session — you can't farm falls to grind WILL. */
        if(st->combat_grace == 0) {
            deeds_record(&st->deeds, "themrburn",
                         st->character.campaign_id, st->character.turn,
                         DEED_FALL_CLEAN);
        }
        return false; /* post-fall grace — hostiles can't re-engage yet */
    }
    int px = st->character.player_x, py = st->character.player_y;
    for(int i = 0; i < st->creature_count; i++) {
        const Creature* c = &st->creatures[i];
        if(!c->alive) continue;
        int dx = px - (int)c->x, dy = py - (int)c->y;
        int adx = dx < 0 ? -dx : dx, ady = dy < 0 ? -dy : dy;
        if((adx > ady ? adx : ady) > 1) continue;
        CreatureDef d;
        creature_compose(c->family_id, c->trait_id, &d);
        if(!creature_is_hostile(d.disposition, d.provoke, c->aggro)) continue;
        st->combat_foe = i;
        st->combat_foe_hp = d.hp > c->wounds ? (uint16_t)(d.hp - c->wounds) : 1;   /* wounds from range carry in */
        st->combat_cursor = 0;
        st->combat_round = 0;
        char nm[24];
        creature_name(&d, nm, sizeof(nm));
        set_statusf(st, "the %s blocks you!", nm);
        st->screen = ScreenCombat;
        return true;
    }
    return false;
}

/* STRIKE: you hit, then the foe hits back (player first — DQ-simple). */
/* The foe falls (shared by a strike, a throw and poison). */
static void combat_kill(AppState* st, Creature* foe, const char* nm) {
    foe->alive = 0;
    st->combat_foe_poison = 0;
    afflict_foe_died(foe->trait_id, foe->x, foe->y, st->character.turn, &st->foul);
    if(foe->family_id == FAMILY_DEAD) {
        /* One of the region's dead is destroyed: route 2's tally (spec 58
         * §58.6). The last one falls in silence. */
        dead_destroyed(st->campaign_seed, st->character.chunk_x, st->character.chunk_y,
                       foe->trait_id, &st->risen, &st->region_book);
        arc_save(st);
    } else {
        /* Persist the kill (slice 1b): defeated creatures stay defeated across
         * chunk re-entry — the finite-world rule. Keyed by spawn position. */
        deltas_record_kill(
            st->character.campaign_id, &st->current_deltas,
            foe->spawn_x, foe->spawn_y);
    }

    /* Roll a material drop (slice 3) — deterministic from
     * (chunk_seed × spawn) so it's reproducible across runs but unique per
     * foe. Biome-weighted via the existing `loot_roll`. */
    Rng drop_rng;
    rng_seed(
        &drop_rng,
        rng_chunk_seed(
            st->campaign_seed,
            st->character.chunk_x, st->character.chunk_y) ^
            ((uint32_t)foe->spawn_x * 73u) ^
            ((uint32_t)foe->spawn_y * 919u) ^ 0xD12057A1u);
    /* Slice 50.F3: Pool-biased combat drop. The Pool at the player's
     * CURRENT chunk shifts kind probabilities — a Heart-themed
     * region drops different kinds than a Craft-themed one. */
    Pool dpool;
    uint8_t dbiome = biome_pool(st->world.biome);
    pool_at(st->campaign_seed, dbiome,
            (int)st->character.chunk_x, (int)st->character.chunk_y, &dpool);
    uint8_t drop_id = loot_roll_pooled(&drop_rng, st->world.biome, &dpool);
    const KindDef* drop = kind_by_id(drop_id);
    if(drop && drop_id < SAVE_INV_KINDS_MAX &&
       st->character.inv_qty[drop_id] < 255) {
        st->character.inv_qty[drop_id]++;
        st->character.identified |= (1ull << drop_id);
    }

    st->combat_foe = -1;
    st->screen = ScreenWorld;
    if(drop) {
        set_statusf(st, "felled %s (+%s)", nm, drop->true_name);
    } else {
        set_statusf(st, "you fell the %s", nm);
    }
    notify(st, &sequence_success);
    save_io_write_character(&st->character);
}

/* The foe strikes back after your action: its attack, plus what its kind
 * adds (a flanking horde, a feeder; spec 50 Q1 §Q.3); a hit that lands may
 * open a bleed or feed it. Returns false if you fell. */
static bool combat_foe_turn(AppState* st, Creature* foe, const CreatureDef* d, int dmg) {
    int fdmg = (int)d->atk + afflict_foe_bonus(st->creatures, st->creature_count, st->combat_foe,
                                               st->character.player_x, st->character.player_y,
                                               st->character.hp, st->character.max_hp) -
               player_def(&st->character, &st->deeds) / 8;
    if(fdmg < 1) fdmg = 1;
    if((int)st->character.hp <= fdmg) {
        player_fall(st);
        return false;
    }
    st->character.hp = (uint16_t)(st->character.hp - fdmg);
    afflict_foe_hit(foe->trait_id, &st->character, &st->combat_foe_hp, d->hp);
    if(dmg > 0) set_statusf(st, "hit %d  took %d", dmg, fdmg);
    else set_statusf(st, "took %d", fdmg);
    notify(st, &sequence_single_vibro);

    if(st->character.equipped_armor != SAVE_EQUIP_NONE &&
       st->character.equipped_armor < SAVE_INV_KINDS_MAX) {
        uint8_t* xp = &st->character.expertise[st->character.equipped_armor];
        if(*xp < 100) (*xp)++;
    }
    return true;
}

/* Poison on the foe (a tincture, a coated edge): it takes POISON_DAMAGE at
 * the start of each round while it runs. Returns true if it fell. */
static bool combat_poison(AppState* st, Creature* foe, const char* nm) {
    if(st->combat_foe_poison == 0) return false;
    st->combat_foe_poison--;
    if(st->combat_foe_hp <= POISON_DAMAGE) {
        combat_kill(st, foe, nm);
        return true;
    }
    st->combat_foe_hp = (uint16_t)(st->combat_foe_hp - POISON_DAMAGE);
    return false;
}

static void combat_strike(AppState* st) {
    if(st->combat_foe < 0 || st->combat_foe >= st->creature_count) return;
    Creature* foe = &st->creatures[st->combat_foe];
    CreatureDef d;
    creature_compose(foe->family_id, foe->trait_id, &d);
    char nm[24];
    creature_name(&d, nm, sizeof(nm));
    st->combat_round++;

    if(combat_poison(st, foe, nm)) return;

    int dmg = player_atk(&st->character, &st->deeds) - (int)d.def / 8;
    if(dmg < 1) dmg = 1;
    /* BODY deed on every landed STRIKE (slice 48.F5; capped 5/session). The
     * deed lands regardless of whether the foe falls — the act of striking
     * is the growth, not the kill. */
    deeds_record(&st->deeds, "themrburn",
                 st->character.campaign_id, st->character.turn, DEED_STRIKE);

    /* Thread C — equipped weapon expertise +1 per STRIKE (Tensura;
     * capped 100). The act of using the weapon makes you better with IT
     * specifically, not "all weapons" — D&D proficiency at item level. */
    if(st->character.equipped_weapon != SAVE_EQUIP_NONE &&
       st->character.equipped_weapon < SAVE_INV_KINDS_MAX) {
        uint8_t* xp = &st->character.expertise[st->character.equipped_weapon];
        if(*xp < 100) (*xp)++;
    }
    if((int)st->combat_foe_hp <= dmg) {
        combat_kill(st, foe, nm);
        return;
    }
    st->combat_foe_hp = (uint16_t)(st->combat_foe_hp - dmg);
    if(st->coating) {                  /* a coated edge poisons the foe it cuts */
        st->coating--;
        st->combat_foe_poison = (uint8_t)(st->combat_foe_poison + COATING_POISON);
    }

    if(!combat_foe_turn(st, foe, &d, dmg)) return;
    save_io_write_character(&st->character);
}

/* FLEE: ~60% escape; failure costs a foe hit. Per-round seed so retries vary. */
/* THROW (the dark tree's flasks, spec 50 Q1 §Q.10.4): a rot tincture
 * poisons the foe for POISON_TURNS rounds; a blight hits at once and fouls
 * the ground under it. Then the foe's turn. */
static void combat_throw(AppState* st) {
    if(st->combat_foe < 0 || st->combat_foe >= st->creature_count) return;
    uint8_t k = afflict_throwable(&st->character);
    if(k == 0xFFu) return;
    Creature* foe = &st->creatures[st->combat_foe];
    CreatureDef d;
    creature_compose(foe->family_id, foe->trait_id, &d);
    char nm[24];
    creature_name(&d, nm, sizeof(nm));
    st->combat_round++;
    if(combat_poison(st, foe, nm)) return;
    st->character.inv_qty[k]--;
    int dmg = 0;
    if(k == AF_KIND_TINCTURE) {
        st->combat_foe_poison = (uint8_t)(st->combat_foe_poison + POISON_TURNS);
    } else {
        dmg = BLIGHT_DAMAGE;
        foul_add(&st->foul, foe->x, foe->y, st->character.turn);
        if((int)st->combat_foe_hp <= dmg) {
            combat_kill(st, foe, nm);
            return;
        }
        st->combat_foe_hp = (uint16_t)(st->combat_foe_hp - dmg);
    }
    if(!combat_foe_turn(st, foe, &d, dmg)) return;
    save_io_write_character(&st->character);
}

static void combat_flee(AppState* st) {
    if(st->combat_foe < 0 || st->combat_foe >= st->creature_count) return;
    Creature* foe = &st->creatures[st->combat_foe];
    CreatureDef d;
    creature_compose(foe->family_id, foe->trait_id, &d);
    st->combat_round++;
    Rng r;
    rng_seed(
        &r,
        rng_chunk_seed(st->campaign_seed, st->character.chunk_x, st->character.chunk_y) ^
            (st->character.turn * 2654435761u) ^ ((uint32_t)st->combat_round * 40503u) ^ 0x5EEDu);
    if(rng_range(&r, 0, 100) < 60) {
        st->combat_foe = -1;
        st->screen = ScreenWorld;
        set_status(st, "you slip away");
        save_io_write_character(&st->character);
    } else {
        int fdmg = (int)d.atk - player_def(&st->character, &st->deeds) / 8;
        if(fdmg < 1) fdmg = 1;
        if((int)st->character.hp <= fdmg) {
            player_fall(st);
            return;
        }
        st->character.hp = (uint16_t)(st->character.hp - fdmg);
        st->character.torch_fuel =
            (st->character.torch_fuel > 2) ? (uint16_t)(st->character.torch_fuel - 2) : 0;
        set_statusf(st, "can't escape!  took %d", fdmg);
        notify(st, &sequence_single_vibro);
    }
}

/* Deliberate skill-gated scan of creature index `ci` (under the examine
 * cursor). Costs turns — the world ticks each, so the target may flee into
 * the dark mid-scan (ephemerality). On completion: advances the family
 * bestiary grade + grows OBSERVE (big on a new family, diminishing after) +
 * a tier-gated reveal. Spec 45 §4.7. */
static void scan_creature(AppState* st, int ci) {
    CreatureDef d;
    creature_compose(st->creatures[ci].family_id, st->creatures[ci].trait_id, &d);
    int tier = creature_scan_tier(st->character.observe, d.scan_diff);
    int cost = creature_scan_cost(d.scan_diff);

    bool completed = true;
    for(int t = 0; t < cost; t++) {
        advance_turn(st);
        if(!st->creatures[ci].alive) {
            completed = false;
            break;
        }
        recompute_visibility(st);
        if(!st->lit[st->creatures[ci].y][st->creatures[ci].x]) {
            completed = false; /* fled out of the light before you finished */
            break;
        }
    }
    recompute_visibility(st);

    /* keep the cursor on the target if it's still in view */
    if(st->creatures[ci].alive) {
        st->examine_x = (int8_t)st->creatures[ci].x;
        st->examine_y = (int8_t)st->creatures[ci].y;
    }

    if(completed) {
        /* advance the family bestiary; grow OBSERVE only on a real gain */
        uint8_t fam = d.family_id;
        int grade = creature_bestiary_grade(st->character.bestiary, fam);
        if(tier > grade) {
            int gain = (grade == 0) ? 8 : (grade == 1 ? 3 : 1);
            st->character.bestiary =
                creature_bestiary_set(st->character.bestiary, fam, (uint8_t)tier);
            int obs = (int)st->character.observe + gain;
            st->character.observe = (uint8_t)(obs > 100 ? 100 : obs);
            /* MIND deed on grade-up (slice 48.F5) — the codex got smarter. */
            deeds_record(&st->deeds, "themrburn",
                         st->character.campaign_id, st->character.turn,
                         DEED_CODEX_UP);
        }
        /* SIGHT deed on completed scan, tiered (slice 48.F5). */
        DeedEvent scan_deed = (tier >= 3) ? DEED_SCAN_TIER3
                              : (tier == 2) ? DEED_SCAN_TIER2
                                            : DEED_SCAN_TIER1;
        deeds_record(&st->deeds, "themrburn",
                     st->character.campaign_id, st->character.turn, scan_deed);
        char nm[24];
        creature_name(&d, nm, sizeof(nm));
        int taught = tier >= 3 ? cast_taught_by(d.element) : -1;
        if(taught >= 0 && !(st->character.casts_known & CAST_BIT(taught))) {
            /* A deep read teaches the cast of its element (spec 46 §5.1):
             * the reticle grows a trigger. */
            st->character.casts_known |= CAST_BIT(taught);
            set_statusf(st, CAST_LINE_LEARNED, CAST_TABLE[taught].name);
        } else if(tier >= 3) {
            set_statusf(
                st, "%s %s %s %s", nm, creature_disposition_name(d.disposition),
                creature_element_name(d.element), creature_aptitude_name(d.aptitude));
        } else if(tier == 2) {
            set_statusf(
                st, "%s %s %s", nm, creature_disposition_name(d.disposition),
                creature_element_name(d.element));
        } else {
            set_statusf(st, "%s %s", nm, creature_disposition_name(d.disposition));
        }
        notify(st, &sequence_success);
    } else {
        set_status(st, "it slipped into the dark");
    }
    save_io_write_character(&st->character); /* turn/fuel advanced — persist */
    maybe_start_combat(st); /* a hostile may have closed during the scan */
}

/* Fire the strongest known cast MP can pay for at the creature under the
 * reticle (spec 46 §5.1). Its wounds carry into melee; struck, it turns on
 * you; a kill at range drops as a melee kill does. A turn passes. */
static void cast_fire(AppState* st, int ci) {
    Creature* foe = &st->creatures[ci];
    int c = cast_pick(st->character.casts_known, st->character.mp);
    if(c < 0) {
        set_status(st, CAST_LINE_EMPTY);
        return;
    }
    st->character.mp = (uint16_t)(st->character.mp - CAST_TABLE[c].mp_cost);
    CreatureDef d;
    creature_compose(foe->family_id, foe->trait_id, &d);
    uint8_t mind = deeds_effective_axis(&st->deeds, st->character.mind, DEED_AXIS_MIND);
    int dmg = cast_damage(c, mind, d.def);
    char nm[24];
    creature_name(&d, nm, sizeof(nm));
    if((int)foe->wounds + dmg >= (int)d.hp) {
        st->combat_foe = ci;
        combat_kill(st, foe, nm);           /* drops, tallies, says it fell */
    } else {
        foe->wounds = (uint8_t)(foe->wounds + dmg);
        foe->aggro = CAST_PROVOKE;
        set_status(st, CAST_LINE_LANDS);
        notify(st, &sequence_single_vibro);
    }
    advance_turn(st);
    recompute_visibility(st);
    save_io_write_character(&st->character);
    if(st->screen == ScreenWorld && maybe_start_combat(st)) st->examining = false;
}

/* Map a deed axis id (DEED_AXIS_*) to the character's base score for it. */
static uint8_t character_base_axis(const CharacterState* c, uint8_t axis_id) {
    switch(axis_id) {
    case DEED_AXIS_BODY:  return c->body;
    case DEED_AXIS_CRAFT: return c->craft;
    case DEED_AXIS_SIGHT: return c->sight;
    case DEED_AXIS_MIND:  return c->mind;
    case DEED_AXIS_HEART: return c->heart;
    case DEED_AXIS_WILL:  return c->will;
    default:              return 0;
    }
}

/* Effective-axis a secret passage requires before it opens (spec 50 §R).
 * Playtest-tunable: base axes start ~10-14, so this asks for real growth in
 * the gating axis without being unreachable. */
#define SECRET_AXIS_THRESHOLD 16u

/* A turn ended inside the chunk: a pending quirk lands, or the trigger
 * tiles next to the player roll (spec 50 Q1 §Q.1). Rubble is a delta,
 * like a pickup, so it stays after a reload. */
static void quirk_tick(AppState* st) {
    QuirkOutcome o;
    quirk_step(st->campaign_seed, st->character.chunk_x, st->character.chunk_y,
               st->character.turn, &st->world,
               st->character.player_x, st->character.player_y, &st->quirk, &o);
    if(o.placed) {
        /* quirk.c can't see creatures: never bury one. The rubble just doesn't fall. */
        for(int i = 0; i < st->creature_count && o.placed; i++) {
            const Creature* c = &st->creatures[i];
            if(c->alive && c->x == (uint8_t)o.rx && c->y == (uint8_t)o.ry) {
                st->world.tiles[o.ry][o.rx] = TILE_FLOOR;
                o.placed = false;
            }
        }
    }
    if(o.placed)
        deltas_record(st->character.campaign_id, &st->current_deltas, o.rx, o.ry, CAVE_IN_RUBBLE);
    if(o.told) notify(st, &sequence_single_vibro);
    if(o.damage) {
        st->character.hp = (st->character.hp > o.damage) ? (uint16_t)(st->character.hp - o.damage) : 0;
        notify(st, &sequence_error);
    }
    if(o.message) set_status(st, o.message);
    if(o.damage && st->character.hp == 0) player_fall(st);
}

/* Once per night, above ground, near a real full or new moon: name it
 * (spec 50 Q1 §Q.11.2, 58 §58.9). The clock is an input: read it here,
 * the sky is derived. Called before quirk_tick, so a cave-in's tell, which
 * must be seen, wins the status line. */
static void sky_tick(AppState* st) {
    if(st->world.biome != BIOME_OUTDOOR) return;
    DateTime now;
    furi_hal_rtc_get_datetime(&now);
    uint64_t t = datetime_datetime_to_timestamp(&now);
    Sky sky;
    sky_at(t, &sky);
    const char* line = sky_line(&sky);
    uint32_t night = sky_night_id(t) + 1u;   /* +1: 0 means never */
    if(!line || st->moon_said_night == night) return;
    st->moon_said_night = night;
    set_status(st, line);
}

/* ─── the corruption arc's verbs (spec 58 §58.17) ─────────────────── */

static void ritual_take_hold(AppState* st) {
    int rx, ry;
    arc_region_here(st, &rx, &ry);
    region_mark_ritual(&st->rituals, rx, ry);
    arc_way_spend((RitualWay)st->rite_way, &st->character);
    arc_save(st);
    save_io_write_character(&st->character);
    arc_mark_edges(st);
    notify(st, &sequence_success);
    set_status(st, ARC_LINE_RITE);
    st->screen = ScreenWorld;
}

/* A failed rite: what it spent stays spent; what was found is kept (§58.7.4).
 * If you fell during it, the fall already said so and moved you. */
static void rite_failed(AppState* st) {
    save_io_write_character(&st->character);
    if(st->fell) return;
    set_status(st, ARC_LINE_FAILED);
    st->screen = ScreenWorld;
}

/* Pay one rite turn: the effort from the body, and the world's turn. A
 * bleed or a foul patch can make you fall in that turn: the rite stops. */
static EffortState rite_turn(AppState* st) {
    EffortBody b = rite_body(st, (RitualWay)st->rite_way);
    EffortState e = effort_turn(&st->rite_run, &b);
    st->character.torch_fuel = b.fuel;
    st->character.hp = b.hp;
    st->fell = false;
    advance_turn(st);
    return st->fell ? EFFORT_SPENT : e;
}

/* Walking into a site opens it, and finds its region's rot (§58.3.1). */
static void site_open(AppState* st, int k, int x, int y) {
    int rx, ry;
    arc_region_here(st, &rx, &ry);
    st->site_k = (int8_t)k;
    st->site_x = (int8_t)x;
    st->site_y = (int8_t)y;
    st->site_kind = st->world.site_kind;
    st->site_cursor = 0;
    st->screen = ScreenSite;
    RegionRecord* r = region_book_touch(&st->region_book, rx, ry);
    if(r && !(r->flags & RR_FOUND)) {
        r->flags |= RR_FOUND;
        arc_save(st);
        arc_mark_edges(st);
    }
}

static void disturb(AppState* st);

static void site_act(AppState* st) {
    uint8_t acts[4];
    int n = site_actions(st, acts);
    if(st->site_cursor >= n) st->site_cursor = (int8_t)(n - 1);
    int rx, ry;
    arc_region_here(st, &rx, &ry);
    switch(acts[st->site_cursor]) {
    case SITE_ACT_SEAL: {
        ArcSealResult r = arc_seal(rx, ry, st->site_k, st->site_kind, &st->character, &st->region_book);
        if(r == ARC_SEALED) {
            arc_save(st);
            save_io_write_character(&st->character);
            notify(st, &sequence_success);
        }
        set_status(st, arc_seal_line(r));
        st->screen = ScreenWorld;
        break;
    }
    case SITE_ACT_DISTURB:
        disturb(st);
        break;
    case SITE_ACT_RITE:
        st->rite_cursor = 0;
        st->screen = ScreenRite;
        break;
    default:
        st->screen = ScreenWorld;
        break;
    }
}

/* Begin the highlighted way (ScreenRite, OK). Spoken and made pass their
 * turns in one go; the vigil and the runes go turn by turn. */
static void rite_begin(AppState* st) {
    uint8_t ways[WAY_COUNT];
    int n = rite_ways(st, ways);
    if(n == 0) return;
    if(st->rite_cursor >= n) st->rite_cursor = 0;
    RitualWay w = (RitualWay)ways[st->rite_cursor];
    int rx, ry;
    arc_region_here(st, &rx, &ry);
    if(!arc_way_ready(st->campaign_seed, rx, ry, w, &st->character, &st->region_book)) {
        set_status(st, ARC_LINE_MISSING);
        st->screen = ScreenWorld;
        return;
    }
    RegionRite rite;
    region_rite(st->campaign_seed, rx, ry, &rite);
    EffortTask t = ritual_task(&rite, w);
    EffortBody b = rite_body(st, w);
    st->rite_way = (uint8_t)w;
    effort_begin(&st->rite_run, &t, &b);
    if(w == WAY_KEPT) {
        st->screen = ScreenVigil;
        return;
    }
    if(w == WAY_SEEN) {
        rune_puzzle(st->campaign_seed, rx, ry, &st->runes);
        for(int i = 0; i < RUNES_MAX; i++) st->rune_turn[i] = st->runes.start[i];
        st->rune_ntouched = 0;
        st->rune_sel = 0;
        st->status_line = NULL;
        st->screen = ScreenRunes;
        return;
    }
    EffortState e = EFFORT_GOING;
    while(e == EFFORT_GOING) e = rite_turn(st);
    recompute_visibility(st);
    if(e == EFFORT_DONE) ritual_take_hold(st);
    else rite_failed(st);
}

/* The moon now (the clock is an input, read here; spec 53 §3 amended). */
static uint8_t moon_now(bool* night) {
    DateTime now;
    furi_hal_rtc_get_datetime(&now);
    Sky sky;
    sky_at(datetime_datetime_to_timestamp(&now), &sky);
    *night = sky.night;
    return sky.moon_strength;
}

/* Raise the dead at (x, y) from the region's pool. An ordinary resting
 * place opens for good (a delta); a site stays as it is. */
static int rise_at(AppState* st, int x, int y) {
    int cx = st->character.chunk_x, cy = st->character.chunk_y;
    int up = dead_raise(st->campaign_seed, cx, cy, &st->world, st->character.player_x,
                        st->character.player_y, x, y, &st->region_book, &st->risen, st->creatures,
                        &st->creature_count, CREATURES_MAX);
    char opened = terrain_opened(st->world.tiles[y][x]);
    bool site = arc_site_at(st->campaign_seed, cx, cy, &st->world, x, y) >= 0;
    if(up > 0 && opened && !site) {
        st->world.tiles[y][x] = opened;
        deltas_record(st->character.campaign_id, &st->current_deltas, x, y, opened);
    }
    return up;
}

/* Disturbing a resting place calls its dead out at once, whatever the moon
 * or the realm; the moon widens it to the unsealed resting places nearby
 * (spec 58 §58.6). A turn passes. */
static void disturb(AppState* st) {
    bool night;
    uint8_t strength = moon_now(&night);
    int radius = dead_disturb_radius(strength);
    int x0 = st->site_x, y0 = st->site_y;
    char g = st->world.tiles[y0][x0];
    int up = rise_at(st, x0, y0);
    int rx, ry;
    arc_region_here(st, &rx, &ry);
    for(int y = y0 - radius; y <= y0 + radius && radius > 0; y++)
        for(int x = x0 - radius; x <= x0 + radius; x++) {
            if((x == x0 && y == y0) || x < 0 || y < 0 || x >= WORLD_COLS || y >= WORLD_ROWS) continue;
            if(!dead_resting_place(st->world.tiles[y][x])) continue;
            int k = arc_site_at(st->campaign_seed, st->character.chunk_x, st->character.chunk_y, &st->world, x, y);
            if(k >= 0 && arc_site_sealed(&st->region_book, rx, ry, k)) continue;
            up += rise_at(st, x, y);
        }
    advance_turn(st);
    recompute_visibility(st);
    arc_save(st);
    save_io_write_character(&st->character);
    set_status(st, g == 'n' || g == 'N' ? DEAD_LINE_TOMB : DEAD_LINE_GRAVE);
    st->screen = ScreenWorld;
    if(up > 0) notify(st, &sequence_single_vibro);
}

/* A turn ended above ground at night under a full or new moon: the
 * resting places within reach may stir (the tell now; the dead next turn,
 * spec 50 Q1 §Q.1.2). The reach grows with the moon. */
static void dead_tick(AppState* st) {
    int cx = st->character.chunk_x, cy = st->character.chunk_y;
    int rx = region_of(cx), ry = region_of(cy);
    if(st->rise_pending) {
        if(st->character.turn < st->rise_due) return;
        st->rise_pending = false;
        if(dead_restless(st->campaign_seed, rx, ry, &st->region_book, &st->rituals) &&
           rise_at(st, st->rise_x, st->rise_y) > 0) {
            arc_save(st);
            notify(st, &sequence_single_vibro);
        }
        return;
    }
    if(st->world.biome != BIOME_OUTDOOR || (cx == 0 && cy == 0)) return;
    if(!dead_restless(st->campaign_seed, rx, ry, &st->region_book, &st->rituals) ||
       dead_dormant(st->campaign_seed, rx, ry, &st->region_book, &st->risen) == 0)
        return;
    bool night;
    uint8_t strength = moon_now(&night);
    if(!night || strength == 0) return;
    int reach = 1 + dead_disturb_radius(strength);
    int px = st->character.player_x, py = st->character.player_y;
    for(int y = py - reach; y <= py + reach; y++)
        for(int x = px - reach; x <= px + reach; x++) {
            if(x < 0 || y < 0 || x >= WORLD_COLS || y >= WORLD_ROWS) continue;
            char g = st->world.tiles[y][x];
            if(!dead_resting_place(g)) continue;
            int k = arc_site_at(st->campaign_seed, cx, cy, &st->world, x, y);
            if(k >= 0 && arc_site_sealed(&st->region_book, rx, ry, k)) continue;
            if(!dead_chance(st->campaign_seed, cx, cy, x, y, st->character.turn, strength)) continue;
            st->rise_pending = true;
            st->rise_x = (int8_t)x;
            st->rise_y = (int8_t)y;
            st->rise_due = st->character.turn + 1;
            set_status(st, g == 'n' ? DEAD_LINE_TOMB : DEAD_LINE_GRAVE);
            return;
        }
}

/* The vigil: one turn kept (OK). Anything that comes for you breaks it,
 * and it starts again from the beginning (§58.7.5). */
static void vigil_wait(AppState* st) {
    EffortState e = rite_turn(st);
    recompute_visibility(st);
    if(e == EFFORT_SPENT) {
        rite_failed(st);
        return;
    }
    st->screen = ScreenWorld;
    if(maybe_start_combat(st)) {
        set_status(st, ARC_LINE_BROKEN);
        return;
    }
    if(e == EFFORT_DONE) {
        ritual_take_hold(st);
        return;
    }
    st->screen = ScreenVigil;
}

/* The runes: each try is a rite turn. Wrong costs the turn; the touches
 * reset; out of turns or strength, the rite fails. */
static void runes_try(AppState* st) {
    bool right = rune_answer(&st->runes, st->rune_turn, st->rune_touched);
    EffortState e = rite_turn(st);
    if(right && e != EFFORT_SPENT) {
        ritual_take_hold(st);
        return;
    }
    st->rune_ntouched = 0;
    if(e != EFFORT_GOING) {
        rite_failed(st);
        return;
    }
    set_status(st, ARC_LINE_FAILED);
}

static void runes_touch(AppState* st) {
    if(st->runes.kind == PUZZLE_TURN) {
        runes_try(st);
        return;
    }
    for(int k = 0; k < st->rune_ntouched; k++)
        if(st->rune_touched[k] == st->rune_sel) return;
    st->rune_touched[st->rune_ntouched++] = (uint8_t)st->rune_sel;
    if(st->rune_ntouched >= st->runes.count) runes_try(st);
}

/* The forge lists only recipes the player knows (recipe_known), and, while
 * something corrupted is carried, one more card: "a dark mixture?" (the
 * experiment slot, index RECIPE_COUNT; spec 50 Q1 §Q.10.2). */
#define CRAFT_EXPERIMENT RECIPE_COUNT
static bool craft_slot_open(const AppState* st, int slot) {
    if(slot == CRAFT_EXPERIMENT) return afflict_carries_corrupted(&st->character);
    return recipe_known((uint8_t)slot, st->character.recipes_known);
}

static void craft_step(AppState* st, int dir) {
    int slots = RECIPE_COUNT + 1;
    for(int i = 0; i < slots; i++) {
        st->craft_cursor = (int8_t)((st->craft_cursor + slots + dir) % slots);
        if(craft_slot_open(st, st->craft_cursor)) return;
    }
}

/* Experiment: if the bag can make a hidden dark recipe, it is found and
 * pulled; otherwise nothing is learned and nothing spent. */
static void craft_experiment(AppState* st) {
    int id = afflict_experiment(&st->character);
    if(id < 0) {
        set_status(st, AF_LINE_NOTHING);
        return;
    }
    st->craft_cursor = (int8_t)id;
    save_io_write_character(&st->character);
    craft_pull(st);
}

static void on_world_move(AppState* st, MoveDir dir) {
    if(dir == MoveNone) return;
    st->status_rune = false;
    /* Update facing to the walked direction — keeps the FPV camera
     * aimed where the player is heading (slice 2026-06-03e). */
    switch(dir) {
    case MoveNorth: st->character.facing = FPV_FACE_N; break;
    case MoveEast:  st->character.facing = FPV_FACE_E; break;
    case MoveSouth: st->character.facing = FPV_FACE_S; break;
    case MoveWest:  st->character.facing = FPV_FACE_W; break;
    default: break;
    }
    int px = st->character.player_x;
    int py = st->character.player_y;

    /* Bump-to-engage (2026-06-01 fix): world_try_move only checks tile
     * walkability — without this guard, the player walks ONTO a creature's
     * tile (creature rendered under @, looks like "invisible spider") and
     * combat triggers at distance 0. Resolution: check the destination for a
     * live creature first. Hostile → open combat right here. Non-hostile →
     * blocked. Either way, don't call world_try_move (so picking up items or
     * crossing doors through a creature isn't possible). */
    int nx = px, ny = py;
    switch(dir) {
    case MoveNorth: ny--; break;
    case MoveSouth: ny++; break;
    case MoveEast:  nx++; break;
    case MoveWest:  nx--; break;
    default: return;
    }
    if(nx >= 0 && nx < WORLD_COLS && ny >= 0 && ny < WORLD_ROWS) {
        for(int i = 0; i < st->creature_count; i++) {
            Creature* c = &st->creatures[i];
            if(!c->alive) continue;
            if(c->x != (uint8_t)nx || c->y != (uint8_t)ny) continue;
            CreatureDef d;
            creature_compose(c->family_id, c->trait_id, &d);
            if(creature_is_hostile(d.disposition, d.provoke, c->aggro)) {
                /* Engage directly — same setup as maybe_start_combat. */
                st->combat_foe = i;
                st->combat_foe_hp = d.hp > c->wounds ? (uint16_t)(d.hp - c->wounds) : 1;   /* wounds from range carry in */
                st->combat_cursor = 0;
                st->combat_round = 0;
                char nm[24];
                creature_name(&d, nm, sizeof(nm));
                set_statusf(st, "engage %s!", nm);
                st->screen = ScreenCombat;
            } else {
                set_status(st, "blocked");
            }
            return;
        }
    }

    char dest_glyph = '\0';
    MoveResult r = world_try_move(&st->world, dir, &px, &py, &dest_glyph);
    st->character.player_x = (int16_t)px;
    st->character.player_y = (int16_t)py;

    /* A real action (not a blocked bump) costs a turn + a unit of torch
     * fuel — the event-driven clock (§14.0). Fuel floors at 0 (never
     * fully blind; radius stays 1). */
    bool took_turn = (r != MoveBlockedByWall && r != MoveBlockedByEdge);
    if(took_turn) {
        advance_turn(st);
    }

    switch(r) {
    case MovePickedUpItem: {
        /* Slice 2026-06-03d (economy bundle): pickup grants no windfall.
         * The slice-4 placeholder "materials grant credits on pickup"
         * was waiting for the shop sink, which now exists. All value
         * flows through the shop (scrap at half, vendor at chunk price).
         * Torches still immediate-refuel — they're a consumable for the
         * torch system, not a tradeable. */
        const KindDef* k = kind_by_glyph(dest_glyph);
        if(k) {
            st->character.identified |= (1ull << k->id);
            if(k->fuel > 0) {
                uint32_t f = (uint32_t)st->character.torch_fuel + k->fuel;
                st->character.torch_fuel =
                    (f > TORCH_FUEL_MAX) ? (uint16_t)TORCH_FUEL_MAX : (uint16_t)f;
                set_statusf(st, "%s  +%u fuel", k->true_name, (unsigned)k->fuel);
            } else {
                if(k->id < SAVE_INV_KINDS_MAX &&
                   st->character.inv_qty[k->id] < 255) {
                    st->character.inv_qty[k->id]++;
                }
                set_statusf(st, "got %s", k->true_name);
                /* A word source or a tome of making is read on the spot (spec 58). */
                const char* read = arc_pickup(&st->world, px, py, &st->character);
                if(read) set_status(st, read);
                /* A book or a tome also teaches from the dark tree (spec 50 Q1 §Q.10.2). */
                if(afflict_read(dest_glyph, st->campaign_seed, st->character.chunk_x,
                                st->character.chunk_y, px, py, &st->character) >= 0)
                    set_status(st, ARC_LINE_READ);
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
    case MoveSteppedOnVendor:
        /* Open the shop in vendor flavor (full chunk prices + buy/sell
         * toggle). The vendor tile stays — the player can step off and
         * back on freely. */
        st->shop_is_vendor = true;
        st->shop_mode = 0; /* land on SELL by default — players usually want to unload */
        st->shop_cursor = 0;
        st->screen = ScreenShop;
        st->status_line = NULL;
        break;
    case MoveSteppedOnVault:
        /* Home-chunk persistent stash. Default focus = Bag (most common
         * action is depositing surplus inventory). */
        st->stash_focus = 0;
        st->stash_cursor = 0;
        st->screen = ScreenStash;
        st->status_line = NULL;
        break;
    case MoveWalkedOffEdge:
        do_transition(st, dir,
                      (dir == MoveNorth || dir == MoveSouth) ? px : py);
        break;
    case MoveSteppedOnStairs:
        set_status(st, "stairs (Phase 4)");
        break;
    case MoveBlockedByWall:
    case MoveBlockedByEdge: {
        /* Walking into a site opens it (spec 58 §58.17). */
        int k = r == MoveBlockedByWall
                    ? arc_site_at(st->campaign_seed, st->character.chunk_x, st->character.chunk_y,
                                  &st->world, nx, ny)
                    : -1;
        if(k >= 0) {
            site_open(st, k, nx, ny);
            break;
        }
        /* A plain grave or sarcophagus: you may disturb it (spec 58 §58.6). */
        if(r == MoveBlockedByWall && nx >= 0 && ny >= 0 && nx < WORLD_COLS && ny < WORLD_ROWS &&
           dead_resting_place(st->world.tiles[ny][nx]) && can_disturb(st)) {
            st->site_k = -1;
            st->site_x = (int8_t)nx;
            st->site_y = (int8_t)ny;
            st->site_cursor = 0;
            st->screen = ScreenSite;
            break;
        }
        /* Slice 2026-06-04 — give collision a voice. In FPV especially,
         * an unmoved view doesn't read as "you bumped a wall" without
         * the status line saying so. Top-down still benefits — the
         * player gets confirmation their input registered. */
        set_status(st, "blocked.");
        break;
    }
    case MoveBlockedBySecret: {
        /* A hidden passage. It opens once the player's EFFECTIVE growth on the
         * axis that gates this edge (deterministic per shared edge; base +
         * persisted deed growth) reaches SECRET_AXIS_THRESHOLD — so the way you
         * play earns the way through. Otherwise it reads as a wall with a tell.
         * The secret sits one tile away in `dir` on the border, so the crossing
         * perp is the same as a walk-off-edge. */
        int cx = st->character.chunk_x;
        int cy = st->character.chunk_y;
        uint8_t axis = (uint8_t)world_edge_secret_axis(
            st->campaign_seed, cx, cy, dir, DEED_AXIS_COUNT);
        uint8_t base = character_base_axis(&st->character, axis);
        uint8_t eff = deeds_effective_axis(&st->deeds, base, axis);
        if(eff >= SECRET_AXIS_THRESHOLD) {
            do_transition(st, dir,
                          (dir == MoveNorth || dir == MoveSouth) ? px : py);
        } else {
            set_status(st, "the stone here rings hollow.");
        }
        break;
    }
    case MoveOk: {
        st->status_line = NULL;
        /* Terrain underfoot (spec 50 §L): scree costs a fuel tick, a
         * glowcap is harvested for fuel. Data lives in the TERRAIN row. */
        TerrainStep ts;
        if(terrain_step(dest_glyph, &ts)) {
            uint16_t before = st->character.torch_fuel;
            st->character.torch_fuel = terrain_step_fuel(before, ts.fuel, TORCH_FUEL_MAX);
            /* Same light alarms as advance_turn: scree can put the torch out. */
            if(before > 0 && st->character.torch_fuel == 0) {
                notify(st, &sequence_error);
            } else if(fov_radius_for_fuel(st->character.torch_fuel) < fov_radius_for_fuel(before)) {
                notify(st, &sequence_single_vibro);
            }
            if(ts.consumed) {
                st->world.tiles[py][px] = TILE_FLOOR;
                deltas_record(
                    st->character.campaign_id, &st->current_deltas, px, py, TILE_FLOOR);
            }
            if(ts.message) set_status(st, ts.message);
        }
        /* A carving underfoot (spec 58 §58.17): spoken words are learned;
         * a seen clue shows its rune to whoever has the SIGHT to read it. */
        {
            uint8_t axes[DEED_AXIS_COUNT];
            effective_axes(st, axes);
            int rx = region_of(st->character.chunk_x), ry = region_of(st->character.chunk_y);
            const RegionRecord* before = region_book_get(&st->region_book, rx, ry);
            uint8_t had = before ? before->pieces : 0;
            ArcStep as;
            arc_step(st->campaign_seed, st->character.chunk_x, st->character.chunk_y, &st->world, px, py,
                     axes[DEED_AXIS_SIGHT], &st->region_book, &as);
            if(as.line) {
                set_status(st, as.line);
                st->status_rune = as.rune;
                memcpy(st->status_icon, as.icon, sizeof(st->status_icon));
                st->status_marks = as.marks;
                const RegionRecord* after = region_book_get(&st->region_book, rx, ry);
                if(after && after->pieces != had) arc_save(st);
            }
        }
        break;
    }
    }

    /* Transitions recompute visibility for the new chunk inside
     * do_transition; same-chunk actions refresh here (fuel change may
     * have shrunk/grown the lit radius). */
    if(took_turn && r != MoveSteppedOnDoor && r != MoveWalkedOffEdge && st->screen == ScreenWorld) {
        sky_tick(st);
        dead_tick(st);
        quirk_tick(st);
        /* The spectral's chill: every other step costs an extra turn, and
         * the creatures take it (spec 50 Q1 §Q.3). */
        if(st->character.chill && (st->character.turn & 1u) && st->screen == ScreenWorld)
            advance_turn(st);
    }
    if(r != MoveSteppedOnDoor && r != MoveWalkedOffEdge) {
        recompute_visibility(st);
    }

    save_io_write_character(&st->character);
    maybe_start_combat(st); /* a hostile adjacent after this turn → engage */
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
        .combat_foe = -1,
        .pending_quest_entry = -1,    /* slice 49.F5 — no quest open */
        .pending_quest_template = -1,
        .quest_choice = 0,
        .resolved_mask = 0u,
        .craft_anim_frame = 0,
        .craft_pending_tier = PULL_FLOOR,
    };

    SaveIoResult io_init = save_io_init();
    if(io_init != SaveIoOk) {
        set_status(&state, "SD init failed");
    } else if(save_io_count_campaigns() > 0) {
        state.cursor = MenuContinue;
    }

    /* Tensura ledger — load the lifetime axis-growth rollup on app open
     * (slice 48.F4). The real_self_id is the same hardcoded "themrburn"
     * used in finalize_new_character; when the profile.json path lands
     * (slice 48.F8 / dock), it sources from there. */
    deeds_init(&state.deeds);
    deeds_load(&state.deeds, "themrburn");

    /* Slice 48.F8 stub — check for a dock-supplied profile_<real_self>.json
     * packet. The consumer side is wired (status line surfaces "profile
     * available") so when the bridge work lands and starts pushing real
     * packets, the device responds immediately. The actual diff-view +
     * axis-override happens in a later slice once the packet schema is
     * exercised; this stub just acknowledges arrival. */
    {
        Storage* storage = furi_record_open(RECORD_STORAGE);
        FileInfo info;
        if(storage_common_stat(
               storage,
               "/ext/apps_data/sanctum_rpg/profile_themrburn.json",
               &info) == FSE_OK && info.size > 0) {
            set_status(&state, "profile packet available");
        }
        furi_record_close(RECORD_STORAGE);
    }

    /* Day-streak detection (slice 48.F7 — "world remembers your days").
     * Read the most-recent campaign's last_played_at_unix and compare to
     * today's RTC. If today == last_played_day + 1, you returned on the
     * next day — a streak day. Record DEED_DAY_STREAK once per session.
     * Same day or >1 day gap → no deed. Honors session-cap = 3 from
     * spec 48 §5.2 (a single login can't grind multiple streak days). */
    {
        DateTime now_dt;
        furi_hal_rtc_get_datetime(&now_dt);
        uint64_t now_unix = datetime_datetime_to_timestamp(&now_dt);
        uint32_t today_day = (uint32_t)(now_unix / 86400u);

        char prev_id[SAVE_IO_CAMPAIGN_ID_MAX + 1];
        if(save_io_most_recent_campaign(prev_id, sizeof(prev_id)) == SaveIoOk) {
            CampaignMeta prev_meta;
            if(save_io_load_meta(prev_id, &prev_meta) == SaveIoOk &&
               prev_meta.last_played_at_unix > 0) {
                uint32_t last_day =
                    (uint32_t)(prev_meta.last_played_at_unix / 86400u);
                if(today_day == last_day + 1) {
                    deeds_record(&state.deeds, "themrburn", prev_id,
                                 0u, DEED_DAY_STREAK);
                }
            }
        }
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
    state.view_port = view_port; /* Thread B — for in-handler animation */
    state.notif = furi_record_open(RECORD_NOTIFICATION);

    bool running = true;
    InputEvent event;
    while(running) {
        FuriStatus s =
            furi_message_queue_get(input_queue, &event, FuriWaitForever);
        if(s != FuriStatusOk) continue;
        if(event.type != InputTypeShort && event.type != InputTypeRepeat &&
           event.type != InputTypeLong)
            continue;
        /* Repeat is for the d-pad only (hold to keep walking / scrolling).
         * OK and Back mean one deliberate act each. Holding OK past the
         * long-press (the FPV toggle) streams Repeats, and each one used to
         * land as an OK press: FPV's "examine ahead" flipped on and off
         * (spending turns, logging SIGHT deeds), and release often left the
         * player in an examine mode FPV doesn't draw — so Up/Down moved an
         * invisible cursor and the view seemed to ignore movement. */
        if(event.type == InputTypeRepeat &&
           (event.key == InputKeyOk || event.key == InputKeyBack))
            continue;

        /* Each input is a fresh frame — transient status cleared on title/picker,
         * preserved on world only when the move sets it. */
        if(state.screen != ScreenWorld && state.screen != ScreenCombat) {
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
                if(state.codex_scroll <
                   (KIND_COUNT + CREATURE_FAMILY_COUNT) - PICKER_VISIBLE_ROWS)
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
                /* Examine mode: d-pad moves the cursor (free — looking isn't
                 * acting); OK scans a creature under the cursor (deliberate,
                 * costs turns, spec §4.7) else exits; Back exits. */
                switch(event.key) {
                case InputKeyUp:    examine_move(&state, 0, -1); break;
                case InputKeyDown:  examine_move(&state, 0, +1); break;
                case InputKeyLeft:  examine_move(&state, -1, 0); break;
                case InputKeyRight: examine_move(&state, +1, 0); break;
                case InputKeyOk: {
                    /* Examine @ → open the read-only character sheet (slice 1c). */
                    if(state.examine_x == state.character.player_x &&
                       state.examine_y == state.character.player_y) {
                        state.examining = false;
                        state.screen = ScreenCharSheet;
                        break;
                    }
                    const Creature* c =
                        creature_at(&state, state.examine_x, state.examine_y);
                    if(c && state.lit[state.examine_y][state.examine_x]) {
                        /* Scan while there's more to learn about its kind;
                         * once there isn't, a known cast fires (spec 46 §5.1). */
                        CreatureDef cd;
                        creature_compose(c->family_id, c->trait_id, &cd);
                        if(cast_fires(state.character.observe, cd.scan_diff,
                                      creature_bestiary_grade(state.character.bestiary, cd.family_id),
                                      state.character.casts_known))
                            cast_fire(&state, (int)(c - state.creatures));
                        else
                            scan_creature(&state, (int)(c - state.creatures));
                    } else {
                        /* Examine on an empty lit tile = SIGHT growth (the
                         * "you looked, you saw" deed, slice 48.F5). Capped
                         * 4/session — keeps the act meaningful, not farmable. */
                        if(state.lit[state.examine_y][state.examine_x]) {
                            deeds_record(&state.deeds, "themrburn",
                                         state.character.campaign_id,
                                         state.character.turn, DEED_EXAMINE);
                        }
                        state.examining = false;
                        state.status_line = NULL;
                    }
                    break;
                }
                case InputKeyBack:
                    state.examining = false;
                    state.status_line = NULL;
                    break;
                default: break;
                }
            } else {
                /* Long-press OK toggles between top-down and FPV view
                 * modes (slice 2026-06-03e). Both modes stay available
                 * indefinitely; long-press flips back and forth. The
                 * long-press latency (~500-700ms) is the firmware's
                 * threshold — not render lag. We announce the switch on
                 * the status strip so the player gets confirmation. */
                if(event.type == InputTypeLong && event.key == InputKeyOk) {
                    state.view_mode ^= 1u;
                    set_status(&state,
                               state.view_mode == 1 ? "view: FPV"
                                                    : "view: top-down");
                    break;
                }
                if(event.type == InputTypeLong) break;

                if(state.view_mode == 1) {
                    /* FPV input model: Up/Down walk forward/back,
                     * L/R turn 90°, OK examine ahead. */
                    switch(event.key) {
                    case InputKeyUp: {
                        /* Walk forward in current facing. */
                        MoveDir d = (state.character.facing == FPV_FACE_N) ? MoveNorth
                                  : (state.character.facing == FPV_FACE_E) ? MoveEast
                                  : (state.character.facing == FPV_FACE_S) ? MoveSouth
                                  : MoveWest;
                        on_world_move(&state, d);
                        break;
                    }
                    case InputKeyDown: {
                        /* Walk backward — opposite of facing, but DON'T
                         * change facing (you're stepping back, not
                         * turning around). */
                        uint8_t saved = state.character.facing;
                        MoveDir d = (saved == FPV_FACE_N) ? MoveSouth
                                  : (saved == FPV_FACE_E) ? MoveWest
                                  : (saved == FPV_FACE_S) ? MoveNorth
                                  : MoveEast;
                        on_world_move(&state, d);
                        state.character.facing = saved;
                        break;
                    }
                    case InputKeyLeft:
                        state.character.facing = fpv_turn_left(state.character.facing);
                        save_io_write_character(&state.character);
                        break;
                    case InputKeyRight:
                        state.character.facing = fpv_turn_right(state.character.facing);
                        save_io_write_character(&state.character);
                        break;
                    case InputKeyOk:
                        /* Examine ahead — target the tile one step in
                         * facing direction. */
                        state.examining = true;
                        state.examine_x = (int8_t)(
                            state.character.player_x + fpv_facing_dx(state.character.facing));
                        state.examine_y = (int8_t)(
                            state.character.player_y + fpv_facing_dy(state.character.facing));
                        /* Clamp into chunk bounds. */
                        if(state.examine_x < 0) state.examine_x = 0;
                        if(state.examine_x >= WORLD_COLS) state.examine_x = WORLD_COLS - 1;
                        if(state.examine_y < 0) state.examine_y = 0;
                        if(state.examine_y >= WORLD_ROWS) state.examine_y = WORLD_ROWS - 1;
                        /* FPV draws no examine cursor, so say the mode out
                         * loud — otherwise Up/Down silently stop walking. */
                        set_status(&state, "looking ahead. Back: done");
                        break;
                    case InputKeyBack:
                        state.screen = ScreenTitle;
                        state.campaign_loaded = false;
                        state.status_line = NULL;
                        break;
                    default: break;
                    }
                    break;
                }

                /* Top-down input model (unchanged). */
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

        case ScreenCombat:
            switch(event.key) {
            case InputKeyUp:
            case InputKeyDown: {
                int nverbs = afflict_throwable(&state.character) != 0xFFu ? 3 : 2;
                state.combat_cursor =
                    (state.combat_cursor + (event.key == InputKeyUp ? nverbs - 1 : 1)) % nverbs;
                break;
            }
            case InputKeyOk:
                if(state.combat_cursor == 0) combat_strike(&state);
                else if(state.combat_cursor == 1) combat_flee(&state);
                else if(afflict_throwable(&state.character) != 0xFFu) combat_throw(&state);
                else state.combat_cursor = 0;
                break;
            case InputKeyBack:
                combat_flee(&state); /* Back = quick-flee */
                break;
            default: break;
            }
            break;

        case ScreenClassPick:
            switch(event.key) {
            case InputKeyLeft:
                state.pending_class_id =
                    (uint8_t)((state.pending_class_id + CLASS_COUNT - 1) % CLASS_COUNT);
                character_apply_class(&state.character, state.pending_class_id);
                break;
            case InputKeyRight:
                state.pending_class_id =
                    (uint8_t)((state.pending_class_id + 1) % CLASS_COUNT);
                character_apply_class(&state.character, state.pending_class_id);
                break;
            case InputKeyOk:
                if(state.pending_class_id == CLASS_WANDERER) {
                    state.stat_buy_cursor = 0;
                    state.screen = ScreenStatBuy;
                } else {
                    finalize_new_character(&state);
                }
                break;
            case InputKeyBack:
                state.screen = ScreenTitle;
                break;
            default: break;
            }
            break;

        case ScreenCharSheet:
            switch(event.key) {
            case InputKeyOk:
                /* Slice 2: OK opens the inventory. */
                state.inv_cursor = 0;
                state.screen = ScreenInventory;
                break;
            case InputKeyBack:
                state.screen = ScreenWorld;
                break;
            default: break;
            }
            break;

        case ScreenInventory:
            switch(event.key) {
            case InputKeyLeft:
                if(state.inv_cursor > 0) state.inv_cursor--;
                break;
            case InputKeyRight:
                if(state.inv_cursor < KIND_COUNT - 1) state.inv_cursor++;
                break;
            case InputKeyUp:
                /* Slice 4: Up = Forge (craft). */
                state.craft_cursor = 0;
                state.screen = ScreenCraft;
                state.status_line = NULL;
                break;
            case InputKeyDown:
                /* Slice 4: Down = Shop (sell). */
                state.shop_cursor = 0;
                state.screen = ScreenShop;
                state.status_line = NULL;
                break;
            case InputKeyOk:
                inventory_use(&state);
                break;
            case InputKeyBack:
                state.screen = ScreenWorld;
                break;
            default: break;
            }
            break;

        case ScreenCraft:
            switch(event.key) {
            case InputKeyLeft:
                craft_step(&state, -1);
                state.status_line = NULL;
                break;
            case InputKeyRight:
                craft_step(&state, +1);
                state.status_line = NULL;
                break;
            case InputKeyOk:
                if(state.craft_cursor == CRAFT_EXPERIMENT) craft_experiment(&state);
                else craft_pull(&state);
                break;
            case InputKeyBack:
                state.screen = ScreenInventory;
                break;
            default: break;
            }
            break;

        case ScreenShop:
            switch(event.key) {
            case InputKeyUp:
                if(state.shop_cursor > 0) state.shop_cursor--;
                break;
            case InputKeyDown: {
                uint8_t list[KIND_COUNT];
                int n;
                if(state.shop_is_vendor && state.shop_mode == 1) {
                    n = build_buyable_list(
                        (uint8_t)state.world.biome, list, KIND_COUNT);
                } else {
                    n = build_sellable_list(&state.character, list, KIND_COUNT);
                }
                if(state.shop_cursor < n - 1) state.shop_cursor++;
                break;
            }
            case InputKeyLeft:
            case InputKeyRight:
                /* Toggle BUY/SELL only at a real vendor — the scrap dealer
                 * has no BUY surface. */
                if(state.shop_is_vendor) {
                    state.shop_mode = (uint8_t)(state.shop_mode ^ 1u);
                    state.shop_cursor = 0;
                }
                break;
            case InputKeyOk:
                if(state.shop_is_vendor && state.shop_mode == 1) {
                    shop_buy(&state);
                } else {
                    shop_sell(&state);
                }
                break;
            case InputKeyBack:
                /* Vendor shop opened FROM world → return to world.
                 * Scrap shop opened FROM inventory → return to inventory. */
                state.screen =
                    state.shop_is_vendor ? ScreenWorld : ScreenInventory;
                state.shop_is_vendor = false;
                state.shop_mode = 0;
                break;
            default: break;
            }
            break;

        case ScreenFpvDemo:
            /* Deprecated. FPV is now a view-mode of ScreenWorld; this
             * case is unreachable but kept for enum compat. Any input
             * routes back to ScreenWorld. */
            state.screen = ScreenWorld;
            state.status_line = NULL;
            break;

        case ScreenStash:
            switch(event.key) {
            case InputKeyUp:
                if(state.stash_cursor > 0) state.stash_cursor--;
                break;
            case InputKeyDown:
                if(state.stash_cursor < KIND_COUNT - 1) state.stash_cursor++;
                break;
            case InputKeyLeft:
            case InputKeyRight:
                state.stash_focus = (uint8_t)(state.stash_focus ^ 1u);
                break;
            case InputKeyOk:
                if(state.stash_focus == 0) stash_deposit(&state);
                else                       stash_withdraw(&state);
                break;
            case InputKeyBack:
                state.screen = ScreenWorld;
                break;
            default: break;
            }
            break;

        case ScreenQuest:
            /* Slice 49.F5 — L/R cycles A/B branch; OK resolves; Back
             * dismisses without resolving (the quest can re-surface on
             * next visit since resolved_mask isn't set on dismiss). */
            switch(event.key) {
            case InputKeyLeft:  state.quest_choice = 0; break;
            case InputKeyRight: state.quest_choice = 1; break;
            case InputKeyOk:    quest_resolve(&state); break;
            case InputKeyBack:
                state.pending_quest_entry = -1;
                state.pending_quest_template = -1;
                state.screen = ScreenWorld;
                break;
            default: break;
            }
            break;

        case ScreenSite: {
            uint8_t acts[4];
            int n = site_actions(&state, acts);
            switch(event.key) {
            case InputKeyUp:   if(state.site_cursor > 0) state.site_cursor--; break;
            case InputKeyDown: if(state.site_cursor < n - 1) state.site_cursor++; break;
            case InputKeyOk:   site_act(&state); break;
            case InputKeyBack: state.screen = ScreenWorld; break;
            default: break;
            }
            break;
        }

        case ScreenRite: {
            uint8_t ways[WAY_COUNT];
            int n = rite_ways(&state, ways);
            switch(event.key) {
            case InputKeyUp:   if(state.rite_cursor > 0) state.rite_cursor--; break;
            case InputKeyDown: if(state.rite_cursor < n - 1) state.rite_cursor++; break;
            case InputKeyOk:   rite_begin(&state); break;
            case InputKeyBack: state.screen = ScreenSite; break;
            default: break;
            }
            break;
        }

        case ScreenVigil:
            switch(event.key) {
            case InputKeyOk:   vigil_wait(&state); break;
            case InputKeyBack:
                set_status(&state, ARC_LINE_BROKEN);
                state.screen = ScreenWorld;
                break;
            default: break;
            }
            break;

        case ScreenRunes:
            switch(event.key) {
            case InputKeyLeft:  if(state.rune_sel > 0) state.rune_sel--; break;
            case InputKeyRight: if(state.rune_sel < state.runes.count - 1) state.rune_sel++; break;
            case InputKeyUp:
            case InputKeyDown:
                if(state.runes.kind != PUZZLE_ORDER)
                    state.rune_turn[state.rune_sel] =
                        (uint8_t)((state.rune_turn[state.rune_sel] + (event.key == InputKeyUp ? 1 : 3)) % 4);
                break;
            case InputKeyOk:   runes_touch(&state); break;
            case InputKeyBack: state.screen = ScreenWorld; break;
            default: break;
            }
            break;

        case ScreenStatBuy: {
            /* Slice 48.F1 axes BODY/CRAFT/SIGHT/MIND/HEART/WILL — pointer
             * array order matches stat_buy_cursor + STAT_NAMES in the draw. */
            uint8_t* const stats[6] = {
                &state.character.body,  &state.character.craft,
                &state.character.sight, &state.character.mind,
                &state.character.heart, &state.character.will,
            };
            int idx = state.stat_buy_cursor;
            int total = (int)state.character.body  + (int)state.character.craft +
                        (int)state.character.sight + (int)state.character.mind +
                        (int)state.character.heart + (int)state.character.will;
            int budget = 66 - total;
            switch(event.key) {
            case InputKeyUp:
                if(state.stat_buy_cursor > 0) state.stat_buy_cursor--;
                break;
            case InputKeyDown:
                if(state.stat_buy_cursor < 5) state.stat_buy_cursor++;
                break;
            case InputKeyLeft:
                if(*stats[idx] > 8) (*stats[idx])--;
                break;
            case InputKeyRight:
                if(*stats[idx] < 16 && budget > 0) (*stats[idx])++;
                break;
            case InputKeyOk:
                finalize_new_character(&state);
                break;
            case InputKeyBack:
                /* Slice 48.F2/F3 — back from profile-review = cancel New
                 * Game. No save artifact (campaign not yet created on disk
                 * — finalize hasn't run). Returns to the title screen. */
                state.screen = ScreenTitle;
                break;
            default: break;
            }
            break;
        }
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
