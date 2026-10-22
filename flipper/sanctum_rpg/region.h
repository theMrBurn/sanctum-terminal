/*
 * region.h — the region tree (spec 58 §58.3): which regions the player may
 * enter.
 *
 * A region is the 3x3-chunk area that already fixes a biome, a style and a
 * built place's name (biome.h region_of). Corruption is contained region by
 * region, and the world opens outward from an origin along a tree:
 *
 *   depth(r)  = |rx - ox| + |ry - oy|          Manhattan, origin at depth 0
 *   inward(r) = the cardinal neighbour one step closer to the origin
 *               (by hash where two qualify)
 *   open(r)   = r is the origin, or inward(r)'s ritual is done
 *
 * Manhattan, not Chebyshev: under Chebyshev a corner region has no cardinal
 * neighbour one step closer, and the chain breaks at every diagonal (the
 * reason barrow-jl's region tree, chunk.jl, uses it).
 *
 * The origin is the region the player wakes in (chunk 0, 0). Each seed's
 * world is different, so what the origin is (its style, its sites) is
 * already random per seed.
 *
 * Pure module — integer math, no SDK, host-testable. The rituals-done set
 * is player state (a saved event record, spec 43 §14.0); the tree itself
 * is derived from the seed and never saved.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "world.h"

/* Rituals a campaign remembers. Each ring of depth d holds 4d regions, so
 * 64 covers every region out to depth 5 with room to spare. */
#define REGION_DONE_MAX 64

/* Save-file line budget: "v1\n" plus "<rx> <ry>\n" per region. */
#define REGION_DONE_TEXT_MAX (4 + REGION_DONE_MAX * 14)

typedef struct {
    int16_t rx[REGION_DONE_MAX];
    int16_t ry[REGION_DONE_MAX];
    uint8_t count;
} RegionRituals;

/* The origin region (the one holding the waking chunk 0, 0). */
void region_origin(uint32_t seed, int* ox, int* oy);

/* Manhattan distance from the origin region. */
int region_depth(uint32_t seed, int rx, int ry);

/* The region one step inward toward the origin. The origin returns itself.
 * Where both axes are off-origin, the region's hash picks which one. */
void region_inward(uint32_t seed, int rx, int ry, int* ix, int* iy);

void region_rituals_clear(RegionRituals* r);
bool region_ritual_done(const RegionRituals* r, int rx, int ry);
/* Record a region's ritual. Idempotent; false only if the set is full. */
bool region_mark_ritual(RegionRituals* r, int rx, int ry);

/* May the player be in (enter) this region? */
bool region_open(uint32_t seed, const RegionRituals* r, int rx, int ry);

/* Does crossing chunk (cx, cy)'s edge in `dir` lead into a closed region
 * from an open one? Crossings inside one region are never closed, and
 * neither is any crossing out of a closed region (an old save stranded
 * outside the tree walks home freely). */
bool region_edge_closed(uint32_t seed, const RegionRituals* r, int cx, int cy, MoveDir dir);

/* Mark which of chunk (cx, cy)'s edges lead into a closed region
 * (World.closed_edges), for the haze. Call after generating the chunk. */
void region_mark_world_edges(uint32_t seed, const RegionRituals* r, int cx, int cy, World* w);

/* Save format: "v1" then one "<rx> <ry>" line per done ritual. */
size_t region_rituals_format(const RegionRituals* r, char* out, size_t cap);
/* Parse that text. Unknown versions and bad lines are skipped (tolerant
 * saves, spec 43 §14.0). */
void region_rituals_parse(const char* text, RegionRituals* out);
