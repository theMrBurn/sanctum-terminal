"""
tests/test_model_loader.py

ModelLoader -- loads Kenney .glb reference models with register tints.
"""
import pytest
from pathlib import Path


class TestModelLoaderContract:

    def test_importable(self):
        from core.systems.model_loader import ModelLoader
        assert ModelLoader is not None

    def test_catalog_has_entries(self):
        from core.systems.model_loader import ASSET_CATALOG
        assert len(ASSET_CATALOG) > 10

    def test_each_entry_has_required_keys(self):
        from core.systems.model_loader import ASSET_CATALOG
        for name, entry in ASSET_CATALOG.items():
            assert "file" in entry, f"{name} missing file"
            assert "scale" in entry, f"{name} missing scale"
            assert "category" in entry, f"{name} missing category"

    def test_kenney_path_exists(self):
        from core.systems.model_loader import KENNEY_PATH
        assert KENNEY_PATH.exists(), f"Kenney assets not found at {KENNEY_PATH}"

    def test_all_catalog_files_exist(self):
        from core.systems.model_loader import ASSET_CATALOG, KENNEY_PATH
        missing = []
        for name, entry in ASSET_CATALOG.items():
            path = KENNEY_PATH / entry["file"]
            if not path.exists():
                missing.append(f"{name}: {entry['file']}")
        assert len(missing) == 0, f"Missing files: {missing}"


class TestModelLoaderCategories:

    def test_flora_category(self):
        from core.systems.model_loader import ModelLoader
        ml = ModelLoader(None)
        flora = ml.by_category("flora")
        assert len(flora) > 5

    def test_geology_category(self):
        from core.systems.model_loader import ModelLoader
        ml = ModelLoader(None)
        geology = ml.by_category("geology")
        assert len(geology) > 2

    def test_remnant_category(self):
        from core.systems.model_loader import ModelLoader
        ml = ModelLoader(None)
        remnant = ml.by_category("remnant")
        assert len(remnant) > 3


class TestRegisterTints:

    def test_all_four_registers_have_tints(self):
        from core.systems.model_loader import REGISTER_TINTS
        for reg in ("survival", "tron", "tolkien", "sanrio"):
            assert reg in REGISTER_TINTS
