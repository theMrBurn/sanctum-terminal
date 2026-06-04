# Building Sanctum RPG (`.fap`) — targets + deploy

`sanctum_rpg` is a Flipper Zero app built with **ufbt**. The host test harness
(`make test`, from `sanctum_rpg/`) is plain gcc and SDK-independent — nothing
below affects it.

`ufbt` is the venv binary `flipper/.venv/bin/ufbt` (run from `sanctum_rpg/` as
`../.venv/bin/ufbt`).

## Two isolated SDK homes (dual-target)

| Target | `UFBT_HOME` | SDK | Use |
|---|---|---|---|
| **Official** (default, live device) | `~/.ufbt` | 1.4.3 | the dev target |
| **Momentum** | `~/.ufbt-momentum` | `mntm-012` | pentest-toolkit firmware; isolated |

`mntm-012` is based on official 1.4.3, so **both report `Target 7, API 87.1`**
and one `.fap` is **cross-loadable on either firmware today**. Building against
each is insurance for a future Momentum release that bumps past official's API.
`sanctum_rpg` builds clean against **both with zero source changes** — it uses
only stock `gui` + `notification` APIs.

## Build

```sh
cd flipper/sanctum_rpg

# Official (default UFBT_HOME=~/.ufbt)
../.venv/bin/ufbt build

# Momentum
UFBT_HOME=~/.ufbt-momentum ../.venv/bin/ufbt build
```

## Output locations (gotcha)

- `ufbt build` writes to **`$UFBT_HOME/build/sanctum_rpg.fap`**:
  - official → `~/.ufbt/build/sanctum_rpg.fap`
  - momentum → `~/.ufbt-momentum/build/sanctum_rpg.fap`
- Plain `ufbt` (build **+ install**) additionally mirrors the official build to
  `sanctum_rpg/dist/`. `ufbt build` does **not** touch `dist/`, so `dist/` can
  be stale — treat **`$UFBT_HOME/build/`** as canonical.

## Deploy to a connected device

```sh
# Official device (current) — copy without launching (the dev push):
cd flipper
.venv/bin/python ~/.ufbt/current/scripts/storage.py send \
    ~/.ufbt/build/sanctum_rpg.fap /ext/apps/Games/sanctum_rpg.fap

# Or build + launch on the matching firmware:
cd flipper/sanctum_rpg
../.venv/bin/ufbt launch                              # official
UFBT_HOME=~/.ufbt-momentum ../.venv/bin/ufbt launch   # momentum
```

## Current state (2026-05-29)

Device is **Official 1.4.3** — the physical Momentum flash (WebSerial) has not
been done, so the official build is what runs. The dual-target is build-side
only; the inner dev loop is unchanged: build official → `storage.py send` →
test on device.
