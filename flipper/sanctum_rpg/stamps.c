/*
 * stamps.c — see stamps.h. Catalog + pick logic for spec 50 §F1.
 *
 * The catalog tables are EXACTLY as locked in spec 50 grammar addendum
 * §F1.C.3 (cavern) and §F1.C.4 (outdoor). Adding a new stamp = one new
 * row. "Never if stamp_id ==" rule per spec 43 §14.0.
 */

#include "stamps.h"

#include <stddef.h>

/* ─── Primitive vocabulary table ────────────────────────────────────── */

const PrimitiveDef PRIMITIVES[PRIM_COUNT_TOTAL] = {
    /* id      glyph walk sight-block */
    {PRIM_ST,  '#',  0,   1},
    {PRIM_C,   '#',  0,   1},
    {PRIM_MC,  'O',  0,   1},
    {PRIM_LST, '#',  0,   1},
    {PRIM_MW,  ',',  1,   0},
    {PRIM_GC,  'q',  1,   0},
    {PRIM_SS,  'I',  0,   1},
    {PRIM_CA,  'Q',  0,   1},
    {PRIM_MH,  'H',  0,   1},
    {PRIM_DF,  '~',  0,   1},
    {PRIM_SC,  ';',  1,   0},
    {PRIM_SR,  ':',  1,   0},
};

const PrimitiveDef* primitive_def(uint8_t id) {
    if(id >= PRIM_COUNT_TOTAL) return NULL;
    return &PRIMITIVES[id];
}

bool primitive_glyph_blocks(char glyph) {
    for(int i = 0; i < PRIM_COUNT_TOTAL; i++) {
        if(PRIMITIVES[i].glyph == glyph) return !PRIMITIVES[i].walkable;
    }
    return false;
}

bool primitive_glyph_blocks_sight(char glyph) {
    for(int i = 0; i < PRIM_COUNT_TOTAL; i++) {
        if(PRIMITIVES[i].glyph == glyph) return PRIMITIVES[i].blocks_sight != 0;
    }
    return false;
}

/* ─── Stamp catalog (locked in spec 50 §F1.C.3 + §F1.C.4) ─────────────
 * 10 cavern stamps + 10 outdoor stamps. Per §F1.C.3 notes:
 *   rotation_mask 0b0001 = only 0° legal (content-meaningful orientation)
 *   rotation_mask 0b0011 = 0° + 180° (linear / horizontal stamps)
 *   rotation_mask 0b1111 = all 4 rotations legal */

#define R_NONE  0b0001u
#define R_FLIP  0b0011u
#define R_ALL   0b1111u

const StampDef STAMPS[] = {
    /* ─── CAVERN (ids 0-9) ───────────────────────────────────────── */
    /* id=0 — two pillars (Pinch) */
    {0, STAMP_BIOME_CAVERN, 3, 1, SF_COMMON, R_FLIP, 2,
     {{PRIM_C, 0, 0}, {PRIM_C, 2, 0}, {0,0,0},{0,0,0},{0,0,0},{0,0,0}}},
    /* id=1 — stelag row (Pinch) */
    {1, STAMP_BIOME_CAVERN, 3, 1, SF_COMMON, R_FLIP, 3,
     {{PRIM_ST, 0, 0}, {PRIM_ST, 1, 0}, {PRIM_ST, 2, 0}, {0,0,0},{0,0,0},{0,0,0}}},
    /* id=2 — moss nook (Pocket) */
    {2, STAMP_BIOME_CAVERN, 2, 2, SF_COMMON, R_ALL, 3,
     {{PRIM_C, 0, 0}, {PRIM_MW, 0, 1}, {PRIM_MW, 1, 1}, {0,0,0},{0,0,0},{0,0,0}}},
    /* id=3 — pillar grove (Pocket) — 3×3, intensity-gated */
    {3, STAMP_BIOME_CAVERN, 3, 3, SF_UNCOMMON, R_ALL, 5,
     {{PRIM_MC, 0, 0}, {PRIM_MC, 1, 0}, {PRIM_MC, 0, 1}, {PRIM_MC, 1, 1},
      {PRIM_MW, 2, 2}, {0,0,0}}},
    /* id=4 — hall pillar (Sprawl) */
    {4, STAMP_BIOME_CAVERN, 2, 2, SF_UNCOMMON, R_NONE, 4,
     {{PRIM_MC, 0, 0}, {PRIM_MC, 1, 0}, {PRIM_MC, 0, 1}, {PRIM_MC, 1, 1},
      {0,0,0},{0,0,0}}},
    /* id=5 — pillar with view (Lookout) */
    {5, STAMP_BIOME_CAVERN, 2, 2, SF_UNCOMMON, R_ALL, 4,
     {{PRIM_MC, 0, 0}, {PRIM_MC, 1, 0}, {PRIM_MC, 0, 1}, {PRIM_MC, 1, 1},
      {0,0,0},{0,0,0}}},
    /* id=6 — low ridge (Lookout) */
    {6, STAMP_BIOME_CAVERN, 2, 1, SF_COMMON, R_ALL, 2,
     {{PRIM_LST, 0, 0}, {PRIM_LST, 1, 0}, {0,0,0},{0,0,0},{0,0,0},{0,0,0}}},
    /* id=7 — broken ridge (Thicket) — 3×2 */
    {7, STAMP_BIOME_CAVERN, 3, 2, SF_UNCOMMON, R_ALL, 3,
     {{PRIM_LST, 0, 0}, {PRIM_LST, 1, 0}, {PRIM_ST, 2, 1}, {0,0,0},{0,0,0},{0,0,0}}},
    /* id=8 — stelag bend (Thicket) — L-bend */
    {8, STAMP_BIOME_CAVERN, 2, 2, SF_UNCOMMON, R_ALL, 3,
     {{PRIM_LST, 0, 0}, {PRIM_LST, 1, 0}, {PRIM_ST, 0, 1}, {0,0,0},{0,0,0},{0,0,0}}},
    /* id=9 — moss carpet (Threshold) — 2×2 walkable */
    {9, STAMP_BIOME_CAVERN, 2, 2, SF_COMMON, R_NONE, 4,
     {{PRIM_MW, 0, 0}, {PRIM_MW, 1, 0}, {PRIM_MW, 0, 1}, {PRIM_MW, 1, 1},
      {0,0,0},{0,0,0}}},

    /* ─── OUTDOOR (ids 10-19) ────────────────────────────────────── */
    /* id=10 — two stones (Pinch) */
    {10, STAMP_BIOME_OUTDOOR, 3, 1, SF_COMMON, R_FLIP, 2,
     {{PRIM_SS, 0, 0}, {PRIM_SS, 2, 0}, {0,0,0},{0,0,0},{0,0,0},{0,0,0}}},
    /* id=11 — scrub hollow (Pocket) */
    {11, STAMP_BIOME_OUTDOOR, 2, 2, SF_COMMON, R_ALL, 3,
     {{PRIM_SS, 0, 0}, {PRIM_SC, 0, 1}, {PRIM_SC, 1, 1}, {0,0,0},{0,0,0},{0,0,0}}},
    /* id=12 — cairn at rest (Pocket) */
    {12, STAMP_BIOME_OUTDOOR, 2, 2, SF_COMMON, R_ALL, 4,
     {{PRIM_CA, 0, 0}, {PRIM_SC, 1, 0}, {PRIM_SC, 0, 1}, {PRIM_SC, 1, 1},
      {0,0,0},{0,0,0}}},
    /* id=13 — lone stone (Sprawl) — 1×1 */
    {13, STAMP_BIOME_OUTDOOR, 1, 1, SF_COMMON, R_NONE, 1,
     {{PRIM_SS, 0, 0}, {0,0,0},{0,0,0},{0,0,0},{0,0,0},{0,0,0}}},
    /* id=14 — the menhir (Sprawl) — SF_RARE distance-gated */
    {14, STAMP_BIOME_OUTDOOR, 2, 2, SF_RARE, R_NONE, 4,
     {{PRIM_MH, 0, 0}, {PRIM_MH, 1, 0}, {PRIM_MH, 0, 1}, {PRIM_MH, 1, 1},
      {0,0,0},{0,0,0}}},
    /* id=15 — cairn watch (Lookout) */
    {15, STAMP_BIOME_OUTDOOR, 2, 2, SF_COMMON, R_ALL, 2,
     {{PRIM_CA, 0, 0}, {PRIM_SR, 1, 1}, {0,0,0},{0,0,0},{0,0,0},{0,0,0}}},
    /* id=16 — wayfinders (Lookout) — line of cairns */
    {16, STAMP_BIOME_OUTDOOR, 3, 1, SF_UNCOMMON, R_FLIP, 2,
     {{PRIM_CA, 0, 0}, {PRIM_CA, 2, 0}, {0,0,0},{0,0,0},{0,0,0},{0,0,0}}},
    /* id=17 — deadfall (Thicket) */
    {17, STAMP_BIOME_OUTDOOR, 2, 1, SF_UNCOMMON, R_ALL, 2,
     {{PRIM_DF, 0, 0}, {PRIM_DF, 1, 0}, {0,0,0},{0,0,0},{0,0,0},{0,0,0}}},
    /* id=18 — scree patch (Threshold) */
    {18, STAMP_BIOME_OUTDOOR, 2, 2, SF_COMMON, R_NONE, 4,
     {{PRIM_SR, 0, 0}, {PRIM_SR, 1, 0}, {PRIM_SR, 0, 1}, {PRIM_SR, 1, 1},
      {0,0,0},{0,0,0}}},
    /* id=19 — scrub field (Threshold) */
    {19, STAMP_BIOME_OUTDOOR, 2, 2, SF_COMMON, R_NONE, 4,
     {{PRIM_SC, 0, 0}, {PRIM_SC, 1, 0}, {PRIM_SC, 0, 1}, {PRIM_SC, 1, 1},
      {0,0,0},{0,0,0}}},
};

const int STAMP_COUNT = (int)(sizeof(STAMPS) / sizeof(STAMPS[0]));

/* ─── Pool-biased stamp pick (engine addendum §F1.4.a) ──────────────── */

/* Rarity → base weight. Common = 100, uncommon = 40, rare = 10. */
static uint32_t stamp_base_weight(const StampDef* s) {
    switch(s->rarity) {
    case SF_COMMON:   return 100u;
    case SF_UNCOMMON: return  40u;
    case SF_RARE:     return  10u;
    default:          return   0u;
    }
}

/* Bag affinity: sum of pool bag weights for primitives this stamp uses.
 * Range 0..(sum of all bag weights, typically 8..120). */
static uint32_t stamp_bag_affinity(const StampDef* s, const Pool* pool) {
    if(!s || !pool) return 0u;
    uint32_t sum = 0;
    for(uint8_t pi = 0; pi < s->prim_count; pi++) {
        uint8_t target = s->prims[pi].prim_id;
        for(int slot = 0; slot < POOL_BAG_SLOTS; slot++) {
            if(pool->primitive_bag[slot][0] == target) {
                sum += pool->primitive_bag[slot][1];
                break;
            }
        }
    }
    return sum;
}

int pick_stamp(Rng* rng, const Pool* pool, uint8_t biome) {
    if(!rng || !pool) return -1;

    /* Single accumulator walk; same idiom as loot_roll. */
    uint32_t weights[64]; /* STAMP_COUNT <= 20 in v1; comfortable. */
    int eligible[64];
    int n_elig = 0;
    uint32_t total = 0;

    for(int i = 0; i < STAMP_COUNT; i++) {
        const StampDef* s = &STAMPS[i];
        if(s->biome != biome) continue;
        /* Intensity gate for big stamps (§F1.1) — 3×3 only at intensity ≥ 64. */
        if(s->width >= 3 && s->height >= 3 &&
           pool->intensity < BIG_STAMP_INTENSITY_GATE) continue;
        /* Rare-stamp distance gate (§L.3 Lock 2 — gated by intensity here). */
        if(s->rarity == SF_RARE &&
           pool->intensity < RARE_SETPIECE_INTENSITY_GATE) continue;

        uint32_t base = stamp_base_weight(s);
        uint32_t affinity = stamp_bag_affinity(s, pool);
        /* engine addendum §F1.4.a: weight = base * (8 + affinity) / 8.
         * Affinity = 0 → no bias. Affinity = 56 (max) → 8× bias. */
        if(affinity > 56u) affinity = 56u;
        uint32_t w = base * (8u + affinity) / 8u;
        if(w == 0) continue;

        eligible[n_elig] = i;
        weights[n_elig] = w;
        total += w;
        n_elig++;
    }

    if(n_elig == 0 || total == 0) return -1;

    uint32_t pick = rng_range(rng, 0, total);
    uint32_t acc = 0;
    for(int j = 0; j < n_elig; j++) {
        acc += weights[j];
        if(pick < acc) return eligible[j];
    }
    return eligible[n_elig - 1];
}

/* ─── Pool-biased rotation pick (engine addendum §F1.4.b) ────────────── */

uint8_t pick_rotation(Rng* rng, const StampDef* stamp, const Pool* pool) {
    if(!rng || !stamp || !pool) return 0;
    /* Build eligible rotations from rotation_mask. */
    uint8_t legal[4];
    int n_legal = 0;
    for(int r = 0; r < 4; r++) {
        if(stamp->rotation_mask & (1u << r)) {
            legal[n_legal++] = (uint8_t)r;
        }
    }
    if(n_legal == 0) return 0;
    if(n_legal == 1) return legal[0];

    /* Apply 2:1 weight skew toward the rotation matching pool->rotation_bias. */
    uint32_t weights[4];
    uint32_t total = 0;
    uint8_t match = (uint8_t)(pool->rotation_bias & 3u);
    for(int j = 0; j < n_legal; j++) {
        weights[j] = (legal[j] == match) ? 2u : 1u;
        total += weights[j];
    }
    uint32_t pick = rng_range(rng, 0, total);
    uint32_t acc = 0;
    for(int j = 0; j < n_legal; j++) {
        acc += weights[j];
        if(pick < acc) return legal[j];
    }
    return legal[n_legal - 1];
}
