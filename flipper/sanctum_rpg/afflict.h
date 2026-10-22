/*
 * afflict.h — what the dead do to you, and the destructive crafts
 * (spec 50 Q1 §Q.3, §Q.4, §Q.10; spec 58 step 7).
 *
 * Each of the dead's kinds carries a Trait.effect (data). Area kinds act
 * within AREA_RADIUS of the player, once per turn, no stacking per kind;
 * horde kinds act in combat by how many stand beside you. Rot spoils what
 * you carry into corrupted kinds (KF_CORRUPTED), which craft only the
 * destructive tree: hidden recipes, found by experimenting at the forge or
 * by reading a book (a root) or a tome (the branch).
 *
 * Pure: the caller applies the results to the character, the foe and the
 * screen. Integer-only, host-tested.
 */
#pragma once

#include <stdbool.h>
#include <stdint.h>

#include "creatures.h"
#include "save_io.h"

/* Tunables (spec 50 Q1 §Q.7). */
#define AREA_RADIUS        2
#define WITHER_FUEL_EXTRA  1
#define HORDE_FLANK_ATK    1
#define FOUL_TURNS         6
#define FOUL_DAMAGE        1
#define FEED_ATK           2
#define FEED_HEAL          1
#define BLEED_TURNS        3
#define ROT_ODDS           8
#define FOUL_MAX           4    /* foul patches at once in a chunk */
/* The tree's outputs (spec 50 Q1 §Q.10.4). */
#define POISON_TURNS       4    /* rot tincture: the foe takes POISON_DAMAGE a round */
#define POISON_DAMAGE      1
#define COATING_HITS       3    /* sour draught: the next hits that land poison */
#define COATING_POISON     2    /* rounds of poison per coated hit */
#define BLIGHT_DAMAGE      3    /* blight: at once, then a foul patch at the foe */

/* Kinds (loot.c) and recipes (recipes.c) this module names. */
#define AF_KIND_FUNGUS     1
#define AF_KIND_VIAL       3
#define AF_KIND_ROTCAP     20
#define AF_KIND_SOURVIAL   21
#define AF_KIND_TINCTURE   22
#define AF_KIND_DRAUGHT    23
#define AF_KIND_BLIGHT     24
#define AF_RECIPE_TINCTURE 4
#define AF_RECIPE_DRAUGHT  5
#define AF_RECIPE_BLIGHT   6

/* Copy (spec 58 §58.9 option A; DRAFT where it has none). */
#define AF_LINE_SPOIL      "your %s has turned."
#define AF_LINE_NOTHING    "nothing comes of it."        /* DRAFT */
#define AF_LINE_DARK       "a dark mixture?"              /* the forge's hint, §Q.10.2 */
#define AF_LINE_COATED     "the edge darkens."            /* DRAFT */

/* The area effects the player stands in this turn. */
typedef struct {
    bool wither;   /* the torch burns WITHER_FUEL_EXTRA more */
    bool chill;    /* every other step costs an extra turn */
    bool rot;      /* a carried consumable may spoil */
} AreaFelt;

void afflict_area(const Creature* cs, int n, int px, int py, AreaFelt* out);

/* The attack the foe at `foe` adds this round: HORDE_FLANK_ATK for each
 * other live dead of its kind beside the player (a flanking horde), and
 * FEED_ATK if it feeds and the player is below half health. */
int afflict_foe_bonus(const Creature* cs, int n, int foe, int px, int py, uint16_t hp, uint16_t max_hp);

/* The foe's hit landed: a bleeder opens a bleed, a feeder heals. */
void afflict_foe_hit(uint8_t trait, CharacterState* c, uint16_t* foe_hp, uint16_t foe_max);

/* Foul patches: RAM only, with a turn expiry (§Q.4: never saved). */
typedef struct {
    struct { int8_t x, y; uint32_t until; } p[FOUL_MAX];
    uint8_t n;
} FoulField;

void foul_clear(FoulField* f);
/* A patch on (x, y) and its neighbours, until turn + FOUL_TURNS. */
void foul_add(FoulField* f, int x, int y, uint32_t turn);
/* Damage for standing on (x, y) on `turn`; expired patches are dropped. */
int foul_step(FoulField* f, int x, int y, uint32_t turn);
bool foul_at(const FoulField* f, int x, int y, uint32_t turn);

/* A foe died: a bloated one leaves a foul patch where it fell. */
void afflict_foe_died(uint8_t trait, int x, int y, uint32_t turn, FoulField* f);

/* One turn of bleeding: -1 HP while the bleed runs. Returns the damage. */
int afflict_bleed_tick(CharacterState* c);

/* Near rot this turn: 1 in ROT_ODDS (by hash) spoils one carried fungus
 * cap or vial into its corrupted kind. Returns the kind that spoiled (the
 * fresh one), or 0xFF. */
uint8_t afflict_rot(uint32_t seed, int cx, int cy, uint32_t turn, CharacterState* c);

/* The corrupted kind a fresh kind spoils into, or 0xFF. */
uint8_t afflict_spoils_into(uint8_t kind);

/* Is the player carrying anything corrupted (the forge offers to experiment)? */
bool afflict_carries_corrupted(const CharacterState* c);

/* Experiment at the forge: the first hidden destructive recipe the player's
 * bag can make, now discovered; or -1 (nothing learned, nothing spent). */
int afflict_experiment(CharacterState* c);

/* Reading a word source also teaches from the dark tree (§Q.10.2): a book a
 * root (by hash of where it lay), a tome the branch. Returns the recipe
 * learned, or -1. */
int afflict_read(char glyph, uint32_t seed, int cx, int cy, int x, int y, CharacterState* c);

/* What a combat throw does: the kind thrown (tincture first, then blight),
 * or 0xFF if nothing throwable is carried. */
uint8_t afflict_throwable(const CharacterState* c);
