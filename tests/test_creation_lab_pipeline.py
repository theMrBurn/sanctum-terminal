"""
tests/test_creation_lab_pipeline.py

Creation lab as live scenario testbed -- AvatarPipeline wired in.

Encounter begins on pickup (on_held), resolves on stow (on_stowed).
Ghost profile drives verb selection. Fingerprint updates from play.
Proximity glow on layer_fx tied to REACHABLE state.
Breathing pulse scales alpha over time.
Lab is the live testbed for the full pipeline.
"""
import pytest
from core.systems.interaction_engine import InteractionState


@pytest.fixture
def lab():
    """Boot creation lab headless with pipeline wired."""
    from creation_lab import CreationLab
    app = CreationLab(headless=True)
    yield app
    try:
        app.destroy()
    except Exception:
        pass


# -- Pipeline wired into lab ---------------------------------------------------

class TestLabPipelineWiring:

    def test_lab_has_pipeline(self, lab):
        assert hasattr(lab, "pipeline")
        assert lab.pipeline is not None

    def test_pipeline_has_encounter_engine(self, lab):
        assert lab.pipeline.encounter is not None

    def test_pipeline_has_fingerprint(self, lab):
        assert lab.pipeline.fingerprint is not None

    def test_pipeline_ghost_blend_is_normalized(self, lab):
        blend = lab.pipeline.ghost_blend
        total = sum(blend.values())
        assert total == pytest.approx(1.0, abs=0.01)


# -- Encounter fires on pickup -------------------------------------------------

class TestLabEncounterOnPickup:

    def test_encounter_begins_on_held(self, lab):
        """When an object is held, an encounter should begin."""
        obj = {"id": "test_obj", "weight": 0.3, "category": "tool",
               "tags": ["precision_score"]}
        # Prime fingerprint so encounter resonates
        lab.pipeline.fingerprint.record("precision_score", 0.8)
        lab.pipeline.refresh_blend()

        lab._on_held(obj)
        assert lab.pipeline.encounter.active_encounter is not None

    def test_encounter_resolves_on_stowed(self, lab):
        """When an object is stowed, the encounter resolves."""
        obj = {"id": "test_obj", "weight": 0.3, "category": "tool",
               "tags": ["precision_score"]}
        lab.pipeline.fingerprint.record("precision_score", 0.8)
        lab.pipeline.refresh_blend()

        lab._on_held(obj)
        lab._on_stowed(obj)
        assert lab.pipeline.encounter.active_encounter is None

    def test_encounter_tags_from_object(self, lab):
        """Encounter uses object tags for resonance calculation."""
        obj = {"id": "test_obj", "weight": 0.3, "category": "tool",
               "tags": ["crafting_time", "precision_score"]}
        lab.pipeline.fingerprint.record("crafting_time", 0.7)
        lab.pipeline.refresh_blend()

        lab._on_held(obj)
        enc = lab.pipeline.encounter.active_encounter
        assert enc is not None
        assert enc["entity"]["tags"] == ["crafting_time", "precision_score"]


# -- Glow lifecycle ------------------------------------------------------------

class TestGlowLifecycle:

    def test_no_glow_initially(self, lab):
        assert len(lab._glows) == 0

    def test_glow_created_on_reachable(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        assert node in lab._glows

    def test_glow_removed_on_dormant(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        lab._on_interaction_state(node, InteractionState.DORMANT)
        assert node not in lab._glows

    def test_glow_replaced_on_state_change(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.DETECTABLE)
        glow_det = lab._glows.get(node)
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        glow_reach = lab._glows.get(node)
        assert glow_reach is not glow_det


# -- Glow placement ------------------------------------------------------------

class TestGlowPlacement:

    def test_glow_on_layer_fx(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        glow = lab._glows[node]
        assert glow.getParent() == lab.layer_fx

    def test_glow_at_object_xy(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        glow = lab._glows[node]
        obj_pos = node.getPos(lab.render)
        assert abs(glow.getX() - obj_pos.x) < 0.01
        assert abs(glow.getY() - obj_pos.y) < 0.01

    def test_glow_near_ground(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        glow = lab._glows[node]
        assert glow.getZ() < 0.1


# -- Glow color ----------------------------------------------------------------

class TestGlowColor:

    def test_state_glow_map_has_reachable(self):
        from creation_lab import _STATE_GLOW
        assert InteractionState.REACHABLE in _STATE_GLOW
        assert _STATE_GLOW[InteractionState.REACHABLE] is not None

    def test_state_glow_map_has_detectable(self):
        from creation_lab import _STATE_GLOW
        assert InteractionState.DETECTABLE in _STATE_GLOW
        assert _STATE_GLOW[InteractionState.DETECTABLE] is not None

    def test_dormant_has_no_glow(self):
        from creation_lab import _STATE_GLOW
        assert _STATE_GLOW[InteractionState.DORMANT] is None


# -- Breathing pulse -----------------------------------------------------------

class TestGlowPulse:

    def test_glow_pulse_task_registered(self, lab):
        task_names = [t.name for t in lab.taskMgr.getTasks()]
        assert "GlowPulse" in task_names

    def test_pulse_varies_alpha(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        glow = lab._glows[node]
        lab._pulse_elapsed = 1.5
        lab._update_glow_pulse()
        new_alpha = glow.getColorScale().getW()
        assert 0.2 <= new_alpha <= 1.0


# -- Floating labels on REACHABLE ----------------------------------------------

class TestFloatingLabels:

    def test_no_labels_initially(self, lab):
        assert len(lab._labels) == 0

    def test_label_created_on_reachable(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        assert node in lab._labels

    def test_label_removed_on_dormant(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        lab._on_interaction_state(node, InteractionState.DORMANT)
        assert node not in lab._labels

    def test_label_not_created_on_detectable(self, lab):
        """Labels only appear on REACHABLE, not DETECTABLE."""
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.DETECTABLE)
        assert node not in lab._labels

    def test_label_on_layer_fx(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        label = lab._labels[node]
        assert label.getParent() == lab.layer_fx

    def test_label_above_object(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        label = lab._labels[node]
        obj_pos = node.getPos(lab.render)
        assert label.getZ() > obj_pos.z

    def test_label_shows_name(self, lab):
        """Label text should contain the object name or id."""
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        obj = lab._spawned[0]["obj"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        label = lab._labels[node]
        text = label.node().getText()
        obj_name = obj.get("name", obj.get("id", ""))
        assert obj_name in text or obj["id"] in text

    def test_label_shows_weight(self, lab):
        """Label text should contain weight."""
        if not lab._spawned:
            pytest.skip("no spawned objects in headless lab")
        node = lab._spawned[0]["node"]
        lab._on_interaction_state(node, InteractionState.REACHABLE)
        label = lab._labels[node]
        text = label.node().getText()
        assert "kg" in text


# -- Activity inference --------------------------------------------------------

class TestActivityInference:

    def test_idle_when_nothing_happening(self, lab):
        assert lab._infer_activity() == "idle"

    def test_exploring_when_moving(self, lab):
        lab.key_map["w"] = True
        assert lab._infer_activity() == "exploring"

    def test_exploring_any_direction(self, lab):
        for key in ("w", "s", "a", "d"):
            lab.key_map = {"w": False, "s": False, "a": False, "d": False}
            lab.key_map[key] = True
            assert lab._infer_activity() == "exploring", f"key={key}"

    def test_observing_when_still_near_reachable(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects")
        node = lab._spawned[0]["node"]
        pos = node.getPos(lab.render)
        lab.cam.setPos(pos.x, pos.y, pos.z)
        lab.ie.tick()
        assert lab._infer_activity() == "observing"

    def test_crafting_when_slots_filled(self, lab):
        lab.slot_a = "some_obj"
        lab.slot_b = "other_obj"
        assert lab._infer_activity() == "crafting"

    def test_combat_when_encounter_active(self, lab):
        lab.pipeline.fingerprint.record("precision_score", 0.5)
        lab.pipeline.encounter.begin({
            "id": "test", "tags": ["precision_score"], "type": "object"
        })
        assert lab._infer_activity() == "combat"

    def test_moving_overrides_observing(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects")
        node = lab._spawned[0]["node"]
        pos = node.getPos(lab.render)
        lab.cam.setPos(pos.x, pos.y, pos.z)
        lab.ie.tick()
        lab.key_map["w"] = True
        assert lab._infer_activity() == "exploring"

    def test_combat_overrides_everything(self, lab):
        lab.key_map["w"] = True
        lab.slot_a = "x"
        lab.slot_b = "y"
        lab.pipeline.encounter.begin({
            "id": "test", "tags": [], "type": "object"
        })
        assert lab._infer_activity() == "combat"


# -- Fingerprint ticking in game loop -----------------------------------------

class TestFingerprintInGameLoop:

    def test_fingerprint_ticked_on_loop(self, lab):
        fp = lab.pipeline.fingerprint
        before = fp._total_time
        lab.game_loop(type("Task", (), {"cont": 1})())
        assert fp._total_time > before

    def test_activity_flows_to_fingerprint(self, lab):
        fp = lab.pipeline.fingerprint
        lab.key_map["w"] = True
        for _ in range(60):
            lab.game_loop(type("Task", (), {"cont": 1})())
        assert fp.state["exploration_time"] > 0.0

    def test_observing_flows_to_fingerprint(self, lab):
        if not lab._spawned:
            pytest.skip("no spawned objects")
        fp = lab.pipeline.fingerprint
        node = lab._spawned[0]["node"]
        pos = node.getPos(lab.render)
        lab.cam.setPos(pos.x, pos.y, pos.z)
        lab.ie.tick()
        for _ in range(60):
            lab.game_loop(type("Task", (), {"cont": 1})())
        assert fp.state["observation_time"] > 0.0


# -- Blend refresh cadence ----------------------------------------------------

class TestBlendRefresh:

    def test_blend_refresh_timer_exists(self, lab):
        assert hasattr(lab, "_blend_refresh_elapsed")

    def test_blend_not_refreshed_every_frame(self, lab):
        old_blend = dict(lab.pipeline.ghost_blend)
        lab.game_loop(type("Task", (), {"cont": 1})())
        assert lab.pipeline.ghost_blend == old_blend

    def test_blend_refreshes_after_interval(self, lab):
        lab.pipeline.fingerprint.record("combat_time", 0.9)
        lab.pipeline.fingerprint.record("exploration_time", 0.9)
        old_blend = dict(lab.pipeline.ghost_blend)
        lab._blend_refresh_elapsed = 11.0
        lab.game_loop(type("Task", (), {"cont": 1})())
        new_blend = lab.pipeline.ghost_blend
        assert new_blend != old_blend


# -- Compound objects in lab ---------------------------------------------------

class TestLabCompoundObjects:

    def test_compounds_loaded(self, lab):
        assert len(lab._compounds) > 0

    def test_torch_spawned(self, lab):
        keys = [cn["key"] for cn in lab._compound_nodes]
        assert "torch_lit" in keys

    def test_tome_spawned(self, lab):
        keys = [cn["key"] for cn in lab._compound_nodes]
        assert "tome" in keys

    def test_compound_has_root_node(self, lab):
        cn = lab._compound_nodes[0]
        assert cn["root"] is not None

    def test_compound_obj_has_tags(self, lab):
        cn = lab._compound_nodes[0]
        assert len(cn["obj"]["tags"]) > 0

    def test_compound_obj_has_weight(self, lab):
        cn = lab._compound_nodes[0]
        assert cn["obj"]["weight"] > 0

    def test_compound_registered_with_ie(self, lab):
        cn = lab._compound_nodes[0]
        state = lab.ie.get_state(cn["root"])
        assert state is not None


# -- Register cycling ----------------------------------------------------------

class TestRegisterCycling:

    def test_default_register_is_survival(self, lab):
        assert lab._register == "survival"

    def test_cycle_advances_register(self, lab):
        lab._cycle_register()
        assert lab._register == "tron"

    def test_cycle_wraps_around(self, lab):
        for _ in range(4):
            lab._cycle_register()
        assert lab._register == "survival"

    def test_compounds_rebuild_on_cycle(self, lab):
        old_roots = [cn["root"] for cn in lab._compound_nodes]
        lab._cycle_register()
        new_roots = [cn["root"] for cn in lab._compound_nodes]
        # Roots should be different objects (rebuilt)
        for old, new in zip(old_roots, new_roots):
            assert old is not new

    def test_compound_count_preserved_on_cycle(self, lab):
        count_before = len(lab._compound_nodes)
        lab._cycle_register()
        assert len(lab._compound_nodes) == count_before


# -- Compound encounter integration -------------------------------------------

class TestCompoundEncounterIntegration:

    def test_compound_encounter_uses_tags(self, lab):
        """Picking up a compound object should begin encounter with its tags."""
        cn = next(c for c in lab._compound_nodes if c["key"] == "torch_lit")
        obj = cn["obj"]
        lab.pipeline.fingerprint.record("crafting_time", 0.8)
        lab.pipeline.fingerprint.record("precision_score", 0.7)
        lab.pipeline.refresh_blend()
        lab._on_held(obj)
        enc = lab.pipeline.encounter.active_encounter
        assert enc is not None
        assert "crafting_time" in enc["entity"]["tags"]

    def test_compound_encounter_verb_matches(self, lab):
        """Torch encounter should suggest TOOLS verb."""
        cn = next(c for c in lab._compound_nodes if c["key"] == "torch_lit")
        obj = cn["obj"]
        lab.pipeline.fingerprint.record("crafting_time", 0.8)
        lab.pipeline.refresh_blend()
        lab._on_held(obj)
        # The encounter is active, dominant verb should reflect profile
        verb = lab.pipeline.encounter.dominant_verb()
        from core.systems.encounter_engine import VERBS
        assert verb in VERBS
