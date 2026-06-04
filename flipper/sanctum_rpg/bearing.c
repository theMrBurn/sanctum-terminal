/*
 * bearing.c — see bearing.h.
 */

#include "bearing.h"

void bearing_to_home(
    int chunk_x, int chunk_y,
    int8_t* sx, int8_t* sy, uint16_t* distance) {
    int dx = -chunk_x; /* direction from (cx, cy) toward 0 along x */
    int dy = -chunk_y; /* and along y */
    if(sx) *sx = (int8_t)(dx > 0 ? 1 : (dx < 0 ? -1 : 0));
    if(sy) *sy = (int8_t)(dy > 0 ? 1 : (dy < 0 ? -1 : 0));
    if(distance) {
        int adx = dx < 0 ? -dx : dx;
        int ady = dy < 0 ? -dy : dy;
        *distance = (uint16_t)(adx > ady ? adx : ady);
    }
}

const char* bearing_label(int8_t sx, int8_t sy) {
    /* Y is screen-y semantics: -1 = north / up the map. */
    if(sx == 0 && sy <  0) return "N";
    if(sx >  0 && sy <  0) return "NE";
    if(sx >  0 && sy == 0) return "E";
    if(sx >  0 && sy >  0) return "SE";
    if(sx == 0 && sy >  0) return "S";
    if(sx <  0 && sy >  0) return "SW";
    if(sx <  0 && sy == 0) return "W";
    if(sx <  0 && sy <  0) return "NW";
    return "";
}
