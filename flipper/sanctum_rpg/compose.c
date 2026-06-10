/*
 * compose.c — see compose.h. Spec 50 §R corner-snap stamp composer.
 *
 * Per-chunk stamp composition by CORNER-SNAP FRONTIER POPPING (spec 50
 * §R.2). A central floor "prime" seeds a frontier of anchor corners;
 * Pool-biased stamps are popped onto those anchors and grow OUTWARD from
 * the chunk center, each placed stamp pushing its own corners back onto
 * the frontier. This realizes the user's north-star drawing — "Example
 * map stamp progression if out from center" (§R.0).
 *
 * Replaces the slice-50.F1 random-placement v1 (which scattered stamps in
 * the interior). Selection is UNCHANGED: pick_stamp (Pool-biased catalog
 * re-weighting, §F1.4.a) and pick_rotation (rotation_bias skew, §F1.4.b)
 * in stamps.c are reused verbatim. Only the PLACEMENT strategy changes.
 *
 * Integration contract (unchanged): the biome owns the chunk edge (border
 * + mid-edge doors for cavern; bare outer ring for outdoor) and pre-places
 * the vendor before this call. The composer only writes interior FLOOR
 * tiles and never overwrites a non-floor tile. world.c runs find_spawn +
 * carve_egress AFTER this, so connectivity is guaranteed downstream — the
 * composer does not reason about reachability.
 *
 * Pure module. Integer-only. Byte-equal across hardware: every rng draw is
 * a deterministic function of (seed, chunk_x, chunk_y) via the caller's Rng.
 */

#include "compose.h"

#include <stdbool.h>
#include <string.h>

#include "stamps.h"

/* Inset from the chunk edges where stamps may not enter. Cavern needs
 * row 0/N-1 + col 0/N-1 as wall/door; outdoor keeps the outer ring bare
 * floor for edge traversal. So inset = 1 in both biomes. */
#define COMPOSE_INSET 1

/* Stamps placed per chunk before the budget is spent (spec 50 §R.3). The
 * frontier may run dry first on a small/crowded chunk; that's fine. */
#define STAMP_BUDGET_PER_CHUNK 4

/* Per-anchor placement retries before the anchor is discarded (spec 50
 * §R.1.2, NetHack-style bounded retry). A popped anchor that fails to fit
 * is re-pushed up to this many times, then dropped. */
#define FIT_RETRY_MAX 2

/* The central prime: a floor footprint at the chunk center whose four
 * corners seed the frontier (spec 50 §R.2.3). Applied UNIFORMLY to every
 * chunk — this engine generates each chunk purely from (seed, cx, cy) with
 * no entry direction (a chunk must be byte-equal regardless of which door
 * the player entered, spec 43 §14.0), so §R.2.3's entry-tile-prime variant
 * is incompatible as built; the first-chunk center rule is used always.
 * The prime is hard-coded floor: the interior is already floor, so the
 * prime is not written — only reserved in the occupancy mask so stamps
 * never bury the spawn. */
#define PRIME_W 3
#define PRIME_H 2

/* Frontier ring capacity (spec 50 §R.2.1). Budget caps real growth far
 * below this; push silently drops on overflow. */
#define FRONTIER_MAX 32

/* ─── Corner-snap data shapes (spec 50 §R.2.1) ─────────────────────────── */

/* Which corner of a stamp's bounding box registers against an anchor.
 * Encoded so the (x_min,y_min) solve in place_for_anchor is a clean switch. */
typedef enum { CORNER_NW = 0, CORNER_NE, CORNER_SW, CORNER_SE } CornerDir;

typedef struct {
    uint8_t x, y;     /* anchor tile */
    uint8_t corner;   /* CornerDir — which stamp corner snaps here */
    uint8_t retry;    /* fit-retries spent on this anchor so far */
} FrontierAnchor;

typedef struct {
    FrontierAnchor entries[FRONTIER_MAX];
    uint8_t count;
} Frontier;

/* Occupancy mask — 96 bits flat (WORLD_COLS * WORLD_ROWS = 16 * 6 = 96).
 * bit (y * WORLD_COLS + x). Cheap O(1) box-overlap test. */
typedef struct {
    uint32_t bits[3];
} OccupancyMask;

static void occ_set(OccupancyMask* m, int x, int y) {
    int b = y * WORLD_COLS + x;
    m->bits[b >> 5] |= (uint32_t)1u << (b & 31);
}

static bool occ_test(const OccupancyMask* m, int x, int y) {
    int b = y * WORLD_COLS + x;
    return (m->bits[b >> 5] >> (b & 31)) & 1u;
}

/* ─── Rotation geometry (spec 50 §R.4.1 — unchanged from v1) ────────────── */

/* Rotate a stamp's (dx, dy) by 90° steps around the stamp's bounding box
 * origin. Result offsets are within the ROTATED dimensions. */
static void rotate_offset(uint8_t w, uint8_t h, uint8_t rot,
                          uint8_t dx, uint8_t dy,
                          uint8_t* rx, uint8_t* ry) {
    switch(rot & 3u) {
    default:
    case 0: *rx = dx;                     *ry = dy;                     break;
    case 1: *rx = (uint8_t)(h - 1u - dy); *ry = dx;                     break;
    case 2: *rx = (uint8_t)(w - 1u - dx); *ry = (uint8_t)(h - 1u - dy); break;
    case 3: *rx = dy;                     *ry = (uint8_t)(w - 1u - dx); break;
    }
}

/* Effective (rotated) bounding-box dimensions. */
static void rotated_dims(uint8_t w, uint8_t h, uint8_t rot,
                         uint8_t* ew, uint8_t* eh) {
    if((rot & 1u) == 0u) { *ew = w; *eh = h; }
    else                 { *ew = h; *eh = w; }
}

/* ─── Corner-snap math pair (spec 50 §R.2.1 / §R.2.2) ───────────────────
 * box_corner() and place_for_anchor() are INVERSES: snapping corner C of a
 * box to a tile, then asking for corner C of the resulting box, returns the
 * same tile. test_compose_corner_roundtrip pins this (AGENTS.md coord-pair
 * rule — two silent coordinate bugs shipped before this rule existed). */

/* Tile coordinate of a box's corner C, given the box's NW origin + dims. */
static void box_corner(int x_min, int y_min, uint8_t ew, uint8_t eh,
                       uint8_t corner, int* cx, int* cy) {
    int x_max = x_min + (int)ew - 1;
    int y_max = y_min + (int)eh - 1;
    switch(corner) {
    default:
    case CORNER_NW: *cx = x_min; *cy = y_min; break;
    case CORNER_NE: *cx = x_max; *cy = y_min; break;
    case CORNER_SW: *cx = x_min; *cy = y_max; break;
    case CORNER_SE: *cx = x_max; *cy = y_max; break;
    }
}

/* NW origin (x_min, y_min) such that the box's corner C lands on (ax, ay). */
static void place_for_anchor(const FrontierAnchor* a, uint8_t ew, uint8_t eh,
                             int* x_min, int* y_min) {
    int ax = (int)a->x, ay = (int)a->y;
    switch(a->corner) {
    default:
    case CORNER_NW: *x_min = ax;                  *y_min = ay;                  break;
    case CORNER_NE: *x_min = ax - ((int)ew - 1);  *y_min = ay;                  break;
    case CORNER_SW: *x_min = ax;                  *y_min = ay - ((int)eh - 1);  break;
    case CORNER_SE: *x_min = ax - ((int)ew - 1);  *y_min = ay - ((int)eh - 1);  break;
    }
}

/* ─── Frontier ring ─────────────────────────────────────────────────────── */

static void frontier_push(Frontier* f, uint8_t x, uint8_t y, uint8_t corner,
                          uint8_t retry) {
    if(f->count >= FRONTIER_MAX) return; /* silently drop (§R.2.2) */
    f->entries[f->count].x = x;
    f->entries[f->count].y = y;
    f->entries[f->count].corner = corner;
    f->entries[f->count].retry = retry;
    f->count++;
}

/* Pop a frontier entry by value, swapping it with the tail (spec 50 §R.2.6).
 * Index = rng_range(0, count) so pop order is a deterministic function of
 * the chunk's RNG stream → byte-equal placement on Flipper and PC port. */
static FrontierAnchor frontier_pop(Frontier* f, Rng* rng) {
    uint8_t i = (uint8_t)rng_range(rng, 0, f->count);
    FrontierAnchor out = f->entries[i];
    f->count--;
    f->entries[i] = f->entries[f->count]; /* swap-with-tail */
    return out;
}

/* ─── Placement primitives ──────────────────────────────────────────────── */

/* Test whether a stamp at NW origin (x_min, y_min) with rotated dims (ew, eh)
 * fits: its box stays inside the interior inset box, and overlaps no occupied
 * tile EXCEPT the single shared anchor tile (corner-tiling, §R.2.5). */
static bool try_place(int x_min, int y_min, uint8_t ew, uint8_t eh,
                      int anchor_x, int anchor_y, const OccupancyMask* occ) {
    if(x_min < COMPOSE_INSET || y_min < COMPOSE_INSET) return false;
    if(x_min + (int)ew > WORLD_COLS - COMPOSE_INSET) return false;
    if(y_min + (int)eh > WORLD_ROWS - COMPOSE_INSET) return false;

    for(int y = y_min; y < y_min + (int)eh; y++) {
        for(int x = x_min; x < x_min + (int)ew; x++) {
            if(x == anchor_x && y == anchor_y) continue; /* shared snap tile */
            if(occ_test(occ, x, y)) return false;
        }
    }
    return true;
}

/* Mark a placed stamp's whole bounding box occupied. */
static void occ_commit_box(OccupancyMask* occ, int x_min, int y_min,
                           uint8_t ew, uint8_t eh) {
    for(int y = y_min; y < y_min + (int)eh; y++) {
        for(int x = x_min; x < x_min + (int)ew; x++) {
            occ_set(occ, x, y);
        }
    }
}

/* Write the stamp's primitives into the chunk at NW origin (x_min, y_min)
 * with rotation. Writes a glyph only onto bare FLOOR — preserves the door /
 * vendor protection invariant (the composer never overwrites non-floor). */
static void blit_stamp(const StampDef* s, uint8_t rot, int x_min, int y_min,
                       World* w) {
    for(uint8_t pi = 0; pi < s->prim_count; pi++) {
        uint8_t rx, ry;
        rotate_offset(s->width, s->height, rot,
                      s->prims[pi].dx, s->prims[pi].dy, &rx, &ry);
        const PrimitiveDef* p = primitive_def(s->prims[pi].prim_id);
        if(!p) continue;
        int tx = x_min + (int)rx;
        int ty = y_min + (int)ry;
        if(tx < 0 || tx >= WORLD_COLS || ty < 0 || ty >= WORLD_ROWS) continue;
        if(w->tiles[ty][tx] != TILE_FLOOR) continue;
        w->tiles[ty][tx] = p->glyph;
    }
}

/* Push the three NON-snap corners of a just-placed stamp onto the frontier,
 * each carrying the SAME corner direction as the snap corner. Keeping the
 * direction constant per branch makes each cluster grow in one consistent
 * outward sense — the radial "out from center" progression (§R.0). Out-of-
 * interior corners are kept; try_place rejects them later if nothing fits. */
static void add_new_corners(Frontier* f, int x_min, int y_min,
                            uint8_t ew, uint8_t eh, uint8_t snap_corner) {
    for(uint8_t c = 0; c < 4; c++) {
        if(c == snap_corner) continue;
        int cx, cy;
        box_corner(x_min, y_min, ew, eh, c, &cx, &cy);
        if(cx < 0 || cx >= WORLD_COLS || cy < 0 || cy >= WORLD_ROWS) continue;
        frontier_push(f, (uint8_t)cx, (uint8_t)cy, snap_corner, 0);
    }
}

/* ─── Composer entry point ──────────────────────────────────────────────── */

void compose_stamps_into_interior(Rng* rng, const Pool* pool,
                                  uint8_t biome, World* out) {
    if(!rng || !pool || !out) return;

    /* 1. Seed occupancy from existing non-floor interior tiles (e.g. a
     *    pre-placed vendor) so stamps never bury them. Border tiles are
     *    outside the inset box and never considered. */
    OccupancyMask occ;
    memset(&occ, 0, sizeof(occ));
    for(int y = COMPOSE_INSET; y < WORLD_ROWS - COMPOSE_INSET; y++) {
        for(int x = COMPOSE_INSET; x < WORLD_COLS - COMPOSE_INSET; x++) {
            if(out->tiles[y][x] != TILE_FLOOR) occ_set(&occ, x, y);
        }
    }

    /* 2. Reserve the central prime box in occupancy (it stays bare floor —
     *    it is the spawn safe-area) and seed the frontier from its four
     *    corners. Each seed's corner direction is the OPPOSITE compass of
     *    the prime corner it sits on, so the first stamp on each branch
     *    grows away from center (NW prime corner → SE-snap → grows up-left,
     *    and so on). */
    int prime_x0 = WORLD_COLS / 2 - PRIME_W / 2;
    int prime_y0 = WORLD_ROWS / 2 - PRIME_H / 2;
    occ_commit_box(&occ, prime_x0, prime_y0, PRIME_W, PRIME_H);

    int px1 = prime_x0 + PRIME_W - 1;
    int py1 = prime_y0 + PRIME_H - 1;
    Frontier frontier;
    frontier.count = 0;
    frontier_push(&frontier, (uint8_t)prime_x0, (uint8_t)prime_y0, CORNER_SE, 0);
    frontier_push(&frontier, (uint8_t)px1,      (uint8_t)prime_y0, CORNER_SW, 0);
    frontier_push(&frontier, (uint8_t)prime_x0, (uint8_t)py1,      CORNER_NE, 0);
    frontier_push(&frontier, (uint8_t)px1,      (uint8_t)py1,      CORNER_NW, 0);

    /* 3. Bounded corner-snap placement loop (§R.2.2). */
    int budget = STAMP_BUDGET_PER_CHUNK;
    while(budget > 0 && frontier.count > 0) {
        FrontierAnchor anchor = frontier_pop(&frontier, rng);

        int stamp_id = pick_stamp(rng, pool, biome);
        if(stamp_id < 0) break; /* no eligible stamp this chunk — done */
        const StampDef* s = &STAMPS[stamp_id];
        uint8_t rot = pick_rotation(rng, s, pool);

        uint8_t ew, eh;
        rotated_dims(s->width, s->height, rot, &ew, &eh);

        int x_min, y_min;
        place_for_anchor(&anchor, ew, eh, &x_min, &y_min);

        if(try_place(x_min, y_min, ew, eh, anchor.x, anchor.y, &occ)) {
            blit_stamp(s, rot, x_min, y_min, out);
            occ_commit_box(&occ, x_min, y_min, ew, eh);
            add_new_corners(&frontier, x_min, y_min, ew, eh, anchor.corner);
            budget--;
        } else if(anchor.retry + 1 < FIT_RETRY_MAX) {
            frontier_push(&frontier, anchor.x, anchor.y, anchor.corner,
                          (uint8_t)(anchor.retry + 1));
        }
        /* else: anchor exhausted its retries — discarded. */
    }
}

#ifdef SANCTUM_RPG_HOST_TEST
bool compose_selftest_corner_roundtrip(void) {
    /* Snap each corner of every valid-size box to a tile, then read that
     * corner back off the resulting box — must return the original tile. */
    for(uint8_t corner = 0; corner < 4; corner++) {
        for(uint8_t ew = 1; ew <= 8; ew++) {
            for(uint8_t eh = 1; eh <= 6; eh++) {
                /* A few representative anchor tiles inside the interior. */
                const uint8_t axs[] = {1, 7, 8, 14};
                const uint8_t ays[] = {1, 2, 3, 4};
                for(unsigned ai = 0; ai < 4; ai++) {
                    FrontierAnchor a = {axs[ai], ays[ai], corner, 0};
                    int x_min, y_min, cx, cy;
                    place_for_anchor(&a, ew, eh, &x_min, &y_min);
                    box_corner(x_min, y_min, ew, eh, corner, &cx, &cy);
                    if(cx != (int)a.x || cy != (int)a.y) return false;
                }
            }
        }
    }
    return true;
}
#endif
