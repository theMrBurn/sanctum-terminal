import pygame
import moderngl
import numpy as np
from engine import DataNode
from sensors import EnvironmentalSensor
from input_handler import InputHandler
from renderer_handler import RenderHandler
from pyrr import Matrix44, Vector3, matrix44


class SanctumViewport:
    def __init__(self):
        # Hardware Setup for macOS Core Profile (M2 Pro)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MAJOR_VERSION, 3)
        pygame.display.gl_set_attribute(pygame.GL_CONTEXT_MINOR_VERSION, 3)
        pygame.display.gl_set_attribute(
            pygame.GL_CONTEXT_PROFILE_MASK, pygame.GL_CONTEXT_PROFILE_CORE
        )

        self.win_size = (1280, 720)
        self.screen = pygame.display.set_mode(
            self.win_size, pygame.OPENGL | pygame.DOUBLEBUF
        )

        self.brain = DataNode()
        self.sensors = EnvironmentalSensor()
        self.inputs = InputHandler()
        self.render = RenderHandler(moderngl.create_context())

        # Sensory Radius Scaled to M2 Pro Cores
        cores = self.brain.specs.get("cores", 8)
        self.sensory_radius = float(cores * 4)

        # Weather Sync
        weather = self.sensors.fetch_passive_data("portland")
        self.color_mod = (
            np.array([0.7, 0.9, 1.3], dtype="f4")
            if weather["temp"] < 25
            else np.array([1.3, 0.9, 0.7], dtype="f4")
        )

        # Camera State
        self.cam_pos = Vector3([0.0, 5.0, -35.0])
        self.yaw, self.pitch = -90.0, 0.0
        self.cam_front = Vector3([0.0, 0.0, 1.0])
        self.cam_up = Vector3([0.0, 1.0, 0.0])

        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)

        # Initial Stream Load
        self.vao = self.render.build_vao(
            self.brain.get_stream(lat=self.cam_pos, radius=self.sensory_radius)
        )

    def update_camera(self, velocity, look, dt):
        """Calculates WASD/Analog movement with Kinetic Momentum."""
        self.yaw += look[0]
        self.pitch = np.clip(self.pitch + look[1], -89, 89)

        front = Vector3([0.0, 0.0, 0.0])
        front.x = np.cos(np.radians(self.yaw)) * np.cos(np.radians(self.pitch))
        front.y = np.sin(np.radians(self.pitch))
        front.z = np.sin(np.radians(self.yaw)) * np.cos(np.radians(self.pitch))
        self.cam_front = front.normalized

        self.cam_pos += self.cam_front * velocity[0]
        self.cam_pos += self.cam_front.cross(self.cam_up).normalized * velocity[1]

    def run(self):
        clock = pygame.time.Clock()
        print(f"--- [SANCTUM ACTIVE | RADIUS: {self.sensory_radius}] ---")

        while True:
            dt = clock.tick(120) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (
                    event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE
                ):
                    return
                if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    self.vao = self.render.build_vao(
                        self.brain.get_stream(
                            lat=self.cam_pos, radius=self.sensory_radius
                        )
                    )

            velocity = self.inputs.get_movement(dt)
            look = self.inputs.get_look(dt)

            # Logic Update
            self.update_camera(velocity, look, dt)
            self.render.transition_tick(self.brain.recovery_mode, dt)

            # Render Calculations
            proj = Matrix44.perspective_projection(
                45.0, self.win_size[0] / self.win_size[1], 0.1, 1000.0
            )
            view = matrix44.create_look_at(
                self.cam_pos, self.cam_pos + self.cam_front, self.cam_up
            )
            mvp = proj * view

            self.render.render_frame(self.vao, mvp, self.color_mod)
            pygame.display.flip()
