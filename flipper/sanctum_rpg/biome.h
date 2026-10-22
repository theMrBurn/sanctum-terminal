/*
 * biome.h — biome assignment + terrain mode.
 *
 * Mirrors sanctum-engage's live biomes (SANCTUM_ENGAGE_INHERITANCE.md §4):
 * cavern (walled, doors) and outdoor (open field, walk off any edge).
 * workroom is the desktop authoring sandbox — skipped on mobile.
 *
 * Biomes form contiguous REGIONS (not per-chunk noise) so you walk
 * through a cavern region, then into an outdoor region — coherent, not
 * a checkerboard. Deterministic: biome_of(seed, cx, cy) is a pure
 * function (golden-master territory, §14.0). Pure module, host-testable.
 */

#pragma once

#include <stdint.h>

typedef enum {
    BIOME_CAVERN = 0,
    BIOME_OUTDOOR,
    BIOME_COUNT,
} Biome;

/* How a biome's chunks are shaped + traversed. */
typedef enum {
    TERRAIN_WALLED = 0, /* border walls; cross only through door tiles */
    TERRAIN_OPEN,       /* no border; walk off ANY edge to the neighbour */
} TerrainMode;

typedef struct {
    const char* name;
    TerrainMode terrain;  /* the biome's ORIGINAL mode; a region's actual
                           * enclosed/open now comes from its style (style.h) */
    uint8_t pool;         /* Pool / weather / narrative id (stamps.h
                           * STAMP_STYLE_CAVERN / _MOOR) for this biome */
} BiomeDef;

extern const BiomeDef BIOME_TABLE[BIOME_COUNT];

/* Region-based deterministic biome for a chunk. */
Biome biome_of(uint32_t seed, int chunk_x, int chunk_y);

/* Terrain mode for a biome (TERRAIN_WALLED for out-of-range, defensively). */
TerrainMode biome_terrain(Biome b);

/* The Pool / weather / narrative id for a biome. Keyed by the biome (the
 * realm), never by a region's enclosed/open — an above-ground hall still
 * draws the above-ground Pool. */
uint8_t biome_pool(Biome b);

/* Chunks per region edge: a region is BIOME_REGION x BIOME_REGION chunks.
 * Bigger = larger contiguous biome zones. */
#define BIOME_REGION 3

/* Region coordinate of a chunk coordinate (floor division by the region
 * edge, so regions tile cleanly through negative coords). */
int region_of(int chunk_coord);

/* Full-avalanche hash of a region. Unlike rng_chunk_seed, mirrored region
 * coords do not collide (memory: rng_chunk_seed point symmetry). */
uint32_t region_hash(uint32_t seed, int region_x, int region_y);

/* Biome affinity bit for loot filtering (1 << biome). */
#define BIOME_BIT(b) ((uint8_t)(1u << (b)))
