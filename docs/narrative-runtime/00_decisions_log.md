# Sanctum Terminal — Pivot Notes (2026-06-26)

## SCOPE CORRECTION (user, this session)
- The NEWSFEED terminal / RSS apps are a SEPARATE project. NOT the game. NOT being deprecated here.
- This pivot is ONLY about the **Sanctum Terminal GAME**.
- (Earlier I wrongly folded the newsfeed reader into the game — corrected.)

## The decision (user, this session)
- DEPRECATE the current "velocity" of the GAME: its visual/UI-UX ambition. Too ambitious right now.
- KEEP: the lore + the basic shape of the game.
- TAKE: the Flipper Zero mobile RPG's RULES ENGINE — the thing that makes it work well.
- SCRAP: the game's visuals, for now.
- BUILD: a pure narrative — "things happening via text." Engine-first, text as the only renderer.

## Through-line
The rules engine IS the product right now. Text is the cheapest window onto it.
Get the simulation right; any renderer (TUI, raycaster, Flipper screen) hangs on it later.

## Consistency check vs standing doctrine
- MATCHES memory "Sanctum RPG on Flipper is PRIME/canonical; PC/Mac port FROM it."
  -> building the terminal as a text-front on the Flipper engine is ON-doctrine, not a detour.
- Flipper RPG known traits to preserve/extract: adventure-sim (not simplified RPG),
  level = age, use-evolving skills, finite contextual loot, NO permadeath, NetHack reference.
- Watch: "Two quest engines" fork (spec 48/49 Flipper-C vs live terminal Python engine had
  INVERSE completion+reward). Pivoting to the Flipper engine may RESOLVE or RE-OPEN this.
- "Seed is truth / merge inputs" — engine should stay seed+input-log deterministic.

## GROUND TRUTH (filesystem, this session)
- **Sanctum Terminal game** = `~/git/sanctum-terminal` on branch `feat/biome-greenhouse`.
  - Rules engine: `core/systems/` (quests/, consequences/, reflective/, encounter_engine,
    expedition_engine, world_gen, game_state, character_*, journal/lexicon ...).
  - THE "VELOCITY" (visual body, heavy): `clients/vector_terminal/` (full FPV renderer:
    chamber/bricks/wireframe/ball-trail), `godot/`, `native_renderer.py`, `frame_composer.py`,
    `thing_renderer.py`, `wireframe_mesh.py`, `ascii_render.py`. Rules+render are WELDED here.
  - State: `data/vault.db` (SQLite), `save/player.json` V3. LIVE_STATE.md tracks migration-sensitive files.
- **Flipper RPG (the thing that works)** = `~/git/sanctum-engage/flipper/sanctum_rpg/` (C, ~10.6k LOC).
  - Rules ≈ 3-4k LOC, mostly renderer-free: world.c(639) creatures.c(505) save_io.c(679)
    compose.c(328) deeds.c(264) deltas.c(254) narrative.c(281) pool.c weather.c stamps.c loot.c
    trade.c classes.c recipes.c biome.c rng.c fov.c. ALREADY HAS narrative.c + deltas.c (seed-truth) + deeds.c.
  - Visual ≈ 1.2k LOC: render_fpv.c(593) + sprites.h(631).
  - Glue/main loop: sanctum_rpg.c(3446) — input+render+rules tied together.
- `~/git/flipper/` = the host-sync TOOLING (cli/daemon/protocol), NOT the .fap. (Matches "bridge deprecated, protocol.py library only".)
- **Barrow** = user's most recent UI experiment (separate pygame raycaster).

## THE CENTRAL FORK (which body to build the text game on)
- A) PORT the Flipper C rules engine -> fresh Python text-front. Lean, on-doctrine (Flipper=prime),
   inherits narrative/deltas/deeds model. sanctum-terminal becomes reference graveyard.
- B) SALVAGE sanctum-terminal core/systems, amputate renderer. Reuses Python but drags the weld/entanglement.
- C) HYBRID: Flipper engine = the spec/spine; cherry-pick terminal-only Python systems with no Flipper
   equivalent (reflective/, quests/, journal/lexicon — the reality-anchor/reflective life-quest work).
- Claude lean: A or C. B is the trap (re-inherits the tangle the user is fleeing). USER DECIDES.

## DECIDED (user): OPTION A
- Flipper mobile experience = the BASELINE.
- Build the game engine as an INPUT/OUTPUT NARRATIVE-BASED engine that handles ALL rules:
  combat, out-of-combat, stats, etc. Pure text first.
- ONLY after the text engine does what the user likes -> start making it visually pleasing.
- "work with you or an agentic team" — agent matrix is in play for this.

## ARCHITECTURE PRINCIPLE (locked)
- Engine speaks I/O contracts, never pixels.
  - INPUT  = structured player INTENTS (verbs/commands), not keystrokes.
  - ENGINE = deterministic rules over seed + delta-log (renderer-blind): combat, out-of-combat,
             stats, world sim, deeds, loot/trade, narrative-event generation, save/load.
  - OUTPUT = structured narrative EVENTS; TEXT is the first renderer of those events.
  - LATER  = visual renderer = just another consumer of the same event stream. Matches the
             "renderer-swap seam" idea from the Flipper One devlog.
- This is the anti-weld discipline (sanctum-terminal welded rules+renderer; never again).

## REFINEMENT (user): REUSE-MAX + SIMPLIFY + NARRATIVE-CHAIN
- "A TON of logic/rules already" across BOTH bodies (Flipper C + terminal Python). USE as much as possible.
- But SIMPLIFY the rules. The test: can it work as a NARRATIVE CHAIN?
- If it works as a narrative chain -> adding visual layers is easy, EITHER as discrete SCENES
  OR as a CONSTANT FOV HUD over the chain.
- => This nudges from pure-A toward **A-spine + C-reuse**: narrative-chain is the unifying abstraction;
  map BOTH engines' simplified rules onto it.

## WHAT THE CODE PROVES (read narrative.c + deltas.c this session)
- narrative.c = a DETERMINISTIC, TABLE-DRIVEN narrative engine ALREADY EXISTS:
  - Quest templates (static const table; "add a template = one row"), %slot% substitution
    (lemma/subject/place/people), theme-mask + severity matching, integer FNV hash anchors
    (deterministic per seed×entry). NO LLM — pure templates. This is EXACTLY the no-LLM-line-safe
    narrator + the "narrative chain" primitive, already working.
  - PO entries (permanent-objects) -> templates -> A/B branches -> deeds. This is the reflective
    life-quest spine (spec 49) in C.
- deltas.c = the SEED-IS-TRUTH model made concrete: world = seed-gen base + applied deltas
  (tile mutations + creature kills), versioned, atomic write, tolerant read. = "merge input streams".
- TAKEAWAY: the two hardest things for a narrative engine — deterministic prose + truth model —
  are already built and proven on Flipper. The "narrative chain" is a small step from here, NOT a rewrite.

## CONSTRAINT (advisor, locked into spec): RUNTIME NARRATOR STAYS DETERMINISTIC
- No LLM in the runtime narrator (CLAUDE.md No-LLM line). Templated/seed-driven prose, like narrative.c.
- Any agentic team is BUILD-TIME ONLY (authoring templates/rules), never runtime.

## ACCEPTANCE GATE (advisor): FEEL, not coverage
- User's bar = "once I'm confident the text engine does what I like" = play-and-feel, iterative.
- => spine the spec on the I/O contract (intent vocab -> beat/event vocab); ship a THIN end-to-end
  playable slice (one combat encounter + a little out-of-combat, all text) EARLY so user can feel it.
  Full rule coverage comes AFTER the feel is proven, behind the stable contract.

## OPEN THREAD (do not lose): what specifically makes the Flipper version WORK?
- User answered the process question, not this one. Candidates from code: templated narrative beats /
  deeds(axis) economy / seed+delta world / loot+trade loop / the feel of it all ticking. NEED user's pick.

## THE VISION (user, clarified — bulleted & confirmed)
- Flipper mechanics already do the basic dungeon-crawl well -> KEEP as substrate, don't rebuild.
- The GAP = compelling NARRATIVE that makes the ruleset worth using. That's what we build.
- BAR: engine must be FULLY PLAYABLE via narrative choices ALONE — text in/out, complete with zero visuals.
- Narrative = source of truth for the experience; every mechanical event becomes a narrative BEAT.
- Visuals added LATER = illustrations of the current beat, never a parallel system, never driving logic.
- Reference model: ATLUS JRPGs + WILDERMYTH — visuals are an execution/illustration of whatever the
  narrative says is happening at that spot. Presentation downstream of story, posed to the beat.
- => confirms locked I/O contract: engine emits beats; renderer (text now; scenes/HUD later) consumes.

## *** THE REAL TARGET (user, most important distinction) ***
- NOT authoring a story. The engine is STORY-AGNOSTIC.
- Deliverable = the RULES/MECHANICS RUNTIME that advances ANY loaded story: combat, stat checks,
  progression/aging, loot, consequences, choice resolution — the verbs that move a narrative along.
- Analogy: build the SYSTEM (tabletop RPG ruleset / SRD), NOT the adventure module. Story = data/content,
  swappable; engine = the runtime that executes it.
- "Compelling" != us writing good prose. It means the MECHANICS are rich enough that ANY story routed
  through them is compelling TO PLAY: every beat is a real choice with stakes, regardless of subject.
- Mechanics are identical whether the story is a dungeon, a kitchen, or a memory.
- This generalizes narrative.c's split (templates=content, engine=matcher/resolver) to the WHOLE ruleset.
- Resonates w/ project_sanctum_runtime memory: "a core runs a GRAMMAR over the CHRONICLE" — here the
  grammar = the narrative-mechanics ruleset, the chronicle = the agnostic story/world stream.

## KEY DESIGN CONSEQUENCE (flag in spec)
- Flipper combat is partly SPATIAL (FOV/aim/ballistics/render_fpv.c). To be playable as narrative-choices-only,
  combat must be RECAST: "creature lunges -> [strike][guard][give ground]" choice-beats, NOT spatial aiming.
- This recast IS the core of "simplify the rules" and is where the most design judgment lives.
- Aligns with Atlus/Wildermyth (they want combat to READ as narrative beats too).

## VISUAL-LATER MAPPING (already de-risked)
- "constant FOV HUD" = literally render_fpv.c (593 LOC, already built) as a persistent view.
- "scenes" = per-beat rendered moments. Engine is blind to which; it just emits beats.

## PROCESS (per workspace protocol + user's spec-before-implement rule)
- Spec-AC BEFORE implementing: inventory Flipper engine -> lock forks -> draft docs/specs/NN -> code.
- Next concrete step candidate: GROUNDED EXTRACTION of the Flipper sanctum_rpg C engine into an
  inventory of actual rules (combat model, stats/classes, deeds/progression, loot/trade, world/biome/
  weather/creatures sim, deltas/seed-truth, narrative beats) = the raw input to the engine spec.

## Open questions (asked user)
1. Scope of "deprecate": hard reset / pivot-in-place / new surface alongside?
2. Narrative mode: passive event log vs interactive choices vs ambient ticking sim?
3. Do I first go EXTRACT the Flipper rules engine (read .fap code/specs) before we design?

## AUDIT MANDATE (user) — running as a team workflow
- Parse BOTH repos for existing logic/rules/mechanics that already DO something.
- GRADING RUBRIC (user's design law):
  - STATE CHANGES, not binary if/then.
  - NO natural dead ends — only LOOPS that close and transition state.
  - Per mechanic: is it a state-loop or a binary dead-end? What state transition does it perform?
- Surface CONFLICTING/overlapping mechanics -> user wants to TALK THROUGH them (don't auto-resolve).
- Answer: do we have a general outline to map LOOPING logic already?
- Output: keep / deprecate / simplify lists + conflict list + gap analysis + proposed state-loop model.
- THEN (next phase, after audit): define the EXPERIENCE & FLOW, and check our mechanics/components map onto it.

## RESOLUTION SYSTEM (user will consult — DECISION IS USER'S)
- User available to direct rules-resolution philosophy (d20 vs GURPS vs own preferences). Ask at vocab-definition step.
- Claude observation to raise: user's design law ("no dead ends, only loops that close + transition state")
  is the CORE of PbtA "fail-forward" resolution (every roll moves the fiction; a miss changes the situation, never stalls).
  - d20 = binary pass/fail (the if/then dead-end shape user is fleeing) -> against the grain.
  - GURPS = 3d6 roll-under, margin matters -> graded state changes, closer to the law, heavier.
  - PbtA = 2d6 miss/mixed/hit, fail-forward -> lightest, most loop-native. Strong candidate given the law.
- DETERMINISTIC != no dice: seeded rng (Flipper rng.c) gives replayable "rolls". All systems remain on the table.
- TODO: when audit lands, explicitly surface the resolution-model question to user (gap analysis open_questions covers it).

## AUDIT COMPLETE (2026-06-26) — full doc: scratchpad/sanctum_engine_AUDIT.md
- 18 keep / 6 simplify / 6 deprecate. Spine exists, split across both codebases = ASSEMBLE don't choose.
- Loop outline: PARTIAL pre-existing (Terminal game_state.py 4-state FSM + dated UAT precedent
  feat_loop-completion.md 2026-04-30 = "no linear dead-ends, only loops"). This audit = first full map.
- spec-48/49 inverse CODE-VERIFIED in 3 domains (quest, combat, defeat).
- KEY SPINE: REMEMBER (Flipper) == journal_followup (Terminal) = "complete by re-engaging source -> seeds
  next beat" = no-dead-end law AS a generative engine. Build the runtime on this.
- DEPRECATE: real-time Strike/ballistics/volley (off-axis, stubs) + 3D render layer (deferred).

## FOUNDATIONAL DECISIONS (user, 2026-06-26)
1. WORLD MODEL = HYBRID as a GENERATOR STACK (procgen-optimal):
   - Spatial seed-world = procgen GENERATOR + coherence guarantor, kept as DATA, never required to render
     (Flipper seed->biome->layout + carve_egress reachability + canonical-edge zero-state neighbor agreement).
   - Beat-graph DERIVED from it = what the player walks in TEXT (narrative.c already hash-anchors beats to chunks).
   - Port carve_egress reachability to the BEAT layer = "no dead ends" as a structural invariant.
   - NOT pure beat-graph (procedural narrative-graph coherence is unsolved; spatial+anchoring is in-repo & proven).
2. COMBAT/ENCOUNTER = COMPREHENSION ACCUMULATOR (Terminal net_passes; PbtA-flavored degrees, win-by-understanding,
   flee still pays 0.25x). Damage = one axis among several. No binary kill dead-end.
3. COMPLETION/REWARD = HYBRID: always-grant intrinsic axis-growth (Flipper coupled) + optional loot on top.
   Forbid rewards=[] dead-end.
4. STAT AXES = BODY/CRAFT/SIGHT/MIND/HEART/WILL (Flipper). Final naming may route through cultural-eccentric.

## ARCHITECTURAL DEFAULTS (Claude-recommended, user not vetoed):
- TRUTH = seed + append-only input-log, state derived by replay (= user's existing north star). CONFIRMED.
- BEAT ENGINE = Terminal consequence substrate (trigger->resolution->effects) as the ONE engine,
  Flipper deeds = atomic event-log beneath. Quests/expeditions/dialogs become DATA on it.
- STATE SKELETON = Terminal pure-data render-decoupled hub-and-spoke FSM (text-now/visuals-later).

## CASCADE: these decisions auto-resolve many of the 21 conflicts. Remaining to settle later:
  progression currency (downstream of #3), source-for-write-back (open Q2), byte-equal hardness (open Q3),
  market-in-v1 (open Q4), growth cadence per-act+prestige (open Q5), text-gen verbatim-vs-template,
  theme vocab bridge, single-PC-vs-class, content-selection drift-vs-LRU. Resolve during spec draft.

## LOGISTICS (decided)
- Spec + promoted audit doc -> sanctum-terminal/docs/specs/ (user left to Claude judgment).
- MEMORY: pin AFTER spec stabilizes (end of step 2) = max leverage; do NOT pin mid-flight.
- PLAN: do step 1 (experience & flow) -> 2 (spec) -> 3 (thin slice), one at a time, conversationally.
- NOW: Phase 1 = define the experience & flow (in dialogue).

## EXPERIENCE & FLOW (Phase 1, in progress)
- THE PULL = GOALS; the goal's SHAPE is the variable. Engine ships goal-SHAPES; content picks which one.
- SOURCE (answers open Q2): PERMANENT OBJECTS = the well that seeds goals/beats. Pluggable interface,
  but PO is the canonical source for the user's instance. (narrative.c MOCK_PO_ENTRIES = placeholders.)
- QUESTIONS ARE THE GRAMMAR AT EVERY SCALE: a beat = a question w/ choices (encounter, micro);
  a session = framed by a series of questions (macro). Same DialPrompt N-option primitive, two altitudes.
- SESSION OPENS WITH A SERIES OF QUESTIONS (char created+active) -> sets goal-shape + thematic drift.
  Open: do answers SELECT the shape or FEED a generator that infers it? Are questions authored / PO-derived /
  a real check-in? (Claude hunch: a check-in pulling current PO state in = half setup, half ritual.)
- GOAL-SHAPES so far (all are LOOPS, no dead ends): single goal / large-iterative-deterministic /
  exploration / timed challenge.
- USEFUL DISTINCTION being explored: GOAL-SHAPES (session spine) vs MODIFIER-CARDS (drawn on top of any shape).
- TEAM BRAINSTORM running: more goal-shapes + tabletop-style modules/cards that fit.

## CONSEQUENCE / IDENTITY SYSTEM — "The Reckoning" (user, 2026-06-26)
- CONCEPT: not D&D's rigid grid. The SAME bounded-accumulator primitive (combat net_passes / aggro)
  pointed at the SELF. Already half-built: narrative.c branches are value-polarities (TEND/LET_GO,
  SPEAK/WITHHOLD pushing HEART vs WILL).
- REUSES: deeds (the log) + pool.c drift (trajectory) + accumulator (tension) + disposition FSM
  (reputation = world reading your trajectory) + level=age (rigidity) + reflective primitive (where a shift is processed).
- MODEL: profile = position + trajectory (a "blob of ever-shifting potential"); choices in-character
  DEEPEN it, choices against it ACCUMULATE TENSION; tension past threshold -> a SHIFT that re-centers you.
- RIGIDITY is a variable: young=elastic (bends, no drama); old/consistent=rigid (absorbs longer, snaps harder).
  Pairs with level=age. Rigidity rations Reckonings -> rarity gives them weight.
- USER REFINEMENTS:
  1. Identity = a BLOB of ever-shifting potential; exact dimensionality = refinement, keep it fluid.
     Resonance: identity as potential your choices COLLAPSE into shape (= "choices are the save file").
  2. The shift is a RECKONING (canonical in-world name; the word itself is evocative/weighty). Peer to the
     reflective interlude; rides the same reflective state-machine primitive. Earn weight via RARITY.
  3. VISIBILITY = felt-through-world by default BUT a visitable PURE STATS PAGE always available.
     PRINCIPLE: "present felt-first, never hide the math; legible on demand." (Ties to user-sovereignty.)
- SEQUENCING: fold Reckoning into the flow; have the team formalize the consequence/Reckoning system as its
  own pass AFTER the goal-shape brainstorm lands (they interact: goal-shapes that TEST alignment;
  modifier-cards that APPLY tension).

## GOAL-SHAPES + DECK landed (doc: scratchpad/sanctum_goal_shapes_DECK.md)
- 9 goal-shapes (your 4 + Vow/Reckoning-goalshape/Tending/Standing-Question/Converging-Threads).
- 8 modifier-cards (Going Without/Ember/Scar/Kindred-Bond/Two-Faced Omen/Dread Tower/Carried Thing/Turning).
- Power picks: The Standing Question, The Carried Thing (cross-session keystone), Reckoning-goalshape.
- Guardrails HELD (rejected): good-vs-evil meter, permadeath, score-chase, boss-rush wall, time-loop retry.
- Determinism reconfirmed: draws ride pool.c bag-draw; cross-session persistence = append-only input events
  replayed as overlays (never seed mutation / per-chunk storage); no new RNG, no runtime LLM, byte-equal.

## NAMING
- "Reckoning" RESERVED for the identity-SHIFT event (user prefers its gravitas as a rare capstone).
- Retrospective-session goal-shape RENAMED -> **The Cairn** (build stone-by-stone = each integrated memory;
  finished cairn = drained-to-zero set, marks a life reviewed; name == mechanic). User register choice: OBJECT.
  ACCEPTED, gated on teachability (below). Pending: cultural-eccentric voice pass over name + full deck.

## PROLOGUE / TRAINING CAMPAIGN (new Phase-1 flow element, user)
- A prologue/training campaign exists; it's where the abstract vocabulary + mechanics are taught
  ONE CONCEPT AT A TIME, BY DOING (diegetic; NO dry D&D-manual tutorial — matches the no-D&D-tutorial voice rule).
- PRINCIPLE (locked): every evocative name must be EARNED by the prologue teaching it through play.
  A name we can't teach diegetically gets cut, however good it sounds. (Cairn passes easily: place one stone.)

## PHASE 1 COMPLETE — canonical flow + seam-check (docs in scratchpad/)
- DURABLE DOCS: sanctum_engine_AUDIT.md, sanctum_goal_shapes_DECK.md, sanctum_session_FLOW.md, sanctum_flow_SEAMCHECK.md
- FLOW SPINE ("one machine wearing different weather"): 4-state FSM (CHARACTER_CREATION/HUB/REFLECTIVE/
  ENGAGEMENT) over ONE consequence beat-engine, driven by ONE deed. "One deed, three readers"
  (axis-growth + goal-shape accumulator + identity tension). Write-back at TWO altitudes = no-dead-end proof.
  "Return to a lit room." One DialPrompt grammar, number-row keymap (zero F-keys), AMBIENT/GLANCE/SUMMON tiers.
- 12 STAGES: Boot -> Draft(Becoming) -> Prologue -> Session-Open -> Hub -> Beat -> Resolve+Write-back ->
  (Fall on defeat) -> Consolidation(age tick) -> Reckoning -> Session-Close -> Write-back/Carry.
- RESOLVED TENSIONS (key): Cairn vs Reckoning naming locked; FSM stays 4 states (others are transient
  brackets/phases riding world.session_frame + REFLECTIVE); Draft PRECEDES prologue teaching beats;
  Reckoning fires at next Consolidation boundary; always-grant supersedes XP-wipe; economy optional.
- SEAM-CHECK VERDICT: structurally sound + disciplined, NO unhandled dead-ends; solidity is at TOPOLOGY
  layer — several load-bearing joints rest on UNBUILT components. Seam-check grepped real code w/ line #s.

## WORK-AHEAD (from seam-check) — feeds Phase 2 spec sequencing
- DECISION to confirm: spatial-vs-graph. (We chose hybrid generator-stack = BEAT-GRAPH primary, spatial
  kept as DATA; only carve_egress's abstract kernel ports. Stage 5 was written spatial-first -> reconcile.)
- MUST-BUILD-FIRST invariants: (1) beat-layer carve_egress (reachability) before any chaining shape;
  (2) seed+input-log replay + deltas-overlay PORT (precondition for ALL cross-session cards); (3) collapse
  Terminal's two stat systems -> one 6-axis sheet (source of truth for "how you acted -> which axis").
- DETERMINISM cleanups (integer-FNV + golden vectors): rewards.py, reflective/magnets.py, the resonance
  gate worth_knowing>0.45 (encounter_engine.py), resolver injectable RNG. Vow tick/Converging quorum integer from start.
- ENGINE GAPS: abilities authored but no resolver reads them; DEFEND inert (wire defend_halves or CUT);
  theme-vocabulary bridge (project learned lexicon -> finite byte-equal vocab).
- PROLOGUE gaps: reflective-compose grammar never taught before The Fall needs it (route a teaching beat
  through it); the Reckoning/tension/blob is wholly unscaffolded (add a one-line by-doing reveal).
- TENSION tuning: distance metric over 6-axis blob + rigidity curve = golden-vector pass w/ REAL PO data.
- CROSS-REPO: PoEntry lives in permanent-objects (separate repo); define+version the source contract boundary.
- ~~NEEDS USER: wife's-voice sample~~ CORRECTED 2026-06-29 — NO sample needed; was a MISREAD.

## VERBATIM PASSTHROUGH (corrected AC, 2026-06-29) — supersedes "wife's-voice" misread
- "Her voice" / "my own voice" = the INPUTTER's own LITERAL WORDS, NOT a literary style.
- RULE (system, not copy-style): USER-AUTHORED content (note/date/reminder/alert/scheduled item/PO entry)
  is stored + USED as-is; engine may key logic/routing off it but NEVER alters it; when SERVED BACK to a
  user it is VERBATIM — never interpreted/summarized/re-enumerated/rephrased.
- ENGINE-GENERATED narration (templated beats/system flavor) = a SEPARATE text class, no verbatim constraint.
- WHY (user): people follow their OWN words; an app-reworded reminder = external authority = ignored;
  self-authored = self-authority = follow-through.
- = workspace-protocol §2 user-sovereignty applied to runtime OUTPUT; resolves audit template-vs-verbatim
  conflict PER-CLASS. narrative.c %slot% already does template-frame + verbatim-user-term; stronger rule:
  served-back-as-itself (reminders/alerts) = whole-verbatim.
- ARCH SEAM: two text classes — USER-AUTHORED (sovereign, verbatim) vs ENGINE-GENERATED (deterministic template).
- ACTION: re-point cultural-eccentric (its "need a voice sample" flag is MOOT). FIX memory
  "Reality-anchor loop closed: toast copy not yet anchored to wife's voice" at spec-pin time — it's a misread.

## SPEC OPEN DECISIONS — refining one at a time (user: "see what we have first")
### #1 BYTE-EQUAL HARDNESS — DECIDED: HARD on the TRUTH/CHRONICLE path, FREE on presentation.
- Rationale: seed-is-truth + cross-device MERGE requires byte-equal for any state-deriving compute;
  user wants narrative state mergeable Mac<->PC<->Flipper. Line = "does it touch the chronicle?"
- What we have: spec 53 golden-vector harness EXISTS (sanctum-engage/tests/conformance/) but covers ONLY
  rng + pool (Phase A, not closed). ~21 Python files use float random; ~9 on truth-path (player_state,
  roster_pool, roaming_pool, actor, encounter_session, rewards, magnets, reflective/state_machine,
  consequences/effects) -> port these to integer-FNV + extend golden harness up the stack. narrative.c
  already integer-FNV; deck designed byte-equal. Presentation/render float = fine (never merged).
- Does NOT force the Flipper to run the FULL runtime day one — just keeps the Python truth-path integer
  so the door stays open.

### #2 GROWTH CADENCE — DECIDED: BOTH layers from day one (micro deeds + macro level=age/prestige).
- What we have: BOTH exist. Flipper deeds.c/.h = mature per-act MICRO (append-only, integer, capped,
  21 deed events on 6 axes; effective_axis = base + deeds.delta). Terminal character_sheet.py = MACRO
  (level=age + prestige via class_history -> earned abilities + stat presets; "Cairn canonical").
  Uniting = wiring deeds onto the one sheet; not net-new.
- Reason FOR both-now: ONE save-schema migration (vs paying the migration tax twice). Matches level=age +
  use-evolving pillar; anchors the Reckoning's rigidity; kills seam-check's "inert level" dead-end.
- GUARDRAILS for the spec (the real cautions, neutralized):
  1. Deeds (micro) = DOMINANT, fully-tuned signal; macro stays LIGHT -> preserves "how you acted -> which axis" legibility.
  2. Macro layer must be DATA-DRIVEN (prestige classes/ages = seed/config, NOT the hardcoded Sean/age-32
     template in engine code) -> preserves story-agnostic.
  3. Structural NOW, tuned LATER (asymmetric effort; macro barely shows in a thin slice = can't be feel-validated yet).
  4. Spec the Reckoning's RIGIDITY input as a clean contract that degrades gracefully when macro is light
     (decouples two high-tuning-risk systems).

### #3 PROTAGONIST — DECIDED: single persistent "You" (canonical).
- Classes = LIFE-STAGES (data), not a creation menu. character_classes.py models class = {stat_preset,
  abilities}; character_sheet class_history = a sequence you AGE through (rogue->monk@32, most-recent wins,
  abilities aggregate). Class-as-creation-mode = OPTIONAL later data toggle, NOT default.
- UNIFICATION (#2+#3+Reckoning): macro layer has TWO drivers — AGE (slow default template) + the RECKONING
  (rare, choice-driven, OVERRIDES the template). Reckoning = the use-evolving override on the age-default.

### "THE HONEST MIRROR" — core principle (user, reality-anchor soul)
- The char sheet is a MIRROR of who you actually are, NOT a build you optimize. Only legit way to change
  it = change your REAL behavior. In-game goals are completed by REAL-WORLD task accomplishment (via PO).
- Discourage restarting a seed; ALLOW honest adjustment; but an honest player SHOULDN'T WANT to edit —
  growth comes from actual behavior.
- HOW WE ENFORCE/ENCOURAGE (mostly architectural, already latent):
  1. DERIVE-DON'T-SET: sheet = rolled-up replay of the append-only deed/input log (seed-is-truth #1).
     No stat slider to game. "Adjustment" = correcting honest INPUTS (re-do the Becoming honestly), never output stats.
  2. NO HIDDEN EDITS: any adjustment is an append-only, visible event on the always-inspectable stats page
     ("never hide the math"). Vanity-editing is self-evident — like editing your own diary.
  3. DISHONESTY -> TENSION -> RECKONING: claiming to be what your actions don't support is AGAINST-PROFILE;
     it generates identity tension (the same accumulator) and destabilizes. Self-dishonesty is mechanically
     uncomfortable; the blob re-centers on real behavior. (This is the deepest enforcement.)
  4. REWARD IS THE EARNED BEAT, NOT THE NUMBER: real completion fires the deed beat + narrative ack +
     write-back; a raw edit gives a hollow number with no beat. Satisfaction lives only on the earned path.
  5. ANTI-GRIND already exists: deeds.h per-session caps -> in-game grinding can't dominate; REAL-WORLD
     PO-completions are the uncapped/meaningful lever.
- RESTART: frame as ABANDONING A LIFE, not resetting a build — heavy/marked/rare (Reckoning-weight), not a cheap "New Game".
- FOLD this honesty/anti-save-scum incentive into the RECKONING-formalization pass (it IS the tension system
  applied to self-misrepresentation) + capture as a spec principle.

## RECKONING FORMALIZATION + STRESS-TEST (docs: sanctum_reckoning_FORMALIZATION.md, _STRESSTEST.md)
- MODEL (validated core): identity = P[6] (position = lifetime deed rollup, inertial) + T[6] (per-axis tension).
  Metric: raw_k = (pmean - P[k]) * delta = projection of a deed onto your mean-centered self; per-axis,
  integer, read P BEFORE applying deed. T reads its own story -> shift re-centers toward the drifted axes.
  Rigidity = K_AGE*age^2 + K_CONS*concentration -> rarer with age, snaps harder, young=elastic emergent.
  B-prior init (born-as-your-claim). Explicit drain event (no instant re-fire). Fires at Consolidation boundary.
- HONEST MIRROR = SAME metric (a claim is scored like an against-act). NO set_stat exists (stat-slider
  UNREPRESENTABLE). Game never judges, just leans. DEED_PO_COMPLETE (uncapped, one-per-id) = real-world is the
  ONLY uncapped growth ("can't farm real life"). Restart = heavy AbandonEvent, fork seed, inherit nothing.
- STRESS-TEST verdict: core HOLDS (green: deeds-vs-base + case-4 discriminator; no-set-stat; reuse REFLECTIVE
  FSM; B-prior; explicit drain). Issues to fold into spec §5 + build order:
  * 🔴 B1 REFUSE doorway is design-fiction — reflective FSM has no player abort -> forced one-way shift
    (contradicts "choice-driven"). Build apply_reckoning_refusal -> exit()->HUB.
  * 🔴 B2 concurrent reflective-entry clobbers an in-progress beat -> defer if already REFLECTIVE (serialize).
  * 🟠 L1 compose_pool/pick_rule use Mersenne Twister; FNV-SEEDING ≠ byte-equal. Replace the selection
    PRIMITIVE: idx = fnv(line_id,i) % len(sorted(pool)). (= the real content of build-list #4.)
  * 🟠 L2 concentration = max-median injects half-integer (median of 6) -> use max-min / integer-safe spread.
  * 🟠 L3 _regen_world uses randint on truth path -> derive seed from chronicle; preflight-assert seed present.
  * 🟡 F1 per-axis T_AXIS_CAP vs age-scaled THRESHOLD -> elders may be UNABLE to Reckon from drift. AC:
    THRESHOLD(age_max) < drift_axis_count*T_AXIS_CAP. (rarity = STRUCTURAL AC, not just a dial.)
  * 🟡 F2 feeders fire but can't AIM -> all-zero T -> random life-stage. Feeders deposit directionally OR
    fallback = no class change / toward D̂. Never shift on a zero vector.
  * 🟡 F3 "consistency -> ΣT=0 structurally" false (integer quantization noise) -> add deadband ε.
  * 🟡 F4 PRIOR_TOTAL pulled two ways (young-elastic vs prologue visibility) -> scripted impulse for the prologue nudge.
  * 🔵 D1 CLASS-RESPEC EXPLOIT: drift off-axis to force a Reckoning into a stronger preset (deeds are real,
    so "earned-beat" defense fails). "Replace + power-tiered presets" = exploitable combo -> pick at most one.
    => makes open-Q#4 (stack vs replace) a GUARDRAIL, not flavor.
  * 🔵 D2 voluntary re-claim pre-empts the Reckoning (rigidity rations involuntary, not voluntary dodge).
    Trigger is "persistent DENIAL" not "drift" -> gate re-Becoming relief by rigidity OR align prologue copy.
  * ⚪ C1 "can't farm real life" = PO-id minting integrity (permanent-objects doesn't validate input).
    Define cross-repo eligibility contract; DEED_PO_COMPLETE fail-soft to CAPPED local grant when offline.
  * ⚪ C2 serial restarter looks pristine -> carry abandonment-count forward as a quiet meta-mark (no dark pattern).
  * GRACEFUL-DEGRADE CATCH: unmapped T-cluster -> stat_preset silently falls back to ROGUE
    (character_sheet.py:131-138). Build the 6-cluster->life-stage table TOTAL before ship, OR fail closed (drain + no class change).
- HARD CHAIN: stat-collapse (build-list #3) BLOCKS everything — B=D&D names, D=BODY/CRAFT/...; incommensurable until one 6-axis space.
- SHARPENED TUNING QUESTIONS (user, was 4): #1 rarity (now a STRUCTURAL AC per F1/F2; default: handful per LIFETIME);
  #2 late-life identity (lifetime D̂ vs recency-weighted); #3 decay rate + refused-Reckoning residue;
  #4 stack-vs-replace (now a GUARDRAIL per D1).

## RECKONING TUNING (user, one at a time)
- #1 RARITY = 7 IN A LIFETIME (typical drifting life; consistent lives fewer/none). Anchors the constant pass;
  must satisfy F1 reachability ceiling THRESHOLD(age_max) < drift_axis_count*T_AXIS_CAP. Resonance: 7 pillars
  author you at start, 7 Reckonings re-author you across the life.

## *** SEED-AS-LEDGER / TRADE MODEL (user original design — FOUNDATIONAL) ***
- THE SEED = THE CAIRN = THE LIFE. One object; a seed-rooted tree; everything addressable from the seed.
- Seed-hash = an ADDRESSING SCHEME, not just RNG. Seed ABX -> ABX.object123.<var>... ; every object/skill/
  artifact/story/color has a deterministic address.
- DATA IS THE CURRENCY: trade transfers an ADDRESS (+provenance), not a data blob — recipient's engine
  deterministically EXPANDS the same address to the identical artifact (the content-VM / seed-language).
  Whole seeds OR any branch tradeable/barterable between seed-holders.
- "Blockchain" = MENTAL MODEL ONLY: append-only, addressable, ownership-by-ledger-entry, transfer-as-event,
  tamper-evident-by-hash. NOT an internet crypto chain — self-hosted, deterministic, P2P (rides mesh/LoRa/merge).
- THIS IS THE WHY behind: the custom seed-hash / seed-language / content-VM; and it DEMANDS decision #1
  (byte-equal hard on truth path) — trade only works if an address reproduces byte-identically for the trader.
- REFRAMES ECONOMY: not a gold shop — peer-to-peer BARTER of seed-addressed artifacts; CORE not optional.
  A trade = a consented MERGE of one ledger branch into another's input-log.
- KEY TENSION — TRADE vs HONEST MIRROR: Cairn has TWO layers:
  * NON-TRADEABLE SELF (axes/identity/deeds) = earned-only honest mirror (can't buy WILL).
  * TRADEABLE ESTATE (objects/artifacts/stories/colors) = made/found things.
  * "skill" straddles: split TECHNIQUE/RECIPE (tradeable) vs CAPABILITY/axis-growth (earned-only, non-tradeable).
    -> confirm with user.
- CONNECTIONS: trade = EGRESS -> rides the consent/egress border (CLAUDE.md §5) + friend-tier framework
  (who you can trade with). Provenance/"can't forge" = SAME problem as the stress-test PO-minting integrity (C1),
  solved by the same append-only addressable ledger.
- Does NOT disturb tuning #2 (identity = the non-tradeable layer). 
- TODO: lock #2=(a); capture seed-as-ledger as a foundational spec section; likely a future formalization pass
  (addressing scheme + trade + provenance + tradeable/non-tradeable boundary + consent-border).

### TRADE MODEL — LOCKED (user): everything offerable, SKILL-GATED, honest-by-tension.
- Everything in the Cairn can be OFFERED; a naive swap is free; APPRAISE/DIAGNOSE/NEGOTIATE/CHARM/
  BARTER-at-length are EARNED capabilities -> a novice gets fleeced, a master walks away ahead. Trade = a playstyle.
- HONEST MIRROR holds by TENSION, not category bans: tools/artifacts/techniques/stories/colors trade freely
  (external — "the sword's power is the sword's"); an aspect of SELF acquired-not-earned isn't backed by P ->
  against-profile -> tension -> never sits as "you" -> a Reckoning re-centers you to who you actually are.
  "Buy the sword, not the swordsmanship; if you try, the system knows." Market can be wide open BECAUSE self can't be faked.
- TRADE = NO NEW SUBSYSTEM: appraise/diagnose = scan/understand (SIGHT/MIND); negotiate/charm = parley/stance
  (HEART/WILL/MIND). A barter is an ENGAGEMENT (comprehension accumulator) in the EXCHANGE context. The LEDGER
  handles transfer+provenance (addresses changing hands); the ENGAGEMENT decides the terms. => EXCHANGE =
  "engagement + ledger entry", a CORE skill-gated context (not an optional gold shop). Both halves already built.
- Skill-split resolved: a technique/recipe = tradeable artifact; the capability to wield/haggle = earned (unearned acquisition -> tension).

### #3 DECAY + REFUSAL — LOCKED.
- Tension decay = SLOW (one-off slip heals over time; a pattern outpaces decay and accrues).
- Post-Reckoning SETTLING = at least a (LOGICAL/in-game) day, scaled by the Reckoning's magnitude
  (discharge ∝ age² -> extravagant = longer settle; small ≈ a day). Truth-path day = epoch ticks (byte-equal),
  NOT wall-clock.
- REAL-TIME "let it breathe" layer = YES (presentation-side pacing; gates WHEN you're invited back, not derived state).
- REFUSAL = a composed OPTIONS-beat, not binary. Refuse/hold -> tension RESIDUE persists (Reckoned again soon) +
  rigidity HARDENS (more brittle) + a standing DISSONANCE = the deck's SCAR (surfaces beats until healed).
  Heavy enough to make reconsidering rational. Loop-closes (refuse -> HUB carrying residue+Scar; question returns). Valid stance, not a free reset.

### SESSION-OPEN = DAILY BASELINE CHECK ("Voight-Kampff", user — design consideration to accommodate NOW)
- Session-open isn't just goal-shape pick — it's a DAILY BASELINE/ALIGNMENT check: re-establish baseline,
  DIAGNOSE DRIFT (read your tension/blob, reflect it back = the honest mirror performed as a greeting) +
  a PASSIVE SYSTEM CHECK (real date, time-of-day, Δ-since-last-engagement). Details SCRIPTED later; engine must SUPPORT it.
- ENGINE HOOKS to build in: (1) session-open reads drift state (tension/blob/to_reckoning); (2) passive system
  check (real clock -> date/time-of-day/last_engagement_at stamp); (3) DialPrompt ask + RECORD user answer VERBATIM
  (user's stated reality canonical; clock is a cross-check); (4) a scriptable, data-driven baseline-ritual slot (content, not code).
- DETERMINISM BOUNDARY: passive clock (date/time/Δ-since-engagement) = AMBIENT PRESENTATION input, NOT truth-path
  (can't feed byte-equal/trade). User-CONFIRMED answers = recorded INPUT EVENTS = truth. (machine clock = hint; confirmed = chronicle.)
- CONNECTS: gates the real-time breathing layer (last-engagement); ties to presence daemon + chronometer-as-ambient-input.
- TONE FLAG (cultural-eccentric, load-bearing): a Voight-Kampff is an interrogation-you-can-fail, but our rule =
  the system NEVER JUDGES, only reflects. Must feel like YOU calibrating YOUR instrument (a greeting), NOT a test of
  whether you're real. Register matters given the elegiac themes.

### #2 LATE-LIFE IDENTITY — LOCKED: (a) lifetime D̂.
- Old deeds define you forever; the polymath generalizes. The Reckoning is the SOLE sharp identity shift
  (recency-weighting would compete with it). Reformation = sustained against-(old)-self drift -> earned Reckoning
  ("you don't drift into a new self, you're Reckoned into one"). Matches Cairn/seed-is-truth; trivial determinism.
  (b) recency-weighted = a one-line replayable upgrade if ever wanted.

## NAMING FINDING — "Cairn" already in code (flag for cultural-eccentric pass)
- character_sheet.py:4 "level=age (Cairn canonical)" — the codebase ALREADY uses "Cairn" as the canonical
  name for the level=age / lived-life concept (there's likely a design_cairn canon/memory).
- We named the retrospective goal-shape "The Cairn" THIS session. COLLISION — but a HAPPY one: both =
  "a life accreted stone by stone." Decide consciously: UNIFY (Cairn = the lived-life canon, the
  goal-shape is its retrospective ritual) or SPLIT (rename one). Route to cultural-eccentric. Lean: unify.
- Also noted: Terminal character_sheet uses D&D stat NAMES (dex/wis/int_/cha/...) not BODY/CRAFT/SIGHT/
  MIND/HEART/WILL -> rename in the stat-vocab collapse (decision #3-adjacent).

## TODO once answered
- Per workspace protocol: spec-AC BEFORE implementing (inventory -> lock forks -> draft spec NN -> code).
- 50/50 rule: end with a propose-update to AGENTS.md / SHARED_STATE.md.
