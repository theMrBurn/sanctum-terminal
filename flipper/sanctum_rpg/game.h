/* game.h — the Flipper RPG's rules: its state and what a key press does.
 *
 * The rules (game.c) call no Flipper SDK: only the pure modules, save_io,
 * deltas and platform.h. The screens (screens.c) draw this state; the shell
 * (sanctum_rpg.c on the device, test/host on the Mac) feeds it keys:
 *
 *   game_open(&st);                       once per launch
 *   step = game_input(&st, key, press);   per key; redraw unless GameIgnored
 *
 * Spec: sanctum-os/docs/specs/43_app_sanctum_rpg_flipper.md
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

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
#include "hollow.h"
#include "ritual.h"
#include "sky.h"
#include "weather.h"
#include "world.h"
#include "facing.h"
#include "platform.h"

#define PICKER_MAX_CAMPAIGNS  16
#define PICKER_VISIBLE_ROWS   4

#define STATUS_BUF_SIZE       48

/* Thread B — Forge slot-machine constants. The animation runs blocking
 * inside the input handler, presenting each frame through
 * platform_present_frame, which paces them. Total ~600ms — long enough to feel like a draw, short
 * enough not to make you wait. */
#define CRAFT_ANIM_SPIN_FRAMES   10  /* fast cycling */
#define CRAFT_ANIM_SETTLE_FRAMES  2  /* brief pause on result before status */
#define CRAFT_ANIM_TOTAL         (CRAFT_ANIM_SPIN_FRAMES + CRAFT_ANIM_SETTLE_FRAMES)

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
    /* The ledger section (spec 58 §58.8) reads the same campaign: its seed,
     * its words known, and region_book (arc_load). */
    uint32_t codex_seed;
    uint8_t codex_words;

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

    bool muted;              /* default ON during dev; toggled in Settings */

    /* Thread B — Forge slot-machine animation. The pull presents its
     * frames through platform_present_frame during the press. craft_
     * anim_frame > 0 puts the craft screen in animation mode; the draw
     * function shows cycling reels instead of the static recipe card. */
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

    /* Inside a hollow (spec 58 §58.15): which (index + 1; 0 = outside), its
     * kind, and the tile to come back out on. The pocket is built into
     * `world`; leaving rebuilds the chunk. Saves write the return tile. */
    uint8_t in_hollow;
    uint8_t hollow_kind_in;
    int8_t hollow_ret_x, hollow_ret_y;

    const char* status_line;
    char status_buf[STATUS_BUF_SIZE];
} AppState;

/* ─── input, as the game sees it ─────────────────────────────────── */

typedef enum { GameKeyUp, GameKeyDown, GameKeyRight, GameKeyLeft, GameKeyOk, GameKeyBack, GameKeyNone } GameKey;
/* Short, long and repeat are the presses the game reads; Other is a raw
 * press or release, which it ignores. */
typedef enum { GamePressShort, GamePressLong, GamePressRepeat, GamePressOther } GamePress;
typedef enum { GameIgnored, GameHandled, GameQuit } GameStep;

/* The fight's verbs, in a fixed order so a learned one never moves the
 * others: STRIKE and FLEE always; SKILL once a cast is learned (spec 46
 * §5.1); THROW once a flask's recipe is learned and one is carried. */
typedef enum { CV_STRIKE = 0, CV_FLEE, CV_SKILL, CV_THROW, CV_COUNT } CombatVerb;

typedef enum { SITE_ACT_SEAL = 0, SITE_ACT_DISTURB, SITE_ACT_RITE, SITE_ACT_LEAVE } SiteAct;

/* ─── the rules ───────────────────────────────────────────────────── */

void game_open(AppState* st);
GameStep game_input(AppState* st, GameKey key, GamePress type);

/* What the screens read (computed from the state, not stored in it). */
const char* examine_name(const AppState* st, int x, int y);
int codex_rows(const AppState* st);
int combat_verbs(const AppState* st, uint8_t* out);
bool is_equipped(const CharacterState* c, uint8_t kind_id);
uint16_t purse(const AppState* st);
int build_sellable_list(const CharacterState* c, uint8_t* out, int max);
int build_buyable_list(uint8_t biome, uint8_t* out, int max);
uint16_t shop_price_for(
    const AppState* st, uint8_t kind_id, uint16_t base, bool is_buy);
void arc_region_here(const AppState* st, int* rx, int* ry);
int site_actions(const AppState* st, uint8_t* acts);
int rite_ways(const AppState* st, uint8_t* ways);
EffortBody rite_body(const AppState* st, RitualWay way);
/* The character sheet (slice 5 → 48.F6) shows effective ATK/DEF: the
 * combat math's own reads, base axis plus lifetime delta (48.F5). */
int player_atk(const CharacterState* c, const DeedsState* d);
int player_def(const CharacterState* c, const DeedsState* d);
