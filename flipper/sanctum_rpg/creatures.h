/*
 * creatures.h — the creature pantheon: composed, not authored.
 *
 * The Elite move (spec 45 §4.5): we do NOT enumerate hundreds of creatures.
 * Two small `static const` tables — body-plan Families and biome-locked
 * Traits — compose deterministically into the whole pantheon. A live
 * creature stores only {family_id, trait_id, ...}; its flat CreatureDef is
 * recomposed on demand. Adding a creature = one table row. No `if kind ==`.
 *
 * This header is the v0.4.0a data foundation: tables + compose + biome-
 * weighted rolls (pure, host-testable, deterministic). The overworld FSM
 * tick, scan, and aggro ride in later slices; CreatureState is declared
 * here so the tick + renderer share one definition.
 *
 * Spec: sanctum-os/docs/specs/45_combat_creatures_vitals.md §4.5-4.9.
 * Pure module — no <furi.h>. Host-compilable via `make test`.
 */

#pragma once

#include <stdint.h>

#include "biome.h"
#include "rng.h"
#include "world.h"

/* Innate base behaviour (spec 45 §4.8). The live `aggro` accumulator can
 * push a non-hostile creature into hostile and decay it back; HOSTILE sits
 * at provoke_threshold 0 and never pacifies. */
typedef enum {
    DISP_PASSIVE = 0,
    DISP_SKITTISH,
    DISP_TERRITORIAL,
    DISP_HOSTILE,
} Disposition;

/* Element — combat mods applied as x4 fixed-point at use time (Tier-2). */
typedef enum {
    ELEM_NONE = 0,
    ELEM_FIRE,
    ELEM_ICE,
} Element;

/* Skill aptitude a family teaches on bestiary mastery (spec 45 §4.6).
 * Inert until the Tier-2 skill system reads it. */
typedef enum {
    APT_NONE = 0,
    APT_SCAVENGE,
    APT_FORTITUDE,
    APT_PATIENCE,
    APT_PERCEPTION,
    APT_RESILIENCE,
    APT_FROST,
    APT_EMBER,
} Aptitude;

/* Behaviour flags (move_flags | add_flags), OR-combined at compose. */
enum {
    CF_FLIGHT      = 1u << 0, /* ignores ground obstacles; reads as hovering */
    CF_PACK        = 1u << 1, /* spawns + reacts in groups */
    CF_PHOTOPHOBIC = 1u << 2, /* bolder as your torch dims (§5.5) */
    CF_PHOTOPHILIC = 1u << 3, /* drawn to your light (§5.5) */
};

/* Overworld FSM state — 2 bits (spec 45 §4.2). Lives on the live creature,
 * not the def; declared here so the (later) tick + render agree. */
typedef enum {
    CR_IDLE = 0,
    CR_APPROACH,
    CR_FLEE,
    CR_ENGAGE,
} CreatureState;

/* Body plan (spec 45 §4.5). Flash-resident static const table. Radii are in
 * Chebyshev tiles; speed = energy gained per world-turn (the energy/speed
 * tick lands in the movement slice). */
typedef struct {
    char        glyph;      /* r b s B S ... */
    const char* root;       /* name root: "rat" */
    uint16_t    base_hp;
    uint8_t     base_atk, base_def, base_speed;
    uint8_t     move_flags;
    uint8_t     disposition;
    uint8_t     notice;     /* awareness radius */
    int8_t      flee;       /* flee radius; <0 ⇒ approaches (signed) */
    uint8_t     provoke;    /* provoke_threshold; 0 ⇒ born hostile */
    uint8_t     scan_diff;  /* OBSERVE proficiency needed for the basic read */
    uint8_t     aptitude;   /* skill taught on mastery */
    uint8_t     biomes;     /* spawn affinity (BIOME_BIT mask) */
    uint8_t     weight;     /* spawn weight */
} Family;

/* Biome-locked evolutionary adaptation (spec 45 §4.5). Trait[0] is "plain"
 * (no change), weighted to dominate so most creatures are unmodified. */
typedef struct {
    const char* affix;      /* "frost-"; "" for plain */
    int8_t      d_hp, d_atk, d_def, d_speed;
    uint8_t     element;
    uint8_t     add_flags;
    int8_t      d_flee;     /* shade skittishness (signed) */
    uint8_t     aptitude_mod;
    uint8_t     biome_mask; /* which biomes allow this trait — the biome-lock */
    uint8_t     weight;     /* trait-roll weight (plain dominates) */
} Trait;

/* A composed creature: family × trait resolved to flat stats. Cheap value
 * type; recomposed on demand from {family_id, trait_id}. */
typedef struct {
    uint8_t  family_id, trait_id;
    char     glyph;
    uint16_t hp;
    uint8_t  atk, def, speed;
    uint8_t  element;
    uint8_t  flags;
    uint8_t  disposition;
    uint8_t  notice;
    int8_t   flee;
    uint8_t  provoke;
    uint8_t  scan_diff;
    uint8_t  aptitude;        /* family's */
    uint8_t  aptitude_trait;  /* trait's shade (APT_NONE if none) */
} CreatureDef;

extern const Family CREATURE_FAMILIES[];
extern const int    CREATURE_FAMILY_COUNT;
extern const Trait  CREATURE_TRAITS[];
extern const int    CREATURE_TRAIT_COUNT;

const Family* creature_family(uint8_t id);
const Trait*  creature_trait(uint8_t id);

/* Resolve {family,trait} → flat CreatureDef (bad ids fall back safely). */
void creature_compose(uint8_t family_id, uint8_t trait_id, CreatureDef* out);

/* Biome-weighted rolls (mirror loot_roll). trait_roll only ever returns a
 * trait whose biome_mask includes `biome` — the biome-lock. */
uint8_t creature_family_roll(Rng* r, Biome biome);
uint8_t creature_trait_roll(Rng* r, Biome biome);

/* Slice 50.F2 — Pool-biased variant. Multiplies each eligible family's
 * biome weight by `pool->family_bias[family_id]` per spec 50 §4.2 +
 * engine addendum §F1.4.a formula: w = base * (8 + bias) / 8 (bias
 * clamped to 56). Pass NULL pool for no bias (matches the legacy fn). */
#include "pool.h"
uint8_t creature_family_roll_pooled(
    Rng* r, Biome biome, const Pool* pool);

/* Slice 50.F2 — Pool-biased convenience. */
void creature_roll_pooled(
    Rng* r, Biome biome, const Pool* pool,
    uint8_t* out_family, uint8_t* out_trait);

/* Convenience: roll a family, then a biome-locked trait. */
void creature_roll(Rng* r, Biome biome, uint8_t* out_family, uint8_t* out_trait);

/* Compose the display name into buf ("frost-rat" / "rat"). */
void creature_name(const CreatureDef* d, char* buf, int buflen);

/* ── live creatures (v0.4.0b) ───────────────────────────────────────── */

#define CREATURES_MAX 8 /* per-chunk cap */

/* A live creature in the current chunk. RAM-only: regenerated on chunk
 * (re)entry, so leaving a chunk resets transient state — the spec 45 §4.8
 * "chunk-exit de-escalation" feature. Defeated/fled persistence is a later
 * delta-layer slice. */
typedef struct {
    uint8_t family_id, trait_id;
    uint8_t x, y;
    uint8_t state;  /* CreatureState — idle until the movement/FSM slice */
    uint8_t energy; /* action-point accumulator (movement slice) */
    uint8_t aggro;  /* provocation accumulator (aggro slice) */
    uint8_t alive;
    uint8_t spawn_x, spawn_y; /* initial position; deterministic-key for kill persistence (slice 1b) */
} Creature;

/* Populate `out` (cap `max`) for a chunk: deterministic count + placement
 * from the chunk seed (a SEPARATE rng stream from world-gen, so world
 * fingerprints stay untouched), biome-rolled, on walkable non-spawn floor.
 * Returns the count placed. Each placed creature has spawn_x/spawn_y set to
 * its initial position — the deterministic key for kill persistence. */
int creatures_populate(
    uint32_t chunk_seed, Biome biome, const World* world, int player_x,
    int player_y, Creature* out, int max);

/* Slice 50.F2 — Pool-biased population. Same as creatures_populate but
 * uses Pool-biased family_roll under the hood. NULL pool = legacy. */
int creatures_populate_pooled(
    uint32_t chunk_seed, Biome biome, const World* world, int player_x,
    int player_y, const Pool* pool, Creature* out, int max);

/* Mark the creature whose spawn position matches (sx, sy) as not-alive.
 * Used after populate to apply persisted kills from the delta layer. */
void creatures_mark_dead_at_spawn(
    Creature* cs, int n, uint8_t spawn_x, uint8_t spawn_y);

/* Advance all creatures one world-turn (the player already paid the turn, so
 * this never touches the clock). Energy/speed gated — fast creatures act more
 * often than slow ones; the FSM (idle/wander → approach | flee → engage) is
 * keyed on the pattern keys + Chebyshev distance; `torch_radius` is the
 * awareness zone (light = perception, spec 45 §5.5). Deterministic from
 * (chunk_seed, turn, slot) with no persistent RNG state — golden-master safe,
 * port-reproducible. Mutates `cs` in place. Returns the count of hostile
 * creatures now adjacent to the player (innately hostile or provoked past
 * their threshold) — the caller applies the contact fuel "flicker". */
int creatures_tick(
    Creature* cs, int n, const World* world, int player_x, int player_y,
    int torch_radius, uint32_t chunk_seed, uint32_t turn);

/* Is this creature currently hostile — innately HOSTILE, or provoked past its
 * threshold (spec 45 §4.8)? Shared by the contact count + the combat trigger. */
int creature_is_hostile(uint8_t disposition, uint8_t provoke, uint8_t aggro);

/* ── scan / bestiary (v0.4.0d, spec 45 §4.7) ────────────────────────── */

/* Reveal tier from OBSERVE proficiency vs a creature's scan_diff:
 *   1 = basic  (name + disposition) — always achievable
 *   2 = full   (+ element / movement), needs observe >= scan_diff
 *   3 = deep   (+ aptitude),          needs observe >= scan_diff + 15
 * Depth is earned by growing OBSERVE (per spec: "deeper insight over time"). */
int creature_scan_tier(uint8_t observe, uint8_t scan_diff);

/* Turns a scan of this difficulty costs (the world ticks each — the target
 * may flee mid-scan). Harder reads take longer. */
int creature_scan_cost(uint8_t scan_diff);

/* Family bestiary grade, 2 bits/family packed in a uint16_t:
 * 0 unseen, 1 seen, 2 studied, 3 mastered (family-level — any rat advances
 * "rat"; traits shade the read). */
int creature_bestiary_grade(uint16_t bestiary, uint8_t family_id);
uint16_t creature_bestiary_set(uint16_t bestiary, uint8_t family_id, uint8_t grade);

/* Short display vocabulary for the scan reveal + bestiary screen. */
const char* creature_disposition_name(uint8_t disposition);
const char* creature_element_name(uint8_t element);
const char* creature_aptitude_name(uint8_t aptitude);
