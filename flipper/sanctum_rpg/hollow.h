/*
 * hollow.h — hollows (spec 58 §58.15): one small pocket off the walkable
 * world per mouth, opened by a found tool or by skill, only once the
 * region's rite is done.
 *
 * Where the mouths are is decided at play time from what the generator
 * made, never from deltas, and with no world-gen bump: a region's style
 * says how many it holds (StyleDef.hollows); a region hash deals them to
 * its chunks, as the sites are dealt (site.c), never rng_chunk_seed (which
 * has mirror twins); a chunk dealt one cuts its mouth into a blocking prop
 * off the border, next to floor reachable from spawn. The prop says the
 * kind: what you climb, what you crawl into the dark under, what you
 * shift aside. A chunk with no such prop loses its hollow (measured in
 * the tests: rare).
 *
 * Pure, integer-only, host-testable.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "world.h"

typedef enum {
    HOLLOW_CLIMB = 0,   /* a tree, a column, a statue: a knotted rope, or BODY */
    HOLLOW_DARK,        /* under flowstone, a stalagmite, a standing stone, up a flue: a horn lantern, or SIGHT */
    HOLLOW_SHIFT,       /* rubble, deadfall, a cairn, a cart, a barrel, an urn, a rack: a pry-iron, or CRAFT */
    HOLLOW_KIND_COUNT,
} HollowKind;

#define HOLLOW_NONE 0xFFu
#define HOLLOWS_PER_REGION_MAX 2

/* The kind of mouth a glyph can hold, or HOLLOW_NONE. */
uint8_t hollow_kind_of(char glyph);

/* How many hollows region (rx, ry) holds (its style's count). */
int region_hollow_count(uint32_t seed, int rx, int ry);

/* Which of its region's hollows chunk (cx, cy) is dealt (0..count-1), or -1. */
int chunk_hollow_index(uint32_t seed, int cx, int cy);

/* Mark the chunk's mouth into w (hollow_kind, hollow_x, hollow_y,
 * hollow_index), from the generated tiles. Call right after generation,
 * before deltas. Returns true if the chunk has one. */
bool hollow_mark(uint32_t seed, int cx, int cy, World* w);
