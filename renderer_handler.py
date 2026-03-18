import moderngl
import numpy as np


class RenderHandler:
    def __init__(self, ctx):
        self.ctx = ctx
        self.ctx.enable(moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.ctx.enable(moderngl.PROGRAM_POINT_SIZE)
        self.ctx.enable(moderngl.DEPTH_TEST)

        # 3.3.1: VOXEL SHADER (Active Perception)
        self.prog = self.ctx.program(
            vertex_shader="""
                #version 330
                in vec3 in_vert;
                in vec3 in_color;
                
                uniform mat4 mvp;
                uniform float u_time;
                uniform float u_intensity;
                uniform float u_visibility;
                uniform vec3 u_cam_pos;
                uniform float u_pulse_time;
                uniform vec3 u_pulse_origin;

                out vec3 v_color;
                out float v_alpha;
                out float v_pulse;

                void main() {
                    v_color = in_color;
                    vec3 pos = in_vert;

                    // 1. THERMAL SHIMMER
                    float shimmer = sin(u_time * 3.5 + pos.x) * cos(u_time * 2.8 + pos.z);
                    pos.y += shimmer * u_intensity * 0.25;

                    // 2. SONAR PULSE (Expanding wave at 50m/s)
                    float wave_radius = u_pulse_time * 50.0;
                    float dist_to_origin = distance(pos, u_pulse_origin);
                    // Gaussian peak for the wave ring
                    float pulse_hit = exp(-pow((dist_to_origin - wave_radius) / 2.0, 2.0));
                    v_pulse = pulse_hit;

                    // 3. DEPTH FADE
                    float dist_to_cam = distance(pos, u_cam_pos);
                    v_alpha = 1.0 - smoothstep(u_visibility * 0.6, u_visibility, dist_to_cam);

                    gl_Position = mvp * vec4(pos, 1.0);
                    gl_PointSize = 4.0 + (v_pulse * 10.0); 
                }
            """,
            fragment_shader="""
                #version 330
                in vec3 v_color;
                in float v_alpha;
                in float v_pulse;
                uniform vec3 u_color_mod;
                uniform float u_alpha_base; 
                out vec4 f_color;
                void main() {
                    // Mix base color with a high-intensity Cyan for the sonar ping
                    vec3 pulse_color = mix(v_color * u_color_mod, vec3(0.0, 1.0, 1.0), v_pulse);
                    f_color = vec4(pulse_color, v_alpha * u_alpha_base);
                }
            """,
        )

        self.hud_prog = self.ctx.program(
            vertex_shader="""
                #version 330
                in vec2 in_vert; in vec2 in_texcoord;
                out vec2 v_texcoord;
                void main() {
                    v_texcoord = vec2(in_texcoord.x, 1.0 - in_texcoord.y);
                    gl_Position = vec4(in_vert, 0.0, 1.0);
                }
            """,
            fragment_shader="""
                #version 330
                uniform sampler2D u_texture;
                in vec2 v_texcoord; out vec4 f_color;
                void main() { f_color = texture(u_texture, v_texcoord); }
            """,
        )

        self.prog["u_alpha_base"].value = 1.0
        self.current_vao = None

    def build_vao(self, data):
        if data is None or len(data) == 0:
            return self.current_vao
        raw_bytes = np.ascontiguousarray(data).tobytes()
        vbo = self.ctx.buffer(raw_bytes)
        return self.ctx.vertex_array(
            self.prog, [(vbo, "3f4 3f4", "in_vert", "in_color")]
        )

    def build_hud_vao(self):
        vertices = np.array(
            [
                -1.0,
                1.0,
                0.0,
                1.0,
                -1.0,
                -1.0,
                0.0,
                0.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
                -1.0,
                1.0,
                0.0,
            ],
            dtype="f4",
        )
        vbo = self.ctx.buffer(vertices)
        return self.ctx.vertex_array(
            self.hud_prog, [(vbo, "2f4 2f4", "in_vert", "in_texcoord")]
        )

    def render_frame(self, vao, mvp, cam_pos, p_state, hud_texture=None, hud_vao=None):
        self.ctx.clear(0.0, 0.0, 0.0)
        if vao:
            self.ctx.enable(moderngl.DEPTH_TEST)
            self.prog["mvp"].write(mvp.astype("f4").tobytes())
            self.prog["u_time"].value = p_state["u_time"]
            self.prog["u_intensity"].value = p_state["u_intensity"]
            self.prog["u_visibility"].value = p_state["u_visibility"]
            self.prog["u_cam_pos"].write(cam_pos.astype("f4").tobytes())
            self.prog["u_pulse_time"].value = p_state["u_pulse_time"]
            self.prog["u_pulse_origin"].write(
                p_state["u_pulse_origin"].astype("f4").tobytes()
            )
            self.prog["u_color_mod"].write(
                np.array([1.0, 1.0, 1.0], dtype="f4").tobytes()
            )
            vao.render(moderngl.POINTS)
        if hud_texture and hud_vao:
            self.ctx.disable(moderngl.DEPTH_TEST)
            hud_texture.use(0)
            hud_vao.render(moderngl.TRIANGLE_STRIP)
