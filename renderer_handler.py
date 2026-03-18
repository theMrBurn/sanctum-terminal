import moderngl
import numpy as np


class RenderHandler:
    def __init__(self, ctx):
        self.ctx = ctx
        self.ctx.enable(moderngl.BLEND)
        self.ctx.enable(moderngl.PROGRAM_POINT_SIZE)
        self.ctx.enable(moderngl.DEPTH_TEST)

        # 3.3.1: VOXEL SHADER (3D)
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
                    gl_PointSize = 4.0; 
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

        # 3.3.2: HUD SHADER (2D Overlay)
        # THE FIX: We manually invert texcoords here so it works regardless of Pygame's flip state.
        self.hud_prog = self.ctx.program(
            vertex_shader="""
                #version 330
                in vec2 in_vert;
                in vec2 in_texcoord;
                out vec2 v_texcoord;
                void main() {
                    v_texcoord = vec2(in_texcoord.x, 1.0 - in_texcoord.y);
                    gl_Position = vec4(in_vert, 0.0, 1.0);
                }
            """,
            fragment_shader="""
                #version 330
                uniform sampler2D u_texture;
                in vec2 v_texcoord;
                out vec4 f_color;
                void main() {
                    f_color = texture(u_texture, v_texcoord);
                }
            """,
        )

        self.prog["u_alpha"].value = 1.0
        self.current_vao = None
        self.fade_value = 1.0

    def build_vao(self, data):
        if data is None or len(data) == 0:
            return self.current_vao
        raw_bytes = np.ascontiguousarray(data).tobytes()
        vbo = self.ctx.buffer(raw_bytes)
        vao = self.ctx.vertex_array(
            self.prog, [(vbo, "3f4 3f4", "in_vert", "in_color")]
        )
        self.current_vao = vao
        return vao

    def build_hud_vao(self):
        """Standard Quad. Inversion logic is moved to the Shader."""
        vertices = np.array(
            [
                -1.0,
                1.0,
                0.0,
                1.0,  # Top Left
                -1.0,
                -1.0,
                0.0,
                0.0,  # Bottom Left
                1.0,
                1.0,
                1.0,
                1.0,  # Top Right
                1.0,
                -1.0,
                1.0,
                0.0,  # Bottom Right
            ],
            dtype="f4",
        )
        vbo = self.ctx.buffer(vertices)
        return self.ctx.vertex_array(
            self.hud_prog, [(vbo, "2f4 2f4", "in_vert", "in_texcoord")]
        )

    def transition_tick(self, is_recovery, dt):
        target_alpha = 0.6 if is_recovery else 1.0
        self.fade_value += (target_alpha - self.fade_value) * dt * 2.0
        self.prog["u_alpha"].value = self.fade_value

    def render_frame(self, vao, mvp, color_mod, hud_texture=None, hud_vao=None):
        self.ctx.clear(0.0, 0.0, 0.0)
        if vao:
            self.ctx.enable(moderngl.DEPTH_TEST)
            self.prog["mvp"].write(mvp.astype("f4").tobytes())
            self.prog["u_color_mod"].write(color_mod.astype("f4").tobytes())
            vao.render(moderngl.POINTS)
        if hud_texture and hud_vao:
            self.ctx.disable(moderngl.DEPTH_TEST)
            hud_texture.use(0)
            hud_vao.render(moderngl.TRIANGLE_STRIP)
