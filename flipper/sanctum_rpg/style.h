/*
 * style.h — what KIND of place a region is.
 *
 * Every terrain type sits on two axes (SHARED_STATE 2026-10-14, "a region
 * has a style"):
 *
 *   biome   — UNDERGROUND (cavern) or ABOVE GROUND (outdoor). Owns loot,
 *             creatures, names, weather and the Pool (biome.h).
 *   style   — the place itself: natural cavern, crypt, old mine, moor,
 *             forest, hall... Owns ENCLOSED/OPEN (terrain mode), the wall
 *             material, the floor marks and the stamp catalog.
 *
 * A style belongs to one biome; each region (BIOME_REGION chunks square)
 * picks one style from its biome's rows by weight. Families group styles
 * for design and naming (caverns, dungeons, mines, moor, forest, ...).
 *
 * Data-table-driven (spec 43 §14.0): adding a style is one STYLE_TABLE row
 * plus its stamps; never `if style == ...` in logic. Pure, host-testable.
 */
#pragma once

#include <stdint.h>

#include "biome.h"

typedef enum {
    STYLE_CAVERN = 0,   /* natural cavern — the original cavern biome */
    STYLE_MOOR,         /* moor / heath — the original outdoor biome */
    STYLE_CRYPT,        /* dungeon: brick, niches, tombs */
    STYLE_MINE,         /* old mine: timber shoring, rails, rubble */
    STYLE_FOREST,       /* forest: trees, stumps, tall grass */
    STYLE_MANOR,        /* above ground, enclosed: a dwelling */
    STYLE_KEEP,         /* above ground, enclosed: a fortification */
    STYLE_ABBEY,        /* above ground, enclosed: a holy place */
    STYLE_MAUSOLEUM,    /* above ground, enclosed: a house for the dead */
    STYLE_MOUND,        /* above ground, enclosed: an earthen burial mound */
    STYLE_BURIAL_CAVE,  /* underground, rough: a small cavern of the dead */
    STYLE_COUNT,
} Style;

typedef enum {
    FAMILY_CAVERNS = 0, /* underground, natural, big */
    FAMILY_MOOR,        /* above ground, open, stones and scrub */
    FAMILY_DUNGEONS,    /* underground, built to hold or bury */
    FAMILY_MINES,       /* underground, dug for ore */
    FAMILY_FOREST,      /* above ground, open, wooded */
    FAMILY_DWELLINGS,   /* above ground, enclosed, lived in */
    FAMILY_FORTIFICATIONS, /* above ground, enclosed, held */
    FAMILY_HOLY,        /* above ground, enclosed, kept */
    FAMILY_BURIAL,      /* either realm: places made for the dead (spec 50 Q1) */
    FAMILY_COUNT,
} StyleFamily;

/* How far a place name reaches (names.c). */
#define NAME_SCOPE_CHUNK  0u   /* wild places: every chunk its own name */
#define NAME_SCOPE_REGION 1u   /* built places: the whole region shares one */

/* Pool bag slots that are seeded (pool.c seeds all POOL_BAG_SLOTS since
 * WORLDGEN 7; it seeded 6 before). */
#define STYLE_VOCAB_MAX 8

typedef struct {
    const char* name;
    Biome biome;          /* realm: underground / above ground */
    TerrainMode terrain;  /* enclosed (walled, doors) / open */
    uint8_t family;       /* StyleFamily */
    uint8_t wall_material;/* SlabMaterial for TILE_WALL in this style */
    const char* wall_name;/* what a wall here is called when examined */
    uint8_t weight;       /* pick weight among its biome's styles */
    /* The style's primitive vocabulary (PRIM_*), in Pool bag-slot order:
     * vocab[k] is biased by the Pool's bag slot k (stamps.c). The ORDER is
     * part of the generator — reordering moves the world (WORLDGEN bump).
     * Cavern starts {0..5}, so slot = id and its chunks predate this table.
     * New primitives are APPENDED (slots 6, 7), never inserted. */
    uint8_t vocab[STYLE_VOCAB_MAX];
    uint8_t vocab_count;
    uint8_t name_scope;   /* NAME_SCOPE_*: a built place has one name per region */
    uint8_t may_wake;     /* 1 = the waking region may be this style. The player
                           * wakes somewhere neutral: no burial place (spec 58) */
} StyleDef;

extern const StyleDef STYLE_TABLE[STYLE_COUNT];

/* The region's style for a chunk. Pure function of (seed, chunk coords);
 * every chunk of a region agrees. */
Style style_of(uint32_t seed, int chunk_x, int chunk_y);

/* The biome's original style (cavern -> STYLE_CAVERN, outdoor -> STYLE_MOOR):
 * for worlds built by hand (starter room, test fixtures). */
Style style_for_biome(Biome b);

/* The Pool bag slot that biases `prim_id` in style `s` (its index in
 * StyleDef.vocab), or -1 if the style has no such primitive. */
int style_vocab_slot(Style s, uint8_t prim_id);

/* Enclosed/open for a style (TERRAIN_WALLED for out-of-range). */
TerrainMode style_terrain(Style s);

/* Enclosed/open for the region a chunk lies in. */
TerrainMode region_terrain(uint32_t seed, int chunk_x, int chunk_y);
