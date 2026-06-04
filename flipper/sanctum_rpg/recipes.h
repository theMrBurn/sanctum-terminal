/*
 * recipes.h — slot-machine crafting (slice 4, spec 46 §3).
 *
 * Each recipe carries inputs (1-2 kinds × required qty), an output kind, and
 * the three base tier weights for the single weighted `rng_range` roll that
 * decides the pull's outcome: JACKPOT (masterwork — bonus quantity), HIT
 * (standard — the item), FLOOR (sellable oddment — credits, never nothing).
 *
 * The user's design (verbatim): "slot machine craft system, super simple,
 * and it notifies us if we have the materials to attempt crafting an item,
 * and at worse it makes a useful object to sell at a shop. like, that simple."
 *
 * Pure module — no Flipper SDK; host-testable via `make test`.
 */

#pragma once

#include <stdint.h>

#include "rng.h"

/* Tier of a single Forge pull. */
typedef enum {
    PULL_FLOOR = 0,  /* oddment — credits, no item */
    PULL_HIT,        /* the item, standard quality (qty 1) */
    PULL_JACKPOT,    /* the item, masterwork (qty 2 — bonus stack) */
} PullTier;

/* Sentinel for "no second input." */
#define RECIPE_NO_INPUT 0xFFu

typedef struct {
    const char* name;        /* "Crystal Brew" */
    uint8_t output_kind;     /* KindDef id produced on HIT/JACKPOT */
    uint8_t input_kind_a;
    uint8_t input_qty_a;
    uint8_t input_kind_b;    /* RECIPE_NO_INPUT if unused */
    uint8_t input_qty_b;
    uint8_t weight_floor;    /* base % chance of oddment */
    uint8_t weight_hit;      /* base % chance of standard */
    uint8_t weight_jackpot;  /* base % chance of masterwork — sums to 100 */
    uint8_t oddment_credits; /* credits granted on FLOOR */
} RecipeDef;

extern const RecipeDef RECIPE_CATALOG[];
extern const int RECIPE_COUNT;

/* Look up a recipe. NULL on out-of-range id. */
const RecipeDef* recipe_def(uint8_t recipe_id);

/* Do the held inventory counts satisfy this recipe? */
int recipe_craftable(const RecipeDef* r, const uint8_t* inv_qty, int inv_len);

/* One weighted roll → tier. Weights sum should be 100; if not, `total` is
 * derived from the recipe's three weights. Deterministic from `rng`. */
PullTier recipe_pull(Rng* rng, const RecipeDef* r);
