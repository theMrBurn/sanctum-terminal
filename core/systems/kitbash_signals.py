"""
core/systems/kitbash_signals.py

Persona C -- signal integration for the kitbash / greeble subsystem
(spec_kitbash_greeble.md §3 + §5).

KitbashEngine.assemble() RECEIVES a signal_state dict; it does not fetch one.
signal_map.json declares nodes but nothing in Python auto-routes them (spec
"Premise corrections"): the map is documentation, not a router. So Persona C
wires the signal flow BY HAND here -- read the LIVE AtmosphereEngine's state and
shape it into the dict the engine consumes.

Signal source (traced, grounded in the code)
---------------------------------------------
    core/systems/atmosphere_engine.py :: AtmosphereEngine
        The STATEFUL signal container. `self.state` is a dict of float signals
        including `entropy_jitter` (0.0-1.0). `snapshot()` returns a JSON-safe
        copy of the whole world state.

    There is NO shared world-state object / router. So the host's LIVE
    AtmosphereEngine must be INJECTED -- constructing a fresh one here would
    hold frozen DEFAULTS (entropy_jitter=0.0), not the live world.

    EntropyEngine (entropy_engine.py) is STATELESS pure math -- NOT a value
    source. Deliberately not used here.

signal_state shape (the engine's contract)
-------------------------------------------
    KitbashEngine reads only signal_state[ENTROPY_KEY] ("entropy") for
    selection; everything else is RECORDED for provenance but not read (see the
    engine docstring, which names "atmosphere" as exactly that recorded slot).
    Persona A tested against {"entropy": 0.0, "atmosphere": "still"}; Persona C
    fills that same "atmosphere" slot with the real live snapshot so the ledger's
    signal_snapshot captures the whole world state:

        {ENTROPY_KEY: <live entropy_jitter>, "atmosphere": <full snapshot>}
"""

from __future__ import annotations

from core.systems.kitbash_engine import ENTROPY_KEY


# -- Constants (no hardcoded tunables -- AGENTS.md line 18) --------------------

# The key on AtmosphereEngine.state that carries the entropy signal selection
# consumes. Mapped onto the engine's ENTROPY_KEY ("entropy") -- the one key
# KitbashEngine actually reads. (ENTROPY_KEY is imported from the engine rather
# than re-spelled here: single source of truth.)
ATMOSPHERE_SOURCE_KEY = "entropy_jitter"

# The nested slot in signal_state that carries the full world snapshot. Recorded
# in the ledger for provenance; NOT read by selection. Matches the engine
# docstring's own "atmosphere" example.
ATMOSPHERE_SNAPSHOT_KEY = "atmosphere"


def signal_state_from_atmosphere(atmosphere) -> dict:
    """
    Shape the LIVE AtmosphereEngine into the signal_state dict KitbashEngine
    consumes.

    `atmosphere` is the host's live AtmosphereEngine (INJECTED, not constructed
    here -- a fresh one holds frozen DEFAULTS). Reads `atmosphere.snapshot()`
    (a JSON-safe copy of live `self.state`), maps `entropy_jitter` onto the
    engine's ENTROPY_KEY, and nests the whole snapshot under
    ATMOSPHERE_SNAPSHOT_KEY so the ledger captures the full world state.

    Returns
        {ENTROPY_KEY: float, ATMOSPHERE_SNAPSHOT_KEY: dict}
    """
    snapshot = atmosphere.snapshot()
    return {
        ENTROPY_KEY:             float(snapshot[ATMOSPHERE_SOURCE_KEY]),
        ATMOSPHERE_SNAPSHOT_KEY: snapshot,
    }


def assemble_and_record(engine, base, parts, atmosphere, vault, seed=0):
    """
    Build a kitbash assembly from the LIVE atmosphere and record it in the vault
    assembly ledger.

    1. Derive signal_state from the live `atmosphere` (see
       signal_state_from_atmosphere).
    2. `engine.assemble(base, parts, signal_state, seed=seed)` -> AssemblyResult.
    3. `vault.record_assembly(result)` -> provenance_hash (INSERT OR IGNORE;
       a replay of the same base/parts/signal reproduces the same hash).

    Returns
        (AssemblyResult, provenance_hash)
    """
    signal_state = signal_state_from_atmosphere(atmosphere)
    result = engine.assemble(base, parts, signal_state, seed=seed)
    provenance_hash = vault.record_assembly(result)
    return result, provenance_hash
