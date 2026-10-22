/*
 * corruption.h — how corrupt a region is, and what the player has done
 * about it (spec 58 §58.3.1, §58.5, §58.6, §58.10).
 *
 * Derived from the seed, never saved:
 *   corruption_intensity  the growing wave over a region's depth
 *   corruption_dead_count the region's fixed number of dead
 *
 * Saved, one record per region the player has touched (RegionBook):
 *   sealed     bit per site (site index in the region's site order)
 *   pieces     bit per piece of the region's spoken words found
 *   destroyed  the dead destroyed here (route 2's tally)
 *   flags      RR_FOUND: the player has seen this region's rot
 *
 * The rituals done are a separate set (region.h RegionRituals), because
 * the gates read only that. Pure module: integer math, no SDK.
 */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* The wave (§58.3.1): intensity(d) = d*RAMP + d*SWING*tri(d mod PERIOD)/PERIOD,
 * where tri is 0 at the start of a period and 2*min(x, PERIOD-x) after it.
 * Peaks and valleys both grow with depth. A 0..JITTER nudge from the
 * region's hash keeps two regions at one depth from feeling identical. */
#define WAVE_PERIOD     3
#define WAVE_RAMP       1
#define WAVE_SWING      1
#define WAVE_JITTER     1
#define INTENSITY_MAX   15

/* The dead (§58.6): a fixed, seeded count per region. */
#define DEAD_PER_REGION_MIN 2
#define DEAD_PER_REGION_MAX 8
#define DEAD_PER_INTENSITY  2   /* one more dead per this much intensity */

/* Records the campaign keeps. Each ring of depth d holds 4d regions, so
 * 64 reaches past depth 5 (as RegionRituals does). */
#define REGION_BOOK_MAX 64

/* Save budget: "v1\n" plus one "<rx> <ry> <sealed> <pieces> <destroyed>
 * <flags>\n" line per record. */
#define REGION_BOOK_TEXT_MAX (4 + REGION_BOOK_MAX * 32)

#define RR_FOUND 0x01u   /* the player has seen this region's rot (§58.3.1) */

typedef struct {
    int16_t rx, ry;
    uint8_t sealed;     /* bit per site, in the region's site order */
    uint8_t pieces;     /* bit per piece of the spoken words found */
    uint8_t destroyed;  /* the dead destroyed here */
    uint8_t flags;      /* RR_* */
} RegionRecord;

typedef struct {
    RegionRecord rec[REGION_BOOK_MAX];
    uint8_t count;
} RegionBook;

/* 0..INTENSITY_MAX for region (rx, ry). The origin region is 0. */
int corruption_intensity(uint32_t seed, int rx, int ry);

/* The region's dead: DEAD_PER_REGION_MIN..MAX, more with intensity. */
int corruption_dead_count(uint32_t seed, int rx, int ry);

void region_book_clear(RegionBook* b);
/* The region's record, or NULL if the player hasn't touched it (all zero). */
const RegionRecord* region_book_get(const RegionBook* b, int rx, int ry);
/* The region's record, added zeroed if new. NULL only if the book is full. */
RegionRecord* region_book_touch(RegionBook* b, int rx, int ry);

size_t region_book_format(const RegionBook* b, char* out, size_t cap);
/* Tolerant: an unknown version or a bad line is skipped, never fatal. */
void region_book_parse(const char* text, RegionBook* out);
