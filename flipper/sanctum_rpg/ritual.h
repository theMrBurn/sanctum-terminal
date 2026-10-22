/*
 * ritual.h — what a region needs to be cleansed and opened (spec 58 §58.5,
 * §58.7, §58.17), derived from the seed and the region, never saved.
 *
 *   region_sites    the region's sites, in site order (the bit order of
 *                   RegionRecord.sealed)
 *   region_rite     the ways it offers, their skill thresholds, the rite's
 *                   difficulty, the spoken pieces and the seen puzzle
 *   region_objects  everything WORLDGEN 9 places for it: artifacts, word
 *                   sources, carvings, the made way's tome and components,
 *                   the kept way's focus objects
 *   rune_*          the seen way's puzzle and its clues
 *
 * Every pick is region_hash with its own salt, never an RNG stream, so
 * nothing here moves another roll. Pure, host-tested.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "effort.h"
#include "site.h"

/* The four ways (§58.7.1). */
typedef enum {
    WAY_SPOKEN = 0,   /* the region's words, gathered piece by piece */
    WAY_MADE,         /* a ward made at the forge and set at the site */
    WAY_KEPT,         /* a vigil with focus objects; interruption restarts it */
    WAY_SEEN,         /* the rune puzzle, solved from carved clues */
    WAY_COUNT,
} RitualWay;

#define WAY_BIT(w) ((uint8_t)(1u << (w)))

/* Tunables (§58.17). */
#define ARTIFACT_SPARE        1    /* artifacts beyond one per site */
#define RITE_SKILL_EASY       8    /* the easiest way: the lowest axis a fresh character can have
                                    * (Profile Review never lets one below 8; the default is 10) */
#define RITE_TURNS_SPOKEN     4
#define RITE_TURNS_MADE       2
#define RITE_TURNS_KEPT       6
#define RITE_SEEN_ATTEMPTS    4    /* the seen way's turns: one per attempt */
#define SPOKEN_PIECES_MAX     4
#define RUNES_MIN             3
#define RUNES_MAX             4
#define RUNE_SHAPES           6    /* distinct rune glyphs */
#define SIGHT_READ_RUNE       12   /* SIGHT needed to read a clue's rune */

typedef enum { PUZZLE_TURN = 0, PUZZLE_ORDER, PUZZLE_BOTH } PuzzleKind;

typedef struct {
    int16_t cx, cy;    /* the site's chunk */
    uint8_t kind;      /* SiteKind */
} RegionSite;

typedef struct {
    uint8_t ways;                 /* WAY_BIT set offered here (2..4 ways) */
    uint8_t easiest;              /* RitualWay with threshold RITE_SKILL_EASY */
    uint8_t threshold[WAY_COUNT]; /* skill a way asks; 0 = not offered */
    uint8_t difficulty;           /* effort per rite turn */
    uint8_t pieces;               /* spoken pieces (if spoken is offered) */
    uint8_t runes;                /* seen: runes at the site */
    uint8_t puzzle;               /* PuzzleKind */
} RegionRite;

/* WORLDGEN 9 objects. */
typedef enum {
    ARC_ARTIFACT = 0,  /* arg: SiteKind it seals */
    ARC_SOURCE,        /* arg: SiteKind whose words it teaches */
    ARC_PIECE,         /* arg: piece index (a carving) */
    ARC_MADE_TOME,     /* teaches the ward */
    ARC_COMPONENT,     /* arg: 0 cord, 1 iron nail */
    ARC_FOCUS,         /* arg: 0 candle, 1 salt, 2 relic */
    ARC_CLUE,          /* arg: rune index (a carving) */
    ARC_KIND_COUNT,
} ArcObjectKind;

#define ARC_OBJECTS_MAX (SITES_PER_REGION_MAX + ARTIFACT_SPARE + SITE_KIND_COUNT + SPOKEN_PIECES_MAX + 3 + 3 + RUNES_MAX)

typedef struct {
    uint8_t what;      /* ArcObjectKind */
    uint8_t arg;
    int16_t cx, cy;    /* the chunk it is placed in */
} ArcObject;

/* The carving's glyph: a walkable floor marking (terrain.c). */
#define TILE_CARVING 'C'

/* The region's sites, in site order. Returns the count (<= SITES_PER_REGION_MAX). */
int region_sites(uint32_t seed, int rx, int ry, RegionSite* out);

void region_rite(uint32_t seed, int rx, int ry, RegionRite* out);

/* The effort a way's rite asks. */
EffortTask ritual_task(const RegionRite* rite, RitualWay way);

/* The axis a way leans on: the better of `a` and `b` where it names two. */
uint8_t ritual_way_axis(RitualWay way, const uint8_t* axes /* DEED_AXIS_COUNT */);

/* Everything WORLDGEN 9 places for the region, in placement order. */
int region_objects(uint32_t seed, int rx, int ry, ArcObject* out);

/* The tile glyph an object is placed as. */
char arc_object_glyph(uint32_t seed, int rx, int ry, const ArcObject* o, int index);

/* The seen puzzle. Each rune has a shape, a correct turn (0..3, a quarter
 * turn each) and a place in the order; the puzzle starts each rune at a
 * wrong turn and shows them in a shuffled order. */
typedef struct {
    uint8_t count;
    uint8_t kind;               /* PuzzleKind */
    uint8_t shape[RUNES_MAX];
    uint8_t turn[RUNES_MAX];    /* the answer: each rune's turn */
    uint8_t start[RUNES_MAX];   /* the turn each rune starts at */
    uint8_t order[RUNES_MAX];   /* the answer: the rune touched k-th */
} RunePuzzle;

void rune_puzzle(uint32_t seed, int rx, int ry, RunePuzzle* out);

/* Is `turns` (and `touched`, the order the player touched them in) the
 * answer? Only the parts the puzzle's kind asks for are checked. */
bool rune_answer(const RunePuzzle* p, const uint8_t* turns, const uint8_t* touched);

/* 8x8 XBM of a rune shape at a turn (0..3). */
void rune_icon(uint8_t shape, uint8_t turn, uint8_t out[8]);
