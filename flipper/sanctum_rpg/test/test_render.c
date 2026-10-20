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
#include "../loot.h"
#include "../figure.h"
#include "../pool.h"
#include "../render_fpv.h"
#include "../rng.h"
#include "../stamps.h"
#include "../terrain.h"
#include "../world.h"
#include "../region.h"
#include "font_secondary.h"

extern int fpv_test_wall_top[];
extern int fpv_test_wall_bot[];
extern int fpv_test_underpaint;
extern int fpv_test_last_figure_x0, fpv_test_last_figure_y0, fpv_test_last_figure_size;
extern int fpv_test_masked_billboards;
extern int fpv_test_wall_mat[];

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
    uint8_t pb = biome_pool(w.biome);
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

/* ── composer rules (figure.c) ─────────────────────────────────────── */
static const int SIZES[] = {8, 12, 18, 32};
#define NSIZES ((int)(sizeof(SIZES) / sizeof(SIZES[0])))

static RenderBudget budget_at(int px) {
    RenderBudget b = RENDER_BUDGET_FLIPPER_1BIT;
    b.width = b.height = (uint8_t)px;
    return b;
}

/* Every combination composes, deterministically, with mask ⊇ ink. */
static void test_figure_rules(void) {
    static uint8_t i1[FIGURE_PLANE_BYTES], m1[FIGURE_PLANE_BYTES];
    static uint8_t i2[FIGURE_PLANE_BYTES], m2[FIGURE_PLANE_BYTES];
    int combos = 0, bad_det = 0, bad_cover = 0, empty = 0, failed = 0;
    for(int f = 0; f < CREATURE_FAMILY_COUNT; f++)
        for(int t = 0; t < CREATURE_TRAIT_COUNT; t++)
            for(int p = 0; p < POSE_COUNT; p++)
                for(int fr = 0; fr < 2; fr++)
                    for(int z = 0; z < NSIZES; z++) {
                        RenderBudget b = budget_at(SIZES[z]);
                        combos++;
                        if(!figure_compose(&b, (uint8_t)f, (uint8_t)t, (FigurePose)p,
                                           (uint8_t)fr, i1, m1)) { failed++; continue; }
                        figure_compose(&b, (uint8_t)f, (uint8_t)t, (FigurePose)p, (uint8_t)fr, i2, m2);
                        if(memcmp(i1, i2, sizeof(i1)) || memcmp(m1, m2, sizeof(m1))) bad_det++;
                        int on = 0;
                        for(int k = 0; k < FIGURE_PLANE_BYTES; k++) {
                            if(i1[k] & ~m1[k]) bad_cover++;
                            on |= m1[k];
                        }
                        if(!on) empty++;
                    }
    CHECK(failed == 0, "figure: every family x trait x pose x frame x size composes");
    CHECK(bad_det == 0, "figure: deterministic (same inputs -> same planes)");
    CHECK(bad_cover == 0, "figure: mask covers ink everywhere (ink implies opaque)");
    CHECK(empty == 0, "figure: no combination draws nothing");
    CHECK(combos == CREATURE_FAMILY_COUNT * CREATURE_TRAIT_COUNT * POSE_COUNT * 2 * NSIZES,
          "figure: sweep covered every combination");
    RenderBudget rich = RENDER_BUDGET_FLIPPER_1BIT;
    rich.bit_depth = 8;
    CHECK(!figure_compose(&rich, 0, 0, POSE_IDLE, 0, i1, m1),
          "figure: unsupported tier refuses rather than guessing");
}

/* IDENTITY FIRST: every family x trait is distinct by SILHOUETTE alone
 * (the mask) at the near size, and still distinct (ink+mask) at 12 px —
 * three tiles out, where the hide has gone solid. */
static int identity_at(int px, bool silhouette_only) {
    static uint8_t ink[40][FIGURE_PLANE_BYTES], mask[40][FIGURE_PLANE_BYTES];
    RenderBudget b = budget_at(px);
    int n = 0, same = 0;
    for(int f = 0; f < CREATURE_FAMILY_COUNT; f++)
        for(int t = 0; t < CREATURE_TRAIT_COUNT; t++, n++)
            figure_compose(&b, (uint8_t)f, (uint8_t)t, POSE_IDLE, 0, ink[n], mask[n]);
    for(int a = 0; a < n; a++)
        for(int c = a + 1; c < n; c++)
            if(!memcmp(mask[a], mask[c], FIGURE_PLANE_BYTES) &&
               (silhouette_only || !memcmp(ink[a], ink[c], FIGURE_PLANE_BYTES))) {
                same++;
                printf("    %dpx: #%d (fam %d trait %d) == #%d (fam %d trait %d)\n", px, a,
                       a / CREATURE_TRAIT_COUNT, a % CREATURE_TRAIT_COUNT, c,
                       c / CREATURE_TRAIT_COUNT, c % CREATURE_TRAIT_COUNT);
            }
    return same;
}

static void test_figure_identity(void) {
    CHECK(CREATURE_FAMILY_COUNT * CREATURE_TRAIT_COUNT == 40, "figure: 5 families x 8 traits");
    CHECK(identity_at(32, true) == 0, "figure: every family x trait has its own silhouette (32px)");
    CHECK(identity_at(12, false) == 0, "figure: every family x trait still distinct at 12px");
}

/* GOLDEN: one FNV-1a 64 over every combination at the device size —
 * ink then mask bytes, order family > trait > pose > frame. A port
 * (Python, ...) reproduces this number or it isn't drawing the same game. */
#define FIGURE_GOLDEN 0x412D3813F79780F0ULL
static void test_figure_golden(void) {
    static uint8_t ink[FIGURE_PLANE_BYTES], mask[FIGURE_PLANE_BYTES];
    uint64_t h = 0xCBF29CE484222325ULL;
    for(int f = 0; f < CREATURE_FAMILY_COUNT; f++)
        for(int t = 0; t < CREATURE_TRAIT_COUNT; t++)
            for(int p = 0; p < POSE_COUNT; p++)
                for(int fr = 0; fr < 2; fr++) {
                    figure_compose(&RENDER_BUDGET_FLIPPER_1BIT, (uint8_t)f, (uint8_t)t,
                                   (FigurePose)p, (uint8_t)fr, ink, mask);
                    for(int k = 0; k < FIGURE_PLANE_BYTES; k++) h = (h ^ ink[k]) * 0x100000001B3ULL;
                    for(int k = 0; k < FIGURE_PLANE_BYTES; k++) h = (h ^ mask[k]) * 0x100000001B3ULL;
                }
    printf("  figure golden (flipper_1bit): 0x%016llX\n", (unsigned long long)h);
    CHECK(h == FIGURE_GOLDEN, "figure: flipper_1bit golden fingerprint unchanged");
}

/* OPAQUE BILLBOARDS: a creature standing in front of a wall must hide it.
 * Same underpaint trick as the walls, over the figure's own mask. */
static void test_figures_are_opaque(void) {
    static const uint32_t seeds[] = {0x12345678, 0xCAFEBABE, 0xDEADBEEF, 0x0BADF00D};
    static const int dx4[4] = {0, 1, 0, -1}, dy4[4] = {-1, 0, 1, 0};
    static uint8_t ink[FIGURE_PLANE_BYTES], mask[FIGURE_PLANE_BYTES];
    int scenes = 0, leaks = 0;
    for(unsigned s = 0; s < sizeof(seeds) / sizeof(seeds[0]); s++)
        for(int f = 0; f < 4; f++)
            for(int fam = 0; fam < CREATURE_FAMILY_COUNT; fam++) {
                World w;
                world_generate_chunk(seeds[s], 0, 0, &w);
                int x = w.spawn_x + 2 * dx4[f], y = w.spawn_y + 2 * dy4[f];
                int mx = w.spawn_x + dx4[f], my = w.spawn_y + dy4[f];
                if(x < 0 || y < 0 || x >= WORLD_COLS || y >= WORLD_ROWS) continue;
                if(world_is_blocking(w.tiles[y][x]) || world_is_blocking(w.tiles[my][mx])) continue;
                Creature c;
                memset(&c, 0, sizeof(c));
                c.family_id = (uint8_t)fam; c.x = (uint8_t)x; c.y = (uint8_t)y; c.alive = 1;
                Canvas a, b;
                fpv_test_last_figure_size = 0;
                fpv_test_underpaint = 0;
                canvas_clear(&a);
                render_fpv_world(&a, &w, w.spawn_x, w.spawn_y, (uint8_t)f, &c, 1);
                int x0 = fpv_test_last_figure_x0, y0 = fpv_test_last_figure_y0;
                int size = fpv_test_last_figure_size;
                fpv_test_underpaint = 1;
                canvas_clear(&b);
                render_fpv_world(&b, &w, w.spawn_x, w.spawn_y, (uint8_t)f, &c, 1);
                fpv_test_underpaint = 0;
                if(!size) continue;
                scenes++;
                int box = size < 8 ? 8 : size;
                RenderBudget bb = budget_at(box);
                figure_compose(&bb, c.family_id, 0, POSE_IDLE, (uint8_t)((x + y) & 1), ink, mask);
                int stride = (box + 7) / 8, leaked = 0;
                for(int yy = 0; yy < size && !leaked; yy++)
                    for(int xx = 0; xx < size; xx++) {
                        int px = x0 + xx, py = y0 + yy;
                        if(px < 0 || py < 0 || px >= 128 || py >= 48) continue;
                        int sx = (xx * box) / size, sy = (yy * box) / size;
                        if(!((mask[sy * stride + (sx >> 3)] >> (sx & 7)) & 1)) continue;
                        if(a.px[py][px] != b.px[py][px]) { leaked = 1; break; }
                    }
                leaks += leaked;
            }
    CHECK(scenes >= 20, "figure: opacity sweep placed creatures in view");
    CHECK(leaks == 0, "figure: creatures are opaque (nothing behind shows through)");
    if(leaks) printf("    %d of %d creature billboards leaked\n", leaks, scenes);
}

/* ── terrain (terrain.h) ─────────────────────────────────────────── */
/* Every PROP in the TERRAIN table, in table order — built from the table so
 * a new prop can't escape the identity / opacity / golden checks. */
#define PROP_MAX 48
static char PROPS[PROP_MAX];
static int PROP_N;
static void props_init(void) {
    PROP_N = 0;
    for(int i = 0; i < terrain_count() && PROP_N < PROP_MAX; i++)
        if(terrain_at(i)->form == TF_PROP) PROPS[PROP_N++] = terrain_at(i)->glyph;
}

static void flat_chunk(World* w, int biome) {
    memset(w, 0, sizeof(*w));
    w->biome = (Biome)biome;
    w->style = style_for_biome(w->biome);
    world_clear_seams(w);
    for(int y = 0; y < WORLD_ROWS; y++)
        for(int x = 0; x < WORLD_COLS; x++)
            w->tiles[y][x] = (x == 0 || y == 0 || x == WORLD_COLS - 1 || y == WORLD_ROWS - 1)
                                 ? TILE_WALL : TILE_FLOOR;
    w->spawn_x = 1; w->spawn_y = 3;
}

/* RULE: a PROP stands in the open — the ray passes it, so the wall behind
 * is still drawn (the old renderer drew every blocker as a full wall). */
static void test_props_do_not_stop_rays(void) {
    World w;
    flat_chunk(&w, BIOME_CAVERN);
    Canvas c;
    canvas_clear(&c);
    render_fpv_world(&c, &w, 1, 3, 1, NULL, 0);
    int empty_top = fpv_test_wall_top[64];
    int bad = 0;
    for(int i = 0; i < PROP_N; i++) {
        w.tiles[3][3] = PROPS[i];
        canvas_clear(&c);
        render_fpv_world(&c, &w, 1, 3, 1, NULL, 0);
        if(fpv_test_wall_top[64] != empty_top) bad++;
        CHECK(world_is_blocking(PROPS[i]) == (PROPS[i] == TILE_ROCK || primitive_glyph_blocks(PROPS[i])),
              "terrain: prop form is render-only — movement comes from the primitive table");
    }
    CHECK(bad == 0, "terrain: props do not stop first-person rays");
    w.tiles[3][3] = 'O';
    canvas_clear(&c);
    render_fpv_world(&c, &w, 1, 3, 1, NULL, 0);
    CHECK(fpv_test_wall_top[64] < empty_top, "terrain: slabs (mega column) still stop rays");
}

/* RULE: identity — every prop has its own silhouette at the device size,
 * and is still distinct at a distant size; mask contains ink. */
static void test_prop_identity(void) {
    static uint8_t ink[PROP_MAX][PIXKIT_PLANE_BYTES], mask[PROP_MAX][PIXKIT_PLANE_BYTES];
    static const int sizes[] = {32, 12};
    for(unsigned z = 0; z < 2; z++) {
        int same = 0, bad_mask = 0;
        for(int i = 0; i < PROP_N; i++) {
            CHECK(terrain_compose_prop(PROPS[i], 0, sizes[z], ink[i], mask[i]), "terrain: prop composes");
            for(int k = 0; k < PIXKIT_PLANE_BYTES; k++) bad_mask += (ink[i][k] & ~mask[i][k]) != 0;
            for(int j = 0; j < i; j++) same += memcmp(mask[i], mask[j], PIXKIT_PLANE_BYTES) == 0;
        }
        CHECK(bad_mask == 0, "terrain: prop mask contains its ink");
        CHECK(same == 0, z == 0 ? "terrain: every prop has its own silhouette (32px)"
                                : "terrain: every prop still distinct at 12px");
    }
    static uint8_t a[PIXKIT_PLANE_BYTES], b[PIXKIT_PLANE_BYTES];
    CHECK(!terrain_compose_prop('#', 0, 32, a, b), "terrain: a wall is not a prop");
}

/* Re-recorded for WORLDGEN 7a: four burial props added (art only, no world
 * change — nothing places them yet). */
#define TERRAIN_GOLDEN 0xC8E84D4F270890D7ULL
static void test_terrain_golden(void) {
    static uint8_t ink[PIXKIT_PLANE_BYTES], mask[PIXKIT_PLANE_BYTES];
    uint64_t h = 0xCBF29CE484222325ULL;
    for(int i = 0; i < PROP_N; i++)
        for(int v = 0; v < TERRAIN_VARIANTS; v++)
            for(int size = 8; size <= PIXKIT_MAX_PX; size++) {
                terrain_compose_prop(PROPS[i], (uint8_t)v, size, ink, mask);
                for(int k = 0; k < PIXKIT_PLANE_BYTES; k++) h = (h ^ ink[k]) * 0x100000001B3ULL;
                for(int k = 0; k < PIXKIT_PLANE_BYTES; k++) h = (h ^ mask[k]) * 0x100000001B3ULL;
            }
    printf("  terrain golden (props): 0x%016llX\n", (unsigned long long)h);
    CHECK(h == TERRAIN_GOLDEN, "terrain: prop golden fingerprint unchanged");
}

/* RULE: a spanning prop is ONE thing — a 2x2 menhir block draws exactly one
 * billboard, from every facing, and grows past the 32 px one-tile cap
 * when close (it is two tiles tall). */
static void test_menhir_is_one_stone(void) {
    World w;
    flat_chunk(&w, BIOME_OUTDOOR);
    w.tiles[2][7] = w.tiles[2][8] = w.tiles[3][7] = w.tiles[3][8] = 'H';
    /* Player positions with the block ahead: east, west, north, south. */
    static const int VIEW[4][3] = {{4, 2, 1}, {11, 3, 3}, {7, 5, 0}, {8, 0, 2}};
    int bad = 0;
    Canvas c;
    for(int i = 0; i < 4; i++) {
        canvas_clear(&c);
        fpv_test_masked_billboards = 0;
        render_fpv_world(&c, &w, VIEW[i][0], VIEW[i][1], (uint8_t)VIEW[i][2], NULL, 0);
        if(fpv_test_masked_billboards != 1) bad++;
    }
    CHECK(bad == 0, "terrain: a 2x2 menhir draws as one billboard from every facing");
    canvas_clear(&c);
    render_fpv_world(&c, &w, 5, 2, 1, NULL, 0);   /* centre 2.5 tiles ahead */
    CHECK(fpv_test_last_figure_size > 24, "terrain: a near menhir is drawn two tiles tall");
    canvas_clear(&c);
    render_fpv_world(&c, &w, 6, 2, 1, NULL, 0);   /* centre 1.5 tiles ahead */
    CHECK(fpv_test_last_figure_size > 32, "terrain: a spanning prop scales past the one-tile cap");
}

/* OPAQUE PROPS (rule 8): a prop in front of a wall hides it. */
static void test_props_are_opaque(void) {
    int scenes = 0, leaks = 0;
    for(int i = 0; i < PROP_N; i++)
        for(int d = 1; d <= 4; d++) {
            World w;
            flat_chunk(&w, BIOME_CAVERN);
            w.tiles[3][1 + d] = PROPS[i];
            Canvas a, b;
            fpv_test_last_figure_size = 0;
            canvas_clear(&a);
            render_fpv_world(&a, &w, 1, 3, 1, NULL, 0);
            int x0 = fpv_test_last_figure_x0, y0 = fpv_test_last_figure_y0, size = fpv_test_last_figure_size;
            fpv_test_underpaint = 1;
            canvas_clear(&b);
            render_fpv_world(&b, &w, 1, 3, 1, NULL, 0);
            fpv_test_underpaint = 0;
            if(!size) continue;
            scenes++;
            int box = size > 32 ? 32 : (size < 8 ? 8 : size);
            static uint8_t ink[PIXKIT_PLANE_BYTES], mask[PIXKIT_PLANE_BYTES];
            /* variant as render_fpv derives it — recompute via any match */
            int leaked = 1;
            for(int v = 0; v < TERRAIN_VARIANTS && leaked; v++) {
                terrain_compose_prop(PROPS[i], (uint8_t)v, box, ink, mask);
                int stride = (box + 7) / 8, bad = 0, drawn = size;   /* recorded post-clamp */
                for(int yy = 0; yy < drawn && !bad; yy++)
                    for(int xx = 0; xx < drawn; xx++) {
                        int px = x0 + xx, py = y0 + yy;
                        if(px < 0 || py < 0 || px >= 128 || py >= 48) continue;
                        int sx = (xx * box) / drawn, sy = (yy * box) / drawn;
                        if(!((mask[sy * stride + (sx >> 3)] >> (sx & 7)) & 1)) continue;
                        if(a.px[py][px] != b.px[py][px]) { bad = 1; break; }
                    }
                leaked = bad;
            }
            leaks += leaked;
        }
    CHECK(scenes >= PROP_N * 3, "terrain: opacity sweep placed props in view");
    CHECK(leaks == 0, "terrain: props are opaque (nothing behind shows through)");
    if(leaks) printf("    %d of %d prop billboards leaked\n", leaks, scenes);
}

/* RULE: on the top-down world screen, terrain never passes for something
 * you act on. Each terrain row's top-down form (its map_icon, else its glyph
 * in the device font) must differ from every item, creature and structure
 * glyph by at least MAP_MIN_APART pixels, and stay inside its own 8px cell
 * (a descender spills into the tile below). Before map_icon, 'l' timber was
 * 1px off the torch 'i', 'v' brazier 1px off the clay pot 'u'.
 * Items and creatures must keep row 0 clear as well: the tool '(' filled
 * it, so a clay pot above it read as a 'y'. Only the player may touch it. */
#define MAP_MIN_APART 3
static void map_form(char g, uint8_t out[FONT2_ROWS]) {
    const uint8_t* icon = terrain_map_icon(g);
    if(!icon) icon = loot_map_icon(g);
    memset(out, 0, FONT2_ROWS);
    if(icon) memcpy(out, icon, 8);
    else if(g >= 32 && g <= 126) memcpy(out, FONT2_CELL[g - 32], FONT2_ROWS);
}
static int map_apart(const uint8_t* a, const uint8_t* b) {
    int d = 0;
    for(int r = 0; r < FONT2_ROWS; r++)
        for(uint8_t x = a[r] ^ b[r]; x; x &= (uint8_t)(x - 1)) d++;
    return d;
}
static void test_map_legibility(void) {
    char actable[64];
    int n = 0;
    for(int i = 0; i < KIND_COUNT; i++) actable[n++] = KIND_CATALOG[i].glyph;
    for(int i = 0; i < CREATURE_FAMILY_COUNT; i++) actable[n++] = CREATURE_FAMILIES[i].glyph;
    static const char STRUCTURE[] = {'@', TILE_DOOR, TILE_STAIRS_UP, TILE_STAIRS_DOWN, TILE_VENDOR, TILE_VAULT};
    for(unsigned i = 0; i < sizeof(STRUCTURE); i++) actable[n++] = STRUCTURE[i];
    int close = 0, spills = 0;
    for(int t = 0; t < terrain_count(); t++) {
        uint8_t f[FONT2_ROWS], o[FONT2_ROWS];
        char g = terrain_at(t)->glyph;
        map_form(g, f);
        if(f[8] || f[9]) {
            spills++;
            printf("    '%c' spills into the tile below\n", g);
        }
        for(int k = 0; k < n; k++) {
            map_form(actable[k], o);
            int d = map_apart(f, o);
            if(d < MAP_MIN_APART) {
                close++;
                printf("    '%c' is %dpx from '%c'\n", g, d, actable[k]);
            }
        }
    }
    int crowds = 0;
    for(int k = 0; k < n; k++) {
        uint8_t o[FONT2_ROWS];
        if(actable[k] == '@') continue;
        map_form(actable[k], o);
        if(o[0] || o[8] || o[9]) {
            crowds++;
            printf("    '%c' reaches past its cell's rows 1..7\n", actable[k]);
        }
    }
    CHECK(close == 0, "map: no terrain looks like an item, creature or structure top-down");
    CHECK(crowds == 0, "map: items, creatures and structures keep a clear row above and below");
    CHECK(spills == 0, "map: every terrain form stays inside its cell");
}

/* RULE: a wall an open chunk grows to face a walled neighbour is the
 * neighbour's wall (World.seam_style): it takes the neighbour's material,
 * and so does a secret in it — a secret drawn in the open chunk's stone
 * among abbey walls would give itself away in first person. DEADBEEF (0,0)
 * is a moor whose west edge faces an abbey. */
static void test_seam_walls_are_the_neighbours(void) {
    World w;
    world_generate_chunk(0xDEADBEEF, 0, 0, &w);
    CHECK(w.style == STYLE_MOOR && w.seam_style[WORLD_SEAM_W] == STYLE_ABBEY,
          "seam: DEADBEEF (0,0) is a moor whose west wall faces an abbey");
    int y = 3;
    while(y < WORLD_ROWS - 1 && w.tiles[y][1] != TILE_FLOOR) y++;
    Canvas c;
    canvas_clear(&c);
    render_fpv_world(&c, &w, 1, y, FPV_FACE_W, NULL, 0);
    CHECK(fpv_test_wall_mat[64] == TM_CARVED, "seam: the moor's west wall is drawn as abbey stone");
    CHECK(w.seam_style[WORLD_SEAM_E] == WORLD_SEAM_NONE && world_wall_style(&w, WORLD_COLS - 1, y) == STYLE_MOOR,
          "seam: an edge facing open ground keeps the chunk's own style");

    /* A secret in a seam wall: same material as the wall around it. */
    World s;
    flat_chunk(&s, BIOME_OUTDOOR);
    s.seam_style[WORLD_SEAM_W] = STYLE_ABBEY;
    s.tiles[3][0] = TILE_SECRET;
    canvas_clear(&c);
    render_fpv_world(&c, &s, 1, 3, FPV_FACE_W, NULL, 0);
    int secret_mat = fpv_test_wall_mat[64];
    canvas_clear(&c);
    render_fpv_world(&c, &s, 1, 2, FPV_FACE_W, NULL, 0);
    CHECK(secret_mat == TM_CARVED && fpv_test_wall_mat[64] == TM_CARVED,
          "seam: a secret in a seam wall wears the neighbour's material too");
    s.seam_style[WORLD_SEAM_N] = STYLE_KEEP;
    CHECK(world_wall_style(&s, 0, 0) == STYLE_KEEP && world_wall_style(&s, 0, 3) == STYLE_ABBEY,
          "seam: a corner takes the north/south edge's style first");
}

/* RULE (spec 58 §58.4): an edge into a region still closed by corruption
 * reads as closed before you touch it — the haze, in both views. A fresh
 * campaign (no ritual done) opens only the origin region (chunks 0..2). */
static void test_closed_edges_show_the_haze(void) {
    RegionRituals none;
    region_rituals_clear(&none);
    World w;
    world_generate_chunk(0x12345678, 1, 1, &w);
    region_mark_world_edges(0x12345678, &none, 1, 1, &w);
    CHECK(w.closed_edges == 0, "haze: a chunk inside the origin region has no closed edge");
    world_generate_chunk(0x12345678, 2, 0, &w);
    region_mark_world_edges(0x12345678, &none, 2, 0, &w);
    CHECK(w.closed_edges == ((1u << WORLD_SEAM_N) | (1u << WORLD_SEAM_E)),
          "haze: the origin's corner chunk is closed to the north and east");
    int hazed_door = 0, hazed_wall = 0;
    for(int y = 0; y < WORLD_ROWS; y++) {
        if(world_cell_in_haze(&w, WORLD_COLS - 1, y)) {
            if(w.tiles[y][WORLD_COLS - 1] == TILE_DOOR) hazed_door++;
            else hazed_wall++;
        }
    }
    CHECK(hazed_door == 1 && hazed_wall == 0, "haze: on a walled closed edge only the doorway hazes");
    CHECK(!world_cell_in_haze(&w, 1, 1), "haze: never inside the chunk");

    /* First person, open ground: DEADBEEF (2,2) is a moor closed east and south. */
    world_generate_chunk(0xDEADBEEF, 2, 2, &w);
    Canvas c;
    canvas_clear(&c);
    render_fpv_world(&c, &w, 12, 2, FPV_FACE_E, NULL, 0);
    int before = fpv_test_wall_mat[64];
    region_mark_world_edges(0xDEADBEEF, &none, 2, 2, &w);
    canvas_clear(&c);
    render_fpv_world(&c, &w, 12, 2, FPV_FACE_E, NULL, 0);
    CHECK(before == -1 && fpv_test_wall_mat[64] == FPV_TEST_MAT_HAZE,
          "haze: an open edge into a closed region draws the haze, not nothing");
    canvas_clear(&c);
    render_fpv_world(&c, &w, 12, 2, FPV_FACE_W, NULL, 0);
    CHECK(fpv_test_wall_mat[64] != FPV_TEST_MAT_HAZE, "haze: an open edge into an open region stays clear");

    /* Generation never reads it: the same chunk generates the same tiles. */
    World a, b;
    world_generate_chunk(0x12345678, 2, 0, &a);
    world_generate_chunk(0x12345678, 2, 0, &b);
    region_mark_world_edges(0x12345678, &none, 2, 0, &b);
    CHECK(memcmp(a.tiles, b.tiles, sizeof(a.tiles)) == 0, "haze: display only, the tiles never change");
}

int main(void) {
    props_init();
    printf("Sanctum RPG — render rule tests\n");
    test_walls_are_opaque();
    test_figure_rules();
    test_figure_identity();
    test_figure_golden();
    test_figures_are_opaque();
    test_props_do_not_stop_rays();
    test_prop_identity();
    test_terrain_golden();
    test_menhir_is_one_stone();
    test_props_are_opaque();
    test_map_legibility();
    test_seam_walls_are_the_neighbours();
    test_closed_edges_show_the_haze();
    printf("%d passed, %d failed\n", g_pass, g_fail);
    return g_fail ? 1 : 0;
}
