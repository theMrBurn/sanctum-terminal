/* facing.h — which way the player faces, and the step it points.
 *
 * Pure (no SDK): the rules turn and walk with it; render_fpv.h includes it
 * for the first-person view.
 */
#pragma once

#include <stdint.h>

/* Facing direction — packed into 2 bits in CharacterState.facing. */
typedef enum {
    FPV_FACE_N = 0,
    FPV_FACE_E = 1,
    FPV_FACE_S = 2,
    FPV_FACE_W = 3,
} FpvFacing;

/* Turn 90° left / right, deterministic. Wraps modulo 4. */
uint8_t fpv_turn_left(uint8_t facing);
uint8_t fpv_turn_right(uint8_t facing);

/* Convert facing → (dx, dy) step in chunk-grid coordinates. */
int fpv_facing_dx(uint8_t facing);
int fpv_facing_dy(uint8_t facing);
