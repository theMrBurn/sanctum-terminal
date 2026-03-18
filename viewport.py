import pygame
import moderngl
import numpy as np
from vault_engine import DataNode
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
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_FORWARD_COMPATIBLE_FLAG, True)

        self.win_size = (1280, 720)
        self.screen = pygame.display.set_mode(
            self.win_size, pygame.OPENGL | pygame.DOUBLEBUF
        )

        try:
            self.ctx = moderngl.create_context()
        except Exception:
            self.ctx = moderngl.create_context(require=330)

        self.brain = DataNode()
        self.sensors = EnvironmentalSensor()
        self.inputs = InputHandler()
        self.render = RenderHandler(self.ctx)

        # Perception Pillar initialization
        self.perception = PerceptionController(self.sensors)

        # HUD Resources
        self.font = pygame.font.SysFont("Monaco", 24)
        self.hud_vao = self.render.build_hud_vao()
        self.sensory_radius = 72.0

        # Simulation State
        self.stream_threshold = 5.0
        self.last_stream_pos = Vector3([0.0, 0.0, 0.0])
        self.step_cycle = 0.0
        self.base_cam_height = 2.0
        self.roll = 0.0

        # Observer Coordinates
        self.cam_pos = Vector3([0.0, self.base_cam_height, 20.0])
        self.yaw, self.pitch = -90.0, -10.0
        self.cam_front = Vector3([0.0, 0.0, 1.0])
        self.cam_up = Vector3([0.0, 1.0, 0.0])

        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        self._refresh_stream()

    def _refresh_stream(self):
        stream_data = self.brain.get_stream(lat=self.cam_pos, radius=self.sensory_radius)
        self.vao = self.render.build_vao(stream_data)
        self.last_stream_pos = Vector3(self.cam_pos)

    def create_hud_texture(self, p_state):
        """Renders raw telemetry surface with Active Pulse feedback."""
        hud_surf = pygame.Surface(self.win_size, pygame.SRCALPHA)
        intensity = p_state["u_intensity"]
        pulse_time = p_state["u_pulse_time"]

        # 1. BASE TELEMETRY
        pos_text = f"OBSERVER_LOC: [{self.cam_pos.x:0.2f}, {self.cam_pos.y:0.2f}, {self.cam_pos.z:0.2f}]"
        stress_text = f"ATMOS_STRESS: {intensity * 100:0.1f}%"

        hud_surf.blit(self.font.render(pos_text, True, (0, 255, 200)), (20, 20))
        hud_surf.blit(self.font.render(stress_text, True, (0, 255, 200)), (20, 50))

        # 2. ACTIVE SONAR READOUT
        if pulse_time > 0:
            # Calculate remaining life of the wave
            remaining = max(0, (2.5 - pulse_time) / 2.5)
            ping_color = (
                (0, 255, 255) if pygame.time.get_ticks() % 200 > 100 else (0, 150, 150)
            )

            # Status Text
            hud_surf.blit(
                self.font.render(">> SCANNING_ENVIRONMENT...", True, ping_color),
                (20, 110),
            )

            # Progress Bar (Depleting as wave expands)
            pygame.draw.rect(hud_surf, (0, 50, 50), (20, 140, 200, 10))
            pygame.draw.rect(hud_surf, ping_color, (20, 140, int(200 * remaining), 10))
        else:
            hud_surf.blit(
                self.font.render(">> SONAR_READY", True, (0, 100, 80)), (20, 110)
            )

        texture_data = pygame.image.tostring(hud_surf, "RGBA", False)
        return self.ctx.texture(self.win_size, 4, texture_data)

    def update_camera(self, velocity, look, dt):
        self.yaw += look[0]
        self.pitch = np.clip(self.pitch + look[1], -89, 89)

        front = Vector3([0.0, 0.0, 0.0])
        front.x = np.cos(np.radians(self.yaw)) * np.cos(np.radians(self.pitch))
        front.y = np.sin(np.radians(self.pitch))
        front.z = np.sin(np.radians(self.yaw)) * np.cos(np.radians(self.pitch))
        self.cam_front = front.normalized

        self.cam_pos += self.cam_front * velocity[0]
        self.cam_pos += self.cam_front.cross(self.cam_up).normalized * velocity[1]

        # Physics Sway
        horizontal_speed = np.linalg.norm(velocity[:2])
        if horizontal_speed > 0.001:
            self.step_cycle += dt * horizontal_speed * 12.0
            self.cam_pos[1] = self.base_cam_height + np.sin(self.step_cycle) * 0.05
            self.roll = np.cos(self.step_cycle * 0.5) * 1.2
        else:
            self.roll *= 1.0 - dt * 5.0

        if (self.cam_pos - self.last_stream_pos).length > self.stream_threshold:
            self._refresh_stream()

    def run(self):
        clock = pygame.time.Clock()
        while True:
            dt = clock.tick(120) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                ):
                    return
                # SONAR PING TRIGGER
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self.perception.trigger_pulse(self.cam_pos)

            velocity = self.inputs.get_movement(dt)
            look = self.inputs.get_look(dt)
            self.update_camera(velocity, look, dt)

            # Perception Sync
            p_state = self.perception.get_shader_state()

            # MVP Construction
            proj = Matrix44.perspective_projection(
                45.0, self.win_size[0] / self.win_size[1], 0.1, 1000.0
            )
            view = matrix44.create_look_at(
                self.cam_pos, self.cam_pos + self.cam_front, self.cam_up
            )
            rotation = Matrix44.from_z_rotation(np.radians(self.roll))
            mvp = proj * rotation * view

            # GPU Frame
            hud_tex = self.create_hud_texture(p_state)
            self.render.render_frame(
                self.vao, mvp, self.cam_pos, p_state, hud_tex, self.hud_vao
            )

            pygame.display.flip()
            hud_tex.release()