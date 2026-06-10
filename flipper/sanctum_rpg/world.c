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
#include "trade.h"

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

/* Anti-trap pass for any DOORED chunk. Postcondition: the spawn, every door
 * on the border, and every walkable interior tile share one 4-connected
 * component. Doors are located by scanning the border for TILE_DOOR, so this
 * serves caverns (4 doors) and open chunks that grew doors facing a walled
 * neighbor (1-3 doors) identically — no door-count or seed plumbing. */
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

    /* Connect every door tile on the border to the spawn component. Scan in a
     * fixed order (top, bottom, then left, right) so the carve is
     * deterministic. The carve may open access to more walkable tiles on the
     * door's side, so re-flood from each carved door. */
    for(int x = 0; x < WORLD_COLS; x++) {
        if(out->tiles[0][x] == TILE_DOOR && !reach[0][x]) {
            egress_carve_to_reach(out, x, 0, reach);
            egress_bfs_walkable(out, x, 0, reach);
        }
        if(out->tiles[WORLD_ROWS - 1][x] == TILE_DOOR && !reach[WORLD_ROWS - 1][x]) {
            egress_carve_to_reach(out, x, WORLD_ROWS - 1, reach);
            egress_bfs_walkable(out, x, WORLD_ROWS - 1, reach);
        }
    }
    for(int y = 0; y < WORLD_ROWS; y++) {
        if(out->tiles[y][0] == TILE_DOOR && !reach[y][0]) {
            egress_carve_to_reach(out, 0, y, reach);
            egress_bfs_walkable(out, 0, y, reach);
        }
        if(out->tiles[y][WORLD_COLS - 1] == TILE_DOOR && !reach[y][WORLD_COLS - 1]) {
            egress_carve_to_reach(out, WORLD_COLS - 1, y, reach);
            egress_bfs_walkable(out, WORLD_COLS - 1, y, reach);
        }
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

/* ─── Shared-edge door positions (spec 50 §R world-coherence) ───────────────
 * The crux of door=door / wall=wall coherence: both chunks sharing an edge
 * must independently agree on where the door through it sits, with NO
 * persistence and NO dependence on which way the player crossed. They agree
 * by hashing the edge's CANONICAL identity — the LOWER chunk coordinate plus
 * an axis bit — which both neighbors reduce to identically.
 *
 * Trap avoided: hashing (my_chunk, my_direction) gives each side a different
 * key and silently re-creates the phase-through-wall bug. Canonicalizing to
 * the lower coordinate is the whole trick. */
#define EDGE_DOOR_SALT 0xD006C0DEu /* separates the door-hash stream */
#define EDGE_AXIS_V    0x000000A1u /* E/W edge — door is a ROW            */
#define EDGE_AXIS_H    0x000000B2u /* N/S edge — door is a COLUMN         */

int world_edge_door_perp(uint32_t seed, int chunk_x, int chunk_y, MoveDir dir) {
    int ex, ey;       /* canonical edge coordinate (lower chunk of the pair) */
    bool vertical;    /* true: E/W edge (door is a row); false: N/S (a col)  */
    switch(dir) {
    case MoveNorth: ex = chunk_x;     ey = chunk_y - 1; vertical = false; break;
    case MoveSouth: ex = chunk_x;     ey = chunk_y;     vertical = false; break;
    case MoveWest:  ex = chunk_x - 1; ey = chunk_y;     vertical = true;  break;
    case MoveEast:  ex = chunk_x;     ey = chunk_y;     vertical = true;  break;
    default:        return WORLD_COLS / 2; /* unreachable; safe centre */
    }
    uint32_t base = seed ^ EDGE_DOOR_SALT ^ (vertical ? EDGE_AXIS_V : EDGE_AXIS_H);
    uint32_t h = rng_chunk_seed(base, ex, ey);
    /* Inset by 1 so doors never land on a corner. */
    if(vertical) return 1 + (int)(h % (uint32_t)(WORLD_ROWS - 2));
    return 1 + (int)(h % (uint32_t)(WORLD_COLS - 2));
}

/* Rare hidden passage on a shared edge — same canonical-edge machinery as the
 * door, distinct salts, gated by rarity. Both neighbors agree on existence,
 * position, and gating quest. */
#define SECRET_SALT       0x5EC0DEEDu /* presence + position hash             */
#define SECRET_GATE_SALT  0x90E57A10u /* which growth axis gates the secret   */
#define SECRET_RARITY     12u         /* ~1 in 12 walled edges has a secret   */

/* Canonical (lower-chunk + axis) edge identity, shared by world_edge_door_perp
 * and the secret helpers so both neighbors of an edge hash the same key. */
static uint32_t edge_hash(uint32_t seed, int cx, int cy, MoveDir dir,
                          uint32_t salt, bool* out_vertical) {
    int ex, ey;
    bool vertical;
    switch(dir) {
    case MoveNorth: ex = cx;     ey = cy - 1; vertical = false; break;
    case MoveSouth: ex = cx;     ey = cy;     vertical = false; break;
    case MoveWest:  ex = cx - 1; ey = cy;     vertical = true;  break;
    case MoveEast:  ex = cx;     ey = cy;     vertical = true;  break;
    default:        ex = cx;     ey = cy;     vertical = false; break;
    }
    if(out_vertical) *out_vertical = vertical;
    uint32_t base = seed ^ salt ^ (vertical ? EDGE_AXIS_V : EDGE_AXIS_H);
    return rng_chunk_seed(base, ex, ey);
}

int world_edge_secret_perp(uint32_t seed, int chunk_x, int chunk_y, MoveDir dir) {
    bool vertical;
    uint32_t h = edge_hash(seed, chunk_x, chunk_y, dir, SECRET_SALT, &vertical);
    if((h % SECRET_RARITY) != 0u) return -1; /* most edges have no secret */
    /* Derive a perp from the upper bits (the low bits drove the rarity gate),
     * then nudge off the door so the two never share a tile. */
    int span = vertical ? (WORLD_ROWS - 2) : (WORLD_COLS - 2);
    int perp = 1 + (int)((h >> 8) % (uint32_t)span);
    int door = world_edge_door_perp(seed, chunk_x, chunk_y, dir);
    if(perp == door) perp = 1 + ((perp - 1 + 1) % span); /* shift one, stay in range */
    return perp;
}

int world_edge_secret_axis(uint32_t seed, int chunk_x, int chunk_y, MoveDir dir,
                           int axis_count) {
    if(axis_count <= 0) return 0;
    uint32_t h = edge_hash(seed, chunk_x, chunk_y, dir, SECRET_GATE_SALT, NULL);
    return (int)(h % (uint32_t)axis_count);
}

/* Stamp the secret tile onto a WALLED edge if this edge carries one. Call only
 * for edges that are actually walls (caller knows which). Overwrites a wall
 * tile; never the door (world_edge_secret_perp is nudged off the door). */
static void place_edge_secret(uint32_t seed, int cx, int cy, MoveDir dir,
                              World* out) {
    int p = world_edge_secret_perp(seed, cx, cy, dir);
    if(p < 0) return;
    switch(dir) {
    case MoveNorth: out->tiles[0][p] = TILE_SECRET;              break;
    case MoveSouth: out->tiles[WORLD_ROWS - 1][p] = TILE_SECRET; break;
    case MoveWest:  out->tiles[p][0] = TILE_SECRET;              break;
    case MoveEast:  out->tiles[p][WORLD_COLS - 1] = TILE_SECRET; break;
    default: break;
    }
}

/* Slice 50.F1: CAVERN — walled border + one door per edge at its hashed
 * shared-edge position (biome owns the edge per spec 50 §F1.5 / §C.4); the
 * Pool-biased stamp composer fills the interior. The old blob algorithm is
 * gone — variety now comes from the stamp catalog × Pool bias × rotation. */
/* Place a single TILE_VENDOR if this chunk is a vendor chunk. Pre-compose
 * so the composer's "refuses to overwrite non-floor" rule protects it,
 * the same way it protects the 4 cavern doors. */
static void place_vendor_if_any(uint32_t seed, int cx, int cy, World* out) {
    if(!chunk_has_vendor(seed, cx, cy)) return;
    int vx, vy;
    vendor_position(seed, cx, cy, &vx, &vy);
    if(vx < 0 || vx >= WORLD_COLS || vy < 0 || vy >= WORLD_ROWS) return;
    out->tiles[vy][vx] = TILE_VENDOR;
}

static void gen_cavern_stamped(
    uint32_t seed, int cx, int cy, Rng* rng, const Pool* pool, World* out) {
    fill_floor_with_border(out);
    /* Doors first — the composer respects them (refuses to overwrite
     * non-floor tiles). Each door sits at its hashed per-edge position
     * (world_edge_door_perp), which the neighbor on the far side derives
     * identically — so crossing an edge always lands door-to-door rather
     * than phasing through a wall. door_transition reads the player's tile
     * position, so it keeps working regardless of where the door sits. */
    out->tiles[0][world_edge_door_perp(seed, cx, cy, MoveNorth)] = TILE_DOOR;
    out->tiles[WORLD_ROWS - 1][world_edge_door_perp(seed, cx, cy, MoveSouth)] = TILE_DOOR;
    out->tiles[world_edge_door_perp(seed, cx, cy, MoveWest)][0] = TILE_DOOR;
    out->tiles[world_edge_door_perp(seed, cx, cy, MoveEast)][WORLD_COLS - 1] = TILE_DOOR;
    /* A rare edge also hides a secret passage (all 4 cavern edges are walls). */
    place_edge_secret(seed, cx, cy, MoveNorth, out);
    place_edge_secret(seed, cx, cy, MoveSouth, out);
    place_edge_secret(seed, cx, cy, MoveWest, out);
    place_edge_secret(seed, cx, cy, MoveEast, out);
    place_vendor_if_any(seed, cx, cy, out);
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

/* Spec 50 §R world-coherence: an OPEN chunk must present a wall + single door
 * on any edge that borders a WALLED neighbor, so the seam reads door=door /
 * wall=wall from either side instead of letting the player phase through the
 * neighbor's rock. Edges facing OPEN neighbors stay bare floor for free
 * traversal. A corner becomes wall if EITHER of its two edges is walled —
 * which falls out of walling the full edge row/col. The door sits at the same
 * hashed position the walled neighbor uses, so crossing lands door-to-door.
 * Consumes no RNG (biome_of is self-seeded), so the geometry stream is
 * unchanged. Returns true if any door was placed (chunk needs egress). */
static bool wall_edges_facing_walled(uint32_t seed, int cx, int cy, World* out) {
    bool n = biome_terrain(biome_of(seed, cx, cy - 1)) == TERRAIN_WALLED;
    bool s = biome_terrain(biome_of(seed, cx, cy + 1)) == TERRAIN_WALLED;
    bool w = biome_terrain(biome_of(seed, cx - 1, cy)) == TERRAIN_WALLED;
    bool e = biome_terrain(biome_of(seed, cx + 1, cy)) == TERRAIN_WALLED;
    if(!n && !s && !w && !e) return false;

    if(n) for(int x = 0; x < WORLD_COLS; x++) out->tiles[0][x] = TILE_WALL;
    if(s) for(int x = 0; x < WORLD_COLS; x++) out->tiles[WORLD_ROWS - 1][x] = TILE_WALL;
    if(w) for(int y = 0; y < WORLD_ROWS; y++) out->tiles[y][0] = TILE_WALL;
    if(e) for(int y = 0; y < WORLD_ROWS; y++) out->tiles[y][WORLD_COLS - 1] = TILE_WALL;

    if(n) out->tiles[0][world_edge_door_perp(seed, cx, cy, MoveNorth)] = TILE_DOOR;
    if(s) out->tiles[WORLD_ROWS - 1][world_edge_door_perp(seed, cx, cy, MoveSouth)] = TILE_DOOR;
    if(w) out->tiles[world_edge_door_perp(seed, cx, cy, MoveWest)][0] = TILE_DOOR;
    if(e) out->tiles[world_edge_door_perp(seed, cx, cy, MoveEast)][WORLD_COLS - 1] = TILE_DOOR;
    /* Secrets only on the walled edges (same shared-edge hash as the neighbor). */
    if(n) place_edge_secret(seed, cx, cy, MoveNorth, out);
    if(s) place_edge_secret(seed, cx, cy, MoveSouth, out);
    if(w) place_edge_secret(seed, cx, cy, MoveWest, out);
    if(e) place_edge_secret(seed, cx, cy, MoveEast, out);
    return true;
}

/* Slice 50.F1: OUTDOOR — open field; the outer ring stays bare floor for free
 * edge traversal EXCEPT on edges that border a walled neighbor, which grow a
 * wall + single door (wall_edges_facing_walled). Stamps fill the interior.
 * Variety comes from the outdoor stamp catalog × Pool bias × rotation. */
static void gen_outdoor_stamped(
    uint32_t seed, int cx, int cy, Rng* rng, const Pool* pool, World* out) {
    for(int y = 0; y < WORLD_ROWS; y++) {
        for(int x = 0; x < WORLD_COLS; x++) {
            out->tiles[y][x] = TILE_FLOOR;
        }
    }
    bool doored = wall_edges_facing_walled(seed, cx, cy, out);
    place_vendor_if_any(seed, cx, cy, out);
    compose_stamps_into_interior(rng, pool, STAMP_BIOME_OUTDOOR, out);
    scatter_items(out, rng, pool);
    find_spawn(out);
    /* Any door we grew must be reachable from spawn (a stamp could otherwise
     * seal it off) — same invariant caverns get, now for doored open chunks. */
    if(doored) carve_egress(out);
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
        gen_outdoor_stamped(base_seed, chunk_x, chunk_y, &rng, &pool, out);
    } else {
        gen_cavern_stamped(base_seed, chunk_x, chunk_y, &rng, &pool, out);
    }

    /* Home chunk (0,0) gets a persistent vault near the spawn — slice
     * 2026-06-03d/C. Placed AFTER gen so we can pick a tile already in
     * the walkable-connected component (find_spawn + carve_egress have
     * run). Search 8-neighbor + a small radius for a non-spawn interior
     * floor; fall back to (sx+1, sy) if nothing else works. The chunk's
     * shop_at_home is FORCED on every load — the vault belongs to the
     * campaign, not to per-chunk persistence. */
    if(chunk_x == 0 && chunk_y == 0) {
        int sx = out->spawn_x, sy = out->spawn_y;
        /* Spiral candidates around spawn, prioritising cardinals close in. */
        static const int ox[12] = { 1, -1,  0,  0,  2, -2,  0,  0,  1, -1,  1, -1};
        static const int oy[12] = { 0,  0,  1, -1,  0,  0,  2, -2,  1,  1, -1, -1};
        bool placed = false;
        for(int i = 0; i < 12 && !placed; i++) {
            int nx = sx + ox[i], ny = sy + oy[i];
            if(nx <= 0 || nx >= WORLD_COLS - 1) continue;
            if(ny <= 0 || ny >= WORLD_ROWS - 1) continue;
            if(!world_walkable(out, nx, ny)) continue;
            if(out->tiles[ny][nx] != TILE_FLOOR) continue; /* don't clobber loot/doors/V */
            out->tiles[ny][nx] = TILE_VAULT;
            placed = true;
        }
        if(!placed) {
            /* Defensive last-resort: force (sx+1, sy) regardless. */
            int fx = sx + 1, fy = sy;
            if(fx > 0 && fx < WORLD_COLS - 1 && fy > 0 && fy < WORLD_ROWS - 1) {
                out->tiles[fy][fx] = TILE_VAULT;
            }
        }
    }
}

bool world_is_blocking(char glyph) {
    /* Legacy blockers + spec 50 §F1 primitive blockers (MC/MH/etc.). A secret
     * passage is solid to movement, FOV, and carve_egress — it only opens at
     * crossing time if its gating quest is resolved (handled by the caller). */
    if(glyph == TILE_WALL || glyph == TILE_ROCK || glyph == TILE_SECRET) return true;
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
    /* A secret reads as a wall, but the caller may open it (resolved quest) —
     * so report it distinctly rather than as a plain wall. */
    if(dest == TILE_SECRET) {
        return MoveBlockedBySecret;
    }
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
    case TILE_VENDOR:
        return MoveSteppedOnVendor;
    case TILE_VAULT:
        return MoveSteppedOnVault;
    default:
        return MoveOk;
    }
}
