/*
 * compose.c — see compose.h. Spec 50 §F1.7 implementation.
 *
 * Per-chunk stamp composition. Reads the Pool, walks the stamps catalog,
 * places N = 2 + (rng % 3) stamps in the interior with bounded retry.
 *
 * v1 simplification: random-position placement instead of frontier corner
 * pop. The Pool's drift is the main source of inter-chunk variation;
 * placement randomness within a chunk produces enough intra-chunk variety
 * for the felt experience. Engine addendum §F1.2's frontier swap-with-tail
 * is the v1.1 refinement target.
 */

#include "compose.h"

#include <stdbool.h>
#include <string.h>

#include "stamps.h"

/* Inset from the chunk edges where stamps may not enter. Cavern needs
 * row 0/N-1 + col 0/N-1 as wall; outdoor needs the same as door/edge
 * room. So inset = 1 in both biomes. */
#define COMPOSE_INSET 1

/* Per-chunk stamp budget (spec 50 §F1.3). Actual N = COMPOSE_MIN +
 * rng_range(0, COMPOSE_RANGE) → 2..4. */
#define COMPOSE_MIN   2
#define COMPOSE_RANGE 3 /* exclusive — yields 0..2, adds to MIN to give 2..4 */

/* Per-stamp placement retry budget. Each stamp gets this many attempts
 * to find a valid (position, fits, no overlap). If all fail, we skip
 * that stamp and move on — the chunk just has fewer stamps. */
#define COMPOSE_RETRY 8

/* Rotate a stamp's (dx, dy) by 90° steps around the stamp's bounding box
 * origin. The resulting offsets are within the ROTATED dimensions. */
static void rotate_offset(uint8_t w, uint8_t h, uint8_t rot,
                          uint8_t dx, uint8_t dy,
                          uint8_t* rx, uint8_t* ry) {
    switch(rot & 3u) {
    default:
    case 0: *rx = dx;             *ry = dy;             break;
    case 1: *rx = (uint8_t)(h - 1u - dy); *ry = dx;     break;
    case 2: *rx = (uint8_t)(w - 1u - dx); *ry = (uint8_t)(h - 1u - dy); break;
    case 3: *rx = dy;             *ry = (uint8_t)(w - 1u - dx); break;
    }
}

/* Effective (rotated) dimensions. */
static void rotated_dims(uint8_t w, uint8_t h, uint8_t rot,
                         uint8_t* ew, uint8_t* eh) {
    if((rot & 1u) == 0u) { *ew = w; *eh = h; }
    else                 { *ew = h; *eh = w; }
}

/* Check whether placing this stamp at (px, py) with rotation `rot` would
 * land entirely within the interior box AND not overlap any non-floor tile.
 * Returns true if the placement is valid. */
static bool can_place(const StampDef* s, uint8_t rot, int px, int py,
                      const World* w) {
    uint8_t ew, eh;
    rotated_dims(s->width, s->height, rot, &ew, &eh);
    if(px < COMPOSE_INSET || py < COMPOSE_INSET) return false;
    if(px + ew > WORLD_COLS - COMPOSE_INSET) return false;
    if(py + eh > WORLD_ROWS - COMPOSE_INSET) return false;

    for(uint8_t pi = 0; pi < s->prim_count; pi++) {
        uint8_t rx, ry;
        rotate_offset(s->width, s->height, rot,
                      s->prims[pi].dx, s->prims[pi].dy, &rx, &ry);
        int tx = px + (int)rx;
        int ty = py + (int)ry;
        if(tx < 0 || tx >= WORLD_COLS || ty < 0 || ty >= WORLD_ROWS) {
            return false;
        }
        /* Refuse to overwrite anything that isn't bare floor. This protects
         * doors (written before compose) + previously-placed stamp tiles. */
        if(w->tiles[ty][tx] != TILE_FLOOR) return false;
    }
    return true;
}

/* Place the stamp's primitives into the chunk at (px, py) with rotation. */
static void blit_stamp(const StampDef* s, uint8_t rot, int px, int py,
                       World* w) {
    for(uint8_t pi = 0; pi < s->prim_count; pi++) {
        uint8_t rx, ry;
        rotate_offset(s->width, s->height, rot,
                      s->prims[pi].dx, s->prims[pi].dy, &rx, &ry);
        const PrimitiveDef* p = primitive_def(s->prims[pi].prim_id);
        if(!p) continue;
        int tx = px + (int)rx;
        int ty = py + (int)ry;
        if(tx < 0 || tx >= WORLD_COLS || ty < 0 || ty >= WORLD_ROWS) continue;
        w->tiles[ty][tx] = p->glyph;
    }
}

void compose_stamps_into_interior(Rng* rng, const Pool* pool,
                                  uint8_t biome, World* out) {
    if(!rng || !pool || !out) return;

    int target = COMPOSE_MIN + (int)rng_range(rng, 0, COMPOSE_RANGE);
    int placed = 0;

    for(int s_idx = 0; s_idx < target; s_idx++) {
        bool placed_this = false;
        for(int attempt = 0; attempt < COMPOSE_RETRY && !placed_this; attempt++) {
            int stamp_id = pick_stamp(rng, pool, biome);
            if(stamp_id < 0) break;
            const StampDef* s = &STAMPS[stamp_id];
            uint8_t rot = pick_rotation(rng, s, pool);

            uint8_t ew, eh;
            rotated_dims(s->width, s->height, rot, &ew, &eh);
            int max_x = (int)(WORLD_COLS - COMPOSE_INSET - ew);
            int max_y = (int)(WORLD_ROWS - COMPOSE_INSET - eh);
            if(max_x < COMPOSE_INSET || max_y < COMPOSE_INSET) continue;

            int px = (int)rng_range(rng, COMPOSE_INSET, (uint32_t)(max_x + 1));
            int py = (int)rng_range(rng, COMPOSE_INSET, (uint32_t)(max_y + 1));

            if(can_place(s, rot, px, py, out)) {
                blit_stamp(s, rot, px, py, out);
                placed++;
                placed_this = true;
            }
        }
    }
    (void)placed;
}
