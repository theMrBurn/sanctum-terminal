/*
 * render_fpv.h — first-person perspective renderer (Etrian-style).
 *
 * Phase 1 (this slice): static demo screen — a single composed scene
 * proving the visual direction (Etrian 5-depth perspective + 32x32
 * pictogram entities, Sable-soft hand-drawn line jitter for walls).
 *
 * Phase 2 (next commit): live world sampling from (player_x, player_y,
 * facing) reading actual chunk data.
 *
 * Phase 3 (later): full sprite-per-kind coverage + weather + foe.
 *
 * Pure rendering. No state. Takes Canvas + composition inputs, paints.
 */

#pragma once

#include <gui/canvas.h>
#include <stdint.h>

#include "world.h"

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

/* Static "Sanctum interior" demo (kept for visual regression testing). */
void render_fpv_demo(Canvas* canvas);

/* Live world FPV render. Samples the world starting at (player_x,
 * player_y), looking in `facing`. Renders the forward column up to
 * depth 4, terminating at the first blocking tile (back wall). */
void render_fpv_world(
    Canvas* canvas,
    const World* world,
    int player_x, int player_y,
    uint8_t facing);
