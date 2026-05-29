/*
 * world.c — see world.h.
 *
 * Starter room is hand-crafted for Phase 2. Phase 3 replaces this with
 * deterministic chunk generation seeded by the campaign's `seed`.
 */

#include "world.h"

#include <string.h>

#include "loot.h"
#include "rng.h"

/* ─── procgen tunables ───────────────────────────────────────────── */

/* Hand-crafted starter room — only used as a fallback / smoke test. */
static const char* const STARTER_ROOM[WORLD_ROWS] = {
    "################",
    "#..............#",
    "#..####........#",
    "#..#..#....*...#",
    "#..####........+",
    "################",
};

/* Procgen — bounds tuned by hand for a 16×6 chunk. Tighten/loosen as
 * playtesting suggests. */
#define GEN_MIN_BLOBS    1
#define GEN_MAX_BLOBS    3   /* exclusive: rng_range(., min, max) returns [min, max) */
#define GEN_BLOB_W       2
#define GEN_BLOB_H       2
#define GEN_INTERIOR_X0  2   /* leftmost x a blob can occupy */
#define GEN_INTERIOR_Y0  2   /* topmost y a blob can occupy */
#define GEN_INTERIOR_X1  (WORLD_COLS - 2 - GEN_BLOB_W)   /* rightmost (inclusive) */
#define GEN_INTERIOR_Y1  (WORLD_ROWS - 2 - GEN_BLOB_H)   /* bottommost (inclusive) */
#define GEN_MIN_ITEMS    1
#define GEN_MAX_ITEMS    3   /* exclusive */
#define GEN_MIN_ROCKS    2   /* outdoor obstacles */
#define GEN_MAX_ROCKS    7   /* exclusive */

/* ─── helpers ────────────────────────────────────────────────────── */

void world_starter_room(World* w) {
    for(int y = 0; y < WORLD_ROWS; y++) {
        memcpy(w->tiles[y], STARTER_ROOM[y], WORLD_COLS);
    }
    w->spawn_x = 1;
    w->spawn_y = 1;
    w->biome = BIOME_CAVERN; /* walled room */
}

static void fill_floor_with_border(World* w) {
    for(int y = 0; y < WORLD_ROWS; y++) {
        for(int x = 0; x < WORLD_COLS; x++) {
            bool border =
                (x == 0 || y == 0 || x == WORLD_COLS - 1 || y == WORLD_ROWS - 1);
            w->tiles[y][x] = border ? TILE_WALL : TILE_FLOOR;
        }
    }
}

static void place_blob(World* w, int x, int y) {
    for(int dy = 0; dy < GEN_BLOB_H; dy++) {
        for(int dx = 0; dx < GEN_BLOB_W; dx++) {
            int tx = x + dx, ty = y + dy;
            if(tx > 0 && tx < WORLD_COLS - 1 && ty > 0 && ty < WORLD_ROWS - 1) {
                w->tiles[ty][tx] = TILE_WALL;
            }
        }
    }
}

/* Pick a random interior floor tile (not a wall blob, not on the border).
 * Returns true and fills out_x, out_y on success; false if the room is
 * too dense to find one within a small retry budget. */
static bool pick_floor(const World* w, Rng* rng, int* x, int* y) {
    for(int tries = 0; tries < 32; tries++) {
        int rx = (int)rng_range(rng, 1, WORLD_COLS - 1);
        int ry = (int)rng_range(rng, 1, WORLD_ROWS - 1);
        if(w->tiles[ry][rx] == TILE_FLOOR) {
            *x = rx;
            *y = ry;
            return true;
        }
    }
    return false;
}

/* Pick a random non-corner border tile for a door. */
static void pick_door_tile(Rng* rng, int* x, int* y) {
    /* Walk the border perimeter (excluding the four corners) as a 1-D
     * sequence of length P, pick a random index, then map back. */
    int top    = WORLD_COLS - 2;        /* x ∈ [1, W-2], y = 0 */
    int right  = WORLD_ROWS - 2;        /* y ∈ [1, H-2], x = W-1 */
    int bottom = WORLD_COLS - 2;        /* x ∈ [1, W-2], y = H-1 */
    int left   = WORLD_ROWS - 2;        /* y ∈ [1, H-2], x = 0 */
    int perimeter = top + right + bottom + left;
    int i = (int)rng_range(rng, 0, (uint32_t)perimeter);
    if(i < top) {
        *x = 1 + i;
        *y = 0;
    } else if((i -= top) < right) {
        *x = WORLD_COLS - 1;
        *y = 1 + i;
    } else if((i -= right) < bottom) {
        *x = 1 + i;
        *y = WORLD_ROWS - 1;
    } else {
        i -= bottom;
        *x = 0;
        *y = 1 + i;
    }
}

/* Shared: scatter loot on floor tiles, biome-weighted (reads out->biome). */
static void scatter_items(World* out, Rng* rng) {
    int item_count = (int)rng_range(rng, GEN_MIN_ITEMS, GEN_MAX_ITEMS);
    for(int i = 0; i < item_count; i++) {
        int ix, iy;
        if(pick_floor(out, rng, &ix, &iy)) {
            out->tiles[iy][ix] = loot_glyph(loot_roll(rng, out->biome));
        }
    }
}

/* Shared: spawn = first walkable floor tile, row-major. */
static void find_spawn(World* out) {
    out->spawn_x = 1;
    out->spawn_y = 1;
    for(int y = 1; y < WORLD_ROWS - 1; y++) {
        for(int x = 1; x < WORLD_COLS - 1; x++) {
            if(out->tiles[y][x] == TILE_FLOOR) {
                out->spawn_x = x;
                out->spawn_y = y;
                return;
            }
        }
    }
}

/* CAVERN: walled room + interior wall blobs + 4 edge-midpoint doors.
 * (pick_door_tile, the random-edge-door variant, is kept for a future
 * non-uniform topology — intentionally unused here.) */
static void gen_cavern(Rng* rng, World* out) {
    fill_floor_with_border(out);
    int blob_count = (int)rng_range(rng, GEN_MIN_BLOBS, GEN_MAX_BLOBS);
    for(int i = 0; i < blob_count; i++) {
        int bx = (int)rng_range(rng, GEN_INTERIOR_X0, GEN_INTERIOR_X1 + 1);
        int by = (int)rng_range(rng, GEN_INTERIOR_Y0, GEN_INTERIOR_Y1 + 1);
        place_blob(out, bx, by);
    }
    (void)pick_door_tile;
    int mid_col = WORLD_COLS / 2;
    int mid_row = WORLD_ROWS / 2;
    out->tiles[0][mid_col] = TILE_DOOR;                  /* north */
    out->tiles[WORLD_ROWS - 1][mid_col] = TILE_DOOR;     /* south */
    out->tiles[mid_row][0] = TILE_DOOR;                  /* west  */
    out->tiles[mid_row][WORLD_COLS - 1] = TILE_DOOR;     /* east  */
    scatter_items(out, rng);
    find_spawn(out);
}

/* OUTDOOR: open field — no border wall, scattered impassable rocks, no
 * doors. You cross by walking off ANY edge (world_try_move returns
 * MoveWalkedOffEdge in an open biome). Rocks stay off the outer ring so
 * every edge tile is a valid crossing. */
static void gen_outdoor(Rng* rng, World* out) {
    for(int y = 0; y < WORLD_ROWS; y++) {
        for(int x = 0; x < WORLD_COLS; x++) {
            out->tiles[y][x] = TILE_FLOOR;
        }
    }
    int rocks = (int)rng_range(rng, GEN_MIN_ROCKS, GEN_MAX_ROCKS);
    for(int i = 0; i < rocks; i++) {
        int rx = (int)rng_range(rng, 1, WORLD_COLS - 1);
        int ry = (int)rng_range(rng, 1, WORLD_ROWS - 1);
        out->tiles[ry][rx] = TILE_ROCK;
    }
    scatter_items(out, rng);
    find_spawn(out);
}

void world_generate_chunk(
    uint32_t base_seed, int chunk_x, int chunk_y, World* out) {
    Rng rng;
    rng_seed(&rng, rng_chunk_seed(base_seed, chunk_x, chunk_y));
    /* biome_of uses its own salted seed — does NOT consume `rng`, so the
     * per-chunk geometry stream stays deterministic. */
    out->biome = biome_of(base_seed, chunk_x, chunk_y);
    if(biome_terrain(out->biome) == TERRAIN_OPEN) {
        gen_outdoor(&rng, out);
    } else {
        gen_cavern(&rng, out);
    }
}

bool world_is_blocking(char glyph) {
    return glyph == TILE_WALL || glyph == TILE_ROCK;
}

bool world_walkable(const World* w, int x, int y) {
    if(x < 0 || x >= WORLD_COLS) return false;
    if(y < 0 || y >= WORLD_ROWS) return false;
    return !world_is_blocking(w->tiles[y][x]);
}

MoveResult world_try_move(World* w, MoveDir dir, int* px, int* py, char* out_dest) {
    int nx = *px;
    int ny = *py;
    switch(dir) {
    case MoveNorth: ny--; break;
    case MoveSouth: ny++; break;
    case MoveEast:  nx++; break;
    case MoveWest:  nx--; break;
    default: return MoveOk;
    }
    if(nx < 0 || nx >= WORLD_COLS || ny < 0 || ny >= WORLD_ROWS) {
        /* Off-grid: in an OPEN biome that's a chunk crossing; in a WALLED
         * biome there's no exit there (doors are the only way out). */
        return (biome_terrain(w->biome) == TERRAIN_OPEN)
                   ? MoveWalkedOffEdge
                   : MoveBlockedByEdge;
    }
    char dest = w->tiles[ny][nx];
    if(world_is_blocking(dest)) {
        return MoveBlockedByWall;
    }
    if(out_dest) *out_dest = dest;
    *px = nx;
    *py = ny;
    /* Any pickupable loot glyph → pickup. Clear the tile in-memory; the
     * caller persists it (delta layer) and maps glyph→kind for effects.
     * `w` is non-const precisely so this mutation is honest. */
    if(loot_is_item_glyph(dest)) {
        w->tiles[ny][nx] = TILE_FLOOR;
        return MovePickedUpItem;
    }
    switch(dest) {
    case TILE_DOOR:
        return MoveSteppedOnDoor;
    case TILE_STAIRS_UP:
    case TILE_STAIRS_DOWN:
        return MoveSteppedOnStairs;
    default:
        return MoveOk;
    }
}
