/* shot — render game views on the host and write them as PBM images.
 *
 * The Flipper screen can't be screenshotted from code, so visual work was
 * done blind. This builds the real renderers (render_fpv.c, ...) against
 * test/shim/gui/canvas.h and dumps the 128x64 framebuffer. `make shots`
 * runs a fixed scene list and test/pbm2png.py turns it into a contact sheet.
 *
 *   test/shot fpv <seed-hex> <chunk_x> <chunk_y> <facing 0-3|a> <out.pbm>
 *
 *   test/shot lineup <family_id> <out.pbm>
 *     every trait of one family: 5 poses at 32px, then idle at the FPV
 *     distance sizes, each on a dithered wall so the mask shows.
 *
 *   test/shot terrain <biome 0|1> <glyph> <dist> <out.pbm>
 *     a synthetic chunk: player at the west end facing east down the long
 *     axis, `glyph` straight ahead at `dist` tiles and once more off to the
 *     side, a wall/edge at the far end — every terrain form seen in place.
 *
 *   test/shot field <biome 0|1> <out.pbm>
 *   test/shot span <glyph> <x> <y> <facing> <out.pbm>
 *     a 2x2 block of a spanning prop at x 8..9, y 2..3, from (x, y)
 *     a synthetic chunk with every feature of that biome scattered in view.
 *
 *   test/shot stylefield <style> <out.pbm>
 *     a synthetic chunk in that style (style.h) with its features in view.
 *
 *   test/shot wall <style> <dist> <out.pbm>
 *     that style's walls up close, with a corner.
 *
 *   test/shot map <seed-hex> <chunk_x> <chunk_y> <out.pbm>
 *     the top-down world screen for that chunk, every tile lit: glyphs in
 *     the device's FontSecondary (test/font_secondary.h), terrain_map_icon
 *     forms where a row has one, and the separator above the status strip.
 *
 *   test/shot terrainset <outdir>
 *     every TERRAIN row at 1, 2 and 4 tiles: <outdir>/terrain_<hex>_<d>.pbm.
 *
 * facing `a` = auto: the facing with the longest open run from spawn, so a
 * scene shows a corridor rather than the wall the player happens to face.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include <gui/canvas.h>

#include "../biome.h"
#include "../creatures.h"
#include "../figure.h"
#include "../loot.h"
#include "../pool.h"
#include "../rng.h"
#include "../stamps.h"
#include "../style.h"
#include "../terrain.h"
#include "../render_fpv.h"
#include "../world.h"
#include "font_secondary.h"

static int write_pbm(const Canvas* c, const char* path) {
    FILE* f = fopen(path, "w");
    if(!f) return 1;
    fprintf(f, "P1\n%d %d\n", SHIM_W, SHIM_H);
    for(int y = 0; y < SHIM_H; y++) {
        for(int x = 0; x < SHIM_W; x++) fputc(c->px[y][x] ? '1' : '0', f);
        fputc('\n', f);
    }
    fclose(f);
    return 0;
}

static const int FDX[4] = {0, 1, 0, -1}, FDY[4] = {-1, 0, 1, 0};  /* N E S W */

static uint8_t open_facing(const World* w) {
    int best = 0, best_run = -1;
    for(int f = 0; f < 4; f++) {
        int run = 0, x = w->spawn_x, y = w->spawn_y;
        for(;;) {
            x += FDX[f]; y += FDY[f];
            if(x < 0 || y < 0 || x >= WORLD_COLS || y >= WORLD_ROWS) break;
            if(world_is_blocking(w->tiles[y][x])) break;
            run++;
        }
        if(run > best_run) { best_run = run; best = f; }
    }
    return (uint8_t)best;
}

/* ── lineup: one family, every trait, every pose + distance sizes ── */
#define LU_CELL 34
static const int LU_SIZES[] = {18, 12, 9, 7};
#define LU_W (5 * LU_CELL + 18 + 12 + 9 + 7 + 5 * 2)
#define LU_H_MAX (16 * LU_CELL)
static uint8_t lu[LU_H_MAX][LU_W];

static int bm(const uint8_t* b, int stride, int x, int y) { return (b[y * stride + (x >> 3)] >> (x & 7)) & 1; }

/* Draw a figure at (ox, oy) scaled to `size`, the way draw_billboard
 * samples it (nearest), over a dithered "wall" so opacity is visible. */
static void put_figure(int ox, int oy, int size, const uint8_t* ink, const uint8_t* mask) {
    int stride = (size + 7) / 8;
    for(int y = 0; y < size; y++)
        for(int x = 0; x < size; x++) {
            int sx = x, sy = y;    /* composed natively at `size` */
            int bg = ((x + ox) & 3) == 0 && ((y + oy) & 1) == 0;   /* a mid-distance wall's density */
            lu[oy + y][ox + x] = bm(mask, stride, sx, sy) ? bm(ink, stride, sx, sy) : bg;
        }
}

static int lineup(int family_id, const char* path) {
    static uint8_t ink[FIGURE_PLANE_BYTES], mask[FIGURE_PLANE_BYTES];
    memset(lu, 0, sizeof(lu));
    int rows = CREATURE_TRAIT_COUNT;
    for(int t = 0; t < rows; t++) {
        int oy = t * LU_CELL + 1, ox = 1;
        for(int p = 0; p < POSE_COUNT; p++, ox += LU_CELL) {
            if(!figure_compose(&RENDER_BUDGET_FLIPPER_1BIT, (uint8_t)family_id, (uint8_t)t,
                               (FigurePose)p, 0, ink, mask)) return 3;
            put_figure(ox, oy, 32, ink, mask);
        }
        for(unsigned k = 0; k < sizeof(LU_SIZES) / sizeof(LU_SIZES[0]); k++) {
            RenderBudget b = RENDER_BUDGET_FLIPPER_1BIT;
            b.width = b.height = (uint8_t)LU_SIZES[k];
            figure_compose(&b, (uint8_t)family_id, (uint8_t)t, POSE_IDLE, 0, ink, mask);
            put_figure(ox, oy + 32 - LU_SIZES[k], LU_SIZES[k], ink, mask);
            ox += LU_SIZES[k] + 2;
        }
    }
    FILE* f = fopen(path, "w");
    if(!f) return 1;
    fprintf(f, "P1\n%d %d\n", LU_W, rows * LU_CELL);
    for(int y = 0; y < rows * LU_CELL; y++) {
        for(int x = 0; x < LU_W; x++) fputc(lu[y][x] ? '1' : '0', f);
        fputc('\n', f);
    }
    fclose(f);
    return 0;
}

/* scene: one composed creature `dist` tiles ahead down the most open
 * facing — to see figures in the world, against real walls. */
static int creature_scene(uint32_t seed, int fam, int trait, int dist, int state, const char* path) {
    World w;
    world_generate_chunk(seed, 1, 0, &w);       /* not the home chunk: no vault at spawn */
    uint8_t f = open_facing(&w);
    Creature c;
    memset(&c, 0, sizeof(c));
    c.family_id = (uint8_t)fam; c.trait_id = (uint8_t)trait; c.state = (uint8_t)state; c.alive = 1;
    c.x = (uint8_t)(w.spawn_x + FDX[f] * dist); c.y = (uint8_t)(w.spawn_y + FDY[f] * dist);
    Canvas cv;
    canvas_clear(&cv);
    render_fpv_world(&cv, &w, w.spawn_x, w.spawn_y, f, &c, 1);
    return write_pbm(&cv, path);
}

/* A bare synthetic chunk: floor, walled perimeter for the cavern. */
static void bare_chunk(World* w, int biome) {
    memset(w, 0, sizeof(*w));
    w->biome = (Biome)biome;
    w->style = style_for_biome(w->biome);
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) {
            bool rim = x == 0 || y == 0 || x == WORLD_COLS - 1 || y == WORLD_ROWS - 1;
            w->tiles[y][x] = (biome == BIOME_CAVERN && rim) ? TILE_WALL : TILE_FLOOR;
        }
    w->spawn_x = 1; w->spawn_y = 3;
}

static int terrain_shot(int biome, char glyph, int dist, const char* path) {
    World w;
    bare_chunk(&w, biome);
    w.tiles[3][1 + dist] = glyph;
    if(1 + dist + 2 < WORLD_COLS - 1) w.tiles[1][1 + dist + 2] = glyph;   /* off to the side */
    Canvas cv;
    canvas_clear(&cv);
    render_fpv_world(&cv, &w, w.spawn_x, w.spawn_y, 1 /* east */, NULL, 0);
    return write_pbm(&cv, path);
}

/* A 2x2 block of a spanning prop (menhir) at x 8..9, y 2..3, seen from
 * (px, py) facing f — so a test can look at it head-on, side-on, oblique. */
static int span_shot(char glyph, int px, int py, int f, const char* path) {
    World w;
    bare_chunk(&w, BIOME_OUTDOOR);
    w.tiles[2][8] = w.tiles[2][9] = w.tiles[3][8] = w.tiles[3][9] = glyph;
    Canvas cv;
    canvas_clear(&cv);
    render_fpv_world(&cv, &w, px, py, (uint8_t)f, NULL, 0);
    return write_pbm(&cv, path);
}

static int field_shot(int biome, const char* path) {
    /* Full 16x6 layouts; the player stands at (1, 3) facing east. Features
     * sit inside the 60-degree view: side +-1 from 2 tiles out, +-2 from 4. */
    static const char* FIELD[2][WORLD_ROWS] = {
        {"................",                 /* cavern (rim becomes wall) */
         "......OO....q.A.",
         "...,,.OO..q.....",
         ".....q.....A....",
         "..,,,..|.,,,MM..",
         "................"},
        {"........HH......",                 /* outdoor */
         "....I...HH..Q...",
         "...;;..Q...o....",
         "................",
         "..::..o..~~..;..",
         ".......I....::.."}};
    World w;
    bare_chunk(&w, biome);
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) {
            char g = FIELD[biome ? 1 : 0][y][x];
            if(g != '.' && w.tiles[y][x] == TILE_FLOOR) w.tiles[y][x] = g;
        }
    Canvas cv;
    canvas_clear(&cv);
    render_fpv_world(&cv, &w, w.spawn_x, w.spawn_y, 1 /* east */, NULL, 0);
    return write_pbm(&cv, path);
}

/* One synthetic layout per new style (cavern/moor use field_shot). */
static const char* STYLE_FIELD[STYLE_COUNT][WORLD_ROWS] = {
    [STYLE_CRYPT] = {"................",
                     "....U.n.U...x...",
                     "...//...O.O.....",
                     ".....x..........",
                     "..n...//...UU...",
                     "................"},
    [STYLE_MINE]  = {"................",
                     "....l...l...^^..",
                     "...---c---..^...",
                     ".....^..........",
                     "..l...--c-..l...",
                     "................"},
    [STYLE_FOREST]= {"........Y.......",
                     "....Y..``..y.t..",
                     "...``..Y...Y....",
                     "................",
                     "..t.~~.Y..;`..Y.",
                     ".......Y....y..."},
    [STYLE_MANOR] = {"................",
                     "....m.m.m...w...",
                     "...[[[...d.d....",
                     ".....m..........",
                     "..d...[[..w.d...",
                     "................"},
    [STYLE_KEEP]  = {"................",
                     "....k...k...v...",
                     "...//..v...d....",
                     ".....k..........",
                     "..v...//..k.d...",
                     "................"},
    [STYLE_ABBEY] = {"................",
                     "....p...p...Z...",
                     "...//..a...v....",
                     ".....Z..........",
                     "..p...//..U.a...",
                     "................"},
};

static int stylefield_shot(int style, const char* path) {
    if(style < 0 || style >= STYLE_COUNT) return 2;
    if(!STYLE_FIELD[style][0]) return field_shot(STYLE_TABLE[style].biome, path);
    World w;
    bare_chunk(&w, style_terrain((Style)style) == TERRAIN_WALLED ? BIOME_CAVERN : BIOME_OUTDOOR);   /* walled rim */
    w.biome = STYLE_TABLE[style].biome;
    w.style = (Style)style;
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) {
            char g = STYLE_FIELD[style][y][x];
            if(g != '.' && w.tiles[y][x] == TILE_FLOOR) w.tiles[y][x] = g;
        }
    Canvas cv;
    canvas_clear(&cv);
    render_fpv_world(&cv, &w, w.spawn_x, w.spawn_y, 1 /* east */, NULL, 0);
    return write_pbm(&cv, path);
}

/* A style's walls up close: the east wall `dist` tiles ahead, looking a
 * little off-axis so two faces and a corner show. */
static int wall_shot(int style, int dist, const char* path) {
    if(style < 0 || style >= STYLE_COUNT) return 2;
    World w;
    bare_chunk(&w, BIOME_CAVERN);
    w.style = (Style)style;
    w.tiles[1][WORLD_COLS - 3] = TILE_WALL;    /* a pier for a corner */
    Canvas cv;
    canvas_clear(&cv);
    render_fpv_world(&cv, &w, WORLD_COLS - 1 - dist, 2, 1 /* east */, NULL, 0);
    return write_pbm(&cv, path);
}

/* The biome a glyph is seen in: the biome of the first style whose stamps
 * place it (anything unstamped, e.g. the legacy boulder: outdoor). */
static int glyph_biome(char g) {
    for(int i = 0; i < STAMP_COUNT; i++)
        for(int k = 0; k < STAMPS[i].prim_count; k++) {
            const PrimitiveDef* p = primitive_def(STAMPS[i].prims[k].prim_id);
            if(p && p->glyph == g) return STYLE_TABLE[STAMPS[i].style].biome;
        }
    for(int id = 0; id < PRIM_COUNT_CAVERN; id++)     /* cavern vocabulary, unstamped */
        if(primitive_def((uint8_t)id)->glyph == g) return BIOME_CAVERN;
    return BIOME_OUTDOOR;
}

static int terrainset(const char* dir) {
    static const int DISTS[] = {1, 2, 4};
    char path[512];
    for(int i = 0; i < terrain_count(); i++) {
        const TerrainDef* d = terrain_at(i);
        int biome = d->form == TF_SLAB ? BIOME_CAVERN : glyph_biome(d->glyph);
        for(int k = 0; k < 3; k++) {
            snprintf(path, sizeof(path), "%s/terrain_%02x_%d.pbm", dir, (unsigned char)d->glyph, DISTS[k]);
            if(terrain_shot(biome, d->glyph, DISTS[k], path)) return 1;
        }
    }
    return 0;
}

/* Mirrors draw_world_screen's tile loop (sanctum_rpg.c): one 8px cell per
 * tile, the glyph at baseline row 7, or the tile's top-down form. */
#define MAP_TILE_PX 8
#define MAP_VIEW_H  (WORLD_ROWS * MAP_TILE_PX)
static void map_draw_tile(Canvas* c, int x, int y, char g) {
    const uint8_t* icon = terrain_map_icon(g);
    if(!icon) icon = loot_map_icon(g);
    if(icon) {
        canvas_draw_xbm(c, x * MAP_TILE_PX, y * MAP_TILE_PX, MAP_TILE_PX, MAP_TILE_PX, icon);
        return;
    }
    if(g < 32 || g > 126) return;
    canvas_draw_xbm(c, x * MAP_TILE_PX, y * MAP_TILE_PX, MAP_TILE_PX, FONT2_ROWS, FONT2_CELL[g - 32]);
}

static int map_shot(uint32_t seed, int cx, int cy, const char* path) {
    static World w;
    world_generate_chunk(seed, cx, cy, &w);
    Canvas c;
    canvas_clear(&c);
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++) map_draw_tile(&c, x, y, w.tiles[y][x]);
    canvas_draw_line(&c, 0, MAP_VIEW_H, SHIM_W - 1, MAP_VIEW_H);
    return write_pbm(&c, path);
}

int main(int argc, char** argv) {
    if(argc == 4 && strcmp(argv[1], "stylefield") == 0) return stylefield_shot(atoi(argv[2]), argv[3]);
    if(argc == 6 && strcmp(argv[1], "map") == 0)
        return map_shot((uint32_t)strtoul(argv[2], NULL, 16), atoi(argv[3]), atoi(argv[4]), argv[5]);
    if(argc == 3 && strcmp(argv[1], "terrainset") == 0) return terrainset(argv[2]);
    if(argc == 5 && strcmp(argv[1], "wall") == 0) return wall_shot(atoi(argv[2]), atoi(argv[3]), argv[4]);
    if(argc == 6 && strcmp(argv[1], "terrain") == 0)
        return terrain_shot(atoi(argv[2]), argv[3][0], atoi(argv[4]), argv[5]);
    if(argc == 7 && strcmp(argv[1], "span") == 0)
        return span_shot(argv[2][0], atoi(argv[3]), atoi(argv[4]), atoi(argv[5]), argv[6]);
    if(argc == 4 && strcmp(argv[1], "field") == 0) return field_shot(atoi(argv[2]), argv[3]);
    if(argc == 8 && strcmp(argv[1], "scene") == 0)
        return creature_scene((uint32_t)strtoul(argv[2], NULL, 16), atoi(argv[3]), atoi(argv[4]),
                              atoi(argv[5]), atoi(argv[6]), argv[7]);
    if(argc == 4 && strcmp(argv[1], "lineup") == 0) return lineup(atoi(argv[2]), argv[3]);
    if(argc != 7 || strcmp(argv[1], "fpv") != 0) {
        fprintf(stderr, "usage: shot fpv <seed-hex> <cx> <cy> <facing> <out.pbm>\n");
        return 2;
    }
    uint32_t seed = (uint32_t)strtoul(argv[2], NULL, 16);
    int cx = atoi(argv[3]), cy = atoi(argv[4]);

    World w;
    world_generate_chunk(seed, cx, cy, &w);
    Creature cr[CREATURES_MAX];
    /* Same spawn path as sanctum_rpg.c populate_creatures(), so a scene shows
     * what the device would show at this seed/chunk. */
    Pool pool;
    uint8_t pool_biome = biome_pool(w.biome);
    pool_at(seed, pool_biome, cx, cy, &pool);
    int n = creatures_populate_pooled(rng_chunk_seed(seed, cx, cy), w.biome, &w,
                                      w.spawn_x, w.spawn_y, &pool, cr, CREATURES_MAX);

    uint8_t facing = argv[5][0] == 'a' ? open_facing(&w) : (uint8_t)atoi(argv[5]);

    Canvas c;
    canvas_clear(&c);
    render_fpv_world(&c, &w, w.spawn_x, w.spawn_y, facing, cr, n);
    return write_pbm(&c, argv[6]);
}
