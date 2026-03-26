from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    Filename,
    getModelPath,
    WindowProperties,
    BitMask32,
    loadPrcFileData,
)
import json
import builtins
from pathlib import Path


class FirstLight(ShowBase):
    def __init__(self, headless=False):
        if headless:
            loadPrcFileData("", "window-type none")
            loadPrcFileData("", "audio-library-name null")

        if hasattr(builtins, "base"):
            self.__dict__ = builtins.base.__dict__
        else:
            super().__init__()

        self.base_path = Path(__file__).parent.absolute()
        getModelPath().prependDirectory(Filename.fromOsSpecific(str(self.base_path)))
        self.live_assets = self.base_path / "data" / "live_assets"

        self.entities = []
        self.asset_lib = self._load_lib()

        if not headless:
            self.render.setShaderAuto()
            self.setup_window()

    def _load_lib(self):
        lib = {}
        if not self.live_assets.exists():
            return lib
        for folder in self.live_assets.iterdir():
            m = folder / "manifest.json"
            if m.exists():
                with open(m, "r") as f:
                    data = json.load(f)
                    lib[data["id"]] = data
        return lib

    def setup_window(self):
        self.disable_mouse()
        props = WindowProperties()
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        if self.win:
            self.win.requestProperties(props)
        self.set_background_color(0.02, 0.02, 0.04)

    def spawn(self, asset_id, pos):
        """Programmatic object placement with collision defaults."""
        data = self.asset_lib.get(asset_id)
        if not data:
            return None

        asset_path = str(self.live_assets / asset_id / data["file"])
        model = self.loader.loadModel(Filename.fromOsSpecific(asset_path))
        model.reparentTo(self.render)
        model.setPos(pos)
        model.setCollideMask(BitMask32.bit(1))
        model.setPythonTag("interactable", data.get("interactable", False))
        model.setPythonTag("id", asset_id)
        self.entities.append(model)
        return model

    def inject_relic(self, relic_data):
        """
        State-Trigger: Receives a RelicDict from QuestEngine/VoxelFactory
        and applies shader uniforms to the GPU pipeline.
        Accepts a dict of shader keys or an asset_id string for
        backwards compatibility with legacy tests.
        """
        if not relic_data:
            return None

        # Legacy support: string asset_id passed directly
        if isinstance(relic_data, str):
            data = self.asset_lib.get(relic_data)
            if not data:
                return None
            model = self.spawn(relic_data, (0, 0, 0))
            return {"node": model, "id": relic_data}

        # Primary path: RelicDict from QuestEngine
        for key, value in relic_data.items():
            self.render.setShaderInput(key, value)
        return relic_data
