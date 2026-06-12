# Findings

Your raw RE notes, sketches, Ghidra exports, disassemblies, memory
maps, scribbled formulas, hex dumps. Anything that captures *what
you actually saw* during a session.

Suggested files (create as you go):

```
findings/
├── disassembly.s                   da65 output
├── memory_map.md                   addresses of seeds, tables, routines
├── seed_bits.md                    bit-by-bit breakdown of s0/s1/s2 → outputs
├── cobra_data.c                    transcribed Cobra vertex/edge/face tables
├── commodity_table.md              transcribed commodity table
├── combat_log.md                   observed AI behaviours in BeebEm sessions
└── ghidra_exports/                 Ghidra binary exports (don't commit)
```

This directory is **partially gitignored** — large binaries (Ghidra
projects, raw dumps) shouldn't be committed; markdown notes can be.
A `.gitignore` at this level handles the split.

Update freely; this is your workspace.
