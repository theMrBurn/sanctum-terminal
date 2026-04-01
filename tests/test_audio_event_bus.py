"""
tests/test_audio_event_bus.py

CV event bus — every render event that should produce audio.
Pure logic tests. No audio, no OSC, no display.
"""

import pytest

from core.systems.audio_event_bus import (
    AudioEventBus, AudioEvent, EVENT_CATALOG,
    GATE, TRIGGER, CV, CC,
)


# -- Event catalog completeness ------------------------------------------------

class TestEventCatalog:
    """Every expected render event is registered with a type."""

    def test_catalog_not_empty(self):
        assert len(EVENT_CATALOG) > 0

    def test_all_types_valid(self):
        valid = {GATE, TRIGGER, CV, CC}
        for name, kind in EVENT_CATALOG.items():
            assert kind in valid, f"{name} has invalid type {kind}"

    def test_entity_events_exist(self):
        assert "entity.wake" in EVENT_CATALOG
        assert "entity.sleep" in EVENT_CATALOG
        assert "entity.band_enter" in EVENT_CATALOG
        assert "entity.band_exit" in EVENT_CATALOG
        assert "entity.band_crossfade" in EVENT_CATALOG

    def test_membrane_events_exist(self):
        assert "membrane.decal_on" in EVENT_CATALOG
        assert "membrane.decal_off" in EVENT_CATALOG
        assert "membrane.mote_spawn" in EVENT_CATALOG

    def test_player_events_exist(self):
        assert "player.step" in EVENT_CATALOG
        assert "player.velocity" in EVENT_CATALOG
        assert "player.heading_delta" in EVENT_CATALOG

    def test_chunk_events_exist(self):
        assert "chunk.enter" in EVENT_CATALOG
        assert "chunk.build" in EVENT_CATALOG
        assert "chunk.despawn" in EVENT_CATALOG
        assert "tile.enter" in EVENT_CATALOG

    def test_contact_events_exist(self):
        assert "contact.hard" in EVENT_CATALOG
        assert "contact.soft" in EVENT_CATALOG
        assert "contact.creature" in EVENT_CATALOG
        assert "contact.surface" in EVENT_CATALOG

    def test_environment_events_exist(self):
        assert "chrono.phase" in EVENT_CATALOG
        assert "chrono.night_weight" in EVENT_CATALOG
        assert "register.switch" in EVENT_CATALOG
        assert "fog.density" in EVENT_CATALOG

    def test_torch_events_exist(self):
        assert "torch.flicker" in EVENT_CATALOG
        assert "torch.proximity" in EVENT_CATALOG

    def test_proximity_events_exist(self):
        assert "proximity.nearest" in EVENT_CATALOG
        assert "proximity.density" in EVENT_CATALOG

    def test_gate_events_are_gates(self):
        gates = [k for k, v in EVENT_CATALOG.items() if v == GATE]
        assert len(gates) >= 5  # wake, sleep, band_enter, band_exit, decal_on/off

    def test_cv_events_are_continuous(self):
        cvs = [k for k, v in EVENT_CATALOG.items() if v == CV]
        assert len(cvs) >= 5  # velocity, proximity, night_weight, etc.

    def test_trigger_events_are_momentary(self):
        triggers = [k for k, v in EVENT_CATALOG.items() if v == TRIGGER]
        assert len(triggers) >= 5  # step, chunk events, contacts


# -- AudioEvent ----------------------------------------------------------------

class TestAudioEvent:

    def test_event_fields(self):
        e = AudioEvent("entity.wake", GATE, value=1.0, channel=3,
                        note=72, velocity=100, entity_kind="crystal_cluster",
                        pos=(10, 20, 0), timestamp=1.5)
        assert e.name == "entity.wake"
        assert e.kind == GATE
        assert e.value == 1.0
        assert e.channel == 3
        assert e.note == 72
        assert e.velocity == 100
        assert e.entity_kind == "crystal_cluster"
        assert e.pos == (10, 20, 0)
        assert e.timestamp == 1.5

    def test_defaults(self):
        e = AudioEvent("player.step", TRIGGER)
        assert e.value == 1.0
        assert e.channel == 0
        assert e.note == 60
        assert e.velocity == 100
        assert e.entity_kind is None
        assert e.pos is None


# -- Bus basics ----------------------------------------------------------------

class TestBusEmitDrain:

    def test_emit_stores_event(self):
        bus = AudioEventBus()
        bus.emit("entity.wake", channel=3, entity_kind="rat")
        assert bus.count() == 1

    def test_drain_returns_and_clears(self):
        bus = AudioEventBus()
        bus.emit("entity.wake")
        bus.emit("entity.sleep")
        events = bus.drain()
        assert len(events) == 2
        assert bus.count() == 0

    def test_drain_named(self):
        bus = AudioEventBus()
        bus.emit("entity.wake")
        bus.emit("player.step")
        bus.emit("entity.wake")
        wakes = bus.drain_named("entity.wake")
        assert len(wakes) == 2
        assert bus.count() == 1  # player.step remains

    def test_count_filtered(self):
        bus = AudioEventBus()
        bus.emit("entity.wake")
        bus.emit("entity.wake")
        bus.emit("player.step")
        assert bus.count("entity.wake") == 2
        assert bus.count("player.step") == 1

    def test_last_event(self):
        bus = AudioEventBus()
        bus.emit("entity.wake", channel=1)
        bus.emit("entity.wake", channel=2)
        e = bus.last("entity.wake")
        assert e.channel == 2

    def test_last_none_when_empty(self):
        bus = AudioEventBus()
        assert bus.last() is None
        assert bus.last("entity.wake") is None

    def test_clear(self):
        bus = AudioEventBus()
        bus.emit("entity.wake")
        bus.clear()
        assert bus.count() == 0

    def test_buffer_ring(self):
        bus = AudioEventBus(buffer_size=4)
        for i in range(6):
            bus.emit("player.step", velocity=i)
        assert bus.count() == 4
        events = bus.drain()
        assert events[0].velocity == 2  # oldest two dropped

    def test_clock_advances(self):
        bus = AudioEventBus()
        bus.tick(0.5)
        bus.emit("player.step")
        bus.tick(0.5)
        bus.emit("player.step")
        events = bus.drain()
        assert events[0].timestamp == 0.5
        assert events[1].timestamp == 1.0


# -- Enable/disable -----------------------------------------------------------

class TestBusEnableDisable:

    def test_disabled_ignores_emit(self):
        bus = AudioEventBus()
        bus.disable()
        bus.emit("entity.wake")
        assert bus.count() == 0

    def test_re_enable(self):
        bus = AudioEventBus()
        bus.disable()
        bus.emit("entity.wake")
        bus.enable()
        bus.emit("entity.wake")
        assert bus.count() == 1


# -- Subscriber dispatch -------------------------------------------------------

class TestBusSubscribe:

    def test_exact_match(self):
        bus = AudioEventBus()
        received = []
        bus.subscribe("entity.wake", lambda e: received.append(e))
        bus.emit("entity.wake")
        bus.emit("entity.sleep")
        assert len(received) == 1
        assert received[0].name == "entity.wake"

    def test_prefix_glob(self):
        bus = AudioEventBus()
        received = []
        bus.subscribe("entity.*", lambda e: received.append(e))
        bus.emit("entity.wake")
        bus.emit("entity.sleep")
        bus.emit("player.step")
        assert len(received) == 2

    def test_wildcard_all(self):
        bus = AudioEventBus()
        received = []
        bus.subscribe("*", lambda e: received.append(e))
        bus.emit("entity.wake")
        bus.emit("player.step")
        bus.emit("chrono.phase")
        assert len(received) == 3

    def test_multiple_listeners(self):
        bus = AudioEventBus()
        a, b = [], []
        bus.subscribe("entity.wake", lambda e: a.append(e))
        bus.subscribe("entity.wake", lambda e: b.append(e))
        bus.emit("entity.wake")
        assert len(a) == 1
        assert len(b) == 1

    def test_unsubscribe(self):
        bus = AudioEventBus()
        received = []
        cb = lambda e: received.append(e)
        bus.subscribe("entity.wake", cb)
        bus.emit("entity.wake")
        bus.unsubscribe("entity.wake", cb)
        bus.emit("entity.wake")
        assert len(received) == 1


# -- Pattern matching edge cases -----------------------------------------------

class TestPatternMatching:

    def test_exact_no_false_prefix(self):
        bus = AudioEventBus()
        received = []
        bus.subscribe("entity.wake", lambda e: received.append(e))
        bus.emit("entity.wake_up")  # should NOT match
        assert len(received) == 0

    def test_glob_requires_dot(self):
        bus = AudioEventBus()
        received = []
        bus.subscribe("entity.*", lambda e: received.append(e))
        bus.emit("entity_other")  # no dot — should NOT match
        assert len(received) == 0

    def test_no_match_no_dispatch(self):
        bus = AudioEventBus()
        received = []
        bus.subscribe("player.*", lambda e: received.append(e))
        bus.emit("entity.wake")
        assert len(received) == 0


# -- Event type classification -------------------------------------------------

class TestEventTypes:
    """Emitted events get their type from the catalog."""

    def test_gate_event_type(self):
        bus = AudioEventBus()
        bus.emit("entity.wake")
        e = bus.last()
        assert e.kind == GATE

    def test_trigger_event_type(self):
        bus = AudioEventBus()
        bus.emit("player.step")
        e = bus.last()
        assert e.kind == TRIGGER

    def test_cv_event_type(self):
        bus = AudioEventBus()
        bus.emit("player.velocity", value=0.75)
        e = bus.last()
        assert e.kind == CV
        assert e.value == 0.75

    def test_cc_event_type(self):
        bus = AudioEventBus()
        bus.emit("register.switch", value=2)
        e = bus.last()
        assert e.kind == CC

    def test_unknown_event_defaults_to_trigger(self):
        bus = AudioEventBus()
        bus.emit("custom.unknown")
        e = bus.last()
        assert e.kind == TRIGGER


# -- Ghost audio seed integration (config verification) ------------------------

class TestGhostAudioSeedMapping:
    """Verify AUDIO_GHOST_SEEDS config maps correctly to bus events."""

    def _get_seeds(self):
        # Import from cavern2 module-level constant
        import importlib
        import sys
        # Load just the constant, not the full ShowBase app
        import types
        mod = types.ModuleType("_seed_loader")
        import ast
        from pathlib import Path
        src = Path("cavern2.py").read_text()
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "AUDIO_GHOST_SEEDS":
                        code = compile(ast.Expression(body=node.value), "cavern2.py", "eval")
                        return eval(code)
        return {}

    def test_all_19_kinds_have_audio_seeds(self):
        seeds = self._get_seeds()
        expected_kinds = [
            "mega_column", "column", "boulder", "stalagmite",
            "giant_fungus", "crystal_cluster", "dead_log", "bone_pile",
            "moss_patch", "ceiling_moss", "hanging_vine",
            "grass_tuft", "rubble", "leaf_pile", "twig_scatter",
            "rat", "beetle", "spider", "leaf",
        ]
        for kind in expected_kinds:
            assert kind in seeds, f"Missing audio seed for {kind}"

    def test_all_seeds_have_required_fields(self):
        seeds = self._get_seeds()
        required = {"channel", "note_base", "velocity_curve", "band_response", "contact", "decay"}
        for kind, seed in seeds.items():
            for field in required:
                assert field in seed, f"{kind} missing field {field}"

    def test_channels_in_range(self):
        seeds = self._get_seeds()
        for kind, seed in seeds.items():
            assert 1 <= seed["channel"] <= 16, f"{kind} channel out of MIDI range"

    def test_notes_in_midi_range(self):
        seeds = self._get_seeds()
        for kind, seed in seeds.items():
            assert 0 <= seed["note_base"] <= 127, f"{kind} note out of MIDI range"

    def test_velocity_curves_valid(self):
        seeds = self._get_seeds()
        valid = {"linear", "log", "step"}
        for kind, seed in seeds.items():
            assert seed["velocity_curve"] in valid, f"{kind} invalid velocity curve"

    def test_band_responses_cover_all_bands(self):
        seeds = self._get_seeds()
        for kind, seed in seeds.items():
            br = seed["band_response"]
            assert 1 in br, f"{kind} missing band 1 response"
            assert 2 in br, f"{kind} missing band 2 response"
            assert 3 in br, f"{kind} missing band 3 response"

    def test_contact_types_valid(self):
        seeds = self._get_seeds()
        valid = {"percussive", "sustained", "none"}
        for kind, seed in seeds.items():
            assert seed["contact"] in valid, f"{kind} invalid contact type"

    def test_decay_types_valid(self):
        seeds = self._get_seeds()
        valid = {"natural", "gated", "frozen"}
        for kind, seed in seeds.items():
            assert seed["decay"] in valid, f"{kind} invalid decay type"

    def test_seed_to_bus_emit(self):
        """A ghost audio seed should produce a valid bus event."""
        seeds = self._get_seeds()
        bus = AudioEventBus()
        seed = seeds["crystal_cluster"]
        bus.emit("entity.band_enter", channel=seed["channel"],
                 note=seed["note_base"], velocity=100,
                 entity_kind="crystal_cluster", pos=(10, 20, 0))
        e = bus.last()
        assert e.channel == 3
        assert e.note == 72
        assert e.entity_kind == "crystal_cluster"


# -- Simulated render scenarios ------------------------------------------------

class TestRenderScenarios:
    """Simulate real render sequences and verify event correctness."""

    def test_entity_lifecycle(self):
        """Walk toward entity: wake → band 1 → 2 → 3. Walk away: 3 → 2 → 1 → sleep."""
        bus = AudioEventBus()
        bus.emit("entity.wake", entity_kind="boulder", channel=2)
        bus.emit("entity.band_enter", value=1, entity_kind="boulder", channel=2)
        bus.emit("entity.band_enter", value=2, entity_kind="boulder", channel=2)
        bus.emit("entity.band_enter", value=3, entity_kind="boulder", channel=2)
        bus.emit("entity.band_exit", value=3, entity_kind="boulder", channel=2)
        bus.emit("entity.band_exit", value=2, entity_kind="boulder", channel=2)
        bus.emit("entity.band_exit", value=1, entity_kind="boulder", channel=2)
        bus.emit("entity.sleep", entity_kind="boulder", channel=2)
        events = bus.drain()
        assert len(events) == 8
        assert events[0].name == "entity.wake"
        assert events[-1].name == "entity.sleep"

    def test_tile_boundary_crossing(self):
        """Cross a tile boundary — tile enter + chunk builds."""
        bus = AudioEventBus()
        bus.emit("tile.enter", pos=(288, 0, 0))
        for i in range(3):
            bus.emit("chunk.build", pos=(288 + i * 16, 0, 0))
        events = bus.drain()
        assert events[0].name == "tile.enter"
        assert bus.count() == 0

    def test_chronometer_cycle(self):
        """Day→night cycle emits continuous CV."""
        bus = AudioEventBus()
        for nw in [0.0, 0.25, 0.5, 0.75, 1.0]:
            bus.emit("chrono.night_weight", value=nw)
        events = bus.drain()
        assert len(events) == 5
        assert events[0].value == 0.0
        assert events[-1].value == 1.0

    def test_register_switch(self):
        bus = AudioEventBus()
        bus.emit("register.switch", value=2)  # tolkien
        e = bus.last()
        assert e.kind == CC
        assert e.value == 2

    def test_player_movement_stream(self):
        """Walking produces velocity CV + periodic step triggers."""
        bus = AudioEventBus()
        for i in range(10):
            bus.tick(0.1)
            bus.emit("player.velocity", value=0.6)
            if i % 3 == 0:
                bus.emit("player.step", velocity=80)
        steps = bus.drain_named("player.step")
        velocities = bus.drain_named("player.velocity")
        assert len(steps) == 4    # frames 0, 3, 6, 9
        assert len(velocities) == 10
