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
#include "style.h"

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
    Style style;   /* the region's style — enclosed/open lives here */
    /* Per edge (WORLD_SEAM_*): the style whose walls an OPEN chunk grew on
     * that edge to face a WALLED neighbour — those walls are the
     * neighbour's, so they take its material and name. WORLD_SEAM_NONE =
     * the chunk's own style. Display only: never hashed, never saved. */
    uint8_t seam_style[4];
    /* Bit (1u << WORLD_SEAM_*): crossing that edge leads into a region still
     * closed by corruption (spec 58 §58.4). Display only — set by the app
     * from the rituals done (region_mark_world_edges), never by generation,
     * never hashed. Drawn as a haze on that edge in both views. */
    uint8_t closed_edges;
} World;

#define WORLD_SEAM_N 0
#define WORLD_SEAM_S 1
#define WORLD_SEAM_W 2
#define WORLD_SEAM_E 3
#define WORLD_SEAM_NONE 0xFFu

/* Reset every edge to the chunk's own style. Generation does this; worlds
 * built by hand (tests, the starter room) must too. */
void world_clear_seams(World* w);

/* The top-down haze over such a cell: an 8x8 XBM (LSB = left), sparse,
 * drawn under the cell's glyph. */
extern const uint8_t WORLD_HAZE_XBM[8];

/* Is cell (x, y) on an edge marked closed, and open ground or a doorway
 * (where the haze shows)? */
bool world_cell_in_haze(const World* w, int x, int y);

/* The style whose wall stands at (x, y): a seam's neighbour style on an
 * edge row/column the chunk grew facing it (north/south win at corners,
 * and coordinates past an edge count as that edge), else the chunk's own. */
Style world_wall_style(const World* w, int x, int y);

/* World-generator version (spec 43 §14.0). Any change that moves a chunk
 * golden MUST bump this, and the golden test pins fingerprints to it. */
#define WORLDGEN_VERSION 6   /* 2: styles; 3: cavern blockers' own glyphs; 4: interiors + glowcaps; 5: floor glyphs clear of weather overlays (2026-10-14); 6: Pool bias by style vocabulary, place names by style (2026-10-20) */

/* May a saved tile mutation (deltas) land on this freshly generated tile?
 * Only floor, loot and harvestable terrain (a glowcap) take one. After a WORLDGEN_VERSION bump a saved
 * pickup can point at what is now a wall, door, vendor or vault; skipping
 * it keeps the new geometry whole (spec 43 §14.0: saves are tolerant). */
bool world_mutation_applies(char fresh_tile);

/* Enclosed/open of a generated chunk (its style's terrain mode). */
TerrainMode world_terrain(const World* w);

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

/* Can (sx, sy) still reach every door on foot (4-connected over walkable
 * tiles)? The egress guarantee, as a check: a player-caused change (a
 * cave-in's rubble, spec 50 Q1) must never make it false. */
bool world_doors_reachable_from(const World* w, int sx, int sy);

/* Apply `dir` to (px, py); returns new position via in-out params and a
 * status code. May mutate the world (e.g. clears a picked-up item tile),
 * hence non-const. No I/O, no autosave; caller handles those.
 *
 * `out_dest` (nullable) receives the destination tile's glyph BEFORE any
 * mutation — so the caller can map a picked-up item glyph → kind for
 * value/name effects. Unchanged when the move is blocked. */
MoveResult world_try_move(
    World* w, MoveDir dir, int* px, int* py, char* out_dest);
