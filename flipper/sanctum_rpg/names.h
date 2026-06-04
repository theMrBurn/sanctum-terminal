/*
 * names.h — deterministic procedural place names for chunks.
 *
 * Elite '84 carried a galaxy of named systems in a few bytes per name via
 * a digram (2-letter pair) table. Same idea here, smaller surface: each
 * chunk gets a name by hashing (campaign_seed × chunk_xy) into a 16×16
 * prefix×suffix table per biome.
 *
 * Cavern names lean stony / dwarvish ("Drumlode", "Khaz Vault"); outdoor
 * names lean open / Tolkien-ish ("Vael Hollow", "Wisp Heath"). Same chunk
 * always gets the same name (byte-equal across PC/Flipper ports).
 *
 * Coverage: 256 names/biome × 2 biomes = 512 distinct possible names —
 * generous for the size of world a Flipper player will visit. Collisions
 * across distant chunks are acceptable (visiting two "Karen Deep"s a
 * thousand chunks apart is fine flavor).
 *
 * Pure module — integer math, no SDK deps, host-testable.
 */

#pragma once

#include <stddef.h>
#include <stdint.h>

/* Upper bound on rendered name length, including '\0'. The longest
 * prefix+suffix pair the tables can produce fits well under this. */
#define NAME_MAX_LEN 24

/* Fill `out` (cap including '\0') with the deterministic name for
 * (campaign_seed × chunk_x × chunk_y × biome). Same inputs → byte-equal
 * output. Cap < 2 is a no-op. */
void name_for_chunk(uint32_t campaign_seed, int chunk_x, int chunk_y,
                    uint8_t biome, char* out, size_t cap);
