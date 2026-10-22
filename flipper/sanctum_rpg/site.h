/*
 * site.h — a region's sites (spec 58 §58.5): the resting places and altars
 * that cleanse a region when sealed.
 *
 * Each region holds SITES_PER_REGION_MIN..MAX sites, each in its own chunk
 * of the region. Which chunks, and each site's kind, come from the seed and
 * the region (region_hash, never rng_chunk_seed, which has mirror twins).
 * The kinds a region may hold are data on its style (StyleDef.site_kinds).
 *
 * The generator places a chunk's site last, on a floor tile where it cuts
 * off no door and no walkable ground (world.c), and records where in
 * World.site_*. A site looks like any other grave or altar; which ones
 * matter is for the player to find out.
 *
 * Derived from the seed, never saved (spec 58 §58.10). Pure, host-testable.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    SITE_GRAVE = 0,   /* 'g' a grave in the open */
    SITE_TOMB,        /* 'n' a sarcophagus */
    SITE_ALTAR,       /* 'a' a built altar */
    SITE_STONE,       /* 'h' an altar stone (a dolmen) */
    SITE_KIND_COUNT,
} SiteKind;

#define SITE_NONE 0xFFu

/* StyleDef.site_kinds bits. */
#define SITE_BIT(k) ((uint8_t)(1u << (k)))

#define SITES_PER_REGION_MIN 2
#define SITES_PER_REGION_MAX 3

typedef struct {
    char glyph;        /* what the generator places */
    const char* name;  /* for tests and the ledger; never shown as a count */
} SiteDef;

extern const SiteDef SITE_TABLE[SITE_KIND_COUNT];

/* How many sites region (rx, ry) holds. */
int region_site_count(uint32_t seed, int rx, int ry);

/* Does chunk (cx, cy) hold one of its region's sites? If so, its kind
 * (SiteKind), else SITE_NONE. */
uint8_t chunk_site_kind(uint32_t seed, int cx, int cy);

/* The site's place in its region's site order (0..count-1), or -1 if the
 * chunk holds no site slot. The order is RegionRecord.sealed's bit order. */
int chunk_site_index(uint32_t seed, int cx, int cy);
