/* Render-rule tests — the real renderers against test/shim (a RAM canvas).
 *
 * Separate binary from test_main.c because it needs the canvas shim; built
 * and run by `make test`. These check RULES of the art system, not pixels:
 * pixel-exact goldens belong to the composer's tiers.
 */
#include <stdio.h>
#include <string.h>

#include <gui/canvas.h>

#include "../biome.h"
#include "../creatures.h"
#include "../pool.h"
#include "../render_fpv.h"
#include "../rng.h"
#include "../stamps.h"
#include "../world.h"

extern int fpv_test_wall_top[];
extern int fpv_test_wall_bot[];
extern int fpv_test_underpaint;

static int g_pass, g_fail;
#define CHECK(cond, msg)                                                   \
    do {                                                                   \
        if(cond) g_pass++;                                                 \
        else { g_fail++; printf("  FAIL: %s  (%s:%d)\n", (msg), __FILE__, __LINE__); } \
    } while(0)

static int scene(uint32_t seed, int cx, int cy, uint8_t facing, Canvas* out) {
    World w;
    world_generate_chunk(seed, cx, cy, &w);
    Pool pool;
    uint8_t pb = (biome_terrain(w.biome) == TERRAIN_OPEN) ? STAMP_BIOME_OUTDOOR : STAMP_BIOME_CAVERN;
    pool_at(seed, pb, cx, cy, &pool);
    Creature cr[CREATURES_MAX];
    int n = creatures_populate_pooled(rng_chunk_seed(seed, cx, cy), w.biome, &w,
                                      w.spawn_x, w.spawn_y, &pool, cr, CREATURES_MAX);
    canvas_clear(out);
    render_fpv_world(out, &w, w.spawn_x, w.spawn_y, facing, cr, n);
    return n;
}

/* RULE: an opaque surface owns every pixel it covers. Render each scene
 * twice — once normally, once with the whole view inked before any pass
 * ("underpaint"). Inside each wall span the two frames must be identical:
 * if anything drawn under a wall can change its pixels, the wall leaks. */
static void test_walls_are_opaque(void) {
    static const uint32_t seeds[] = {0x12345678, 0xCAFEBABE, 0xDEADBEEF, 0x0BADF00D, 0x00C0FFEE};
    int walls_seen = 0, leaks = 0;
    static int top[128], bot[128];
    for(unsigned s = 0; s < sizeof(seeds) / sizeof(seeds[0]); s++)
        for(int cx = -1; cx <= 1; cx++)
            for(int cy = -1; cy <= 1; cy++)
                for(uint8_t f = 0; f < 4; f++) {
                    Canvas a, b;
                    fpv_test_underpaint = 0;
                    scene(seeds[s], cx, cy, f, &a);
                    memcpy(top, fpv_test_wall_top, sizeof(top));
                    memcpy(bot, fpv_test_wall_bot, sizeof(bot));
                    fpv_test_underpaint = 1;
                    scene(seeds[s], cx, cy, f, &b);
                    fpv_test_underpaint = 0;
                    for(int c = 0; c < 128; c++) {
                        if(top[c] > bot[c]) continue;
                        walls_seen++;
                        for(int y = top[c]; y <= bot[c]; y++)
                            if(a.px[y][c] != b.px[y][c]) { leaks++; break; }
                    }
                }
    CHECK(walls_seen > 1000, "render: opacity sweep actually covered wall columns");
    CHECK(leaks == 0, "render: walls are opaque (nothing drawn under a wall shows through)");
    if(leaks) printf("    %d of %d wall columns leaked\n", leaks, walls_seen);
}

int main(void) {
    printf("Sanctum RPG — render rule tests\n");
    test_walls_are_opaque();
    printf("%d passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}
