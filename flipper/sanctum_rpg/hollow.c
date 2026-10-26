/* hollow.c — see hollow.h. */
#include "hollow.h"

#include <string.h>

#include "biome.h"
#include "style.h"

#define HOLLOW_SLOT_SALT  0x4011A0E5u
#define HOLLOW_TILE_SALT  0x7EA11D0Bu

/* What each prop can hide (spec 58 §58.15 as built: walls stand only on a
 * chunk's border, so the dark is under or up a prop, not in a wall). */
static const struct { char glyph; uint8_t kind; } MOUTHS[] = {
    {'Y', HOLLOW_CLIMB}, {'y', HOLLOW_CLIMB}, {'|', HOLLOW_CLIMB},   /* tree, dead tree, column */
    {'O', HOLLOW_CLIMB}, {'Z', HOLLOW_CLIMB}, {'l', HOLLOW_CLIMB},   /* great column, statue, timber prop */
    {'M', HOLLOW_DARK},  {'A', HOLLOW_DARK},  {'I', HOLLOW_DARK},    /* flowstone, stalagmite, standing stone */
    {'w', HOLLOW_DARK},                                              /* a hearth's flue */
    {'^', HOLLOW_SHIFT}, {'~', HOLLOW_SHIFT}, {'Q', HOLLOW_SHIFT},   /* rubble, deadfall, cairn */
    {'c', HOLLOW_SHIFT}, {'d', HOLLOW_SHIFT}, {'U', HOLLOW_SHIFT},   /* ore cart, barrel, funeral urn */
    {'k', HOLLOW_SHIFT}, {'m', HOLLOW_SHIFT}, {'p', HOLLOW_SHIFT},   /* weapon rack, table, pew */
    {'v', HOLLOW_SHIFT},                                             /* brazier */
};

uint8_t hollow_kind_of(char glyph) {
    for(unsigned i = 0; i < sizeof(MOUTHS) / sizeof(MOUTHS[0]); i++)
        if(MOUTHS[i].glyph == glyph) return MOUTHS[i].kind;
    return HOLLOW_NONE;
}

int region_hollow_count(uint32_t seed, int rx, int ry) {
    Style s = style_of(seed, rx * BIOME_REGION, ry * BIOME_REGION);
    int n = STYLE_TABLE[s].hollows;
    return n > HOLLOWS_PER_REGION_MAX ? HOLLOWS_PER_REGION_MAX : n;
}

static uint32_t mix(uint32_t h) {
    h ^= h >> 15; h *= 0x2C1B3C6Du; h ^= h >> 12;
    return h;
}

int chunk_hollow_index(uint32_t seed, int cx, int cy) {
    int rx = region_of(cx), ry = region_of(cy);
    const int n = BIOME_REGION * BIOME_REGION;
    uint8_t order[BIOME_REGION * BIOME_REGION];
    for(int i = 0; i < n; i++) order[i] = (uint8_t)i;
    uint32_t h = region_hash(seed ^ HOLLOW_SLOT_SALT, rx, ry);
    for(int i = n - 1; i > 0; i--) {                     /* Fisher-Yates, as site.c deals sites */
        h = mix(h);
        int j = (int)(h % (uint32_t)(i + 1));
        uint8_t t = order[i]; order[i] = order[j]; order[j] = t;
    }
    int slot = (cx - rx * BIOME_REGION) + BIOME_REGION * (cy - ry * BIOME_REGION);
    int count = region_hollow_count(seed, rx, ry);
    for(int k = 0; k < count; k++)
        if(order[k] == slot) return k;
    return -1;
}

static bool is_arc_object(const World* w, int x, int y) {
    for(int a = 0; a < w->arc_count; a++)
        if(w->arc[a].x == x && w->arc[a].y == y) return true;
    return false;
}

bool hollow_mark(uint32_t seed, int cx, int cy, World* w) {
    w->hollow_kind = HOLLOW_NONE;
    w->hollow_x = w->hollow_y = -1;
    w->hollow_index = -1;
    int k = chunk_hollow_index(seed, cx, cy);
    if(k < 0) return false;
    uint8_t reach[WORLD_ROWS][WORLD_COLS];
    memset(reach, 0, sizeof(reach));
    world_reach(w, w->spawn_x, w->spawn_y, reach);
    const int iw = WORLD_COLS - 2, ih = WORLD_ROWS - 2, cells = iw * ih;
    int start = (int)(mix(region_hash(seed ^ HOLLOW_TILE_SALT, cx, cy)) % (uint32_t)cells);
    for(int i = 0; i < cells; i++) {
        int c = (start + i) % cells;
        int x = 1 + c % iw, y = 1 + c / iw;              /* off the border ring */
        uint8_t kind = hollow_kind_of(w->tiles[y][x]);
        if(kind == HOLLOW_NONE) continue;
        if(x == w->site_x && y == w->site_y) continue;
        if(is_arc_object(w, x, y)) continue;
        if(!(reach[y][x - 1] || reach[y][x + 1] || reach[y - 1][x] || reach[y + 1][x])) continue;
        w->hollow_kind = kind;
        w->hollow_x = (int8_t)x;
        w->hollow_y = (int8_t)y;
        w->hollow_index = (int8_t)k;
        return true;
    }
    return false;
}
