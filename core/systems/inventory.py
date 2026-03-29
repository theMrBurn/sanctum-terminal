"""
core/systems/inventory.py

Eight slots. Weight limit. Provenance preserved.
Every object you carry has a history.
The world notices what you choose to hold.
"""


class Inventory:
    """
    The player carries eight things at a time.
    Not because of arbitrary game design.
    Because attention is finite.
    Weight is real. Choice matters.
    """

    DEFAULT_WEIGHT = 0.5  # objects without declared weight

    def __init__(self, max_slots=8, max_weight=20.0):
        self.max_slots  = max_slots
        self.max_weight = max_weight
        self._slots     = {}   # id -> object dict

    def pickup(self, obj):
        """
        Pick up an object. Returns True if successful.
        Fails silently if slots or weight exceeded.
        The world does not punish you for trying.
        """
        if len(self._slots) >= self.max_slots:
            return False
        w = obj.get("weight", self.DEFAULT_WEIGHT)
        if self.current_weight() + w > self.max_weight:
            return False
        obj_id = obj.get("id", f"obj_{len(self._slots)}")
        self._slots[obj_id] = dict(obj)
        return True

    def drop(self, obj_id):
        """
        Drop an object by id. Returns the object or None.
        The world receives it back.
        """
        return self._slots.pop(obj_id, None)

    def get(self, obj_id):
        """Return object by id without removing it."""
        return self._slots.get(obj_id)

    def list(self):
        """Return all carried objects as a list."""
        return list(self._slots.values())

    def count(self):
        """Number of objects currently carried."""
        return len(self._slots)

    def current_weight(self):
        """Total weight of all carried objects."""
        return sum(
            o.get("weight", self.DEFAULT_WEIGHT)
            for o in self._slots.values()
        )

    def has_space(self, weight=0.0):
        """True if there is a slot and weight capacity available."""
        return (
            len(self._slots) < self.max_slots
            and self.current_weight() + weight <= self.max_weight
        )

    def is_empty(self):
        return len(self._slots) == 0

    def snapshot(self):
        """Serialize for Grace checkpoint."""
        return dict(self._slots)

    def restore(self, snapshot):
        """Restore from Grace checkpoint."""
        self._slots = dict(snapshot)