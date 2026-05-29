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

/* id, glyph, true_name, unid_name, class, weight, value, flags, biomes, fuel
 *
 * biome affinity (v0.3.4): crystal is cavern-only, fungus outdoor-only,
 * the rest spawn in both. The torch (v0.3.5) grants fuel on pickup — the
 * light you hunt for to keep exploring as your own torch burns down. */
#define B_CAVE  BIOME_BIT(BIOME_CAVERN)
#define B_OUT   BIOME_BIT(BIOME_OUTDOOR)
#define B_BOTH  (B_CAVE | B_OUT)

const KindDef KIND_CATALOG[] = {
    {0, '*', "crystal shard", "a glinting sliver",  KC_CRYSTALLINE, 38,  5, KF_PICKUPABLE,                 B_CAVE,  0},
    {1, '&', "fungus cap",    "a fleshy growth",    KC_ORGANIC,     28,  3, KF_PICKUPABLE | KF_CONSUMABLE, B_OUT,   0},
    {2, 'u', "clay pot",      "a clay vessel",       KC_LIFE,        24,  2, KF_PICKUPABLE,                 B_BOTH,  0},
    {3, '!', "vial",          "a stoppered vial",    KC_ENCOUNTER,   14,  8, KF_PICKUPABLE | KF_CONSUMABLE, B_BOTH,  0},
    {4, '(', "tool",          "a worn implement",    KC_ENCOUNTER,   11, 12, KF_PICKUPABLE,                 B_BOTH,  0},
    {5, 'i', "torch",         "an unlit brand",      KC_ENCOUNTER,   15,  2, KF_PICKUPABLE,                 B_BOTH, 50},
    {6, 'T', "chest",         "a banded coffer",     KC_LIFE,         8, 30, KF_PICKUPABLE,                 B_BOTH,  0},
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

int loot_is_item_glyph(char glyph) {
    const KindDef* k = kind_by_glyph(glyph);
    return k != NULL && (k->flags & KF_PICKUPABLE);
}

uint8_t loot_roll(Rng* r, Biome biome) {
    uint8_t bbit = BIOME_BIT(biome);
    uint32_t total = 0;
    for(int i = 0; i < KIND_COUNT; i++) {
        if((KIND_CATALOG[i].flags & KF_PICKUPABLE) && (KIND_CATALOG[i].biomes & bbit)) {
            total += KIND_CATALOG[i].weight;
        }
    }
    if(total == 0) return KIND_CATALOG[0].id;
    uint32_t pick = rng_range(r, 0, total);
    uint32_t acc = 0;
    for(int i = 0; i < KIND_COUNT; i++) {
        if(!(KIND_CATALOG[i].flags & KF_PICKUPABLE)) continue;
        if(!(KIND_CATALOG[i].biomes & bbit)) continue;
        acc += KIND_CATALOG[i].weight;
        if(pick < acc) return KIND_CATALOG[i].id;
    }
    return KIND_CATALOG[KIND_COUNT - 1].id;
}

char loot_glyph(uint8_t kind_id) {
    const KindDef* k = kind_by_id(kind_id);
    return k ? k->glyph : '.';
}
