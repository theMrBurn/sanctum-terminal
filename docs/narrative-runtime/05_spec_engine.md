# Spec — narrative-mechanics runtime (engine)

**Status:** DRAFT 2026-07-02. Design only; propose→ratify (workspace protocol §0)
— a human-authored commit ratifies this into doctrine. Implementation follows the
build order in §8. §5 (Reckoning), §3.7 (trade/ledger), and §2.1 (session-open
baseline) are filled; the four Reckoning tuning calls are settled (§7).
**Companions:** [`README`](README.md), [`01_engine_audit`](01_engine_audit.md),
[`02_goal_shapes_and_cards`](02_goal_shapes_and_cards.md),
[`03_session_flow`](03_session_flow.md), [`04_flow_seamcheck`](04_flow_seamcheck.md);
`design_character_sheet`; `deeds.h`; `core/systems/reflective/state_machine.py`;
`core/systems/consequences/`; `sanctum-engage/tests/conformance/` (spec 53).

## Premise

Rebuild the Sanctum Terminal **game** as a **story-agnostic narrative-mechanics
runtime** — fully playable in text, visuals added later as illustrations of beats.
The Flipper RPG is the proven baseline; we reuse-and-simplify existing logic across
both codebases rather than rewrite. **The rules engine is the product; text is the
cheapest window onto it.**

The runtime is **one machine wearing different weather**: a 4-state FSM over one
predicate-gated beat engine, driven by one atomic event (the deed). Goal-shapes,
modifier-cards, the prologue, and the Reckoning are all *data* on that spine.

## 0. The hard law

State changes, never binary if/then. **No dead ends — only loops that close and
transition state, on _both_ success and failure.** Failure is a doorway, never GAME
OVER. Every stage names a real next stage on both branches; a shortfall is a
reframed question (the write-back spine), not a loss.

## 1. The I/O contract — the renderer-agnostic boundary

The engine speaks **intents in, beat-events out**. It never touches pixels.

- **Intent** — a structured player choice (a verb + target), not a keystroke. One
  grammar at every scale (`DialPrompt`: a framed question + N options + commit).
  Micro: a beat is a question. Macro: a session is framed by questions.
- **Beat-event** — a structured event the engine emits (a `StateEvent` with a
  register hint). Text is the *first* renderer of these; a visual renderer is later
  just another consumer of the same stream.

### Two text classes (the verbatim-passthrough rule)

| Class | Source | Rule |
|---|---|---|
| **User-authored** | notes, dates, reminders, alerts, PObject entries | Stored and *used* as-is; the engine may key logic/routing off it but **never alters it**. When surfaced back to a user it is rendered **verbatim** — never interpreted, summarized, re-enumerated, or rephrased. |
| **Engine-generated** | beat narration, system flavor | Templated / seed-driven prose. No verbatim constraint. No runtime LLM. |

This is workspace-protocol §2 user-sovereignty applied to runtime output, and it
resolves the audit's template-vs-verbatim conflict per-class. (`narrative.c` already
does the hybrid: user terms dropped verbatim into a template frame via `%slot%`; the
stronger guarantee is that content served back *as itself* — a reminder, an alert —
is whole-verbatim.)

## 2. The state machine — 4 states + transient brackets

Extends `core/systems/game_state.py`. **Four states, hub-and-spoke; no state per
goal-shape, card, or phase.**

```
CHARACTER_CREATION  ⇄  HUB  ⇄  ENGAGEMENT
                       HUB  ⇄  REFLECTIVE
```

- **HUB** is the only hub; ENGAGEMENT / REFLECTIVE are spokes that always close back
  to HUB. All routing obeys `_ALLOWED_TRANSITIONS` — **no spoke-to-spoke edges**
  (defeat is `ENGAGEMENT → HUB → REFLECTIVE`).
- **Transient brackets / phases** ride on `world.session_frame` and live
  `ConsequenceInstance`s, *not* new states: Session-Open/Close, Consolidation, the
  Fall's grace-counter, and **the Reckoning** (rides REFLECTIVE).

The canonical 12-stage flow is `03_session_flow.md`; this spec formalizes its
contracts and does not restate it.

### 2.1 Session-open baseline check (the "Voight-Kampff")

Session-open is not just goal-shape selection; it is a **daily baseline / alignment
check**. The instrument re-establishes your baseline, **diagnoses drift** (reads your
tension/blob and reflects it back — the honest mirror performed as a *greeting*), and
runs a **passive system check** (real date, time-of-day, gap since last engagement). The
specific questions are *scripted content*; the engine must carry the hooks:

1. Session-open **reads drift state** (`T`, blob, `to_reckoning`).
2. A **passive system check** — real clock → date / time-of-day / `last_engagement_at`.
3. **Ask + record** via `DialPrompt`; the user's answer is stored **verbatim** (their
   stated reality is canonical; the machine clock is only a cross-check).
4. A **scriptable, data-driven baseline-ritual slot** (content, not engine code).

**Determinism boundary:** the passive clock (date / time / Δ-since-engagement) is an
**ambient *presentation* input, never a truth-path value** (it cannot feed byte-equal
state or trade). A *confirmed* answer is recorded as an **input event** → truth.
**Tone (→ cultural-eccentric):** it must read as *you calibrating your own instrument*, a
greeting — never an interrogation you can fail. The system never judges; it reflects.

## 3. Core data model

Concrete schemas. All truth-path numbers are **integers** (see §6).

### 3.1 The deed (the atomic event — one deed, three readers)

Port of `deeds.h`. Append-only, never edited; per-session caps (RAM-only anti-grind).

```
Deed {
  event_id:   int      # fixed enumeration (DEED_STRIKE, DEED_SCAN_TIER1, DEED_QUEST_TEND, ...)
  axis:       int      # 0..5  BODY/CRAFT/SIGHT/MIND/HEART/WILL
  delta:      int      # signed axis growth
  at:         int      # logical tick (turn-clock), not wall time
  cap_group:  int      # which per-session cap this counts against
}
```
`effective_axis[X] = base.axes[X] + Σ deeds.delta[X]` (rolled up by replay).
**Three readers** consume each committed deed: (a) axis-growth (always), (b) the
active goal-shape accumulator if `theme_mask` overlaps, (c) the identity-tension
accumulator if the act runs against the alignment blob (§5).

### 3.2 The beat engine (one substrate)

Port of `core/systems/consequences/`. Quests, expeditions, dialogs, the 9
goal-shapes, the 8 cards, the prologue, and the Reckoning are all rows on this.

```
ConsequenceInstance {
  id:               str
  trigger:          Predicate     # when this beat may surface
  resolution:       Predicate     # when it resolves (accumulator≥threshold | HP=0 | lock | drain==0)
  effects:          Effect[]      # mutate flags / heal / grant deed / chain next beat / draw card
  context:          dict          # story DATA (the swappable part)
  progress:         AccumState    # §4
}
```

### 3.3 Goal-shape & modifier-card rows (data, not code)

```
GoalShape  { id, accumulator_pattern, theme_mask, threshold|chain|K|drain|quorum, po_source_ref }
ModifierCard { id, draw_trigger, operator, target:("tier1"|"tier2"|"verb_cap"), persists:bool }
```
`accumulator_pattern` ∈ { single-threshold, fixed-chain, open-vow-track, K-lock,
drain-to-zero, quorum-of-N, drift-to-graduation, turn-countdown }. See
`02_goal_shapes_and_cards.md` for the catalogue (9 shapes, 8 cards).

### 3.4 The character sheet (one canonical sheet)

Collapses Terminal's two stat systems (`PlayerState` d20-saves + `CharacterSheet` 6
stats) into one. **Stat vocabulary = BODY/CRAFT/SIGHT/MIND/HEART/WILL** (remap the
D&D-named presets in `character_classes.py`).

```
CharacterSheet {
  name:          str          # user-authored → verbatim
  birthday:      (int,int)
  age:           int          # ticks at each birthday; level = age ("Cairn canonical")
  class_history: ClassEntry[] # life-stages (data), NOT a creation menu — single "You"
  axes:          int[6]       # BODY/CRAFT/SIGHT/MIND/HEART/WILL (base; deeds add on top)
  abilities:     Ability[]    # ≤3 cap; earned, aggregated across class_history
}
```
Growth = **both layers** (decision #2): micro deeds (dominant, tuned) + macro
level=age/prestige (light, data-driven). The Reckoning is the choice-driven override
on the age-default life-stage (§5).

### 3.5 Truth: input-log + delta overlay

Port `deltas.c` to Python. World = `base_seed`-procgen + applied delta overlay
(idempotent), state derived by **replay** of the append-only log. Cross-session marks
(Scar, Bond, Carried Thing, identity shift, honest adjustments) are **input events
replayed as overlays — never seed mutation, never per-chunk storage** (chunks stay
pure functions of `base_seed, cx, cy`).

### 3.6 The PObject source contract (cross-repo boundary)

`PoEntry` originates in `permanent-objects` (separate repo). Define and **version**
the boundary; the runtime reads PO history first and **falls back to generic seed if
offline**. Shape (per `narrative.c`):

```
PoEntry { id, lemma, subject, place?, people?, theme_mask, severity }
```

### 3.7 The seed-ledger & trade (EXCHANGE)

**The seed *is* the Cairn *is* the life** — a seed-rooted, addressable tree. Seed `ABX`;
everything done with/to/for it is a path under it: `ABX.object123.<var>…`. Every object,
artifact, skill/technique, story, even a colour has a deterministic address.

- **Data is the currency.** A trade transfers an **address (+ provenance)**, not a data
  blob — the recipient's engine **deterministically expands** the address (the
  content-VM / seed-language) to the *identical* artifact. This is *why* decision #1
  (byte-equal on the truth path) is load-bearing: an address must reproduce
  byte-identically for the person you trade it to, or the economy breaks.
- **The ledger** is append-only, addressable, ownership-by-entry, transfer-as-event,
  tamper-evident-by-hash. "Blockchain" is the **mental model only** — *not* an internet
  crypto chain: self-hosted, deterministic, peer-to-peer. A trade is a **consented merge**
  of one ledger branch into another's input-log, and therefore rides the **consent/egress
  border** (workspace protocol §5) and the friend-tier framework (who you may trade with).
- **EXCHANGE = engagement + ledger — no new subsystem.** Appraise / diagnose is
  **scan / understand** (SIGHT/MIND) pointed at goods; negotiate / charm is
  **parley / stance** (HEART/WILL/MIND) pointed at a person. A barter is a
  comprehension-accumulator **engagement (§4)**; the ledger records the resulting transfer.
  Everything is offerable; **trade-mastery is earned** (a novice gets fleeced), and the
  honest mirror holds by tension (buy the sword, not the swordsmanship — §5.7). EXCHANGE is
  thus a **core, skill-gated context**, not the optional gold-shop of the earlier draft.
- **Provenance = the same problem as PO-minting integrity** (§5.7 / stress-test C1),
  solved by the same append-only addressable ledger.

*A dedicated formalization pass (addressing scheme, the content-VM expansion contract,
transfer/provenance, the tradeable/non-tradeable boundary, consent-border wiring) is
flagged in §10.*

## 4. The accumulator — one primitive, three tiers

One bounded `net_passes`-to-threshold primitive, parameterized:

- **Tier 1 — beat comprehension.** Resolves one beat. fight / understand / parley /
  study all add; flee adds partial. Damage is one axis among several. Integer d20
  resolver (`encounter_resolver.py`), injectable RNG → **integer** in conformance.
- **Tier 2 — session goal-shape.** The shape *is* which accumulator pattern wraps the
  tier-1 successes (§3.3).
- **Tier 3 — cross-session identity tension → the Reckoning** (§5).

**N-parallel routing (open extension).** Standing Question and Converging Threads run
2–4 live tier-2 accumulators; the deed must fan out to N by `theme_mask` overlap, plus
the cross-pollination draw on abandonment. This is a real extension of "one deed,
three readers," flagged for the redline (§10).

## 5. The Reckoning + the honest mirror

Full formalization: [`06_reckoning_formalization.md`](06_reckoning_formalization.md);
adversarial verification: [`07_reckoning_stresstest.md`](07_reckoning_stresstest.md).
This section is the buildable summary + the settled decisions.

### 5.1 The blob (two integer vectors)

Identity is `P[6]` (**position** — *who you are*, the lifetime `deeds.delta` rollup,
inertial for free) and `T[6]` (**tension** — per-axis strain, accumulated here). No
separate trajectory vector, no snapshot. Born as your *claim* (the Becoming's pillar
lean), sculpted by deeds → young-elastic is emergent.

### 5.2 The against-profile metric (integer; the #1 unknown, resolved)

Read `P` **before** applying the deed's own growth:
```
pmean = (Σ P[a]) / 6                      # integer floor
raw_k = (pmean - P[k]) * delta            # signed: >0 into a dimple, <0 deepening a bulge
T[k]  = clamp(T[k] + raw_k, 0, T_AXIS_CAP)
```
Per-axis, not scalar — this is load-bearing: it gives **shift attribution for free**
(the top-`T` axes *are* the re-center direction) and closes the scalar dodge (one
in-character act can't launder a session of drift). Worked example in `06`.

### 5.3 Rigidity & firing

```
R         = K_AGE*age*age + K_CONS*spread(P)     # spread = integer (max-min), NOT median
THRESHOLD = T_BASE + R
fired?    = (Σ T[a]) >= THRESHOLD                 # checked ONLY at a Consolidation boundary
```
The `age²` term is the rarity engine (acts-to-fire grows ~linearly with a life →
genuinely rarer with age; discharge ∝ `age²` → "snaps harder"). An explicit
`ReckoningEvent` drains `T` to a residue at its own log position (no instant re-fire).

### 5.4 The shift (stack, not replace)

Re-center `B̂` toward the top-`T` axes; append a `ClassEntry` to `class_history` that
**persists** — abilities **accrete** across chapters (the Cairn: every stone stays).
Presets are **thematic starting-bias only, never power-tiered** (stats come from deeds,
decision #2) — so there is nothing to respec *into*; the exploit has no surface. The
3-ability cap bounds the active loadout while breadth accretes.

### 5.5 Refusal (an options-beat with teeth)

A Reckoning is **choice-driven** — refusal is a valid stance, not a dead end, but it
has real cost: **tension residue persists** (Reckoned again soon), **rigidity hardens**
(more brittle), and a standing **dissonance = the deck's Scar** (surfaces beats until
healed). Heavy enough that reconsidering is rational. Loop-closes to HUB. **This
requires building a player-facing abort** (`apply_reckoning_refusal → exit() → HUB`) —
the reflective FSM has no such operation today (stress-test B1).

### 5.6 Decay & settling

Tension decay is **slow** (a one-off slip heals; a *pattern* outpaces decay). Post-fire
**settling ≥ one logical (in-game) day, scaled by the discharge magnitude** (extravagant
→ longer). Logical time only on the truth path (byte-equal). A **real-time "let it
breathe" layer** — the game declines to surface the next heavy beat until a real day has
passed — is permitted purely on the *presentation* side (see §5.8).

### 5.7 The honest mirror (same machinery)

- **Derive-don't-set** — there is **no `set_stat` anywhere**; a stat-slider is
  *unrepresentable* (no event carries an output number; the sheet is `replay(log)`).
- **Lying is the same metric** — a claim (re-doing the Becoming) that outruns your deeds
  is against-profile → tension → an unearned, unenjoyable Reckoning. The game **never
  judges, only leans** — no warnings, no "are you sure." Hollowness teaches.
- **You can't farm real life** — add `DEED_PO_COMPLETE` (**uncapped, one-shot-per-id**);
  in-game deeds stay session-capped, so **real-world accomplishment via Permanent Objects
  is the only uncapped path**. Fail-soft to a *capped* local grant when the PO source is
  offline; PO-id minting integrity is a cross-repo contract (build-list, stress-test C1).
- **Trade doesn't break it** — you buy the sword, not the swordsmanship; an aspect of
  self acquired-not-earned isn't backed by `P` → tension (§5B).
- **Restart = abandoning a life** — a heavy visible `AbandonEvent`, fork a new
  `base_seed`, inherit nothing; deterrent is opportunity cost, not a guilt-prompt. Carry
  an **abandonment count** forward as a quiet meta-mark so the weight is *true* for a
  serial restarter (stress-test C2). No dark-pattern.

### 5.8 Visibility, teaching, tuning

- **Stats page** = a pure read over replay-derived state (`s` summon, no tick): shows
  `B̂` (asserted self) vs `D̂` (enacted self) vs effective, per-axis `T`, and the raw
  `to_reckoning` distance. Bare integers under an in-world frame ("the instrument reading
  itself"). Float permitted for *presentation only* (a bar-fill ratio).
- **Prologue teaching** — one sub-threshold "that wasn't like you" nudge (feel the spring
  wind once; cannot fire), then the first real fire self-reveals in one line (*"All this
  leaning has a name. This is a Reckoning. Few lives have many."*). Route the first
  Cairn-stone compose through the *actual* `reflective/magnets.py` primitive so the
  compose grammar is muscle-memory before The Fall.
- **Rarity target = 7 per lifetime** (a typical *drifting* life; a consistent life earns
  fewer or none). This is a **hard acceptance criterion**, bounded by the F1 reachability
  ceiling (`THRESHOLD(age_max) < drift_axis_count · T_AXIS_CAP`) so an elder can Reckon
  from *drift*, not only deck-feeders.
- **Late-life identity = lifetime `D̂`** (old deeds define you forever; the Reckoning is
  the *sole* sharp identity shift; reformation is an earned turning point, not a fade).

### 5B. Feeders & determinism notes

Deck feeders add integer impulses at the same Consolidation boundary (`config/reckoning.json`,
data-driven): Scar / Carried-Thing-severity / Dread-Tower-fall. Because a bare scalar feeder
can't *aim* the shift, a feeder-only fire must **deposit directionally or fall back to no
class-change** — never re-center on an all-zero `T` (stress-test F2). Quantization noise from
integer-capped deeds is killed with a **deadband ε** on `|D̂−B̂|` (F3). Selection (the Reckoning
beat variant / magnet pool) must use **`idx = fnv(line_id,i) % len(sorted(pool))`, not seeded
Mersenne-Twister** — FNV-seeding `random.Random` does *not* buy C↔Python byte-equality
(stress-test L1). The `cluster → life-stage` table must be **total before ship, or the override
fails closed** (drain + no class change) — never the silent fallback-to-rogue (stress-test,
graceful-degradation).

## 6. Determinism & No-LLM conformance

- **Byte-equal is HARD on the truth/chronicle path** (decision #1): the tension
  metric, accumulators, deeds, selection/relevance, and goal progress are
  state-deriving → **integer-FNV, no float**, golden-vector gated (spec 53 harness in
  `sanctum-engage/tests/conformance/`, currently covers `rng`+`pool` only — extend up
  the stack). **Float is fine only on pure presentation** (layout, ambient tint).
- **Float-RNG ports required** (truth path): `quests/rewards.py`,
  `reflective/magnets.py`, the `worth_knowing > 0.45` resonance gate in
  `encounter_engine.py`, and the resolver injectable. (~9 truth-path files use
  `random`; the rest are spatial/render and out of scope.)
- **Selection = primitive, not seeded RNG.** Replace Mersenne-Twister `sample`/`choice`
  with `idx = fnv(line_id,i) % len(sorted(pool))` — seeding `random.Random` does *not* buy
  C↔Python parity (§5B, build #4).
- **Trade demands it end-to-end.** A traded address must expand **byte-identically** on a
  peer, so the seed-ledger + content-VM sit on the truth path (§3.7). This is the second
  reason decision #1 is non-negotiable (the first being merge).
- **Passive clock is presentation-only.** Real date / time-of-day / Δ-since-engagement
  never touch the truth path; only *confirmed* answers become input events (§2.1).
- **No runtime LLM.** Prose is templated / verbatim / seed-driven. Sanctioned NLP
  (lexicon) is curation-time only.

## 7. Locked decisions (record)

| # | Decision | |
|---|---|---|
| 1 | **Byte-equal** | Hard on the truth/chronicle path; free on presentation. Keeps cross-device merge + **trade** alive. |
| 2 | **Growth cadence** | Both layers from day one. Guardrails: deeds dominant + macro light; macro data-driven (no baked-in personal template); structural-now/tuned-later; rigidity is a clean graceful-degrade contract. |
| 3 | **Protagonist** | Single persistent "You". Classes = life-stages (data); class-as-creation-mode is an optional later toggle. The Reckoning is the choice-driven override on the age-default. |
| 4 | **Reckoning rarity** | **7 per lifetime** (a typical *drifting* life; consistent lives fewer/none). Hard AC, bounded by the F1 reachability ceiling. |
| 5 | **Late-life identity** | **Lifetime `D̂`** — old deeds define you forever; the Reckoning is the *sole* sharp identity shift; reformation is an earned turning point. |
| 6 | **Decay & refusal** | Slow decay; post-fire settling ≥ a *logical* day scaled by discharge magnitude; **refusal = an options-beat with teeth** (residue + rigidity-harden + a Scar). Optional real-time "breathe" layer, presentation-side only. |
| 7 | **Reckoning shift** | **Stack, not replace** (chapters accrete, abilities aggregate — the Cairn); presets thematic, **not power-tiered** — kills the respec exploit. |
| 8 | **Trade / economy** | Everything offerable; **skill-gated**; honest-by-tension. **EXCHANGE = engagement + ledger.** The seed is the data *and* the currency (addressable seed-ledger, P2P consented merge). Core, not optional. |
| 9 | **Session-open** | A daily **baseline / drift-diagnostic** check ("Voight-Kampff"). Passive clock = presentation-only; confirmed answers = truth. Never an interrogation-you-can-fail. |

Earlier locks (from the dossier): beat-graph world over spatial-as-data;
comprehension accumulator; always-grant axis reward + optional loot; one consequence
beat-engine + deeds; verbatim passthrough; honest mirror.

## 8. Build order (sequenced, with acceptance criteria)

Dependency-ordered from the seam-check. Each item is a buildable unit with AC.

1. **Stat-vocab collapse** — one 6-axis `CharacterSheet`; remap D&D presets; reconcile
   `PlayerState`/`CharacterSheet`. *AC:* one sheet is the single source of truth for
   "how you acted → which axis grew"; resolver + deeds + goal-shapes read it.
2. **Persistence/overlay port** — `deltas.c` model in Python (input-log replay + delta
   overlay). *AC:* a tile mutation + a deed survive restart and LRU eviction; state is
   re-derived by replay; no seed mutation.
3. **Beat-layer reachability** — port `carve_egress` to the beat graph. *AC:* every
   seeded beat is provably reachable from current state, or a connecting beat is
   carved; no silent dead end. **Gate for any chaining shape.**
4. **Determinism gates** — port the §6 float sites to integer-FNV; **replace the
   selection *primitive*** (`idx = fnv(line_id,i) % len(sorted(pool))`, *not* seeded
   Mersenne-Twister — L1); integer spread not median (L2); derive any regen seed from the
   chronicle (L3). Extend the golden-vector harness up the stack. *AC:* C↔Python
   byte-equal on rng/pool + deeds + tier-1/2/3 accumulators; the discriminating vectors
   (four-case gate, `acts_to_fire(age)` monotonic, no instant re-fire after a Reckoning).
5. **Engine gaps** — wire abilities (`verb + target_save`) into the resolver;
   implement or **cut** `DEFEND`; build the bounded theme-vocabulary bridge. *AC:* no
   inert verb; the earned-ability loop fires; selection is byte-equal.
6. **The Reckoning + honest mirror** (§5) — includes: build the **refuse/abort operation**
   (`apply_reckoning_refusal → exit()→HUB`, B1); **serialize reflective entry** so a
   Reckoning defers rather than clobbers a live beat (B2); feeders deposit **directionally
   or fail closed** (F2); a **deadband ε** against quantization noise (F3); the
   `cluster→life-stage` table **total or fail-closed** (no silent rogue-fallback);
   `DEED_PO_COMPLETE` uncapped + fail-soft; the **abandonment meta-mark** (C2). *AC:*
   tension is integer + golden-gated; **7/lifetime and reachable from drift** (not
   feeder-only); refusal has teeth; no cheap reset path.
7. **Prologue teaching** — teach the reflective-compose grammar before The Fall needs
   it; give the Reckoning the sub-threshold nudge + one-line reveal. *AC:* every
   evocative name is earned by an act before it is spoken.
8. **Session-open baseline check** (§2.1) — drift-read + passive system check
   (presentation-side clock) + verbatim-confirm + a scriptable ritual slot. *AC:* the
   passive clock never touches the truth path; confirmed answers are logged as input events.
9. **Trade / EXCHANGE + the seed-ledger** (§3.7) — the addressable ledger, the content-VM
   expansion contract, engagement-driven barter, consent-border wiring. *AC:* an address
   expands **byte-identically** on a peer; a trade is a consented merge with intact
   provenance; nothing self-related is transferable without generating tension. *(Depends
   on #2 persistence + #4 determinism.)*
10. **The thin slice (Phase 3)** — one encounter + a little exploration, all text, on
    the real engine. *AC:* the user can *feel* it; the loop closes with no dead end.

## 9. Out-of-scope explicitly

- Visual rendering (raycaster / FOV-HUD / scenes) — a *later* renderer on the same
  beat stream. The 3D layer (`geometry.py`, `frame_composer.py`, `paper_doll.py`, …)
  stays on the shelf.
- The real-time ARPG substrate (`strike.py`, `ballistics.py`, volley) — parked.
- Market/economy — an optional spoke off HUB, off by default in v1.
- Making the Flipper run the *full* runtime — decision #1 keeps the door open; it is
  not a v1 target.

## 10. Open questions for redline

- **N-parallel accumulator routing** (§4) — confirm the fan-out + cross-pollination
  rule for Standing Question / Converging Threads.
- **Spec home** — keep the spec in `docs/narrative-runtime/` (this file) or also mint
  a flat `docs/spec_narrative_runtime.md` per the older convention?
- **Theme-vocabulary bridge** — the projection of the open learned lexicon onto the
  finite byte-equal vocabulary needs its own mini-design.
- **Cairn naming** — `character_sheet.py` already uses "Cairn" for level=age; the
  retrospective goal-shape is also "The Cairn." Unify (one lived-life canon) or split?
  → cultural-eccentric pass.
- **Seed-ledger / trade formalization** (§3.7) — a dedicated pass: the addressing scheme,
  the content-VM expansion contract, transfer/provenance, the tradeable-vs-non-tradeable
  boundary, and consent-border wiring. (The economy is now *core*, so this is scoped work,
  not a maybe.)
- **Session-open baseline ritual** (§2.1) — the actual scripted questions + the tone that
  keeps it a *greeting*, not an interrogation. → cultural-eccentric.

**Settled this session (no longer open):** the four Reckoning tuning calls — rarity
= 7/lifetime, late-life = lifetime `D̂`, decay/refusal, stack-not-replace (§5); the trade
model (§3.7); the session-open baseline (§2.1). **market-in-v1 is now CORE** (trade is a
core skill-gated context, not the off-by-default gold shop). Single-source write-back
= Permanent Objects, confirmed.
