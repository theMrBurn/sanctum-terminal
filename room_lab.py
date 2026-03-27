import sys
from direct.showbase.ShowBase import ShowBase
from panda3d.core import AmbientLight, AntialiasAttrib, DirectionalLight, Vec4, WindowProperties
from rich.console import Console
from core.systems.biome_renderer import BiomeRenderer, _make_box_geom, _make_plane_geom

console = Console()
MOUSE_SENSITIVITY = 0.15
PITCH_CLAMP = 80.0
SNAP_THRESHOLD = 200

class RoomLab(ShowBase):
    ROOM_W = 880    
    ROOM_D = 1500
    CEILING_Z = 99
    EYE_Z = 6.0
    MOVE_SPEED = 30.0
    BIOME = 'ICY'
    SEED = 89
    DENSITY = 0.6

    def __init__(self):
        super().__init__()
        props = WindowProperties()
        props.setTitle('Room Lab')
        props.setSize(1280, 720)
        self.win.requestProperties(props)
        self.setBackgroundColor(0.02, 0.02, 0.04, 1)
        self.cam_yaw = 0.0
        self.cam_pitch = 0.0
        self.mouse_look_active = False
        self._last_mx = None
        self._last_my = None
        self.key_map = {'w':False,'s':False,'a':False,'d':False,'q':False,'e':False}
        self.disableMouse()
        self.camLens.setFov(80)
        self.cam.setPos(0, 0, self.EYE_Z)
        self.cam.setHpr(0, 0, 0)
        self.setup_lighting()
        self.render.setShaderAuto()
        self.render.setAntialias(AntialiasAttrib.MMultisample)
        self.setup_controls()
        self._build_room()
        self.taskMgr.add(self.fly_cam_task, 'FlyCAM')
        console.log('[bold cyan]ROOM LAB[/bold cyan]')
        console.log('WSAD | Click mouse look | ESC release | Shift+ESC quit')
        self.accept('escape', self.disable_mouse_look)
        self.accept('shift-escape', self.exit_app)
        self.accept('mouse1', self.enable_mouse_look)

    def _build_room(self):
        from core.systems.biome_renderer import BIOME_PALETTE
        palette = BIOME_PALETTE.get(self.BIOME, BIOME_PALETTE['VOID'])
        floor_c = palette['floor']
        hw = self.ROOM_W / 2
        hd = self.ROOM_D / 2
        fn = _make_plane_geom(self.ROOM_W, self.ROOM_D, floor_c)
        self.render.attachNewNode(fn).setPos(0, 0, 0)
        cn = _make_plane_geom(self.ROOM_W, self.ROOM_D, tuple(c*0.4 for c in floor_c))
        cp = self.render.attachNewNode(cn)
        cp.setPos(0, 0, self.CEILING_Z)
        cp.setHpr(0, 180, 0)
        wall_c = tuple(c*0.6 for c in floor_c)
        walls = [
            (self.ROOM_W,1.0,self.CEILING_Z,0,hd,self.CEILING_Z/2),
            (self.ROOM_W,1.0,self.CEILING_Z,0,-hd,self.CEILING_Z/2),
            (1.0,self.ROOM_D,self.CEILING_Z,hw,0,self.CEILING_Z/2),
            (1.0,self.ROOM_D,self.CEILING_Z,-hw,0,self.CEILING_Z/2),
        ]
        for w,d,h,x,y,z in walls:
            wn = _make_box_geom(w,h,d,wall_c)
            self.render.attachNewNode(wn).setPos(x,y,z)
        renderer = BiomeRenderer(render_root=self.render,biome_key=self.BIOME,seed=self.SEED)
        count = int(8 + self.DENSITY * 30)
        renderer.render_scatter(count=count, radius=hw*0.8)
        console.log(f'[dim]{count} objects[/dim]')

    def setup_lighting(self):
        d = DirectionalLight('d')
        d.setColor(Vec4(1,0.95,0.85,1))
        dn = self.render.attachNewNode(d)
        dn.setHpr(150,-45,0)
        self.render.setLight(dn)
        from core.systems.biome_renderer import BIOME_PALETTE
        p = BIOME_PALETTE.get(self.BIOME, BIOME_PALETTE['VOID'])
        br = max(0.3, p['scale'] * 0.6)
        a = AmbientLight('a')
        a.setColor(Vec4(br, br*0.95, br*1.05, 1))
        self.render.setLight(self.render.attachNewNode(a))

    def setup_controls(self):
        for key in self.key_map:
            self.accept(key, self.update_key_map, [key, True])
            self.accept(f'{key}-up', self.update_key_map, [key, False])

    def update_key_map(self,key,val): self.key_map[key]=val

    def enable_mouse_look(self):
        self.mouse_look_active=True
        self._last_mx=None
        self._last_my=None
        props=WindowProperties()
        props.setCursorHidden(True)
        props.setMouseMode(WindowProperties.M_relative)
        self.win.requestProperties(props)

    def disable_mouse_look(self):
        self.mouse_look_active=False
        props=WindowProperties()
        props.setCursorHidden(False)
        props.setMouseMode(WindowProperties.M_absolute)
        self.win.requestProperties(props)

    def fly_cam_task(self,task):
        dt=globalClock.getDt()
        speed=self.MOVE_SPEED*dt
        if self.mouse_look_active and self.mouseWatcherNode.hasMouse():
            md=self.win.getPointer(0)
            mx,my=md.getX(),md.getY()
            if self._last_mx is not None:
                dx=mx-self._last_mx
                dy=my-self._last_my
                if abs(dx)<SNAP_THRESHOLD and abs(dy)<SNAP_THRESHOLD:
                    self.cam_yaw-=dx*MOUSE_SENSITIVITY
                    self.cam_pitch-=dy*MOUSE_SENSITIVITY
                    self.cam_pitch=max(-PITCH_CLAMP,min(PITCH_CLAMP,self.cam_pitch))
                    self.cam.setHpr(self.cam_yaw,self.cam_pitch,0)
            self._last_mx,self._last_my=mx,my
        if self.key_map['w']: self.cam.setPos(self.cam,0,speed,0)
        if self.key_map['s']: self.cam.setPos(self.cam,0,-speed,0)
        if self.key_map['a']: self.cam.setPos(self.cam,-speed,0,0)
        if self.key_map['d']: self.cam.setPos(self.cam,speed,0,0)
        if self.key_map['e']: self.cam.setPos(self.cam,0,0,speed)
        if self.key_map['q']: self.cam.setPos(self.cam,0,0,-speed)
        x,y,z=self.cam.getPos()
        hw=self.ROOM_W/2-2
        hd=self.ROOM_D/2-2
        self.cam.setPos(max(-hw,min(hw,x)),max(-hd,min(hd,y)),self.EYE_Z)
        return task.cont

    def exit_app(self): sys.exit(0)

if __name__ == '__main__':
    RoomLab().run()