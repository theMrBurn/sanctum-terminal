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
 * shift aside. A hollow dealt to a chunk with no such prop falls to the
 * next chunk on its chain (HOLLOW_CHAIN; deciding that generates the
 * earlier ones, never reads deltas); past the chain it is lost (rare,
 * measured in the tests).
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

/* The kinds (loot.c) the hollows hold. The tools: one per HollowKind, in
 * that order, so HOLLOW_TOOL_KIND + kind is the tool that opens it. */
#define HOLLOW_TOOL_KIND  25   /* knotted rope, horn lantern, pry-iron */
#define HOLLOW_KIND_TOKEN 28   /* a rare thing, self-describing (barter-ready, §58.16) */
#define HOLLOW_KIND_LORE  29   /* a fragment: read, never explains (§58.14) */
#define HOLLOWS_PER_REGION_MAX 2
#define HOLLOW_CHAIN 3            /* a hollow falls to the next chunk dealt when one has no fit prop */

/* The kind of mouth a glyph can hold, or HOLLOW_NONE. */
uint8_t hollow_kind_of(char glyph);

/* How many hollows region (rx, ry) holds (its style's count). */
int region_hollow_count(uint32_t seed, int rx, int ry);

/* Which of its region's hollows chunk (cx, cy) is dealt (0..count-1), or -1. */
int chunk_hollow_index(uint32_t seed, int cx, int cy);

#include "corruption.h"
#include "save_io.h"

#define REACH_AXIS_THRESHOLD 22   /* the skill way in (the user's, 2026-10-26; secrets ask 16) */
#define HOLLOW_EFFORT_TURNS   2
#define HOLLOW_EFFORT_DIFF    4

/* Copy (voice law §C.5). The refusal confirms what you see; the same line
 * when the body gives out partway (what was spent stays spent). The climb
 * line is the user's (2026-10-26); the others are DRAFT. */
#define HOLLOW_LINE_CLIMB "a ledge. your hands slip."
#define HOLLOW_LINE_DARK  "the dark there drinks the light."     /* DRAFT */
#define HOLLOW_LINE_SHIFT "it will not shift."                   /* DRAFT */
#define HOLLOW_LINE_LORE  "old ink. a name, scraped off."        /* DRAFT: the vellum read */
const char* hollow_refusal(uint8_t kind);

/* The axis the skill way leans on: BODY to climb, SIGHT for the dark,
 * CRAFT to shift (DEED_AXIS_*). */
uint8_t hollow_axis(uint8_t kind);

/* The tool (a kind id) that opens a hollow of `kind`. */
uint8_t hollow_tool(uint8_t kind);

typedef enum {
    HOLLOW_SHUT = 0,    /* the region's rite isn't done: no hollow shows */
    HOLLOW_BY_TOOL,     /* you carry its tool: you pass, unannounced */
    HOLLOW_BY_SKILL,    /* skill at the threshold: an effort task */
    HOLLOW_REFUSED,     /* neither: the refusal line */
} HollowWay;

HollowWay hollow_way(uint8_t kind, bool rite_done, const CharacterState* c, uint8_t axis_eff);

/* What hollow `index` of region (rx, ry), of kind `kind`, holds (a kind
 * id): half the time the tool for one of the OTHER kinds (one hollow opens
 * the next), else a carved token or a vellum scrap. */
uint8_t hollow_find(uint32_t seed, int rx, int ry, int index, uint8_t kind);

/* Its find is taken (RegionRecord flags; saved in regions.txt). */
bool hollow_taken(const RegionBook* b, int rx, int ry, int index);
/* Mark it taken. False only if the book is full. */
bool hollow_take(RegionBook* b, int rx, int ry, int index);

/* Build hollow `index`'s pocket into w: a short dead-end passage walled in
 * the region's style but enclosed (cavern biome: no sky, no weather), the way out a door on its west edge (w->spawn is just
 * inside it), the find at the far end unless taken. No site, no ritual
 * objects, no hollow, no closed edges: rot never reaches a pocket. */
void hollow_pocket(uint32_t seed, int rx, int ry, int index, uint8_t kind, bool taken, World* w);

/* Mark the chunk's mouth into w (hollow_kind, hollow_x, hollow_y,
 * hollow_index), from the generated tiles. Call right after generation,
 * before deltas. Returns true if the chunk has one. */
bool hollow_mark(uint32_t seed, int cx, int cy, World* w);
