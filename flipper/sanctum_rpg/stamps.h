/*
 * stamps.h — terrain stamp catalog + primitive vocabulary (spec 50 §C + §F1).
 *
 * Slice 50.F1. Pure module — no Flipper SDK, host-testable. Per the engine
 * addendum §F1.7, the primitive vocabulary lives in this same translation
 * unit as a small static const table; a separate primitives.c isn't worth
 * the include-graph cost at 6+6 = 12 rows.
 *
 * Stamps are the building blocks the composer places in chunks. Each stamp:
 *   - a fixed bounding-box (w × h)
 *   - a list of primitive placements (primitive_id, dx, dy)
 *   - a rotation_mask (which of 4 rotations are valid)
 *   - rarity tier (common / uncommon / rare — gates distance/intensity)
 *   - biome (CAVERN or OUTDOOR — exclusive in v1)
 *
 * Primitives carry the rendering glyph + walkability + sight-blocking flags.
 * The composer reads the Pool to bias stamp selection (catalog re-weighting
 * by bag affinity, rotation bias on matching slot, intensity gating of
 * large/rare stamps).
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "pool.h"
#include "rng.h"

/* ─── Primitive vocabulary ──────────────────────────────────────────────
 * The first 6 are cavern (0..5), next 6 are outdoor (6..11), then the
 * styles' own. The Pool's primitive_bag is POSITIONAL: slot k biases the
 * k-th primitive of the stamp's style vocabulary (StyleDef.vocab), not
 * primitive id k. Cavern's vocabulary is {0..5}, so there slot = id.
 *
 * Glyph mapping (1-bit Flipper display):
 *   ST  'A' stalagmite (1×1 hard blocker)     — a PROP (was '#', WORLDGEN 3)
 *   C   '|' column                            — SLAB, fluted (was '#')
 *   MC  'O' mega column (2×2 landmark)         — new glyph
 *   LST 'M' large stelag (chamber-divider)    — SLAB, raw flowstone (was '#')
 *   MW  ',' moss (walkable soft)              — new glyph
 *   GC  'q' glowcap (walkable; +fuel hook)    — reserved slot resolved 2026-06-02
 *
 *   SS  'I' standing stone                    — new glyph
 *   CA  'Q' cairn (small landmark)            — new glyph
 *   MH  'H' menhir (2×2 large landmark)        — new glyph
 *   DF  '~' deadfall                          — new glyph
 *   SC  ';' scrub (walkable soft)             — new glyph
 *   SR  ':' scree (walkable but costly)       — new glyph */

#define PRIM_ST   0u
#define PRIM_C    1u
#define PRIM_MC   2u
#define PRIM_LST  3u
#define PRIM_MW   4u
#define PRIM_GC   5u  /* glowcap (reserved cavern #5; locked 2026-06-02) */

#define PRIM_SS   6u
#define PRIM_CA   7u
#define PRIM_MH   8u
#define PRIM_DF   9u
#define PRIM_SC  10u
#define PRIM_SR  11u

/* Crypt (style dungeon) */
#define PRIM_SA  12u  /* 'n' sarcophagus   — blocking */
#define PRIM_BP  13u  /* 'x' bone pile     — walkable, low */
#define PRIM_UR  14u  /* 'U' urn           — blocking */
#define PRIM_FS  15u  /* '/' flagstone     — floor mark */
/* Old mine */
#define PRIM_OC  16u  /* 'c' ore cart      — blocking */
#define PRIM_RB  17u  /* '^' rubble        — blocking */
#define PRIM_PO  18u  /* 'l' timber post   — blocking */
#define PRIM_RL  19u  /* '-' rails         — floor mark */
/* Forest */
#define PRIM_TR  20u  /* 'Y' tree          — blocking, blocks sight */
#define PRIM_DT  21u  /* 'y' dead tree     — blocking */
#define PRIM_SP  22u  /* 't' stump         — blocking, low */
#define PRIM_TG  23u  /* '`' tall grass    — walkable */

/* Manor / keep / abbey (above-ground interiors) */
#define PRIM_TB  24u  /* 'm' table         — blocking */
#define PRIM_BA  25u  /* 'd' barrel        — blocking */
#define PRIM_HE  26u  /* 'w' hearth        — blocking */
#define PRIM_RK  27u  /* 'k' weapon rack   — blocking */
#define PRIM_BZ  28u  /* 'v' brazier       — blocking */
#define PRIM_AL  29u  /* 'a' altar         — blocking */
#define PRIM_SU  30u  /* 'Z' statue        — blocking, blocks sight */
#define PRIM_PW  31u  /* 'p' pew           — blocking */
#define PRIM_PL  32u  /* '[' boards       — floor mark */

#define PRIM_COUNT_CAVERN  6
#define PRIM_COUNT_OUTDOOR 6
#define PRIM_COUNT_TOTAL  33

typedef struct {
    uint8_t id;
    char    glyph;
    uint8_t walkable;   /* 1 = walkable, 0 = blocking */
    uint8_t blocks_sight; /* 1 = blocks LOS / FOV     */
} PrimitiveDef;

extern const PrimitiveDef PRIMITIVES[PRIM_COUNT_TOTAL];

/* Look up a primitive by id. Returns NULL on oob. */
const PrimitiveDef* primitive_def(uint8_t id);

/* True if the glyph maps to a blocking primitive — used by world_is_blocking
 * to extend its blocking-tile vocabulary for the new spec 50 primitives. */
bool primitive_glyph_blocks(char glyph);

/* True if the glyph maps to a sight-blocking primitive — used by FOV. */
bool primitive_glyph_blocks_sight(char glyph);

/* ─── Stamps ───────────────────────────────────────────────────────── */

/* Stamp flags (rarity / gating). */
#define SF_COMMON   0u
#define SF_UNCOMMON 1u
#define SF_RARE     2u  /* distance-gated: skipped within RARE_SETPIECE_DIST */

/* Style eligibility — each stamp belongs to one style (style.h). The first
 * two styles are the original biomes, so their ids are unchanged. The
 * STAMP_BIOME_* names remain the Pool / weather / narrative ids (biome_pool). */
#define STAMP_STYLE_CAVERN  0u
#define STAMP_STYLE_MOOR    1u
#define STAMP_STYLE_CRYPT   2u
#define STAMP_STYLE_MINE    3u
#define STAMP_STYLE_FOREST  4u
#define STAMP_STYLE_MANOR   5u
#define STAMP_STYLE_KEEP    6u
#define STAMP_STYLE_ABBEY   7u
#define STAMP_BIOME_CAVERN  0u
#define STAMP_BIOME_OUTDOOR 1u

/* Maximum primitives any single stamp places. 9 covers the largest catalog
 * entry (3×3 pillar grove with 5 primitives). */
#define STAMP_MAX_PRIMS 6

typedef struct {
    uint8_t prim_id;  /* PRIM_* */
    uint8_t dx;       /* offset within stamp bounding box */
    uint8_t dy;
} StampPrimitive;

typedef struct {
    uint8_t  id;
    uint8_t  style;          /* Style (style.h) this stamp belongs to */
    uint8_t  width;
    uint8_t  height;
    uint8_t  rarity;         /* SF_* */
    uint8_t  rotation_mask;  /* bit-per-rotation: bit 0 = 0°, bit 1 = 90°, ... */
    uint8_t  prim_count;
    StampPrimitive prims[STAMP_MAX_PRIMS];
} StampDef;

extern const StampDef STAMPS[];
extern const int STAMP_COUNT;

/* Big-stamp intensity gate (per engine addendum §F1.1). A 3×3 stamp is
 * eligible only if pool->intensity >= this threshold. */
#define BIG_STAMP_INTENSITY_GATE 64u

/* Rare-stamp distance gate (per grammar §L.3 Lock 2). A SF_RARE stamp
 * requires pool->intensity >= this threshold. */
#define RARE_SETPIECE_INTENSITY_GATE 32u

/* Pool-biased stamp pick. Walks the eligible catalog (biome + size gate +
 * rarity gate) and returns one stamp_id, weighted by the Pool's
 * primitive_bag (catalog re-weighting per engine addendum §F1.4.a).
 * Returns -1 if no stamp is eligible. */
int pick_stamp(Rng* rng, const Pool* pool, uint8_t style);

/* Pool-biased rotation pick. Picks one valid rotation (0..3) for the stamp,
 * with a 2:1 weight skew toward `pool->rotation_bias` per §F1.4.b. */
uint8_t pick_rotation(Rng* rng, const StampDef* stamp, const Pool* pool);
