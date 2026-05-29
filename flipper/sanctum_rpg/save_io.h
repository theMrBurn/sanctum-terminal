/*
 * save_io.h — persistent campaign state on the Flipper SD card.
 *
 * Spec: sanctum-os/docs/specs/43_app_sanctum_rpg_flipper.md §4.
 *
 * Storage layout (under /ext/apps_data/sanctum_rpg/):
 *
 *     campaigns/
 *       001/
 *         meta.json         <- this file's scope in v0.1.2
 *         character.json    <- future
 *         autosave.json     <- future (atomic rename pattern)
 *         deltas/, journal.log, ...
 *       002/
 *       ...
 *
 * v0.1.2 implements only meta.json. character.json and autosave.json
 * follow in v0.1.3+.
 *
 * Format: canonical JSON (small subset). The writer emits a fixed
 * layout; the reader does keyed string lookups, not full JSON parsing.
 * The result is wire-compatible with the host-side JSON tooling spec
 * 43 §8 contemplates, without dragging a JSON library on-device.
 */

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SAVE_IO_SCHEMA_VERSION 1
#define SAVE_IO_CAMPAIGN_NAME_MAX 31
#define SAVE_IO_CAMPAIGN_ID_MAX 7  /* "001".."999" supports 999 slots */

typedef struct {
    char campaign_id[SAVE_IO_CAMPAIGN_ID_MAX + 1]; /* e.g. "001" */
    char character_name[SAVE_IO_CAMPAIGN_NAME_MAX + 1];
    uint32_t seed;
    uint64_t started_at_unix;
    uint64_t last_played_at_unix;
    bool permadeath;
    uint8_t schema_version;
} CampaignMeta;

/* Per-campaign character state.
 *   Phase 2 v0.2.0: position + vitals.
 *   Phase 3b v0.3.1: chunk coordinates added — player position is now
 *     (chunk_x, chunk_y, player_x, player_y). chunk_*  fields default
 *     to 0 when loading older saves that lack them (backward-compat). */
typedef struct {
    char campaign_id[SAVE_IO_CAMPAIGN_ID_MAX + 1];
    int16_t chunk_x;
    int16_t chunk_y;
    int16_t player_x;
    int16_t player_y;
    uint16_t hp;
    uint16_t max_hp;
    uint16_t mp;
    uint16_t max_mp;
    uint8_t level;
    uint32_t credits;
    uint64_t identified;   /* bitmask of identified kind ids (v0.3.3) */
    uint32_t turn;         /* turn counter — the event-driven clock (v0.3.5) */
    uint16_t torch_fuel;   /* burns 1/turn; drives vision radius (v0.3.5) */
    uint8_t schema_version;
} CharacterState;

/* Result codes — keep small + descriptive over rich error types. */
typedef enum {
    SaveIoOk = 0,
    SaveIoNotFound,
    SaveIoFsError,
    SaveIoParseError,
    SaveIoFull,        /* hit campaign-slot ceiling */
} SaveIoResult;

/* Ensure the on-card directory tree exists. Idempotent.
 * Returns SaveIoOk on success, SaveIoFsError if any mkdir fails. */
SaveIoResult save_io_init(void);

/* Count campaigns currently on disk. Returns 0 if none.
 * Negative return = error. */
int save_io_count_campaigns(void);

/* Find the most-recently-played campaign id (by last_played_at).
 * Returns SaveIoOk and fills out_id; SaveIoNotFound if none. */
SaveIoResult save_io_most_recent_campaign(char* out_id, size_t out_len);

/* Create a new campaign with default character name. Allocates the
 * next sequential id ("001", "002", ...). Writes meta.json atomically.
 * Returns the chosen id in out_id. */
SaveIoResult save_io_new_campaign(
    const char* character_name,
    uint32_t seed,
    char* out_id,
    size_t out_len);

/* Load a campaign's meta.json. */
SaveIoResult save_io_load_meta(const char* campaign_id, CampaignMeta* out);

/* Write a campaign's meta.json atomically (write tmp, rename). */
SaveIoResult save_io_write_meta(const CampaignMeta* meta);

/* Update last_played_at_unix to now, atomically rewrite meta.json.
 * Convenience wrapper used on campaign entry. */
SaveIoResult save_io_touch_played(const char* campaign_id);

/* Character state I/O. character.json sits in the same campaign dir as
 * meta.json. Missing file is SaveIoNotFound (caller initialises). */
SaveIoResult save_io_load_character(const char* campaign_id, CharacterState* out);
SaveIoResult save_io_write_character(const CharacterState* state);
