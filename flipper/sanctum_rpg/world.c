/*
 * world.c — see world.h.
 *
 * Starter room is hand-crafted for Phase 2. Phase 3 replaces this with
 * deterministic chunk generation seeded by the campaign's `seed`.
 */

#include "world.h"

#include <string.h>

#include "compose.h"
#include "loot.h"
#include "pool.h"
#include "rng.h"
#include "stamps.h"

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
/* Loot density: 2-4 items per 16×6 chunk (avg 3). Bumped 2026-06-01 from
 * 1-2 — playtest reported torches + craft inputs too sparse, the gather→
 * craft loop was stalling. Math: at ~3 items/chunk, cavern delivers ~0.4
 * torches/chunk (1 per ~2.5 chunks) and ~1 crystal/chunk (Crystal Brew
 * inputs in ~2 cavern chunks). Tight but the loop actually closes. */
#define GEN_MIN_ITEMS    2
#define GEN_MAX_ITEMS    5   /* exclusive */
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

/* Shared: scatter loot on floor tiles, biome-weighted (reads out->biome).
 * Slice 50.F3: pool-aware — the Pool's loot_kind_bias shifts catalog
 * weights so the same biome drifts toward different loot kinds as the
 * player walks. Pool can be NULL (legacy callers) for no bias. */
static void scatter_items(World* out, Rng* rng, const Pool* pool) {
    int item_count = (int)rng_range(rng, GEN_MIN_ITEMS, GEN_MAX_ITEMS);
    for(int i = 0; i < item_count; i++) {
        int ix, iy;
        if(pick_floor(out, rng, &ix, &iy)) {
            out->tiles[iy][ix] = loot_glyph(loot_roll_pooled(rng, out->biome, pool));
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

/* ─── egress carve (anti-trap pass) ───────────────────────────────────
 *
 * After the stamp composer fills the cavern interior, it is possible for
 * the placed stamps to wall the spawn off from one or more (or in the
 * pathological case ALL) of the 4 mid-edge doors — see playtest 2026-06-03,
 * which produced a fully sealed room. The "no-escape" failure mode breaks
 * the game.
 *
 * Rule: every door, the spawn, and every walkable tile in the cavern must
 * end up in one connected component. Achieved by:
 *
 *   1. BFS-mark the spawn's connected walkable region.
 *   2. For each door not yet in the region, run a BFS from the door (over
 *      ALL cells, allowing passage through blocking ones) to find the
 *      shortest path to the region. Carve = set every blocking cell on
 *      that path to TILE_FLOOR; absorb the path into the region.
 *   3. Sweep the grid for any walkable cells still outside the region
 *      (isolated pockets the composer created). Carve them to the region
 *      the same way.
 *
 * Pure on the World*. No RNG. Deterministic: same input chunk → byte-equal
 * carved output. The carve only converts blocking → floor, so items and
 * doors are never overwritten.
 *
 * The carve BFS is restricted to interior tiles (and the start cell when
 * it's a perimeter door) — we never carve through the cavern's outer wall.
 */

#define EGRESS_GRID_CELLS (WORLD_ROWS * WORLD_COLS)

/* Flood-fill walkable region starting at (sx, sy); marks reach[y][x]=1
 * for every reachable cell. Caller pre-zeros `reach`. */
static void egress_bfs_walkable(
    const World* out, int sx, int sy, uint8_t reach[WORLD_ROWS][WORLD_COLS]) {
    if(sx < 0 || sx >= WORLD_COLS || sy < 0 || sy >= WORLD_ROWS) return;
    if(!world_walkable(out, sx, sy)) return;
    int qx[EGRESS_GRID_CELLS];
    int qy[EGRESS_GRID_CELLS];
    int head = 0, tail = 0;
    qx[tail] = sx; qy[tail] = sy; tail++;
    reach[sy][sx] = 1;
    const int dx[4] = {0, 0, 1, -1};
    const int dy[4] = {-1, 1, 0, 0};
    while(head < tail) {
        int x = qx[head], y = qy[head]; head++;
        for(int d = 0; d < 4; d++) {
            int nx = x + dx[d], ny = y + dy[d];
            if(nx < 0 || nx >= WORLD_COLS || ny < 0 || ny >= WORLD_ROWS) continue;
            if(reach[ny][nx]) continue;
            if(!world_walkable(out, nx, ny)) continue;
            reach[ny][nx] = 1;
            qx[tail] = nx; qy[tail] = ny; tail++;
        }
    }
}

/* Carve the shortest 4-connected path from (sx, sy) to any cell already
 * in `reach`, ignoring blocking. Sets every blocking cell on the path to
 * TILE_FLOOR and marks each path cell in `reach`. The carve BFS is
 * restricted to interior tiles, except for the start cell itself (so a
 * door tile on the perimeter is a valid start).
 *
 * Idempotent if (sx, sy) is already in `reach` (returns immediately). */
static void egress_carve_to_reach(
    World* out, int sx, int sy, uint8_t reach[WORLD_ROWS][WORLD_COLS]) {
    if(sx < 0 || sx >= WORLD_COLS || sy < 0 || sy >= WORLD_ROWS) return;
    if(reach[sy][sx]) return;

    int16_t parent[EGRESS_GRID_CELLS];
    for(int p = 0; p < EGRESS_GRID_CELLS; p++) parent[p] = -1;
    int qx[EGRESS_GRID_CELLS];
    int qy[EGRESS_GRID_CELLS];
    int head = 0, tail = 0;
    int start_idx = sy * WORLD_COLS + sx;
    qx[tail] = sx; qy[tail] = sy; tail++;
    parent[start_idx] = (int16_t)start_idx; /* self-parent marks visited */
    int hit = -1;
    const int dx[4] = {0, 0, 1, -1};
    const int dy[4] = {-1, 1, 0, 0};
    while(head < tail && hit < 0) {
        int x = qx[head], y = qy[head]; head++;
        for(int d = 0; d < 4; d++) {
            int nx = x + dx[d], ny = y + dy[d];
            if(nx < 0 || nx >= WORLD_COLS || ny < 0 || ny >= WORLD_ROWS) continue;
            int np = ny * WORLD_COLS + nx;
            if(parent[np] >= 0) continue;
            /* Carve BFS stays in the interior; the cavern's outer wall is
             * sacred — door_transition expects exits only at the 4 doors. */
            bool is_interior =
                (nx > 0 && nx < WORLD_COLS - 1 && ny > 0 && ny < WORLD_ROWS - 1);
            bool is_start = (nx == sx && ny == sy);
            if(!is_interior && !is_start) continue;
            parent[np] = (int16_t)(y * WORLD_COLS + x);
            if(reach[ny][nx]) {
                hit = np;
                break;
            }
            qx[tail] = nx; qy[tail] = ny; tail++;
        }
    }
    if(hit < 0) return; /* geometrically isolated — shouldn't happen on 16×6 */

    /* Walk the parent chain from `hit` back to start; carve as we go. */
    int cur = hit;
    while(cur != start_idx) {
        int cx_ = cur % WORLD_COLS;
        int cy_ = cur / WORLD_COLS;
        if(!world_walkable(out, cx_, cy_)) {
            out->tiles[cy_][cx_] = TILE_FLOOR;
        }
        reach[cy_][cx_] = 1;
        cur = parent[cur];
    }
    reach[sy][sx] = 1;
}

/* Anti-trap pass for caverns. Postcondition: spawn, all 4 doors, and
 * every walkable interior tile share one 4-connected component. */
static void carve_egress(World* out) {
    /* Defensive: a degenerate spawn (blocked by a stamp landing on (1,1))
     * shouldn't happen — find_spawn picks a TILE_FLOOR — but in case the
     * grid is completely walled in, force the spawn cell walkable so the
     * BFS has a seed. */
    if(!world_walkable(out, out->spawn_x, out->spawn_y)) {
        out->tiles[out->spawn_y][out->spawn_x] = TILE_FLOOR;
    }

    uint8_t reach[WORLD_ROWS][WORLD_COLS];
    memset(reach, 0, sizeof(reach));

    egress_bfs_walkable(out, out->spawn_x, out->spawn_y, reach);

    /* The 4 mid-edge doors. Order is fixed (N, S, W, E) so any chunks that
     * need carving carve deterministically. */
    const int doors[4][2] = {
        { WORLD_COLS / 2,     0                  },
        { WORLD_COLS / 2,     WORLD_ROWS - 1     },
        { 0,                  WORLD_ROWS / 2     },
        { WORLD_COLS - 1,     WORLD_ROWS / 2     },
    };
    for(int i = 0; i < 4; i++) {
        int dxd = doors[i][0], dyd = doors[i][1];
        if(reach[dyd][dxd]) continue;
        egress_carve_to_reach(out, dxd, dyd, reach);
        /* The carved corridor may have opened access to additional walkable
         * tiles that share the door's side — sweep them in. */
        egress_bfs_walkable(out, dxd, dyd, reach);
    }

    /* Sweep for isolated walkable pockets (composer geometry can produce
     * an island of floor inside a stamp ring). Connect each to the main
     * region so the player can never be stranded on a sub-island. */
    for(int y = 1; y < WORLD_ROWS - 1; y++) {
        for(int x = 1; x < WORLD_COLS - 1; x++) {
            if(reach[y][x]) continue;
            if(!world_walkable(out, x, y)) continue;
            egress_carve_to_reach(out, x, y, reach);
            egress_bfs_walkable(out, x, y, reach);
        }
    }
}

/* Slice 50.F1: CAVERN — walled border + 4 mid-edge doors (biome owns the
 * edge per spec 50 §F1.5 / §C.4); the Pool-biased stamp composer fills
 * the interior. The old blob algorithm is gone — variety now comes from
 * the stamp catalog (10 cavern stamps) × Pool bias × rotation. */
static void gen_cavern_stamped(Rng* rng, const Pool* pool, World* out) {
    fill_floor_with_border(out);
    /* Doors first — the composer respects them (refuses to overwrite
     * non-floor tiles). Mid-edge positions stay unchanged so the existing
     * door_transition + do_transition code keeps working. */
    int mid_col = WORLD_COLS / 2;
    int mid_row = WORLD_ROWS / 2;
    out->tiles[0][mid_col] = TILE_DOOR;
    out->tiles[WORLD_ROWS - 1][mid_col] = TILE_DOOR;
    out->tiles[mid_row][0] = TILE_DOOR;
    out->tiles[mid_row][WORLD_COLS - 1] = TILE_DOOR;
    (void)pick_door_tile;
    (void)place_blob; /* slice 50.F1 — blob algorithm retired */
    compose_stamps_into_interior(rng, pool, STAMP_BIOME_CAVERN, out);
    scatter_items(out, rng, pool);
    find_spawn(out);
    /* Anti-trap: ensure spawn + all 4 doors + every walkable cell share one
     * connected component. The composer can otherwise seal the spawn off
     * from one or all doors (playtest 2026-06-03: fully sealed room). The
     * carve modifies tiles after all RNG consumption — byte-equal output
     * across builds for the same chunk geometry. */
    carve_egress(out);
}

/* Slice 50.F1: OUTDOOR — open field, no walls, no doors (cross any edge).
 * Stamps fill the interior; the outer ring stays bare floor so edge
 * traversal works. The old rock-scatter algorithm is gone — variety now
 * comes from the outdoor stamp catalog (10 stamps) × Pool bias × rotation. */
static void gen_outdoor_stamped(Rng* rng, const Pool* pool, World* out) {
    for(int y = 0; y < WORLD_ROWS; y++) {
        for(int x = 0; x < WORLD_COLS; x++) {
            out->tiles[y][x] = TILE_FLOOR;
        }
    }
    compose_stamps_into_interior(rng, pool, STAMP_BIOME_OUTDOOR, out);
    scatter_items(out, rng, pool);
    find_spawn(out);
}

void world_generate_chunk(
    uint32_t base_seed, int chunk_x, int chunk_y, World* out) {
    Rng rng;
    rng_seed(&rng, rng_chunk_seed(base_seed, chunk_x, chunk_y));
    /* biome_of uses its own salted seed — does NOT consume `rng`, so the
     * per-chunk geometry stream stays deterministic. */
    out->biome = biome_of(base_seed, chunk_x, chunk_y);

    /* Slice 50.F1: build the Pool by canonical X-first-then-Y walk from
     * the campaign prime (chunk 0, 0). Same (base_seed, biome, cx, cy) →
     * byte-equal Pool → byte-equal stamp placement. The Pool is internal
     * to gen — never persisted, regenerated on every call (spec 50 §3.3). */
    Pool pool;
    uint8_t pool_biome = (biome_terrain(out->biome) == TERRAIN_OPEN)
                             ? STAMP_BIOME_OUTDOOR
                             : STAMP_BIOME_CAVERN;
    pool_at(base_seed, pool_biome, chunk_x, chunk_y, &pool);

    if(biome_terrain(out->biome) == TERRAIN_OPEN) {
        gen_outdoor_stamped(&rng, &pool, out);
    } else {
        gen_cavern_stamped(&rng, &pool, out);
    }
}

bool world_is_blocking(char glyph) {
    /* Legacy blockers + spec 50 §F1 primitive blockers (MC/MH/etc.). */
    if(glyph == TILE_WALL || glyph == TILE_ROCK) return true;
    return primitive_glyph_blocks(glyph);
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
