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

from core.systems.quest_engine import QuestEngine
from core.systems.spawn_engine import SpawnEngine
from core.vault import vault as RelicVault
from tools.daemon import VoxelWatcher
from tools.importer import VoxelTransformer as Transformer

console = Console()


class SanctumTerminal(ShowBase):
    def __init__(self):
        super().__init__()

        # 1. Window & Lab Setup
        props = WindowProperties()
        props.setTitle("Sanctum Terminal — Lab")
        props.setSize(1920, 1080)
        self.win.requestProperties(props)
        self.setBackgroundColor(0.02, 0.02, 0.04, 1)
        props.setFullscreen(True)


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

        # 3. Camera
        self.disableMouse()
        self.cam.setPos(0, -30, 3)
        self.cam.lookAt(0, 10, 0)

        # 4. Lighting
        self.setup_lighting()
        self.render.setShaderAuto()
        self.render.setAntialias(AntialiasAttrib.MMultisample)

        # 5. VoxelMax Watcher
        self.export_path = Path("exports")
        self.export_path.mkdir(exist_ok=True)
        self.watcher = VoxelWatcher(str(self.export_path), self.on_relic_detected)
        self.watcher.start()

        # 6. Tasks + Controls
        self.setup_controls()
        self.taskMgr.add(self.update_simulation, "SimulationUpdate")
        self.taskMgr.add(self.fly_cam_task, "FlyCamTask")

        # 7. Boot biome scene from SpawnEngine
        self.boot_biome_scene()

        # 8. Legacy relic boot
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

    def boot_biome_scene(self):
        """Renders procedural biome geometry on boot."""
        try:
            from pathlib import Path

            from core.systems.biome_renderer import BiomeRenderer
            from core.systems.quest_engine import QuestEngine

            db_path = Path("data/vault.db")
            quest = QuestEngine(db_path=db_path) if db_path.exists() else None

            if quest:
                rules = quest.get_active_biome_rules()
                density = rules.get("encounter_density", 0.3)
                override = rules.get("biome_override")
                biome_key = override if override else "VOID"
            else:
                density = 0.3
                biome_key = "VERDANT"

            renderer = BiomeRenderer(
                render_root=self.render, biome_key=biome_key, seed=42
            )
            nodes = renderer.render_scene(encounter_density=density)
            console.log(
                f"[bold cyan]BIOME:[/bold cyan] {biome_key} — {len(nodes)} objects rendered."
            )
        except Exception as e:
            console.log(f"[red]BIOME ERROR:[/red] {e}")

    def setup_lighting(self):
        dlight = DirectionalLight("dlight")
        dlight.setColor(Vec4(1, 0.95, 0.8, 1))
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
        model = self.loader.loadModel(model_path)
        p = Path(model_path)
        json_path = p.with_suffix(".json")
        if json_path.exists():
            with open(json_path, "r") as f:
                config = json.load(f)
                model.setScale(config.get("render_scale", 1.0))
                model.setZ(config.get("y_offset", 0.0))
                if "GLO_" in p.name:
                    model.setPythonTag("static", True)
                if not config.get("shadow_cast", True):
                    model.setShadowCaster(False)
        else:
            model.setScale(0.05)
        return model

    def load_relic(self, file_path):
        try:
            if hasattr(self, "current_relic"):
                self.current_relic.removeNode()
            self.current_relic = self.smart_load(file_path)
            self.current_relic.reparentTo(self.render)
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
            if not self.current_relic.hasPythonTag("static"):
                bob = math.sin(task.time * 1.5) * 0.1
                self.current_relic.setZ(self.current_relic.getZ() + (bob * 0.01))
        return task.cont

    def exit_app(self):
        if hasattr(self, "watcher"):
            self.watcher.stop()
        sys.exit(0)


if __name__ == "__main__":
    app = SanctumTerminal()
    app.run()
