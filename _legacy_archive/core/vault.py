import numpy as np
from systems.volume import Volume


class VoxelRecord:
    """Structured data format for legacy test compatibility."""

    EXT_DTYPE = [("p", "f4", (3,)), ("c", "f4", (3,)), ("t", "f4")]


class Vault:
    def __init__(self, ctx=None, max_reserve=11_000_000):
        self.ctx = ctx
        self.max_reserve = max_reserve
        self.vao = None
        self.vbo = None
        self.current_voxel_count = 0

        # Cache for collision checks
        self._active_volumes = {}

        if self.ctx:
            self.vbo = self.ctx.buffer(reserve=max_reserve * 7 * 4)

    def update_vbo(self, payload, shader_prog):
        """Direct GPU injection for the Viewport."""
        if len(payload) == 0 or not self.ctx:
            return
        self.vbo.write(payload.tobytes())
        self.current_voxel_count = len(payload)
        if not self.vao:
            self.vao = self.ctx.vertex_array(
                shader_prog,
                [(self.vbo, "3f4 3f4 1f4", "in_vert", "in_color", "in_time")],
            )

    def _get_volume_at(self, world_pos):
        """Finds or generates procedural data for a point."""
        grid_origin = (np.array(world_pos) // 64.0) * 64.0
        key = tuple(grid_origin.tolist())
        if key not in self._active_volumes:
            vol = Volume(grid_origin)
            self._active_volumes[key] = vol.hydrate(0.0)
        return self._active_volumes[key]

    def check_collision(self, world_pos):
        """Checks if a point is inside a procedural voxel."""
        if world_pos[1] <= 0.1:
            return True

        data = self._get_volume_at(world_pos)
        # Spatial distance check
        dists = np.linalg.norm(data[:, 0:3] - world_pos, axis=1)
        # Use .item() to convert numpy bool to python bool for the test suite
        return bool(np.any(dists < 0.6))

    def get_visible_frame(self, pos, front, radius, system_heat=0):
        """Converts procedural data to the VoxelRecord format for tests."""
        data = self._get_volume_at(pos)
        records = np.empty(len(data), dtype=VoxelRecord.EXT_DTYPE)
        records["p"] = data[:, 0:3]
        records["c"] = data[:, 3:6]
        records["t"] = data[:, 6]
        return records

    def manifest_voxel(self, world_pos, color):
        """Legacy mock for manifest call."""
        pass

    def _bloom_entropy(self, cx, cz, heat, timestamp):
        """Legacy mock for bloom call."""
        pass
