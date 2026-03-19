import pygame
import numpy as np


class InputHandler:
    def __init__(self):
        self.velocity = np.array([0.0, 0.0, 0.0], dtype="f4")
        self.friction = 0.15
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
        move_speed = 10.0  # Bumping up from 8.0 for better feel
        is_sprinting = keys[pygame.K_LSHIFT]

        speed_mod = 2.0 if is_sprinting else 1.0
        target_speed = move_speed * speed_mod

        dir_vec = np.array([0.0, 0.0, 0.0], dtype="f4")

        if keys[pygame.K_w]:
            dir_vec[0] += 1.0
        if keys[pygame.K_s]:
            dir_vec[0] -= 1.0
        if keys[pygame.K_d]:
            dir_vec[1] += 1.0
        if keys[pygame.K_a]:
            dir_vec[1] -= 1.0

        mag = np.linalg.norm(dir_vec[:2])
        if mag > 0:
            dir_vec[:2] /= mag

        # SNAPPY LERP: Increased to 8.0 so you move the moment you press W
        lerp_factor = 8.0 * dt
        self.velocity = (
            self.velocity + (dir_vec * target_speed - self.velocity) * lerp_factor
        )

        return self.velocity

    def get_look(self, dt):
        mdx, mdy = pygame.mouse.get_rel()
        return [float(mdx) * 0.4, float(mdy) * 0.4]

    def get_actions(self):
        keys = pygame.key.get_pressed()
        return {"primary": pygame.mouse.get_pressed()[0], "jump": keys[pygame.K_SPACE]}
