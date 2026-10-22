/* sky.c — see sky.h. */
#include "sky.h"

#include <stddef.h>

/* Copy (spec 58 §58.9, option A for both; the user picks). "no moon. a
 * spade, somewhere." waits for the rising: it may only show on nights a
 * rising is possible. */
#define SKY_LINE_FULL "full moon. the graves are lit."
#define SKY_LINE_NEW  "no moon. your own hands, gone."

#define SECONDS_PER_DAY 86400u
#define REACH_MIN       ((uint32_t)MOON_REACH_DAYS * 24u * 60u)

void sky_at(uint64_t local_unix, Sky* out) {
    uint32_t hour = (uint32_t)((local_unix % SECONDS_PER_DAY) / 3600u);
    out->night = hour >= SKY_NIGHT_START_HOUR || hour < SKY_NIGHT_END_HOUR;

    /* Before the epoch (an unset clock): treat as the epoch, a new moon. */
    uint64_t since = local_unix > SKY_MOON_EPOCH ? local_unix - SKY_MOON_EPOCH : 0;
    uint32_t age = (uint32_t)((since / 60u) % SKY_SYNODIC_MIN);
    out->moon_age_min = age;

    /* Distance in minutes to the nearest new (age 0 or a full month) and
     * to full (half a month). */
    const uint32_t half = SKY_SYNODIC_MIN / 2u;
    uint32_t to_new = age < half ? age : SKY_SYNODIC_MIN - age;
    uint32_t to_full = age > half ? age - half : half - age;
    bool nearer_new = to_new <= to_full;
    uint32_t d = nearer_new ? to_new : to_full;

    if(d < REACH_MIN) {
        out->phase = nearer_new ? MOON_NEW : MOON_FULL;
        out->moon_strength = (uint8_t)(((REACH_MIN - d) * MOON_STRENGTH_MAX + REACH_MIN - 1) / REACH_MIN);
    } else {
        out->phase = age < half ? MOON_WAXING : MOON_WANING;
        out->moon_strength = 0;
    }
}

const char* sky_line(const Sky* s) {
    if(!s->night || s->moon_strength == 0) return NULL;
    return s->phase == MOON_FULL ? SKY_LINE_FULL : s->phase == MOON_NEW ? SKY_LINE_NEW : NULL;
}

uint32_t sky_night_id(uint64_t local_unix) {
    uint64_t day = local_unix / SECONDS_PER_DAY;
    uint32_t hour = (uint32_t)((local_unix % SECONDS_PER_DAY) / 3600u);
    if(hour < SKY_NIGHT_END_HOUR && day > 0) day--;
    return (uint32_t)day;
}
