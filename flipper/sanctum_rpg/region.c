/* region.c — see region.h. */
#include "region.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "biome.h"

/* Salt so the inward pick doesn't correlate with the region's style. */
#define REGION_INWARD_SALT 0x1A7E3D2Bu

void region_origin(uint32_t seed, int* ox, int* oy) {
    (void)seed;   /* the waking chunk is (0, 0) for every seed */
    *ox = region_of(0);
    *oy = region_of(0);
}

int region_depth(uint32_t seed, int rx, int ry) {
    int ox, oy;
    region_origin(seed, &ox, &oy);
    return abs(rx - ox) + abs(ry - oy);
}

void region_inward(uint32_t seed, int rx, int ry, int* ix, int* iy) {
    int ox, oy;
    region_origin(seed, &ox, &oy);
    int dx = rx - ox, dy = ry - oy;
    int sx = dx > 0 ? -1 : 1, sy = dy > 0 ? -1 : 1;   /* step toward the origin */
    *ix = rx;
    *iy = ry;
    if(dx == 0 && dy == 0) return;
    if(dx == 0) { *iy = ry + sy; return; }
    if(dy == 0) { *ix = rx + sx; return; }
    uint32_t h = region_hash(seed ^ REGION_INWARD_SALT, rx, ry);
    if(h & 1u) *ix = rx + sx;
    else       *iy = ry + sy;
}

void region_rituals_clear(RegionRituals* r) { r->count = 0; }

bool region_ritual_done(const RegionRituals* r, int rx, int ry) {
    for(int i = 0; i < r->count; i++)
        if(r->rx[i] == rx && r->ry[i] == ry) return true;
    return false;
}

bool region_mark_ritual(RegionRituals* r, int rx, int ry) {
    if(region_ritual_done(r, rx, ry)) return true;
    if(r->count >= REGION_DONE_MAX) return false;
    r->rx[r->count] = (int16_t)rx;
    r->ry[r->count] = (int16_t)ry;
    r->count++;
    return true;
}

bool region_open(uint32_t seed, const RegionRituals* r, int rx, int ry) {
    if(region_depth(seed, rx, ry) == 0) return true;
    int ix, iy;
    region_inward(seed, rx, ry, &ix, &iy);
    return region_ritual_done(r, ix, iy);
}

bool region_edge_closed(uint32_t seed, const RegionRituals* r, int cx, int cy, MoveDir dir) {
    int nx = cx, ny = cy;
    switch(dir) {
    case MoveNorth: ny--; break;
    case MoveSouth: ny++; break;
    case MoveWest:  nx--; break;
    case MoveEast:  nx++; break;
    default: return false;
    }
    int rx = region_of(nx), ry = region_of(ny);
    if(rx == region_of(cx) && ry == region_of(cy)) return false;
    /* Only the tree's border refuses. A player standing in a region that is
     * itself closed (a save from before the gates, spec 58 §58.4) may walk
     * anywhere until back inside it: leaving is always allowed, and no one
     * is walled in where they woke up. */
    if(!region_open(seed, r, region_of(cx), region_of(cy))) return false;
    return !region_open(seed, r, rx, ry);
}

void region_mark_world_edges(uint32_t seed, const RegionRituals* r, int cx, int cy, World* w) {
    w->closed_edges = 0;
    if(region_edge_closed(seed, r, cx, cy, MoveNorth)) w->closed_edges |= 1u << WORLD_SEAM_N;
    if(region_edge_closed(seed, r, cx, cy, MoveSouth)) w->closed_edges |= 1u << WORLD_SEAM_S;
    if(region_edge_closed(seed, r, cx, cy, MoveWest))  w->closed_edges |= 1u << WORLD_SEAM_W;
    if(region_edge_closed(seed, r, cx, cy, MoveEast))  w->closed_edges |= 1u << WORLD_SEAM_E;
}

size_t region_rituals_format(const RegionRituals* r, char* out, size_t cap) {
    if(cap == 0) return 0;
    size_t n = (size_t)snprintf(out, cap, "v1\n");
    for(int i = 0; i < r->count && n < cap; i++)
        n += (size_t)snprintf(out + n, cap - n, "%d %d\n", r->rx[i], r->ry[i]);
    return n < cap ? n : cap - 1;
}

void region_rituals_parse(const char* text, RegionRituals* out) {
    region_rituals_clear(out);
    if(!text || strncmp(text, "v1\n", 3) != 0) return;
    const char* p = text + 3;
    while(*p) {
        int rx, ry;
        if(sscanf(p, "%d %d", &rx, &ry) == 2) region_mark_ritual(out, rx, ry);
        const char* nl = strchr(p, '\n');
        if(!nl) break;
        p = nl + 1;
    }
}
