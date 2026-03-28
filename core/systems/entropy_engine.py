"""
core/systems/entropy_engine.py

Every living thing has a place where it belongs.
This engine calculates how much any given species belongs
at any given point in the world.

P(E) = product of Gaussian attunements across local conditions.
The world grows where it belongs. Not where it is placed.
"""
import copy
import math
import random


class EntropyEngine:
    """
    Ecological placement engine.
    Each species has ideal conditions — elevation, moisture, slope.
    Proximity to ideal yields high attunement.
    Distance from ideal yields low attunement.
    The interference of all three determines where life takes root.
    """

    # Ideal conditions per species.
    # mu    = the sweet spot
    # sigma = the grit — how far from ideal before presence fades
    IDEALS = {
        'OAK': {
            'elevation': {'mu':  4.0, 'sigma': 6.0},
            'moisture':  {'mu': 0.55, 'sigma': 0.25},
            'slope':     {'mu':  0.1, 'sigma': 0.15},
        },
        'PINE': {
            'elevation': {'mu': 12.0, 'sigma': 5.0},
            'moisture':  {'mu': 0.30, 'sigma': 0.20},
            'slope':     {'mu': 0.45, 'sigma': 0.20},
        },
        'WILLOW': {
            'elevation': {'mu':  1.0, 'sigma': 3.0},
            'moisture':  {'mu': 0.85, 'sigma': 0.15},
            'slope':     {'mu': 0.05, 'sigma': 0.08},
        },
        'DEAD': {
            'elevation': {'mu':  8.0, 'sigma': 6.0},
            'moisture':  {'mu': 0.12, 'sigma': 0.15},
            'slope':     {'mu': 0.25, 'sigma': 0.20},
        },
        'YOUNG': {
            'elevation': {'mu':  3.0, 'sigma': 5.0},
            'moisture':  {'mu': 0.50, 'sigma': 0.30},
            'slope':     {'mu': 0.15, 'sigma': 0.20},
        },
        'ANCIENT': {
            'elevation': {'mu':  0.0, 'sigma': 4.0},
            'moisture':  {'mu': 0.70, 'sigma': 0.20},
            'slope':     {'mu': 0.03, 'sigma': 0.06},
        },
        'SHRUB': {
            'elevation': {'mu':  2.0, 'sigma': 5.0},
            'moisture':  {'mu': 0.50, 'sigma': 0.35},
            'slope':     {'mu': 0.05, 'sigma': 0.08},
        },
    }

    # The Wide Relational Curve — render presence by distance
    FOCUS_DIST    = 10.0   # full presence, SURREAL_SPEC active
    MIDFIELD_DIST = 30.0   # silhouette, Another World vectors
    HORIZON_DIST  = 40.0   # Carcosa threshold — dither and fade

    def gaussian(self, value, mu, sigma):
        """
        How close is this value to the ideal?
        Returns 1.0 at perfect attunement, approaches 0.0 at the margins.
        """
        return float(math.exp(-((value - mu) ** 2) / (2 * sigma ** 2)))

    def attunement(self, species, elevation, moisture, slope):
        """
        How much does this species belong here?

        P(E) = gaussian(elevation) * gaussian(moisture) * gaussian(slope)

        Returns 1.0 at perfect conditions.
        Returns near 0.0 at the margins.
        The world grows where it belongs.
        """
        if species not in self.IDEALS:
            raise ValueError(
                f'Unknown species: {species!r}. '
                f'Known: {list(self.IDEALS.keys())}'
            )
        ideal = self.IDEALS[species]
        return float(
            self.gaussian(elevation, **ideal['elevation'])
            * self.gaussian(moisture,  **ideal['moisture'])
            * self.gaussian(slope,     **ideal['slope'])
        )

    # Keep placement_weight as alias — tests reference it
    def placement_weight(self, tree_type, elevation, moisture, slope):
        """Alias for attunement(). Preserved for test compatibility."""
        return self.attunement(tree_type, elevation, moisture, slope)

    def pick_tree_type(self, elevation, moisture, slope, rng=None):
        """
        Which species belongs here most?

        Weighted sampling from attunement scores.
        Nothing is impossible — only some things are unlikely.
        The world has exceptions. That is what makes it feel alive.
        """
        if rng is None:
            rng = random
        weights = {
            s: self.attunement(s, elevation, moisture, slope)
            for s in self.IDEALS
        }
        # Every species has a minimum presence — nothing is banished
        weights = {s: max(0.02, w) for s, w in weights.items()}
        species = list(weights.keys())
        vals    = list(weights.values())
        return rng.choices(species, weights=vals, k=1)[0]

    def presence_tier(self, distance):
        """
        Where does this distance fall on the Wide Relational Curve?

        FOCUS    — full presence, sharp, SURREAL_SPEC active
        MIDFIELD — silhouette, flat vectors, Another World
        HORIZON  — the Carcosa threshold, dither and fade
        """
        if distance < self.FOCUS_DIST:
            return 'FOCUS'
        elif distance < self.HORIZON_DIST:
            return 'MIDFIELD'
        else:
            return 'HORIZON'

    # Keep lod_tier as alias — tests reference it
    def lod_tier(self, distance):
        """Alias for presence_tier(). Preserved for test compatibility."""
        return self.presence_tier(distance)

    def sigmoid_weight(self, distance):
        """
        Render weight by distance.
        1.0 at the threshold of presence.
        0.0 at the horizon.
        Smooth — nothing cuts, everything fades.
        """
        k = 0.15  # steepness of the curve
        return float(1.0 / (1.0 + math.exp(k * (distance - self.MIDFIELD_DIST))))

    def attune_to_seed(self, seed_params):
        """
        Shift species ideals to reflect the world's seed parameters.

        The interview spoke. The ecology listens.
        High moisture shifts WILLOW and ANCIENT toward abundance.
        High heat shifts DEAD toward prevalence.

        Returns modified IDEALS — does not alter the original.
        """
        ideals   = copy.deepcopy(self.IDEALS)
        moisture = seed_params.get('moisture', 0.5)
        heat     = seed_params.get('heat', 0.5)
        ideals['WILLOW']['moisture']['mu']   = min(0.95, moisture + 0.1)
        ideals['ANCIENT']['moisture']['mu']  = min(0.90, moisture + 0.05)
        ideals['DEAD']['moisture']['mu']     = max(0.02, 0.12 - heat * 0.1)
        ideals['DEAD']['elevation']['sigma'] = 4.0 + heat * 4.0
        return ideals

    # Keep interview_modifiers as alias — tests reference it
    def interview_modifiers(self, seed_params):
        """Alias for attune_to_seed(). Preserved for test compatibility."""
        return self.attune_to_seed(seed_params)