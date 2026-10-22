/*
 * effort.h — one general function for demanding tasks (spec 58 §58.7.5).
 *
 * Effort is not a meter. It is computed from what the player already has:
 *
 *   available = (fuel - FUEL_FLOOR) + (hp - HP_FLOOR)
 *             + EFFORT_PER_SKILL * max(0, axis - EFFORT_SKILL_BASE)
 *   required  = turns * difficulty
 *   success   = available >= required
 *
 * A task takes `turns` turns. Each turn costs required/turns (the last turn
 * the remainder), paid from the skill bonus first, then from the body:
 * EFFORT_HP_SHARE percent from health, the rest from fuel, each side
 * covering the other's shortfall. Neither goes below its floor, so effort
 * alone never takes health to zero. If the body can't pay, the task fails
 * there: what was spent stays spent (the caller keeps what was found).
 *
 * Interruption (the kept way: a creature engages, the player moves) is
 * the caller's: it abandons the run and starts a new one.
 *
 * Fuel is an input, not the character's torch: v0.6.1 replaces the torch
 * with shards (spec 43 §17.4), and effort shouldn't care which. Pure,
 * integer-only, host-tested.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

/* Tunables (spec 58 §58.11 #3: set in playtest). */
#define EFFORT_PER_SKILL   4    /* effort per point of axis above the base */
#define EFFORT_SKILL_BASE  8    /* a fresh character's axes are 10 */
#define EFFORT_HP_SHARE    25   /* percent of each turn's body cost from health */
#define EFFORT_FUEL_FLOOR  5    /* effort never burns the light below this */
#define EFFORT_HP_FLOOR    1    /* effort never takes health below this */

typedef struct {
    uint8_t turns;       /* >= 1 */
    uint8_t difficulty;  /* effort per turn */
    uint8_t axis;        /* DEED_AXIS_*: the skill it leans on */
} EffortTask;

typedef struct {
    uint16_t fuel;
    uint16_t hp;
    uint8_t axis_value;  /* the player's effective axis for the task */
} EffortBody;

typedef enum {
    EFFORT_GOING = 0,    /* more turns to go */
    EFFORT_DONE,         /* the last turn is paid: the task succeeded */
    EFFORT_SPENT,        /* the body couldn't pay: the task failed */
} EffortState;

typedef struct {
    EffortTask task;
    uint8_t turns_done;
    uint16_t skill_left;  /* the skill bonus not yet spent */
    uint16_t paid;        /* effort paid so far (skill + body) */
} EffortRun;

uint16_t effort_skill(const EffortTask* t, const EffortBody* b);
uint16_t effort_available(const EffortTask* t, const EffortBody* b);
uint16_t effort_required(const EffortTask* t);
bool effort_can(const EffortTask* t, const EffortBody* b);

/* The line before starting: the odds in words, never a number (43 §17.10). */
const char* effort_odds_line(const EffortTask* t, const EffortBody* b);

void effort_begin(EffortRun* r, const EffortTask* t, const EffortBody* b);
/* Pay one turn from `b`. */
EffortState effort_turn(EffortRun* r, EffortBody* b);
