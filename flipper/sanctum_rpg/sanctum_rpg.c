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
#include <stdint.h>
#include <stdio.h>

#include "biome.h"
#include "classes.h"
#include "creatures.h"
#include "deeds.h"
#include "deltas.h"
#include "fov.h"
#include "loot.h"
#include "narrative.h"
#include "pool.h"
#include "recipes.h"
#include "save_io.h"
#include "stamps.h"
#include "bearing.h"
#include "names.h"
#include "trade.h"
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
    ScreenCombat,
    ScreenClassPick, /* slice 1c — New Game class picker (unreachable; spec 48.F2) */
    ScreenStatBuy,   /* slice 1c → 48.F3 — Profile Review (only PC builder) */
    ScreenCharSheet, /* slice 1c — read-only sheet (examine @ to open) */
    ScreenInventory, /* slice 2 — bag/equipment grid (from sheet, OK opens) */
    ScreenCraft,     /* slice 4 — the Forge: slot-machine recipe pull */
    ScreenShop,      /* slice 4 — sell items for credits */
    ScreenStash,     /* slice 2026-06-03d/C — home-chunk vault deposit/withdraw */
    ScreenQuest,     /* slice 49.F5 — quest surfaced, branch A/B choice */
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
    c->credits = DEFAULT_CREDITS;
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
    uint8_t wbiome = (biome_terrain(st->world.biome) == TERRAIN_OPEN)
                         ? STAMP_BIOME_OUTDOOR : STAMP_BIOME_CAVERN;
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
    uint8_t pool_biome = (biome_terrain(st->world.biome) == TERRAIN_OPEN)
                             ? STAMP_BIOME_OUTDOOR : STAMP_BIOME_CAVERN;
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
static void enter_world_phase2(
    AppState* st, const char* campaign_id, bool fresh_character) {
    world_generate_chunk(
        st->campaign_seed,
        st->character.chunk_x, st->character.chunk_y,
        &st->world);

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
                (uint8_t)st->world.biome, place, sizeof(place));
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
        uint8_t nbiome = (biome_terrain(st->world.biome) == TERRAIN_OPEN)
                             ? STAMP_BIOME_OUTDOOR : STAMP_BIOME_CAVERN;
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
    switch(t) {
    case TILE_WALL:        return "rock wall";
    case TILE_ROCK:        return "boulder";
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
            (uint8_t)st->world.biome, place, sizeof(place));
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
                    switch(st->current_weather.kind) {
                    case WEATHER_STORM:      glyph = '"'; break;
                    case WEATHER_HEAT:       glyph = '~'; break;
                    case WEATHER_DUST_STORM: glyph = '_'; break;
                    case WEATHER_RAIN:
                    default:                 glyph = '\''; break;
                    }
                }
            } else if(st->seen[y][x]) {
                glyph = loot_is_item_glyph(tile) ? TILE_FLOOR : tile;
            } else {
                continue; /* unseen → dark */
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
        if(wg != '\0') {
            char wbuf[2] = {wg, '\0'};
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
        if(dist > 0) {
            char hbuf[8];
            snprintf(hbuf, sizeof(hbuf), "%s%u",
                     bearing_label(sx, sy), (unsigned)dist);
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

    int bw = 100, bh = 6, by = 16;
    canvas_draw_frame(canvas, 0, by, bw, bh);
    int filled = (d.hp > 0) ? (int)((bw - 2) * (int)st->combat_foe_hp / (int)d.hp) : 0;
    if(filled > 0) canvas_draw_box(canvas, 1, by + 1, filled, bh - 2);
    canvas_draw_line(canvas, 0, 24, SCREEN_W - 1, 24);

    static const char* const VERBS[2] = {"STRIKE", "FLEE"};
    for(int i = 0; i < 2; i++) {
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

/* Build the list of sellable kind ids (qty > 0 and value > 0). Returns count.
 * The Shop screen's cursor is an index INTO this list, not a kind id. */
static int build_sellable_list(const CharacterState* c, uint8_t* out, int max) {
    int n = 0;
    for(int i = 0; i < KIND_COUNT && n < max && i < SAVE_INV_KINDS_MAX; i++) {
        const KindDef* k = kind_by_id((uint8_t)i);
        if(!k) continue;
        if(c->inv_qty[i] == 0) continue;
        if(k->value == 0) continue;
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
    case PULL_FLOOR:
        st->character.credits += r->oddment_credits;
        set_statusf(st, "the work resists  +%uc",
                    (unsigned)r->oddment_credits);
        notify(st, &sequence_single_vibro);
        /* No deed on FLOOR — credits ARE the reward; growth waits for HIT. */
        break;
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
        return is_buy ? trade_buy_price(base, delta)
                      : trade_sell_price(base, delta);
    }
    /* Scrap dealer is sell-only; the BUY branch never reaches here in
     * normal flow, but if it did, treat as the same scrap rate. */
    return trade_scrap_price(base);
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
    st->character.inv_qty[id]--;
    st->character.credits += price;
    set_statusf(st, "sold %s +%uc", k->true_name, (unsigned)price);
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
    if(st->character.credits < price) {
        set_statusf(st, "need %uc", (unsigned)price);
        notify(st, &sequence_error);
        return;
    }
    if(id >= SAVE_INV_KINDS_MAX || st->character.inv_qty[id] >= 255) {
        set_status(st, "bag full");
        return;
    }
    st->character.credits -= price;
    st->character.inv_qty[id]++;
    st->character.identified |= (1ull << id); /* you bought it — you know it */
    set_statusf(st, "bought %s -%uc", k->true_name, (unsigned)price);
    notify(st, &sequence_success);
    save_io_write_character(&st->character);
}

/* Forge (slice 4 + Thread B animation) — single-recipe card view; during a
 * pull, the recipe card is overlaid with a 3-reel slot animation that
 * cycles glyphs and settles on a tier-appropriate pattern. */
static void draw_craft_screen(Canvas* canvas, const AppState* st) {
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
    char counter[16];
    snprintf(
        counter, sizeof(counter), "%d/%d",
        (int)(st->craft_cursor + 1), (int)RECIPE_COUNT);
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
    snprintf(
        balance, sizeof(balance), "%luc", (unsigned long)st->character.credits);
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
                snprintf(line, sizeof(line), "%c %s  %uc",
                         k->glyph, k->true_name, (unsigned)price);
            } else {
                snprintf(line, sizeof(line), "%c %s x%u  %uc",
                         k->glyph, k->true_name,
                         (unsigned)st->character.inv_qty[id], (unsigned)price);
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

    /* Grid: KIND_COUNT (7) slots in a single row, 16px col pitch — slot i is
     * kind id i. Equipped slot = inverted cell; cursor = frame. */
    const int CELL_W = 16, CELL_H = 12;
    const int GRID_Y = 18;
    for(int i = 0; i < KIND_COUNT; i++) {
        const KindDef* k = kind_by_id((uint8_t)i);
        if(!k) continue;
        int x = i * CELL_W;
        int y = GRID_Y;
        bool selected = (st->inv_cursor == i);
        bool eq = is_equipped(&st->character, (uint8_t)i);
        char gbuf[2] = {k->glyph, '\0'};
        if(st->character.inv_qty[i] > 0) {
            if(eq) {
                canvas_draw_box(canvas, x, y, CELL_W, CELL_H);
                canvas_invert_color(canvas);
                canvas_draw_str(canvas, x + 5, y + 9, gbuf);
                canvas_invert_color(canvas);
            } else {
                canvas_draw_str(canvas, x + 5, y + 9, gbuf);
            }
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

static void title_draw(Canvas* canvas, void* ctx) {
    const AppState* st = ctx;
    canvas_clear(canvas);
    switch(st->screen) {
    case ScreenTitle:       draw_title_screen(canvas, st); break;
    case ScreenLoadPicker:  draw_picker_screen(canvas, st); break;
    case ScreenWorld:       draw_world_screen(canvas, st); break;
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
                st->campaign_seed, cx, cy, (uint8_t)st->world.biome,
                place, sizeof(place));
            set_statusf(st, "%s", place);
        }
    }

    /* Slice 49.F4 — quest surfacing on chunk arrival. If this chunk is
     * an anchor for an unresolved entry, set pending_quest and open the
     * quest screen. Deterministic per (campaign_seed × entry_id) so the
     * SAME chunk always anchors the SAME quest within a campaign. */
    if(st->pending_quest_entry < 0) {
        /* Slice 50.F4: Pool-biased narrative pick on chunk transition. */
        Pool npool;
        uint8_t nbiome = (biome_terrain(st->world.biome) == TERRAIN_OPEN)
                             ? STAMP_BIOME_OUTDOOR : STAMP_BIOME_CAVERN;
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
static void advance_turn(AppState* st) {
    uint16_t old_fuel = st->character.torch_fuel;
    st->character.turn++;
    /* Atmosphere: rain/storm bleed extra fuel per turn. Indoor weather
     * is already attenuated upstream, so this naturally applies less. */
    uint16_t burn = FUEL_PER_TURN +
                    (uint16_t)st->current_weather.fuel_burn_extra;
    uint16_t fuel = (old_fuel >= burn) ? (uint16_t)(old_fuel - burn) : 0;
    st->character.torch_fuel = fuel;

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
        st->combat_foe_hp = d.hp;
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
static void combat_strike(AppState* st) {
    if(st->combat_foe < 0 || st->combat_foe >= st->creature_count) return;
    Creature* foe = &st->creatures[st->combat_foe];
    CreatureDef d;
    creature_compose(foe->family_id, foe->trait_id, &d);
    char nm[24];
    creature_name(&d, nm, sizeof(nm));
    st->combat_round++;

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
        foe->alive = 0;
        /* Persist the kill (slice 1b): defeated creatures stay defeated across
         * chunk re-entry — the finite-world rule. Keyed by spawn position. */
        deltas_record_kill(
            st->character.campaign_id, &st->current_deltas,
            foe->spawn_x, foe->spawn_y);

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
        uint8_t dbiome = (biome_terrain(st->world.biome) == TERRAIN_OPEN)
                             ? STAMP_BIOME_OUTDOOR : STAMP_BIOME_CAVERN;
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
        return;
    }
    st->combat_foe_hp = (uint16_t)(st->combat_foe_hp - dmg);

    int fdmg = (int)d.atk - player_def(&st->character, &st->deeds) / 8;
    if(fdmg < 1) fdmg = 1;
    if((int)st->character.hp <= fdmg) {
        player_fall(st);
        return;
    }
    st->character.hp = (uint16_t)(st->character.hp - fdmg);
    set_statusf(st, "hit %d  took %d", dmg, fdmg);
    notify(st, &sequence_single_vibro);

    /* Thread C — equipped armor expertise +1 per absorbed hit (Tensura;
     * capped 100). The act of taking and surviving a hit teaches you the
     * specific armor — D&D proficiency at item level. */
    if(st->character.equipped_armor != SAVE_EQUIP_NONE &&
       st->character.equipped_armor < SAVE_INV_KINDS_MAX) {
        uint8_t* xp = &st->character.expertise[st->character.equipped_armor];
        if(*xp < 100) (*xp)++;
    }

    save_io_write_character(&st->character);
}

/* FLEE: ~60% escape; failure costs a foe hit. Per-round seed so retries vary. */
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
        if(tier >= 3) {
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

static void on_world_move(AppState* st, MoveDir dir) {
    if(dir == MoveNone) return;
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
                st->combat_foe_hp = d.hp;
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
        /* Slice 2026-06-03d (economy bundle): pickup grants NO credits.
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
        if(event.type != InputTypeShort && event.type != InputTypeRepeat) continue;

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
            case InputKeyDown:
                state.combat_cursor ^= 1; /* two verbs — toggle */
                break;
            case InputKeyOk:
                if(state.combat_cursor == 0) combat_strike(&state);
                else combat_flee(&state);
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
                state.craft_cursor =
                    (int8_t)((state.craft_cursor + RECIPE_COUNT - 1) %
                             RECIPE_COUNT);
                state.status_line = NULL;
                break;
            case InputKeyRight:
                state.craft_cursor =
                    (int8_t)((state.craft_cursor + 1) % RECIPE_COUNT);
                state.status_line = NULL;
                break;
            case InputKeyOk:
                craft_pull(&state);
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
