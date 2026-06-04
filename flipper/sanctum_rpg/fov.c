/*
 * fov.c — see fov.h.
 */

#include "fov.h"

int fov_radius_for_fuel(uint16_t fuel) {
    if(fuel >= 60) return 4;
    if(fuel >= 30) return 3;
    if(fuel >= 10) return 2;
    return 1; /* low or empty — adjacent only, never fully blind */
}

bool fov_is_lit(int px, int py, int tx, int ty, int radius) {
    int dx = tx - px;
    int dy = ty - py;
    if(dx < 0) dx = -dx;
    if(dy < 0) dy = -dy;
    int cheb = (dx > dy) ? dx : dy; /* Chebyshev distance */
    return cheb <= radius;
}
