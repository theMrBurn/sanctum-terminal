/*
 * compose.h — corner-snap stamp composer (spec 50 §F1 + §F1.7).
 *
 * Pure module. Drops Pool-biased stamps into a chunk's interior. Biome
 * owns the edge (border + 4 mid-edge doors); the composer only touches
 * the interior box.
 *
 * v1 simplification (spec 50 §F1.5 + §F1.7): random non-overlapping
 * placement with bounded retry. Full corner-snap frontier-popping is
 * the elegant model but adds significant complexity; v1 ships the
 * simpler model that produces visible architectural variety. Frontier
 * refinement is a v1.1 polish slice if playtest demands it.
 */

#pragma once

#include "pool.h"
#include "rng.h"
#include "world.h"

/* Place a Pool-biased stamp composition into the chunk's interior.
 * Stamps are eligible-by-biome (cavern stamps for cavern, outdoor for
 * outdoor). Border cells (row 0 / row N-1 / col 0 / col N-1) are never
 * written. Existing non-floor tiles (e.g. mid-edge doors written before
 * this call) are respected and never overwritten. */
void compose_stamps_into_interior(Rng* rng, const Pool* pool,
                                  uint8_t biome, World* out);
