/*
 * biome.c — see biome.h.
 */

#include "biome.h"

#include "rng.h"

/* Chunks per biome region edge. Bigger = larger contiguous biome zones. */
#define BIOME_REGION 3

const BiomeDef BIOME_TABLE[BIOME_COUNT] = {
    [BIOME_CAVERN]  = {"cavern",  TERRAIN_WALLED},
    [BIOME_OUTDOOR] = {"outdoor", TERRAIN_OPEN},
};

/* Floor division — C truncates toward zero, which breaks region
 * contiguity across negative coords (cx=-1 must land in region -1, not
 * 0). This makes regions tile cleanly in all four quadrants. */
static int floor_div(int a, int b) {
    if(a >= 0) return a / b;
    return -(((-a) + b - 1) / b);
}

Biome biome_of(uint32_t seed, int chunk_x, int chunk_y) {
    int rx = floor_div(chunk_x, BIOME_REGION);
    int ry = floor_div(chunk_y, BIOME_REGION);
    /* Distinct seed salt so biome regions don't correlate with the
     * per-chunk geometry seed. */
    uint32_t h = rng_chunk_seed(seed ^ 0x5B10E001u, rx, ry);
    return (Biome)(h % BIOME_COUNT);
}

TerrainMode biome_terrain(Biome b) {
    if((unsigned)b >= (unsigned)BIOME_COUNT) return TERRAIN_WALLED;
    return BIOME_TABLE[b].terrain;
}
