/* The app on the host: sanctum_rpg.c, save_io.c and deltas.c as the device
 * builds them, unchanged, against test/host/shim, driven by a script.
 *
 *   build/host/sanctum_host SCRIPT ROOT TRACE
 *
 * ROOT is a folder standing in for the SD card's /ext (fresh, or a
 * fixture copied in). The script:
 *   clock UNIX            the local time the RTC reports (fixed until changed)
 *   random SEED           furi_hal_random's seed
 *   key K [TYPE] [xN]     K = up down left right ok back; TYPE = short (default) long repeat
 *   fuzz N SEED           N random key events from SEED
 *   # comment
 * After each event the app has handled (and drawn), one trace step: the
 * screen, the status line, the frame's hash, notifications, the character
 * as the game last saved it, the chunk, the player, the creatures. When the
 * script runs out (or the app quits), the whole ROOT tree, hashed per file.
 * This is the reference the extraction of the game loop must reproduce
 * (README / spec: test/host). */

#include "../../sanctum_rpg.c"

#include <dirent.h>
#include <errno.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

/* ── the inputs ───────────────────────────────────────────────────── */
uint64_t host_clock_unix = 1762430400ull;    /* 2025-11-06 12:00 */
uint32_t host_random_state = 1;
const char* host_root = "build/host/root";

typedef struct { InputKey key; InputType type; } HostEv;
static HostEv* evs;
static int nevs, cap_evs, at_ev;
static struct { int at; uint64_t clock; } *clocks;
static int nclocks;
static FILE* trace;
static int step;
static char notes[256];

static uint32_t xs(uint32_t* s) { *s ^= *s << 13; *s ^= *s >> 17; *s ^= *s << 5; return *s; }

static void push(InputKey k, InputType t) {
    if(nevs == cap_evs) { cap_evs = cap_evs ? cap_evs * 2 : 256; evs = realloc(evs, cap_evs * sizeof(*evs)); }
    evs[nevs].key = k; evs[nevs].type = t; nevs++;
}

static InputKey key_of(const char* s) {
    static const char* N[] = {"up", "down", "right", "left", "ok", "back"};
    for(int i = 0; i < 6; i++) if(!strcmp(s, N[i])) return (InputKey)i;
    fprintf(stderr, "host: bad key %s\n", s); exit(2);
}

static void read_script(const char* path) {
    FILE* f = fopen(path, "r");
    if(!f) { fprintf(stderr, "host: can't read %s\n", path); exit(2); }
    char line[256];
    while(fgets(line, sizeof(line), f)) {
        char a[32] = "", b[32] = "", c[32] = "", d[32] = "";
        if(line[0] == '#' || sscanf(line, "%31s %31s %31s %31s", a, b, c, d) < 1) continue;
        if(!strcmp(a, "clock")) {
            clocks = realloc(clocks, (nclocks + 1) * sizeof(*clocks));
            clocks[nclocks].at = nevs; clocks[nclocks].clock = strtoull(b, NULL, 10); nclocks++;
        } else if(!strcmp(a, "random")) host_random_state = (uint32_t)strtoul(b, NULL, 10) | 1u;
        else if(!strcmp(a, "key")) {
            InputType t = InputTypeShort;
            int n = 1;
            const char* opts[2] = {c, d};
            for(int i = 0; i < 2; i++) {
                if(!strcmp(opts[i], "long")) t = InputTypeLong;
                else if(!strcmp(opts[i], "repeat")) t = InputTypeRepeat;
                else if(opts[i][0] == 'x') n = atoi(opts[i] + 1);
            }
            for(int i = 0; i < n; i++) push(key_of(b), t);
        } else if(!strcmp(a, "fuzz")) {
            int n = atoi(b);
            uint32_t s = (uint32_t)strtoul(c, NULL, 10) | 1u;
            for(int i = 0; i < n; i++) {
                uint32_t r = xs(&s);
                /* walking-heavy: the d-pad most, OK often, Back rarely (it leaves the world) */
                static const InputKey K[16] = {InputKeyUp, InputKeyUp, InputKeyDown, InputKeyDown, InputKeyLeft,
                    InputKeyLeft, InputKeyRight, InputKeyRight, InputKeyUp, InputKeyRight, InputKeyLeft, InputKeyDown,
                    InputKeyOk, InputKeyOk, InputKeyOk, InputKeyBack};
                InputType t = ((r >> 8) % 23 == 0) ? InputTypeLong : InputTypeShort;
                push(K[r & 15], t);
            }
        } else { fprintf(stderr, "host: bad script line: %s", line); exit(2); }
    }
    fclose(f);
}

/* ── the trace ────────────────────────────────────────────────────── */
static uint64_t fnv(const void* p, size_t n, uint64_t h) {
    const uint8_t* b = p;
    for(size_t i = 0; i < n; i++) h = (h ^ b[i]) * 0x100000001B3ULL;
    return h;
}
#define FNV0 0xCBF29CE484222325ULL

static AppState* app;                 /* the draw callback's context: the app's state */
static ViewPortDrawCallback app_draw;
static uint64_t frame_hash;

static void path_of(const char* ext, char* out, size_t n) {
    if(!strncmp(ext, "/ext", 4)) snprintf(out, n, "%s%s", host_root, ext + 4);
    else snprintf(out, n, "%s/%s", host_root, ext);
}

static uint64_t file_hash(const char* real, long* size) {
    FILE* f = fopen(real, "rb");
    *size = -1;
    if(!f) return 0;
    uint64_t h = FNV0;
    char buf[4096];
    size_t n;
    *size = 0;
    while((n = fread(buf, 1, sizeof(buf), f)) > 0) { h = fnv(buf, n, h); *size += (long)n; }
    fclose(f);
    return h;
}

static void trace_step(const char* why) {
    if(!trace || !app) return;
    AppState* st = app;
    fprintf(trace, "step %d %s screen %d status \"%s\" frame %016llx", step++, why, (int)st->screen,
            st->status_line ? st->status_line : "", (unsigned long long)frame_hash);
    if(notes[0]) fprintf(trace, " notes%s", notes);
    notes[0] = '\0';
    fprintf(trace, "\n");
    if(st->campaign_loaded) {
        char p[512];
        long size;
        char ext[160];
        snprintf(ext, sizeof(ext), "/ext/apps_data/sanctum_rpg/campaigns/%s/character.json", st->character.campaign_id);
        path_of(ext, p, sizeof(p));
        uint64_t ch = file_hash(p, &size);
        fprintf(trace, "  at chunk %d %d pos %d %d turn %u hp %u fuel %u hollow %u character.json %016llx\n",
                st->character.chunk_x, st->character.chunk_y, st->character.player_x, st->character.player_y,
                (unsigned)st->character.turn, (unsigned)st->character.hp, (unsigned)st->character.torch_fuel,
                (unsigned)st->in_hollow, (unsigned long long)ch);
        fprintf(trace, "  world %016llx seen %016llx creatures %d:", (unsigned long long)fnv(st->world.tiles, sizeof(st->world.tiles), FNV0),
                (unsigned long long)fnv(st->seen, sizeof(st->seen), FNV0), st->creature_count);
        for(int i = 0; i < st->creature_count; i++) {
            const Creature* c = &st->creatures[i];
            fprintf(trace, " %u.%u@%u,%u/%u%s", c->family_id, c->trait_id, c->x, c->y, c->state, c->alive ? "" : "x");
        }
        fprintf(trace, "\n");
    }
}

static int cmpstr(const void* a, const void* b) { return strcmp(*(char* const*)a, *(char* const*)b); }

static void trace_tree(const char* dir, const char* rel) {
    DIR* d = opendir(dir);
    if(!d) return;
    char* names[1024];
    int n = 0;
    struct dirent* e;
    while((e = readdir(d)) && n < 1024)
        if(strcmp(e->d_name, ".") && strcmp(e->d_name, "..")) names[n++] = strdup(e->d_name);
    closedir(d);
    qsort(names, n, sizeof(char*), cmpstr);
    for(int i = 0; i < n; i++) {
        char p[1024], r[1024];
        snprintf(p, sizeof(p), "%s/%s", dir, names[i]);
        snprintf(r, sizeof(r), "%s/%s", rel, names[i]);
        struct stat sb;
        if(!stat(p, &sb) && S_ISDIR(sb.st_mode)) trace_tree(p, r);
        else {
            long size;
            uint64_t h = file_hash(p, &size);
            fprintf(trace, "file %s %ld %016llx\n", r, size, (unsigned long long)h);
        }
        free(names[i]);
    }
}

static void finish(int code) {
    trace_step("end");
    trace_tree(host_root, "");
    fclose(trace);
    exit(code);
}

void host_note(const char* what) {
    size_t l = strlen(notes);
    snprintf(notes + l, sizeof(notes) - l, " %s", what);
}

/* ── furi ─────────────────────────────────────────────────────────── */
static int dummy_record;
void* furi_record_open(const char* name) { (void)name; return &dummy_record; }
void furi_record_close(const char* name) { (void)name; }
struct FuriMessageQueue { int unused; };
static struct FuriMessageQueue the_queue;
FuriMessageQueue* furi_message_queue_alloc(uint32_t count, uint32_t size) { (void)count; (void)size; return &the_queue; }
void furi_message_queue_free(FuriMessageQueue* q) { (void)q; }
FuriStatus furi_message_queue_put(FuriMessageQueue* q, const void* msg, uint32_t t) { (void)q; (void)msg; (void)t; return FuriStatusOk; }
FuriStatus furi_message_queue_get(FuriMessageQueue* q, void* msg, uint32_t t) {
    (void)q; (void)t;
    if(at_ev > 0) trace_step("after");
    if(at_ev >= nevs) finish(0);
    for(int i = 0; i < nclocks; i++) if(clocks[i].at == at_ev) host_clock_unix = clocks[i].clock;
    InputEvent* e = msg;
    memset(e, 0, sizeof(*e));
    e->key = evs[at_ev].key;
    e->type = evs[at_ev].type;
    e->sequence = (uint32_t)at_ev;
    fprintf(trace, "event %d key %d type %d\n", at_ev, (int)e->key, (int)e->type);
    at_ev++;
    return FuriStatusOk;
}
void furi_delay_ms(uint32_t ms) { (void)ms; }

/* ── clock, random ────────────────────────────────────────────────── */
void furi_hal_rtc_get_datetime(DateTime* dt) {
    time_t t = (time_t)host_clock_unix;
    struct tm tm;
    gmtime_r(&t, &tm);
    dt->year = (uint16_t)(tm.tm_year + 1900); dt->month = (uint8_t)(tm.tm_mon + 1); dt->day = (uint8_t)tm.tm_mday;
    dt->hour = (uint8_t)tm.tm_hour; dt->minute = (uint8_t)tm.tm_min; dt->second = (uint8_t)tm.tm_sec;
    dt->weekday = (uint8_t)(tm.tm_wday == 0 ? 7 : tm.tm_wday);
}
uint32_t datetime_datetime_to_timestamp(DateTime* dt) {
    struct tm tm = {0};
    tm.tm_year = dt->year - 1900; tm.tm_mon = dt->month - 1; tm.tm_mday = dt->day;
    tm.tm_hour = dt->hour; tm.tm_min = dt->minute; tm.tm_sec = dt->second;
    return (uint32_t)timegm(&tm);
}
uint32_t furi_hal_random_get(void) { return xs(&host_random_state); }

/* ── notifications ────────────────────────────────────────────────── */
const NotificationSequence sequence_success = {"success"}, sequence_single_vibro = {"vibro"},
                           sequence_error = {"error"};
void notification_message(NotificationApp* a, const NotificationSequence* seq) { (void)a; host_note(seq->name); }

/* ── gui ──────────────────────────────────────────────────────────── */
struct ViewPort { int unused; };
static struct ViewPort the_vp;
ViewPort* view_port_alloc(void) { return &the_vp; }
void view_port_free(ViewPort* vp) { (void)vp; }
void view_port_draw_callback_set(ViewPort* vp, ViewPortDrawCallback cb, void* ctx) {
    (void)vp; app_draw = cb; app = (AppState*)ctx;
}
void view_port_input_callback_set(ViewPort* vp, ViewPortInputCallback cb, void* ctx) { (void)vp; (void)cb; (void)ctx; }
void view_port_update(ViewPort* vp) {
    (void)vp;
    static Canvas c;
    canvas_clear(&c);
    if(app_draw) app_draw(&c, app);
    frame_hash = fnv(c.px, sizeof(c.px), frame_hash ^ 0x9E3779B97F4A7C15ULL);
}
void gui_add_view_port(Gui* gui, ViewPort* vp, GuiLayer layer) { (void)gui; (void)vp; (void)layer; }
void gui_remove_view_port(Gui* gui, ViewPort* vp) { (void)gui; (void)vp; }

/* ── storage: /ext is ROOT ────────────────────────────────────────── */
struct File { FILE* f; DIR* d; char path[512]; char** names; int n, at; };
File* storage_file_alloc(Storage* s) { (void)s; return calloc(1, sizeof(File)); }
static void dir_drop(File* f) {
    for(int i = 0; i < f->n; i++) free(f->names[i]);
    free(f->names);
    f->names = NULL; f->n = f->at = 0;
}
void storage_file_free(File* f) { if(f) { if(f->f) fclose(f->f); dir_drop(f); free(f); } }
bool storage_file_open(File* f, const char* path, FS_AccessMode am, FS_OpenMode om) {
    char p[512];
    path_of(path, p, sizeof(p));
    const char* mode = "rb";
    if(am & FSAM_WRITE) mode = (om & FSOM_OPEN_APPEND) ? "ab" : (om & FSOM_CREATE_ALWAYS) ? "wb" : "r+b";
    if((om & FSOM_OPEN_EXISTING) && access(p, F_OK)) return false;
    f->f = fopen(p, mode);
    if(!f->f && (am & FSAM_WRITE) && (om & FSOM_OPEN_ALWAYS)) f->f = fopen(p, "w+b");
    return f->f != NULL;
}
bool storage_file_close(File* f) { if(f->f) { fclose(f->f); f->f = NULL; } return true; }
size_t storage_file_read(File* f, void* buf, size_t n) { return f->f ? fread(buf, 1, n, f->f) : 0; }
size_t storage_file_write(File* f, const void* buf, size_t n) { return f->f ? fwrite(buf, 1, n, f->f) : 0; }
FS_Error storage_common_stat(Storage* s, const char* path, FileInfo* info) {
    (void)s;
    char p[512];
    path_of(path, p, sizeof(p));
    struct stat sb;
    if(stat(p, &sb)) return FSE_NOT_EXIST;
    if(info) { info->size = (uint64_t)sb.st_size; info->flags = S_ISDIR(sb.st_mode) ? FSF_DIRECTORY : 0; }
    return FSE_OK;
}
FS_Error storage_common_rename(Storage* s, const char* from, const char* to) {
    (void)s;
    char a[512], b[512];
    path_of(from, a, sizeof(a)); path_of(to, b, sizeof(b));
    return rename(a, b) ? FSE_INTERNAL : FSE_OK;
}
FS_Error storage_common_remove(Storage* s, const char* path) {
    (void)s;
    char p[512];
    path_of(path, p, sizeof(p));
    return remove(p) ? FSE_NOT_EXIST : FSE_OK;
}
FS_Error storage_common_mkdir(Storage* s, const char* path) {
    (void)s;
    char p[512];
    path_of(path, p, sizeof(p));
    if(!mkdir(p, 0755)) return FSE_OK;
    return errno == EEXIST ? FSE_EXIST : FSE_INTERNAL;
}
bool storage_simply_mkdir(Storage* s, const char* path) {
    FS_Error e = storage_common_mkdir(s, path);
    return e == FSE_OK || e == FSE_EXIST;
}
/* directory entries come back sorted, so the order is the host's no matter
 * the filesystem (the device's FAT order is creation order) */
bool storage_dir_open(File* f, const char* path) {
    path_of(path, f->path, sizeof(f->path));
    DIR* d = opendir(f->path);
    if(!d) return false;
    dir_drop(f);
    struct dirent* e;
    int cap = 0;
    while((e = readdir(d))) {
        if(!strcmp(e->d_name, ".") || !strcmp(e->d_name, "..")) continue;
        if(f->n == cap) { cap = cap ? cap * 2 : 16; f->names = realloc(f->names, cap * sizeof(char*)); }
        f->names[f->n++] = strdup(e->d_name);
    }
    closedir(d);
    qsort(f->names, f->n, sizeof(char*), cmpstr);
    return true;
}
bool storage_dir_read(File* f, FileInfo* info, char* name, uint16_t name_len) {
    if(f->at >= f->n) return false;
    const char* nm = f->names[f->at++];
    snprintf(name, name_len, "%s", nm);
    char p[1024];
    snprintf(p, sizeof(p), "%s/%s", f->path, nm);
    struct stat sb;
    if(info && !stat(p, &sb)) { info->size = (uint64_t)sb.st_size; info->flags = S_ISDIR(sb.st_mode) ? FSF_DIRECTORY : 0; }
    return true;
}
bool storage_dir_close(File* f) { dir_drop(f); return true; }

/* ── main ─────────────────────────────────────────────────────────── */
int main(int argc, char** argv) {
    if(argc != 4) { fprintf(stderr, "usage: sanctum_host SCRIPT ROOT TRACE\n"); return 2; }
    host_root = argv[2];
    read_script(argv[1]);
    trace = fopen(argv[3], "w");
    if(!trace) { fprintf(stderr, "host: can't write %s\n", argv[3]); return 2; }
    char ext[512];
    snprintf(ext, sizeof(ext), "%s/apps_data", host_root);
    mkdir(host_root, 0755);
    mkdir(ext, 0755);
    /* Back on the title quits the app; while the script has events left the
     * player opens it again (the resume path: Continue, the saves). */
    while(at_ev < nevs) {
        sanctum_rpg_app(NULL);
        if(at_ev < nevs) fprintf(trace, "relaunch\n");
        app = NULL;
    }
    finish(0);
}
