/*
 * world.h — tile grid + movement.
 *
 * Phase 2 v0.2.0: a single hand-crafted starter room. Procgen chunks
 * (spec 43 §6 — the four-layer seed cake, infinite-by-construction)
 * land in Phase 3 and replace `world_starter_room` with seeded chunk
 * generation. The world API surface stays the same.
 *
 * Coordinates: tile (0,0) is top-left of the playable area. The status
 * bar lives below the grid and is not part of the world.
 *
 * No hardcoded literals in render/logic code — see #defines.
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "biome.h"

#define WORLD_COLS 16
#define WORLD_ROWS 6

/* Tile glyphs — sanctum-engage canonical ASCII. */
#define TILE_FLOOR  '.'
#define TILE_WALL   '#'   /* cavern structure — impassable */
#define TILE_ROCK   'o'   /* outdoor obstacle (boulder) — impassable */
#define TILE_DOOR   '+'
#define TILE_ITEM   '*'   /* legacy/starter-room item glyph (loot.c is canonical) */
#define TILE_STAIRS_UP    '<'
#define TILE_STAIRS_DOWN  '>'

/* Movement intents. */
typedef enum {
    MoveNone,
    MoveNorth,
    MoveSouth,
    MoveEast,
    MoveWest,
} MoveDir;

/* Result of attempted movement, used to drive status messages + UI. */
typedef enum {
    MoveOk,
    MoveBlockedByWall,
    MoveBlockedByEdge,    /* off-grid in a WALLED biome — no exit there */
    MoveWalkedOffEdge,    /* off-grid in an OPEN biome — transition to neighbour */
    MovePickedUpItem,
    MoveSteppedOnDoor,
    MoveSteppedOnStairs,
} MoveResult;

typedef struct {
    char tiles[WORLD_ROWS][WORLD_COLS];
    int spawn_x;
    int spawn_y;
    Biome biome;
} World;

/* Is this tile glyph impassable? (walls + outdoor rocks) */
bool world_is_blocking(char glyph);

/* Hand-crafted starter room — kept as a known-good reference for the
 * generator + as a smoke-test fallback. Production path is
 * world_generate_chunk. Idempotent. */
void world_starter_room(World* w);

/* Deterministic procgen — same (base_seed, chunk_x, chunk_y) always
 * produces the same tiles. Spec 43 §6 four-layer seed cake: for v0.3.0
 * we use only the campaign and chunk layers; daily + field layers land
 * later. Sets spawn_x/spawn_y to a guaranteed-walkable tile.
 *
 * v0.3.0 simplification: chunks are 16×6 (one viewport), not 64×64 as
 * spec 43 §6 describes. The chunk-as-screenful makes Phase 3b
 * (multi-chunk traversal) materially smaller; we revisit if/when the
 * world feels too small. */
void world_generate_chunk(
    uint32_t base_seed, int chunk_x, int chunk_y, World* out);

/* Is (x, y) walkable? Walls + edges are not. */
bool world_walkable(const World* w, int x, int y);

/* Apply `dir` to (px, py); returns new position via in-out params and a
 * status code. May mutate the world (e.g. clears a picked-up item tile),
 * hence non-const. No I/O, no autosave; caller handles those.
 *
 * `out_dest` (nullable) receives the destination tile's glyph BEFORE any
 * mutation — so the caller can map a picked-up item glyph → kind for
 * value/name effects. Unchanged when the move is blocked. */
MoveResult world_try_move(
    World* w, MoveDir dir, int* px, int* py, char* out_dest);
