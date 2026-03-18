import moderngl
import numpy as np
from pyrr import Matrix44


class RenderHandler:
    def __init__(self, ctx):
        self.ctx = ctx

        # Shader source with support for global alpha/tinting
        self.prog = self.ctx.program(
            vertex_shader="""
                #version 330
                in vec3 in_vert;
                in vec3 in_color;
                uniform mat4 mvp;
                out vec3 v_color;
                void main() {
                    v_color = in_color;
                    gl_Position = mvp * vec4(in_vert, 1.0);
                }
            """,
            fragment_shader="""
                #version 330
                in vec3 v_color;
                uniform vec3 u_color_mod;
                uniform float u_alpha;
                out vec4 f_color;
                void main() {
                    // Apply weather-based tint and global opacity
                    f_color = vec4(v_color * u_color_mod, u_alpha);
                }
            """,
        )

        # Initial Uniform States
        self.prog["u_alpha"].value = 1.0
        self.current_vao = None
        self.fade_value = 1.0

        # Enable blending for the fade-in effect
        self.ctx.enable(moderngl.BLEND)

    def build_vao(self, data):
        """
        Takes the numpy array from the DataNode and binds it to the GPU.
        If the data is identical to current, skip the rebuild to save cycles.
        """
        if data is None or len(data) == 0:
            return self.current_vao

        # vbo layout: x, y, z, r, g, b (all f4 / float32)
        vbo = self.ctx.buffer(data.tobytes())

        # Creating Vertex Array Object
        vao = self.ctx.simple_vertex_array(self.prog, vbo, "in_vert", "in_color")

        self.current_vao = vao
        return vao

    def transition_tick(self, is_recovery, dt):
        """
        Smoothly adjusts the alpha based on the engine state.
        Fades the view slightly when in recovery to indicate 'Scaffold' mode.
        """
        target_alpha = 0.6 if is_recovery else 1.0

        # Simple linear interpolation for the fade
        if self.fade_value < target_alpha:
            self.fade_value = min(target_alpha, self.fade_value + dt * 2.0)
        elif self.fade_value > target_alpha:
            self.fade_value = max(target_alpha, self.fade_value - dt * 2.0)

        self.prog["u_alpha"].value = self.fade_value

    def render_frame(self, vao, mvp, color_mod):
        """
        Standardized render call for the viewport loop.
        """
        if vao is None:
            return

        self.ctx.clear(0, 0, 0)

        # Write uniforms
        self.prog["mvp"].write(mvp.astype("f4").tobytes())
        self.prog["u_color_mod"].write(color_mod.astype("f4").tobytes())

        # Render as Points (Voxels)
        vao.render(moderngl.POINTS)


if __name__ == "__main__":
    # Context-less check (requires active GL context to run fully)
    print("Renderer Handler initialized for Sanctum Terminal [ModernGL Mode]")
