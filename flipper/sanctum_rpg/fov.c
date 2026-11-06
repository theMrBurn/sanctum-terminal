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

void fov_seen_pack(const uint8_t* seen, int cells, uint8_t* bits) {
    for(int i = 0; i < (cells + 7) / 8; i++) bits[i] = 0;
    for(int i = 0; i < cells; i++)
        if(seen[i]) bits[i >> 3] |= (uint8_t)(1u << (i & 7));
}

void fov_seen_unpack(const uint8_t* bits, int cells, uint8_t* seen) {
    for(int i = 0; i < cells; i++) seen[i] = (uint8_t)((bits[i >> 3] >> (i & 7)) & 1u);
}

void fov_seen_to_hex(const uint8_t* bits, int nbytes, char* out) {
    static const char HEX[] = "0123456789abcdef";
    for(int i = 0; i < nbytes; i++) {
        out[2 * i] = HEX[bits[i] >> 4];
        out[2 * i + 1] = HEX[bits[i] & 15];
    }
    out[2 * nbytes] = '\0';
}

static int hexval(char c) {
    if(c >= '0' && c <= '9') return c - '0';
    if(c >= 'a' && c <= 'f') return c - 'a' + 10;
    if(c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

bool fov_seen_from_hex(const char* hex, int nbytes, uint8_t* bits) {
    for(int i = 0; i < nbytes; i++) {
        int hi = hexval(hex[2 * i]), lo = hi < 0 ? -1 : hexval(hex[2 * i + 1]);
        if(hi < 0 || lo < 0) return false;
        bits[i] = (uint8_t)(hi << 4 | lo);
    }
    return true;
}
