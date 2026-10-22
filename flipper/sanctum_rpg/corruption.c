/* corruption.c — see corruption.h. */
#include "corruption.h"

#include <stdio.h>
#include <string.h>

#include "biome.h"
#include "region.h"

/* Salts keep these rolls independent of style, sites and the inward pick. */
#define WAVE_JITTER_SALT 0xC0EE7A11u
#define DEAD_COUNT_SALT  0xDEAD5EEDu

int corruption_intensity(uint32_t seed, int rx, int ry) {
    int d = region_depth(seed, rx, ry);
    if(d == 0) return 0;
    int x = d % WAVE_PERIOD;
    int tri = 2 * (x < WAVE_PERIOD - x ? x : WAVE_PERIOD - x);
    int v = d * WAVE_RAMP + d * WAVE_SWING * tri / WAVE_PERIOD;
    v += (int)(region_hash(seed ^ WAVE_JITTER_SALT, rx, ry) % (WAVE_JITTER + 1));
    return v > INTENSITY_MAX ? INTENSITY_MAX : v;
}

int corruption_dead_count(uint32_t seed, int rx, int ry) {
    int n = DEAD_PER_REGION_MIN + corruption_intensity(seed, rx, ry) / DEAD_PER_INTENSITY;
    n += (int)(region_hash(seed ^ DEAD_COUNT_SALT, rx, ry) & 1u);
    if(n > DEAD_PER_REGION_MAX) n = DEAD_PER_REGION_MAX;
    return n;
}

void region_book_clear(RegionBook* b) { b->count = 0; }

const RegionRecord* region_book_get(const RegionBook* b, int rx, int ry) {
    for(int i = 0; i < b->count; i++)
        if(b->rec[i].rx == rx && b->rec[i].ry == ry) return &b->rec[i];
    return NULL;
}

RegionRecord* region_book_touch(RegionBook* b, int rx, int ry) {
    for(int i = 0; i < b->count; i++)
        if(b->rec[i].rx == rx && b->rec[i].ry == ry) return &b->rec[i];
    if(b->count >= REGION_BOOK_MAX) return NULL;
    RegionRecord* r = &b->rec[b->count++];
    memset(r, 0, sizeof(*r));
    r->rx = (int16_t)rx;
    r->ry = (int16_t)ry;
    return r;
}

size_t region_book_format(const RegionBook* b, char* out, size_t cap) {
    if(cap == 0) return 0;
    size_t n = (size_t)snprintf(out, cap, "v1\n");
    for(int i = 0; i < b->count && n < cap; i++) {
        const RegionRecord* r = &b->rec[i];
        n += (size_t)snprintf(out + n, cap - n, "%d %d %u %u %u %u\n", r->rx, r->ry,
                              (unsigned)r->sealed, (unsigned)r->pieces,
                              (unsigned)r->destroyed, (unsigned)r->flags);
    }
    return n < cap ? n : cap - 1;
}

void region_book_parse(const char* text, RegionBook* out) {
    region_book_clear(out);
    if(!text || strncmp(text, "v1\n", 3) != 0) return;
    const char* p = text + 3;
    while(*p) {
        int rx, ry;
        unsigned s, pc, d, f;
        if(sscanf(p, "%d %d %u %u %u %u", &rx, &ry, &s, &pc, &d, &f) == 6) {
            RegionRecord* r = region_book_touch(out, rx, ry);
            if(r) {
                r->sealed = (uint8_t)s;
                r->pieces = (uint8_t)pc;
                r->destroyed = (uint8_t)(d > 255u ? 255u : d);
                r->flags = (uint8_t)f;
            }
        }
        const char* nl = strchr(p, '\n');
        if(!nl) break;
        p = nl + 1;
    }
}
