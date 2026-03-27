import json
from pathlib import Path
from core.systems.interview import InterviewEngine, _detect_commitment_depth, _depth_prompt


class InterviewUI:
    """
    Viewport-driven interview system.
    Manages prompt flow, depth detection, and completion callback.
    Headless-safe — render_root can be a mock for testing.
    In live mode, renders OnscreenText directly on the Panda3D viewport.
    """

    def __init__(self, render_root=None, on_complete=None):
        self.render_root    = render_root
        self.on_complete    = on_complete
        self.engine         = InterviewEngine()
        self.engine.on_complete = on_complete
        self.active         = False
        self.current_prompt = None
        self.awaiting_depth = False
        self.depth_prompt   = None
        self._depth_index   = 0
        self._text_nodes    = []
        self._input_buffer  = ""

    # ── Flow ──────────────────────────────────────────────────────────────────

    def start(self):
        """Begin the interview — show first prompt."""
        self.active         = True
        self.current_prompt = self.engine.next_prompt()
        self._render_prompt()
        return self

    def submit(self, value):
        """
        Submit an answer for the current prompt.
        Detects low commitment on Q7 and triggers depth invitation.
        """
        if not self.active or not self.current_prompt:
            return

        pid = self.current_prompt["id"]

        # Q7 depth detection
        if pid == "q7":
            depth = _detect_commitment_depth(value)
            if depth == 1:
                self.awaiting_depth = True
                self.depth_prompt   = _depth_prompt(value, self._depth_index)
                self._depth_index  += 1
                self._render_depth_invite()
                # Store the original answer but wait for depth response
                self.engine.answer(pid, value)
                return
            else:
                self.engine.answer(pid, value)
        else:
            # Validate choice answers — skip if invalid
            if self.current_prompt["type"] == "choice":
                if value not in self.current_prompt.get("options", {}):
                    self.skip()
                    return
            self.engine.answer(pid, value)

        self._advance()

    def submit_depth(self, value):
        """
        Submit a depth response after a low-commitment Q7 answer.
        Upgrades the torch if deeper answer given.
        """
        if not self.awaiting_depth:
            return

        self.awaiting_depth = False
        self.depth_prompt   = None

        # Re-answer Q7 with the deeper response
        if value and value.strip():
            self.engine.answer("q7", value.strip())
        # else keep the original answer already stored

        self._advance()

    def skip(self):
        """Skip the current prompt."""
        if not self.active or not self.current_prompt:
            return
        self.engine.skip(self.current_prompt["id"])
        self._advance()

    def _advance(self):
        """Move to the next prompt or complete."""
        self._clear_text()
        next_p = self.engine.next_prompt()
        if next_p:
            self.current_prompt = next_p
            self._render_prompt()
        else:
            self.current_prompt = None
            self.active         = False
            self._render_complete()

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _render_prompt(self):
        """Render current prompt to viewport or stdout (headless)."""
        if not self.current_prompt:
            return
        if self.render_root and hasattr(self.render_root, 'attachNewNode'):
            self._render_panda3d_prompt()
        # Headless — no output needed, tests drive via submit/skip

    def _render_depth_invite(self):
        """Render depth invitation to viewport or stdout."""
        if self.render_root and hasattr(self.render_root, 'attachNewNode'):
            self._render_panda3d_text(self.depth_prompt, pos=(0, 0.3))

    def _render_complete(self):
        """Render completion state."""
        if self.render_root and hasattr(self.render_root, 'attachNewNode'):
            result = self.engine.resolve()
            self._render_panda3d_text(
                f"> Open your eyes.",
                pos=(0, 0),
                scale=0.08,
                color=(1, 1, 1, 1)
            )

    def _render_panda3d_prompt(self):
        """Render prompt using Panda3D OnscreenText."""
        try:
            from direct.gui.OnscreenText import OnscreenText
            from panda3d.core import TextNode

            prompt  = self.current_prompt
            text    = prompt["prompt"]
            options = prompt.get("options", {})

            # Clear previous
            self._clear_text()

            # Main question
            node = OnscreenText(
                text=f"> {text}",
                pos=(0, 0.2),
                scale=0.06,
                fg=(1, 1, 1, 1),
                shadow=(0, 0, 0, 0.5),
                align=TextNode.ACenter,
                mayChange=True,
            )
            self._text_nodes.append(node)

            # Options
            if options:
                y = 0.0
                for key, opt in options.items():
                    label = opt.get("label", key)
                    opt_node = OnscreenText(
                        text=f"[{key}] {label}",
                        pos=(0, y),
                        scale=0.045,
                        fg=(0.7, 0.7, 0.9, 1),
                        align=TextNode.ACenter,
                        mayChange=True,
                    )
                    self._text_nodes.append(opt_node)
                    y -= 0.07

        except Exception:
            pass  # Headless — silent

    def _render_panda3d_text(self, text, pos=(0, 0), scale=0.055, color=(0.8, 0.8, 1, 1)):
        """Generic Panda3D text render."""
        try:
            from direct.gui.OnscreenText import OnscreenText
            from panda3d.core import TextNode
            node = OnscreenText(
                text=text,
                pos=pos,
                scale=scale,
                fg=color,
                align=TextNode.ACenter,
                mayChange=True,
            )
            self._text_nodes.append(node)
        except Exception:
            pass

    def _clear_text(self):
        """Remove all rendered text nodes."""
        for node in self._text_nodes:
            try:
                node.destroy()
            except Exception:
                pass
        self._text_nodes = []

    # ── Input (for Panda3D key binding) ───────────────────────────────────────

    def handle_char(self, char):
        """
        Called by Panda3D key events during interview.
        Accumulates typed characters, submits on Enter.
        """
        if not self.active:
            return
        if char == "\n" or char == "\r":
            self._handle_enter()
        elif char == "\x08":  # backspace
            self._input_buffer = self._input_buffer[:-1]
            self._update_input_display()
        else:
            self._input_buffer += char
            self._update_input_display()

    def _handle_enter(self):
        """Process Enter key — submit or skip."""
        value = self._input_buffer.strip()
        self._input_buffer = ""
        self._update_input_display()

        if self.awaiting_depth:
            self.submit_depth(value if value else None)
        elif value:
            self.submit(value)
        else:
            self.skip()

    def _update_input_display(self):
        """Update the input line display."""
        pass  # Implement with OnscreenText in live mode
