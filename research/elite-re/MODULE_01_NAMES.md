# Module 01 — System-Name Procgen

The smallest, most self-contained, most magical piece of Elite. Pure
math — no graphics, no I/O. When you finish, you'll be able to
regenerate `LAVE`, `DISO`, `RIEDQUAT`, `ZAONCE`, and `TIONISLA` from
first principles, and you'll own the 3-register shift that the entire
2048-system galaxy is built on.

Estimated time: **one evening.**

---

## Goal

Implement, in **modern C or Python you write yourself**, a function:

```c
void generate_galaxy(uint16_t seed0, uint16_t seed1, uint16_t seed2,
                     char names_out[256][8]);
```

that, given the canonical Galaxy 1 starting seeds, produces the 256
system names of Galaxy 1 in the same order they appear on the in-game
galactic chart, byte-equivalent (uppercase, null-terminated, 3 or 4
syllables each).

**Verification:** boot Elite in BeebEm, open the galactic chart for
Galaxy 1, photograph the first 10 system names, and assert your code
produces the same 10. If yes — done.

---

## Hardware / firmware context

- Original target: BBC Micro Model B, 6502 @ 2 MHz, 32 KB RAM
- Source: `Elite-BBCMicro-(Cassette).ssd` or `(Disc).ssd` — both work,
  same algorithm
- Tools you need: BeebEm (or b2), da65 (or any 6502 disassembler),
  Python or C for your reimplementation
- Optional: Ghidra with the 6502 plugin if you want a decompile view

---

## What you'll discover (hints, not spoilers)

The procgen uses **three 16-bit values**, call them `s0 / s1 / s2`.
They undergo a Fibonacci-like shift each time a system is generated:

```
tmp = s0 + s1 + s2          (16-bit, with carry handling)
s0 := s1
s1 := s2
s2 := tmp
```

There is a small table of **2-letter syllables**:

```
AL  LE  XE  GE  ZA  CE  BI  SO
US  ES  AR  MA  IN  DI  RE  A?    (the "A?" is a tab-character syllable)
ER  AT  EN  BE  RA  LA  VE  TI
ED  OR  QU  AN  TE  IS  RI  ON
```

Each system name is 4 syllables (8 letters max), or 3 syllables when
a specific bit of one seed is clear — that's why some names are
shorter (`LAVE` = `LA` + `VE` = 4 letters; `RIEDQUAT` is the full 4
syllables). Specific bits of `s0/s1/s2` pick which syllable indices.

That's the whole algorithm. Your job is to find:
1. WHERE in the disassembly this routine lives
2. WHICH bits map to syllable indices
3. WHICH seed controls the 3-vs-4 length gate
4. The Galaxy 1 starting seeds

---

## Suggested approach

### Step 1 — make your `.ssd` readable

```sh
# in tools/
da65 -o disassembly.s sources/Elite-BBCMicro-Cassette.ssd
```

You'll get one large `.s` file. Skim for any string-looking sequences;
the syllable table is right there in the binary if you look for the
ASCII pattern (`AL LE XE GE...`).

### Step 2 — find the syllable table

Use `xxd sources/Elite.ssd | grep -i 'AL.LE'` or similar — the table
of syllable letter-pairs is contiguous in the binary, near (but not
at) the procgen routine.

Once you've found it, note its address. **Don't look at bbcelite.com
yet.** Just the offset.

### Step 3 — find the routine

The routine that produces names will:
- LDA / STA pattern on three consecutive 16-bit memory locations
  (`s0`/`s1`/`s2`)
- A three-step ADC-with-carry sequence (the Fibonacci shift)
- Indexing into the syllable table you found in Step 2

Set BeebEm to break on any read from those three memory addresses,
load the galactic chart, and watch the breakpoint fire. The PC where
it fires is in your routine.

### Step 4 — re-derive the algorithm

In your notebook (paper or text file):

- Trace one execution of the routine by hand from the breakpoint
- Identify which bits of which seed pick the first syllable index
- Identify the length gate (the "3 or 4 syllables" bit)
- Confirm by hand-running the algorithm for the canonical first system

### Step 5 — reimplement

Write your own `generate_lave()` in Python or C. It should:
1. Start with the Galaxy 1 seeds you observed in the emulator
2. Output the first system name as text
3. Match Elite's output exactly

When `generate_lave()` prints `LAVE` — Module 01 done.

### Step 6 — generalise

Extend to `generate_galaxy(galaxy_number)` that produces all 256
system names. Photograph the BBC's chart for one galaxy, diff against
your output, fix any discrepancies.

---

## Your notes

> *Use this section as a free-form workbook. Write as you go — what
> address you found the syllable table at, what the 3-vs-4 gate looked
> like, dead ends you hit. Future-you and any session re-loading this
> file will thank you.*

### Session 1 — YYYY-MM-DD

(fill in)

### Session 2 — YYYY-MM-DD

(fill in)

### Algorithm restatement (when done)

(write your own one-paragraph explanation of how the syllable picker
works, in your own words, without consulting any reference. This is
the proof of mastery.)

---

## Verification log

Run your final implementation against the BBC emulator for Galaxy 1.
Paste the first 20 system names (yours / emulator's) here:

```
Yours          Emulator
-----          --------
?              ?
?              ?
...
```

When all 256 match for Galaxy 1, mark Module 01 done in
`README.md` and `MILESTONES.md`.

---

## When stuck

- Switch from da65 to Ghidra; the decompile view is sometimes more
  legible than raw assembly
- Try a different `.ssd` (Cassette vs Disc); the routine is the
  same but address mappings differ — picking the simpler binary
  helps
- Read the **source code comments only**, not the explanations, on
  bbcelite.com. The label names alone often unlock understanding
  without giving the answer.

**Do not, under any circumstances, read Moxon's `Tnames.asm`
walkthrough until your own implementation produces `LAVE`.** That's
the line between "got the answer" and "earned the answer."

---

## Onward

When Module 01 is done, Module 02 uses the *same seeds you just
mastered* to produce per-system attributes (government, economy, tech
level, population, productivity, fluctuation). The seed work doesn't
repeat — you'll just be reading different bits.

→ `MODULE_02_SYSTEM_DATA.md`
