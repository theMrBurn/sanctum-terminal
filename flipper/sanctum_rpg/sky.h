/*
 * sky.h — night, day and the moon, from the device's real clock
 * (spec 50 Q1 §Q.11).
 *
 * The clock is an INPUT, like a button press (spec 53): the turn's local
 * time goes in, the sky comes out. Nothing in generation reads it.
 *
 * Integer only. The moon's age is counted in minutes from a reference new
 * moon; the clock is local time without a timezone, so the phase can be a
 * few hours off, far inside the MOON_REACH_DAYS window. Pure, host-testable.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/* Night is [SKY_NIGHT_START_HOUR, 24) and [0, SKY_NIGHT_END_HOUR), local. */
#define SKY_NIGHT_START_HOUR 20
#define SKY_NIGHT_END_HOUR    6

#define SKY_SYNODIC_MIN   42524u        /* 29.5306 days */
#define SKY_MOON_EPOCH    947182440ull  /* a new moon: 2000-01-06 18:14 UTC */
#define MOON_REACH_DAYS   3             /* the moon has strength this close to full or new */
#define MOON_STRENGTH_MAX 16

typedef enum { MOON_NEW = 0, MOON_WAXING, MOON_FULL, MOON_WANING } MoonPhase;

typedef struct {
    bool night;
    uint32_t moon_age_min;   /* minutes since the last new moon, 0..SKY_SYNODIC_MIN-1 */
    MoonPhase phase;         /* NEW / FULL inside the reach window, else WAXING / WANING */
    uint8_t moon_strength;   /* MOON_STRENGTH_MAX at full or new, 0 at the window's edge and beyond */
} Sky;

void sky_at(uint64_t local_unix, Sky* out);

/* The status line for this sky, or NULL when there is nothing to say: a
 * line only at night, and only near a real full or new moon (spec 58
 * §58.9). The caller says it once per night (sky_night_id), above ground. */
const char* sky_line(const Sky* s);

/* Which night a moment belongs to: the day number of the evening that
 * night began on. The small hours after midnight belong to the evening
 * before. Used to say something once per night. */
uint32_t sky_night_id(uint64_t local_unix);
