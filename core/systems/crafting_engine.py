import hashlib
import json
from pathlib import Path


def _load_json(path):
    p = Path(path)
    if p.exists():
        return json.load(open(p))
    return {}


class CraftingEngine:
    """
    Combines two objects into a crafted result.
    Known recipes produce defined objects.
    Unknown combinations produce UNNAMED objects.
    All results are provenance-hashed and stored in history.
    Order-independent -- craft(a,b) == craft(b,a).
    """

    def __init__(self):
        self._recipes = _load_json('config/blueprints/crafting.json')
        self._objects = _load_json('config/blueprints/objects.json')
        self._history = []

    def craft(self, input_a, input_b):
        """
        Combine two object keys into a crafted result.
        Returns result dict with name, primitive, description,
        ability, impact_rating, provenance_hash.
        """
        # Normalize order -- always sort so craft(a,b)==craft(b,a)
        key_a, key_b = sorted([input_a, input_b])

        # Find matching recipe
        result = None
        for recipe_name, recipe in self._recipes.items():
            if recipe_name == 'UNKNOWN':
                continue
            inputs = sorted(recipe['inputs'])
            if inputs == [key_a, key_b]:
                result = dict(recipe['output'])
                break

        # Unknown combo -- return UNNAMED
        if result is None:
            result = dict(self._recipes.get('UNKNOWN', {}).get('output', {
                'name': 'Unnamed Object',
                'primitive': 'BLOCK',
                'description': 'Something happened. Not sure what yet.',
                'ability': 'Unknown',
                'impact_rating': 1,
            }))

        # Provenance hash -- deterministic from sorted inputs
        raw = json.dumps({'a': key_a, 'b': key_b}, sort_keys=True)
        result['provenance_hash'] = hashlib.sha256(
            raw.encode()).hexdigest()[:16]
        result['inputs'] = [key_a, key_b]

        # Store in history
        self._history.append(result)
        return result

    def get_history(self):
        """Return all crafted objects this session."""
        return list(self._history)

    def get_object(self, key):
        """Look up a base object from the catalog."""
        for cat in self._objects.values():
            if key in cat:
                return cat[key]
        return None

    def get_all_objects(self):
        """Return flat dict of all catalog objects."""
        all_objs = {}
        for cat in self._objects.values():
            all_objs.update(cat)
        return all_objs

    def recipes_for(self, object_key):
        """Return all recipes that use this object."""
        matches = []
        for name, recipe in self._recipes.items():
            if object_key in recipe.get('inputs', []):
                matches.append((name, recipe))
        return matches