# Tools Setup

Install these before starting Module 01.

---

## BeebEm — BBC Micro emulator

Primary emulator. Mature, single-step debugger, breakpoint support.

- **macOS:** `brew install --cask beebem` (if available) or download
  binary from <https://www.mkw.me.uk/beebem/> — works under Rosetta on
  Apple Silicon.
- **Linux:** package available on most distros; `apt install beebem`
  or build from source.
- **Windows:** download installer from the same site.

After install:
1. File → Disc Image → Load... → pick your `.ssd` in `sources/`
2. View → Debug → Debugger window appears
3. Debugger supports breakpoints on read/write to memory addresses.
   Right-click a memory cell to set.

---

## b2 — modern BBC emulator

Alternative to BeebEm with a more polished debugger UI. Optional but
useful when BeebEm feels clunky.

- Download from <https://github.com/tom-seddon/b2>
- Cross-platform, builds from source

---

## da65 — 6502 disassembler

Part of the cc65 toolchain. Used to produce a static disassembly of
the Elite binary.

- **macOS:** `brew install cc65`
- **Linux:** `apt install cc65` or build from source
- Usage:

```sh
# the .ssd is actually a disk image; extract the binary first
beebem-fs extract sources/Elite.ssd ELITE
da65 ELITE > findings/disassembly.s
```

(If `beebem-fs` isn't available, BeebEm has a "Save Disk to Local
File" option that produces a flat file. Or use the `acornutils` package.)

---

## Ghidra — interactive RE

NSA's open-source reverse-engineering platform. Has a 6502 plugin
that gives you a decompile view alongside the assembly.

- Download from <https://ghidra-sre.org/>
- Cross-platform (Java)
- Install the **6502 / 65C02 / 65816 plugin** from the
  ghidra-plugins repos: <https://github.com/Ghidra-SRE/Ghidra/tree/master/Ghidra/Processors/65xx>

Open Ghidra → New Project → Import binary (your `ELITE`) → analyze
with the 6502 language pack.

---

## Hex viewer

For ad-hoc poking. `xxd` ships with every Unix; use it freely.

```sh
xxd sources/Elite.ssd | grep -i 'AL.LE'   # find syllable table candidate
```

---

## Python / C

Your reimplementation lives here. No special setup; whatever you
already use.

I'd suggest Python for Modules 01–02 (rapid iteration), C for
Modules 03 (3D pipeline you'll port to Flipper later) and onward.

---

## Acquiring the `.ssd`

The original BBC Elite disk image is publicly released by Ian Bell at
<http://www.iancgbell.clara.net/elite/>. Pick the Cassette or Disc
version; both work for the RE curriculum. Drop the `.ssd` into
`sources/` — that directory is gitignored.

**Do not commit `.ssd` files.** They're not yours to redistribute,
and the workbook is research, not a republication.

---

## Optional: a tiny BBC reference

If the BBC Micro itself is unfamiliar, the *Advanced User Guide* PDF
is free online and explains the OS calls, memory map, and Mode 4
screen layout you'll see referenced in the disassembly. ~30 min read
to feel oriented.
