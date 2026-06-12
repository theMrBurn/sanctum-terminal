# Elite '84 Reverse-Engineering Workbook

A personal, sit-down-with-coffee curriculum for reverse-engineering
Braben & Bell's BBC Elite (1984). The goal isn't to *translate* what
Mark Moxon has already done at bbcelite.com — it's to **earn the
knowledge yourself**, with Moxon as the answer key consulted only
after you've taken your own swing.

The finished port of Elite to the Flipper Zero (or whatever target)
becomes derivative work from your own understanding, not from someone
else's annotations. That's the whole point.

This is research, not production code. Nothing here ships in any
sanctum binary. The deliverable from each module is your own clean-
room C implementation of the subsystem + your filled-in workbook
notes.

---

## Status

| Module                               | Status   | When done |
|--------------------------------------|----------|-----------|
| 01 — System-name procgen             | not started |        |
| 02 — System data (gov / econ / etc.) | not started |        |
| 03 — 3D wireframe pipeline           | not started |        |
| 04 — Trade economy                   | not started |        |
| 05 — Combat AI + flight model        | not started |        |

Update the timestamp column as you finish each module. The bar is
**"my pure-C implementation produces byte-identical output to the
running BBC emulator"**, not "I can read the disassembly."

---

## Directory layout

```
elite-re/
├── README.md                       (this file)
├── MILESTONES.md                   chronological log — fill in as you go
├── MODULE_01_NAMES.md              <- start here
├── MODULE_02_SYSTEM_DATA.md
├── MODULE_03_3D_PIPELINE.md
├── MODULE_04_TRADE_ECONOMY.md
├── MODULE_05_COMBAT_AI.md
├── tools/
│   └── SETUP.md                    BeebEm / da65 / Ghidra / b2 install notes
├── sources/
│   └── README.md                   where you put your own .ssd (NOT committed)
├── reference/
│   └── README.md                   bbcelite.com / Bell / Pinder references — answer key
└── findings/
    └── README.md                   your raw notes, sketches, Ghidra exports, etc.
```

---

## Hard rules

- **No copyrighted Elite assets ship with sanctum binaries.** Anything
  derived from the RE work that ends up in a shipping repo must be
  clean-room (your own algorithm restatement in your own code) and
  not a transcription.
- **Your `.ssd` disk image stays in `sources/`, which is gitignored.**
  Acquire it yourself from Ian Bell's site (publicly released). Don't
  commit the binary.
- **bbcelite.com is the answer key.** Use only after you've made your
  own attempt at the module. Diff your work against Moxon's notes;
  where you got something he didn't — that's your insight. Where you
  missed something — that's where you learn.
- **"Done" means byte-equivalent.** A module is done when your modern
  C re-implementation of that subsystem produces the same bytes /
  same outputs as the BBC emulator running the original game, against
  a fixed input. Not before.

---

## The path

1. Read `tools/SETUP.md`, install BeebEm + da65 + Ghidra.
2. Get a `.ssd` of BBC Elite from Ian Bell's site into `sources/`.
3. Open `MODULE_01_NAMES.md`. Work through it without looking at
   `reference/` until you have a Python `generate_lave()` that prints
   `LAVE`.
4. Move to Module 02. The seed-handling code you already understand
   makes 02 noticeably faster.
5. Modules 03–05 are independent of each other (in the sense that you
   can tackle them in any order), but each builds on the seed
   machinery from 01/02 in subtle ways.

Update `MILESTONES.md` after each session. The dated log becomes the
narrative of your own RE journey — useful to revisit, and the basis
for any future write-up.

---

## Boundary to sanctum

- The RE work informs (but does not directly produce code for):
  - `sanctum-engage` — the desktop ASCII roguelike's procgen patterns
  - `sanctum-os/docs/specs/43_app_sanctum_rpg_flipper.md` — the
    Flipper RPG's wireframe / procgen architecture
  - A future spec ("Sanctum Elite") that this work eventually unlocks
- The RE work does NOT ship in any sanctum app. The clean-room
  outputs (your own C implementations) become reference designs we
  port intentionally, not as copies.

Anything pulled from `bbcelite.com` (Moxon's MIT-licensed annotations)
must keep its license header if used. We will likely keep it as
reference material only, not source.
