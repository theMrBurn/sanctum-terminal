/*
 * fov.h — field of view + the torch-fuel → vision-radius relationship.
 *
 * v0.3.5a (Sight): the survival-pressure pillar. A torch burns down one
 * unit per turn (event-driven — the turn IS the clock, §14.0); as fuel
 * drops, your lit radius shrinks, so "explore one more chunk" becomes a
 * fuel gamble. Finding a torch refuels you.
 *
 * Pure module (no Flipper deps) so the vision math is host-tested for
 * determinism + symmetry. The `seen`/`lit` grids themselves live in the
 * app state; this module only answers "given a radius, is (tx,ty) lit
 * from (px,py)?" and "what radius does this fuel give?".
 *
 * v0.3.5a uses Chebyshev-radius FOV (a square pool of light) — symmetric
 * and deterministic, no wall occlusion. Shadowcasting occlusion is a
 * later refinement (flagged in spec 43).
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define TORCH_FUEL_MAX  100u
#define FUEL_PER_TURN   1u     /* burn rate */

/* Lit radius for a given fuel level. Banded: bright when fueled, a tiny
 * adjacent pool when nearly out — but never fully blind (min radius 1)
 * so the game stays playable at zero fuel. */
int fov_radius_for_fuel(uint16_t fuel);

/* Is (tx,ty) lit from (px,py) at this radius? Chebyshev distance ≤ r.
 * Symmetric: fov_is_lit(a,b,c,d,r) == fov_is_lit(c,d,a,b,r). */
bool fov_is_lit(int px, int py, int tx, int ty, int radius);
