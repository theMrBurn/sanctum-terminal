/* hollow.c — see hollow.h. */
#include "hollow.h"

#include <string.h>

#include "biome.h"
#include "deeds.h"
#include "loot.h"
#include "style.h"

#define HOLLOW_SLOT_SALT  0x4011A0E5u
#define HOLLOW_TILE_SALT  0x7EA11D0Bu
#define HOLLOW_FIND_SALT  0x0F1D0F1Du
#define HOLLOW_ROOM_SALT  0x2C0FFEE5u

/* What each prop can hide (spec 58 §58.15 as built: walls stand only on a
 * chunk's border, so the dark is under or up a prop, not in a wall). */
static const struct { char glyph; uint8_t kind; } MOUTHS[] = {
    /* props only: a slab (a column, flowstone) is drawn as a wall and could
     * never show its mouth */
    {'Y', HOLLOW_CLIMB}, {'y', HOLLOW_CLIMB},                        /* tree, dead tree */
    {'Z', HOLLOW_CLIMB}, {'l', HOLLOW_CLIMB},                        /* statue, timber prop */
    {'A', HOLLOW_DARK},  {'I', HOLLOW_DARK},                         /* stalagmite, standing stone */
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

/* The region's chunk slots in a dealt order (Fisher-Yates, as site.c). */
static void hollow_order(uint32_t seed, int rx, int ry, uint8_t order[BIOME_REGION * BIOME_REGION]) {
    const int n = BIOME_REGION * BIOME_REGION;
    for(int i = 0; i < n; i++) order[i] = (uint8_t)i;
    uint32_t h = region_hash(seed ^ HOLLOW_SLOT_SALT, rx, ry);
    for(int i = n - 1; i > 0; i--) {
        h = mix(h);
        int j = (int)(h % (uint32_t)(i + 1));
        uint8_t t = order[i]; order[i] = order[j]; order[j] = t;
    }
}

/* Hollow k's chain: order[k], then order[count + k], order[2*count + k]...
 * (HOLLOW_CHAIN long). The first chunk on it with a fit prop holds it. */
static int chain_slot(const uint8_t* order, int count, int k, int j) {
    int pos = j * count + k;
    return pos < BIOME_REGION * BIOME_REGION ? order[pos] : -1;
}

static void chunk_of_slot(int rx, int ry, int slot, int* cx, int* cy) {
    *cx = rx * BIOME_REGION + slot % BIOME_REGION;
    *cy = ry * BIOME_REGION + slot / BIOME_REGION;
}

static bool is_arc_object(const World* w, int x, int y) {
    for(int a = 0; a < w->arc_count; a++)
        if(w->arc[a].x == x && w->arc[a].y == y) return true;
    return false;
}

/* The mouth tile in a generated chunk, or false if it has no fit prop. */
static bool find_mouth(uint32_t seed, int cx, int cy, const World* w, int* mx, int* my) {
    uint8_t reach[WORLD_ROWS][WORLD_COLS];
    memset(reach, 0, sizeof(reach));
    world_reach(w, w->spawn_x, w->spawn_y, reach);
    const int iw = WORLD_COLS - 2, ih = WORLD_ROWS - 2, cells = iw * ih;
    int start = (int)(mix(region_hash(seed ^ HOLLOW_TILE_SALT, cx, cy)) % (uint32_t)cells);
    for(int i = 0; i < cells; i++) {
        int c = (start + i) % cells;
        int x = 1 + c % iw, y = 1 + c / iw;              /* off the border ring */
        if(hollow_kind_of(w->tiles[y][x]) == HOLLOW_NONE) continue;
        if(x == w->site_x && y == w->site_y) continue;
        if(is_arc_object(w, x, y)) continue;
        if(!(reach[y][x - 1] || reach[y][x + 1] || reach[y - 1][x] || reach[y + 1][x])) continue;
        *mx = x; *my = y;
        return true;
    }
    return false;
}

int chunk_hollow_index(uint32_t seed, int cx, int cy) {
    int rx = region_of(cx), ry = region_of(cy);
    uint8_t order[BIOME_REGION * BIOME_REGION];
    hollow_order(seed, rx, ry, order);
    int slot = (cx - rx * BIOME_REGION) + BIOME_REGION * (cy - ry * BIOME_REGION);
    int count = region_hollow_count(seed, rx, ry);
    for(int j = 0; j < HOLLOW_CHAIN; j++)
        for(int k = 0; k < count; k++)
            if(chain_slot(order, count, k, j) == slot) return k;
    return -1;
}

bool hollow_mark(uint32_t seed, int cx, int cy, World* w) {
    w->hollow_kind = HOLLOW_NONE;
    w->hollow_x = w->hollow_y = -1;
    w->hollow_index = -1;
    int rx = region_of(cx), ry = region_of(cy);
    uint8_t order[BIOME_REGION * BIOME_REGION];
    hollow_order(seed, rx, ry, order);
    int slot = (cx - rx * BIOME_REGION) + BIOME_REGION * (cy - ry * BIOME_REGION);
    int count = region_hollow_count(seed, rx, ry);
    for(int k = 0; k < count; k++)
        for(int j = 0; j < HOLLOW_CHAIN; j++) {
            int s = chain_slot(order, count, k, j);
            if(s < 0) break;
            if(s != slot) continue;
            /* this chunk is j-th on hollow k's chain: it holds it if every
             * earlier one has no fit prop (their generated tiles, never deltas) */
            for(int e = 0; e < j; e++) {
                int ex, ey, mx, my;
                chunk_of_slot(rx, ry, chain_slot(order, count, k, e), &ex, &ey);
                World other;
                world_generate_chunk(seed, ex, ey, &other);
                if(find_mouth(seed, ex, ey, &other, &mx, &my)) return false;
            }
            int mx, my;
            if(!find_mouth(seed, cx, cy, w, &mx, &my)) return false;
            w->hollow_kind = hollow_kind_of(w->tiles[my][mx]);
            w->hollow_x = (int8_t)mx;
            w->hollow_y = (int8_t)my;
            w->hollow_index = (int8_t)k;
            return true;
        }
    return false;
}

uint8_t hollow_axis(uint8_t kind) {
    return kind == HOLLOW_CLIMB ? DEED_AXIS_BODY : kind == HOLLOW_DARK ? DEED_AXIS_SIGHT : DEED_AXIS_CRAFT;
}

uint8_t hollow_tool(uint8_t kind) { return (uint8_t)(HOLLOW_TOOL_KIND + kind); }

HollowWay hollow_way(uint8_t kind, bool rite_done, const CharacterState* c, uint8_t axis_eff) {
    if(!rite_done || kind >= HOLLOW_KIND_COUNT) return HOLLOW_SHUT;
    if(c->inv_qty[hollow_tool(kind)]) return HOLLOW_BY_TOOL;
    if(axis_eff >= REACH_AXIS_THRESHOLD) return HOLLOW_BY_SKILL;
    return HOLLOW_REFUSED;
}

uint8_t hollow_find(uint32_t seed, int rx, int ry, int index, uint8_t kind) {
    uint32_t h = mix(region_hash(seed ^ HOLLOW_FIND_SALT ^ (uint32_t)(index * 0x9E3779B9u), rx, ry));
    switch(h & 3u) {
    case 0: case 1: {                                    /* a tool for another kind */
        uint8_t other = (uint8_t)((kind + 1 + ((h >> 2) & 1u)) % HOLLOW_KIND_COUNT);
        return hollow_tool(other);
    }
    case 2:  return HOLLOW_KIND_TOKEN;
    default: return HOLLOW_KIND_LORE;
    }
}

bool hollow_taken(const RegionBook* b, int rx, int ry, int index) {
    const RegionRecord* r = region_book_get(b, rx, ry);
    return r && index >= 0 && index < HOLLOWS_PER_REGION_MAX && (r->flags & RR_HOLLOW_TAKEN(index));
}

bool hollow_take(RegionBook* b, int rx, int ry, int index) {
    if(index < 0 || index >= HOLLOWS_PER_REGION_MAX) return false;
    RegionRecord* r = region_book_touch(b, rx, ry);
    if(!r) return false;
    r->flags |= (uint8_t)RR_HOLLOW_TAKEN(index);
    return true;
}

void hollow_pocket(uint32_t seed, int rx, int ry, int index, uint8_t kind, bool taken, World* w) {
    memset(w, 0, sizeof(*w));
    /* enclosed whatever the region above: an open style (moor, forest:
     * rock walls) is walled as a cavern, the same rock, so no sky, no far
     * ridge and the weather muffled, as indoors */
    w->style = style_of(seed, rx * BIOME_REGION, ry * BIOME_REGION);
    if(style_terrain(w->style) == TERRAIN_OPEN) w->style = STYLE_CAVERN;
    w->biome = BIOME_CAVERN;
    world_clear_seams(w);
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) w->tiles[y][x] = TILE_WALL;
    uint32_t h = mix(region_hash(seed ^ HOLLOW_ROOM_SALT ^ (uint32_t)(index * 0x85EBCA6Bu), rx, ry));
    int len = 4 + (int)(h % 6u);                        /* 4..9 cells in */
    int y0 = 1 + (int)((h >> 4) % 3u);                  /* a two-row passage: rows y0, y0+1 (1..4) */
    for(int x = 1; x <= len; x++) {
        w->tiles[y0][x] = TILE_FLOOR;
        w->tiles[y0 + 1][x] = TILE_FLOOR;
    }
    int nook = 2 + (int)((h >> 8) % (uint32_t)(len - 1));   /* a nook up or down off the passage */
    int ny = y0 == 1 ? y0 + 2 : y0 - 1;
    if(ny >= 1 && ny <= WORLD_ROWS - 2) w->tiles[ny][nook] = TILE_FLOOR;
    w->tiles[y0][0] = TILE_DOOR;                        /* the way out */
    w->spawn_x = 1;
    w->spawn_y = y0;
    if(!taken) {
        const KindDef* f = kind_by_id(hollow_find(seed, rx, ry, index, kind));
        if(f) w->tiles[y0 + 1][len] = f->glyph;
    }
}

const char* hollow_refusal(uint8_t kind) {
    return kind == HOLLOW_CLIMB ? HOLLOW_LINE_CLIMB : kind == HOLLOW_DARK ? HOLLOW_LINE_DARK : HOLLOW_LINE_SHIFT;
}
