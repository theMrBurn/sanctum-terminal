/*
 * narrative.h — PO-driven narrative layer (spec 49 §C + §L + §R, v1).
 *
 * The producer (permanent-objects) hasn't shipped its exporter yet, so this
 * v1 bundles the mock entries from spec 49 §C directly as `static const`
 * data in narrative.c. When the real packet loader lands (slice 49.D*),
 * the consumer side (eligibility filter, template engine, anchor binding,
 * substitution) keeps working unchanged — the data swap is transparent.
 *
 * Pure module: no Flipper SDK deps. Integer-deterministic per spec 43 §14.0.
 *
 * Theme bit ordering follows spec 49 §I.1.3 (the binding wire-format
 * ordering), NOT §L.0.1 — see the §C "Note on theme bits".
 */

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "deeds.h"

/* Theme bits — spec 49 §I.1.3. The first 6 mirror spec 48's axes so
 * quest resolutions feed deeds naturally; bits 6-15 are world flavor. */
#define THEME_BODY    (1u <<  0)
#define THEME_MIND    (1u <<  1)
#define THEME_HEART   (1u <<  2)
#define THEME_CRAFT   (1u <<  3)
#define THEME_SIGHT   (1u <<  4)
#define THEME_WILL    (1u <<  5)
#define THEME_HOME    (1u <<  6)
#define THEME_FIELD   (1u <<  7)
#define THEME_KIN     (1u <<  8)
#define THEME_BOND    (1u <<  9)
#define THEME_TOOL    (1u << 10)
#define THEME_ART     (1u << 11)
#define THEME_RISK    (1u << 12)
#define THEME_RITUAL  (1u << 13)
#define THEME_LOSS    (1u << 14)
#define THEME_OTHER   (1u << 15)

typedef struct {
    const char* id;        /* "po-001" */
    const char* lemma;     /* "kitchen-shelf" — substituted via %lemma% */
    const char* subject;   /* substituted via %subject% (may be NULL) */
    const char* place;     /* substituted via %place% (may be NULL) */
    const char* people;    /* RELATION not name; via %people% (may be NULL) */
    uint16_t theme_mask;
    uint8_t severity;      /* 1..5 */
} PoEntry;

typedef struct {
    uint8_t id;
    uint16_t theme_match;      /* entry must have AT LEAST ONE matching bit */
    uint8_t min_severity;
    /* Display strings — %lemma%, %subject%, %place%, %people% substitute
     * at runtime via narrative_substitute. Each ≤ 120 chars to fit 128px. */
    const char* intro;
    const char* branch_a_label;
    const char* branch_b_label;
    const char* resolution_a;
    const char* resolution_b;
    DeedEvent branch_a_deed;   /* axis-feed via spec 48 deeds catalog */
    DeedEvent branch_b_deed;
} QuestTemplate;

extern const PoEntry      MOCK_PO_ENTRIES[];
extern const int          MOCK_PO_ENTRY_COUNT;
extern const QuestTemplate QUEST_TEMPLATES[];
extern const int           QUEST_TEMPLATE_COUNT;

/* Deterministic anchor binding (spec 49 §R.2). Same campaign + entry →
 * same chunk_xy under that campaign. Range ±8 chunks each axis (§R.5 v1 cut). */
void narrative_anchor(uint32_t campaign_seed, uint8_t entry_id,
                      int8_t* chunk_x_out, int8_t* chunk_y_out);

/* Eligibility check (spec 49 §L.1, slot-completeness deferred for mock).
 * Returns true if the entry-template pair matches. Pure integer logic. */
bool narrative_eligible(const PoEntry* entry, const QuestTemplate* tpl);

/* Mad-lib substitution. Walks `tpl_str`, copies fixed text into `out`,
 * expands %lemma% / %subject% / %place% / %people% via the entry's slots.
 * Out buffer is null-terminated and bounded to `cap`. Truncates safely
 * (no overflow); unknown placeholders pass through verbatim. Pure. */
void narrative_substitute(char* out, size_t cap, const char* tpl_str,
                          const PoEntry* entry);

/* Look up an eligible (entry × template) pair for a given chunk, skipping
 * already-resolved entries. Returns true on hit and writes the entry +
 * template indices via out-params. Deterministic per (campaign_seed,
 * chunk_x, chunk_y). v1: takes a `resolved_mask` (uint32 bit-per-entry). */
bool narrative_pick_for_chunk(uint32_t campaign_seed, int chunk_x, int chunk_y,
                              uint32_t resolved_mask,
                              uint8_t* entry_out, uint8_t* template_out);

/* Slice 50.F4 — Pool-biased variant. When multiple templates are eligible
 * for the matched entry, prefers templates whose entry theme_mask aligns
 * with the Pool's foreground themes (weight ≥ THEME_FOREGROUND_THRESHOLD).
 * Score = template.min_severity * 4 + popcount(entry.themes & foreground) * 2.
 * Falls back to base behavior when pool == NULL. Per spec 50 §4.4. */
#include "pool.h"
bool narrative_pick_for_chunk_pooled(
    uint32_t campaign_seed, int chunk_x, int chunk_y,
    uint32_t resolved_mask, const Pool* pool,
    uint8_t* entry_out, uint8_t* template_out);
