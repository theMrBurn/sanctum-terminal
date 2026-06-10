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
#define TILE_VENDOR 'V'   /* slice 2026-06-03d — economy bundle */
#define TILE_VAULT  '='   /* slice 2026-06-03d — home-chunk persistent stash */
#define TILE_SECRET '%'   /* spec 50 §R — a hidden passage. Reads/acts as wall
                           * (world_is_blocking) and renders as one in FPV; the
                           * distinct top-down glyph is the discovery "tell".
                           * Passable only when its gating quest is resolved —
                           * that check lives at crossing time, never in gen. */

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
    MoveSteppedOnVendor,
    MoveSteppedOnVault,
    MoveBlockedBySecret,  /* walked at a TILE_SECRET — caller checks the gating
                           * quest and either crosses or shows the "tell" */
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

/* Door position on the shared edge between (chunk_x, chunk_y) and its
 * neighbor in `dir`. Returns the perpendicular tile index ALONG that edge:
 * a COLUMN in [1, WORLD_COLS-2] for MoveNorth/MoveSouth, a ROW in
 * [1, WORLD_ROWS-2] for MoveEast/MoveWest.
 *
 * Both neighbors of an edge derive the IDENTICAL position because the hash
 * keys on the edge's canonical identity (the lower chunk coordinate + axis),
 * not on either chunk's viewpoint. So a chunk's east door row always equals
 * its east-neighbor's west door row — door=door across the seam, with no
 * persistence and no dependence on entry direction (spec 43 §14.0). */
int world_edge_door_perp(uint32_t seed, int chunk_x, int chunk_y, MoveDir dir);

/* A rare hidden passage may sit on a WALLED shared edge, at a position both
 * neighbors derive identically (same canonical-edge hashing as the door, with
 * a distinct salt and a rarity gate). Returns the perpendicular tile index of
 * the secret, or -1 if this edge has none. Never collides with the door. */
int world_edge_secret_perp(uint32_t seed, int chunk_x, int chunk_y, MoveDir dir);

/* The growth axis (0..axis_count-1) that gates the secret on this edge.
 * Deterministic per canonical edge, so both neighbors agree on which axis
 * opens the passage. The caller compares the player's EFFECTIVE axis (base +
 * deed growth, which persists across sessions) against a threshold — so a
 * secret rewards how the character has been played. */
int world_edge_secret_axis(uint32_t seed, int chunk_x, int chunk_y, MoveDir dir,
                           int axis_count);

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
