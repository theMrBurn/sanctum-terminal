import pygame
import moderngl
import numpy as np
from vault_engine import DataNode
from relativity_engine import RelativityEngine
from sensors import EnvironmentalSensor
from input_handler import InputHandler
from renderer_handler import RenderHandler
from perception import PerceptionController
from pyrr import Matrix44, Vector3, matrix44


class SanctumViewport:
    def __init__(self):
        pygame.display.init()
        pygame.font.init()
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
        pygame.display.gl_set_attribute(
            pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE
        )
        self.win_size = (1280, 720)
        self.screen = pygame.display.set_mode(
            self.win_size, pygame.OPENGL | pygame.DOUBLEBUF
        )
        self.ctx = moderngl.create_context()
        self.brain = DataNode()
        self.sensors = EnvironmentalSensor()
        self.inputs = InputHandler()
        self.render = RenderHandler(self.ctx)
        self.perception = PerceptionController(self.sensors)
        self.font = pygame.font.SysFont("Monaco", 24)
        self.hud_vao = self.render.build_hud_vao()
        self.sensory_radius, self.stream_threshold = 80.0, 1.2
        self.cam_pos = Vector3([0.0, 2.0, 20.0])
        self.yaw, self.pitch, self.roll, self.step_cycle = -90.0, -10.0, 0.0, 0.0
        self.cam_front = Vector3([0.0, 0.0, -1.0])
        self.cam_up = Vector3([0.0, 1.0, 0.0])
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        self.vao, self.current_stream_raw = None, None
        self._refresh_stream()

    def _refresh_stream(self):
        raw_world = self.brain.fetch_sector(self.cam_pos, self.sensory_radius)
        local_frame = RelativityEngine.get_local_frame(
            raw_world, self.cam_pos, self.cam_front, self.sensory_radius
        )
        self.vao = self.render.build_vao(local_frame)
        self.last_stream_pos = Vector3(self.cam_pos)
        self.current_stream_raw = local_frame

    def create_hud_texture(self, p_state, stream_data):
        hud_surf = pygame.Surface(self.win_size, pygame.SRCALPHA)
        min_dist = 99.0
        if stream_data is not None and len(stream_data) > 0:
            obstacles = [
                np.linalg.norm(v["p"])
                for v in stream_data
                if v["c"][0] > 0.2 or v["p"][1] > -1.0
            ]
            if obstacles:
                min_dist = min(obstacles)
        color = (255, 255, 0) if pygame.time.get_ticks() % 500 < 100 else (0, 100, 80)
        hud_surf.blit(
            self.font.render(
                f"OBSERVER_LOC: [{self.cam_pos.x:0.1f}, {self.cam_pos.z:0.1f}]",
                True,
                (0, 255, 200),
            ),
            (20, 20),
        )
        hud_surf.blit(
            self.font.render(f"PROXIMITY_PING: {min_dist:0.1f}m", True, color), (20, 50)
        )
        texture_data = pygame.image.tobytes(hud_surf, "RGBA", False)
        return self.ctx.texture(self.win_size, 4, texture_data)

    def update_camera(self, velocity, look, dt):
        self.yaw += look[0]
        self.pitch = np.clip(self.pitch + look[1], -89, 89)
        f = [
            np.cos(np.radians(self.yaw)) * np.cos(np.radians(self.pitch)),
            np.sin(np.radians(self.pitch)),
            np.sin(np.radians(self.yaw)) * np.cos(np.radians(self.pitch)),
        ]
        self.cam_front = Vector3(f).normalized
        right = self.cam_front.cross(self.cam_up).normalized
        move_vec = (self.cam_front * velocity[0]) + (right * velocity[1])
        if np.linalg.norm(velocity[:2]) > 0.01:
            self.step_cycle += dt * 10.0
            self.roll = np.sin(self.step_cycle * 0.5) * 1.5
        else:
            self.roll *= 0.9
        next_pos = self.cam_pos + move_vec
        if not self.brain.check_collision(next_pos, radius=1.0):
            self.cam_pos = next_pos
        if (self.cam_pos - self.last_stream_pos).length > self.stream_threshold:
            self._refresh_stream()

    def run(self):
        clock = pygame.time.Clock()
        while True:
            dt = clock.tick(120) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    return
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.perception.trigger_pulse(self.cam_pos)
            v, l = self.inputs.get_movement(dt), self.inputs.get_look(dt)
            self.update_camera(v, l, dt)
            proj = Matrix44.perspective_projection(70.0, 1.777, 0.01, 1000.0)
            view = matrix44.create_look_at(
                np.array([0, 0, 0], "f4"),
                np.array(self.cam_front, "f4"),
                np.array(self.cam_up, "f4"),
            )
            mvp = proj * Matrix44.from_z_rotation(np.radians(self.roll)) * view
            hud_tex = self.create_hud_texture(
                self.perception.get_shader_state(), self.current_stream_raw
            )
            self.render.render_frame(
                self.vao,
                mvp,
                [0, 0, 0],
                self.perception.get_shader_state(),
                hud_tex,
                self.hud_vao,
            )
            pygame.display.flip()
            hud_tex.release()
