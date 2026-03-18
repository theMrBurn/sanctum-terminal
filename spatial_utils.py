import numpy as np
from pyrr import Matrix44, Vector3, matrix44


class RelativityCamera:
    def __init__(self, position=[0, 2, 20]):
        self.pos = Vector3(position)
        self.yaw = -90.0
        self.pitch = -10.0
        self.front = Vector3([0.0, 0.0, -1.0])
        self.up = Vector3([0.0, 1.0, 0.0])

    def update_orientation(self, dx, dy):
        self.yaw += dx
        self.pitch = np.clip(self.pitch + dy, -89, 89)

        # Unified direction vector calculation
        rad_y, rad_p = np.radians(self.yaw), np.radians(self.pitch)
        self.front = Vector3(
            [
                np.cos(rad_y) * np.cos(rad_p),
                np.sin(rad_p),
                np.sin(rad_y) * np.cos(rad_p),
            ]
        ).normalized

    def get_view_matrix(self, roll=0.0):
        view = matrix44.create_look_at(self.pos, self.pos + self.front, self.up)
        if abs(roll) > 0.01:
            view = Matrix44.from_z_rotation(np.radians(roll)) * view
        return view

    def get_projection(self, fov=70.0, aspect=1.777):
        return Matrix44.perspective_projection(fov, aspect, 0.1, 1000.0)
