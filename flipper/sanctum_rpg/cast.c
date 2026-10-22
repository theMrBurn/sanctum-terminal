/* cast.c — see cast.h. */
#include "cast.h"

/* name        element    power mp */
const CastDef CAST_TABLE[CAST_COUNT] = {
    [CAST_SENDING] = {"sending", ELEM_NONE, 2, 2},   /* taught by any plain creature's deep read */
    [CAST_EMBER]   = {"ember",   ELEM_FIRE, 3, 3},
    [CAST_RIME]    = {"rime",    ELEM_ICE,  3, 3},
};

bool cast_fires(uint8_t observe, uint8_t scan_diff, int bestiary_grade, uint8_t casts_known) {
    if(!casts_known) return false;
    return creature_scan_tier(observe, scan_diff) <= bestiary_grade;
}

int cast_taught_by(uint8_t element) {
    for(int c = 0; c < CAST_COUNT; c++)
        if(CAST_TABLE[c].element == element) return c;
    return -1;
}

int cast_pick(uint8_t casts_known, uint16_t mp) {
    int best = -1;
    for(int c = 0; c < CAST_COUNT; c++) {
        if(!(casts_known & CAST_BIT(c)) || CAST_TABLE[c].mp_cost > mp) continue;
        if(best < 0 || CAST_TABLE[c].power > CAST_TABLE[best].power) best = c;
    }
    return best;
}

int cast_damage(int c, uint8_t mind, uint8_t def) {
    if(c < 0 || c >= CAST_COUNT) return 0;
    int d = (int)CAST_TABLE[c].power + mind / CAST_MIND_DIV - def / 8;
    return d < 1 ? 1 : d;
}

uint16_t cast_mp_regen(uint16_t mp, uint16_t max_mp, uint32_t turn) {
    if(mp < max_mp && turn % MP_REGEN_TURNS == 0) mp++;
    return mp;
}
