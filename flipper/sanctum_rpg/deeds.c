/*
 * deeds.c — see deeds.h. The Tensura ledger implementation.
 *
 * The event-info table is the single source of truth for axis/delta/cap.
 * "Never if event ==" — every event is a row, not a branch.
 */

#include "deeds.h"

#include <stddef.h>
#include <string.h>
#include <stdio.h>

#ifndef SANCTUM_RPG_HOST_TEST
#include <furi.h>
#include <storage/storage.h>
#endif

/* Event table — id, axis, delta, per-session cap (0 = uncapped). Per
 * spec 48 §5.2. The order MUST match the DeedEvent enum in deeds.h. */
typedef struct {
    uint8_t axis;
    int8_t  delta;
    uint8_t cap;     /* 0 = uncapped */
} DeedEventInfo;

static const DeedEventInfo DEED_EVENT_TABLE[DEED_EVENT_COUNT] = {
    [DEED_EXAMINE]          = {DEED_AXIS_SIGHT, 1, 4},
    [DEED_SCAN_TIER1]       = {DEED_AXIS_SIGHT, 2, 3},
    [DEED_SCAN_TIER2]       = {DEED_AXIS_SIGHT, 3, 2},
    [DEED_SCAN_TIER3]       = {DEED_AXIS_SIGHT, 4, 1},
    [DEED_CHUNK_MAPPED]     = {DEED_AXIS_SIGHT, 2, 0}, /* one-shot per chunk; caller dedups */
    [DEED_CODEX_UP]         = {DEED_AXIS_MIND,  1, 0},
    [DEED_RECIPE_LEARNED]   = {DEED_AXIS_MIND,  2, 0}, /* one-shot per recipe; caller dedups */
    [DEED_LONG_SESSION]     = {DEED_AXIS_MIND,  2, 1},
    [DEED_FORGE_HIT]        = {DEED_AXIS_CRAFT, 1, 3},
    [DEED_FORGE_JACKPOT]    = {DEED_AXIS_CRAFT, 3, 2},
    [DEED_FALL_CLEAN]       = {DEED_AXIS_WILL,  1, 2},
    [DEED_FUEL_LOW_SURVIVE] = {DEED_AXIS_WILL,  1, 1},
    [DEED_DAY_STREAK]       = {DEED_AXIS_WILL,  1, 3},
    [DEED_STRIKE]           = {DEED_AXIS_BODY,  1, 5},
    [DEED_FLEE_SUCCESS]     = {DEED_AXIS_BODY,  1, 2},
    [DEED_PARLEY_SUCCESS]   = {DEED_AXIS_HEART, 2, 3},
    [DEED_PARLEY_HOLD]      = {DEED_AXIS_HEART, 1, 2},
    [DEED_QUEST_TEND]       = {DEED_AXIS_HEART, 2, 2},
    [DEED_QUEST_LET_GO]     = {DEED_AXIS_WILL,  2, 2},
    [DEED_QUEST_SPEAK]      = {DEED_AXIS_HEART, 2, 2},
    [DEED_QUEST_WITHHOLD]   = {DEED_AXIS_WILL,  2, 2},
};

#ifndef SANCTUM_RPG_HOST_TEST
/* Event name strings — for the log line + future codex display. Same order.
 * Flipper-only: parsing/writing happens via file I/O which the host harness
 * stubs out, so this table isn't referenced under SANCTUM_RPG_HOST_TEST. */
static const char* const DEED_EVENT_NAMES[DEED_EVENT_COUNT] = {
    [DEED_EXAMINE]          = "examine",
    [DEED_SCAN_TIER1]       = "scan-tier1",
    [DEED_SCAN_TIER2]       = "scan-tier2",
    [DEED_SCAN_TIER3]       = "scan-tier3",
    [DEED_CHUNK_MAPPED]     = "chunk-mapped",
    [DEED_CODEX_UP]         = "codex-up",
    [DEED_RECIPE_LEARNED]   = "recipe-learned",
    [DEED_LONG_SESSION]     = "long-session",
    [DEED_FORGE_HIT]        = "forge-hit",
    [DEED_FORGE_JACKPOT]    = "forge-jackpot",
    [DEED_FALL_CLEAN]       = "fall-clean",
    [DEED_FUEL_LOW_SURVIVE] = "fuel-low",
    [DEED_DAY_STREAK]       = "day-streak",
    [DEED_STRIKE]           = "strike",
    [DEED_FLEE_SUCCESS]     = "flee-ok",
    [DEED_PARLEY_SUCCESS]   = "parley-ok",
    [DEED_PARLEY_HOLD]      = "parley-hold",
    [DEED_QUEST_TEND]       = "quest-tend",
    [DEED_QUEST_LET_GO]     = "quest-letgo",
    [DEED_QUEST_SPEAK]      = "quest-speak",
    [DEED_QUEST_WITHHOLD]   = "quest-hold",
};

static const char* DEEDS_BASE_DIR = "/ext/apps_data/sanctum_rpg";
#endif

void deeds_init(DeedsState* d) {
    if(!d) return;
    memset(d, 0, sizeof(*d));
    d->loaded = false;
}

bool deed_event_info(DeedEvent event, uint8_t* axis_out, int8_t* delta_out,
                     uint8_t* cap_out) {
    if(event >= DEED_EVENT_COUNT) return false;
    const DeedEventInfo* info = &DEED_EVENT_TABLE[event];
    if(axis_out)  *axis_out  = info->axis;
    if(delta_out) *delta_out = info->delta;
    if(cap_out)   *cap_out   = info->cap;
    return true;
}

uint8_t deeds_effective_axis(const DeedsState* d, uint8_t base, uint8_t axis_id) {
    if(!d || axis_id >= DEED_AXIS_COUNT) return base;
    int eff = (int)base + (int)d->delta[axis_id];
    if(eff < 0) return 0;
    if(eff > 255) return 255;
    return (uint8_t)eff;
}

#ifndef SANCTUM_RPG_HOST_TEST

/* Compose the per-real-self deeds dir + log file path. */
static void deeds_dir_path(const char* real_self_id, char* out, size_t cap) {
    snprintf(out, cap, "%s/deeds_%s", DEEDS_BASE_DIR, real_self_id);
}

static void deeds_log_path(const char* real_self_id, char* out, size_t cap) {
    snprintf(out, cap, "%s/deeds_%s/log.txt", DEEDS_BASE_DIR, real_self_id);
}

/* Parse one log line: `DEED <ts> <campaign> <turn> <event> <delta>`.
 * On success, returns the axis_id (0..5) and writes delta to *delta_out.
 * On failure (malformed / unknown event / cap-eclipsed), returns DEED_AXIS_COUNT.
 *
 * Recovery scan: we re-derive `delta` from the event's table entry, NOT from
 * the log line's last column. The log line's column is informational; the
 * table is canonical. This way if a future delta-tune changes a row, replaying
 * an old log re-derives growth with the NEW math. (Spec 48 §11 implication.) */
static uint8_t deeds_parse_line(const char* line, int8_t* delta_out) {
    if(!line || strncmp(line, "DEED ", 5) != 0) return DEED_AXIS_COUNT;
    /* Find the event name — 5th whitespace-separated field. Skip past
     * "DEED <ts> <campaign> <turn> " by stepping through 4 spaces. */
    const char* p = line + 5;
    for(int i = 0; i < 3; i++) {
        const char* sp = strchr(p, ' ');
        if(!sp) return DEED_AXIS_COUNT;
        p = sp + 1;
    }
    /* p now points at the event name. Read it up to next space. */
    char event_buf[24];
    size_t k = 0;
    while(p[k] && p[k] != ' ' && p[k] != '\n' && k < sizeof(event_buf) - 1) {
        event_buf[k] = p[k];
        k++;
    }
    event_buf[k] = '\0';
    /* Match against the event-name table. */
    for(int e = 0; e < DEED_EVENT_COUNT; e++) {
        if(DEED_EVENT_NAMES[e] && strcmp(DEED_EVENT_NAMES[e], event_buf) == 0) {
            *delta_out = DEED_EVENT_TABLE[e].delta;
            return DEED_EVENT_TABLE[e].axis;
        }
    }
    return DEED_AXIS_COUNT;
}

void deeds_load(DeedsState* d, const char* real_self_id) {
    if(!d || !real_self_id) return;
    deeds_init(d);

    Storage* storage = furi_record_open(RECORD_STORAGE);
    char path[128];
    deeds_log_path(real_self_id, path, sizeof(path));

    File* file = storage_file_alloc(storage);
    if(storage_file_open(file, path, FSAM_READ, FSOM_OPEN_EXISTING)) {
        /* Read the whole log in one shot — bounded ~16KB worst case for v1
         * (each line ~70 bytes, ~230 lines fits a heavy season of play). */
        char buf[4096];
        size_t total = 0;
        while(total < sizeof(buf) - 1) {
            size_t got = storage_file_read(file, buf + total, sizeof(buf) - 1 - total);
            if(got == 0) break;
            total += got;
        }
        buf[total] = '\0';
        /* Walk line by line, accumulating axis deltas. */
        char* line = buf;
        while(line && *line) {
            char* nl = strchr(line, '\n');
            if(nl) *nl = '\0';
            int8_t delta = 0;
            uint8_t axis = deeds_parse_line(line, &delta);
            if(axis < DEED_AXIS_COUNT) {
                int32_t v = (int32_t)d->delta[axis] + (int32_t)delta;
                if(v > INT16_MAX) v = INT16_MAX;
                if(v < INT16_MIN) v = INT16_MIN;
                d->delta[axis] = (int16_t)v;
            }
            line = nl ? nl + 1 : NULL;
        }
        storage_file_close(file);
    }
    storage_file_free(file);
    furi_record_close(RECORD_STORAGE);
    d->loaded = true;
}

bool deeds_record(
    DeedsState* d, const char* real_self_id, const char* campaign_id,
    uint32_t turn, DeedEvent event) {
    if(!d || event >= DEED_EVENT_COUNT) return false;
    const DeedEventInfo* info = &DEED_EVENT_TABLE[event];

    /* Cap check (0 = uncapped). */
    if(info->cap > 0 && d->session_counts[event] >= info->cap) return false;

    /* Apply growth + bump session count. */
    int32_t v = (int32_t)d->delta[info->axis] + (int32_t)info->delta;
    if(v > INT16_MAX) v = INT16_MAX;
    if(v < INT16_MIN) v = INT16_MIN;
    d->delta[info->axis] = (int16_t)v;
    if(d->session_counts[event] < 255) d->session_counts[event]++;

    /* Append to log. Best-effort — if storage fails we still keep the
     * in-RAM growth so the player isn't penalized for a transient
     * SD-write hiccup; the next deeds_load reconciles from disk. */
    Storage* storage = furi_record_open(RECORD_STORAGE);
    char dir_path[128];
    char log_path[160];
    deeds_dir_path(real_self_id, dir_path, sizeof(dir_path));
    deeds_log_path(real_self_id, log_path, sizeof(log_path));
    storage_common_mkdir(storage, DEEDS_BASE_DIR);
    storage_common_mkdir(storage, dir_path);

    File* file = storage_file_alloc(storage);
    if(storage_file_open(file, log_path, FSAM_WRITE, FSOM_OPEN_APPEND)) {
        char line[96];
        /* TS is the in-game turn for now; an RTC-stamped TS lands with 48.F7. */
        int n = snprintf(
            line, sizeof(line), "DEED %lu %s %lu %s %d\n",
            (unsigned long)turn,
            (campaign_id && campaign_id[0]) ? campaign_id : "-",
            (unsigned long)turn,
            DEED_EVENT_NAMES[event] ? DEED_EVENT_NAMES[event] : "?",
            (int)info->delta);
        if(n > 0) storage_file_write(file, line, (size_t)n);
        storage_file_close(file);
    }
    storage_file_free(file);
    furi_record_close(RECORD_STORAGE);

    return true;
}

#else  /* SANCTUM_RPG_HOST_TEST — host harness gets stubs */

void deeds_load(DeedsState* d, const char* real_self_id) {
    (void)real_self_id;
    if(d) d->loaded = true;
}

bool deeds_record(
    DeedsState* d, const char* real_self_id, const char* campaign_id,
    uint32_t turn, DeedEvent event) {
    (void)real_self_id; (void)campaign_id; (void)turn;
    if(!d || event >= DEED_EVENT_COUNT) return false;
    const DeedEventInfo* info = &DEED_EVENT_TABLE[event];
    if(info->cap > 0 && d->session_counts[event] >= info->cap) return false;
    int32_t v = (int32_t)d->delta[info->axis] + (int32_t)info->delta;
    if(v > INT16_MAX) v = INT16_MAX;
    if(v < INT16_MIN) v = INT16_MIN;
    d->delta[info->axis] = (int16_t)v;
    if(d->session_counts[event] < 255) d->session_counts[event]++;
    return true;
}

#endif
