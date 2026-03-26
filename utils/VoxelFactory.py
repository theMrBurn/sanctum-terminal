import json
import re
import shutil
from pathlib import Path

from core.systems.biome_registry import BiomeRegistry
from core.systems.quest_engine import QuestEngine


class VoxelFactory:
    """
    Voxel state generator. Queries QuestEngine first, falls back to
    noise-based BiomeRegistry. Also handles asset sanitization and
    manifest generation for the live_assets pipeline.
    """

    def __init__(self, export_dir=None, live_dir=None, quest_engine=None):
        self.export_dir = Path(export_dir) if export_dir else None
        self.live_dir = Path(live_dir) if live_dir else None

        # Wire up QuestEngine — use provided instance or boot a default
        if quest_engine is not None:
            self.quest_engine = quest_engine
        else:
            try:
                default_db = Path(__file__).parent.parent / "data" / "vault.db"
                self.quest_engine = (
                    QuestEngine(db_path=default_db) if default_db.exists() else None
                )
            except Exception:
                self.quest_engine = None

        self.registry = BiomeRegistry(quest_engine=self.quest_engine)

    # ── Static helpers ────────────────────────────────────────────────────────

    @staticmethod
    def sanitize(val):
        """Clamps a value to 0.0-1.0. Returns 0.5 on invalid input."""
        try:
            return max(0.0, min(1.0, float(val)))
        except (TypeError, ValueError):
            return 0.5

    @staticmethod
    def sanitize_filename(name):
        """
        Normalizes filenames for cross-platform safety.
        Replaces spaces and special chars with underscores.
        Example: 'Model (1).obj' -> 'Model_1_.obj'
        """
        return re.sub(r"[^A-Za-z0-9_.\-]", "_", name)

    # ── Biome state ───────────────────────────────────────────────────────────

    def get_state(self, temperature, moisture):
        """
        Primary voxel state method.
        Queries QuestEngine-gated BiomeRegistry.
        Returns (voxel_id: str, relic_dict: dict).
        """
        t = self.sanitize(temperature)
        m = self.sanitize(moisture)
        return self.registry.get_state(t, m)

    # ── Asset pipeline ────────────────────────────────────────────────────────

    def process_all_exports(self):
        """
        Scans export_dir, sanitizes filenames, copies assets to live_dir,
        and generates manifest.json for each asset package.
        """
        if not self.export_dir or not self.export_dir.exists():
            raise FileNotFoundError(
                f"VoxelFactory: export_dir not found — {self.export_dir}"
            )
        if not self.live_dir:
            raise ValueError("VoxelFactory: live_dir is required for processing.")

        self.live_dir.mkdir(parents=True, exist_ok=True)

        for item in self.export_dir.iterdir():
            if item.is_dir():
                self._process_package(item)
            elif item.suffix.lower() in (".obj", ".png", ".jpg", ".json"):
                self._process_loose_file(item)

    def _process_package(self, package_dir):
        """Processes a single export package folder."""
        package_id = self.sanitize_filename(package_dir.name)
        dest_dir = self.live_dir / package_id
        dest_dir.mkdir(parents=True, exist_ok=True)

        obj_file = None
        textures = []

        for f in package_dir.iterdir():
            safe_name = self.sanitize_filename(f.name)
            dest_file = dest_dir / safe_name
            shutil.copy2(f, dest_file)

            if f.suffix.lower() == ".obj":
                obj_file = safe_name
            elif f.suffix.lower() in (".png", ".jpg", ".jpeg"):
                textures.append(safe_name)

        # Generate manifest if we found an obj
        if obj_file:
            self._write_manifest(dest_dir, package_id, obj_file, textures)

    def _process_loose_file(self, filepath):
        """Copies a loose file to live_dir with a sanitized name."""
        safe_name = self.sanitize_filename(filepath.name)
        shutil.copy2(filepath, self.live_dir / safe_name)

    def _write_manifest(self, dest_dir, asset_id, obj_file, textures):
        """Writes manifest.json for a processed asset package."""
        manifest = {
            "id": asset_id,
            "file": obj_file,
            "textures": textures,
            "interactable": False,
            "version": "1.0",
        }
        manifest_path = dest_dir / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
