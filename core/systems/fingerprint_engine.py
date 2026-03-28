import math


# All trackable behavioral dimensions
DIMENSIONS = [
    'exploration_time',
    'crafting_time',
    'observation_time',
    'combat_time',
    'audio_interactions',
    'workbench_interactions',
    'objects_inspected',
    'distance_average',
    'overwhelm_count',
    'negotiate_count',
    'endure_count',
    'retreat_count',
    'food_prepared',
    'puzzle_attempts',
    'timing_accuracy',
    'rhythm_pattern_score',
    'precision_score',
    'crafting_tier',
    'creature_interactions',
    'unknown_combinations',
]

# Activity → dimension mapping for tick()
ACTIVITY_MAP = {
    'exploring':   'exploration_time',
    'crafting':    'crafting_time',
    'observing':   'observation_time',
    'combat':      'combat_time',
    'audio':       'audio_interactions',
    'idle':        None,
}

# Decay rates -- dimensions fade slowly if not reinforced
DECAY_RATE = 0.0001  # per second of real time


class FingerprintEngine:
    '''
    Tracks behavioral dimensions in real time.
    All values normalized 0.0-1.0.
    Feeds GhostProfileEngine for world calibration.
    Never shown to player -- expressed through world response.
    '''

    def __init__(self):
        self.state        = {dim: 0.0 for dim in DIMENSIONS}
        self._time_totals = {dim: 0.0 for dim in DIMENSIONS}
        self._total_time  = 0.0
        self._session_time= 0.0

    def record(self, dimension, value):
        '''
        Record a behavioral event.
        value: intensity 0.0-1.0 or count (will be normalized)
        Accumulates with sigmoid compression so nothing saturates.
        '''
        if dimension not in self.state:
            return
        current = self.state[dimension]
        # Sigmoid accumulation -- diminishing returns near 1.0
        delta = value * (1.0 - current) * 0.3
        self.state[dimension] = min(1.0, current + delta)

    def tick(self, dt, activity='idle'):
        '''
        Update time-based dimensions.
        dt: seconds elapsed
        activity: current player activity string
        '''
        self._total_time   += dt
        self._session_time += dt

        dim = ACTIVITY_MAP.get(activity)
        if dim:
            self._time_totals[dim] += dt
            # Normalize against total session time
            if self._session_time > 0:
                ratio = self._time_totals[dim] / self._session_time
                self.state[dim] = min(1.0, ratio)

    def export(self):
        '''Return current fingerprint as normalized dict.'''
        return dict(self.state)

    def dominant_activity(self):
        '''Return the activity dimension with highest value.'''
        activity_dims = {
            k: self.state[k] for k in [
                'exploration_time', 'crafting_time',
                'observation_time', 'combat_time',
            ]
        }
        best = max(activity_dims, key=activity_dims.get)
        return best.replace('_time', '')

    def reset_session(self):
        '''Reset session-specific counters. Keep cumulative history.'''
        self._session_time = 0.0
        for dim in DIMENSIONS:
            self._time_totals[dim] = 0.0

    def apply_decay(self, real_seconds_elapsed):
        '''
        Apply time-based decay for offline periods.
        Dimensions fade slightly when player is away.
        Core identity persists -- only surface behavior fades.
        '''
        decay = min(0.3, real_seconds_elapsed * DECAY_RATE)
        for dim in DIMENSIONS:
            self.state[dim] = max(0.0, self.state[dim] - decay)