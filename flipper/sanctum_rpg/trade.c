/*
 * trade.c — see trade.h.
 */

#include "trade.h"

#include "loot.h"

#include "world.h"

/* FNV-1a-flavored hash, same shape as weather.c / names.c. */
static uint32_t trade_hash32(uint32_t a, uint32_t b, uint32_t c, uint32_t d) {
    uint32_t h = 0x811C9DC5u;
    uint32_t vs[4] = {a, b, c, d};
    for(int i = 0; i < 4; i++) {
        uint32_t v = vs[i];
        h ^= (v >>  0) & 0xFFu; h *= 16777619u;
        h ^= (v >>  8) & 0xFFu; h *= 16777619u;
        h ^= (v >> 16) & 0xFFu; h *= 16777619u;
        h ^= (v >> 24) & 0xFFu; h *= 16777619u;
    }
    h ^= h >> 16;
    h *= 0x85EBCA6Bu;
    h ^= h >> 13;
    return h;
}

bool chunk_has_vendor(uint32_t seed, int cx, int cy) {
    uint32_t h = trade_hash32(seed, (uint32_t)cx, (uint32_t)cy, 0x7E1D0A12u);
    /* ~1 in 6 chunks gets a vendor. The `% 6` is fine for byte-equal
     * across ports — same hash, same modulo. Chunk (0,0) is FORCED to
     * not be a vendor (it's reserved for the home/vault tile in slice C). */
    if(cx == 0 && cy == 0) return false;
    return (h % 6u) == 0u;
}

void vendor_position(uint32_t seed, int cx, int cy, int* vx, int* vy) {
    if(!vx || !vy) return;
    uint32_t h = trade_hash32(seed, (uint32_t)cx, (uint32_t)cy, 0x5E11E8Cu);
    /* Interior box: x ∈ [2, COLS-3], y ∈ [1, ROWS-2]. Avoids perimeter
     * walls + the mid-edge doors (which are at the very perimeter). */
    int x_range = WORLD_COLS - 4;  /* [2 .. COLS-3] inclusive */
    int y_range = WORLD_ROWS - 2;  /* [1 .. ROWS-2] inclusive */
    *vx = 2 + (int)((h >> 0) % (uint32_t)x_range);
    *vy = 1 + (int)((h >> 8) % (uint32_t)y_range);
}

int8_t chunk_price_delta(uint32_t seed, int cx, int cy, uint8_t kind_id) {
    uint32_t h = trade_hash32(seed, (uint32_t)cx, (uint32_t)cy, (uint32_t)kind_id);
    /* Map [0, 100) → [-50, +50). Skews slightly negative on the boundary
     * but that's a 1-unit bias and irrelevant in play. */
    int v = (int)(h % 101u) - 50;
    if(v > 50) v = 50;
    if(v < -50) v = -50;
    return (int8_t)v;
}

bool trade_kind_is_numeraire(uint8_t kind_id) {
    return kind_id == (uint8_t)TRADE_NUMERAIRE_KIND;
}

bool trade_kind_untradeable(uint8_t kind_id) {
    const KindDef* k = kind_by_id(kind_id);
    return trade_kind_is_numeraire(kind_id) || (k && (k->flags & KF_NOTRADE));
}

uint16_t trade_shards_earned(uint16_t value) {
    /* §17.5a rule 1 — truncate toward the player's loss. */
    return (uint16_t)((uint32_t)value / TRADE_SHARD_VALUE);
}

uint16_t trade_shards_owed(uint16_t value) {
    /* Same rule, other direction: a part-shard debt costs a whole shard. */
    uint32_t v = (uint32_t)value + (TRADE_SHARD_VALUE - 1u);
    return (uint16_t)(v / TRADE_SHARD_VALUE);
}

uint16_t trade_buy_price(uint8_t kind_id, uint16_t base, int8_t delta) {
    if(trade_kind_untradeable(kind_id)) return TRADE_NO_PRICE;
    /* Vendor's ask: base × (100 + delta + spread) / 100 */
    int p = (int)base * (100 + (int)delta + TRADE_SPREAD) / 100;
    if(p < 1) p = 1;
    if(p > 0xFFFF) p = 0xFFFF;
    return (uint16_t)p;
}

uint16_t trade_sell_price(uint8_t kind_id, uint16_t base, int8_t delta) {
    if(trade_kind_untradeable(kind_id)) return TRADE_NO_PRICE;
    /* Vendor's bid: base × (100 + delta - spread) / 100 */
    int p = (int)base * (100 + (int)delta - TRADE_SPREAD) / 100;
    if(p < 1) p = 1;
    if(p > 0xFFFF) p = 0xFFFF;
    return (uint16_t)p;
}

uint16_t trade_scrap_price(uint8_t kind_id, uint16_t base) {
    if(trade_kind_untradeable(kind_id)) return TRADE_NO_PRICE;
    /* Anywhere, lossy: half of base. Floor at 1. */
    return (base / 2u) > 0u ? (uint16_t)(base / 2u) : 1u;
}
