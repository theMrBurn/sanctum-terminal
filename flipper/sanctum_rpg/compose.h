/*
 * compose.h — corner-snap stamp composer (spec 50 §F1 + §F1.7).
 *
 * Pure module. Drops Pool-biased stamps into a chunk's interior. Biome
 * owns the edge (border + 4 mid-edge doors); the composer only touches
 * the interior box.
 *
 * Placement is CORNER-SNAP FRONTIER POPPING (spec 50 §R.2): a central
 * floor prime seeds a frontier of anchor corners, Pool-biased stamps are
 * popped onto them and grow outward from center, each placed stamp pushing
 * its own corners back onto the frontier. This realizes the north-star
 * drawing's "out from center" progression (§R.0). Selection (pick_stamp /
 * pick_rotation in stamps.c) is unchanged; only placement is corner-snap.
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

#ifdef SANCTUM_RPG_HOST_TEST
/* Host-test hook: verifies the corner-snap math pair (box_corner /
 * place_for_anchor) are exact inverses across every corner and every valid
 * stamp dimension. Returns true on success. Exposed only under the host-test
 * macro so the internals stay file-static in the .fap build. (AGENTS.md
 * coord-pair rule: pin both sides of a coordinate convention with a test.) */
bool compose_selftest_corner_roundtrip(void);
#endif
