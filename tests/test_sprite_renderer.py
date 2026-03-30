"""
tests/test_sprite_renderer.py

SpriteRenderer -- 2D billboard pixel art in 3D world.
"""
import pytest


class TestSpriteRendererContract:

    def test_importable(self):
        from core.systems.sprite_renderer import SpriteRenderer
        assert SpriteRenderer is not None

    def test_sprite_catalog_has_monk(self):
        from core.systems.sprite_renderer import SPRITE_CATALOG
        assert "monk" in SPRITE_CATALOG

    def test_sprite_sheets_defined(self):
        from core.systems.sprite_renderer import SPRITE_SHEETS
        assert "roguelike" in SPRITE_SHEETS

    def test_sheet_has_required_keys(self):
        from core.systems.sprite_renderer import SPRITE_SHEETS
        for name, info in SPRITE_SHEETS.items():
            for key in ("path", "tile_size", "margin", "cols", "rows"):
                assert key in info, f"{name} missing {key}"

    def test_all_four_register_tints(self):
        from core.systems.sprite_renderer import SPRITE_REGISTER_TINTS
        for reg in ("survival", "tron", "tolkien", "sanrio"):
            assert reg in SPRITE_REGISTER_TINTS

    def test_catalog_entries_have_sheet(self):
        from core.systems.sprite_renderer import SPRITE_CATALOG, SPRITE_SHEETS
        for name, entry in SPRITE_CATALOG.items():
            assert entry["sheet"] in SPRITE_SHEETS, f"{name} references unknown sheet"

    def test_catalog_has_creatures(self):
        from core.systems.sprite_renderer import SPRITE_CATALOG
        creatures = [k for k in SPRITE_CATALOG if k not in ("monk", "monk_walk1", "monk_walk2")]
        assert len(creatures) >= 5


class TestSpriteSheetFile:

    def test_roguelike_sheet_exists(self):
        from pathlib import Path
        from core.systems.sprite_renderer import SPRITE_SHEETS
        path = Path(SPRITE_SHEETS["roguelike"]["path"])
        assert path.exists(), f"Sprite sheet not found at {path}"
