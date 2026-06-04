/*
 * recipes.c — see recipes.h.
 *
 * Initial slice 4 catalog: three recipes to demonstrate the loop end-to-end.
 * Each recipe sums to 100 in weights (FLOOR + HIT + JACKPOT). Future slices
 * extend this catalog and add skill/material-quality modifiers to the roll
 * (game-theory agent's `lift` formula). For slice 4 we ship the static base
 * weights — the slot machine spins, the floor is always sellable.
 *
 * Kind ids referenced (from loot.c): 0 = crystal, 1 = fungus, 2 = clay pot,
 * 3 = vial, 4 = tool, 5 = torch, 6 = chest. We don't include those headers
 * here to keep this module independent.
 */

#include "recipes.h"

#include <stddef.h>

const RecipeDef RECIPE_CATALOG[] = {
    /* "Crystal Brew" — 2 crystal → 1 vial (heal +8). Easy mid-game recipe. */
    {
        .name = "Crystal Brew",
        .output_kind = 3, /* vial */
        .input_kind_a = 0, /* crystal */
        .input_qty_a = 2,
        .input_kind_b = RECIPE_NO_INPUT,
        .input_qty_b = 0,
        .weight_floor = 40,
        .weight_hit = 55,
        .weight_jackpot = 5,
        .oddment_credits = 3,
    },
    /* "Fungal Distillate" — 2 fungus → 1 vial. Outdoor-leaning alternative. */
    {
        .name = "Fungal Distillate",
        .output_kind = 3, /* vial */
        .input_kind_a = 1, /* fungus */
        .input_qty_a = 2,
        .input_kind_b = RECIPE_NO_INPUT,
        .input_qty_b = 0,
        .weight_floor = 45,
        .weight_hit = 50,
        .weight_jackpot = 5,
        .oddment_credits = 2,
    },
    /* "Honed Edge" — 1 crystal + 1 clay pot → 1 tool (weapon, +2 atk on equip).
     * Higher-value recipe; uses two distinct materials. */
    {
        .name = "Honed Edge",
        .output_kind = 4, /* tool */
        .input_kind_a = 0, /* crystal */
        .input_qty_a = 1,
        .input_kind_b = 2, /* clay pot */
        .input_qty_b = 1,
        .weight_floor = 50,
        .weight_hit = 42,
        .weight_jackpot = 8,
        .oddment_credits = 5,
    },
};

const int RECIPE_COUNT =
    (int)(sizeof(RECIPE_CATALOG) / sizeof(RECIPE_CATALOG[0]));

const RecipeDef* recipe_def(uint8_t recipe_id) {
    if((int)recipe_id >= RECIPE_COUNT) return NULL;
    return &RECIPE_CATALOG[recipe_id];
}

int recipe_craftable(const RecipeDef* r, const uint8_t* inv_qty, int inv_len) {
    if(!r || !inv_qty) return 0;
    if(r->input_kind_a >= inv_len) return 0;
    if(inv_qty[r->input_kind_a] < r->input_qty_a) return 0;
    if(r->input_kind_b != RECIPE_NO_INPUT) {
        if(r->input_kind_b >= inv_len) return 0;
        if(inv_qty[r->input_kind_b] < r->input_qty_b) return 0;
    }
    return 1;
}

PullTier recipe_pull(Rng* rng, const RecipeDef* r) {
    if(!r) return PULL_FLOOR;
    uint32_t total = (uint32_t)r->weight_floor + (uint32_t)r->weight_hit +
                     (uint32_t)r->weight_jackpot;
    if(total == 0) return PULL_FLOOR;
    uint32_t pick = rng_range(rng, 0, total);
    if(pick < r->weight_floor) return PULL_FLOOR;
    if(pick < (uint32_t)r->weight_floor + r->weight_hit) return PULL_HIT;
    return PULL_JACKPOT;
}
