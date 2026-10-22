/*
 * arc.h — the corruption arc's verbs (spec 58 §58.5–§58.8, §58.17): what
 * picking things up and stepping on carvings teaches, sealing a site,
 * whether a region is cleansed, and which ways of the rite are open to the
 * player and ready.
 *
 * The rules only; the app owns the screens, the turns and the saving.
 * Pure: reads and changes the CharacterState (save_io.h, a plain struct)
 * and the RegionBook, nothing else. Host-tested.
 *
 * Copy follows spec 58 §58.9 (option A). Lines §58.9 doesn't draft are
 * marked DRAFT: the user's call.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "corruption.h"
#include "ritual.h"
#include "save_io.h"
#include "world.h"

/* Copy (§58.9, option A). */
#define ARC_LINE_READ        "a cramped hand. you mouth it."
#define ARC_LINE_SEAL        "you set the stone. it sits."
#define ARC_LINE_RITE        "the fog lifts off the road."
#define ARC_LINE_CORRUPT     "the stone is warm. it sweats."
#define ARC_LINE_SEALED      "cold stone. nothing in it."
#define ARC_LINE_ENTER       "no birds. the wells smell."
#define ARC_LINE_REFUSED     "the fog does not thin."
/* DRAFT lines (not in §58.9; voice law §C.5; the user's call). */
#define ARC_LINE_NO_WORDS    "the words won't come."
#define ARC_LINE_NO_ARTIFACT "you have nothing to set."
#define ARC_LINE_CARVED      "cut words. you mouth them."
#define ARC_LINE_WORN        "a worn mark."
#define ARC_LINE_RUNE        "a mark, cut deep."
#define ARC_LINE_MISSING     "something is still missing."
#define ARC_LINE_FAILED      "it does not take."
#define ARC_LINE_VIGIL       "you keep still."
#define ARC_LINE_BROKEN      "the vigil breaks."
#define ARC_LINE_NOT_YET     "not while it is unclean."

/* The ward recipe's id (recipes.c) and the kinds the ways use (loot.c). */
#define ARC_RECIPE_WARD   3
#define ARC_KIND_WARD     16
#define ARC_KIND_CANDLE   17
#define ARC_KIND_SALT     18
#define ARC_KIND_RELIC    19

/* The artifact kind that seals a site kind (loot.c ids 7..10). */
uint8_t arc_artifact_kind(uint8_t site_kind);

/* The World.arc entry at (x, y), or NULL. */
const void* arc_entry_at(const World* w, int x, int y, uint8_t* what, uint8_t* arg);

/* A pickup at (x, y) (before the tile is cleared): a word source or a tome
 * of making teaches on the spot. Returns the line to show, or NULL. */
const char* arc_pickup(const World* w, int x, int y, CharacterState* c);

/* What stepping onto a carving at (x, y) shows. */
typedef struct {
    const char* line;   /* NULL: not a carving */
    bool rune;          /* show `icon` (and `marks` dots) after the line */
    uint8_t icon[8];
    uint8_t marks;      /* an order puzzle's place, 1-based; 0 = none */
} ArcStep;

/* Steps onto a carving. A spoken piece is learned (the region's record);
 * a seen clue shows its rune if `sight` reaches SIGHT_READ_RUNE. */
void arc_step(uint32_t seed, int cx, int cy, const World* w, int x, int y, uint8_t sight,
              RegionBook* book, ArcStep* out);

/* The site at (x, y) of chunk (cx, cy): its index in the region's site
 * order, or -1. */
int arc_site_at(uint32_t seed, int cx, int cy, const World* w, int x, int y);

bool arc_site_sealed(const RegionBook* book, int rx, int ry, int k);

/* Is the region cleansed: every site sealed (route 1), or every one of its
 * dead destroyed (route 2)? */
bool arc_region_cleansed(uint32_t seed, int rx, int ry, const RegionBook* book);

typedef enum {
    ARC_SEALED = 0,
    ARC_ALREADY,
    ARC_NEED_WORDS,
    ARC_NEED_ARTIFACT,
    ARC_BOOK_FULL,
} ArcSealResult;

/* Seal site k (of kind `kind`) in region (rx, ry): needs the words for its
 * kind and an artifact of its kind, which is consumed. */
ArcSealResult arc_seal(int rx, int ry, int k, uint8_t kind, CharacterState* c, RegionBook* book);
const char* arc_seal_line(ArcSealResult r);

/* The ways of the region's rite this player has the skill for (`axes`:
 * the six effective axes). */
uint8_t arc_ways_open(uint32_t seed, int rx, int ry, const uint8_t* axes);

/* Has the player gathered what way `way` needs? */
bool arc_way_ready(uint32_t seed, int rx, int ry, RitualWay way, const CharacterState* c,
                   const RegionBook* book);

/* A rite took hold by `way`: spend what it consumes (the ward, the focus
 * objects). Nothing is spent on failure (§58.7.4). */
void arc_way_spend(RitualWay way, CharacterState* c);

/* In-game names of the ways (no user terms on the status bar, §58.9). */
const char* arc_way_name(RitualWay way);
