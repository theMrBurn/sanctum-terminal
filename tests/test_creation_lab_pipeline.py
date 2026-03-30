"""
tests/test_creation_lab_pipeline.py

Creation lab as live scenario testbed -- AvatarPipeline wired in.

Encounter begins on pickup (on_held), resolves on stow (on_stowed).
Ghost profile drives verb selection. Fingerprint updates from play.
Lab is the live testbed for the full pipeline.
"""
import pytest


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
