import sys, json
from pathlib import Path
from direct.showbase.ShowBase import ShowBase
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import (
    AmbientLight, DirectionalLight, PointLight, Vec4,
    WindowProperties, TextNode, AntialiasAttrib,
    CollisionNode, CollisionPlane,
    Plane, Point3, Vec3, Material, Fog,
)
from rich.console import Console
from core.systems.geometry import make_box as _make_box_geom, make_plane as _make_plane_geom
from core.systems.lab_environment import (
    ENVIRONMENT_REGISTERS, build_environment, update_lighting, update_fog,
)
from core.systems.crafting_engine import CraftingEngine
from core.systems.primitive_factory import PrimitiveFactory
from core.systems.inventory import Inventory
from core.systems.pickup_system import PickupSystem, PICKUP_RADIUS
from core.systems.interaction_engine import InteractionEngine, InteractionState
from core.systems.scenario_engine import ScenarioEngine, ScenarioState
from core.systems.avatar_pipeline import AvatarPipeline
from core.systems.biome_scene import BiomeSceneBuilder

console = Console()

MOUSE_SENSITIVITY = 0.15
PITCH_CLAMP       = 80.0
SNAP_THRESHOLD    = 200


def _load_lab_config():
    path = Path(__file__).parent / "config" / "manifest.json"
    raw  = json.load(open(path)).get("lab", {})
    atm  = raw.get("atmosphere", {})
    return {
        "ground_z":    raw.get("ground_z",    5.0),
        "extent_x":    raw.get("extent_x",   10.0),
        "extent_y_n":  raw.get("extent_y_n", 14.0),
        "extent_y_s":  raw.get("extent_y_s",-14.0),
        "wall_margin": raw.get("wall_margin",  0.6),
        "move_speed":  raw.get("move_speed",  12.0),
        "headless":    raw.get("headless",   False),
        "bg":          tuple(atm.get("background",  [0.05, 0.04, 0.04])),
        "floor_color": tuple(atm.get("floor_color", [0.14, 0.12, 0.10])),
        "wall_color":  tuple(atm.get("wall_color",  [0.18, 0.16, 0.14])),
        "grid_color":  tuple(atm.get("grid_color",  [0.20, 0.18, 0.15])),
        "bench_color": tuple(atm.get("bench_color", [0.08, 0.06, 0.05])),
        "light_sun":   tuple(atm.get("light_sun",   [1.4,  0.94, 0.82])),
        "light_fill":  tuple(atm.get("light_fill",  [0.08, 0.10, 0.16])),
        "light_amb":   tuple(atm.get("light_amb",   [0.06, 0.055, 0.05])),
        "sun_hpr":     tuple(atm.get("sun_hpr",     [15, -65, 0])),
        "wall_height": atm.get("wall_height", 14.0),
        "specular":    tuple(atm.get("specular",    [0.7, 0.65, 0.55])),
        "shininess":   atm.get("shininess", 28.0),
    }


_CFG         = _load_lab_config()
GROUND_Z     = _CFG["ground_z"]
LAB_X        = _CFG["extent_x"]
LAB_Y_N      = _CFG["extent_y_n"]
LAB_Y_S      = _CFG["extent_y_s"]
_WALL_MARGIN = _CFG["wall_margin"]
_MOVE_SPEED  = _CFG["move_speed"]

_ROLE_WEIGHT = {
    "handle": 0.3, "edge": 0.4, "cover": 0.2,
    "material": 0.8, "surface": 2.0, "container": 0.3,
    "blank": 1.0, "marker": 0.6, "fuel": 0.5,
}
_DEFAULT_WEIGHT = 0.5

# Glow colors per interaction state -- layer_fx visual language
_STATE_GLOW = {
    InteractionState.REACHABLE:  (0.9, 0.85, 0.4, 1),   # warm amber -- touchable
    InteractionState.DETECTABLE: (0.3, 0.4,  0.6, 1),   # cool blue  -- sensed
    InteractionState.DORMANT:    None,                    # no glow
}



def clamp_to_lab(x: float, y: float, z: float) -> tuple:
    """Pure fn -- no ShowBase dep. _clamp_camera delegates here."""
    return (
        max(-LAB_X + _WALL_MARGIN, min(LAB_X - _WALL_MARGIN, x)),
        max(LAB_Y_S + _WALL_MARGIN, min(LAB_Y_N - _WALL_MARGIN, y)),
        GROUND_Z,
    )


class CreationLab(ShowBase):
    """
    Creation lab -- live scenario testbed.
    InteractionEngine owns proximity state.
    ScenarioEngine owns quest state.
    PickupSystem delegates to InteractionEngine.nearest().

    Scene graph layers (signal_map.json [scene_graph]):
        layer_structure    -- walls, floor, collision
        layer_interactable -- workbench, objects
        layer_fx           -- glow, labels, state indicators

    [E] lift/stow  [G] drop  [C] craft  [X] clear
    [Q] new fetch scenario from nearest object
    Shift+ESC quit
    """

    def __init__(self, headless=None):
        super().__init__()

        self.headless = headless if headless is not None else _CFG["headless"]

        if self.win and not self.headless:
            props = WindowProperties()
            props.setTitle("Sanctum -- Creation Lab")
            props.setSize(1280, 720)
            self.win.requestProperties(props)

        bg = _CFG["bg"]
        self.setBackgroundColor(bg[0], bg[1], bg[2], 1)

        self.cam_yaw   = 0.0
        self.cam_pitch = 0.0
        self.mouse_look_active = False
        self._last_mx  = None
        self._last_my  = None
        self.key_map   = {"w": False, "s": False, "a": False, "d": False}

        self.engine    = CraftingEngine()
        self.factory   = PrimitiveFactory()
        self._objects  = self.engine.get_all_objects()
        self._obj_keys = list(self._objects.keys())
        self.slot_a    = None
        self.slot_b    = None
        self._hud      = []
        self._spawned  = []
        self._walls    = []
        self._floor    = None
        self._glows    = {}   # node -> glow NodePath on layer_fx
        self._labels   = {}   # node -> label NodePath on layer_fx

        # Compound objects -- multi-primitive with visual registers
        self._compounds     = self._load_compounds()
        self._compound_nodes = []  # [{"key": str, "root": NodePath, "obj": dict, "pos": tuple}]
        self._register       = "survival"
        self._registers      = ["survival", "tron", "tolkien", "sanrio"]
        self._biome          = "LAB"   # LAB = box room, others = biome scene
        self._biomes         = ["LAB", "VERDANT", "CHROME", "NEON", "IRON", "FROZEN"]
        self._biome_builder  = None  # initialized after layer_structure exists

        # Scene graph layers
        self.layer_structure    = self.render.attachNewNode("layer_structure")
        self.layer_interactable = self.render.attachNewNode("layer_interactable")
        self.layer_fx           = self.render.attachNewNode("layer_fx")

        # BiomeSceneBuilder -- needs layer_structure to exist
        self._biome_builder = BiomeSceneBuilder(
            self.layer_structure, seed=42, panda_loader=self.loader
        )

        # Specular -- Anno wet-stone on all interactables
        mat = Material("interactable")
        sp  = _CFG["specular"]
        mat.setSpecular(Vec4(sp[0], sp[1], sp[2], 1))
        mat.setShininess(_CFG["shininess"])
        self.layer_interactable.setMaterial(mat, 1)

        # Inventory
        self.inventory = Inventory()

        # InteractionEngine -- owns proximity state for all world objects
        # on_state_change drives layer_fx glow
        self.ie = InteractionEngine(
            camera          = self.cam,
            render          = self.render,
            on_state_change = self._on_interaction_state,
        )

        # ScenarioEngine -- owns quest state, provenance hash per scenario
        self.se           = ScenarioEngine(seed="BURN")
        self._active_sid  = None   # currently displayed scenario

        # AvatarPipeline -- ghost profile + encounter engine, default answers
        # In production, answers come from InterviewEngine. Lab uses defaults.
        self.pipeline = AvatarPipeline(answers={}, age=30, seed="BURN")
        self._blend_refresh_elapsed = 0.0
        self._blend_refresh_interval = 10.0  # seconds between ghost blend refresh

        # PickupSystem -- delegates nearest lookup to InteractionEngine
        self.pickup = PickupSystem(
            camera         = self.cam,
            inventory      = self.inventory,
            get_nearest_fn = lambda: self.ie.nearest("pickup"),
            on_held_fn     = self._on_held,
            on_stowed_fn   = self._on_stowed,
            on_dropped_fn  = self._on_dropped,
            on_fail_fn     = self._on_pickup_fail,
        )

        self.disableMouse()
        self.camLens.setFov(75)
        self.cam.setPos(0, -6, GROUND_Z)
        self.cam.setHpr(0, 0, 0)
        self.render.setShaderAuto()
        self.render.setAntialias(AntialiasAttrib.MMultisample)

        self.setup_lighting()
        self.setup_controls()
        self._build_lab()
        self._update_hud()
        self._pulse_elapsed = 0.0
        self.taskMgr.add(self._glow_pulse_task, "GlowPulse")
        self.taskMgr.add(self.game_loop, "GameLoop")

        if not self.headless:
            self.accept("escape",       self.disable_mouse_look)
            self.accept("shift-escape", self.exit_app)
            self.accept("mouse1",       self.enable_mouse_look)
            console.log("[bold cyan]CREATION LAB -- SCENARIO TESTBED[/bold cyan]")
            console.log("[E] lift/stow  [G] drop  [C] craft  [X] clear")
            console.log("[R] register  [B] biome  [Q] fetch  Shift+ESC quit")

    # -- Interaction state -> layer_fx glow ------------------------------------

    def _on_interaction_state(self, node, state: InteractionState) -> None:
        """
        Fires on every state transition.
        Drives glow indicator + floating label on layer_fx.
        Warm amber = reachable. Cool blue = detectable. None = dormant.
        Label only on REACHABLE: name + weight + one use.
        """
        # Remove existing glow for this node
        if node in self._glows:
            try: self._glows[node].removeNode()
            except: pass
            del self._glows[node]

        # Remove existing label for this node
        if node in self._labels:
            try: self._labels[node].removeNode()
            except: pass
            del self._labels[node]

        color = _STATE_GLOW.get(state)
        if color is None:
            return

        # Glow: small flat slab beneath the object, on layer_fx
        # Reads as ground contact light -- not UI, world-space
        glow_geom = _make_box_geom(0.6, 0.6, 0.04, color[:3])
        glow_np   = self.layer_fx.attachNewNode(glow_geom)
        obj_pos   = node.getPos(self.render)
        glow_np.setPos(obj_pos.x, obj_pos.y, 0.01)
        glow_np.setTransparency(True)
        glow_np.setAlphaScale(0.7)
        self._glows[node] = glow_np

        # Label: only on REACHABLE -- name + weight + one use
        if state is InteractionState.REACHABLE:
            self._create_label(node)

    # -- Glow pulse (breathing) ------------------------------------------------

    def _glow_pulse_task(self, task):
        """Breathe glow alpha between 0.4 and 0.8. Runs every frame."""
        import math
        self._pulse_elapsed += globalClock.getDt()
        self._update_glow_pulse()
        return task.cont

    def _update_glow_pulse(self):
        """Set glow alpha based on sine wave. Called from task or test."""
        import math
        alpha = 0.6 + 0.2 * math.sin(self._pulse_elapsed * 2.5)
        for glow in self._glows.values():
            try:
                glow.setColorScale(1, 1, 1, alpha)
            except Exception:
                pass

    # -- Floating labels -------------------------------------------------------

    def _create_label(self, node) -> None:
        """
        Create a floating label above the object on layer_fx.
        Shows: name + weight + one use line.
        Billboard mode: always faces camera.
        """
        obj = node.getPythonTag("obj")
        if not obj:
            return

        name   = obj.get("name", obj.get("id", "unknown"))
        weight = obj.get("weight", 0.0)
        use    = obj.get("ability", obj.get("use", obj.get("role", "")))

        lines = [name]
        lines.append(f"{weight:.1f}kg")
        if use:
            lines.append(use)

        text = "\n".join(lines)

        tn = TextNode(f"label_{id(node)}")
        tn.setText(text)
        tn.setAlign(TextNode.ACenter)
        tn.setTextColor(0.85, 0.80, 0.72, 0.9)
        tn.setShadow(0.03, 0.03)
        tn.setShadowColor(0, 0, 0, 0.6)

        label_np = self.layer_fx.attachNewNode(tn)
        obj_pos  = node.getPos(self.render)
        label_np.setPos(obj_pos.x, obj_pos.y, obj_pos.z + 1.2)
        label_np.setScale(0.3)
        label_np.setBillboardPointEye()

        self._labels[node] = label_np

    # -- Scenario wiring -------------------------------------------------------

    def _create_fetch_scenario(self) -> None:
        """
        [Q] -- create a fetch scenario from the nearest reachable object.
        Win condition: object lands in inventory.
        Demonstrates live scenario creation from world state.
        """
        nearest = self.ie.nearest("pickup")
        if nearest is None:
            console.log("[dim]no reachable object for fetch scenario[/dim]")
            return

        obj = nearest["obj"]
        obj_id = obj["id"]

        # Win when object is in inventory
        def win_fn():
            return self.inventory.get(obj_id) is not None

        sid = self.se.create(
            "fetch",
            {
                "target_id":  obj_id,
                "return_pos": (0, 2, 0),
                "objective":  f"Pick up the {obj_id.replace('_', ' ')} "
                              f"and bring it to the workbench.",
            },
            win_fn      = win_fn,
            on_complete = self._on_scenario_complete,
        )
        self.se.activate(sid)
        self._active_sid = sid
        console.log(
            f"[bold yellow]SCENARIO[/bold yellow]  fetch  "
            f"[dim]{self.se.get_provenance(sid)}[/dim]"
        )
        console.log(f"  {self.se.get_objective(sid)}")
        self._update_hud()

    def _on_scenario_complete(self, sid: str) -> None:
        console.log(f"[bold green]COMPLETE[/bold green]  {sid[:8]}  "
                    f"[dim]{self.se.get_provenance(sid)}[/dim]")
        if self._active_sid == sid:
            self._active_sid = None
        self._update_hud()

    # -- Build -----------------------------------------------------------------

    def _build_lab(self):
        I     = self.layer_interactable

        # Environment surfaces (rebuildable on register change)
        self._env_nodes = []
        self._build_environment()

        # Collision planes (permanent)
        for name, plane in [
            ("wall_n", Plane(Vec3( 0, -1, 0), Point3(0,      LAB_Y_N, 0))),
            ("wall_s", Plane(Vec3( 0,  1, 0), Point3(0,      LAB_Y_S, 0))),
            ("wall_e", Plane(Vec3(-1,  0, 0), Point3(LAB_X,  0,       0))),
            ("wall_w", Plane(Vec3( 1,  0, 0), Point3(-LAB_X, 0,       0))),
        ]:
            cn = CollisionNode(name)
            cn.addSolid(CollisionPlane(plane))
            self._walls.append(self.layer_structure.attachNewNode(cn))

        # Workbench + objects (permanent)
        bench = _make_box_geom(3.0, 1.2, 1.0, _CFG["bench_color"])
        I.attachNewNode(bench).setPos(0, 2, 0.5)

        for i, key in enumerate(self._obj_keys[:9]):
            self._spawn_at(key, ((i - 4) * 2.0, LAB_Y_N - 3.0, 0.5))

        # Compound objects -- torch and book, visible from camera start
        self._spawn_compound("torch_lit", (-3.0, 0.0, 0.0))
        self._spawn_compound("tome",      ( 3.0, 0.0, 0.0))

    def _build_environment(self):
        """Build floor, walls, grid from current register. Delegates to lab_environment."""
        nodes, reg = build_environment(
            self.layer_structure, self._register, LAB_X, LAB_Y_N, LAB_Y_S
        )
        self._env_nodes.extend(nodes)
        self._floor = nodes[0] if nodes else None
        bg = reg["background"]
        self.setBackgroundColor(bg[0], bg[1], bg[2], 1)

    def _apply_environment_register(self):
        """Rebuild environment surfaces and update lighting for current register."""
        for np in self._env_nodes:
            try:
                np.removeNode()
            except Exception:
                pass
        self._env_nodes = []
        self._build_environment()
        reg = ENVIRONMENT_REGISTERS.get(self._register, ENVIRONMENT_REGISTERS["survival"])
        self._update_lighting(reg)

    # -- Camera ----------------------------------------------------------------

    def _clamp_camera(self):
        x, y, z = clamp_to_lab(self.cam.getX(), self.cam.getY(), self.cam.getZ())
        self.cam.setPos(x, y, z)

    # -- Spawn -----------------------------------------------------------------

    def _make_obj_dict(self, key):
        obj = dict(self._objects[key])
        obj["id"]     = key
        obj["weight"] = _ROLE_WEIGHT.get(obj.get("role", ""), _DEFAULT_WEIGHT)
        return obj

    def _spawn_at(self, obj_key, pos):
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
            np.setPos(*pos)
            np.setPythonTag("pickupable", True)
            np.setPythonTag("obj", obj)
            self._spawned.append({"node": np, "key": obj_key, "obj": obj})
            # Register with InteractionEngine
            self.ie.register(np, "pickup", obj=obj)
        except Exception as e:
            console.log(f"[yellow]SPAWN:[/yellow] {obj_key} -- {e}")

    def _spawn_object(self, obj_key):
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
            np.setPos(0, 0, 0.5)
            np.setPythonTag("pickupable", True)
            np.setPythonTag("obj", obj)
            self._spawned.append({"node": np, "key": obj_key, "obj": obj})
            self.ie.register(np, "pickup", obj=obj)
            if self.slot_a is None:
                self.slot_a = obj_key
                np.setPos(-0.8, 2, 1.5)
            elif self.slot_b is None:
                self.slot_b = obj_key
                np.setPos(0.8, 2, 1.5)
            self._update_hud()
        except Exception as e:
            console.log(f"[red]SPAWN ERROR:[/red] {e}")

    # -- Compound objects ------------------------------------------------------

    @staticmethod
    def _load_compounds():
        path = Path(__file__).parent / "config" / "blueprints" / "compounds.json"
        if path.exists():
            return json.load(open(path))
        return {}

    def _spawn_compound(self, compound_key, pos):
        """
        Spawn a compound object (multi-primitive) in the current register.
        Registers with InteractionEngine. Tags flow to encounter system.
        """
        bp = self._compounds.get(compound_key)
        if not bp:
            return

        full_palette = self.factory.resolve_register_full(
            bp["registers"], self._register
        )
        parts = self.factory.from_blueprint_full(bp, full_palette)

        # Create a root node for the compound
        root = self.layer_interactable.attachNewNode(f"compound_{compound_key}")
        root.setPos(*pos)

        for p in parts:
            child = root.attachNewNode(p.geom_node)
            child.setPos(p.offset_x, p.offset_y, p.offset_z)
            # Emission: apply emissive material
            if p.emission > 0:
                mat = Material(f"emit_{p.role}")
                e = p.emission
                mat.setEmission(Vec4(
                    p.edge_color[0] * e, p.edge_color[1] * e,
                    p.edge_color[2] * e, 1.0
                ))
                child.setMaterial(mat, 1)

        # Build obj dict from blueprint metadata
        obj = {
            "id":             compound_key,
            "name":           compound_key.replace("_", " ").title(),
            "weight":         bp.get("weight", 0.5),
            "tags":           bp.get("tags", []),
            "encounter_verb": bp.get("encounter_verb", ""),
            "use_line":       bp.get("use_line", ""),
            "description":    bp.get("description", ""),
            "category":       bp.get("category", "misc"),
            "role":           parts[0].role if parts else "",
            "ability":        bp.get("use_line", ""),
        }

        root.setPythonTag("pickupable", True)
        root.setPythonTag("obj", obj)
        self._compound_nodes.append({
            "key": compound_key, "root": root, "obj": obj, "pos": pos,
        })
        self._spawned.append({"node": root, "key": compound_key, "obj": obj})
        self.ie.register(root, "pickup", obj=obj)

    def _rebuild_compounds(self):
        """
        Rebuild all compound objects in the current register.
        Removes old geometry, spawns new with current palette.
        Preserves positions and interaction state.
        """
        # Save positions and unregister
        saved = []
        for cn in self._compound_nodes:
            saved.append({"key": cn["key"], "pos": cn["pos"]})
            self.ie.unregister(cn["root"])
            # Remove from _spawned
            self._spawned = [
                s for s in self._spawned if s["node"] is not cn["root"]
            ]
            cn["root"].removeNode()
        self._compound_nodes.clear()

        # Respawn in current register
        for s in saved:
            self._spawn_compound(s["key"], s["pos"])

        console.log(
            f"[bold cyan]REGISTER[/bold cyan]  {self._register}  "
            f"[dim]{len(saved)} compound(s) rebuilt[/dim]"
        )

    def _cycle_register(self):
        """[R] -- cycle visual register: survival → tron → tolkien → sanrio."""
        idx = self._registers.index(self._register)
        self._register = self._registers[(idx + 1) % len(self._registers)]
        if self._biome == "LAB":
            self._apply_environment_register()
        else:
            # Rebuild biome scene in new register
            self._biome_builder.clear()
            self._biome_builder.build(self._biome, register=self._register)
        self._rebuild_compounds()
        self._update_hud()

    def _cycle_biome(self):
        """[B] -- cycle biome scene: LAB → VERDANT → CHROME → NEON → IRON → FROZEN."""
        idx = self._biomes.index(self._biome)
        self._biome = self._biomes[(idx + 1) % len(self._biomes)]

        # Clear biome scene
        self._biome_builder.clear()

        if self._biome == "LAB":
            # Restore lab: show interactables, rebuild environment
            self.layer_interactable.show()
            self._apply_environment_register()
        else:
            # Hide lab interactables (workbench, shelf objects)
            self.layer_interactable.hide()
            # Remove lab environment geometry
            for np in self._env_nodes:
                try:
                    np.removeNode()
                except Exception:
                    pass
            self._env_nodes = []
            # Build biome scene with current register
            self._biome_builder.build(self._biome, register=self._register)
            # Background from biome palette
            from core.systems.biome_renderer import BIOME_PALETTE
            pal = BIOME_PALETTE.get(self._biome, BIOME_PALETTE["VOID"])
            fc = pal["floor"]
            self.setBackgroundColor(fc[0] * 0.3, fc[1] * 0.3, fc[2] * 0.3, 1)

        console.log(
            f"[bold magenta]BIOME[/bold magenta]  {self._biome}  "
        )
        self._update_hud()

    # -- Pickup callbacks ------------------------------------------------------

    def _on_held(self, obj):
        console.log(
            f"[cyan]holding[/cyan]  {obj['id']}  "
            f"[dim]{obj.get('description', '')}[/dim]"
        )
        # Begin encounter -- ghost profile drives resonance
        tags   = obj.get("tags", [])
        entity = {"id": obj["id"], "tags": tags, "type": "object"}
        worth  = self.pipeline.encounter.begin(entity)
        if worth:
            verb = self.pipeline.encounter.dominant_verb()
            self.pipeline.encounter.choose(verb)
            console.log(
                f"[bold magenta]ENCOUNTER[/bold magenta]  resonant  "
                f"verb={verb}  [dim]{obj['id']}[/dim]"
            )
        self._update_hud()

    def _on_stowed(self, obj):
        console.log(
            f"[green]stowed[/green]   {obj['id']}  "
            f"[dim]{self.inventory.count()}/{self.inventory.max_slots} slots[/dim]"
        )
        # Resolve encounter on stow -- silence if not resonant
        result = self.pipeline.encounter.resolve()
        if result["worth_knowing"]:
            console.log(
                f"[bold green]RESOLVED[/bold green]  "
                f"xp={result['xp_staged']:.2f}  "
                f"verb={result['verb_used']}  "
                f"r={result['resonance']:.2f}"
            )
            self.pipeline.fingerprint.record("objects_inspected", 0.2)
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
        console.log(
            f"[bold green]CRAFTED:[/bold green] {result['name']}  "
            f"{result['provenance_hash']}"
        )
        console.log(f"  {result['description']}  ability: {result['ability']}")
        rn = _make_box_geom(0.6, 0.6, 0.6, (0.6, 0.8, 0.5))
        self.layer_interactable.attachNewNode(rn).setPos(0, 2, 1.5)
        self.slot_a = None
        self.slot_b = None
        self._update_hud(result)

    def _clear(self):
        self.slot_a = None
        self.slot_b = None
        self._update_hud()

    # -- HUD -------------------------------------------------------------------

    def _update_hud(self, result=None):
        for n in self._hud:
            try: n.destroy()
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
        ]

        # Active scenario
        if self._active_sid:
            state = self.se.get_state(self._active_sid)
            obj   = self.se.get_objective(self._active_sid)
            lines += [
                f"QUEST:  [{state.name}]",
                f"  {obj}",
                "",
            ]

        lines += [f"REGISTER: {self._register}  BIOME: {self._biome}"]
        lines += ["[E] lift/stow  [G] drop  [Q] fetch  [R] register  [B] biome  [C] craft"]

        if result:
            lines += ["", f">> {result['name']}", result["description"]]

        y = 0.92
        for line in lines:
            t = OnscreenText(
                text=line, pos=(-1.5, y), scale=0.044,
                fg=(0.85, 0.80, 0.72, 1),
                align=TextNode.ALeft, mayChange=True
            )
            self._hud.append(t)
            y -= 0.065

    # -- Lighting --------------------------------------------------------------

    def setup_lighting(self):
        ls  = _CFG["light_sun"]
        lf  = _CFG["light_fill"]
        la  = _CFG["light_amb"]
        hpr = _CFG["sun_hpr"]

        self._sun_light = DirectionalLight("sun")
        self._sun_light.setColor(Vec4(ls[0], ls[1], ls[2], 1))
        self._sun_light.setShadowCaster(True, 1024, 1024)
        sn = self.render.attachNewNode(self._sun_light)
        sn.setHpr(*hpr)
        self.render.setLight(sn)

        self._fill_light = DirectionalLight("fill")
        self._fill_light.setColor(Vec4(lf[0], lf[1], lf[2], 1))
        fn = self.render.attachNewNode(self._fill_light)
        fn.setHpr(hpr[0] + 180, -20, 0)
        self.render.setLight(fn)

        self._amb_light = AmbientLight("amb")
        self._amb_light.setColor(Vec4(la[0], la[1], la[2], 1))
        self.render.setLight(self.render.attachNewNode(self._amb_light))

        lamp = PointLight("lamp")
        lamp.setColor(Vec4(1.0, 0.75, 0.4, 1))
        lamp.setShadowCaster(True, 512, 512)
        lamp.setAttenuation((0.5, 0.0, 0.02))
        ln = self.render.attachNewNode(lamp)
        ln.setPos(-6, LAB_Y_N - 4, 4.0)
        self.render.setLight(ln)

        post = _make_box_geom(0.12, 0.12, 4.0, (0.10, 0.08, 0.07))
        self.render.attachNewNode(post).setPos(-6, LAB_Y_N - 4, 2.0)

        # Fog -- initial setup from current register
        self._fog = None
        reg = ENVIRONMENT_REGISTERS.get(self._register, ENVIRONMENT_REGISTERS["survival"])
        self._fog = update_fog(self._fog, self.render, reg)

    def _update_lighting(self, reg):
        """Delegate to lab_environment."""
        update_lighting(self._sun_light, self._fill_light, self._amb_light, reg)
        self._fog = update_fog(self._fog, self.render, reg)

    # -- Controls --------------------------------------------------------------

    def setup_controls(self):
        for key in self.key_map:
            self.accept(key,         self.update_key_map, [key, True])
            self.accept(f"{key}-up", self.update_key_map, [key, False])
        self.accept("e", self.pickup.on_e_pressed)
        self.accept("g", self.pickup.on_drop_pressed)
        self.accept("q", self._create_fetch_scenario)
        self.accept("r", self._cycle_register)
        self.accept("b", self._cycle_biome)
        self.accept("c", self._craft)
        self.accept("x", self._clear)
        for i in range(9):
            self.accept(str(i + 1), self._spawn_by_number, [i])

    def _spawn_by_number(self, index):
        if index < len(self._obj_keys):
            self._spawn_object(self._obj_keys[index])

    def update_key_map(self, key, val):
        self.key_map[key] = val

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

    # -- Activity inference ----------------------------------------------------

    def _infer_activity(self) -> str:
        """
        Derive current player activity from world state.
        Priority: combat > exploring > crafting > observing > idle.
        Feeds fingerprint.tick() every frame.
        """
        # Active encounter = combat (highest priority)
        if self.pipeline.encounter.active_encounter is not None:
            return "combat"

        # Movement keys held = exploring
        if any(self.key_map.values()):
            return "exploring"

        # Crafting slots filled = crafting
        if self.slot_a is not None and self.slot_b is not None:
            return "crafting"

        # Near reachable objects and still = observing
        if self.ie.all_reachable():
            return "observing"

        return "idle"

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
        self.ie.tick()
        self.se.tick()

        # Fingerprint tick -- accumulate behavioral time
        activity = self._infer_activity()
        self.pipeline.fingerprint.tick(dt, activity)

        # Encounter cooldown -- world digests before speaking again
        self.pipeline.encounter.tick_cooldown(dt)

        # Blend refresh -- merge interview + fingerprint periodically
        self._blend_refresh_elapsed += dt
        if self._blend_refresh_elapsed >= self._blend_refresh_interval:
            self._blend_refresh_elapsed = 0.0
            self.pipeline.refresh_blend()

        return task.cont

    def exit_app(self):
        sys.exit(0)


if __name__ == "__main__":
    CreationLab().run()
