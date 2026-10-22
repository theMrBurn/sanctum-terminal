/* site.c — see site.h. */
#include "site.h"

#include "biome.h"
#include "style.h"

/* Salts keep site rolls independent of style, biome and the inward pick. */
#define SITE_COUNT_SALT 0x5173C0A1u
#define SITE_SLOT_SALT  0x5173510Bu
#define SITE_KIND_SALT  0x51737E9Du

const SiteDef SITE_TABLE[SITE_KIND_COUNT] = {
    [SITE_GRAVE] = {'g', "grave"},
    [SITE_TOMB]  = {'n', "tomb"},
    [SITE_ALTAR] = {'a', "altar"},
    [SITE_STONE] = {'h', "altar stone"},
};

int region_site_count(uint32_t seed, int rx, int ry) {
    uint32_t span = SITES_PER_REGION_MAX - SITES_PER_REGION_MIN + 1;
    return SITES_PER_REGION_MIN + (int)(region_hash(seed ^ SITE_COUNT_SALT, rx, ry) % span);
}

/* The region's chunk slots (0..8, row-major) in a seeded order: a
 * Fisher-Yates shuffle driven by one region hash, re-mixed per step. The
 * first region_site_count slots hold the sites. */
static void site_slots(uint32_t seed, int rx, int ry, uint8_t order[BIOME_REGION * BIOME_REGION]) {
    const int n = BIOME_REGION * BIOME_REGION;
    for(int i = 0; i < n; i++) order[i] = (uint8_t)i;
    uint32_t h = region_hash(seed ^ SITE_SLOT_SALT, rx, ry);
    for(int i = n - 1; i > 0; i--) {
        h ^= h >> 15; h *= 0x2C1B3C6Du; h ^= h >> 12;
        int j = (int)(h % (uint32_t)(i + 1));
        uint8_t t = order[i]; order[i] = order[j]; order[j] = t;
    }
}

uint8_t chunk_site_kind(uint32_t seed, int cx, int cy) {
    int rx = region_of(cx), ry = region_of(cy);
    int slot = (cx - rx * BIOME_REGION) + BIOME_REGION * (cy - ry * BIOME_REGION);
    uint8_t order[BIOME_REGION * BIOME_REGION];
    site_slots(seed, rx, ry, order);
    int count = region_site_count(seed, rx, ry);
    int k = -1;
    for(int i = 0; i < count; i++)
        if(order[i] == slot) k = i;
    if(k < 0) return SITE_NONE;
    uint8_t kinds = STYLE_TABLE[style_of(seed, cx, cy)].site_kinds;
    int allowed = 0;
    for(int s = 0; s < SITE_KIND_COUNT; s++) allowed += (kinds >> s) & 1u;
    if(allowed == 0) return SITE_NONE;
    /* Each site of the region rolls its own kind among the style's. */
    uint32_t pick = region_hash(seed ^ SITE_KIND_SALT ^ (uint32_t)(k * 0x9E3779B9u), rx, ry) % (uint32_t)allowed;
    for(int s = 0; s < SITE_KIND_COUNT; s++)
        if(((kinds >> s) & 1u) && pick-- == 0) return (uint8_t)s;
    return SITE_NONE;
}
