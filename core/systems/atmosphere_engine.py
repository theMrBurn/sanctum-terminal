"""
core/systems/atmosphere_engine.py

Global atmospheric state controller.
One truth. All systems subscribe.
Nothing is instant -- everything breathes.
"""


# Default atmospheric state -- neutral world
DEFAULTS = {
    'clarity_radius':   1.0,   # sigmoid LOD peak
    'entropy_jitter':   0.0,   # vertex wobble
    'dither_depth':     0.0,   # bayer 4x4 density
    'specular_bleed':   0.2,   # surreal_spec intensity
    'moisture':         0.5,   # world wetness
    'heat':             0.4,   # world temperature
    'friction':         0.85,  # movement feel
    'time_of_day':      0.6,   # 0=midnight 1=noon
    'encounter_density':0.3,   # creature activity
    'karma':            0.5,   # world disposition
}


class AtmosphereEngine:
    """
    Global state controller for the world's atmosphere.
    All systems read from here. Nothing writes directly.
    Changes lerp over time -- no hard cuts.
    Ghost profile modifiers applied as multipliers.
    """

    def __init__(self):
        self.state          = dict(DEFAULTS)
        self._targets       = {}   # key -> (target, duration, elapsed)
        self._subscribers   = {}   # key -> [callbacks]
        self.ghost_modifiers= {}   # from GhostProfileEngine

    def set(self, key, value, duration=0.0):
        """
        Set an atmospheric value.
        duration=0 → instant
        duration>0 → lerp over N seconds
        """
        if key not in self.state:
            return
        value = max(0.0, min(1.0, float(value)))
        if duration <= 0.0:
            self.state[key] = value
            self._targets.pop(key, None)
            self._fire(key, value)
        else:
            self._targets[key] = {
                'target':   value,
                'duration': duration,
                'elapsed':  0.0,
                'start':    self.state[key],
            }

    def tick(self, dt):
        """
        Advance all lerp targets.
        Call every frame with delta time.
        """
        done = []
        for key, t in self._targets.items():
            t['elapsed'] += dt
            progress = min(1.0, t['elapsed'] / t['duration'])
            # Smooth step interpolation
            smooth = progress * progress * (3 - 2 * progress)
            value  = t['start'] + (t['target'] - t['start']) * smooth
            self.state[key] = value
            self._fire(key, value)
            if progress >= 1.0:
                self.state[key] = t['target']
                done.append(key)
        for key in done:
            self._targets.pop(key)

    def subscribe(self, key, callback):
        """Register a callback for when key changes."""
        if key not in self._subscribers:
            self._subscribers[key] = []
        self._subscribers[key].append(callback)

    def unsubscribe(self, key, callback):
        """Remove a callback."""
        if key in self._subscribers:
            try:
                self._subscribers[key].remove(callback)
            except ValueError:
                pass

    def from_seed_params(self, params):
        """
        Apply interview seed params to atmosphere.
        Called once on world load.
        """
        mapping = {
            'moisture':          'moisture',
            'heat':              'heat',
            'encounter_density': 'encounter_density',
            'karma_baseline':    'karma',
            'ambient_intensity': 'clarity_radius',
        }
        for param, key in mapping.items():
            if param in params:
                self.set(key, float(params[param]))

    def from_ghost_modifiers(self, modifiers):
        """
        Apply ghost profile world modifiers.
        Stored as multipliers -- applied via get_modifier().
        """
        self.ghost_modifiers.update(modifiers)

    def get_modifier(self, key, default=1.0):
        """
        Get a ghost profile modifier value.
        Returns default (1.0) if not set -- neutral multiplier.
        """
        val = self.ghost_modifiers.get(key, default)
        return float(val) if isinstance(val, (int, float)) else default

    def _fire(self, key, value):
        """Fire all callbacks for a key."""
        for cb in self._subscribers.get(key, []):
            try:
                cb(value)
            except Exception:
                pass

    def snapshot(self):
        """Return current state as a plain dict for Grace checkpointing."""
        return dict(self.state)

    def restore(self, snapshot):
        """Restore state from a Grace checkpoint."""
        for key, value in snapshot.items():
            if key in self.state:
                self.state[key] = float(value)