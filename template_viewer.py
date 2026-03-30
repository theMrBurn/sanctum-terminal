"""
template_viewer.py

Visual preview of all entity templates.

Controls:
    Left/Right  Cycle through templates
    R           Cycle register tint (survival/tron/tolkien/sanrio)
    Mouse       Orbit camera (hold right-click + drag)
    Scroll      Zoom in/out
    ESC         Quit

Usage:
    make viewer
"""

import sys
from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    AmbientLight, DirectionalLight, Vec4, Vec3,
    WindowProperties, TextNode, AntialiasAttrib,
    PointLight,
)
from rich.console import Console

from core.systems.entity_template import TemplateCatalog, EntityBuilder, EntityInstance
from core.systems.material_system import MaterialRegistry
from core.systems.billboard_renderer import BillboardRenderer

console = Console()

REGISTERS = {
    "survival": (1.0, 0.85, 0.7, 1.0),
    "tron":     (0.6, 0.9, 1.0, 1.0),
    "tolkien":  (0.85, 0.95, 0.75, 1.0),
    "sanrio":   (1.0, 0.8, 0.9, 1.0),
    "none":     (1.0, 1.0, 1.0, 1.0),
}

REGISTER_NAMES = list(REGISTERS.keys())


class TemplateViewer(ShowBase):

    def __init__(self):
        super().__init__()

        props = WindowProperties()
        props.setTitle("Sanctum -- Template Viewer")
        props.setSize(1280, 720)
        self.win.requestProperties(props)

        self.setBackgroundColor(0.12, 0.11, 0.10, 1)
        self.disableMouse()
        self.camLens.setFov(55)
        self.render.setShaderAuto()
        self.render.setAntialias(AntialiasAttrib.MMultisample)

        # Lighting
        amb = AmbientLight("amb")
        amb.setColor(Vec4(0.25, 0.23, 0.22, 1))
        self.render.setLight(self.render.attachNewNode(amb))

        sun = DirectionalLight("sun")
        sun.setColor(Vec4(0.6, 0.55, 0.45, 1))
        sn = self.render.attachNewNode(sun)
        sn.setHpr(30, -50, 0)
        self.render.setLight(sn)

        fill = DirectionalLight("fill")
        fill.setColor(Vec4(0.2, 0.22, 0.3, 1))
        fn = self.render.attachNewNode(fill)
        fn.setHpr(-120, -30, 0)
        self.render.setLight(fn)

        # Ground plane (subtle)
        from core.systems.geometry import make_plane
        ground = make_plane(10, 10, (0.15, 0.14, 0.13))
        gn = self.render.attachNewNode(ground)
        gn.setPos(0, 0, 0)

        # Template catalog + material registry
        self._catalog = TemplateCatalog()
        self._mat_registry = MaterialRegistry()
        self._mat_registry.load_all()
        self._names = self._catalog.names()
        self._index = 0
        self._register_index = 0
        self._current: EntityInstance | None = None
        self._hud = []

        # Camera orbit state
        self._cam_dist = 5.0
        self._cam_heading = 30.0
        self._cam_pitch = -25.0
        self._dragging = False
        self._last_mouse = None

        # Load first template
        self._load_current()
        self._update_camera()
        self._update_hud()

        # Controls
        self.accept("arrow_left", self._prev)
        self.accept("arrow_right", self._next)
        self.accept("r", self._cycle_register)
        self.accept("escape", sys.exit)
        self.accept("mouse3", self._start_drag)
        self.accept("mouse3-up", self._stop_drag)
        self.accept("wheel_up", self._zoom_in)
        self.accept("wheel_down", self._zoom_out)

        self.taskMgr.add(self._orbit_task, "OrbitCamera")

        console.log("[bold cyan]TEMPLATE VIEWER[/bold cyan]")
        console.log(f"  {len(self._names)} templates loaded")
        console.log("[Left/Right] cycle  [R] register  [RMB+drag] orbit  [Scroll] zoom  [ESC] quit")

    def _load_current(self):
        if self._current:
            self._current.cleanup()
            self._current = None

        if not self._names:
            return

        name = self._names[self._index]
        template = self._catalog.get(name)
        reg_name = REGISTER_NAMES[self._register_index]

        # Avatars and creatures use billboard rendering
        # Everything else uses 3D material rendering
        if template.category in ("avatar", "creature"):
            sprite_map = self._get_sprite_map(name)
            bb = BillboardRenderer(self.loader)
            self._current = bb.build(template, sprite_map, parent=self.render)
        else:
            builder = EntityBuilder(
                material_registry=self._mat_registry,
                register=reg_name,
                loader=self.loader,
            )
            self._current = builder.build(template, parent=self.render)

        # Auto-zoom based on size class
        size_map = {"small": 3.0, "medium": 5.0, "large": 8.0}
        self._cam_dist = size_map.get(template.size_class, 5.0)

        console.log(
            f"[green]{name}[/green]  "
            f"cat={template.category}  size={template.size_class}  "
            f"parts={len(self._current.parts)}  "
            f"sockets={len(self._current.sockets)}"
        )

    def _get_sprite_map(self, template_name):
        """Load sprite map for a template, or return empty dict."""
        import json
        from pathlib import Path
        # Check for a matching sprite config
        config_paths = [
            Path(f"assets/sprites/{template_name}.json"),
            Path(f"assets/sprites/monk_benevolent.json"),  # default for humanoid
        ]
        for p in config_paths:
            if p.exists():
                with open(p) as f:
                    return json.load(f)
        return {}

    def _prev(self):
        if not self._names:
            return
        self._index = (self._index - 1) % len(self._names)
        self._load_current()
        self._update_camera()
        self._update_hud()

    def _next(self):
        if not self._names:
            return
        self._index = (self._index + 1) % len(self._names)
        self._load_current()
        self._update_camera()
        self._update_hud()

    def _cycle_register(self):
        self._register_index = (self._register_index + 1) % len(REGISTER_NAMES)
        reg_name = REGISTER_NAMES[self._register_index]
        # Rebuild with new register materials
        self._load_current()
        self._update_camera()
        self._update_hud()
        console.log(f"Register: [cyan]{reg_name}[/cyan]")

    def _zoom_in(self):
        self._cam_dist = max(1.5, self._cam_dist - 0.5)
        self._update_camera()

    def _zoom_out(self):
        self._cam_dist = min(20.0, self._cam_dist + 0.5)
        self._update_camera()

    def _start_drag(self):
        self._dragging = True
        self._last_mouse = None

    def _stop_drag(self):
        self._dragging = False
        self._last_mouse = None

    def _orbit_task(self, task):
        if self._dragging and self.mouseWatcherNode.hasMouse():
            mx = self.mouseWatcherNode.getMouseX()
            my = self.mouseWatcherNode.getMouseY()
            if self._last_mouse:
                dx = mx - self._last_mouse[0]
                dy = my - self._last_mouse[1]
                self._cam_heading -= dx * 200
                self._cam_pitch = max(-80, min(-5, self._cam_pitch - dy * 100))
                self._update_camera()
            self._last_mouse = (mx, my)
        return task.cont

    def _update_camera(self):
        import math
        h_rad = math.radians(self._cam_heading)
        p_rad = math.radians(self._cam_pitch)
        # Look-at height = 1m (roughly center of most templates)
        look_z = 1.0
        x = self._cam_dist * math.cos(p_rad) * math.sin(h_rad)
        y = -self._cam_dist * math.cos(p_rad) * math.cos(h_rad)
        z = look_z - self._cam_dist * math.sin(p_rad)
        self.cam.setPos(x, y, z)
        self.cam.lookAt(0, 0, look_z)

    def _update_hud(self):
        for h in self._hud:
            h.destroy()
        self._hud = []

        if not self._names:
            return

        name = self._names[self._index]
        template = self._catalog.get(name)
        reg_name = REGISTER_NAMES[self._register_index]

        lines = [
            f"{name}  ({self._index + 1}/{len(self._names)})",
            f"category: {template.category}   size: {template.size_class}",
            f"parts: {len(template.part_names())}   sockets: {len(template.socket_names())}",
            f"register: {reg_name}",
            "",
            "[Left/Right] cycle   [R] register   [RMB] orbit   [Scroll] zoom",
        ]

        y = 0.92
        for line in lines:
            t = OnscreenText(
                text=line, pos=(-1.5, y), scale=0.048,
                fg=(0.75, 0.70, 0.60, 1),
                align=TextNode.ALeft,
            )
            self._hud.append(t)
            y -= 0.07


if __name__ == "__main__":
    TemplateViewer().run()
