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

/* Render the static "Sanctum interior, facing the hearth" demo scene.
 * Used by ScreenFpvDemo to UAT the visual direction. */
void render_fpv_demo(Canvas* canvas);
