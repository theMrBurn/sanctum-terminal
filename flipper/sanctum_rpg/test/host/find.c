/* Fixtures for the host reference (test/host): finds, in a real world, the
 * places a fresh game rarely reaches in random play, and writes a save that
 * starts the player beside them. Uses the game's own pure code (generation,
 * the arc's records), so a fixture is a real place in a real seed.
 *
 *   build/host/find SCENARIO SEED ROOT
 *
 * SCENARIO: hollow (tool in the bag) | hollow_skill (axes at 22) | site
 * (words and an artifact to seal) | rite (every site sealed, the ways'
 * things in the bag) | fight (casts and flasks known, beside a creature's
 * spawn) | vendor | quest (in a chunk a quest surfaces in) | forge
 * (a full bag, rot's leavings among it)
 * Prints where it put the player; scripts take it from there. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "biome.h"
#include "corruption.h"
#include "creatures.h"
#include "hollow.h"
#include "narrative.h"
#include "pool.h"
#include "region.h"
#include "ritual.h"
#include "site.h"
#include "trade.h"
#include "arc.h"
#include "afflict.h"
#include "world.h"
#include "rng.h"

static const char* root;
static uint32_t seed;

typedef struct {
    int cx, cy, px, py, facing;
    int axes;                        /* body..will */
    int axis_over[6];                /* -1 or a value */
    uint8_t inv[32];
    int words, recipes, casts, mp;
} Char;

static void mk(const char* p) { mkdir(p, 0755); }

static void dirs(void) {
    char p[512];
    mk(root);
    snprintf(p, sizeof(p), "%s/apps_data", root); mk(p);
    snprintf(p, sizeof(p), "%s/apps_data/sanctum_rpg", root); mk(p);
    snprintf(p, sizeof(p), "%s/apps_data/sanctum_rpg/campaigns", root); mk(p);
    snprintf(p, sizeof(p), "%s/apps_data/sanctum_rpg/campaigns/001", root); mk(p);
}

static void put(const char* name, const char* text) {
    char p[512];
    snprintf(p, sizeof(p), "%s/apps_data/sanctum_rpg/campaigns/001/%s", root, name);
    FILE* f = fopen(p, "w");
    if(!f) { perror(p); exit(1); }
    fputs(text, f);
    fclose(f);
}

static void write_save(const Char* c) {
    char b[4096], inv[256] = "";
    int n = 0;
    for(int i = 0; i < 32; i++) n += snprintf(inv + n, sizeof(inv) - n, "%s%u", i ? "," : "", c->inv[i]);
    snprintf(b, sizeof(b),
             "{\n  \"schema_version\": 10,\n  \"campaign_id\": \"001\",\n  \"character_name\": \"themrburn\",\n"
             "  \"seed\": %u,\n  \"started_at_unix\": 1762430400,\n  \"last_played_at_unix\": 1762430400,\n"
             "  \"permadeath\": false\n}\n", seed);
    put("meta.json", b);
    static const char* AX[6] = {"body", "craft", "sight", "mind", "heart", "will"};
    char axes[256] = "";
    n = 0;
    for(int i = 0; i < 6; i++)
        n += snprintf(axes + n, sizeof(axes) - n, "  \"%s\": %d,\n", AX[i], c->axis_over[i] >= 0 ? c->axis_over[i] : c->axes);
    snprintf(b, sizeof(b),
             "{\n  \"schema_version\": 10,\n  \"campaign_id\": \"001\",\n  \"chunk_x\": %d,\n  \"chunk_y\": %d,\n"
             "  \"player_x\": %d,\n  \"player_y\": %d,\n  \"hp\": 10,\n  \"max_hp\": 10,\n  \"mp\": %d,\n  \"max_mp\": 5,\n"
             "  \"level\": 1,\n  \"identified\": 0,\n  \"turn\": 100,\n  \"torch_fuel\": 100,\n  \"observe\": 60,\n"
             "  \"bestiary\": 0,\n  \"class_id\": 0,\n%s  \"verbs_mask\": 45,\n  \"inv\": \"%s\",\n"
             "  \"equipped_weapon\": 255,\n  \"equipped_light\": 255,\n  \"equipped_armor\": 255,\n"
             "  \"expertise\": \"25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25,25\",\n"
             "  \"vault\": \"0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0\",\n  \"facing\": %d,\n"
             "  \"words\": %d,\n  \"recipes\": %d,\n  \"bleed\": 0,\n  \"chill\": 0,\n  \"casts\": %d\n}\n",
             c->cx, c->cy, c->px, c->py, c->mp, axes, inv, c->facing, c->words, c->recipes, c->casts);
    put("character.json", b);
}

static Char base(void) {
    Char c;
    memset(&c, 0, sizeof(c));
    c.axes = 12;
    for(int i = 0; i < 6; i++) c.axis_over[i] = -1;
    c.mp = 5;
    c.facing = 1;
    return c;
}

static const int DX[4] = {0, 1, 0, -1}, DY[4] = {-1, 0, 1, 0};   /* N E S W = the FPV facings */

/* a walkable tile beside (x, y), reachable from spawn; facing toward (x, y) */
static int beside(const World* w, int x, int y, int* sx, int* sy, int* facing) {
    uint8_t reach[WORLD_ROWS][WORLD_COLS];
    memset(reach, 0, sizeof(reach));
    world_reach(w, w->spawn_x, w->spawn_y, reach);
    for(int d = 0; d < 4; d++) {
        int ax = x - DX[d], ay = y - DY[d];
        if(ax < 1 || ay < 1 || ax > WORLD_COLS - 2 || ay > WORLD_ROWS - 2) continue;
        if(reach[ay][ax]) { *sx = ax; *sy = ay; *facing = d; return 1; }
    }
    return 0;
}

static void rituals_done(int rx, int ry) {
    RegionRituals r;
    region_rituals_clear(&r);
    region_mark_ritual(&r, rx, ry);
    char b[2048];
    region_rituals_format(&r, b, sizeof(b));
    put("rituals.txt", b);
}

static void book(int rx, int ry, uint8_t sealed, uint8_t pieces, uint8_t flags) {
    RegionBook bk;
    region_book_clear(&bk);
    RegionRecord* r = region_book_touch(&bk, rx, ry);
    r->sealed = sealed; r->pieces = pieces; r->flags = flags;
    static char b[REGION_BOOK_TEXT_MAX];
    region_book_format(&bk, b, sizeof(b));
    put("regions.txt", b);
}

static int hollow(int skill) {
    int ox, oy;
    region_origin(seed, &ox, &oy);
    for(int d = 1; d <= 4; d++)
        for(int ry = oy - d; ry <= oy + d; ry++)
            for(int rx = ox - d; rx <= ox + d; rx++) {
                if(region_depth(seed, rx, ry) != d) continue;
                for(int s = 0; s < BIOME_REGION * BIOME_REGION; s++) {
                    int cx = rx * BIOME_REGION + s % 3, cy = ry * BIOME_REGION + s / 3;
                    World w;
                    world_generate_chunk(seed, cx, cy, &w);
                    if(!hollow_mark(seed, cx, cy, &w)) continue;
                    Char c = base();
                    c.cx = cx; c.cy = cy;
                    if(!beside(&w, w.hollow_x, w.hollow_y, &c.px, &c.py, &c.facing)) continue;
                    if(skill) c.axis_over[hollow_axis(w.hollow_kind) == 0 ? 0 : hollow_axis(w.hollow_kind) == 1 ? 1 : 2] = 22;
                    else c.inv[hollow_tool(w.hollow_kind)] = 1;
                    write_save(&c);
                    rituals_done(rx, ry);
                    book(rx, ry, 0, 0, RR_FOUND);
                    printf("hollow %s: region %d %d chunk %d %d mouth %d %d kind %d; stand %d %d, the mouth to the %c\n",
                           skill ? "(skill)" : "(tool)", rx, ry, cx, cy, w.hollow_x, w.hollow_y, w.hollow_kind,
                           c.px, c.py, "NESW"[c.facing]);
                    return 0;
                }
            }
    return 1;
}

static int site(int rite) {
    int ox, oy;
    region_origin(seed, &ox, &oy);
    for(int d = 1; d <= 4; d++)
        for(int ry = oy - d; ry <= oy + d; ry++)
            for(int rx = ox - d; rx <= ox + d; rx++) {
                if(region_depth(seed, rx, ry) != d) continue;
                RegionSite sites[SITES_PER_REGION_MAX];
                int n = region_sites(seed, rx, ry, sites);
                for(int k = 0; k < n; k++) {
                    World w;
                    world_generate_chunk(seed, sites[k].cx, sites[k].cy, &w);
                    if(w.site_kind == SITE_NONE) continue;
                    Char c = base();
                    c.cx = sites[k].cx; c.cy = sites[k].cy;
                    if(!beside(&w, w.site_x, w.site_y, &c.px, &c.py, &c.facing)) continue;
                    c.words = 0x0F;
                    if(rite) {
                        c.axes = 16;
                        c.inv[ARC_KIND_WARD] = 1; c.inv[ARC_KIND_CANDLE] = 1;
                        c.inv[ARC_KIND_SALT] = 1; c.inv[ARC_KIND_RELIC] = 1;
                        book(rx, ry, (uint8_t)((1u << n) - 1u), 0xFF, RR_FOUND);
                    } else {
                        c.inv[arc_artifact_kind(w.site_kind)] = 2;
                        book(rx, ry, 0, 0, RR_FOUND);
                    }
                    write_save(&c);
                    printf("%s: region %d %d chunk %d %d site %d %d kind %d; stand %d %d, the site to the %c\n",
                           rite ? "rite" : "site", rx, ry, c.cx, c.cy, w.site_x, w.site_y, w.site_kind, c.px, c.py,
                           "NESW"[c.facing]);
                    return 0;
                }
            }
    return 1;
}

static int fight(void) {
    for(int cy = -9; cy <= 9; cy++)
        for(int cx = -9; cx <= 9; cx++) {
            World w;
            world_generate_chunk(seed, cx, cy, &w);
            Pool pool;
            pool_at(seed, biome_pool(w.biome), cx, cy, &pool);
            Creature cr[CREATURES_MAX];
            int n = creatures_populate_pooled(rng_chunk_seed(seed, cx, cy), w.biome, &w, w.spawn_x, w.spawn_y, &pool,
                                              cr, CREATURES_MAX);
            for(int i = 0; i < n; i++) {
                CreatureDef d;
                creature_compose(cr[i].family_id, cr[i].trait_id, &d);
                /* one that crowding provokes and that holds its ground: a few turns beside
                 * it and the bump engages */
                if(d.provoke == 0 || d.flee > 0 || (d.flags & CF_PHOTOPHILIC)) continue;
                Char c = base();
                c.cx = cx; c.cy = cy;
                if(!beside(&w, cr[i].x, cr[i].y, &c.px, &c.py, &c.facing)) continue;
                c.casts = 0x07; c.mp = 5;
                c.inv[AF_KIND_TINCTURE] = 2; c.inv[AF_KIND_BLIGHT] = 2;
                c.recipes = 0x7F;
                write_save(&c);
                printf("fight: chunk %d %d creature %u.%u at %d %d; stand %d %d, it to the %c\n", cx, cy,
                       cr[i].family_id, cr[i].trait_id, cr[i].x, cr[i].y, c.px, c.py, "NESW"[c.facing]);
                return 0;
            }
        }
    return 1;
}

static int vendor(void) {
    for(int cy = -4; cy <= 4; cy++)
        for(int cx = -4; cx <= 4; cx++) {
            if(!chunk_has_vendor(seed, cx, cy)) continue;
            World w;
            world_generate_chunk(seed, cx, cy, &w);
            for(int y = 1; y < WORLD_ROWS - 1; y++)
                for(int x = 1; x < WORLD_COLS - 1; x++) {
                    if(w.tiles[y][x] != TILE_VENDOR) continue;
                    Char c = base();
                    c.cx = cx; c.cy = cy;
                    if(!beside(&w, x, y, &c.px, &c.py, &c.facing)) continue;
                    c.inv[0] = 40; c.inv[1] = 3; c.inv[3] = 2;     /* shards, caps, vials */
                    write_save(&c);
                    printf("vendor: chunk %d %d at %d %d; stand %d %d, it to the %c\n", cx, cy, x, y, c.px, c.py,
                           "NESW"[c.facing]);
                    return 0;
                }
        }
    return 1;
}

static int forge(void) {
    Char c = base();
    World w;
    world_generate_chunk(seed, 0, 0, &w);
    c.cx = 0; c.cy = 0; c.px = w.spawn_x; c.py = w.spawn_y;
    for(int k = 0; k < 8; k++) c.inv[k] = 9;           /* the trade goods: enough for every pull */
    c.inv[AF_KIND_ROTCAP] = 4; c.inv[AF_KIND_SOURVIAL] = 2;   /* what rot leaves: the experiment */
    write_save(&c);
    printf("forge: chunk 0 0 at spawn %d %d, a full bag\n", c.px, c.py);
    return 0;
}

static int quest(void) {
    for(int cy = -6; cy <= 6; cy++)
        for(int cx = -6; cx <= 6; cx++) {
            World w;
            world_generate_chunk(seed, cx, cy, &w);
            Pool pool;
            pool_at(seed, biome_pool(w.biome), cx, cy, &pool);
            uint8_t e, t;
            if(!narrative_pick_for_chunk_pooled(seed, cx, cy, 0u, &pool, &e, &t)) continue;
            /* stand in it: a quest surfaces on load as well as on arrival */
            Char c = base();
            c.cx = cx; c.cy = cy; c.px = w.spawn_x; c.py = w.spawn_y;
            write_save(&c);
            printf("quest: chunk %d %d (entry %u) at spawn %d %d\n", cx, cy, e, c.px, c.py);
            return 0;
        }
    return 1;
}

int main(int argc, char** argv) {
    if(argc != 4) { fprintf(stderr, "usage: find SCENARIO SEED ROOT\n"); return 2; }
    seed = (uint32_t)strtoul(argv[2], NULL, 10);
    root = argv[3];
    dirs();
    const char* s = argv[1];
    int r = !strcmp(s, "hollow") ? hollow(0) : !strcmp(s, "hollow_skill") ? hollow(1) : !strcmp(s, "site") ? site(0)
          : !strcmp(s, "rite") ? site(1) : !strcmp(s, "fight") ? fight() : !strcmp(s, "vendor") ? vendor()
          : !strcmp(s, "quest") ? quest() : !strcmp(s, "forge") ? forge() : 2;
    if(r) fprintf(stderr, "find: no %s found in seed %u\n", s, seed);
    return r;
}
