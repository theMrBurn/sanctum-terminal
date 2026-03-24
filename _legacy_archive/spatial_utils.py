import numpy as np
from pyrr import Matrix44, Vector3, matrix44


class RelativityCamera:
    def __init__(self, position=[0, 0, 0]):
        self.pos = Vector3(position, dtype="f4")
        self.yaw = -90.0
        self.pitch = 0.0
        self.front = Vector3([0.0, 0.0, -1.0], dtype="f4")
        self.up = Vector3([0.0, 1.0, 0.0], dtype="f4")

    def update_orientation(self, dx, dy):
        self.yaw += dx
        self.pitch = np.clip(self.pitch - dy, -88, 88)

        rad_y, rad_p = np.radians(self.yaw), np.radians(self.pitch)
        self.front = Vector3(
            [
                np.cos(rad_y) * np.cos(rad_p),
                np.sin(rad_p),
                np.sin(rad_y) * np.cos(rad_p),
            ],
            dtype="f4",
        ).normalized

    def get_view_matrix(self):
        # In Relative Mode, we are always at [0,0,0], looking at [front]
        return matrix44.create_look_at(self.pos, self.pos + self.front, self.up).astype(
            "f4"
        )

    def get_projection(self, fov=70.0, aspect=1.777):
        return Matrix44.perspective_projection(fov, aspect, 0.1, 1000.0).astype("f4")
