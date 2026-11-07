# AGENTS.md — flipper/sanctum_rpg

Subsystem doctrine for the Flipper RPG, the canonical engine. It sits below the root `AGENTS.md` (read that first) and the workspace protocol, and adds to them. Each rule here came from a bug that actually shipped or nearly shipped. Ratified by the user on 2026-10-26; the source entries are in `docs/handoffs/SHARED_STATE.md` for 2026-10-22 and 2026-10-26.

## Verification rules

1. **A mutation check must compile, and its output must be read whole.** Filter for the verdict only after confirming the mutated build ran. Under `-Werror`, a compile error looks exactly like "survived".
2. **New table rows must leave every other user of the table byte-identical.** When a table-driven roll gains rows for one feature, prove the other features' streams are unchanged by replaying the old table. Two cases already: the dead's kinds against ordinary traits, and the shard guard against the outdoor goldens. Measure each change's golden moves on their own.
3. **A saved change ships with its filter, as a pair.** Every new delta kind ships with a test that it survives `deltas_apply_to_world` (the opened-grave bug class).
4. **A gate goes live only after its save round-trips,** and only after its first region is proven solvable with what that region alone places.
5. **When a spec says a display state shows "in both views", test each view.** Spec 58 claimed site forms that neither view drew.
6. **Screenshot every new mark at the device size, over the real base shading, before committing (`make shots`).** Equality and liveness tests pass a mark that is invisible at one distance, or drawn in ink over a face already shaded dark. That happened with the sarcophagus.
7. **Every way into a modal state, such as combat, sets all of its per-encounter fields fresh.** If a field is cleared only on the success exit, it leaks out through the other exits (flee, fall). That happened with the poison carry-over.
