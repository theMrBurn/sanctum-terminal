import numpy as np


class Avatar:
    def __init__(self, start_pos=[0.0, 0.0, 0.0]):
        self.pos = np.array(start_pos, dtype="f4")
        self.vel = np.array([0.0, 0.0, 0.0], dtype="f4")
        self.eye_height = 1.6
        self.gravity = -24.0
        self.jump_force = 8.5
        self.on_ground = False
        self.step_cycle = 0.0

    def jump(self):
        if self.on_ground:
            self.vel[1] = self.jump_force
            self.on_ground = False

    def get_eye_pos(self):
        return self.pos + np.array([0, self.eye_height, 0], dtype="f4")

    def update(self, dt, move_input, vault, world_offset):
        self.vel[1] += self.gravity * dt
        delta_pos = (
            np.array([move_input[0], self.vel[1], move_input[1]], dtype="f4") * dt
        )
        check_pos = (world_offset + self.pos) + delta_pos

        if vault.check_collision(check_pos) or check_pos[1] <= 0:
            if self.vel[1] <= 0:
                self.pos[1] = 0.0
                self.on_ground = True
                self.vel[1] = 0
        else:
            self.pos[1] += delta_pos[1]
            self.on_ground = False

        speed = np.linalg.norm(move_input)
        if self.on_ground and speed > 0.1:
            self.step_cycle += dt * 12.0
