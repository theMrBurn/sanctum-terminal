import pygame
import numpy as np


class InputHandler:
    def __init__(self):
        self.velocity = np.array([0.0, 0.0, 0.0], dtype="f4")
        self.friction = 0.85
        self.deadzone = 0.15  # Ignore analog input below 15% to prevent drift

        # Initialize Joystick for Xbox Controller
        pygame.joystick.init()
        self.joystick = None
        if pygame.joystick.get_count() > 0:
            self.joystick = pygame.joystick.Joystick(0)
            self.joystick.init()
            print(f">>> [INPUT] Controller Detected: {self.joystick.get_name()}")
        else:
            print(">>> [INPUT] No Controller Found - WASD Mode Active")

        # Mouse / Trackpad setup
        try:
            pygame.mouse.set_visible(False)
            pygame.event.set_grab(True)
        except:
            pass

    def _apply_deadzone(self, value):
        """Internal helper to filter noisy analog stick data."""
        return value if abs(value) > self.deadzone else 0.0

    def get_movement(self, dt):
        keys = pygame.key.get_pressed()
        move_speed = 35.0 * dt

        # 1. Sprint Logic (Shift or Left Stick Click)
        is_sprinting = keys[pygame.K_LSHIFT]
        if self.joystick and self.joystick.get_button(8):  # LS Click
            is_sprinting = True

        speed_mod = 1.8 if is_sprinting else 1.0
        accel = move_speed * speed_mod

        input_vec = np.array([0.0, 0.0, 0.0], dtype="f4")

        # 2. Keyboard Input (WASD)
        if keys[pygame.K_w]:
            input_vec[0] += accel
        if keys[pygame.K_s]:
            input_vec[0] -= accel
        if keys[pygame.K_d]:
            input_vec[1] += accel
        if keys[pygame.K_a]:
            input_vec[1] -= accel

        # 3. Controller Input (Left Stick)
        if self.joystick:
            # Axis 1 is Vertical (Inverted by default in SDL), Axis 0 is Horizontal
            joy_y = -self._apply_deadzone(self.joystick.get_axis(1))
            joy_x = self._apply_deadzone(self.joystick.get_axis(0))

            input_vec[0] += joy_y * accel
            input_vec[1] += joy_x * accel

        # 4. Vertical / Jump (Space or 'A' Button)
        jump_trigger = keys[pygame.K_SPACE]
        if self.joystick and self.joystick.get_button(0):  # 'A' Button
            jump_trigger = True

        if jump_trigger:
            input_vec[2] += accel * 2.0

        # 5. KINETIC PHYSICS
        # Apply pseudo-gravity to keep the observer grounded
        self.velocity[2] -= 20.0 * dt

        # Integrate Input
        self.velocity += input_vec

        # Apply Friction (Damping)
        self.velocity *= self.friction

        # Hard Floor Clamp
        if self.velocity[2] < -10.0:
            self.velocity[2] = -10.0

        return self.velocity

    def get_look(self, dt):
        # 1. Mouse Look
        mdx, mdy = pygame.mouse.get_rel()
        look_vec = [mdx * 0.15, mdy * 0.15]

        # 2. Controller Look (Right Stick)
        if self.joystick:
            # Axis 3: RS Horizontal, Axis 4: RS Vertical
            rdx = self._apply_deadzone(self.joystick.get_axis(3))
            rdy = self._apply_deadzone(self.joystick.get_axis(4))

            # Sensitivity boost for analog sticks (adjustable)
            look_vec[0] += rdx * 5.0
            look_vec[1] += rdy * 5.0

        return look_vec

    def get_actions(self):
        keys = pygame.key.get_pressed()

        # Check Xbox 'X' (Button 2) or 'B' (Button 1) for UI toggles
        joy_primary = False
        joy_menu = False
        if self.joystick:
            joy_primary = self.joystick.get_button(2)  # 'X'
            joy_menu = self.joystick.get_button(7)  # 'Start/Menu'

        return {
            "primary": pygame.mouse.get_pressed()[0] or joy_primary,
            "toggle_view": keys[pygame.K_v],
            "menu": keys[pygame.K_ESCAPE] or joy_menu,
        }
