/*
 * style.c — see style.h.
 */
#include "style.h"

#include <stdbool.h>

#include "rng.h"
#include "site.h"
#include "stamps.h"
#include "terrain.h"

/* The two original biomes became the two first styles, and their ids are
 * also the stamp-catalog ids (StampDef.style). Pinned so no world moves. */
_Static_assert(STYLE_CAVERN == STAMP_STYLE_CAVERN, "cavern style id is the cavern stamp id");
_Static_assert(STYLE_MOOR == STAMP_STYLE_MOOR, "moor style id is the outdoor stamp id");
_Static_assert(STYLE_CRYPT == STAMP_STYLE_CRYPT && STYLE_MINE == STAMP_STYLE_MINE &&
               STYLE_FOREST == STAMP_STYLE_FOREST && STYLE_MANOR == STAMP_STYLE_MANOR &&
               STYLE_KEEP == STAMP_STYLE_KEEP && STYLE_ABBEY == STAMP_STYLE_ABBEY &&
               STYLE_MAUSOLEUM == STAMP_STYLE_MAUSOLEUM && STYLE_MOUND == STAMP_STYLE_MOUND &&
               STYLE_BURIAL_CAVE == STAMP_STYLE_BURIAL_CAVE,
               "style ids are stamp-catalog ids");

/* Pick weights within a biome: natural caverns stay the commonest underground;
 * moor and forest share the surface. */
#define STYLE_W_CAVERN 2
#define STYLE_W_CRYPT  1
#define STYLE_W_MINE   1
#define STYLE_W_MOOR   3   /* the open country stays the commonest surface */
#define STYLE_W_FOREST 3
#define STYLE_W_MANOR  1
#define STYLE_W_KEEP   1
#define STYLE_W_ABBEY  1
#define STYLE_W_MAUSOLEUM   1   /* WORLDGEN 7: the burial family */
#define STYLE_W_MOUND       1
#define STYLE_W_BURIAL_CAVE 1

const StyleDef STYLE_TABLE[STYLE_COUNT] = {
    /*               name      biome          terrain         family           wall       wall name      weight
     *               vocabulary (bag-slot order), count, name scope, may wake, site kinds */
    [STYLE_CAVERN] = {"cavern", BIOME_CAVERN,  TERRAIN_WALLED, FAMILY_CAVERNS,  TM_STONE,  "rock wall",   STYLE_W_CAVERN,
                     {PRIM_ST, PRIM_C, PRIM_MC, PRIM_LST, PRIM_MW, PRIM_GC, PRIM_DL}, 7, NAME_SCOPE_CHUNK, 1, SITE_BIT(SITE_STONE)},
    [STYLE_MOOR]   = {"moor",   BIOME_OUTDOOR, TERRAIN_OPEN,   FAMILY_MOOR,     TM_STONE,  "rock wall",   STYLE_W_MOOR,
                     {PRIM_SS, PRIM_CA, PRIM_MH, PRIM_DF, PRIM_SC, PRIM_SR, PRIM_GR, PRIM_DL}, 8, NAME_SCOPE_CHUNK, 1, SITE_BIT(SITE_GRAVE) | SITE_BIT(SITE_STONE)},
    [STYLE_CRYPT]  = {"crypt",  BIOME_CAVERN,  TERRAIN_WALLED, FAMILY_DUNGEONS, TM_BRICK,  "brick wall",  STYLE_W_CRYPT,
                     {PRIM_SA, PRIM_BP, PRIM_UR, PRIM_FS, PRIM_MC, PRIM_AL}, 6, NAME_SCOPE_REGION, 1, SITE_BIT(SITE_TOMB) | SITE_BIT(SITE_ALTAR)},
    [STYLE_MINE]   = {"mine",   BIOME_CAVERN,  TERRAIN_WALLED, FAMILY_MINES,    TM_TIMBER, "shored rock", STYLE_W_MINE,
                     {PRIM_OC, PRIM_RB, PRIM_PO, PRIM_RL, PRIM_DL}, 5, NAME_SCOPE_REGION, 1, SITE_BIT(SITE_STONE)},
    [STYLE_FOREST] = {"forest", BIOME_OUTDOOR, TERRAIN_OPEN,   FAMILY_FOREST,   TM_STONE,  "rock wall",   STYLE_W_FOREST,
                     {PRIM_TR, PRIM_DT, PRIM_SP, PRIM_TG, PRIM_DF, PRIM_SC, PRIM_DL}, 7, NAME_SCOPE_CHUNK, 1, SITE_BIT(SITE_GRAVE) | SITE_BIT(SITE_STONE)},
    [STYLE_MANOR]  = {"manor",  BIOME_OUTDOOR, TERRAIN_WALLED, FAMILY_DWELLINGS, TM_FRAME, "plaster wall", STYLE_W_MANOR,
                     {PRIM_TB, PRIM_BA, PRIM_HE, PRIM_PL, PRIM_GR}, 5, NAME_SCOPE_REGION, 1, SITE_BIT(SITE_GRAVE) | SITE_BIT(SITE_ALTAR)},
    [STYLE_KEEP]   = {"keep",   BIOME_OUTDOOR, TERRAIN_WALLED, FAMILY_FORTIFICATIONS, TM_ASHLAR, "curtain wall", STYLE_W_KEEP,
                     {PRIM_RK, PRIM_BZ, PRIM_BA, PRIM_FS, PRIM_GR}, 5, NAME_SCOPE_REGION, 1, SITE_BIT(SITE_GRAVE) | SITE_BIT(SITE_ALTAR)},
    [STYLE_ABBEY]  = {"abbey",  BIOME_OUTDOOR, TERRAIN_WALLED, FAMILY_HOLY,     TM_CARVED, "carved wall", STYLE_W_ABBEY,
                     {PRIM_AL, PRIM_SU, PRIM_PW, PRIM_BZ, PRIM_UR, PRIM_FS, PRIM_GR}, 7, NAME_SCOPE_REGION, 1, SITE_BIT(SITE_ALTAR) | SITE_BIT(SITE_GRAVE)},
    [STYLE_MAUSOLEUM] = {"mausoleum", BIOME_OUTDOOR, TERRAIN_WALLED, FAMILY_BURIAL, TM_CARVED, "tomb wall", STYLE_W_MAUSOLEUM,
                     {PRIM_SA, PRIM_UR, PRIM_SU, PRIM_FS, PRIM_AL}, 5, NAME_SCOPE_REGION, 0, SITE_BIT(SITE_TOMB) | SITE_BIT(SITE_ALTAR)},
    [STYLE_MOUND]  = {"mound",  BIOME_OUTDOOR, TERRAIN_WALLED, FAMILY_BURIAL,   TM_EARTH,  "earthen wall", STYLE_W_MOUND,
                     {PRIM_GR, PRIM_SS, PRIM_BP, PRIM_UR}, 4, NAME_SCOPE_REGION, 0, SITE_BIT(SITE_GRAVE)},
    [STYLE_BURIAL_CAVE] = {"burial cavern", BIOME_CAVERN, TERRAIN_WALLED, FAMILY_BURIAL, TM_STONE, "rock wall", STYLE_W_BURIAL_CAVE,
                     {PRIM_BP, PRIM_ST, PRIM_UR, PRIM_MW, PRIM_DL}, 5, NAME_SCOPE_REGION, 0, SITE_BIT(SITE_STONE)},
};

/* Distinct salt so a region's style doesn't correlate with its biome. */
#define STYLE_SALT 0x57A1E5EDu

/* May style `s` be picked here? The waking region (the one holding chunk
 * 0, 0) only picks styles marked may_wake. */
static bool style_eligible(int s, Biome b, bool waking) {
    return STYLE_TABLE[s].biome == b && STYLE_TABLE[s].weight && (!waking || STYLE_TABLE[s].may_wake);
}

Style style_of(uint32_t seed, int chunk_x, int chunk_y) {
    Biome b = biome_of(seed, chunk_x, chunk_y);
    int rx = region_of(chunk_x), ry = region_of(chunk_y);
    bool waking = rx == region_of(0) && ry == region_of(0);
    uint32_t total = 0;
    Style only = STYLE_COUNT;
    int n = 0;
    for(int s = 0; s < STYLE_COUNT; s++)
        if(style_eligible(s, b, waking)) {
            total += STYLE_TABLE[s].weight;
            only = (Style)s;
            n++;
        }
    if(n <= 1) return only == STYLE_COUNT ? STYLE_CAVERN : only;
    uint32_t h = region_hash(seed ^ STYLE_SALT, rx, ry) % total;
    for(int s = 0; s < STYLE_COUNT; s++) {
        if(!style_eligible(s, b, waking)) continue;
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

int style_vocab_slot(Style s, uint8_t prim_id) {
    if((unsigned)s >= STYLE_COUNT) return -1;
    const StyleDef* d = &STYLE_TABLE[s];
    for(int k = 0; k < d->vocab_count; k++)
        if(d->vocab[k] == prim_id) return k;
    return -1;
}
