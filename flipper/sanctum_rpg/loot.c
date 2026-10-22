/*
 * loot.c — see loot.h.
 *
 * v0.3.3 starter catalog: a tight, glyph-distinct set drawn from the
 * canonical kind_config.json vocabulary. Weights sum to 100 (so the
 * distribution test reads as percentages). Expand as biomes (v0.3.4)
 * and depth scaling (v0.3.8) gate which kinds appear where.
 *
 * Glyphs are intentionally distinct so the world tile grid (a plain
 * char[][]) unambiguously encodes which kind sits on a tile — no
 * parallel item layer needed. (This is the simplification the upcoming
 * "ASCII as pixel art" rendering discussion may revisit.)
 */

#include "loot.h"

#include <stddef.h>

#include "pool.h"
#include "trade.h"

/* id, glyph, true_name, unid_name, class, weight, value, flags, biomes, fuel
 *
 * biome affinity (v0.3.4): crystal is cavern-only, fungus outdoor-only,
 * the rest spawn in both. The torch (v0.3.5) grants fuel on pickup — the
 * light you hunt for to keep exploring as your own torch burns down. */
#define B_CAVE  BIOME_BIT(BIOME_CAVERN)
#define B_OUT   BIOME_BIT(BIOME_OUTDOOR)
#define B_BOTH  (B_CAVE | B_OUT)

/* slice 5 additions (per-kind equip bonuses): equip_slot + atk_bonus/
 * def_bonus/light_bonus. The "tool" weapon goes from a flat +2 hardcode
 * in player_atk to a data row here — future weapons (sword, club, gauntlet)
 * differentiate via the catalog without touching combat code. Armor and
 * lantern items will land later; their columns are zero today. */
/* Top-down forms (KindDef.map_icon): 8x8 XBM, row 0 first, LSB = left.
 * Rows 1..7 only, so an item never touches the tile above or below. */
static const uint8_t MAP_TOOL[8] = {0x00, 0x04, 0x0E, 0x0E, 0x0E, 0x04, 0x04, 0x04}; /* a head on a haft */
/* The corruption arc's objects (spec 58 §58.17), placed by WORLDGEN 9 and
 * never rolled (weight 0, no biome). Their glyphs are machine identities;
 * these forms are what the map shows. */
static const uint8_t MAP_SEAL[8]    = {0x00, 0x00, 0x1C, 0x22, 0x2A, 0x22, 0x1C, 0x00}; /* a disc with a boss */
static const uint8_t MAP_RELIQ[8]   = {0x00, 0x08, 0x1C, 0x3E, 0x22, 0x2A, 0x3E, 0x00}; /* a box under a little roof */
static const uint8_t MAP_CENSER[8]  = {0x00, 0x08, 0x08, 0x14, 0x3E, 0x2A, 0x1C, 0x08}; /* a pierced bowl on a chain */
static const uint8_t MAP_BOUND[8]   = {0x00, 0x00, 0x1C, 0x3E, 0x7F, 0x3E, 0x1C, 0x00}; /* a corded stone */
static const uint8_t MAP_SCROLL[8]  = {0x00, 0x00, 0x7E, 0x42, 0x5A, 0x42, 0x7E, 0x00}; /* a leaf with a line of hand */
static const uint8_t MAP_BOOK[8]    = {0x00, 0x00, 0x3C, 0x26, 0x26, 0x26, 0x3C, 0x00}; /* a sewn spine */
static const uint8_t MAP_TOME[8]    = {0x00, 0x7E, 0x46, 0x56, 0x46, 0x46, 0x7E, 0x00}; /* a heavy clasped book */
static const uint8_t MAP_CORD[8]    = {0x00, 0x00, 0x0C, 0x12, 0x2C, 0x48, 0x30, 0x00}; /* a loop of cord */
static const uint8_t MAP_NAIL[8]    = {0x00, 0x0E, 0x04, 0x04, 0x04, 0x04, 0x04, 0x00}; /* a long nail */
static const uint8_t MAP_WARD[8]    = {0x00, 0x08, 0x2A, 0x1C, 0x7F, 0x1C, 0x2A, 0x08}; /* a knotted star */
static const uint8_t MAP_CANDLE[8]  = {0x00, 0x08, 0x00, 0x08, 0x08, 0x08, 0x1C, 0x00}; /* a flame on a stub */
static const uint8_t MAP_SALT[8]    = {0x00, 0x00, 0x00, 0x08, 0x14, 0x22, 0x7F, 0x00}; /* a little heap */
static const uint8_t MAP_RELIC[8]   = {0x00, 0x00, 0x06, 0x0E, 0x1C, 0x38, 0x30, 0x00}; /* a finger bone */

const KindDef KIND_CATALOG[] = {
    /* id glyph true_name        unid_name             class           wt  val  flags                                          biomes  fuel heal effect       slot       atk def lt  map form */
    {0, '*', "crystal shard", "a glinting sliver",  KC_CRYSTALLINE, 38,  5, KF_PICKUPABLE,                                 B_CAVE,  0, 0, ""       ,    EQ_NONE,   0,  0,  0, NULL},
    {1, '&', "fungus cap",    "a fleshy growth",    KC_ORGANIC,     28,  3, KF_PICKUPABLE | KF_CONSUMABLE,                 B_OUT,   0, 3, "+3 HP",     EQ_NONE,   0,  0,  0, NULL},
    {2, 'u', "clay pot",      "a clay vessel",      KC_LIFE,        24,  2, KF_PICKUPABLE,                                 B_BOTH,  0, 0, ""       ,    EQ_NONE,   0,  0,  0, NULL},
    {3, '!', "vial",          "a stoppered vial",   KC_ENCOUNTER,   14,  8, KF_PICKUPABLE | KF_CONSUMABLE,                 B_BOTH,  0, 8, "+8 HP",     EQ_NONE,   0,  0,  0, NULL},
    {4, '(', "tool",          "a worn implement",   KC_ENCOUNTER,   11, 12, KF_PICKUPABLE | KF_EQUIP,                      B_BOTH,  0, 0, "+2 atk",    EQ_WEAPON, 2,  0,  0, MAP_TOOL},   /* '(' fills its cell top to bottom */
    {5, 'i', "torch",         "an unlit brand",     KC_ENCOUNTER,   15,  2, KF_PICKUPABLE,                                 B_BOTH, 50, 0, "+50 fuel",  EQ_NONE,   0,  0,  0, NULL},
    {6, 'T', "chest",         "a banded coffer",    KC_LIFE,         8, 30, KF_PICKUPABLE,                                 B_BOTH,  0, 0, ""       ,    EQ_NONE,   0,  0,  0, NULL},
    /* spec 58 §58.17 — the corruption arc. Names are placeholders (the user's call). */
    {7, 'e', "grave-seal",    "a lead disc",        KC_LIFE,         0,  0, KF_PICKUPABLE | KF_NOTRADE,                    0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_SEAL},
    {8, ']', "reliquary",     "a small box",        KC_LIFE,         0,  0, KF_PICKUPABLE | KF_NOTRADE,                    0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_RELIQ},
    {9, 'j', "censer",        "a pierced vessel",   KC_LIFE,         0,  0, KF_PICKUPABLE | KF_NOTRADE,                    0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_CENSER},
    {10, 'f', "bound stone",  "a corded stone",     KC_LIFE,         0,  0, KF_PICKUPABLE | KF_NOTRADE,                    0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_BOUND},
    {11, '?', "scroll",       "a rolled leaf",      KC_LIFE,         0,  4, KF_PICKUPABLE,                                 0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_SCROLL},
    {12, '}', "book",         "a sewn book",        KC_LIFE,         0,  6, KF_PICKUPABLE,                                 0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_BOOK},
    {13, '{', "tome",         "a heavy tome",       KC_LIFE,         0,  8, KF_PICKUPABLE,                                 0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_TOME},
    {14, 'z', "cord",         "a hank of cord",     KC_ORGANIC,      0,  0, KF_PICKUPABLE | KF_NOTRADE,                    0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_CORD},
    {15, 'J', "iron nail",    "a long nail",        KC_ENCOUNTER,    0,  0, KF_PICKUPABLE | KF_NOTRADE,                    0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_NAIL},
    {16, 'W', "ward",         "a knotted thing",    KC_ENCOUNTER,    0,  0, KF_PICKUPABLE | KF_NOTRADE,                    0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_WARD},
    {17, 'K', "candle",       "a tallow stub",      KC_ORGANIC,      0,  0, KF_PICKUPABLE | KF_NOTRADE,                    0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_CANDLE},
    {18, 'P', "salt",         "a twist of salt",    KC_CRYSTALLINE,  0,  0, KF_PICKUPABLE | KF_NOTRADE,                    0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_SALT},
    {19, ')', "relic",        "a finger bone",      KC_LIFE,         0,  0, KF_PICKUPABLE | KF_NOTRADE,                    0,       0, 0, ""       ,    EQ_NONE,   0,  0,  0, MAP_RELIC},
};

const int KIND_COUNT = (int)(sizeof(KIND_CATALOG) / sizeof(KIND_CATALOG[0]));

const KindDef* kind_by_id(uint8_t id) {
    if(id >= (uint8_t)KIND_COUNT) return NULL;
    return &KIND_CATALOG[id];
}

const KindDef* kind_by_glyph(char glyph) {
    for(int i = 0; i < KIND_COUNT; i++) {
        if(KIND_CATALOG[i].glyph == glyph) return &KIND_CATALOG[i];
    }
    return NULL;
}

const uint8_t* loot_map_icon(char glyph) {
    const KindDef* k = kind_by_glyph(glyph);
    return k ? k->map_icon : NULL;
}

int loot_is_item_glyph(char glyph) {
    const KindDef* k = kind_by_glyph(glyph);
    return k != NULL && (k->flags & KF_PICKUPABLE);
}

uint8_t loot_roll(Rng* r, Biome biome) {
    return loot_roll_pooled(r, biome, NULL);
}

/* Slice 50.F3 — Pool-biased loot roll. Same formula as F1.4.a. */
uint8_t loot_roll_pooled(Rng* r, Biome biome, const Pool* pool) {
    uint8_t bbit = BIOME_BIT(biome);
    uint32_t total = 0;
    uint32_t weights[64]; /* KIND_COUNT is small; comfortable. */
    for(int i = 0; i < KIND_COUNT; i++) {
        weights[i] = 0;
        if(!(KIND_CATALOG[i].flags & KF_PICKUPABLE)) continue;
        if(!(KIND_CATALOG[i].biomes & bbit)) continue;
        uint32_t base = KIND_CATALOG[i].weight;
        /* Spec 43 §17.3 #4: the numeraire takes no Pool bias, so a
         * Craft-themed cavern isn't a mint (landed with WORLDGEN 9). */
        if(pool && i < POOL_LOOT_KINDS && !trade_kind_is_numeraire((uint8_t)i)) {
            uint32_t bias = pool->loot_kind_bias[i];
            if(bias > 56u) bias = 56u;
            base = base * (8u + bias) / 8u;
        }
        weights[i] = base;
        total += base;
    }
    if(total == 0) return KIND_CATALOG[0].id;
    uint32_t pick = rng_range(r, 0, total);
    uint32_t acc = 0;
    for(int i = 0; i < KIND_COUNT; i++) {
        if(weights[i] == 0) continue;
        acc += weights[i];
        if(pick < acc) return KIND_CATALOG[i].id;
    }
    return KIND_CATALOG[KIND_COUNT - 1].id;
}

char loot_glyph(uint8_t kind_id) {
    const KindDef* k = kind_by_id(kind_id);
    return k ? k->glyph : '.';
}
