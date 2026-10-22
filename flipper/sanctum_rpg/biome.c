/*
 * biome.c — see biome.h.
 */

#include "biome.h"

#include "rng.h"

const BiomeDef BIOME_TABLE[BIOME_COUNT] = {
    [BIOME_CAVERN]  = {"cavern",  TERRAIN_WALLED, 0u},
    [BIOME_OUTDOOR] = {"outdoor", TERRAIN_OPEN,   1u},
};

/* Floor division — C truncates toward zero, which breaks region
 * contiguity across negative coords (cx=-1 must land in region -1, not
 * 0). This makes regions tile cleanly in all four quadrants. */
static int floor_div(int a, int b) {
    if(a >= 0) return a / b;
    return -(((-a) + b - 1) / b);
}

int region_of(int chunk_coord) { return floor_div(chunk_coord, BIOME_REGION); }

uint32_t region_hash(uint32_t seed, int region_x, int region_y) {
    uint32_t h = 0x811C9DC5u;   /* FNV-1a over the three words, then a finalizer */
    uint32_t w[3] = {seed, (uint32_t)region_x, (uint32_t)region_y};
    for(int i = 0; i < 3; i++)
        for(int b = 0; b < 4; b++) h = (h ^ ((w[i] >> (8 * b)) & 0xFFu)) * 0x01000193u;
    h ^= h >> 16; h *= 0x7FEB352Du; h ^= h >> 15; h *= 0x846CA68Bu; h ^= h >> 16;
    return h;
}

uint8_t biome_pool(Biome b) {
    if((unsigned)b >= (unsigned)BIOME_COUNT) return BIOME_TABLE[BIOME_CAVERN].pool;
    return BIOME_TABLE[b].pool;
}

Biome biome_of(uint32_t seed, int chunk_x, int chunk_y) {
    int rx = region_of(chunk_x);
    int ry = region_of(chunk_y);
    /* Distinct seed salt so biome regions don't correlate with the
     * per-chunk geometry seed. */
    uint32_t h = rng_chunk_seed(seed ^ 0x5B10E001u, rx, ry);
    return (Biome)(h % BIOME_COUNT);
}

TerrainMode biome_terrain(Biome b) {
    if((unsigned)b >= (unsigned)BIOME_COUNT) return TERRAIN_WALLED;
    return BIOME_TABLE[b].terrain;
}
