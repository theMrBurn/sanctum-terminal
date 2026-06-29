# Sanctum Runtime — Goal-Shapes & Modifier-Card Deck

_Generated 2026-06-26 by the `goal-shape-brainstorm` workflow (4 lenses + synthesis). Companion to `sanctum_engine_AUDIT.md`._

**Frame:** each session opens with framing questions that pick a GOAL-SHAPE (the session's spine) and may draw MODIFIER-CARDS (modules layered on top). All items: story-agnostic, PO-sourced, loop-closing on BOTH success and failure. Determinism: every draw rides the existing `pool.c` bag-draw; cross-session persistence = append-only input events replayed as overlays (never seed mutation); no new RNG, no runtime LLM, byte-equal PC↔Flipper.

---
## GOAL-SHAPES (session spines)

### Single Goal
_One target beat; the loop runs until it is reached._

- **Fit:** The atomic spine — a session aimed at a single comprehension threshold. Story-agnostic (the target is whatever PO seeds it) and the baseline against which the other shapes define themselves.
- **Loop:** SUCCESS: threshold crossed → axis surge in the verb you carried it with, optional loot, and the resolved source re-seeds the next beat (write-back). FAILURE/EXPIRY: relevance/turn budget exhausts before the threshold → partial growth is booked and the unreached target is written back as one of next session's opening questions. No dead end — falling short is a reframed question.
- **PO hook:** The single target beat is seeded from one PO entry; completion re-engages and re-files it.

### Large Goal, Iterative Deterministic Steps
_One aim decomposed into a seed-derived fixed chain of sub-beats._

- **Fit:** Gives a session a deterministic arc without an authored plot — the chain is a pure function of the seed, byte-equal PC↔Flipper. Distinct from the emergent Vow: here the route is fixed in advance.
- **Loop:** SUCCESS: each sub-beat crossed advances the chain; final link pays a compound axis surge weighted by the verbs used along the way. FAILURE/EXPIRY: budget runs out mid-chain → completed links book their growth and the remaining links collapse into a single 'unfinished work' opener for the next session. The chain never hard-stops; it re-spools as tomorrow's question.
- **PO hook:** The decomposition is seeded from one PO entry; each sub-beat re-engages a facet of that source.

### Exploration
_No fixed target; relevance-gated wandering where discovery is the point._

- **Fit:** The spatial/open spine — embodies the Elite-'84 procgen DNA (depth from deterministic seed, not authored destination). Pairs with the contemplative 'a life, not a campaign' feel.
- **Loop:** SUCCESS: a relevance gate clears → the discovered locus pays SIGHT/MIND-leaning growth and seeds a richer adjacent beat. FAILURE/EXPIRY: budget ends with nothing found → the session books the ground covered as small growth and the most-approached-but-unreached thread becomes a 'something out there' opener. Wandering that finds nothing is still a step taken, never a dead end.
- **PO hook:** Relevance gates are weighted by PO sources in scope; entering their orbit surfaces the related entry.

### Timed Challenge
_A goal pursued under a turn-budget; the clock is the pressure._

- **Fit:** The one shape where the budget IS the spine (the Ember and Dread Tower only borrow pressure locally). A neutral, monotone countdown — distinct from the Dread Tower's escalation curve.
- **Loop:** SUCCESS: goal crossed before the clock → bonus WILL/BODY for holding under pressure, plus the goal's own axis. FAILURE/EXPIRY: clock hits zero with the goal unmet → this is NOT game over; partial growth is booked and the unreached goal is re-framed as next session's opening question (the deadline that passed becomes 'the thing you didn't get to'). The HARD DESIGN LAW holds: expiry is a doorway.
- **PO hook:** The goal under the clock is seeded from a PO entry with date/urgency weight (almanac or a journal stressor).

### The Vow (Sworn Track) *(new)*
_Swear a vow against a high-severity permanent object; an OPEN progress track that any thematically-relevant beat advances — resolvable by fulfilment, renewal, or honorable forswearing._

- **Fit:** Distinct from shapes 1 and 2: the route is emergent, not a fixed beat or chain. Any beat whose deed matches the vow's theme_mask marks the track (tick = popcount of overlapping theme bits), with track length derived from PoEntry.severity (1..5). Termination is a concrete integer check, never a vibe. Forswearing is a first-class rewarded exit — the cleanest expression of 'failure is a doorway.'
- **Loop:** SUCCESS: track fills and resolves over threshold → vow FULFILLED, pays the axis in its theme_mask; write-back may RENEW into a harder follow-up vow seeding the next session. FAILURE/EXPIRY: (a) track fills UNDER threshold → vow RENEWED at a re-scoped harder rank, severity bumped, carried; (b) player FORSWEARS before fill → pays WILL + HEART (the cost of letting go) and emits the PoEntry as a Burden seed for a future session. No game over.
- **PO hook:** The vow IS a single PoEntry; severity sets track length, theme_mask sets which beats mark it and which axis pays. Forswearing produces the write-back The Carried Thing consumes.

### The Cairn *(new)*
_(Renamed from the team's working title "The Reckoning" — that name is reserved for the identity-shift event. You build the cairn stone by stone: each integrated memory is a stone placed; the finished cairn is the drained-to-zero set, marking a life reviewed.)_

_A retrospective session: tend a finite working-set of held memories drawn from your own past, integrating or releasing each, until the set drains to zero._

- **Fit:** The backward-looking spine — the write-back spine turned into a whole frame. Reads PO journal/almanac history FIRST (so no cold-start even on session one), biased toward your dominant axes. Keeps the TYOV drain engine: an active set of N entries, each beat fills a slot (deepen) or forces a release, and the integer drain to zero guarantees a finite, byte-equal session. This is 'a life, not a campaign' made literal.
- **Loop:** SUCCESS: a memory whose slots all fill → INTEGRATED (kept), grants a permanent small bonus on its theme_mask axis, re-filed as treasured/resolved (resurfaces less often). FAILURE/EXPIRY: a memory crossed out → LOST, but loss is generative — it fires one grief/echo beat paying HEART+WILL and the entry is tagged 'lost-may-return' to resurface later; budget expiry books partial growth and unreconciled entries become next session's opening questions. Both outcomes drain the set toward a clean end.
- **PO hook:** The active set IS a subset of PO journal/almanac entries; slots map to re-engagements of one entry; the LOSS theme bit tags released memories. Canonical write-back loop.

### The Tending *(new)*
_A cyclic session spent keeping one living thing alive rather than reaching a target — sustain, don't arrive._

- **Fit:** The present-tense sustain spine. Distinct from Exploration (wanders spatially) and the Ritual idea it folds in: it stays put and repeats temporally around one touchstone PO while DRIFT (not arrival) is the payload. Each cycle re-asks the same touchstone questions; pressure is entropy, not a clock or enemy. Termination is concrete: the touchstone's accumulated drift crossing a fixed integer threshold 'graduates' the practice into a new touchstone. Affect is steady devotion, not deathbed vigil.
- **Loop:** SUCCESS: a cycle held → steady growth on the touchstone's axis (HEART/WILL), the source matures and re-seeds a richer beat, drift advances toward graduation. FAILURE/EXPIRY: a cycle broken or the thing left untended → it does not die, it goes FALLOW/dormant; this is itself a deed (pays WILL, or HEART if relational) and the dormant source seeds a future 'return to the fallow thing' beat. Both held and broken cycles advance drift; the practice transforms either way.
- **PO hook:** The touchstone IS one persistent PO entry (a recurring journal practice or an ongoing relation) re-engaged every cycle; RITUAL/HOME/BOND theme bits tag it; graduation = drift threshold on severity/theme_mask.

### The Standing Question *(new)*
_The session IS a question you can't yet answer; permanent objects are laid as a fixed spread of positions, each beat reads one, and the answer crystallizes when every position locks._

- **Fit:** The open/divinatory spine and the deepest expression of 'questions are the grammar at every scale' — it literally realizes the session-opening-questions frame. Distinct from the base accumulator (which gathers successes toward a fixed threshold): this gathers READINGS that change WHICH answer you commit to. Keeps a concrete integer end-state via a fixed K-position spread that locks position by position. Affect is curiosity, kept light, never solemn.
- **Loop:** SUCCESS: a position resolves to CLARITY → it LOCKS and pays the axis in its PoEntry's theme_mask; when the final position locks the framing question is answered and the composite seeds the next session's opening question. FAILURE/EXPIRY: a position resolves to AMBIGUITY → no fail: the entry reshuffles, a deeper-severity entry draws into the SAME slot (pays SIGHT/MIND for sitting with the unclear); if ambiguity persists to a guard limit the spread REFRAMES and still locks. Budget expiry commits the best PARTIAL answer and the remainder becomes a standing question framing a future session.
- **PO hook:** Each spread position IS a PoEntry (a genuine ambiguity — a two-meaning lexicon lemma, an open journal line); ambiguity re-draws by severity; the locked composite is written back as the next session's seed question.

### Converging Threads *(new)*
_Two-to-four parallel accumulators run at once; the session resolves when a QUORUM of them crosses threshold, not all of them._

- **Fit:** The parallel/portfolio spine — forces genuine 'which do I abandon?' tradeoffs (no dominant single line). A stalled thread doesn't die; it CROSS-POLLINATES, injecting a complication or shortcut into a sibling (Pandemic's bleeding cure tracks; Ironsworn's concurrent vows). The cross-pollination edge is a deterministic pool.c weighted draw over live threads. Quorum (e.g. 2-of-3) makes abandonment a real, characterizing choice.
- **Loop:** SUCCESS: quorum reached → a compound axis surge weighted by which threads you carried (carrying SIGHT+MIND pays study-flavored); abandoned threads convert into named loose ends that become next session's openers. FAILURE/EXPIRY: budget exhausts before quorum → every thread books whatever it accumulated as partial growth and each unreached thread is written back as an opening question (drift seed). No thread is ever a dead end.
- **PO hook:** Each thread is seeded from a separate PO entry (e.g. three distinct journal/lexicon items); abandoning a thread re-files its source as an unresolved question for the write-back spine.

---
## MODIFIER-CARDS (drawn on top of any shape)

### Going Without (The Vow constraint)
_A self-imposed limit on one resolution verb, sworn at session-open as part of the framing questions._

- **Effect:** DRAWN AT SESSION-OPEN as one of the framing questions: forbid or tax a single verb for the whole session (no FIGHT; STUDY costs double; you may not WALK AWAY). Mechanically just toggles/adjusts that verb's entry in the existing per-session cap array in deeds.h — no new machinery. Removing a tool forces the others to carry the weight: austerity as depth. The vow's wording is seeded from a PO lexicon term or journal intention (a real resolve turned into a constraint), so it reads as something the character cares about. You CAN break it mid-session — no hard fail.
- **Loop:** SUCCESS (honored to session end): WILL surge (held the line) plus HEART if it cost you an easier path; logged kept, biases future vow draws harder. FAILURE (broken): the moment you use the forbidden verb the constraint discharges and lifts — the axis-growth you'd have earned is REDIRECTED into the axis of the verb you chose instead (choosing otherwise is itself characterizing). State transitions cleanly on both honor and break.
- **Pairs with:** The Vow (Sworn Track), The Reckoning, The Standing Question, The Tending

### The Ember
_A local countdown laid on top of ONE thread inside any non-timed shape; its expiry is a doorway, not a death._

- **Effect:** DRAWN AT A BEAT-BOUNDARY when a thread first raises stakes (a danger is named). Seeds a small integer countdown (pool.c draw for the count) ticking one per beat. Unlike the Timed-Challenge goal-shape, the Ember is a transient overlay on a single thread, not the session's spine — so a contemplative session can host one pocket of pressure without becoming a race. Both the threat and its discharge-beat are seeded from a PO source (an almanac date/season or a journal stressor), so the clock pressures something real.
- **Loop:** SUCCESS: resolve the threatened thread before the count runs out → WILL/BODY bonus for holding under pressure; the Ember discharges harmlessly, logged averted. FAILURE/EXPIRY: count hits zero → the session does NOT end; the Ember discharges into a state change — the threatened thing happens (the fire spreads, the visitor leaves) and that consequence becomes the NEXT beat, paying the axis of how you handle the aftermath.
- **Pairs with:** Converging Threads, Two-Faced Omen, The Vow (Sworn Track)

### The Scar
_A high-stakes outcome that PERSISTS across sessions by writing a permanent mark to the append-only log._

- **Effect:** DRAWN ON A THRESHOLD-CROSS at a session-defining beat (success OR failure). Appends ONE input event — a mark on a chunk_xy, a standing axis modifier, or a 'marked' flag on a PO source. DETERMINISM GUARD: because chunks are pure functions of (base_seed,cx,cy) with NO per-chunk storage, the Scar must never mutate the seed or persist chunk state — it lives as an append-only input event and is replayed as a beat/render-time OVERLAY (like render_fpv billboarding features over pure geometry). This is legacy-game permanence (Risk/Pandemic Legacy stickers) over an unchanged deterministic world. Marks attach to a real PO place/term, so the legacy that accrues is the legacy of engaging your actual permanent objects.
- **Loop:** SUCCESS (triumph mark): logged as a boon that upweights future favorable draws at that place/source; pays the axis the triumph was won in. FAILURE (scar mark): logged as a STANDING COMPLICATION, not a defeat — the marked chunk/source spawns recurring beats that future sessions can HEAL for axis payout. The wound is re-closable; the world remembers until you tend it.
- **Pairs with:** The Reckoning, Kindred (The Bond), The Carried Thing (Burden)

### Kindred (The Bond)
_A recurring person/place/term from your real life walks the session beside you as a standing relationship meter that colors beats and persists across sessions._

- **Effect:** DRAWN when the runtime detects re-engagement of the SAME PO source across sessions (recurrence of a person/place/lexicon term), or from a KIN/BOND-themed source. Uses PoEntry.people — explicitly a RELATION, never a literal name (e.g. 'a neighbor', 'the one who taught you'), substituted via %people% — so it stays story-agnostic. The companion colors every beat as foil/witness, periodically acts, and unlocks beat choices unavailable solo. Carries a small integer bond-track stored, like the Scar, as append-only input events (never live state). No permadeath: they cannot be lost to death. The most PO-native card and the in-world face of the reality-anchor spine.
- **Loop:** SUCCESS (bond-track fills / you feed it): bond DEEPENS, pays HEART + BOND, sets the BOND theme bit so the relation recurs more readily; a matured bond can be 'called on' once for a free success, then cools and must be re-tended. FAILURE (neglect/expiry): the bond does not sever — it sediments into DISTANCE/estrangement (LOSS bit set) that surfaces as a beat ('you have not returned to X in a long while') and may re-seed as a Carried Thing or Return target. Reconciling distance pays HEART. State transitions on both tending and neglect.
- **Pairs with:** The Reckoning, The Tending, The Carried Thing (Burden), The Scar

### Two-Faced Omen
_A single card with two faces — upright is a windfall, reversed is a complication — drawn at the accumulator's midpoint to bend the back half of the session._

- **Effect:** DRAWN AT THE MIDPOINT-CROSS of the primary accumulator (the rising-action beat). One pool.c draw resolves both WHICH omen and its orientation (high bit of the hash = upright/reversed), like a reversed tarot card or Gloomhaven two-sided event. Upright = a consumable edge (re-roll, free success, verb discount) for the remaining beats; reversed = a twist re-skinning the back half with a complication (a verb gets harder, or a new axis demand appears). Folding twist and boon into one card keeps the deck small — a Flipper-budget virtue. The omen's flavor is seeded by colliding the session's PO drift source with a second PO term, so it reads as emergent from your own material.
- **Loop:** SUCCESS: upright boon SPENT → converts to effect, logged consumed; reversed twist OVERCOME → folds into payout as a bonus axis (you grew by handling it). FAILURE/EXPIRY: upright boon left UNSPENT → sediments into a small standing axis gain (unrealized potential becomes character); reversed twist UNRESOLVED → spawns a named loose thread seeding the next session. Both faces close on both branches.
- **Pairs with:** Converging Threads, The Ember, The Standing Question

### The Dread Tower
_An escalating-pressure card: certain beats force a seed-deterministic 'pull' that depletes a dread pool, raising severity and narrowing branches; when the tower falls it TRANSFORMS the session instead of ending it._

- **Effect:** DRAWN over any shape. Why it is NOT the Timed-Challenge goal-shape: that clock is neutral and monotone; the Dread Tower is an ESCALATION curve — each pull (a) removes tokens from a dread pool, (b) raises the severity floor of subsequently drawn PoEntries, and (c) narrows available branches per beat, so the world gets heavier as the pool empties. Pulls are triggered by specific beats (RISK theme bit), not the turn counter. Pull severity scales with PoEntry.severity; the transformation-beat draws the highest-severity entry in scope — all from real PO material. Wretched & Alone's dread tower, defanged of its mandatory death ending.
- **Loop:** SUCCESS (tower held to the host shape's natural end): the dread was contained → bonus WILL, and a 'steadiness' write-back lowers the severity of the riskiest PoEntry in play. FAILURE (pool exhausted / tower falls): a forced climactic transformation-beat fires and the session pivots into an aftermath/reckoning state, paying the run's biggest single axis jump (usually WILL, or BODY if RISK-themed). No game over — the fall is the hardest-won deed.
- **Pairs with:** The Vow (Sworn Track), The Standing Question, Timed Challenge

### The Carried Thing (Burden)
_You begin the session carrying something unfinished from a past one; it weights every beat until you set it down — the write-back spine made tangible._

- **Effect:** DRAWN over any shape, but its SOURCE is the output of earlier sessions: it is the explicit CONSUMER of the forswear/loss write-backs from The Vow, The Reckoning, and The Tending (and distant Kindred bonds / Return relics). This cross-layer wiring is what makes 'a life, not a campaign' mechanically real across sessions. One branch of each beat is 'shadowed' by the burden, which periodically surfaces its own demanding beat; PoEntry.severity is the integer tracking how heavy it has grown (resolution removes it, neglect raises it; LOSS bit marks it carried-unresolved). Seeded from a prior input-log entry flagged unresolved.
- **Loop:** SUCCESS (engaged to completion): RESOLVED — big HEART + WILL payout; the carried PoEntry is finally marked resolved and stops following the character. FAILURE (ignored/failed): DEEPENS — severity increments and the burden carries forward into the next session's carry-slot, heavier; pays a small SIGHT (the cost of looking away). Never a penalty, just the truth that some things travel with you until you're ready.
- **Pairs with:** The Vow (Sworn Track), The Reckoning, The Tending, Kindred (The Bond)

### The Turning
_A card drawn from the almanac that gives the session the weight of a date or season — a harvest, an anniversary, a turning._

- **Effect:** DRAWN over any shape from the ALMANAC/calendar PO source — a real date with weight (anniversary, season-turn, recurring observance). Colors the whole session with seasonal/date pressure and spans the full register: a GOOD turning (harvest, joyful anniversary) as readily as an ominous one. Biases which axes pay out and which theme bits surface. This is the deck's deliberate LIGHTNESS VALVE — serendipity and small joys, not only omen — and it plugs straight into the session-opening-questions frame as a date that frames the session's drift.
- **Loop:** SUCCESS (you heed the turning): bonus axis aligned to the season's theme; the date is written back as observed. FAILURE/EXPIRY (it passes unheeded): no block — it leaves a residue theme bit set that surfaces in a future session (an anniversary you missed comes back around). State carries cleanly either way.
- **Pairs with:** The Tending, The Standing Question, Kindred (The Bond)

---
## REJECTED / RISKY (guardrails held)

- **Cleft** — Placeholder/test stub in the raw candidates (one_liner 'x', fields 'a/b/c'). No real content — not a design.
- **Boss-rush / escalating-climax ladder** — Requires an authored final wall and implies a hard fail at the gauntlet's end. Violates 'a life, not a campaign' and the no-dead-ends law. (Elite's rank ladder is earned over real time, never a single gauntlet — the Dread Tower captures escalation without the wall.)
- **Good-vs-evil alignment meter** — Reduces a life to a scalar moral verdict — a D&D-alignment intrusion against the no-D&D rule, and Disco Elysium explicitly refuses to score morality. The six axes are growth-by-how-you-act, never a judgement.
- **Permadeath roguelike run / score-chase leaderboard** — Needs a hard-fail death state and turns a life into a win-condition / high score. No permadeath is established; failure must be a doorway, not a tombstone (Wretched & Alone's death-spiral is deliberately inverted here).
- **Time-loop 'do it perfectly' retry (Outer Wilds-style)** — Replaying to undo erases the append-only input-log — 'your choices ARE the save' — and implies an authored optimum, breaking seed-is-truth. Cross-session continuity (Carried Thing, Scar) is the sanctioned alternative.

---
## SYNTHESIS NOTES

Three highest-leverage additions, all chosen for how they marry the PO source to the session-opening-questions frame:

1. THE STANDING QUESTION (goal-shape) — the single best fit. It literally instantiates 'session opens with a series of questions / questions are the grammar at every scale': the session IS a question, each beat is a reading of a PO laid into a spread position, and the unanswered remainder becomes the next session's opening question. Its K-position-lock termination keeps it a concrete integer end-state, not vibes. Build this first if forced to pick one.

2. THE CARRIED THING / BURDEN (modifier) — the keystone of cross-session continuity. It is the explicit CONSUMER of the forswear/loss write-backs emitted by The Vow, The Reckoning, and The Tending. That cross-layer wiring is what turns three independent goal-shapes into one continuous 'a life, not a campaign' — and it is the deck's strongest answer to 'pairs well with the PO source + write-back spine.' Spec the Vow/Reckoning/Tending failure write-backs and the Burden consumer together, as one loop, not separately.

3. THE RECKONING (goal-shape) — the write-back spine turned into a whole session, reading PO journal/almanac history FIRST so there is no cold-start even on session one. It keeps the TYOV drain-to-zero engine (a finite memory set, each entry kept or lost), which guarantees a finite byte-equal session.

Frame-fit cluster: KINDRED is the most PO-native card (people-as-relation, the reality-anchor face) and THE TURNING is the lightness valve that reads a real almanac date — both plug directly into the session-open framing questions (Going Without is itself sworn AS a framing question; The Turning colors the session from a date). Deliberately keep the deck's affect spread: The Reckoning/Carried Thing/Bond-distance lean elegiac, so The Turning, Kindred, and The Standing Question carry serendipity, warmth, and curiosity — a life has small joys, not only grief.

Determinism note carried from the candidates and still binding: every draw rides the existing pool.c bag-draw (seed-hashed, anti-recurrence via last_drop_slot); card verb-limits reuse the per-session cap array in deeds.h (RAM-only anti-grind); any cross-session persistence (Scar, Bond, Carried Thing) is an append-only INPUT EVENT replayed as a beat/render-time OVERLAY — never seed mutation or per-chunk storage, since chunks are pure functions of (base_seed,cx,cy). No new RNG, no LLM at runtime, byte-equal PC↔Flipper.

Dedup log (for the spec author): merged Return + Memory Ledger + board-Reckoning → The Reckoning; Ritual Cycle + Tending → The Tending; Oracle Spread + Standing Question → The Standing Question; the two Vow-constraint cards → Going Without; Bond + Companion + Kindred → Kindred (The Bond); Burden + Carried Thing → The Carried Thing. The goal-shape 'The Vow (Sworn Track)' and the modifier 'Going Without' are intentionally kept separate (one is a session spine with a progress track; one is a verb-disable drawn on top of any spine) — the rename disambiguates them.