import numpy as np


class RelativityEngine:
    @staticmethod
    def get_local_frame(absolute_voxels, observer_pos, observer_front, radius):
        if absolute_voxels is None or len(absolute_voxels) == 0:
            return np.array([], dtype=[("p", "f4", (3,)), ("c", "f4", (3,))])

        # 1. THE OFFSET (Vectorized) - Observer is always [0,0,0]
        abs_p = absolute_voxels["p"]
        local_p = abs_p - np.array(observer_pos)

        # 2. DISTANCE MASK
        dists = np.linalg.norm(local_p, axis=1)
        mask = dists <= radius

        # 3. FRUSTUM CULLING
        if observer_front is not None:
            norm_p = local_p / (dists[:, np.newaxis] + 1e-6)
            mask &= np.dot(norm_p, np.array(observer_front)) > -0.45

        local_frame = absolute_voxels[mask].copy()
        local_frame["p"] = local_p[mask]

        return local_frame
