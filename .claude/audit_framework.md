# Audit Framework

Pattern that worked for the 2026-04-26 four-pillar audit. Use as a skeleton for future audit-shaped sessions (force-multiplier reviews, architecture reviews, migration audits). **Read `LIVE_PIPELINE_MAP.md` at repo root before any audit work** — agents that don't see the live-vs-legacy boundary will oversell.

---

## Phase 0 — Read & map source artifacts

**Goal:** structured digests of every source-of-truth, returned by parallel agents so the main thread's context stays clean.

For Sanctum Terminal, source-of-truth artifacts are:
- `~/Desktop/design_thoughts.txt` — running design journal
- `~/Desktop/prompt engineering live hash.txt` — append-only session particle trail
- Project root MDs (currently: `LIVE_PIPELINE_MAP.md`, `SANCTUM_SESSION.md`, `README.md`)
- Memory index at `~/.claude/projects/<project>/memory/MEMORY.md`

**Spawn one agent per artifact. Each prompt asks for:**
1. Canonical decisions (treated as settled)
2. Open threads (TBD, deferred, in-progress)
3. Contradictions (internal disagreements)
4. Anchored vs drifting sections
5. Cross-references to other artifacts
6. Audit-relevance flags per pillar

Cap each digest under ~800 words. Do **not** ask for paraphrase — ask for *structure extraction*. The reconciliation pass needs deltas, not summaries.

---

## Phase 1 — Reconciliation pass (pre-audit sync)

**Goal:** produce a single delta report so the audit isn't auditing contradictions.

Sections:
- **Source currency ranking** (most-current → most-stale; flag zombie docs)
- **Critical contradictions** (numbered, each with a recommended resolution)
- **Stale doctrine to retire** (memory pins giving wrong advice)
- **Coverage gaps relevant to audit pillars**
- **Decision asks** — questions the user must answer before Phase 2 (e.g., "archive zombie docs?", "patch stale memory?", "is X live or legacy?")

**Do not start Phase 2 until decision asks are answered.** Auditing against contradictions wastes everyone's time.

---

## Phase 2 — Audit (parallel spot-check agents)

**Goal:** for each pillar/concern, produce `Current State / Bottleneck / Concrete shift` blocks grounded in actual code, not just docs.

**Per-agent prompt skeleton:**
```
Spot-check the codebase for Pillar N: <name>.

Working directory: /Users/themrburn/git/sanctum-terminal/

Read `LIVE_PIPELINE_MAP.md` first — DO NOT recommend refactors against
files in the Legacy section.

Specific things to verify (with file:line citations):
1. <claim from docs/memory>
2. <claim from docs/memory>
...

Return format (under 700 words):
A. Current state — strengths.
B. Current state — leaks. Severity each (high/med/low).
C. Primary bottleneck for this pillar. One paragraph.
D. Concrete shift recommended. 2-3 specific changes with file paths.
   Don't propose new abstractions; propose collapsing existing duplication.

Don't speculate. If the code disagrees with the briefing, say so.
```

**Run agents in parallel.** Each is independent. Synthesize the four returns into a single deliverable.

### Pitfalls observed in the 2026-04-26 audit

| Pitfall | How it manifests | Mitigation |
|---|---|---|
| **Legacy-blind agent** | Recommends refactors against Panda3D files that aren't in the live pipeline | Brief with `LIVE_PIPELINE_MAP.md`; ask "would this be valuable if target were legacy?" before implementing |
| **Unmeasured performance claims** | Cites "22-25ms spike" or "50-100× speedup" from docs without verification | Treat claims as hypotheses; require measurement before optimization (instrumentation is cheap) |
| **Unity-shaped framework imported literally** | DOTS/Burst recommendations applied to Python+GDScript+TCP | Translate the *shape* of wins, not the literal tooling. Vectorize where possible; restructure data only if marshalling is the ceiling |
| **YAGNI schema pre-wiring** | "Pre-wire the JSON schema even though no consumer exists" | Reject — violates "don't design for hypothetical future requirements" |
| **Whitelist-to-JSON shuffle** | "Move the Python whitelist to JSON" without adding validation | Rejects unless validation/schema goes with it. Moving names is motion |

---

## Phase 3 — Post-audit reflow

**Goal:** findings flow back into source-of-truth before they rot.

For each finding, decide: memory pin, design_thoughts append, or live-hash session arc. **Do not duplicate** — pick one home.

- Memory: durable rules, learned-the-hard-way feedback, project-state snapshots
- design_thoughts: design discussion, decision rationale, scope deferrals
- live hash: session log, what shipped, what reverted, what stays unanswered

User typically wants memory edits done by Claude and Desktop file edits proposed but executable on demand. Confirm scope before writing into Desktop files.

---

## Phase 4 — Memory consolidation

**Run last by design.** Audit findings reveal which memories are load-bearing vs stale; consolidating before risks discarding live ones.

Pattern: ~110 files → ~15-20 thematic. Group by topic, not chronology. Update MEMORY.md index to reflect consolidation. Delete superseded/duplicate entries.

---

## Outputs and deliverables

A complete audit produces:
1. Phase 0 digests (in-context, agent-returned)
2. Phase 1 reconciliation delta (single report, user reviews)
3. Phase 2 audit (current/potential matrix per pillar + sequencing recommendation)
4. Phase 3 reflow (memory + Desktop file edits)
5. Phase 4 consolidation (smaller memory surface)

Sequencing matters. Skipping Phase 1 means auditing contradictions. Skipping Phase 3 means findings rot in chat history. Skipping Phase 4 means the memory surface keeps growing.

---

*Created 2026-04-26, extracted from the force-multiplier audit. Update when patterns shift.*
