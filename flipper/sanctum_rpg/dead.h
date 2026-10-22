/*
 * dead.h — the rising dead (spec 50 Q1 §Q.1.2, spec 58 §58.6, §58.17).
 *
 * A region's dead are one pool: corruption_dead_count of them, dormant
 * until something raises them. Any rising — by chance at night under a
 * full or new moon above ground, or by the player disturbing a resting
 * place — draws from the pool; risen dead that calm down (the player left
 * their region) return to it; destroyed dead add to the region's tally.
 *
 *   dormant = count - destroyed - risen and still up
 *
 * An ordinary grave or sarcophagus opens once (a delta) and stays open; a
 * site can be disturbed again while the pool holds dead, so the tally can
 * always be closed (route 2, §58.6). Nothing rises where every site is
 * sealed (route 1 holds) or the rite has taken hold, nor in the home chunk.
 *
 * Risen records (RisenBook) are saved with the campaign. Pure, host-tested.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "corruption.h"
#include "creatures.h"
#include "region.h"
#include "world.h"

/* Tunables (spec 50 Q1 §Q.7, spec 58 §58.6). */
#define DEAD_RISE_ODDS      64   /* 1 in 64 at the exact phase (QUIRK_ODDS) */
#define HORDE_SIZE          3    /* the dead per horde rising */
#define DISTURB_RADIUS_MIN  0    /* no moon: only the place you touched */
#define DISTURB_RADIUS_MAX  4    /* tiles, at the strongest moon */
#define RISEN_RECORDS_MAX   4    /* risings remembered at once; the oldest calms first */

/* Copy (spec 58 §58.9, option A). */
#define DEAD_LINE_GRAVE     "the turf heaves. once."
#define DEAD_LINE_TOMB      "the lid has shifted."

typedef struct {
    int16_t cx, cy;     /* the chunk they rose in */
    int8_t x, y;        /* where they rose */
    uint8_t trait;      /* their kind */
    uint8_t count;      /* still up */
} RisenRecord;

typedef struct {
    RisenRecord rec[RISEN_RECORDS_MAX];
    uint8_t count;
} RisenBook;

#define RISEN_TEXT_MAX (4 + RISEN_RECORDS_MAX * 32)

/* Does this kind come as a horde (HORDE_SIZE) or alone (an area kind)? */
bool dead_is_horde(uint8_t trait);

/* Is `glyph` a resting place (it has an opened form)? */
bool dead_resting_place(char glyph);

int dead_up_in_region(const RisenBook* rb, int rx, int ry);
int dead_dormant(uint32_t seed, int rx, int ry, const RegionBook* book, const RisenBook* rb);

/* May the dead rise in this region at all? Not once every site is sealed
 * (route 1), every one of its dead destroyed (route 2), or its rite done. */
bool dead_restless(uint32_t seed, int rx, int ry, const RegionBook* book, const RegionRituals* rituals);

/* The kind that rises from (x, y) of chunk (cx, cy), by hash among the
 * dead's kinds the biome allows. */
uint8_t dead_rise_kind(uint32_t seed, int cx, int cy, int x, int y, Biome biome);

/* Above ground, at night: does a step next to resting place (x, y) on turn
 * `turn` set it off? 1 in DEAD_RISE_ODDS at the moon's full strength,
 * falling to nothing at the window's edge (`strength` 0..MOON_STRENGTH_MAX). */
bool dead_chance(uint32_t seed, int cx, int cy, int x, int y, uint32_t turn, uint8_t strength);

/* How far a disturbance reaches under a moon of `strength`. */
int dead_disturb_radius(uint8_t strength);

/* Raise the dead at resting place (x, y): up to HORDE_SIZE (a horde kind)
 * or 1, no more than the region's dormant dead, onto free floor beside it
 * (never the player's tile or a creature's). Appends them to `cs` (up to
 * `max`) and records the rising. Returns how many rose. */
int dead_raise(uint32_t seed, int cx, int cy, const World* w, int px, int py, int x, int y,
               const RegionBook* book, RisenBook* rb, Creature* cs, int* n, int max);

/* Chunk (cx, cy) entered: put its risen back up, beside where they rose. */
void dead_restore(const RisenBook* rb, int cx, int cy, const World* w, int px, int py, Creature* cs,
                  int* n, int max);

/* One of the dead was destroyed in chunk (cx, cy): it leaves the risen
 * record and joins the region's tally. True if that was the region's last. */
bool dead_destroyed(uint32_t seed, int cx, int cy, uint8_t trait, RisenBook* rb, RegionBook* book);

/* The player is in region (rx, ry): the dead risen elsewhere calm down and
 * return to their regions' dormant pools. True if any did. */
bool dead_calm_outside(RisenBook* rb, int rx, int ry);

void risen_book_clear(RisenBook* rb);
size_t risen_book_format(const RisenBook* rb, char* out, size_t cap);
void risen_book_parse(const char* text, RisenBook* out);
