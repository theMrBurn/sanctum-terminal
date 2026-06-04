/*
 * trade.h — regional economy. Vendor chunks, per-chunk price deltas,
 *           buy/sell/scrap pricing helpers.
 *
 * The Elite-'84-style trade triangle: each chunk × kind pair has a
 * deterministic price modifier in [-50, +50]. Negative = local SURPLUS
 * (the vendor sells cheap, also pays poorly to buy more). Positive =
 * local SCARCITY (vendor pays handsomely for it, charges a premium to
 * resell). A small static spread separates the vendor's bid (sell-to)
 * and ask (buy-from) so vendors always have a margin.
 *
 * Vendor chunks: ~1 in 6 chunks gets a vendor, deterministically chosen
 * from (campaign_seed × chunk_xy). When a chunk is a vendor chunk, a
 * single `V` tile sits at a deterministic interior position; the rest of
 * the chunk is unchanged.
 *
 * Pricing model (one int8_t delta per kind per chunk):
 *
 *   vendor BUY  (what you pay vendor):  base × (100 + delta + SPREAD)/100
 *   vendor SELL (what vendor pays you): base × (100 + delta - SPREAD)/100
 *   scrap (Down-from-inventory shop):   base / 2  — anywhere, lossy
 *
 * With SPREAD=20: buying at surplus chunk (delta=-50) costs base × 70%;
 * selling at scarcity chunk (delta=+50) yields base × 130%. Profit:
 * 60% per round-trip unit, before travel cost (torch fuel + creature
 * encounters + weather).
 *
 * Pure module — integer math, no SDK deps, host-testable.
 */

#pragma once

#include <stdbool.h>
#include <stdint.h>

#define TRADE_SPREAD 20 /* vendor margin, % of base */

/* Is this chunk a vendor chunk? Deterministic per (seed × cx × cy).
 * Approximate hit rate: ~1 in 6 chunks. */
bool chunk_has_vendor(uint32_t campaign_seed, int chunk_x, int chunk_y);

/* The deterministic interior position of the vendor tile in a vendor
 * chunk. Always within the [2..WORLD_COLS-3] × [1..WORLD_ROWS-2] box
 * so it doesn't collide with the cavern's perimeter walls or mid-edge
 * doors. */
void vendor_position(
    uint32_t campaign_seed, int chunk_x, int chunk_y, int* vx, int* vy);

/* Price modifier for this (chunk, kind), in range [-50, +50] (percent
 * of base). Same inputs → byte-equal delta — port-stable. */
int8_t chunk_price_delta(
    uint32_t campaign_seed, int chunk_x, int chunk_y, uint8_t kind_id);

/* Pricing helpers. `base` is the kind's catalog `value`. */
uint16_t trade_buy_price(uint16_t base, int8_t delta);   /* vendor ask */
uint16_t trade_sell_price(uint16_t base, int8_t delta);  /* vendor bid */
uint16_t trade_scrap_price(uint16_t base);               /* inventory scrap */
