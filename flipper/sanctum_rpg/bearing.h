/*
 * bearing.h — 8-way compass bearing utility.
 *
 * For the persistent home-bearing HUD: from any chunk (cx, cy), what
 * direction is the home chunk (0, 0), and how far?
 *
 * Pure integer module. Same shape future-proofs for quest bearings
 * (Tier-2) by exposing the (sx, sy, distance) primitive — a quest
 * bearing is the same math with a different target.
 */

#pragma once

#include <stdint.h>

/* From chunk (cx, cy) toward (0, 0):
 *   *sx, *sy ∈ {-1, 0, +1}  — signed direction (component-wise sign of -cx, -cy)
 *   *distance              — Chebyshev distance in chunks
 *
 * At home (cx == 0 && cy == 0), distance is 0 and (sx, sy) = (0, 0). */
void bearing_to_home(
    int chunk_x, int chunk_y,
    int8_t* sx, int8_t* sy, uint16_t* distance);

/* 8-way compass label for a (sx, sy) pair: "N", "NE", "E", "SE", "S",
 * "SW", "W", "NW", or "" when (sx, sy) = (0, 0). Static string. */
const char* bearing_label(int8_t sx, int8_t sy);
