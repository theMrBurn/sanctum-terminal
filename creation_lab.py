import sys, json
from pathlib import Path
from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    AmbientLight, DirectionalLight, Vec4,
    WindowProperties, TextNode, AntialiasAttrib,
    CollisionNode, CollisionPlane,
    Plane, Point3, Vec3,
)
from rich.console import Console
from core.systems.biome_renderer import _make_box_geom, _make_plane_geom
from core.systems.crafting_engine import CraftingEngine
from core.systems.primitive_factory import PrimitiveFactory
from core.systems.inventory import Inventory
from core.systems.pickup_system import PickupSystem, PICKUP_RADIUS

console = Console()

MOUSE_SENSITIVITY = 0.15
PITCH_CLAMP       = 80.0
SNAP_THRESHOLD    = 200


def _load_lab_config():
    """Lab dimensions from config/manifest.json [lab]. Config is authority."""
    path = Path(__file__).parent / "config" / "manifest.json"
    raw  = json.load(open(path)).get("lab", {})
    return {
        "ground_z":    raw.get("ground_z",    5.0),
        "ceiling_z":   raw.get("ceiling_z",  16.0),
        "extent_x":    raw.get("extent_x",   10.0),
        "extent_y_n":  raw.get("extent_y_n", 14.0),
        "extent_y_s":  raw.get("extent_y_s",-14.0),
        "wall_margin": raw.get("wall_margin",  0.6),
        "move_speed":  raw.get("move_speed",  12.0),
        "headless":    raw.get("headless",   False),
    }


_CFG = _load_lab_config()

GROUND_Z    = _CFG["ground_z"]
LAB_CEILING = _CFG["ceiling_z"]
LAB_X       = _CFG["extent_x"]
LAB_Y_N     = _CFG["extent_y_n"]
LAB_Y_S     = _CFG["extent_y_s"]
_WALL_MARGIN = _CFG["wall_margin"]
_MOVE_SPEED  = _CFG["move_speed"]

# Weight by role -- material truth, not database field.
# The Long Dark model: what a thing is determines how much it costs to carry.
_ROLE_WEIGHT = {
    "handle":    0.3,
    "edge":      0.4,
    "cover":     0.2,
    "material":  0.8,
    "surface":   2.0,
    "container": 0.3,
    "blank":     1.0,
    "marker":    0.6,
    "fuel":      0.5,
}
_DEFAULT_WEIGHT = 0.5


def clamp_to_lab(x: float, y: float, z: float) -> tuple:
    """
    Pure function -- no ShowBase dependency. Fully testable headless.
    Returns (x, y, z) clamped to lab bounds.
    Z is always GROUND_Z -- no flying, no crouching.
    Pattern: extract logic, test the function, method delegates.
    AtmosphereModule will follow the same extraction when lighting lifts.
    """
    return (
        max(-LAB_X + _WALL_MARGIN, min(LAB_X - _WALL_MARGIN, x)),
        max(LAB_Y_S + _WALL_MARGIN, min(LAB_Y_N - _WALL_MARGIN, y)),
        GROUND_Z,
    )


class CreationLab(ShowBase):
    """
    White void creation lab -- bounded, layered, entered intentionally.
    Dimensions driven by config/manifest.json [lab].
    Scene graph follows signal_map.json [scene_graph] layer convention:

        layer_structure    -- walls, floor, ceiling (static, collision)
        layer_interactable -- shelf objects, workbench (pickupable, craftable)
        layer_fx           -- glow, labels, state indicators (coming)
        layer_hud          -- screen-space UI

    This layer model is the contract InteractionEngine will depend on.
    SignalRouter will own layer creation at boot when built.
    For now, CreationLab bootstraps the convention.

    [E] lift/stow  [G] drop  [C] craft  [X] clear  Shift+ESC quit
    """

    def __init__(self, headless=None):
        super().__init__()

        self.headless = headless if headless is not None else _CFG["headless"]

        if self.win and not self.headless:
            props = WindowProperties()
            props.setTitle("Sanctum -- Creation Lab")
            props.setSize(1280, 720)
            self.win.requestProperties(props)

        self.setBackgroundColor(0.92, 0.90, 0.88, 1)

        self.cam_yaw   = 0.0
        self.cam_pitch = 0.0
        self.mouse_look_active = False
        self._last_mx  = None
        self._last_my  = None
        self.key_map   = {"w": False, "s": False, "a": False, "d": False}

        self.engine  = CraftingEngine()
        self.factory = PrimitiveFactory()
        self.slot_a  = None
        self.slot_b  = None
        self._hud    = []
        self._spawned = []

        # -- Scene graph layers (signal_map.json [scene_graph] convention)
        # Structure first -- geometry owned here never fights interactables.
        # FX layer renders over world so glow/labels always read clearly.
        # HUD layer is screen-space, always on top.
        self.layer_structure    = self.render.attachNewNode("layer_structure")
        self.layer_interactable = self.render.attachNewNode("layer_interactable")
        self.layer_fx           = self.render.attachNewNode("layer_fx")
        self.layer_hud          = self.render.attachNewNode("layer_hud")

        # Draw order -- structure renders first, hud renders last
        self.layer_structure.setBin("opaque", 0)
        self.layer_interactable.setBin("opaque", 1)
        self.layer_fx.setBin("transparent", 0)

        # Geometry handles -- tests verify these exist
        self._walls   = []
        self._ceiling = None
        self._floor   = None

        self.inventory = Inventory()
        self.pickup    = PickupSystem(
            camera         = self.cam,
            inventory      = self.inventory,
            get_nearest_fn = self._nearest_pickupable,
            on_held_fn     = self._on_held,
            on_stowed_fn   = self._on_stowed,
            on_dropped_fn  = self._on_dropped,
            on_fail_fn     = self._on_pickup_fail,
        )

        self.disableMouse()
        self.camLens.setFov(75)
        self.cam.setPos(0, -8, GROUND_Z)
        self.cam.setHpr(0, 0, 0)
        self.render.setShaderAuto()
        self.render.setAntialias(AntialiasAttrib.MMultisample)

        self.setup_lighting()
        self.setup_controls()
        self._build_lab()
        self._update_hud()
        self.taskMgr.add(self.game_loop, "GameLoop")

        if not self.headless:
            self.accept("escape",       self.disable_mouse_look)
            self.accept("shift-escape", self.exit_app)
            self.accept("mouse1",       self.enable_mouse_look)
            console.log("[bold cyan]CREATION LAB[/bold cyan]")
            console.log("WSAD move | mouse look | [E] lift/stow | [G] drop")
            console.log("1-9 spawn | [C] craft | [X] clear | Shift+ESC quit")

    # -- Scene graph layers ----------------------------------------------------

    def _build_lab(self):
        """
        Builds lab geometry into the correct scene graph layers.
        layer_structure owns all static geometry and collision planes.
        layer_interactable owns all spawned objects.
        No geometry attaches directly to render -- layer is always the parent.
        """
        self._build_structure()
        self._build_workbench()
        self._spawn_shelf()

    def _build_structure(self):
        """
        Static geometry and collision -- all owned by layer_structure.
        Collision planes and visual geometry share the same parent,
        guaranteeing they stay aligned even if the layer moves.
        """
        S     = self.layer_structure
        depth = abs(LAB_Y_S - LAB_Y_N)
        width = LAB_X * 2
        wc    = (0.82, 0.80, 0.78)   # wall color
        wt    = 0.3                   # wall thickness

        # Floor
        fn = _make_plane_geom(int(width), int(depth), (0.88, 0.86, 0.84))
        self._floor = S.attachNewNode(fn)
        self._floor.setPos(0, 0, 0)

        # Grid -- 2m cells, orientation within bounded space
        for i in range(-5, 6):
            gn = _make_box_geom(0.04, 0.01, width, (0.78, 0.76, 0.74))
            S.attachNewNode(gn).setPos(i * 2, 0, 0.005)
            gn2 = _make_box_geom(depth, 0.01, 0.04, (0.78, 0.76, 0.74))
            S.attachNewNode(gn2).setPos(0, i * 2, 0.005)

        # North wall (behind shelf)
        nw = _make_box_geom(width, wt, LAB_CEILING, wc)
        S.attachNewNode(nw).setPos(0, LAB_Y_N, LAB_CEILING / 2)

        # South wall -- door gap centred, 3m wide
        door_w   = 3.0
        panel_w  = (width - door_w) / 2
        for sign in (-1, 1):
            pw = _make_box_geom(panel_w, wt, LAB_CEILING, wc)
            xpos = sign * (panel_w / 2 + door_w / 2)
            S.attachNewNode(pw).setPos(xpos, LAB_Y_S, LAB_CEILING / 2)

        # East wall
        ew = _make_box_geom(wt, depth, LAB_CEILING, wc)
        S.attachNewNode(ew).setPos(LAB_X, 0, LAB_CEILING / 2)

        # West wall
        ww = _make_box_geom(wt, depth, LAB_CEILING, wc)
        S.attachNewNode(ww).setPos(-LAB_X, 0, LAB_CEILING / 2)

        # Ceiling -- thin slab well above camera
        cn = _make_box_geom(width, depth, wt, wc)
        self._ceiling = S.attachNewNode(cn)
        self._ceiling.setPos(0, 0, LAB_CEILING)

        # Collision planes -- four inward-facing, owned by layer_structure
        # Geometry and collision share parent: they cannot drift apart
        for name, plane in [
            ("wall_n", Plane(Vec3( 0, -1, 0), Point3(0,      LAB_Y_N, 0))),
            ("wall_s", Plane(Vec3( 0,  1, 0), Point3(0,      LAB_Y_S, 0))),
            ("wall_e", Plane(Vec3(-1,  0, 0), Point3(LAB_X,  0,       0))),
            ("wall_w", Plane(Vec3( 1,  0, 0), Point3(-LAB_X, 0,       0))),
        ]:
            cn2 = CollisionNode(name)
            cn2.addSolid(CollisionPlane(plane))
            self._walls.append(S.attachNewNode(cn2))

        # Shelf -- north wall, 2m from wall face
        sn = _make_box_geom(width * 0.9, 0.3, 1.5, (0.55, 0.52, 0.48))
        S.attachNewNode(sn).setPos(0, LAB_Y_N - 2.0, 0.75)

    def _build_workbench(self):
        """
        Workbench lives in layer_interactable -- it is an interactive surface.
        Slot markers are children of the workbench node for correct alignment.
        """
        I = self.layer_interactable

        bench = _make_box_geom(3.0, 1.5, 1.0, (0.22, 0.18, 0.14))
        bench_np = I.attachNewNode(bench)
        bench_np.setPos(0, 0, 0.5)

        # Slot A -- left
        an = _make_box_geom(0.8, 0.05, 0.8, (0.4, 0.35, 0.28))
        bench_np.attachNewNode(an).setPos(-0.8, 0, 0.53)

        # Slot B -- right
        bn = _make_box_geom(0.8, 0.05, 0.8, (0.4, 0.35, 0.28))
        bench_np.attachNewNode(bn).setPos(0.8, 0, 0.53)

        # Output slot -- slightly forward and elevated
        on2 = _make_box_geom(0.8, 0.05, 0.8, (0.3, 0.45, 0.35))
        bench_np.attachNewNode(on2).setPos(0, -1.0, 0.58)

    def _spawn_shelf(self):
        """Spawn first 9 catalog objects onto shelf, owned by layer_interactable."""
        objs = self.engine.get_all_objects()
        keys = list(objs.keys())
        self._objects  = objs
        self._obj_keys = keys
        for i, key in enumerate(keys[:9]):
            self._spawn_on_shelf(key, i)

    # -- Camera clamping -------------------------------------------------------

    def _clamp_camera(self):
        """Delegates to pure clamp_to_lab. Called every frame."""
        x, y, z = clamp_to_lab(self.cam.getX(), self.cam.getY(), self.cam.getZ())
        self.cam.setPos(x, y, z)

    # -- Spawn -----------------------------------------------------------------

    def _make_obj_dict(self, obj_key):
        obj = dict(self._objects[obj_key])
        obj["id"]     = obj_key
        obj["weight"] = _ROLE_WEIGHT.get(obj.get("role", ""), _DEFAULT_WEIGHT)
        return obj

    def _spawn_on_shelf(self, obj_key, index):
        raw = self._objects.get(obj_key)
        if not raw:
            return
        obj = self._make_obj_dict(obj_key)
        try:
            p  = self.factory.build(
                raw["primitive"], tuple(raw["scale"]),
                tuple(raw["color"]), role=raw["role"]
            )
            np = self.layer_interactable.attachNewNode(p.geom_node)
            np.setPos((index - 4) * 2.2, LAB_Y_N - 2.0, 1.5)
            np.setHpr(index * 15, 0, 0)
            np.setPythonTag("pickupable", True)
            np.setPythonTag("obj", obj)
            self._spawned.append({"node": np, "key": obj_key, "obj": obj})
        except Exception as e:
            console.log(f"[yellow]SPAWN:[/yellow] {obj_key} -- {e}")

    def _spawn_object(self, obj_key):
        raw = self._objects.get(obj_key)
        if not raw:
            console.log(f"[red]Unknown:[/red] {obj_key}")
            return
        obj = self._make_obj_dict(obj_key)
        try:
            p  = self.factory.build(
                raw["primitive"], tuple(raw["scale"]),
                tuple(raw["color"]), role=raw["role"]
            )
            np = self.layer_interactable.attachNewNode(p.geom_node)
            np.setPos(0, -4, 1.0)
            np.setPythonTag("pickupable", True)
            np.setPythonTag("obj", obj)
            self._spawned.append({"node": np, "key": obj_key, "obj": obj})
            if self.slot_a is None:
                self.slot_a = obj_key
                np.setPos(-0.8, 0, 1.5)
                console.log(f"[green]Slot A:[/green] {obj_key}")
            elif self.slot_b is None:
                self.slot_b = obj_key
                np.setPos(0.8, 0, 1.5)
                console.log(f"[green]Slot B:[/green] {obj_key}")
            self._update_hud()
        except Exception as e:
            console.log(f"[red]SPAWN ERROR:[/red] {e}")

    # -- Nearest pickupable ----------------------------------------------------

    def _nearest_pickupable(self):
        """
        Scans layer_interactable only -- not all of render.
        This is the InteractionEngine contract: interactive objects
        live in layer_interactable, engine scans that layer.
        """
        cam_pos   = self.cam.getPos(self.render)
        best      = None
        best_dist = PICKUP_RADIUS
        for entry in self._spawned:
            np = entry["node"]
            if np.isHidden() or not np.getPythonTag("pickupable"):
                continue
            p    = np.getPos(self.render)
            dist = ((p.x - cam_pos.x)**2 + (p.y - cam_pos.y)**2) ** 0.5
            if dist < best_dist:
                best      = entry
                best_dist = dist
        return {"obj": best["obj"], "node": best["node"]} if best else None

    # -- Pickup callbacks ------------------------------------------------------

    def _on_held(self, obj):
        console.log(
            f"[cyan]holding[/cyan]  {obj['id']}  "
            f"[dim]{obj.get('description', '')}[/dim]"
        )
        self._update_hud()

    def _on_stowed(self, obj):
        console.log(
            f"[green]stowed[/green]   {obj['id']}  "
            f"[dim]{self.inventory.count()}/{self.inventory.max_slots} slots[/dim]"
        )
        self._update_hud()

    def _on_dropped(self, obj):
        console.log(f"[yellow]dropped[/yellow]  {obj['id']}")
        self._update_hud()

    def _on_pickup_fail(self, reason):
        console.log({
            "nothing_nearby": "[dim]nothing within reach[/dim]",
            "inventory_full": "[red]carrying too much[/red]",
        }.get(reason, reason))

    # -- Craft / clear ---------------------------------------------------------

    def _craft(self):
        if not self.slot_a or not self.slot_b:
            console.log("[yellow]need two objects in slots to craft[/yellow]")
            return
        result = self.engine.craft(self.slot_a, self.slot_b)
        console.log(f"[bold green]CRAFTED:[/bold green] {result['name']}")
        console.log(f"  {result['description']}")
        console.log(f"  ability: {result['ability']}")
        console.log(f"  hash: {result['provenance_hash']}")
        # Output lands in layer_interactable -- it is a world object
        rn = _make_box_geom(0.6, 0.6, 0.6, (0.6, 0.8, 0.5))
        self.layer_interactable.attachNewNode(rn).setPos(0, -1.0, 1.6)
        self.slot_a = None
        self.slot_b = None
        self._update_hud(result)

    def _clear(self):
        self.slot_a = None
        self.slot_b = None
        self._update_hud()
        console.log("[dim]slots cleared[/dim]")

    # -- HUD -------------------------------------------------------------------

    def _update_hud(self, result=None):
        for node in self._hud:
            try: node.destroy()
            except: pass
        self._hud = []
        held  = self.pickup.held_obj
        lines = [
            f"SLOT A: {self.slot_a or 'empty'}",
            f"SLOT B: {self.slot_b or 'empty'}",
            "",
            f"HELD:   {held['id'] if held else '--'}",
            f"BAG:    {self.inventory.count()}/{self.inventory.max_slots}"
            f"  {self.inventory.current_weight():.1f}kg",
            "",
            "[E] lift/stow  [G] drop  [C] craft  [X] clear",
        ]
        if result:
            lines += [
                "", f">> {result['name']}",
                result["description"],
                f"ability: {result['ability']}",
            ]
        y = 0.85
        for line in lines:
            t = OnscreenText(
                text=line, pos=(-1.5, y), scale=0.048,
                fg=(0.15, 0.12, 0.10, 1),
                align=TextNode.ALeft, mayChange=True
            )
            self._hud.append(t)
            y -= 0.07

    # -- Lighting --------------------------------------------------------------
    # Prepped for AtmosphereModule lift.
    # setup_lighting() is the wiring point -- logic will move to AtmosphereModule.
    # Inputs: render node. Outputs: three light nodes attached to scene.
    # When AtmosphereModule exists, this becomes: self.atmosphere.mount(self.render)

    def setup_lighting(self):
        sun = DirectionalLight("sun")
        sun.setColor(Vec4(1.0, 0.98, 0.94, 1))
        sn = self.render.attachNewNode(sun)
        sn.setHpr(30, -50, 0)
        self.render.setLight(sn)

        fill = DirectionalLight("fill")
        fill.setColor(Vec4(0.5, 0.55, 0.65, 1))
        fn = self.render.attachNewNode(fill)
        fn.setHpr(210, -30, 0)
        self.render.setLight(fn)

        amb = AmbientLight("amb")
        amb.setColor(Vec4(0.55, 0.52, 0.48, 1))
        self.render.setLight(self.render.attachNewNode(amb))

    # -- Controls --------------------------------------------------------------

    def setup_controls(self):
        for key in self.key_map:
            self.accept(key,         self.update_key_map, [key, True])
            self.accept(f"{key}-up", self.update_key_map, [key, False])
        self.accept("e", self.pickup.on_e_pressed)
        self.accept("g", self.pickup.on_drop_pressed)
        self.accept("c", self._craft)
        self.accept("x", self._clear)
        for i in range(9):
            self.accept(str(i + 1), self._spawn_by_number, [i])

    def _spawn_by_number(self, index):
        if index < len(self._obj_keys):
            self._spawn_object(self._obj_keys[index])

    def update_key_map(self, key, val):
        self.key_map[key] = val

    # -- Mouse look ------------------------------------------------------------

    def enable_mouse_look(self):
        self.mouse_look_active = True
        self._last_mx = None
        self._last_my = None
        if self.win:
            props = WindowProperties()
            props.setCursorHidden(True)
            props.setMouseMode(WindowProperties.M_relative)
            self.win.requestProperties(props)

    def disable_mouse_look(self):
        self.mouse_look_active = False
        if self.win:
            props = WindowProperties()
            props.setCursorHidden(False)
            props.setMouseMode(WindowProperties.M_absolute)
            self.win.requestProperties(props)

    # -- Game loop -------------------------------------------------------------

    def game_loop(self, task):
        dt = globalClock.getDt()

        if self.mouse_look_active and self.win and self.mouseWatcherNode.hasMouse():
            md = self.win.getPointer(0)
            mx, my = md.getX(), md.getY()
            if self._last_mx is not None:
                dx = mx - self._last_mx
                dy = my - self._last_my
                if abs(dx) < SNAP_THRESHOLD and abs(dy) < SNAP_THRESHOLD:
                    self.cam_yaw   -= dx * MOUSE_SENSITIVITY
                    self.cam_pitch -= dy * MOUSE_SENSITIVITY
                    self.cam_pitch  = max(-PITCH_CLAMP, min(PITCH_CLAMP, self.cam_pitch))
                    self.cam.setHpr(self.cam_yaw, self.cam_pitch, 0)
            self._last_mx, self._last_my = mx, my

        if self.key_map["w"]: self.cam.setPos(self.cam, 0,  _MOVE_SPEED * dt, 0)
        if self.key_map["s"]: self.cam.setPos(self.cam, 0, -_MOVE_SPEED * dt, 0)
        if self.key_map["a"]: self.cam.setPos(self.cam, -_MOVE_SPEED * dt, 0, 0)
        if self.key_map["d"]: self.cam.setPos(self.cam,  _MOVE_SPEED * dt, 0, 0)

        self._clamp_camera()
        self.pickup.update(dt)
        return task.cont

    def exit_app(self):
        sys.exit(0)


if __name__ == "__main__":
    CreationLab().run()
