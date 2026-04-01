"""
core/systems/repl.py

In-engine Python REPL overlay. Type Python directly into the game.

Usage (in cavern2.py):
    from core.systems.repl import EngineREPL
    self._repl = EngineREPL(self, self._cfg)
    # ~ key toggles it (bound automatically)
"""

from panda3d.core import TextNode
from direct.gui.OnscreenText import OnscreenText
from direct.gui.DirectGui import DirectEntry


class EngineREPL:
    """In-engine Python REPL. ~ to toggle, enter to execute, up for history."""

    MAX_HISTORY = 50
    MAX_OUTPUT_LINES = 12

    def __init__(self, app, cfg, namespace=None):
        self._app = app
        self._cfg = cfg
        self._visible = False
        self._history = []
        self._history_idx = 0
        self._output_lines = []

        # Build the namespace available in the REPL
        self._ns = {
            "cfg": cfg,
            "fog": getattr(cfg, 'fog', None),
            "camera": getattr(cfg, 'camera', None),
            "lighting": getattr(cfg, 'lighting', None),
            "ground": getattr(cfg, 'ground', None),
            "lod": getattr(cfg, 'lod', None),
            "postprocess": getattr(cfg, 'postprocess', None),
            "daylight": getattr(cfg, 'daylight', None),
            "entity": getattr(cfg, 'entity', None),
            "world": getattr(cfg, 'world', None),
            "save": lambda path=None: cfg.save(path),
            "load": lambda path=None: cfg.load(path),
            "app": app,
            "here": lambda: (app.cam.getX(), app.cam.getY(), app.cam.getZ()),
        }
        if namespace:
            self._ns.update(namespace)

        # Output display
        self._output_text = OnscreenText(
            text="", pos=(-1.25, -0.5), scale=0.035,
            fg=(0.0, 1.0, 0.4, 0.9), align=TextNode.ALeft,
            mayChange=True, shadow=(0, 0, 0, 0.85),
        )
        self._output_text.hide()

        # Prompt
        self._prompt = OnscreenText(
            text="~ ", pos=(-1.25, -0.72), scale=0.04,
            fg=(1.0, 0.9, 0.3, 0.9), align=TextNode.ALeft,
            mayChange=True, shadow=(0, 0, 0, 0.85),
        )
        self._prompt.hide()

        # Input field
        self._entry = DirectEntry(
            text="", scale=0.04, pos=(-1.15, 0, -0.72),
            width=50, numLines=1,
            focus=0, frameColor=(0, 0, 0, 0.7),
            text_fg=(1, 1, 1, 1), text_font=None,
            command=self._on_enter,
            suppressKeys=1,
        )
        self._entry.hide()

        # Keybinds
        app.accept("shift-`", self._toggle)

    def _toggle(self):
        self._visible = not self._visible
        if self._visible:
            self._output_text.show()
            self._prompt.show()
            self._entry.show()
            self._entry["focus"] = 1
            self._show_output("[REPL] Type Python. cfg.fog.near, save(), help(cfg)")
        else:
            self._output_text.hide()
            self._prompt.hide()
            self._entry.hide()
            self._entry["focus"] = 0

    def _on_enter(self, text):
        text = text.strip()
        if not text:
            self._entry.enterText("")
            return

        self._history.append(text)
        if len(self._history) > self.MAX_HISTORY:
            self._history = self._history[-self.MAX_HISTORY:]
        self._history_idx = len(self._history)

        # Execute
        try:
            # Try eval first (expressions return values)
            result = eval(text, {"__builtins__": __builtins__}, self._ns)
            if result is not None:
                self._show_output(f"~ {text}\n  → {result!r}")
            else:
                self._show_output(f"~ {text}")
        except SyntaxError:
            # Fall back to exec (statements like assignments)
            try:
                exec(text, {"__builtins__": __builtins__}, self._ns)
                self._show_output(f"~ {text}  [ok]")
            except Exception as e:
                self._show_output(f"~ {text}\n  ERROR: {e}")
        except Exception as e:
            self._show_output(f"~ {text}\n  ERROR: {e}")

        self._entry.enterText("")

    def _show_output(self, text):
        self._output_lines.append(text)
        if len(self._output_lines) > self.MAX_OUTPUT_LINES:
            self._output_lines = self._output_lines[-self.MAX_OUTPUT_LINES:]
        self._output_text.setText("\n".join(self._output_lines))

    def add_namespace(self, key, obj):
        """Add an object to the REPL namespace at runtime."""
        self._ns[key] = obj
