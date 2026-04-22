"""Numbered schema migrations for config/kind_config.json.

Each migration is a module `NNN_name.py` declaring `VERSION`, `DESCRIPTION`,
`up(config) -> config` and `down(config) -> config`. The runner discovers
them by filename order; version numbers must be monotonic with no gaps.
"""
