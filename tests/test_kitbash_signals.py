"""
tests/test_kitbash_signals.py

Persona C -- kitbash signal integration (spec_kitbash_greeble.md §3 + §5).

Pure logic: AtmosphereEngine has zero external imports, so no Panda3D / bpy /
headless machinery is needed.

Coverage:
  (a) live entropy mapping   -- TEST: high entropy_jitter -> signal["entropy"]
      >= threshold + a snapshot; low -> < threshold.
  (b) live-not-DEFAULTS      -- TEST: a mutated atmosphere reads the LIVE value,
      not the frozen DEFAULTS (default entropy_jitter is 0.0; exact equality
      proves the live read).
  (c) assemble_and_record    -- TEST: produces an AssemblyResult AND a hash that
      vault.assembly_by_hash round-trips.
"""

import pytest

from core.systems.atmosphere_engine import AtmosphereEngine, DEFAULTS
from core.systems.kitbash_engine import (
    KitbashEngine,
    Base,
    Socket,
    Part,
    AssemblyResult,
    ENTROPY_THRESHOLD,
    ENTROPY_KEY,
)
from core.systems.kitbash_signals import (
    signal_state_from_atmosphere,
    assemble_and_record,
    ATMOSPHERE_SOURCE_KEY,
    ATMOSPHERE_SNAPSHOT_KEY,
)


# -- Fixtures -----------------------------------------------------------------

@pytest.fixture
def vault(tmp_path):
    from core.vault import vault
    return vault(db_path=tmp_path / "vault.db")


@pytest.fixture
def base():
    return Base(
        base_id="hull_alpha",
        sockets=(
            Socket(name="dorsal",    socket_type="mount", scale_class="medium"),
            Socket(name="port_wing", socket_type="mount", scale_class="medium"),
            Socket(name="antenna",   socket_type="spire", scale_class="small"),
        ),
    )


@pytest.fixture
def parts():
    return [
        Part("ind_mount_a", frozenset({"mount"}), "medium", category="industrial"),
        Part("ind_mount_b", frozenset({"mount"}), "medium", category="industrial"),
        Part("ind_spire",   frozenset({"spire"}), "small",  category="industrial"),
        Part("org_mount_a", frozenset({"mount"}), "medium", category="organic"),
        Part("org_mount_b", frozenset({"mount"}), "medium", category="organic"),
        Part("org_spire",   frozenset({"spire"}), "small",  category="organic"),
    ]


# -- (a) live entropy mapping -------------------------------------------------

class TestSignalStateFromAtmosphere:

    def test_high_entropy_maps_above_threshold(self):
        atmosphere = AtmosphereEngine()
        atmosphere.set(ATMOSPHERE_SOURCE_KEY, 0.9)   # instant (duration=0)
        signal = signal_state_from_atmosphere(atmosphere)
        assert signal[ENTROPY_KEY] >= ENTROPY_THRESHOLD
        # the full world snapshot is nested for provenance
        assert ATMOSPHERE_SNAPSHOT_KEY in signal
        assert isinstance(signal[ATMOSPHERE_SNAPSHOT_KEY], dict)
        assert signal[ATMOSPHERE_SNAPSHOT_KEY][ATMOSPHERE_SOURCE_KEY] == 0.9

    def test_low_entropy_maps_below_threshold(self):
        atmosphere = AtmosphereEngine()
        atmosphere.set(ATMOSPHERE_SOURCE_KEY, 0.1)
        signal = signal_state_from_atmosphere(atmosphere)
        assert signal[ENTROPY_KEY] < ENTROPY_THRESHOLD
        assert isinstance(signal[ATMOSPHERE_SNAPSHOT_KEY], dict)

    def test_snapshot_is_a_copy_not_the_live_state(self):
        """The nested snapshot must not alias live state (snapshot() copies)."""
        atmosphere = AtmosphereEngine()
        atmosphere.set(ATMOSPHERE_SOURCE_KEY, 0.3)
        signal = signal_state_from_atmosphere(atmosphere)
        atmosphere.set(ATMOSPHERE_SOURCE_KEY, 0.9)   # mutate AFTER snapshot
        # captured snapshot still reflects the value at capture time
        assert signal[ATMOSPHERE_SNAPSHOT_KEY][ATMOSPHERE_SOURCE_KEY] == 0.3


# -- (b) reads the LIVE value, not the frozen DEFAULTS ------------------------

class TestReadsLiveNotDefaults:

    def test_mutated_atmosphere_read_not_defaults(self):
        assert DEFAULTS[ATMOSPHERE_SOURCE_KEY] == 0.0   # baseline is stable
        atmosphere = AtmosphereEngine()
        atmosphere.set(ATMOSPHERE_SOURCE_KEY, 0.9)      # mutate live world
        signal = signal_state_from_atmosphere(atmosphere)
        # exact equality: 0.9 proves the live read, not the 0.0 default
        assert signal[ENTROPY_KEY] == 0.9

    def test_fresh_atmosphere_yields_default(self):
        """An untouched atmosphere yields the DEFAULT (contrast case)."""
        atmosphere = AtmosphereEngine()
        signal = signal_state_from_atmosphere(atmosphere)
        assert signal[ENTROPY_KEY] == DEFAULTS[ATMOSPHERE_SOURCE_KEY]


# -- (c) assemble_and_record round-trip ---------------------------------------

class TestAssembleAndRecord:

    def test_produces_result_and_roundtrips_hash(self, base, parts, vault):
        engine = KitbashEngine()
        atmosphere = AtmosphereEngine()
        atmosphere.set(ATMOSPHERE_SOURCE_KEY, 0.8)      # scavenged bias

        result, provenance_hash = assemble_and_record(
            engine, base, parts, atmosphere, vault, seed=7
        )

        assert isinstance(result, AssemblyResult)
        assert result.base_id == "hull_alpha"
        assert isinstance(provenance_hash, str) and provenance_hash

        # the recorded signal_snapshot carried the live entropy + world snapshot
        assert result.signal_snapshot[ENTROPY_KEY] == 0.8
        assert result.signal_snapshot[ATMOSPHERE_SNAPSHOT_KEY][ATMOSPHERE_SOURCE_KEY] == 0.8

        # the hash round-trips through the ledger
        row = vault.assembly_by_hash(provenance_hash)
        assert row is not None
        assert row["base_id"] == "hull_alpha"
        assert row["provenance_hash"] == provenance_hash
        assert row["socket_bindings"] == [list(b) for b in result.bindings]

    def test_live_atmosphere_changes_the_recorded_snapshot(self, base, parts, vault):
        """A different live atmosphere value lands in a different ledger row."""
        engine = KitbashEngine()

        low = AtmosphereEngine()
        low.set(ATMOSPHERE_SOURCE_KEY, 0.1)
        _, h_low = assemble_and_record(engine, base, parts, low, vault, seed=7)

        high = AtmosphereEngine()
        high.set(ATMOSPHERE_SOURCE_KEY, 0.9)
        _, h_high = assemble_and_record(engine, base, parts, high, vault, seed=7)

        # different live world -> different signal_snapshot -> different hash
        assert h_low != h_high
        assert vault.assembly_by_hash(h_low)["signal_snapshot"][ENTROPY_KEY] == 0.1
        assert vault.assembly_by_hash(h_high)["signal_snapshot"][ENTROPY_KEY] == 0.9
