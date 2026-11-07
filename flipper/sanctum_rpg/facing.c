/* facing.c — the four facings and their turns (see facing.h). Pure; moved
 * out of render_fpv.c so the rules can turn and step without the renderer. */

#include "facing.h"

uint8_t fpv_turn_left(uint8_t facing) { return (uint8_t)((facing + 3u) & 3u); }
uint8_t fpv_turn_right(uint8_t facing) { return (uint8_t)((facing + 1u) & 3u); }

int fpv_facing_dx(uint8_t facing) {
    switch(facing & 3u) {
    case FPV_FACE_E: return  1;
    case FPV_FACE_W: return -1;
    default:         return  0;
    }
}

int fpv_facing_dy(uint8_t facing) {
    switch(facing & 3u) {
    case FPV_FACE_N: return -1;
    case FPV_FACE_S: return  1;
    default:         return  0;
    }
}
