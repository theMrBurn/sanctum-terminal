import math
import random


class EntropyEngine:
    """
    Gaussian placement weights for ecological tree distribution.
    Every tree type has ideal conditions (elevation, moisture, slope).
    P(E) = product of gaussians across all local variables.
    The world grows where it belongs.
    """

    # Ideal conditions per tree type
    # mu = ideal value, sigma = tolerance (grit)
    IDEALS = {
        'OAK': {
            'elevation': {'mu': 4.0,  'sigma': 6.0},
            'moisture':  {'mu': 0.55, 'sigma': 0.25},
            'slope':     {'mu': 0.1,  'sigma': 0.15},
        },
        'PINE': {
            'elevation': {'mu': 12.0, 'sigma': 5.0},
            'moisture':  {'mu': 0.30, 'sigma': 0.20},
            'slope':     {'mu': 0.45, 'sigma': 0.20},
        },
        'WILLOW': {
            'elevation': {'mu': 1.0,  'sigma': 3.0},
            'moisture':  {'mu': 0.85, 'sigma': 0.15},
            'slope':     {'mu': 0.05, 'sigma': 0.08},
        },
        'DEAD': {
            'elevation': {'mu': 8.0,  'sigma': 6.0},
            'moisture':  {'mu': 0.12, 'sigma': 0.15},
            'slope':     {'mu': 0.25, 'sigma': 0.20},
        },
        'YOUNG': {
            'elevation': {'mu': 3.0,  'sigma': 5.0},
            'moisture':  {'mu': 0.50, 'sigma': 0.30},
            'slope':     {'mu': 0.15, 'sigma': 0.20},
        },
        'ANCIENT': {
            'elevation': {'mu': 0.0,  'sigma': 4.0},
            'moisture':  {'mu': 0.70, 'sigma': 0.20},
            'slope':     {'mu': 0.03, 'sigma': 0.06},
        },
        'SHRUB': {
            'elevation': {'mu': 2.0,  'sigma': 5.0},
            'moisture':  {'mu': 0.50, 'sigma': 0.35},
            'slope':     {'mu': 0.05, 'sigma': 0.08},
        },
    }

    # Wide Relational Curve thresholds
    FOCUS_DIST    = 10.0
    MIDFIELD_DIST = 30.0
    HORIZON_DIST  = 40.0

    def gaussian(self, value, mu, sigma):
        """
        Single Gaussian score.
        Returns 1.0 at ideal (value==mu), approaches 0.0 further away.
        """
        return float(math.exp(-((value - mu) ** 2) / (2 * sigma ** 2)))

    def placement_weight(self, tree_type, elevation, moisture, slope):
        """
        P(E) = product of gaussians across elevation, moisture, slope.
        Returns float 0.0-1.0.
        Higher = more likely to place this tree type here.
        """
        if tree_type not in self.IDEALS:
            raise ValueError(
                f'EntropyEngine: unknown tree type {tree_type!r}. '
                f'Valid: {list(self.IDEALS.keys())}'
            )
        ideal = self.IDEALS[tree_type]
        p_elev = self.gaussian(elevation, **ideal['elevation'])
        p_mois = self.gaussian(moisture,  **ideal['moisture'])
        p_slop = self.gaussian(slope,     **ideal['slope'])
        return float(p_elev * p_mois * p_slop)

    def pick_tree_type(self, elevation, moisture, slope, rng=None):
        """
        Sample a tree type weighted by placement_weight at local conditions.
        Uses entropy math -- not pure frequency weights.
        The world grows where it belongs.
        """
        if rng is None:
            rng = random
        weights = {
            t: self.placement_weight(t, elevation, moisture, slope)
            for t in self.IDEALS
        }
        # Normalize -- ensure at least min weight so nothing is impossible
        min_w = 0.02
        weights = {t: max(min_w, w) for t, w in weights.items()}
        types  = list(weights.keys())
        vals   = list(weights.values())
        return rng.choices(types, weights=vals, k=1)[0]

    def lod_tier(self, distance):
        """
        Wide Relational Curve -- LOD tier from camera distance.
        FOCUS    d < 10  : full detail + SURREAL_SPEC
        MIDFIELD 10-30   : flat vector silhouettes
        HORIZON  d > 40  : dithered, P(E) near 0
        """
        if distance < self.FOCUS_DIST:
            return 'FOCUS'
        elif distance < self.HORIZON_DIST:
            return 'MIDFIELD'
        else:
            return 'HORIZON'

    def sigmoid_weight(self, distance):
        """
        Sigmoid activation for render weight.
        1.0 at distance=0, 0.0 at distance=infinity.
        Smooth falloff across the wide relational curve.
        """
        # Sigmoid centered at MIDFIELD_DIST
        k = 0.15  # steepness
        return float(1.0 / (1.0 + math.exp(k * (distance - self.MIDFIELD_DIST))))

    def interview_modifiers(self, seed_params):
        """
        Apply interview seed params to IDEALS.
        moisture shifts WILLOW/ANCIENT probability.
        heat shifts DEAD probability.
        Returns modified IDEALS copy -- does not mutate original.
        """
        import copy
        ideals = copy.deepcopy(self.IDEALS)
        moisture = seed_params.get('moisture', 0.5)
        heat     = seed_params.get('heat', 0.5)
        # High moisture -- WILLOW and ANCIENT thrive
        ideals['WILLOW']['moisture']['mu']  = min(0.95, moisture + 0.1)
        ideals['ANCIENT']['moisture']['mu'] = min(0.90, moisture + 0.05)
        # High heat -- DEAD trees spread
        ideals['DEAD']['moisture']['mu']    = max(0.02, 0.12 - heat * 0.1)
        ideals['DEAD']['elevation']['sigma']= 4.0 + heat * 4.0
        return ideals