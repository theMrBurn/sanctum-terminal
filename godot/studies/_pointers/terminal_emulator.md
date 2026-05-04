# Terminal Emulator — pointer

**Origin**: https://github.com/andrea-calligaris/terminal-emulator
**License**: MIT
**Godot version**: 4.6 (matches ours)

## Why not copied locally

Phase 3 deferred. Per `design_north_star` memory: "Phase 3 teaches modding. The
terminal was always real. NEVER surface to player." This plugin is the Phase 3
endgame tool. Cloning it now clutters the studies library with content we
won't touch for months/years.

## Capabilities (summary)

- Manual character rendering (avoids RichTextLabel limitations)
- Command parsing: typed options, flags, positional args
- Auto-help via `--help` / `-h`
- Command history + tab autocomplete
- Mouse text selection + copy/paste
- Non-blocking execution (doesn't freeze UI)
- Multi-line input (Shift+Enter)
- Word-based cursor navigation (Ctrl/Alt+arrows)

## When to clone

Phase 3 milestone trigger fires. Before then, the studies folder stays
uncluttered.

## Pair with

- `SimpleGodotCRTShader` (awesome-godot) — for CRT look on terminal reveal
