import moderngl
import numpy as np
import pygame


class RenderHandler:
    def __init__(self, ctx):
        self.ctx = ctx
        self.ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.ctx.enable(moderngl.PROGRAM_POINT_SIZE)

        # Initialize textures
        self.sprite_tex = self._load_texture("textures/noise.png")
        self.prog = self._build_main_shader()
        self.hud_prog = self._build_hud_shader()

    def _load_texture(self, path):
        try:
            img = pygame.image.load(path).convert_alpha()
            data = pygame.image.tobytes(img, "RGBA")
            tex = self.ctx.texture(img.get_size(), 4, data)
            tex.build_mipmaps()
            return tex
        except:
            return self.ctx.texture((1, 1), 4, b"\xff\xff\xff\xff")

    def _build_main_shader(self):
        return self.ctx.program(
            vertex_shader="""
                #version 330
                in vec3 in_vert;
                in vec3 in_color;
                in float in_time;
                uniform mat4 u_mvp;
                uniform vec3 u_view_offset;
                uniform float u_time;
                uniform float u_velocity;
                out vec3 v_color;
                out float v_alpha;

                void main() {
                    v_color = in_color;
                    float age = u_time - in_time;
                    v_alpha = clamp(age, 0.0, 1.0);

                    float glitch = u_velocity > 12.0 ? sin(u_time * 50.0) * 0.05 : 0.0;
                    vec3 pos = in_vert + vec3(glitch, 0.0, glitch);

                    vec3 relative_pos = pos - u_view_offset;
                    gl_Position = u_mvp * vec4(relative_pos, 1.0);
                    
                    float dist = length(relative_pos);
                    gl_PointSize = clamp(250.0 / (dist * 0.2 + 1.0), 4.0, 80.0);gl_PointSize = clamp(250.0 / (dist * 0.2 + 1.0), 5.0, 60.0);
                    v_alpha *= clamp(1.0 - (dist / 160.0), 0.0, 1.0);
                }
            """,
            fragment_shader="""
                #version 330
                uniform sampler2D u_sprite;
                in vec3 v_color;
                in float v_alpha;
                out vec4 f_color;
                void main() {
                    vec4 tex = texture(u_sprite, gl_PointCoord);
                    if (tex.a < 0.1) discard;
                    f_color = vec4(v_color * tex.rgb, v_alpha * tex.a);
                }
            """,
        )

    def render_frame(
        self, vault, mvp, view_offset, current_time, velocity, hud_tex, hud_vao
    ):
        self.ctx.clear(0.01, 0.01, 0.03, 1.0)
        self.sprite_tex.use(0)
        self.prog["u_sprite"].value = 0
        self.prog["u_mvp"].write(mvp.tobytes())
        self.prog["u_view_offset"].write(np.array(view_offset, dtype="f4").tobytes())
        self.prog["u_time"].value = current_time
        self.prog["u_velocity"].value = velocity

        if vault.vao:
            vault.vao.render(moderngl.POINTS, vertices=vault.current_voxel_count)

        if hud_tex and hud_vao:
            self.ctx.disable(moderngl.DEPTH_TEST)
            hud_tex.use(1)  # Uses unit 1 so it doesn't fight the sprite on unit 0
            self.hud_prog["t"].value = 1
            hud_vao.render(moderngl.TRIANGLE_STRIP)
            self.ctx.enable(moderngl.DEPTH_TEST)

    def _build_hud_shader(self):
        return self.ctx.program(
            vertex_shader="""
                #version 330
                in vec2 in_vert;
                in vec2 in_texcoord;
                out vec2 v_tex;
                void main() {
                    v_tex = vec2(in_texcoord.x, 1.0 - in_texcoord.y);
                    gl_Position = vec4(in_vert, 0.0, 1.0);
                }
            """,
            fragment_shader="""
                #version 330
                uniform sampler2D t;
                in vec2 v_tex;
                out vec4 f;
                void main() {
                    f = texture(t, v_tex);
                }
            """,
        )

    def build_hud_vao(self):
        vbo = self.ctx.buffer(
            np.array([-1, 1, 0, 1, -1, -1, 0, 0, 1, 1, 1, 1, 1, -1, 1, 0], "f4")
        )
        return self.ctx.vertex_array(
            self.hud_prog, [(vbo, "2f4 2f4", "in_vert", "in_texcoord")]
        )
