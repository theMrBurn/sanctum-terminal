/*
 * deltas.h — per-chunk tile-mutation persistence.
 *
 * The world's tile grid is purely procgen (deterministic from seed),
 * but the *player* changes things — picks up items, opens doors,
 * eventually breaks walls / kills NPCs. The delta layer records those
 * mutations on disk so they survive chunk regeneration.
 *
 * Storage layout (per campaign, per chunk):
 *   apps_data/sanctum_rpg/campaigns/<id>/deltas/g0_<cx>_<cy>.txt
 *
 * File format (flat text, line-oriented):
 *   v1
 *   <x> <y> <tile_char>
 *   <x> <y> <tile_char>
 *   ...
 *
 * Chose flat text over JSON because:
 *   - No parser complexity on-device.
 *   - Host-side tools (Phase 4 sync) can read it as easily as JSON.
 *   - Spec 43 §4 mentions JSON but doesn't require it; we can migrate
 *     later if sync needs structured.
 *
 * Pipeline on chunk entry:
 *   1. world_generate_chunk()           (fresh tiles from seed)
 *   2. deltas_load() + deltas_apply()   (overlay mutations)
 *   3. player can now interact          (deltas_record on each mutation)
 *
 * Per spec 43 / project_sanctum_rpg_flipper: items are FINITE.
 * Picked-up items stay gone forever (no daily refresh).
 *
 * "g0_" prefix is "galaxy 0" — placeholder namespace; spec 43 §6
 * contemplates multiple galaxies later. Single galaxy for now.
 */

#pragma once

#include "save_io.h"
#include "world.h"

#define DELTAS_MAX_PER_CHUNK 256   /* hard cap; far more than playtest reaches */
#define DELTAS_SCHEMA_VERSION 1

typedef struct {
    int8_t x;
    int8_t y;
    char tile;
} TileMutation;

typedef struct {
    int chunk_x;
    int chunk_y;
    int count;
    TileMutation items[DELTAS_MAX_PER_CHUNK];
} ChunkDeltas;

/* Clear in-memory deltas, set the chunk coords (used when entering a
 * new chunk before deltas_load). */
void deltas_reset(ChunkDeltas* d, int chunk_x, int chunk_y);

/* Load any on-disk deltas for (campaign_id, chunk_x, chunk_y).
 * Returns SaveIoOk if loaded OR if no file exists (legitimately empty).
 * SaveIoParseError if a malformed file is found. The deltas buffer
 * is reset before loading. */
SaveIoResult deltas_load(
    const char* campaign_id, int chunk_x, int chunk_y, ChunkDeltas* out);

/* Apply every recorded mutation to the world's tile grid. Idempotent
 * — applying twice is the same as applying once for our mutation
 * scheme (it's a simple overwrite, not a delta-on-delta). */
void deltas_apply_to_world(const ChunkDeltas* d, World* w);

/* Append a mutation in memory + write the full delta file atomically.
 * Returns SaveIoFull if the in-memory buffer is at DELTAS_MAX_PER_CHUNK
 * (a sane chunk shouldn't ever fill this). */
SaveIoResult deltas_record(
    const char* campaign_id, ChunkDeltas* d, int x, int y, char tile);
