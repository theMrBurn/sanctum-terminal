/* shot — render game views on the host and write them as PBM images.
 *
 * The Flipper screen can't be screenshotted from code, so visual work was
 * done blind. This builds the real renderers (render_fpv.c, ...) against
 * test/shim/gui/canvas.h and dumps the 128x64 framebuffer. `make shots`
 * runs a fixed scene list and test/pbm2png.py turns it into a contact sheet.
 *
 *   test/shot fpv <seed-hex> <chunk_x> <chunk_y> <facing 0-3|a> <out.pbm>
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
#include "../pool.h"
#include "../rng.h"
#include "../stamps.h"
#include "../render_fpv.h"
#include "../world.h"

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

int main(int argc, char** argv) {
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
    uint8_t pool_biome = (biome_terrain(w.biome) == TERRAIN_OPEN) ? STAMP_BIOME_OUTDOOR
                                                                  : STAMP_BIOME_CAVERN;
    pool_at(seed, pool_biome, cx, cy, &pool);
    int n = creatures_populate_pooled(rng_chunk_seed(seed, cx, cy), w.biome, &w,
                                      w.spawn_x, w.spawn_y, &pool, cr, CREATURES_MAX);

    uint8_t facing = argv[5][0] == 'a' ? open_facing(&w) : (uint8_t)atoi(argv[5]);

    Canvas c;
    canvas_clear(&c);
    render_fpv_world(&c, &w, w.spawn_x, w.spawn_y, facing, cr, n);
    return write_pbm(&c, argv[6]);
}
