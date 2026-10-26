/* arc.c — see arc.h. */
#include "arc.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "biome.h"
#include "recipes.h"
#include "site.h"

/* loot.c ids of the artifacts, by SiteKind. */
static const uint8_t ARTIFACT_KIND[SITE_KIND_COUNT] = {
    [SITE_GRAVE] = 7, [SITE_TOMB] = 8, [SITE_ALTAR] = 9, [SITE_STONE] = 10,
};

uint8_t arc_artifact_kind(uint8_t site_kind) {
    return site_kind < SITE_KIND_COUNT ? ARTIFACT_KIND[site_kind] : 0xFFu;
}

const void* arc_entry_at(const World* w, int x, int y, uint8_t* what, uint8_t* arg) {
    for(int i = 0; i < w->arc_count; i++)
        if(w->arc[i].x == x && w->arc[i].y == y) {
            if(what) *what = w->arc[i].what;
            if(arg) *arg = w->arc[i].arg;
            return &w->arc[i];
        }
    return NULL;
}

const char* arc_pickup(const World* w, int x, int y, CharacterState* c) {
    uint8_t what, arg;
    if(!arc_entry_at(w, x, y, &what, &arg)) return NULL;
    if(what == ARC_SOURCE) {
        c->words_known |= (uint8_t)SITE_BIT(arg);
        return ARC_LINE_READ;
    }
    if(what == ARC_MADE_TOME) {
        c->recipes_known |= RECIPE_BIT(ARC_RECIPE_WARD);
        return ARC_LINE_READ;
    }
    return NULL;
}

void arc_step(uint32_t seed, int cx, int cy, const World* w, int x, int y, uint8_t sight,
              RegionBook* book, ArcStep* out) {
    memset(out, 0, sizeof(*out));
    uint8_t what, arg;
    if(w->tiles[y][x] != TILE_CARVING || !arc_entry_at(w, x, y, &what, &arg)) return;
    int rx = region_of(cx), ry = region_of(cy);
    if(what == ARC_PIECE) {
        RegionRecord* r = region_book_touch(book, rx, ry);
        if(r) r->pieces |= (uint8_t)(1u << arg);
        out->line = ARC_LINE_CARVED;
        return;
    }
    if(what != ARC_CLUE) return;
    /* Whoever may take the seen way can read its clues: the way's own
     * threshold decides both (spec 58 §58.7.2). */
    RegionRite rite;
    region_rite(seed, rx, ry, &rite);
    if(sight < rite.threshold[WAY_SEEN]) {
        out->line = ARC_LINE_WORN;
        return;
    }
    RunePuzzle p;
    rune_puzzle(seed, rx, ry, &p);
    out->line = ARC_LINE_RUNE;
    out->rune = true;
    rune_icon(p.shape[arg], p.turn[arg], out->icon);
    if(p.kind != PUZZLE_TURN)
        for(int k = 0; k < p.count; k++)
            if(p.order[k] == arg) out->marks = (uint8_t)(k + 1);
}

int arc_site_at(uint32_t seed, int cx, int cy, const World* w, int x, int y) {
    if(w->site_kind == SITE_NONE || w->site_x != x || w->site_y != y) return -1;
    return chunk_site_index(seed, cx, cy);
}

bool arc_site_sealed(const RegionBook* book, int rx, int ry, int k) {
    const RegionRecord* r = region_book_get(book, rx, ry);
    return r && k >= 0 && (r->sealed & (1u << k));
}

bool arc_region_cleansed(uint32_t seed, int rx, int ry, const RegionBook* book) {
    const RegionRecord* r = region_book_get(book, rx, ry);
    if(!r) return false;
    if(r->destroyed >= corruption_dead_count(seed, rx, ry)) return true;
    RegionSite sites[SITES_PER_REGION_MAX];
    int n = region_sites(seed, rx, ry, sites);
    for(int k = 0; k < n; k++)
        if(!(r->sealed & (1u << k))) return false;
    return n > 0;
}

ArcSealResult arc_seal(int rx, int ry, int k, uint8_t kind, CharacterState* c, RegionBook* book) {
    if(arc_site_sealed(book, rx, ry, k)) return ARC_ALREADY;
    if(!(c->words_known & SITE_BIT(kind))) return ARC_NEED_WORDS;
    uint8_t art = arc_artifact_kind(kind);
    if(art >= SAVE_INV_KINDS_MAX || c->inv_qty[art] == 0) return ARC_NEED_ARTIFACT;
    RegionRecord* r = region_book_touch(book, rx, ry);
    if(!r) return ARC_BOOK_FULL;
    c->inv_qty[art]--;
    r->sealed |= (uint8_t)(1u << k);
    r->flags |= RR_FOUND;
    return ARC_SEALED;
}

const char* arc_seal_line(ArcSealResult r) {
    switch(r) {
    case ARC_SEALED:        return ARC_LINE_SEAL;
    case ARC_ALREADY:       return ARC_LINE_SEALED;
    case ARC_NEED_WORDS:    return ARC_LINE_NO_WORDS;
    case ARC_NEED_ARTIFACT: return ARC_LINE_NO_ARTIFACT;
    default:                return ARC_LINE_NO_ARTIFACT;
    }
}

uint8_t arc_ways_open(uint32_t seed, int rx, int ry, const uint8_t* axes) {
    RegionRite rite;
    region_rite(seed, rx, ry, &rite);
    uint8_t open = 0;
    for(int w = 0; w < WAY_COUNT; w++)
        if((rite.ways & WAY_BIT(w)) && ritual_way_axis((RitualWay)w, axes) >= rite.threshold[w])
            open |= WAY_BIT(w);
    return open;
}

bool arc_way_ready(uint32_t seed, int rx, int ry, RitualWay way, const CharacterState* c,
                   const RegionBook* book) {
    RegionRite rite;
    region_rite(seed, rx, ry, &rite);
    switch(way) {
    case WAY_SPOKEN: {
        const RegionRecord* r = region_book_get(book, rx, ry);
        uint8_t all = (uint8_t)((1u << rite.pieces) - 1u);
        return r && (r->pieces & all) == all;
    }
    case WAY_MADE: return c->inv_qty[ARC_KIND_WARD] > 0;
    case WAY_KEPT:
        return c->inv_qty[ARC_KIND_CANDLE] > 0 && c->inv_qty[ARC_KIND_SALT] > 0 &&
               c->inv_qty[ARC_KIND_RELIC] > 0;
    case WAY_SEEN: return true;   /* the clues help; the runes are always there */
    default: return false;
    }
}

void arc_way_spend(RitualWay way, CharacterState* c) {
    if(way == WAY_MADE) {
        if(c->inv_qty[ARC_KIND_WARD]) c->inv_qty[ARC_KIND_WARD]--;
    } else if(way == WAY_KEPT) {
        if(c->inv_qty[ARC_KIND_CANDLE]) c->inv_qty[ARC_KIND_CANDLE]--;
        if(c->inv_qty[ARC_KIND_SALT]) c->inv_qty[ARC_KIND_SALT]--;
        if(c->inv_qty[ARC_KIND_RELIC]) c->inv_qty[ARC_KIND_RELIC]--;
    }
}

const char* arc_way_name(RitualWay way) {
    switch(way) {
    case WAY_SPOKEN: return "say the words";
    case WAY_MADE:   return "set the ward";
    case WAY_KEPT:   return "keep a vigil";
    case WAY_SEEN:   return "turn the runes";
    default:         return "?";
    }
}

/* ── the ledger (§58.8) ───────────────────────────────────────────── */

#define LEDGER_HEAD_ROWS   2   /* the heading, the incantations */
#define LEDGER_REGION_ROWS 4   /* heading, sealed, destroyed, standing */

static bool ledger_listed(const RegionRecord* r) {
    return (r->flags & RR_FOUND) || r->sealed || r->destroyed;
}

int arc_ledger_rows(const RegionBook* book) {
    int n = 0;
    for(int i = 0; i < book->count; i++) n += ledger_listed(&book->rec[i]);
    return LEDGER_HEAD_ROWS + n * LEDGER_REGION_ROWS;
}

static int bits8(uint8_t v) {
    int n = 0;
    for(; v; v &= (uint8_t)(v - 1)) n++;
    return n;
}

bool arc_ledger_line(uint32_t seed, const RegionBook* book, uint8_t words_known, int row,
                     char* out, size_t cap) {
    if(row < 0 || row >= arc_ledger_rows(book) || cap < 2) return false;
    if(row == 0) { snprintf(out, cap, "-- ledger --"); return true; }                 /* DRAFT */
    if(row == 1) { snprintf(out, cap, "incantations  %d", bits8(words_known)); return true; }
    int j = (row - LEDGER_HEAD_ROWS) / LEDGER_REGION_ROWS;
    int line = (row - LEDGER_HEAD_ROWS) % LEDGER_REGION_ROWS;
    const RegionRecord* r = NULL;
    for(int i = 0, seen = 0; i < book->count; i++)
        if(ledger_listed(&book->rec[i]) && seen++ == j) { r = &book->rec[i]; break; }
    if(!r) return false;
    switch(line) {
    case 0: snprintf(out, cap, "ground %d", j + 1); break;                              /* DRAFT */
    case 1: snprintf(out, cap, "sites sealed  %d/%d", bits8(r->sealed),
                     region_site_count(seed, r->rx, r->ry)); break;
    case 2: snprintf(out, cap, "dead destroyed %d", r->destroyed); break;
    default: {
        const char* st = arc_region_cleansed(seed, r->rx, r->ry, book) ? "cleansed"
                       : (r->sealed || r->destroyed)                  ? "held"
                                                                       : "rising";
        snprintf(out, cap, "corruption  %s", st);
        break;
    }
    }
    return true;
}
