# Module 02 — System Data (Government, Economy, Tech Level, ...)

The same 3-register seed you mastered in Module 01 carries **per-system
attribute data** in its other bits. Government type, economy, tech
level, population, productivity, and the fluctuation byte all
decompose from the same `s0/s1/s2` you already understand. Then a
separate text grammar — Braben's "goat soup" — emits the descriptive
sentence ("Planet Lave is mostly noted for its <X> and <Y>") from
yet more bits of the same seeds.

Estimated time: **2–4 evenings.**

---

## Goal

Implement, in your own code:

```c
typedef struct {
    char     name[8];          // from Module 01
    uint8_t  government;       // 0..7
    uint8_t  economy;          // 0..7
    uint8_t  tech_level;       // 0..14
    uint16_t population;       // billions
    uint16_t productivity;
    uint8_t  fluctuation;      // for market generation, used in Module 04
    char     description[120]; // the "Planet X is..." paragraph
} system_info_t;

void generate_galaxy_data(uint8_t galaxy_num, system_info_t out[256]);
```

**Verification:** for at least 20 systems in Galaxy 1, confirm against
the BBC emulator's Data on System screen (`I` key in game) that every
field matches.

---

## What you'll discover

- Which bits of `s0/s1/s2` map to which attribute
- The lookup table for economy names ("Rich Agricultural", "Average
  Industrial", etc.) — there are 8 entries
- The 8 government names ("Anarchy", "Feudal", "Dictatorship", ...)
- The grammar for descriptive text — a recursive token-substitution
  system where `<token>` expands to one of several phrases, also
  seeded
- How "fluctuation" derives — it's smaller than you might expect

---

## Suggested approach

### Step 1 — start from your seeds

You already have `s0/s1/s2` from Module 01 producing names. Save those
exact seeds before the name-generator consumed them; the *same* seed
state produces a system's data, in a different routine.

### Step 2 — find the data routine

Open BeebEm, navigate to a system's data screen. Break on the seeds'
memory addresses. The data routine should fire when you press `I`.
Note its address.

### Step 3 — map each attribute

For one fixed system (Lave is canonical), work out:
- Which bit positions of which seed produce `economy = 0` (Rich Agri)
- Which produce `government = 6` (Corporate State)
- Which produce `tech_level = 8`
- Population formula (involves the economy and government bits)
- Productivity formula (involves tech level)

This is mostly bitwise AND/shift/mask reasoning. Sketch a 48-bit
field of all three seeds and annotate which bits drive which output.

### Step 4 — the goat soup

The descriptive paragraph generator is its own little routine. It
operates on a **grammar table** of phrases like:

```
<0> Planet <name> is <1> noted for its <2> and <3> <4>.
<1> mostly | well | reasonably
<2> <food> | <weather> | <people>
<3> ... (recursive)
```

Each `<N>` picks from a small list using bits of (yet more of) the
seeds. The full grammar is maybe 200 entries.

This is the longest part of Module 02 by far. Don't be surprised if
this alone takes two evenings.

### Step 5 — reimplement

Extend the structure of your Module 01 code:
- A `lookup_economy(seeds) -> string` function
- A `lookup_government(seeds) -> string` function
- A `goat_soup(seeds, system_name) -> string` function
- A `generate_galaxy_data(g) -> array[256]` function

### Step 6 — verify

Cross-reference 20 systems' worth of data screens between BeebEm and
your code. Fix any mismatch.

---

## Your notes

### Session 1 — YYYY-MM-DD

(fill in)

### Bit-map of the seeds

(diagram which bits drive which attribute — this is the artefact
of Module 02)

### Goat soup grammar table

(your transcription of the phrases + their substitution rules)

---

## Verification log

For each of 20 systems (your output vs emulator):

```
System    Gov    Econ    Tech    Pop    Prod    Desc match?
------    ---    ----    ----    ---    ----    -----------
LAVE      ?      ?       ?       ?      ?       y/n
DISO      ?      ?       ?       ?      ?       y/n
...
```

---

## When stuck

- The goat soup grammar is the hardest part. If you've spent more
  than 2 evenings on it, peek at Moxon's notes for the grammar
  *table itself* (the data) but keep your own implementation of
  the *interpreter*. The table is data; the interpreter is the
  algorithm.
- For tech-level / population / productivity formulas, work them out
  algebraically: pick three systems, write the equations, solve.

---

## Onward

→ `MODULE_03_3D_PIPELINE.md` — the graphical soul of Elite. Ship
vertex tables, edge tables, the projection matrix multiply, the line
drawer.
