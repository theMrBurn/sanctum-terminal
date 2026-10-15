/*
 * style.h — what KIND of place a region is.
 *
 * Every terrain type sits on two axes (SHARED_STATE 2026-10-14, "a region
 * has a style"):
 *
 *   biome   — UNDERGROUND (cavern) or ABOVE GROUND (outdoor). Owns loot,
 *             creatures, names, weather and the Pool (biome.h).
 *   style   — the place itself: natural cavern, crypt, old mine, moor,
 *             forest, hall... Owns ENCLOSED/OPEN (terrain mode), the wall
 *             material, the floor marks and the stamp catalog.
 *
 * A style belongs to one biome; each region (BIOME_REGION chunks square)
 * picks one style from its biome's rows by weight. Families group styles
 * for design and naming (caverns, dungeons, mines, moor, forest, ...).
 *
 * Data-table-driven (spec 43 §14.0): adding a style is one STYLE_TABLE row
 * plus its stamps; never `if style == ...` in logic. Pure, host-testable.
 */
#pragma once

#include <stdint.h>

#include "biome.h"

typedef enum {
    STYLE_CAVERN = 0,   /* natural cavern — the original cavern biome */
    STYLE_MOOR,         /* moor / heath — the original outdoor biome */
    STYLE_COUNT,
} Style;

typedef enum {
    FAMILY_CAVERNS = 0, /* underground, natural, big */
    FAMILY_MOOR,        /* above ground, open, stones and scrub */
    FAMILY_COUNT,
} StyleFamily;

typedef struct {
    const char* name;
    Biome biome;          /* realm: underground / above ground */
    TerrainMode terrain;  /* enclosed (walled, doors) / open */
    uint8_t family;       /* StyleFamily */
    uint8_t wall_material;/* SlabMaterial for TILE_WALL in this style */
    uint8_t weight;       /* pick weight among its biome's styles */
} StyleDef;

extern const StyleDef STYLE_TABLE[STYLE_COUNT];

/* The region's style for a chunk. Pure function of (seed, chunk coords);
 * every chunk of a region agrees. */
Style style_of(uint32_t seed, int chunk_x, int chunk_y);

/* The biome's original style (cavern -> STYLE_CAVERN, outdoor -> STYLE_MOOR):
 * for worlds built by hand (starter room, test fixtures). */
Style style_for_biome(Biome b);

/* Enclosed/open for a style (TERRAIN_WALLED for out-of-range). */
TerrainMode style_terrain(Style s);

/* Enclosed/open for the region a chunk lies in. */
TerrainMode region_terrain(uint32_t seed, int chunk_x, int chunk_y);
