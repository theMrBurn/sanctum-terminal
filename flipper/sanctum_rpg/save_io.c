/*
 * save_io.c — see save_io.h for contract.
 *
 * Hard rules (from sanctum-engage AGENTS.md):
 *   - No hardcoded tunables in render/logic code. Paths and limits live
 *     as #defines at file top.
 *   - Atomic writes only — no half-written meta.json after a crash.
 *
 * The "JSON" we emit is canonical and minimal — a fixed-layout writer
 * pairs with a key-search reader. We do not parse arbitrary JSON.
 */

#include "save_io.h"

#include <furi.h>
#include <storage/storage.h>
#include <furi_hal_rtc.h>

#include "fov.h"  /* TORCH_FUEL_MAX (default fuel for old saves) */

#include <stdio.h>
#include <string.h>

/* ─── paths ────────────────────────────────────────────────────────── */

#define SAVE_ROOT      "/ext/apps_data/sanctum_rpg"
#define SAVE_CAMPAIGNS SAVE_ROOT "/campaigns"

#define META_BUF_SIZE     384  /* fits a v1 meta.json with headroom */
#define LINE_BUF_SIZE     128
#define MAX_CAMPAIGN_SLOT 999  /* "999/" — beyond this we report SaveIoFull */

/* ─── helpers ──────────────────────────────────────────────────────── */

static SaveIoResult ensure_dir(Storage* storage, const char* path) {
    if(storage_common_stat(storage, path, NULL) == FSE_OK) {
        return SaveIoOk;
    }
    if(storage_simply_mkdir(storage, path)) {
        return SaveIoOk;
    }
    /* simply_mkdir returns false if already-exists; verify. */
    if(storage_common_stat(storage, path, NULL) == FSE_OK) {
        return SaveIoOk;
    }
    return SaveIoFsError;
}

static uint64_t rtc_now_unix(void) {
    DateTime dt;
    furi_hal_rtc_get_datetime(&dt);
    return datetime_datetime_to_timestamp(&dt);
}

/* Stable non-zero seed derived from the campaign id (FNV-1a). Used as a
 * fallback when a save's `seed` is missing/zero/corrupt — so the world
 * stays consistent for that campaign instead of silently becoming
 * "world 0". This is a corruption recovery path, not the normal one. */
static uint32_t derive_seed_from_id(const char* id) {
    uint32_t h = 2166136261u;
    for(const char* p = id; *p; p++) {
        h ^= (uint8_t)*p;
        h *= 16777619u;
    }
    return h ? h : 1u;
}

static void meta_path(const char* campaign_id, char* out, size_t out_len) {
    snprintf(out, out_len, SAVE_CAMPAIGNS "/%s/meta.json", campaign_id);
}

static void meta_tmp_path(const char* campaign_id, char* out, size_t out_len) {
    snprintf(out, out_len, SAVE_CAMPAIGNS "/%s/meta.tmp", campaign_id);
}

static void campaign_dir(const char* campaign_id, char* out, size_t out_len) {
    snprintf(out, out_len, SAVE_CAMPAIGNS "/%s", campaign_id);
}

static void character_path(const char* campaign_id, char* out, size_t out_len) {
    snprintf(out, out_len, SAVE_CAMPAIGNS "/%s/character.json", campaign_id);
}

static void character_tmp_path(const char* campaign_id, char* out, size_t out_len) {
    snprintf(out, out_len, SAVE_CAMPAIGNS "/%s/character.tmp", campaign_id);
}

/* ─── canonical JSON writer ───────────────────────────────────────── */

static int format_meta_json(const CampaignMeta* m, char* buf, size_t buf_len) {
    /* Canonical layout — keys in fixed order, no trailing comma, no
     * pretty-printing variations. Reader relies on this. */
    return snprintf(
        buf, buf_len,
        "{\n"
        "  \"schema_version\": %u,\n"
        "  \"campaign_id\": \"%s\",\n"
        "  \"character_name\": \"%s\",\n"
        "  \"seed\": %lu,\n"
        "  \"started_at_unix\": %llu,\n"
        "  \"last_played_at_unix\": %llu,\n"
        "  \"permadeath\": %s\n"
        "}\n",
        (unsigned)m->schema_version,
        m->campaign_id,
        m->character_name,
        (unsigned long)m->seed,
        (unsigned long long)m->started_at_unix,
        (unsigned long long)m->last_played_at_unix,
        m->permadeath ? "true" : "false");
}

/* ─── canonical JSON reader (key search, not a real parser) ──────── */

static const char* find_value(const char* buf, const char* key) {
    /* Locate `"<key>":` and return pointer to the first char after `:`
     * (with leading whitespace skipped). NULL on miss. */
    char needle[64];
    snprintf(needle, sizeof(needle), "\"%s\":", key);
    const char* p = strstr(buf, needle);
    if(!p) return NULL;
    p += strlen(needle);
    while(*p == ' ' || *p == '\t') p++;
    return p;
}

static bool read_str(const char* buf, const char* key, char* out, size_t out_len) {
    const char* v = find_value(buf, key);
    if(!v || *v != '"') return false;
    v++;
    size_t i = 0;
    while(*v && *v != '"' && i + 1 < out_len) {
        out[i++] = *v++;
    }
    out[i] = '\0';
    return *v == '"';
}

static bool read_u32(const char* buf, const char* key, uint32_t* out) {
    const char* v = find_value(buf, key);
    if(!v) return false;
    *out = (uint32_t)strtoul(v, NULL, 10);
    return true;
}

static bool read_u64(const char* buf, const char* key, uint64_t* out) {
    const char* v = find_value(buf, key);
    if(!v) return false;
    *out = (uint64_t)strtoull(v, NULL, 10);
    return true;
}

static bool read_bool(const char* buf, const char* key, bool* out) {
    const char* v = find_value(buf, key);
    if(!v) return false;
    if(strncmp(v, "true", 4) == 0) { *out = true; return true; }
    if(strncmp(v, "false", 5) == 0) { *out = false; return true; }
    return false;
}

/* ─── public API ──────────────────────────────────────────────────── */

SaveIoResult save_io_init(void) {
    Storage* storage = furi_record_open(RECORD_STORAGE);
    SaveIoResult r = ensure_dir(storage, "/ext/apps_data");
    if(r == SaveIoOk) r = ensure_dir(storage, SAVE_ROOT);
    if(r == SaveIoOk) r = ensure_dir(storage, SAVE_CAMPAIGNS);
    furi_record_close(RECORD_STORAGE);
    return r;
}

int save_io_count_campaigns(void) {
    Storage* storage = furi_record_open(RECORD_STORAGE);
    File* dir = storage_file_alloc(storage);
    int count = 0;
    if(storage_dir_open(dir, SAVE_CAMPAIGNS)) {
        FileInfo info;
        char name[64];
        while(storage_dir_read(dir, &info, name, sizeof(name))) {
            if(file_info_is_dir(&info)) count++;
        }
        storage_dir_close(dir);
    }
    storage_file_free(dir);
    furi_record_close(RECORD_STORAGE);
    return count;
}

SaveIoResult save_io_most_recent_campaign(char* out_id, size_t out_len) {
    Storage* storage = furi_record_open(RECORD_STORAGE);
    File* dir = storage_file_alloc(storage);
    bool found = false;
    uint64_t best_ts = 0;

    if(storage_dir_open(dir, SAVE_CAMPAIGNS)) {
        FileInfo info;
        char name[64];
        while(storage_dir_read(dir, &info, name, sizeof(name))) {
            if(!file_info_is_dir(&info)) continue;
            /* Read this campaign's meta to compare timestamps. */
            CampaignMeta m;
            /* Have to close+reopen storage record? No — same handle is fine. */
            if(save_io_load_meta(name, &m) == SaveIoOk) {
                if(m.last_played_at_unix >= best_ts) {
                    best_ts = m.last_played_at_unix;
                    strncpy(out_id, name, out_len - 1);
                    out_id[out_len - 1] = '\0';
                    found = true;
                }
            }
        }
        storage_dir_close(dir);
    }
    storage_file_free(dir);
    furi_record_close(RECORD_STORAGE);
    return found ? SaveIoOk : SaveIoNotFound;
}

static SaveIoResult next_campaign_id(char* out_id, size_t out_len) {
    Storage* storage = furi_record_open(RECORD_STORAGE);
    File* dir = storage_file_alloc(storage);
    int highest = 0;
    if(storage_dir_open(dir, SAVE_CAMPAIGNS)) {
        FileInfo info;
        char name[64];
        while(storage_dir_read(dir, &info, name, sizeof(name))) {
            if(!file_info_is_dir(&info)) continue;
            int n = atoi(name);
            if(n > highest) highest = n;
        }
        storage_dir_close(dir);
    }
    storage_file_free(dir);
    furi_record_close(RECORD_STORAGE);

    int next = highest + 1;
    if(next > MAX_CAMPAIGN_SLOT) return SaveIoFull;
    /* Format manually — bounded by definition (0..999), 4 bytes incl NUL.
     * Avoids -Werror=format-truncation across snprintf width inference. */
    if(out_len < 4) return SaveIoFsError;
    out_id[0] = '0' + (char)(next / 100);
    out_id[1] = '0' + (char)((next / 10) % 10);
    out_id[2] = '0' + (char)(next % 10);
    out_id[3] = '\0';
    return SaveIoOk;
}

SaveIoResult save_io_new_campaign(
    const char* character_name,
    uint32_t seed,
    char* out_id,
    size_t out_len) {
    char id[SAVE_IO_CAMPAIGN_ID_MAX + 1];
    SaveIoResult r = next_campaign_id(id, sizeof(id));
    if(r != SaveIoOk) return r;

    Storage* storage = furi_record_open(RECORD_STORAGE);
    char dir[80];
    campaign_dir(id, dir, sizeof(dir));
    r = ensure_dir(storage, dir);
    furi_record_close(RECORD_STORAGE);
    if(r != SaveIoOk) return r;

    CampaignMeta m = {
        .seed = seed,
        .started_at_unix = rtc_now_unix(),
        .last_played_at_unix = rtc_now_unix(),
        .permadeath = false,
        .schema_version = SAVE_IO_SCHEMA_VERSION,
    };
    strncpy(m.campaign_id, id, sizeof(m.campaign_id) - 1);
    m.campaign_id[sizeof(m.campaign_id) - 1] = '\0';
    strncpy(m.character_name, character_name, sizeof(m.character_name) - 1);
    m.character_name[sizeof(m.character_name) - 1] = '\0';

    r = save_io_write_meta(&m);
    if(r != SaveIoOk) return r;

    strncpy(out_id, id, out_len - 1);
    out_id[out_len - 1] = '\0';
    return SaveIoOk;
}

SaveIoResult save_io_load_meta(const char* campaign_id, CampaignMeta* out) {
    Storage* storage = furi_record_open(RECORD_STORAGE);
    File* file = storage_file_alloc(storage);
    char path[80];
    meta_path(campaign_id, path, sizeof(path));

    SaveIoResult r = SaveIoOk;
    if(!storage_file_open(file, path, FSAM_READ, FSOM_OPEN_EXISTING)) {
        r = SaveIoNotFound;
        goto out;
    }
    char buf[META_BUF_SIZE];
    size_t n = storage_file_read(file, buf, sizeof(buf) - 1);
    storage_file_close(file);
    if(n == 0) { r = SaveIoParseError; goto out; }
    buf[n] = '\0';

    /* Tolerant load (spec 43 §14.0): pre-init sane defaults, overlay
     * whatever the file actually has, NEVER hard-reject on a schema
     * mismatch or a missing field. A schema bump must not wipe saves;
     * new fields just default until the player re-saves. The only fatal
     * condition is an unreadable/empty file (handled above). */
    out->schema_version = SAVE_IO_SCHEMA_VERSION;
    strncpy(out->campaign_id, campaign_id, sizeof(out->campaign_id) - 1);
    out->campaign_id[sizeof(out->campaign_id) - 1] = '\0';
    out->character_name[0] = '\0';
    out->started_at_unix = 0;
    out->last_played_at_unix = 0;
    out->permadeath = false;

    uint32_t schema = SAVE_IO_SCHEMA_VERSION;
    read_u32(buf, "schema_version", &schema); /* informational; accept any */
    out->schema_version = (uint8_t)schema;

    /* campaign_id from file if present, else the directory name we were
     * given (always correct since the dir IS the id). */
    read_str(buf, "campaign_id", out->campaign_id, sizeof(out->campaign_id));
    read_str(buf, "character_name", out->character_name, sizeof(out->character_name));

    /* Seed guard: missing/zero/corrupt seed → stable per-id fallback,
     * never silent world 0. */
    uint32_t seed = 0;
    if(read_u32(buf, "seed", &seed) && seed != 0) {
        out->seed = seed;
    } else {
        out->seed = derive_seed_from_id(out->campaign_id);
    }

    read_u64(buf, "started_at_unix", &out->started_at_unix);
    read_u64(buf, "last_played_at_unix", &out->last_played_at_unix);
    read_bool(buf, "permadeath", &out->permadeath);

out:
    storage_file_free(file);
    furi_record_close(RECORD_STORAGE);
    return r;
}

SaveIoResult save_io_write_meta(const CampaignMeta* meta) {
    Storage* storage = furi_record_open(RECORD_STORAGE);
    File* file = storage_file_alloc(storage);

    char tmp_path[80], real_path[80];
    meta_tmp_path(meta->campaign_id, tmp_path, sizeof(tmp_path));
    meta_path(meta->campaign_id, real_path, sizeof(real_path));

    SaveIoResult r = SaveIoOk;
    if(!storage_file_open(file, tmp_path, FSAM_WRITE, FSOM_CREATE_ALWAYS)) {
        r = SaveIoFsError;
        goto out;
    }
    char buf[META_BUF_SIZE];
    int len = format_meta_json(meta, buf, sizeof(buf));
    if(len <= 0 || (size_t)len >= sizeof(buf)) {
        storage_file_close(file);
        r = SaveIoFsError;
        goto out;
    }
    if(storage_file_write(file, buf, len) != (size_t)len) {
        storage_file_close(file);
        r = SaveIoFsError;
        goto out;
    }
    storage_file_close(file);

    /* Atomic rename — overwrites any prior meta.json. */
    if(storage_common_remove(storage, real_path) != FSE_OK) {
        /* missing is fine; other errors are not — but rename below will
         * tell us either way. */
    }
    FS_Error rerr = storage_common_rename(storage, tmp_path, real_path);
    if(rerr != FSE_OK) r = SaveIoFsError;

out:
    storage_file_free(file);
    furi_record_close(RECORD_STORAGE);
    return r;
}

SaveIoResult save_io_touch_played(const char* campaign_id) {
    CampaignMeta m;
    SaveIoResult r = save_io_load_meta(campaign_id, &m);
    if(r != SaveIoOk) return r;
    m.last_played_at_unix = rtc_now_unix();
    return save_io_write_meta(&m);
}

/* ─── character.json — atomic write / read ────────────────────────── */

static int format_character_json(const CharacterState* c, char* buf, size_t buf_len) {
    return snprintf(
        buf, buf_len,
        "{\n"
        "  \"schema_version\": %u,\n"
        "  \"campaign_id\": \"%s\",\n"
        "  \"chunk_x\": %d,\n"
        "  \"chunk_y\": %d,\n"
        "  \"player_x\": %d,\n"
        "  \"player_y\": %d,\n"
        "  \"hp\": %u,\n"
        "  \"max_hp\": %u,\n"
        "  \"mp\": %u,\n"
        "  \"max_mp\": %u,\n"
        "  \"level\": %u,\n"
        "  \"credits\": %lu,\n"
        "  \"identified\": %llu,\n"
        "  \"turn\": %lu,\n"
        "  \"torch_fuel\": %u\n"
        "}\n",
        (unsigned)c->schema_version,
        c->campaign_id,
        (int)c->chunk_x,
        (int)c->chunk_y,
        (int)c->player_x,
        (int)c->player_y,
        (unsigned)c->hp,
        (unsigned)c->max_hp,
        (unsigned)c->mp,
        (unsigned)c->max_mp,
        (unsigned)c->level,
        (unsigned long)c->credits,
        (unsigned long long)c->identified,
        (unsigned long)c->turn,
        (unsigned)c->torch_fuel);
}

SaveIoResult save_io_load_character(const char* campaign_id, CharacterState* out) {
    Storage* storage = furi_record_open(RECORD_STORAGE);
    File* file = storage_file_alloc(storage);
    char path[80];
    character_path(campaign_id, path, sizeof(path));

    SaveIoResult r = SaveIoOk;
    if(!storage_file_open(file, path, FSAM_READ, FSOM_OPEN_EXISTING)) {
        r = SaveIoNotFound;
        goto out;
    }
    char buf[META_BUF_SIZE];
    size_t n = storage_file_read(file, buf, sizeof(buf) - 1);
    storage_file_close(file);
    if(n == 0) { r = SaveIoParseError; goto out; }
    buf[n] = '\0';

    /* Tolerant load (spec 43 §14.0): pre-init a sane baseline, overlay
     * whatever the file has, never hard-reject on schema/missing fields.
     * Baseline keeps a partial/older save from loading dead-on-arrival
     * (e.g. hp would otherwise default to 0). Future fields (skills,
     * age, last-death-type) simply default until the player re-saves. */
    out->schema_version = SAVE_IO_SCHEMA_VERSION;
    strncpy(out->campaign_id, campaign_id, sizeof(out->campaign_id) - 1);
    out->campaign_id[sizeof(out->campaign_id) - 1] = '\0';
    out->chunk_x = 0;
    out->chunk_y = 0;
    out->player_x = 1;
    out->player_y = 1;
    out->hp = 10;
    out->max_hp = 10;
    out->mp = 5;
    out->max_mp = 5;
    out->level = 1;
    out->credits = 0;
    out->identified = 0;
    out->turn = 0;
    out->torch_fuel = TORCH_FUEL_MAX; /* old saves load with full fuel, not blind */

    uint32_t schema = SAVE_IO_SCHEMA_VERSION;
    read_u32(buf, "schema_version", &schema); /* informational; accept any */
    out->schema_version = (uint8_t)schema;

    read_str(buf, "campaign_id", out->campaign_id, sizeof(out->campaign_id));

    uint32_t v32;
    uint64_t v64;
    if(read_u32(buf, "chunk_x", &v32))   out->chunk_x  = (int16_t)(int32_t)v32;
    if(read_u32(buf, "chunk_y", &v32))   out->chunk_y  = (int16_t)(int32_t)v32;
    if(read_u32(buf, "player_x", &v32))  out->player_x = (int16_t)(int32_t)v32;
    if(read_u32(buf, "player_y", &v32))  out->player_y = (int16_t)(int32_t)v32;
    if(read_u32(buf, "hp", &v32))        out->hp       = (uint16_t)v32;
    if(read_u32(buf, "max_hp", &v32))    out->max_hp   = (uint16_t)v32;
    if(read_u32(buf, "mp", &v32))        out->mp       = (uint16_t)v32;
    if(read_u32(buf, "max_mp", &v32))    out->max_mp   = (uint16_t)v32;
    if(read_u32(buf, "level", &v32))     out->level    = (uint8_t)v32;
    if(read_u64(buf, "credits", &v64))   out->credits  = (uint32_t)v64;
    if(read_u64(buf, "identified", &v64)) out->identified = v64;
    if(read_u32(buf, "turn", &v32))      out->turn       = v32;
    if(read_u32(buf, "torch_fuel", &v32)) out->torch_fuel = (uint16_t)v32;

out:
    storage_file_free(file);
    furi_record_close(RECORD_STORAGE);
    return r;
}

SaveIoResult save_io_write_character(const CharacterState* state) {
    Storage* storage = furi_record_open(RECORD_STORAGE);
    File* file = storage_file_alloc(storage);

    char tmp_path[80], real_path[80];
    character_tmp_path(state->campaign_id, tmp_path, sizeof(tmp_path));
    character_path(state->campaign_id, real_path, sizeof(real_path));

    SaveIoResult r = SaveIoOk;
    if(!storage_file_open(file, tmp_path, FSAM_WRITE, FSOM_CREATE_ALWAYS)) {
        r = SaveIoFsError;
        goto out;
    }
    char buf[META_BUF_SIZE];
    int len = format_character_json(state, buf, sizeof(buf));
    if(len <= 0 || (size_t)len >= sizeof(buf)) {
        storage_file_close(file);
        r = SaveIoFsError;
        goto out;
    }
    if(storage_file_write(file, buf, len) != (size_t)len) {
        storage_file_close(file);
        r = SaveIoFsError;
        goto out;
    }
    storage_file_close(file);

    storage_common_remove(storage, real_path);  /* ignore "not found" */
    FS_Error rerr = storage_common_rename(storage, tmp_path, real_path);
    if(rerr != FSE_OK) r = SaveIoFsError;

out:
    storage_file_free(file);
    furi_record_close(RECORD_STORAGE);
    return r;
}
