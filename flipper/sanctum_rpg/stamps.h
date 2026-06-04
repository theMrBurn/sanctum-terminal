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
 * IDs match pool.h conceptually: the Pool's primitive_bag carries IDs
 * from THIS table. The first 6 are cavern (0..5), next 6 are outdoor
 * (6..11). The composer + Pool only ever sample a biome-eligible slice.
 *
 * Glyph mapping (1-bit Flipper display):
 *   ST  '#' stelag (1×1 hard blocker)         — render = TILE_WALL
 *   C   '#' column                            — same glyph as ST; grammar distinguishes
 *   MC  'O' mega column (2×2 landmark)         — new glyph
 *   LST '#' large stelag (chamber-divider)    — same glyph as ST
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

#define PRIM_COUNT_CAVERN  6
#define PRIM_COUNT_OUTDOOR 6
#define PRIM_COUNT_TOTAL  12

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

/* Biome eligibility — each stamp belongs to one biome (cavern OR outdoor). */
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
    uint8_t  biome;          /* STAMP_BIOME_* */
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
int pick_stamp(Rng* rng, const Pool* pool, uint8_t biome);

/* Pool-biased rotation pick. Picks one valid rotation (0..3) for the stamp,
 * with a 2:1 weight skew toward `pool->rotation_bias` per §F1.4.b. */
uint8_t pick_rotation(Rng* rng, const StampDef* stamp, const Pool* pool);
