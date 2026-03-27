import json
from pathlib import Path
from core.systems.interview import InterviewEngine, _detect_commitment_depth, _depth_prompt


class InterviewUI:
    """
    Viewport-driven interview system.
    10 prompts, normalized float output via curves.
    Headless-safe — render_root can be a mock for testing.
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
        self._input_node    = None
        self._input_buffer  = ""

    def start(self):
        self.active         = True
        self.current_prompt = self.engine.next_prompt()
        self._render_prompt()
        return self

    def submit(self, value):
        if not self.active or not self.current_prompt:
            return
        pid = self.current_prompt["id"]

        if pid == "q10":
            depth = _detect_commitment_depth(value)
            if depth == 1:
                self.awaiting_depth = True
                self.depth_prompt   = _depth_prompt(value, self._depth_index)
                self._depth_index  += 1
                self.engine.answer(pid, value)
                self._render_depth_invite()
                return
            else:
                self.engine.answer(pid, value)
        else:
            if self.current_prompt["type"] == "choice":
                if value not in self.current_prompt.get("options", {}):
                    self.skip()
                    return
            self.engine.answer(pid, value)

        self._advance()

    def submit_depth(self, value):
        if not self.awaiting_depth:
            return
        self.awaiting_depth = False
        self.depth_prompt   = None
        if value and value.strip():
            self.engine.answer("q10", value.strip())
        self._advance()

    def skip(self):
        if not self.active or not self.current_prompt:
            return
        self.engine.skip(self.current_prompt["id"])
        self._advance()

    def _advance(self):
        self._clear_text()
        next_p = self.engine.next_prompt()
        if next_p:
            self.current_prompt = next_p
            self._render_prompt()
        else:
            self.current_prompt = None
            self.active         = False
            self._render_complete()

    def handle_char(self, char):
        if not self.active:
            return
        if char in ("\n", "\r"):
            self._handle_enter()
        elif char == "\x08":
            self._input_buffer = self._input_buffer[:-1]
            self._update_input_display()
        else:
            # For choice prompts — single key match
            if (self.current_prompt and
                    self.current_prompt["type"] == "choice" and
                    not self.awaiting_depth):
                options = self.current_prompt.get("options", {})
                # Direct key match
                if char in options:
                    self.submit(char)
                    return
                # First-letter match
                matches = [k for k in options if k.startswith(char)]
                if len(matches) == 1:
                    self.submit(matches[0])
                    return
            self._input_buffer += char
            self._update_input_display()

    def _handle_enter(self):
        value = self._input_buffer.strip()
        self._input_buffer = ""
        self._update_input_display()
        if self.awaiting_depth:
            self.submit_depth(value if value else None)
        elif value:
            self.submit(value)
        else:
            self.skip()

    def _render_prompt(self):
        if not self.current_prompt:
            return
        if self._is_live():
            self._render_panda3d_prompt()

    def _render_depth_invite(self):
        if self._is_live() and self.depth_prompt:
            self._render_panda3d_text(
                f"> {self.depth_prompt}",
                pos=(0, 0.1),
                color=(0.9, 0.9, 0.6, 1)
            )

    def _render_complete(self):
        if self._is_live():
            self._render_panda3d_text(
                "> Open your eyes.",
                pos=(0, 0),
                scale=0.08,
                color=(1, 1, 1, 1)
            )

    def _is_live(self):
        return (self.render_root is not None and
                not isinstance(self.render_root, type) and
                hasattr(self.render_root, "attachNewNode"))

    def _render_panda3d_prompt(self):
        try:
            from direct.gui.OnscreenText import OnscreenText
            from panda3d.core import TextNode

            prompt  = self.current_prompt
            text    = prompt["prompt"]
            options = prompt.get("options", {})
            pid     = prompt["id"]
            total   = len(self.engine.prompts)
            idx     = next((i for i, p in enumerate(self.engine.prompts)
                           if p["id"] == pid), 0) + 1

            self._clear_text()

            # Progress indicator
            prog = OnscreenText(
                text=f"{idx} / {total}",
                pos=(0, 0.75),
                scale=0.04,
                fg=(0.4, 0.4, 0.5, 1),
                align=TextNode.ACenter,
                mayChange=True,
                sort=200,
            )
            self._text_nodes.append(prog)

            # Question
            node = OnscreenText(
                text=f"> {text}",
                pos=(0, 0.35),
                scale=0.065,
                fg=(1, 1, 1, 1),
                shadow=(0, 0, 0, 0.6),
                align=TextNode.ACenter,
                mayChange=True,
                sort=200,
            )
            self._text_nodes.append(node)

            # Options
            if options:
                y = 0.1
                for key, opt in options.items():
                    label    = opt.get("label", key)
                    opt_node = OnscreenText(
                        text=f"[{key}]  {label}",
                        pos=(0, y),
                        scale=0.048,
                        fg=(0.6, 0.6, 0.85, 1),
                        align=TextNode.ACenter,
                        mayChange=True,
                    )
                    self._text_nodes.append(opt_node)
                    y -= 0.08

            # Input line (for open prompts)
            if prompt["type"] == "open":
                hint = OnscreenText(
                    text="(type and press Enter, or Enter to skip)",
                    pos=(0, -0.55),
                    scale=0.038,
                    fg=(0.4, 0.4, 0.5, 1),
                    align=TextNode.ACenter,
                    mayChange=True,
                )
                self._text_nodes.append(hint)

            if prompt["type"] == "open":
                self._update_input_display()

        except Exception:
            pass

    def _render_panda3d_text(self, text, pos=(0, 0),
                              scale=0.055, color=(0.8, 0.8, 1, 1)):
        try:
            from direct.gui.OnscreenText import OnscreenText
            from panda3d.core import TextNode
            node = OnscreenText(
                text=text, pos=pos, scale=scale,
                fg=color, align=TextNode.ACenter, mayChange=True,
            )
            self._text_nodes.append(node)
        except Exception:
            pass

    def _update_input_display(self):
        try:
            from direct.gui.OnscreenText import OnscreenText
            from panda3d.core import TextNode
            if self._input_node:
                try:
                    self._input_node.destroy()
                except Exception:
                    pass
            self._input_node = OnscreenText(
                text=f"> {self._input_buffer}_",
                pos=(0, -0.65),
                scale=0.055,
                fg=(1, 1, 0.5, 1),
                align=TextNode.ACenter,
                mayChange=True,
            )
        except Exception:
            pass

    def _clear_text(self):
        for node in self._text_nodes:
            try:
                node.destroy()
            except Exception:
                pass
        self._text_nodes = []
        if self._input_node:
            try:
                self._input_node.destroy()
            except Exception:
                pass
            self._input_node = None
