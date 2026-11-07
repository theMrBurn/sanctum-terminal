# AGENTS.md — flipper/sanctum_rpg

Subsystem doctrine for the Flipper RPG, the canonical engine. It sits below the root `AGENTS.md` (read that first) and the workspace protocol, and adds to them. Each rule here came from a bug that actually shipped or nearly shipped. Rules 1–7 were ratified by the user on 2026-10-26; their source entries are in `docs/handoffs/SHARED_STATE.md` for 2026-10-22 and 2026-10-26. Rules 8–11 were ratified on 2026-11-06, from that day's host-reference and turn-loop entries.

## Verification rules

1. **A mutation check must compile, and its output must be read whole.** Filter for the verdict only after confirming the mutated build ran. Under `-Werror`, a compile error looks exactly like "survived".
2. **New table rows must leave every other user of the table byte-identical.** When a table-driven roll gains rows for one feature, prove the other features' streams are unchanged by replaying the old table. Two cases already: the dead's kinds against ordinary traits, and the shard guard against the outdoor goldens. Measure each change's golden moves on their own.
3. **A saved change ships with its filter, as a pair.** Every new delta kind ships with a test that it survives `deltas_apply_to_world` (the opened-grave bug class).
4. **A gate goes live only after its save round-trips,** and only after its first region is proven solvable with what that region alone places.
5. **When a spec says a display state shows "in both views", test each view.** Spec 58 claimed site forms that neither view drew.
6. **Screenshot every new mark at the device size, over the real base shading, before committing (`make shots`).** Equality and liveness tests pass a mark that is invisible at one distance, or drawn in ink over a face already shaded dark. That happened with the sarcophagus.
7. **Every way into a modal state, such as combat, sets all of its per-encounter fields fresh.** If a field is cleared only on the success exit, it leaks out through the other exits (flee, fall). That happened with the poison carry-over.

## The host reference and the rules/shell split

The app is split in three: `game.c` (the rules, no SDK), `screens.c` (the draws) and `sanctum_rpg.c` (the Flipper shell). `make host` replays `test/host/scripts` against all three, built on the Mac, and checks the traces against `test/host/ref.sha256`.

8. **A change to `game.c`, `screens.c`, `sanctum_rpg.c`, `save_io.c` or `deltas.c` that should not alter play must pass `make host` unchanged.** Re-record with `make host-ref` only for an intended change, and say which traces moved and why: mask the fields that should move and show that the rest is identical.
9. **A planted change that the reference doesn't catch is a missing script, not a pass.** Before trusting a slice, plant one change in the code it touches and check that the reference catches it.
10. **`game.c` includes no Flipper SDK header.** A new need goes through `platform.h` (or `save_io`), and `make game-pure` must stay green.
11. **Move code between files by line range, with a script, and check each moved item is verbatim in its new home.** The reference covers 87% of lines; the rest is guarded only by being unchanged text.
