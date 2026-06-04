/*
 * deeds.h — the Tensura on-device ledger (slice 48.F4/F5/F6).
 *
 * The deeds log is an append-only record of axis-growth events. Lives in the
 * LIFETIME tier (per spec 43 `codex_shared/` precedent + spec 48 §3 storage
 * tier split) under `/ext/apps_data/sanctum_rpg/deeds_<real_self>/`:
 *
 *     log.txt   — append-only line ledger (one DEED per line, format §5.1)
 *     axes.json — rolled-up delta per axis for fast load
 *
 * The rollup is recomputed by scanning log.txt on app open and held in RAM
 * (DeedsState). `effective_axis = profile.axes[X] + deeds.delta[X]`.
 *
 * Per-session caps prevent farming any single event (spec 48 §5.4). The
 * session counter array is RAM-only — by design, anti-grind is bound to
 * the "this session" boundary (app open → app close).
 *
 * Honors spec 43 §14.0 — integers only, deterministic state advancement.
 * Honors spec 48 §11 — append-only, never edited; per-session caps mandatory.
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define DEED_AXIS_BODY    0
#define DEED_AXIS_CRAFT   1
#define DEED_AXIS_SIGHT   2
#define DEED_AXIS_MIND    3
#define DEED_AXIS_HEART   4
#define DEED_AXIS_WILL    5
#define DEED_AXIS_COUNT   6

/* Event ids — fixed enumeration. Adding a new event = new id at the end. */
typedef enum {
    DEED_EXAMINE = 0,         /* SIGHT +1, cap 4/session */
    DEED_SCAN_TIER1,          /* SIGHT +2, cap 3/session */
    DEED_SCAN_TIER2,          /* SIGHT +3, cap 2/session */
    DEED_SCAN_TIER3,          /* SIGHT +4, cap 1/session */
    DEED_CHUNK_MAPPED,        /* SIGHT +2 — placeholder, one-shot per chunk_xy */
    DEED_CODEX_UP,            /* MIND +1, uncapped */
    DEED_RECIPE_LEARNED,      /* MIND +2 — placeholder, one-shot per recipe id */
    DEED_LONG_SESSION,        /* MIND +2, cap 1/day — slice 48.F7 */
    DEED_FORGE_HIT,           /* CRAFT +1, cap 3/session */
    DEED_FORGE_JACKPOT,       /* CRAFT +3, cap 2/session */
    DEED_FALL_CLEAN,          /* WILL +1, cap 2/session */
    DEED_FUEL_LOW_SURVIVE,    /* WILL +1, cap 1/session */
    DEED_DAY_STREAK,          /* WILL +1, cap 3 (per spec 48 §5.2; slice 48.F7) */
    DEED_STRIKE,              /* BODY +1, cap 5/session */
    DEED_FLEE_SUCCESS,        /* BODY +1, cap 2/session */
    DEED_PARLEY_SUCCESS,      /* HEART +2 — placeholder, slice 49 fills */
    DEED_PARLEY_HOLD,         /* HEART +1 — placeholder, slice 49 fills */
    DEED_QUEST_TEND,          /* HEART +2 — slice 49.F5 */
    DEED_QUEST_LET_GO,        /* WILL +2 — slice 49.F5 */
    DEED_QUEST_SPEAK,         /* HEART +2 — slice 49.F5 */
    DEED_QUEST_WITHHOLD,      /* WILL +2 — slice 49.F5 */
    DEED_EVENT_COUNT,
} DeedEvent;

typedef struct {
    int16_t delta[DEED_AXIS_COUNT];       /* axis-growth rollup (lifetime; +1 per landed deed) */
    uint8_t session_counts[DEED_EVENT_COUNT];  /* anti-grind, RAM-only, reset on app open */
    bool loaded;                          /* true = log scanned at app open */
} DeedsState;

/* Zero the state. Call once at app init before deeds_load. */
void deeds_init(DeedsState* d);

/* Scan the deeds log for the given real_self and populate the `delta` array.
 * No-op if the log file is missing (first launch). Atomic-tolerant.
 * NOTE: Flipper-side (uses Storage record) — NOT host-testable. */
void deeds_load(DeedsState* d, const char* real_self_id);

/* Record a deed. Returns true on success, false if the per-session cap was
 * already hit. On success:
 *   - increments session_counts[event]
 *   - adds the event's delta to delta[axis_id]
 *   - appends a line to /ext/apps_data/sanctum_rpg/deeds_<real_self>/log.txt
 * On cap-hit: no log line written, no delta change.
 * Caller passes campaign_id + turn so each log line is grep-able for context. */
bool deeds_record(
    DeedsState* d, const char* real_self_id, const char* campaign_id,
    uint32_t turn, DeedEvent event);

/* Lookup helpers — what axis/delta/cap does this event id carry?
 * Returned via out-params; returns false on bad event id. Pure (no I/O). */
bool deed_event_info(DeedEvent event, uint8_t* axis_out, int8_t* delta_out,
                     uint8_t* cap_out);

/* Effective axis read: base + delta, clamped to uint8 range.
 * Pure helper, used by combat math (player_atk/def) + char sheet display. */
uint8_t deeds_effective_axis(const DeedsState* d, uint8_t base, uint8_t axis_id);
