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
