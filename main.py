import json
import math
import sys
from pathlib import Path

from direct.showbase.ShowBase import ShowBase
from panda3d.core import (
    AmbientLight,
    AntialiasAttrib,
    DirectionalLight,
    Texture,
    Vec4,
    WindowProperties,
)
from rich.console import Console

# Project Imports
# Note: Ensure these paths match your folder structure
from core.vault import vault as RelicVault
from tools.daemon import VoxelWatcher
from tools.importer import VoxelTransformer as Transformer

console = Console()


class SanctumTerminal(ShowBase):
    def __init__(self):
        super().__init__()

        # 1. Window & Lab Setup
        props = WindowProperties()
        props.setTitle("Sanctum Simulation Lab v7.2 - Altar Mode")
        props.setSize(1280, 720)
        self.win.requestProperties(props)
        self.setBackgroundColor(0.05, 0.05, 0.07, 1)  # Deep Midnight Blue

        # 2. Simulation State
        self.vault = RelicVault()
        self.transformer = Transformer()
        self.camera_speed = 40.0
        self.key_map = {
            "w": False,
            "s": False,
            "a": False,
            "d": False,
            "q": False,
            "e": False,
        }

        # 3. Cinematic Camera Placement
        self.disableMouse()
        self.cam.setPos(0, -100, 50)
        self.cam.lookAt(0, 0, 0)

        # 4. Lighting Rig
        self.setup_lighting()
        self.render.setShaderAuto()
        self.render.setAntialias(AntialiasAttrib.MMultisample)

        # 5. The Smart Watcher
        self.export_path = Path("exports")
        self.export_path.mkdir(exist_ok=True)
        self.watcher = VoxelWatcher(str(self.export_path), self.on_relic_detected)
        self.watcher.start()

        # 6. Simulation & Input Tasks
        self.setup_controls()
        self.taskMgr.add(self.update_simulation, "SimulationUpdate")
        self.taskMgr.add(self.fly_cam_task, "FlyCamTask")

        # 7. BOOT LOGIC
        initial_relic = None
        if len(sys.argv) > 1:
            initial_relic = sys.argv[1]
        elif Path(".last_relic").exists():
            with open(".last_relic", "r") as f:
                initial_relic = f.read().strip()

        if initial_relic and Path(initial_relic).exists():
            self.taskMgr.doMethodLater(
                0.2, self.load_relic, "InitLoad", extraArgs=[initial_relic]
            )

        console.log("[bold green]ALTAR ONLINE.[/bold green] Ready for Voxel Ingestion.")
        self.accept("escape", self.exit_app)

    def setup_lighting(self):
        dlight = DirectionalLight("dlight")
        dlight.setColor(Vec4(1, 0.95, 0.8, 1))
        # Ensure shadows are chunky/low-res as requested
        dlight.setShadowCaster(True, 512, 512)
        dlnp = self.render.attachNewNode(dlight)
        dlnp.setHpr(150, -45, 0)
        self.render.setLight(dlnp)

        alight = AmbientLight("alight")
        alight.setColor(Vec4(0.2, 0.2, 0.25, 1))
        alnp = self.render.attachNewNode(alight)
        self.render.setLight(alnp)

    def setup_controls(self):
        for key in self.key_map:
            self.accept(key, self.update_key_map, [key, True])
            self.accept(f"{key}-up", self.update_key_map, [key, False])

    def update_key_map(self, key, state):
        self.key_map[key] = state

    def on_relic_detected(self, file_path):
        self.taskMgr.add(lambda t: self.load_relic(file_path), "LoadRelicTask")

    def smart_load(self, model_path):
        """The logic that reads your VoxelFactory JSONs"""
        # Load the model
        model = self.loader.loadModel(model_path)

        # Identify the JSON sidecar
        p = Path(model_path)
        json_path = p.with_suffix(".json")

        if json_path.exists():
            with open(json_path, "r") as f:
                config = json.load(f)
                model.setScale(config.get("render_scale", 1.0))
                model.setZ(config.get("y_offset", 0.0))

                # Tag GLO objects as static so they don't 'bob'
                if "GLO_" in p.name:
                    model.setPythonTag("static", True)

                # Low-fi Shadow Toggle
                if not config.get("shadow_cast", True):
                    model.setShadowCaster(False)

                console.log(
                    f"[dim cyan]JSON MAPPING:[/dim cyan] {p.name} scaled to {config.get('render_scale')}"
                )
        else:
            # Default fallback for new objects
            model.setScale(0.05)

        return model

    def load_relic(self, file_path):
        try:
            if hasattr(self, "current_relic"):
                self.current_relic.removeNode()

            # Use our Smart Load instead of the raw loader
            self.current_relic = self.smart_load(file_path)
            self.current_relic.reparentTo(self.render)

            # Force Nearest-Neighbor for that Voxel Crunch
            for tex in self.current_relic.findAllTextures():
                tex.setMagfilter(Texture.FTNearest)
                tex.setMinfilter(Texture.FTNearest)

            with open(".last_relic", "w") as f:
                f.write(str(file_path))

            console.log(
                f"[bold magenta]INGESTED:[/bold magenta] {Path(file_path).name}"
            )
            return False
        except Exception as e:
            console.log(f"[red]LOAD ERROR:[/red] {e}")
            return False

    def fly_cam_task(self, task):
        dt = globalClock.getDt()
        if self.key_map["w"]:
            self.cam.setY(self.cam, self.camera_speed * dt)
        if self.key_map["s"]:
            self.cam.setY(self.cam, -self.camera_speed * dt)
        if self.key_map["a"]:
            self.cam.setX(self.cam, -self.camera_speed * dt)
        if self.key_map["d"]:
            self.cam.setX(self.cam, self.camera_speed * dt)
        if self.key_map["e"]:
            self.cam.setZ(self.cam, self.camera_speed * dt)
        if self.key_map["q"]:
            self.cam.setZ(self.cam, -self.camera_speed * dt)
        return task.cont

    def update_simulation(self, task):
        if hasattr(self, "current_relic"):
            # Only apply hover to dynamic objects (Actors/Props)
            if not self.current_relic.hasPythonTag("static"):
                bob = math.sin(task.time * 1.5) * 0.1
                # Small movement relative to current Z
                self.current_relic.setZ(self.current_relic.getZ() + (bob * 0.01))
        return task.cont

    def exit_app(self):
        if hasattr(self, "watcher"):
            self.watcher.stop()
        sys.exit(0)


if __name__ == "__main__":
    app = SanctumTerminal()
    app.run()
