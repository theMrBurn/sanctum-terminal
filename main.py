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
from core.systems.grace_handler import GraceHandler
from core.systems.interview_ui import InterviewUI
from core.vault import vault as RelicVault
from tools.daemon import VoxelWatcher
from tools.importer import VoxelTransformer as Transformer

console = Console()

MOUSE_SENSITIVITY = 0.15
PITCH_CLAMP       = 80.0
SNAP_THRESHOLD    = 200


class SanctumTerminal(ShowBase):
    def __init__(self):
        super().__init__()

        props = WindowProperties()
        props.setTitle("Sanctum Terminal — Lab")
        props.setSize(1280, 720)
        self.win.requestProperties(props)
        self.setBackgroundColor(0.02, 0.02, 0.04, 1)

        self.vault             = RelicVault()
        self.transformer       = Transformer()
        self.camera_speed      = 40.0
        self.mouse_look_active = False
        self.cam_yaw           = 0.0
        self.cam_pitch         = 0.0
        self._last_mx          = None
        self._last_my          = None
        self._interview_active = False
        self._biome_renderer   = None
        self.key_map = {
            "w": False, "s": False,
            "a": False, "d": False,
            "q": False, "e": False,
        }

        # Grace handler
        db_path    = Path("data/vault.db")
        self.grace = GraceHandler(db_path=db_path) if db_path.exists() else None

        self.disableMouse()
        self.camLens.setFov(80)
        self.cam.setPos(0, 0, 6)
        self.cam.setHpr(0, 0, 0)

        self.setup_lighting()
        self.render.setShaderAuto()
        self.render.setAntialias(AntialiasAttrib.MMultisample)

        self.export_path = Path("exports")
        self.export_path.mkdir(exist_ok=True)
        self.watcher = VoxelWatcher(str(self.export_path), self.on_relic_detected)
        self.watcher.start()

        self.setup_controls()
        self.taskMgr.add(self.update_simulation, "SimulationUpdate")
        self.taskMgr.add(self.fly_cam_task, "FlyCamTask")

        self.boot_biome_scene()

        console.log("[bold green]ALTAR ONLINE.[/bold green]")
        self.accept("escape",       self.disable_mouse_look)
        self.accept("shift-escape", self.exit_app)
        self.accept("mouse1",       self.enable_mouse_look)

    # ── Interview ─────────────────────────────────────────────────────────────

    def boot_biome_scene(self):
        """
        First boot: run viewport interview.
        Subsequent boots: recover from grace checkpoint.
        """
        try:
            db_path   = Path("data/vault.db")
            recovered = self.grace.recover() if self.grace else None

            if recovered and "biome_key" in recovered:
                biome_key         = recovered["biome_key"]
                density           = recovered.get("encounter_density", 0.3)
                self.camera_speed = recovered.get("camera_speed", 40.0)
                console.log(f"[bold yellow]GRACE:[/bold yellow] Recovered — {biome_key}")
                self._spawn_biome(biome_key, density)
            else:
                # Spawn default biome silently
                self._spawn_biome("VOID", 0.3)
                self._place_overlay()
                self._show_click_to_begin()

        except Exception as e:
            console.log(f"[red]BOOT ERROR:[/red] {e}")
            if self.grace:
                self.grace.fire("system_panic", {"reason": str(e)})
            self._spawn_biome("VOID", 0.3)

    def _show_click_to_begin(self):
        """Show click-to-begin prompt — gets macOS keyboard focus."""
        try:
            from direct.gui.OnscreenText import OnscreenText
            from panda3d.core import TextNode
            self._click_prompt = OnscreenText(
                text="> Click to begin.",
                pos=(0, 0),
                scale=0.07,
                fg=(1, 1, 1, 0.8),
                align=TextNode.ACenter,
                mayChange=True,
            )
            self.accept("mouse1", self._on_click_to_begin)
        except Exception as e:
            console.log(f"[yellow]CLICK:[/yellow] {e}")
            self._start_interview()

    def _on_click_to_begin(self):
        """Player clicked — now we have keyboard focus."""
        if hasattr(self, "_click_prompt") and self._click_prompt:
            try:
                self._click_prompt.destroy()
            except Exception:
                pass
        self._start_interview()

    def _start_interview(self):
        """Launch the viewport interview."""
        # Suspend movement keys during interview
        for key in self.key_map:
            self.ignore(key)
            self.ignore(f"{key}-up")
        self._interview_active = True
        self.interview_ui = InterviewUI(
            render_root=self.render,
            on_complete=self._on_interview_complete
        )
        self.interview_ui.engine.on_complete = self._on_interview_complete
        self.interview_ui.start()

        # Bind character input
        self.win.requestProperties(self.win.getProperties())
        self.win.requestProperties(self.win.getProperties())
        self.accept("typed-character", self._handle_interview_char)
        self.accept("enter",           self._handle_interview_enter)
        self.accept("backspace",       self._handle_interview_backspace)
        # Force keyboard focus
        base.win.movePointer(0, self.win.getXSize()//2, self.win.getYSize()//2)
        # Force keyboard focus
        base.win.movePointer(0, self.win.getXSize()//2, self.win.getYSize()//2)

    def _handle_interview_char(self, char):
        if self._interview_active:
            self.interview_ui.handle_char(char)

    def _handle_interview_enter(self):
        if self._interview_active:
            self.interview_ui.handle_char("\n")

    def _handle_interview_backspace(self):
        if self._interview_active:
            self.interview_ui.handle_char("")

    def _on_interview_complete(self, config):
        """Called when interview finishes — spawn the world."""
        self._interview_active = False
        self.interview_ui._clear_text()

        biome_key         = config["biome_key"]
        density           = config["encounter_density"]
        self.camera_speed = config["camera_speed"]

        # Register first relic
        db_path = Path("data/vault.db")
        if db_path.exists():
            try:
                quest = QuestEngine(db_path=db_path, grace=self.grace)
                if config["first_relic"]["archetypal_name"] != "unnamed":
                    quest.register_event(config["first_relic"])
            except Exception as e:
                console.log(f"[yellow]RELIC:[/yellow] {e}")

        if self.grace:
            self.grace.fire("interview_complete", config)

        self._spawn_biome(biome_key, density)
        self._reveal_world()

    def _spawn_biome(self, biome_key, density):
        """Spawn procedural biome geometry."""
        try:
            from core.systems.biome_renderer import BiomeRenderer

            if self._biome_renderer:
                self._biome_renderer.clear()

            self._biome_renderer = BiomeRenderer(
                render_root=self.render,
                biome_key=biome_key,
                seed=42
            )
            nodes = self._biome_renderer.render_scene(encounter_density=density)

            if self.grace:
                self.grace.fire("biome_transition", {
                    "biome_key": biome_key,
                    "density":   density,
                })
                self.grace.checkpoint({
                    "biome_key":         biome_key,
                    "encounter_density": density,
                    "karma":             0.0,
                    "camera_speed":      self.camera_speed,
                })

            console.log(
                f"[bold cyan]BIOME:[/bold cyan] {biome_key} — {len(nodes)} objects."
            )
        except Exception as e:
            console.log(f"[red]BIOME ERROR:[/red] {e}")

    def _reveal_world(self):
        """
        The 'open your eyes' moment.
        Black overlay fades out — like opening your eyes.
        """
        try:
            from direct.gui.DirectFrame import DirectFrame
            from direct.interval.LerpInterval import LerpColorScaleInterval
            from direct.interval.IntervalGlobal import Sequence, Wait, Func

            # Black overlay — eyes closed
            self._overlay = DirectFrame(
                frameColor=(0, 0, 0, 1),
                frameSize=(-2, 2, -2, 2),
                parent=self.aspect2d,
                sortOrder=50,
                suppressMouse=False,
            )

            # Sequence: wait → fade out overlay (eyes open)
            reveal = Sequence(
                Wait(1.5),
                Func(self._clear_interview_text),
                LerpColorScaleInterval(
                    self._overlay, 4.0,
                    (1, 1, 1, 0),
                    (1, 1, 1, 1),
                ),
                Func(self._on_reveal_complete),
            )
            reveal.start()

        except Exception as e:
            console.log(f"[yellow]REVEAL:[/yellow] {e}")
            self._on_reveal_complete()

    def _clear_interview_text(self):
        """Clear interview UI text before reveal."""
        if hasattr(self, "interview_ui"):
            self.interview_ui._clear_text()

    def _on_reveal_complete(self):
        """Called when reveal sequence finishes — enable controls."""
        # Restore movement keys
        self.setup_controls()
        if hasattr(self, "_overlay") and self._overlay:
            try:
                self._overlay.destroy()
            except Exception:
                pass
        console.log("[bold green]> You are here.[/bold green]")

    # ── Mouse + Movement ──────────────────────────────────────────────────────

    def enable_mouse_look(self):
        if self._interview_active:
            return
        self.mouse_look_active = True
        self._last_mx          = None
        self._last_my          = None
        props = WindowProperties()
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        self.win.requestProperties(props)
        cx = self.win.getXSize() // 2
        cy = self.win.getYSize() // 2
        self.win.movePointer(0, cx, cy)

    def disable_mouse_look(self):
        self.mouse_look_active = False
        self._last_mx          = None
        self._last_my          = None
        props = WindowProperties()
        props.setCursorHidden(False)
        props.setMouseMode(WindowProperties.M_absolute)
        self.win.requestProperties(props)

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
        model     = self.loader.loadModel(model_path)
        p         = Path(model_path)
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
            console.log(f"[bold magenta]INGESTED:[/bold magenta] {Path(file_path).name}")
            return False
        except Exception as e:
            console.log(f"[red]LOAD ERROR:[/red] {e}")
            return False

    def fly_cam_task(self, task):
        if self._interview_active:
            return task.cont

        dt    = globalClock.getDt()
        speed = self.camera_speed * dt

        if self.mouse_look_active and self.mouseWatcherNode.hasMouse():
            md = self.win.getPointer(0)
            mx = md.getX()
            my = md.getY()
            if self._last_mx is not None:
                dx = mx - self._last_mx
                dy = my - self._last_my
                if abs(dx) < SNAP_THRESHOLD and abs(dy) < SNAP_THRESHOLD:
                    self.cam_yaw   -= dx * MOUSE_SENSITIVITY
                    self.cam_pitch -= dy * MOUSE_SENSITIVITY
                    self.cam_pitch  = max(-PITCH_CLAMP, min(PITCH_CLAMP, self.cam_pitch))
                    self.cam.setHpr(self.cam_yaw, self.cam_pitch, 0)
            self._last_mx = mx
            self._last_my = my

        if self.key_map["w"]: self.cam.setPos(self.cam, 0,  speed, 0)
        if self.key_map["s"]: self.cam.setPos(self.cam, 0, -speed, 0)
        if self.key_map["a"]: self.cam.setPos(self.cam, -speed, 0, 0)
        if self.key_map["d"]: self.cam.setPos(self.cam,  speed, 0, 0)
        if self.key_map["e"]: self.cam.setPos(self.cam, 0, 0,  speed)
        if self.key_map["q"]: self.cam.setPos(self.cam, 0, 0, -speed)

        self.cam.setZ(6.0)
        return task.cont

    def update_simulation(self, task):
        if hasattr(self, "current_relic"):
            if not self.current_relic.hasPythonTag("static"):
                bob = math.sin(task.time * 1.5) * 0.1
                self.current_relic.setZ(self.current_relic.getZ() + (bob * 0.01))
        return task.cont

    def exit_app(self):
        if self.grace:
            self.grace.fire("system_panic", {"reason": "user_exit"})
        if hasattr(self, "watcher"):
            self.watcher.stop()
        sys.exit(0)


if __name__ == "__main__":
    app = SanctumTerminal()
    app.run()
