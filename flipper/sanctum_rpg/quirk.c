/* quirk.c — see quirk.h. */
#include "quirk.h"

#include <string.h>

#include "terrain.h"

#define CAVE_IN_HIT_MSG  "rock comes down on you."
#define CAVE_IN_MISS_MSG "rubble falls behind you."

static uint32_t quirk_hash(uint32_t seed, int cx, int cy, int x, int y, uint32_t turn, uint32_t salt) {
    uint32_t h = 0x811C9DC5u;
    uint32_t w[6] = {seed, (uint32_t)cx, (uint32_t)cy, (uint32_t)((x & 0xFF) | ((y & 0xFF) << 8)), turn, salt};
    for(int i = 0; i < 6; i++)
        for(int b = 0; b < 4; b++) h = (h ^ ((w[i] >> (8 * b)) & 0xFFu)) * 0x01000193u;
    h ^= h >> 16; h *= 0x7FEB352Du; h ^= h >> 15; h *= 0x846CA68Bu; h ^= h >> 16;
    return h;
}

static int cheb(int ax, int ay, int bx, int by) {
    int dx = ax > bx ? ax - bx : bx - ax, dy = ay > by ? ay - by : by - ay;
    return dx > dy ? dx : dy;
}

bool quirk_fire(uint32_t seed, int cx, int cy, uint32_t turn, QuirkKind k, int x, int y,
                QuirkCause cause, QuirkPending* p) {
    if(p->active || (unsigned)k >= QUIRK_COUNT) return false;
    const QuirkDef* d = &QUIRK_TABLE[k];
    if(cause == QUIRK_BY_CHANCE && quirk_hash(seed, cx, cy, x, y, turn, d->salt) % d->odds != 0) return false;
    p->active = true;
    p->kind = (uint8_t)k;
    p->x = (int8_t)x;
    p->y = (int8_t)y;
    p->due_turn = turn + 1;
    return true;
}

/* Rubble may land on open ground: plain floor or a floor mark (rails...),
 * never a door, item, vendor, vault, prop or the player. */
static bool rubble_may_land(const World* w, int x, int y, int px, int py) {
    if(x < 0 || y < 0 || x >= WORLD_COLS || y >= WORLD_ROWS) return false;
    if(x == px && y == py) return false;
    char t = w->tiles[y][x];
    if(t == TILE_FLOOR) return true;
    const TerrainDef* d = terrain_def(t);
    return d && d->form == TF_FLOOR;
}

static void land_cave_in(uint32_t seed, int cx, int cy, World* w, int px, int py,
                         const QuirkPending* p, QuirkOutcome* out) {
    static const int8_t NX[8] = {-1, 0, 1, 1, 1, 0, -1, -1};
    static const int8_t NY[8] = {-1, -1, -1, 0, 1, 1, 1, 0};
    uint32_t start = quirk_hash(seed, cx, cy, p->x, p->y, p->due_turn, 0x5E1EC7u) & 7u;
    for(int i = 0; i < 8; i++) {
        int k = (int)((start + (uint32_t)i) & 7u);
        int x = p->x + NX[k], y = p->y + NY[k];
        if(!rubble_may_land(w, x, y, px, py)) continue;
        char was = w->tiles[y][x];
        w->tiles[y][x] = CAVE_IN_RUBBLE;
        if(world_doors_reachable_from(w, px, py)) {
            out->placed = true;
            out->rx = (int8_t)x;
            out->ry = (int8_t)y;
            break;
        }
        w->tiles[y][x] = was;   /* would cut the way to a door: try the next */
    }
    bool hit = cheb(px, py, p->x, p->y) <= 1;
    out->damage = hit ? CAVE_IN_DAMAGE : 0;
    out->message = hit ? CAVE_IN_HIT_MSG : CAVE_IN_MISS_MSG;
}

const QuirkDef QUIRK_TABLE[QUIRK_COUNT] = {
    [QUIRK_CAVE_IN] = {'l', QUIRK_ODDS_CAVE_IN, 0xCA7E1Du, "the timbers groan. dust.", land_cave_in},
};

void quirk_step(uint32_t seed, int cx, int cy, uint32_t turn, World* w, int px, int py,
                QuirkPending* p, QuirkOutcome* out) {
    memset(out, 0, sizeof(*out));
    if(p->active) {
        if(turn < p->due_turn) return;
        if(p->kind < QUIRK_COUNT) QUIRK_TABLE[p->kind].land(seed, cx, cy, w, px, py, p, out);
        out->landed = true;
        p->active = false;
        return;
    }
    for(int k = 0; k < QUIRK_COUNT; k++)
        for(int dy = -1; dy <= 1; dy++)
            for(int dx = -1; dx <= 1; dx++) {
                int x = px + dx, y = py + dy;
                if(x < 0 || y < 0 || x >= WORLD_COLS || y >= WORLD_ROWS) continue;
                if(w->tiles[y][x] != QUIRK_TABLE[k].trigger) continue;
                if(quirk_fire(seed, cx, cy, turn, (QuirkKind)k, x, y, QUIRK_BY_CHANCE, p)) {
                    out->told = true;
                    out->message = QUIRK_TABLE[k].tell;
                    return;
                }
            }
}
