/*
 * deltas.c — see deltas.h.
 */

#include "deltas.h"

#include <furi.h>
#include <storage/storage.h>

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define DELTAS_DIR_FMT   "/ext/apps_data/sanctum_rpg/campaigns/%s/deltas"
#define DELTAS_FILE_FMT  "/ext/apps_data/sanctum_rpg/campaigns/%s/deltas/g0_%d_%d.txt"
#define DELTAS_TMP_FMT   "/ext/apps_data/sanctum_rpg/campaigns/%s/deltas/g0_%d_%d.tmp"

#define READ_BUF_SIZE    4096
#define WRITE_BUF_SIZE   4096

/* ─── paths ─────────────────────────────────────────────────────── */

static void deltas_dir(const char* campaign_id, char* out, size_t out_len) {
    snprintf(out, out_len, DELTAS_DIR_FMT, campaign_id);
}

static void deltas_file_path(
    const char* campaign_id, int cx, int cy, char* out, size_t out_len) {
    snprintf(out, out_len, DELTAS_FILE_FMT, campaign_id, cx, cy);
}

static void deltas_tmp_path(
    const char* campaign_id, int cx, int cy, char* out, size_t out_len) {
    snprintf(out, out_len, DELTAS_TMP_FMT, campaign_id, cx, cy);
}

static bool ensure_deltas_dir(const char* campaign_id) {
    Storage* storage = furi_record_open(RECORD_STORAGE);
    char path[120];
    deltas_dir(campaign_id, path, sizeof(path));
    bool ok = (storage_common_stat(storage, path, NULL) == FSE_OK) ||
              storage_simply_mkdir(storage, path) ||
              (storage_common_stat(storage, path, NULL) == FSE_OK);
    furi_record_close(RECORD_STORAGE);
    return ok;
}

/* ─── reset / apply ─────────────────────────────────────────────── */

void deltas_reset(ChunkDeltas* d, int chunk_x, int chunk_y) {
    d->chunk_x = chunk_x;
    d->chunk_y = chunk_y;
    d->count = 0;
    d->kill_count = 0;
}

void deltas_apply_to_world(const ChunkDeltas* d, World* w) {
    for(int i = 0; i < d->count; i++) {
        int x = d->items[i].x;
        int y = d->items[i].y;
        if(x < 0 || x >= WORLD_COLS || y < 0 || y >= WORLD_ROWS) continue;
        w->tiles[y][x] = d->items[i].tile;
    }
}

/* ─── load ──────────────────────────────────────────────────────── */

/* Parse one mutation line "x y c" into m. Returns true on success. */
static bool parse_mutation_line(const char* line, TileMutation* m) {
    int x, y;
    char tile;
    /* Format: integer space integer space single-char. The tile char
     * may be any printable; we don't restrict here. */
    int n = sscanf(line, "%d %d %c", &x, &y, &tile);
    if(n != 3) return false;
    if(x < -127 || x > 127 || y < -127 || y > 127) return false;
    m->x = (int8_t)x;
    m->y = (int8_t)y;
    m->tile = tile;
    return true;
}

/* Parse "K x y" line into a kill record. Returns true on success. */
static bool parse_kill_line(const char* line, CreatureKill* k) {
    if(line[0] != 'K' || line[1] != ' ') return false;
    int x, y;
    int n = sscanf(line + 2, "%d %d", &x, &y);
    if(n != 2) return false;
    if(x < 0 || x > 255 || y < 0 || y > 255) return false;
    k->spawn_x = (uint8_t)x;
    k->spawn_y = (uint8_t)y;
    return true;
}

SaveIoResult deltas_load(
    const char* campaign_id, int chunk_x, int chunk_y, ChunkDeltas* out) {
    deltas_reset(out, chunk_x, chunk_y);

    Storage* storage = furi_record_open(RECORD_STORAGE);
    File* file = storage_file_alloc(storage);
    char path[160];
    deltas_file_path(campaign_id, chunk_x, chunk_y, path, sizeof(path));

    SaveIoResult r = SaveIoOk;
    if(storage_common_stat(storage, path, NULL) != FSE_OK) {
        /* No file → legitimately no deltas for this chunk. */
        goto out;
    }
    if(!storage_file_open(file, path, FSAM_READ, FSOM_OPEN_EXISTING)) {
        r = SaveIoFsError;
        goto out;
    }
    char buf[READ_BUF_SIZE];
    size_t n = storage_file_read(file, buf, sizeof(buf) - 1);
    storage_file_close(file);
    if(n == 0) goto out;
    buf[n] = '\0';

    /* Parse line-by-line without strtok_r (firmware-disabled symbol).
     * Walk the buffer, replacing \n with \0 in-place, yielding lines. */
    char* p = buf;
    char* line_start = p;
    bool first_line = true;

    while(*p != '\0' || line_start < p) {
        bool eol = (*p == '\n' || *p == '\0');
        if(!eol) {
            p++;
            continue;
        }
        /* p points at terminator; line_start..p-1 is the line. */
        bool last = (*p == '\0');
        *p = '\0';

        const char* line = line_start;
        if(first_line) {
            first_line = false;
            int version = 0;
            if(line[0] == 'v') {
                version = atoi(line + 1);
            }
            if(version != DELTAS_SCHEMA_VERSION) {
                r = SaveIoParseError;
                goto out;
            }
        } else if(line[0] != '\0' && line[0] != '#') {
            /* Creature-kill line ("K x y") OR tile-mutation line ("x y c").
             * Old format (no prefix) is parsed as a mutation — back-compat. */
            if(line[0] == 'K' && line[1] == ' ') {
                if(out->kill_count < DELTAS_MAX_KILLS_PER_CHUNK) {
                    CreatureKill k;
                    if(parse_kill_line(line, &k)) {
                        out->kills[out->kill_count++] = k;
                    }
                }
            } else {
                if(out->count >= DELTAS_MAX_PER_CHUNK) {
                    r = SaveIoFull;
                    break;
                }
                TileMutation m;
                if(parse_mutation_line(line, &m)) {
                    out->items[out->count++] = m;
                }
            }
            /* Malformed lines are skipped silently — tolerant on read. */
        }

        if(last) break;
        p++;
        line_start = p;
    }

out:
    storage_file_free(file);
    furi_record_close(RECORD_STORAGE);
    return r;
}

/* ─── write ─────────────────────────────────────────────────────── */

static SaveIoResult write_deltas_atomic(
    const char* campaign_id, const ChunkDeltas* d) {
    if(!ensure_deltas_dir(campaign_id)) return SaveIoFsError;

    Storage* storage = furi_record_open(RECORD_STORAGE);
    File* file = storage_file_alloc(storage);
    char tmp_path[160], real_path[160];
    deltas_tmp_path(campaign_id, d->chunk_x, d->chunk_y, tmp_path, sizeof(tmp_path));
    deltas_file_path(campaign_id, d->chunk_x, d->chunk_y, real_path, sizeof(real_path));

    SaveIoResult r = SaveIoOk;
    if(!storage_file_open(file, tmp_path, FSAM_WRITE, FSOM_CREATE_ALWAYS)) {
        r = SaveIoFsError;
        goto out;
    }
    char buf[WRITE_BUF_SIZE];
    int len = snprintf(buf, sizeof(buf), "v%d\n", DELTAS_SCHEMA_VERSION);
    if(len <= 0 || (size_t)len >= sizeof(buf)) { r = SaveIoFsError; storage_file_close(file); goto out; }
    if(storage_file_write(file, buf, len) != (size_t)len) {
        storage_file_close(file);
        r = SaveIoFsError;
        goto out;
    }
    for(int i = 0; i < d->count; i++) {
        len = snprintf(buf, sizeof(buf), "%d %d %c\n",
                       (int)d->items[i].x, (int)d->items[i].y, d->items[i].tile);
        if(len <= 0 || (size_t)len >= sizeof(buf)) { r = SaveIoFsError; break; }
        if(storage_file_write(file, buf, len) != (size_t)len) { r = SaveIoFsError; break; }
    }
    for(int i = 0; i < d->kill_count && r == SaveIoOk; i++) {
        len = snprintf(buf, sizeof(buf), "K %u %u\n",
                       (unsigned)d->kills[i].spawn_x, (unsigned)d->kills[i].spawn_y);
        if(len <= 0 || (size_t)len >= sizeof(buf)) { r = SaveIoFsError; break; }
        if(storage_file_write(file, buf, len) != (size_t)len) { r = SaveIoFsError; break; }
    }
    storage_file_close(file);
    if(r != SaveIoOk) goto out;

    storage_common_remove(storage, real_path);  /* ignore "not found" */
    FS_Error rerr = storage_common_rename(storage, tmp_path, real_path);
    if(rerr != FSE_OK) r = SaveIoFsError;

out:
    storage_file_free(file);
    furi_record_close(RECORD_STORAGE);
    return r;
}

SaveIoResult deltas_record(
    const char* campaign_id, ChunkDeltas* d, int x, int y, char tile) {
    if(d->count >= DELTAS_MAX_PER_CHUNK) return SaveIoFull;
    /* Tile coords are int8_t — chunks are 16×6, fits trivially. */
    d->items[d->count].x = (int8_t)x;
    d->items[d->count].y = (int8_t)y;
    d->items[d->count].tile = tile;
    d->count++;
    return write_deltas_atomic(campaign_id, d);
}

SaveIoResult deltas_record_kill(
    const char* campaign_id, ChunkDeltas* d, uint8_t spawn_x, uint8_t spawn_y) {
    if(d->kill_count >= DELTAS_MAX_KILLS_PER_CHUNK) return SaveIoFull;
    /* Dedupe — if this spawn is already recorded, no-op. */
    for(int i = 0; i < d->kill_count; i++) {
        if(d->kills[i].spawn_x == spawn_x && d->kills[i].spawn_y == spawn_y) {
            return SaveIoOk;
        }
    }
    d->kills[d->kill_count].spawn_x = spawn_x;
    d->kills[d->kill_count].spawn_y = spawn_y;
    d->kill_count++;
    return write_deltas_atomic(campaign_id, d);
}
