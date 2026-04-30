# ok, Palette family alignment audit — walkthrough

**Goal:** verify each kind class's hue family is intentional, not accidental drift. Tag + screenshot per stop, I correlate timestamps to telemetry on your return.

**Why this audit:** `design_thoughts.txt` calls for "verify organic kinds' hue keys (giant_fungus / moss_patch / bone_pile / toadstool / spore_pod) for intentional chromatic mismatch vs. accidental scatter." Pure observation pass — no code changes during the walk. I'll propose config diffs based on what you see.

**Tag modifier convention** (existing key bindings — no new keys to learn):

| Modifier | Reason | Use for |
|---|---|---|
| (plain) `T` | `neutral` | Catalog shot — "this is what kind X looks like in situ" |
| `Shift+T` | `interesting` | Aligned but worth noting — "this works because…" |
| `Alt+T` | `beautiful` | Strong hit — "this palette is exactly right" |
| `Ctrl+T` | `dangerous` | Wrong — "this clashes / breaks the family" |
| `Cmd+T` | `weird` | Surprising / unintentional — "didn't expect this combo" |

---

## The walk — 6 stops, ~10 min

Brain is alive on :9877, auto-arm is wired (return to hub within 12m of (0, -14) re-arms a scout after 5s cooldown). Reload the Godot scene, then walk this loop. The HUD will show position so you can confirm you're at each stop's rough zone.

### Stop 1 — Hub center (0, 0)
Press **H** to teleport to the south arch (0, -14), then walk north into the hub interior. You should see at minimum: mega_column at axis_mundi, columns at the cardinal arches, possibly buttress.

**What to read:**
- **Structural class** (mega_column, column, buttress, doorframe). All warm dark stone family — `color_base ≈ [0.25, 0.22, 0.19]`. Look for: do they read as the SAME stone family, or is one straying warm/cool?
- Tag `T` neutral with a column or mega in frame.

### Stop 2 — Mid-distance, geological mix
Walk 30m out from hub in any direction. Find a cluster with **boulder + stalagmite + rubble** in frame.

**What to read:**
- **Geological class**. boulder/stalagmite/rubble share a class. Should be brownish-warm-grey family. Look for: is rubble noticeably different in tone from the boulders it sits next to (intentional — rubble is `vertex_colors=true` baked, others use facet shader)?
- Tag `Alt+T` if it reads as one cohesive stone family. `Ctrl+T` if rubble looks plastic / out of family.

### Stop 3 — A toadstool / fungus cluster
Find **giant_fungus** or **toadstool** in frame (purple cap + pale stem). 30-40m out.

**What to read:**
- **Organic_flora class**. Cap should be saturated purple, stem a desaturated pale stone-ish, base darker. The fungal palette is INTENTIONALLY "wearing" the geological palette in shape (mycelium camouflage per `design_mycelium_camouflage`) but breaking it in color.
- Tag `Alt+T` if the cap-stem-base color story reads. `Cmd+T` if something feels wrong but you can't quite name it.

### Stop 4 — A crystal_cluster
Crystals are blue/violet, slightly emissive, listen to light pipes. Find one within 40m.

**What to read:**
- **Crystalline class**. Should pop cool against the warm stone of stops 1-2. The `light_reactive: true` flag means they should show subtle accent lift. Look for: do they read as glowing or just colored?
- Tag `T` neutral. If they're emissive enough to feel "lit from within", `Alt+T`.

### Stop 5 — Tissue scatter (ground level)
Stop at any spot where you can see **moss_patch + grass_tuft + cave_gravel + rubble** all near your feet (within 5-10m). Look DOWN.

**What to read:**
- **Tissue layer mix.** moss is green-purple-toned, grass is greenish-yellow, gravel is warm grey, rubble is warm tan-grey. Are they distinct ENOUGH that the eye reads them as different surface types, or do they blur into one beige mush?
- Tag `Ctrl+T` if it's all the same value/saturation (= bad — palette flattens). `Alt+T` if there's clear material differentiation.

### Stop 6 — Atmosphere kinds (look up)
Find **firefly** + **filament** + **hanging_vine** + **ceiling_moss**. Drape kinds attach to ceiling; fireflies bob mid-air.

**What to read:**
- **Atmosphere class.** Cool/luminous colors — fireflies should be warm gold-amber dots, filaments cool blue-violet vertical strands, vines green-organic. Look for: is the ceiling/atmosphere layer feeling "alive" with these or just decorative?
- Tag whatever fits; honestly this one is the hardest to call.

---

## After the walk

Open the brain log briefly — `tail /tmp/brain.log` — to confirm tile streaming was healthy throughout (no errors).

Then ping me with "audit done". I'll:
1. Read every JSON sidecar from this walk
2. Open the screenshots in order
3. Map each tag's reason against the kind_counts and crosshair entries to deduce what you saw
4. Propose any per-class or per-kind palette tweaks in `kind_config.json` as small atomic commits

If a palette feels right as-is (most likely outcome), no code changes — we just close the audit task and move on. If something's clearly drifted, we tune it one kind at a time per `feedback_one_change_confirm`.

---

## Notes for me (Claude) on what to correlate

- Tag JSON `crosshair[*]` shows the 5 nearest entities to the reticle with `kind`, `r/g/b` (linear color), `distance`, `angular_size`. The colors there are the actual instance vertex colors (post jitter) — that's the source of truth, not the kind_config defaults.
- `kind_counts` confirms what KIND was in frame so I can match the user's tag reason to the right family.
- The `tag_reason` modifier tells me valence — the user's intent for that observation.
- `design_thoughts.txt` (Desktop) item 8 is the audit's source spec — re-read on session resume if needed.
