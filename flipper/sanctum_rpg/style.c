/*
 * style.c — see style.h.
 */
#include "style.h"

#include "rng.h"
#include "stamps.h"
#include "terrain.h"

/* The two original biomes became the two first styles, and their ids are
 * also the stamp-catalog ids (StampDef.style). Pinned so no world moves. */
_Static_assert(STYLE_CAVERN == STAMP_STYLE_CAVERN, "cavern style id is the cavern stamp id");
_Static_assert(STYLE_MOOR == STAMP_STYLE_MOOR, "moor style id is the outdoor stamp id");
_Static_assert(STYLE_CRYPT == STAMP_STYLE_CRYPT && STYLE_MINE == STAMP_STYLE_MINE &&
               STYLE_FOREST == STAMP_STYLE_FOREST, "style ids are stamp-catalog ids");

/* Pick weights within a biome: natural caverns stay the commonest underground;
 * moor and forest share the surface. */
#define STYLE_W_CAVERN 2
#define STYLE_W_CRYPT  1
#define STYLE_W_MINE   1
#define STYLE_W_MOOR   1
#define STYLE_W_FOREST 1

const StyleDef STYLE_TABLE[STYLE_COUNT] = {
    /*               name      biome          terrain         family           wall       weight */
    [STYLE_CAVERN] = {"cavern", BIOME_CAVERN,  TERRAIN_WALLED, FAMILY_CAVERNS,  TM_STONE,  STYLE_W_CAVERN},
    [STYLE_MOOR]   = {"moor",   BIOME_OUTDOOR, TERRAIN_OPEN,   FAMILY_MOOR,     TM_STONE,  STYLE_W_MOOR},
    [STYLE_CRYPT]  = {"crypt",  BIOME_CAVERN,  TERRAIN_WALLED, FAMILY_DUNGEONS, TM_BRICK,  STYLE_W_CRYPT},
    [STYLE_MINE]   = {"mine",   BIOME_CAVERN,  TERRAIN_WALLED, FAMILY_MINES,    TM_TIMBER, STYLE_W_MINE},
    [STYLE_FOREST] = {"forest", BIOME_OUTDOOR, TERRAIN_OPEN,   FAMILY_FOREST,   TM_STONE,  STYLE_W_FOREST},
};

/* Distinct salt so a region's style doesn't correlate with its biome. */
#define STYLE_SALT 0x57A1E5EDu

Style style_of(uint32_t seed, int chunk_x, int chunk_y) {
    Biome b = biome_of(seed, chunk_x, chunk_y);
    uint32_t total = 0;
    Style only = STYLE_COUNT;
    int n = 0;
    for(int s = 0; s < STYLE_COUNT; s++)
        if(STYLE_TABLE[s].biome == b && STYLE_TABLE[s].weight) {
            total += STYLE_TABLE[s].weight;
            only = (Style)s;
            n++;
        }
    if(n <= 1) return only == STYLE_COUNT ? STYLE_CAVERN : only;
    int rx = region_of(chunk_x), ry = region_of(chunk_y);
    uint32_t h = region_hash(seed ^ STYLE_SALT, rx, ry) % total;
    for(int s = 0; s < STYLE_COUNT; s++) {
        if(STYLE_TABLE[s].biome != b || !STYLE_TABLE[s].weight) continue;
        if(h < STYLE_TABLE[s].weight) return (Style)s;
        h -= STYLE_TABLE[s].weight;
    }
    return only;
}

Style style_for_biome(Biome b) {
    for(int s = 0; s < STYLE_COUNT; s++)
        if(STYLE_TABLE[s].biome == b) return (Style)s;
    return STYLE_CAVERN;
}

TerrainMode style_terrain(Style s) {
    if((unsigned)s >= (unsigned)STYLE_COUNT) return TERRAIN_WALLED;
    return STYLE_TABLE[s].terrain;
}

TerrainMode region_terrain(uint32_t seed, int chunk_x, int chunk_y) {
    return style_terrain(style_of(seed, chunk_x, chunk_y));
}
