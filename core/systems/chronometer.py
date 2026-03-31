"""
core/systems/chronometer.py

Real-time chronometric system — binds game world to actual time of day.

No accelerated clock. No game-time. Just reality leaking in.
The player never sees a clock — they feel it.

Reads system datetime and outputs normalized values (0.0-1.0) that
other systems consume to modulate behavior, lighting, density, mood.

Usage:
    chrono = Chronometer()

    # In game loop:
    state = chrono.read()
    fog_density = 0.8 + state["night_weight"] * 0.4
    rat_activity = 0.3 + state["nocturnal"] * 0.7
"""

import datetime
import math


class Chronometer:
    """Real-time chronometric state. No game clock — real clock."""

    def __init__(self, timezone=None):
        """Initialize. timezone=None uses system local time."""
        self._tz = timezone

    def read(self):
        """Read current chronometric state. Call once per frame or per cycle.

        Returns dict of normalized 0.0-1.0 values:
            hour_24:      raw hour (0-23)
            time_of_day:  0.0=midnight, 0.25=6am, 0.5=noon, 0.75=6pm
            day_phase:    "night" / "dawn" / "day" / "dusk"
            night_weight: 0.0=full day, 1.0=deep night (smooth curve)
            dawn_weight:  peaks at sunrise
            dusk_weight:  peaks at sunset
            nocturnal:    activity multiplier for nocturnal creatures
            diurnal:      activity multiplier for daytime creatures
            day_of_week:  0=Monday, 6=Sunday (normalized 0.0-1.0)
            season:       0.0=winter solstice, 0.5=summer solstice (northern hemisphere)
            moon_approx:  rough 29.5-day cycle, 0.0=new, 0.5=full, 1.0=new
        """
        now = datetime.datetime.now(self._tz)
        hour = now.hour + now.minute / 60.0 + now.second / 3600.0

        # Time of day: 0.0 = midnight, 0.5 = noon
        time_of_day = hour / 24.0

        # Night weight: smooth curve, peaks at midnight, zero at noon
        # Uses cosine so transitions are gentle, not stepped
        night_weight = (math.cos(time_of_day * 2 * math.pi) + 1.0) / 2.0

        # Dawn/dusk windows (roughly 5-7am and 5-7pm)
        dawn_center = 6.0 / 24.0   # 6am
        dusk_center = 18.0 / 24.0   # 6pm
        window = 1.5 / 24.0         # ±1.5 hours

        dawn_dist = abs(time_of_day - dawn_center)
        dawn_weight = max(0.0, 1.0 - dawn_dist / window) if dawn_dist < window else 0.0

        dusk_dist = abs(time_of_day - dusk_center)
        dusk_weight = max(0.0, 1.0 - dusk_dist / window) if dusk_dist < window else 0.0

        # Phase label
        if dawn_weight > 0.3:
            phase = "dawn"
        elif dusk_weight > 0.3:
            phase = "dusk"
        elif night_weight > 0.5:
            phase = "night"
        else:
            phase = "day"

        # Creature activity curves
        # Nocturnal: active at night, peak at midnight
        nocturnal = night_weight
        # Diurnal: active during day, peak at noon
        diurnal = 1.0 - night_weight

        # Day of week (0=Monday)
        day_of_week = now.weekday() / 6.0

        # Season approximation (northern hemisphere, based on day of year)
        day_of_year = now.timetuple().tm_yday
        # Winter solstice ~Dec 21 = day 355. Offset so 0.0 = winter solstice.
        season = ((day_of_year - 355) % 365) / 365.0
        # Convert to 0=winter solstice, 0.5=summer solstice
        season_weight = (math.cos(season * 2 * math.pi) + 1.0) / 2.0

        # Moon phase approximation (synodic period ~29.53 days)
        # Known new moon: Jan 6, 2000
        known_new = datetime.datetime(2000, 1, 6, 18, 14)
        days_since = (now - known_new).total_seconds() / 86400.0
        moon_phase = (days_since % 29.53) / 29.53  # 0=new, 0.5≈full

        return {
            "hour_24": int(now.hour),
            "time_of_day": time_of_day,
            "day_phase": phase,
            "night_weight": night_weight,
            "dawn_weight": dawn_weight,
            "dusk_weight": dusk_weight,
            "nocturnal": nocturnal,
            "diurnal": diurnal,
            "day_of_week": day_of_week,
            "season": season_weight,
            "moon_approx": moon_phase,
        }
