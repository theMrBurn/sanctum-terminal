"""
core/systems/config_engine.py

Config-as-code engine. Loads sanctum.toml, exposes it as a live namespace,
provides an in-engine REPL for real-time manipulation.

Usage:
    cfg = ConfigEngine("config/sanctum.toml")
    cfg.fog.near          # 25.0
    cfg.fog.near = 30     # updates live, triggers watchers
    cfg.save()            # writes back to TOML
    cfg.save("presets/dark_mood.toml")  # named preset
    cfg.load("presets/dark_mood.toml")  # restore
"""

import os

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # pip install tomli for 3.10
    except ImportError:
        tomllib = None


class ConfigNode:
    """Dot-accessible config namespace. Supports nested access and watchers."""

    def __init__(self, data=None, root=None, path=""):
        object.__setattr__(self, '_data', data or {})
        object.__setattr__(self, '_root', root or self)
        object.__setattr__(self, '_path', path)
        object.__setattr__(self, '_watchers', {} if root is None else root._watchers)

    def __getattr__(self, key):
        d = object.__getattribute__(self, '_data')
        if key.startswith('_'):
            return object.__getattribute__(self, key)
        if key not in d:
            raise AttributeError(f"No config key: {self._path}.{key}" if self._path else f"No config key: {key}")
        val = d[key]
        if isinstance(val, dict):
            return ConfigNode(val, root=self._root, path=f"{self._path}.{key}" if self._path else key)
        return val

    def __setattr__(self, key, value):
        if key.startswith('_'):
            object.__setattr__(self, key, value)
            return
        d = object.__getattribute__(self, '_data')
        d[key] = value
        full_path = f"{self._path}.{key}" if self._path else key
        # Fire watchers
        watchers = object.__getattribute__(self, '_watchers')
        for pattern, fn in watchers.items():
            if full_path.startswith(pattern) or pattern == "*":
                fn(full_path, value)

    def __repr__(self):
        try:
            d = object.__getattribute__(self, '_data')
            path = object.__getattribute__(self, '_path')
            if not path:
                sections = [k for k in d if isinstance(d[k], dict)]
                scalars = [k for k in d if not isinstance(d[k], dict)]
                parts = []
                if sections:
                    parts.append(f"sections: {', '.join(sections)}")
                if scalars:
                    parts.append(f"keys: {', '.join(scalars)}")
                return f"<Config {' | '.join(parts)}>"
            items = []
            for k, v in d.items():
                if isinstance(v, dict):
                    items.append(f"  {k}: {{...}}")
                else:
                    items.append(f"  {k} = {v!r}")
            return f"[{path}]\n" + "\n".join(items)
        except Exception as e:
            return f"<ConfigNode error: {e}>"

    def __iter__(self):
        return iter(object.__getattribute__(self, '_data'))

    def _get_nested(self, dotpath):
        """Get a value by dot-separated path string."""
        parts = dotpath.split(".")
        node = self
        for p in parts:
            node = getattr(node, p)
        return node

    def _set_nested(self, dotpath, value):
        """Set a value by dot-separated path string."""
        parts = dotpath.split(".")
        node = self
        for p in parts[:-1]:
            node = getattr(node, p)
        setattr(node, parts[-1], value)

    def watch(self, pattern, fn):
        """Register a watcher. fn(path, value) called on matching changes."""
        watchers = object.__getattribute__(self, '_watchers')
        watchers[pattern] = fn

    def to_dict(self):
        """Recursively convert back to plain dict."""
        d = object.__getattribute__(self, '_data')
        out = {}
        for k, v in d.items():
            if isinstance(v, dict):
                out[k] = ConfigNode(v).to_dict()
            else:
                out[k] = v
        return out


class ConfigEngine:
    """Loads TOML config, exposes as live namespace, saves presets."""

    def __init__(self, path="config/sanctum.toml"):
        self._path = path
        self._cfg = ConfigNode()
        if os.path.exists(path):
            self.load(path)

    def load(self, path=None):
        """Load a TOML file into the config namespace."""
        path = path or self._path
        if tomllib is None:
            # Fallback: try to read as JSON-ish
            print(f"[config] tomllib not available, skipping {path}")
            return
        with open(path, "rb") as f:
            data = tomllib.load(f)
        self._cfg = ConfigNode(data)
        return self._cfg

    def save(self, path=None):
        """Write current config state to TOML."""
        path = path or self._path
        data = self._cfg.to_dict()
        lines = _dict_to_toml(data)
        with open(path, "w") as f:
            f.write(lines)
        print(f"[config] Saved to {path}")

    @property
    def root(self):
        return self._cfg

    def __getattr__(self, key):
        if key.startswith('_'):
            return object.__getattribute__(self, key)
        return getattr(self._cfg, key)

    def __setattr__(self, key, value):
        if key.startswith('_'):
            object.__setattr__(self, key, value)
        else:
            setattr(self._cfg, key, value)

    def __repr__(self):
        return repr(self._cfg)


def _toml_value(v):
    """Format a Python value as TOML."""
    if isinstance(v, bool):
        return "true" if v else "false"
    elif isinstance(v, str):
        return f'"{v}"'
    elif isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    elif isinstance(v, float):
        return f"{v}"
    elif isinstance(v, int):
        return f"{v}"
    elif isinstance(v, dict):
        return "{ " + ", ".join(f'{k} = {_toml_value(val)}' for k, val in v.items()) + " }"
    return repr(v)


def _dict_to_toml(data, prefix=""):
    """Recursively convert dict to TOML string."""
    lines = []
    # Scalars first
    for k, v in data.items():
        if not isinstance(v, dict):
            lines.append(f"{k} = {_toml_value(v)}")
    # Then sections
    for k, v in data.items():
        if isinstance(v, dict):
            # Check if it's an inline table (no nested dicts)
            has_nested = any(isinstance(vv, dict) for vv in v.values())
            section = f"{prefix}.{k}" if prefix else k
            lines.append(f"\n[{section}]")
            lines.extend(_dict_to_toml(v, section).split("\n"))
    return "\n".join(lines)
