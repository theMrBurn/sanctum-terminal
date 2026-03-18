import pygame
import numpy as np


class InputHandler:
    def __init__(self):
        self.velocity = np.array([0.0, 0.0, 0.0], dtype="f4")
        self.friction = 0.15  # Reduced friction for "weightier" movement
        self.deadzone = 0.15

        pygame.joystick.init()
        self.joystick = None
        if pygame.joystick.get_count() > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            print(f">>> [INPUT] Controller Detected: {self.joystick.get_name()}")
        else:
            print(">>> [INPUT] No Controller Found - WASD Mode Active")

    def _apply_deadzone(self, value):
        return value if abs(value) > self.deadzone else 0.0

    def get_movement(self, dt):
        keys = pygame.key.get_pressed()

        # Base speed in units per second
        move_speed = 15.0

        is_sprinting = keys[pygame.K_LSHIFT]
        if self.joystick and self.joystick.get_button(8):
            is_sprinting = True

        speed_mod = 2.5 if is_sprinting else 1.0
        target_speed = move_speed * speed_mod

        # Directional Intent
        dir_vec = np.array([0.0, 0.0, 0.0], dtype="f4")

        if keys[pygame.K_w]:
            dir_vec[0] += 1.0
        if keys[pygame.K_s]:
            dir_vec[0] -= 1.0
        if keys[pygame.K_d]:
            dir_vec[1] += 1.0
        if keys[pygame.K_a]:
            dir_vec[1] -= 1.0

        if self.joystick:
            dir_vec[0] += -self._apply_deadzone(self.joystick.get_axis(1))
            dir_vec[1] += self._apply_deadzone(self.joystick.get_axis(0))

        # Normalize direction so diagonal isn't faster
        mag = np.linalg.norm(dir_vec[:2])
        if mag > 0:
            dir_vec[:2] /= mag

        # Vertical Movement
        if keys[pygame.K_SPACE] or (self.joystick and self.joystick.get_button(0)):
            dir_vec[2] += 1.0
        if keys[pygame.K_LCTRL]:  # Added Descend
            dir_vec[2] -= 1.0

        # LERP velocity toward target for smooth starts/stops
        # This prevents the "leaping" effect
        lerp_factor = 10.0 * dt
        self.velocity = (
            self.velocity + (dir_vec * target_speed - self.velocity) * lerp_factor
        )

        return self.velocity * dt

    def get_look(self, dt):
        mdx, mdy = pygame.mouse.get_rel()
        # Sensitivity scaled by dt for frame-rate independence
        look_vec = [mdx * 12.0 * dt, mdy * 12.0 * dt]

        if self.joystick:
            rdx = self._apply_deadzone(self.joystick.get_axis(3))
            rdy = self._apply_deadzone(self.joystick.get_axis(4))
            look_vec[0] += rdx * 150.0 * dt
            look_vec[1] += rdy * 150.0 * dt

        return look_vec

    def get_actions(self):
        keys = pygame.key.get_pressed()
        return {
            "primary": pygame.mouse.get_pressed()[0]
            or (self.joystick and self.joystick.get_button(2)),
            "toggle_view": keys[pygame.K_v],
            "menu": keys[pygame.K_ESCAPE]
            or (self.joystick and self.joystick.get_button(7)),
        }
