import moderngl
import numpy as np
from pyrr import Matrix44


class RenderHandler:
    def __init__(self, ctx):
        self.ctx = ctx

        # --- PRODUCTION SETTINGS ---
        self.ctx.enable(moderngl.BLEND)
        self.ctx.enable(moderngl.PROGRAM_POINT_SIZE)
        self.ctx.enable(moderngl.DEPTH_TEST)  # Re-enabled for proper 3D layering

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
                    
                    // Sharp Voxel Size for Retina/M2 Pro (Adjust to 4.0 - 6.0)
                    gl_PointSize = 5.0; 
                }
            """,
            fragment_shader="""
                #version 330
                in vec3 v_color;
                uniform vec3 u_color_mod;
                uniform float u_alpha;
                out vec4 f_color;
                void main() {
                    f_color = vec4(v_color * u_color_mod, u_alpha);
                }
            """,
        )

        self.prog["u_alpha"].value = 1.0
        self.current_vao = None
        self.fade_value = 1.0

    def build_vao(self, data):
        """
        Takes the VoxelStream and binds it using explicit byte-offsets.
        """
        if data is None or len(data) == 0:
            return self.current_vao

        # Ensure the structured array is contiguous before sending to GPU
        raw_bytes = np.ascontiguousarray(data).tobytes()
        vbo = self.ctx.buffer(raw_bytes)

        # Mapping 'p' and 'c' from engine.py to shader 'in_vert' and 'in_color'
        vao = self.ctx.vertex_array(
            self.prog,
            [(vbo, "3f4 3f4", "in_vert", "in_color")],
        )

        self.current_vao = vao
        return vao

    def transition_tick(self, is_recovery, dt):
        target_alpha = 0.6 if is_recovery else 1.0
        if self.fade_value < target_alpha:
            self.fade_value = min(target_alpha, self.fade_value + dt * 2.0)
        elif self.fade_value > target_alpha:
            self.fade_value = max(target_alpha, self.fade_value - dt * 2.0)

        self.prog["u_alpha"].value = self.fade_value

    def render_frame(self, vao, mvp, color_mod):
        if vao is None:
            return

        # Back to the Black Void
        self.ctx.clear(0.0, 0.0, 0.0)

        # Write uniforms
        self.prog["mvp"].write(mvp.astype("f4").tobytes())
        self.prog["u_color_mod"].write(color_mod.astype("f4").tobytes())

        # Render as Points
        vao.render(moderngl.POINTS)


if __name__ == "__main__":
    print("Renderer Handler initialized for Sanctum Terminal [Production Mode]")
