/*
 * quirk.h — terrain quirks that happen TO the player (spec 50 Q1 §Q.1).
 *
 * Scree and glowcap act when you step on them (terrain.h step_*). A quirk is
 * different: it arms near a trigger tile, shows its tell, and lands on the
 * player's NEXT turn. That one turn is the counterplay.
 *
 * Two ways to arm one, through the same function:
 *   by chance   — a step that ends next to a trigger tile rolls
 *                 hash(seed, chunk, tile, turn, salt) % odds == 0. A hash,
 *                 not an RNG stream: it never disturbs world generation or
 *                 any other roll, and the same play replays identically.
 *   by trigger  — reserved (§Q.2): skips the roll, keeps the tell, the
 *                 delay and every safety rule. v1 ships no triggers.
 *
 * Only one quirk is pending at a time. Data-table-driven: a quirk is a
 * QUIRK_TABLE row (trigger glyph, odds, salt, tell). Pure, host-testable;
 * the caller applies the outcome (status line, HP, the rubble delta).
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "world.h"

typedef enum {
    QUIRK_CAVE_IN = 0,   /* mine: rubble falls near a timber prop */
    QUIRK_COUNT,
} QuirkKind;

typedef enum { QUIRK_BY_CHANCE = 0, QUIRK_BY_TRIGGER } QuirkCause;


/* Cave-in tunables (spec 50 Q1 §Q.7). */
#define QUIRK_ODDS_CAVE_IN 64
#define CAVE_IN_DAMAGE     3
#define CAVE_IN_RUBBLE     '^'

typedef struct {
    bool active;
    uint8_t kind;        /* QuirkKind */
    int8_t x, y;         /* the trigger tile */
    uint32_t due_turn;   /* lands on this turn */
} QuirkPending;

typedef struct {
    bool told;           /* armed this turn: show `message` (the tell) */
    bool landed;         /* resolved this turn */
    bool placed;         /* rubble landed at (rx, ry): record it as a delta */
    int8_t rx, ry;
    uint8_t damage;      /* HP the player takes */
    const char* message; /* status line, or NULL */
} QuirkOutcome;

typedef struct {
    char trigger;        /* the tile a step must end next to */
    uint16_t odds;       /* 1 in `odds` qualifying steps */
    uint32_t salt;       /* keeps each quirk's rolls independent */
    const char* tell;    /* shown when it arms, one turn before it lands */
    /* What landing does (the table row owns it; no `if kind ==`). */
    void (*land)(uint32_t seed, int cx, int cy, World* w, int px, int py,
                 const QuirkPending* p, QuirkOutcome* out);
} QuirkDef;

extern const QuirkDef QUIRK_TABLE[QUIRK_COUNT];

/* Arm a quirk at trigger tile (x, y) for turn `turn`. QUIRK_BY_CHANCE rolls
 * first; QUIRK_BY_TRIGGER doesn't. False if one is already pending or the
 * roll misses. */
bool quirk_fire(uint32_t seed, int cx, int cy, uint32_t turn, QuirkKind k, int x, int y,
                QuirkCause cause, QuirkPending* p);

/* One player turn ended at (px, py) on turn `turn`: land a due quirk, or
 * roll the trigger tiles next to the player. May change `w` (the rubble). */
void quirk_step(uint32_t seed, int cx, int cy, uint32_t turn, World* w, int px, int py,
                QuirkPending* p, QuirkOutcome* out);
