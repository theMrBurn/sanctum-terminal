import moderngl
import numpy as np
import pygame


class RenderHandler:
    def __init__(self, ctx):
        self.ctx = ctx
        self.ctx.enable(moderngl.DEPTH_TEST | moderngl.BLEND)
        self.ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        self.ctx.enable(moderngl.PROGRAM_POINT_SIZE)

        # Point Cloud Shader
        self.prog = self.ctx.program(
            vertex_shader="""
                #version 330
                layout (location = 0) in vec3 in_vert;
                layout (location = 1) in vec3 in_color;
                
                uniform mat4 u_mvp;
                uniform vec3 u_cam_pos;
                uniform float u_time;
                uniform float u_pulse_time;
                uniform vec3 u_pulse_origin;
                uniform float u_intensity;

                out vec3 v_color;
                out float v_alpha;
                out float v_pulse;

                void main() {
                    v_color = in_color;
                    vec3 pos = in_vert;

                    // Sonar Pulse Math
                    float wave_dist = u_pulse_time * 60.0;
                    float d = distance(pos, u_pulse_origin);
                    v_pulse = smoothstep(5.0, 0.0, abs(d - wave_dist));

                    // Dynamic Fog / Atmospheric Stress (u_intensity)
                    float dist_to_cam = distance(pos, u_cam_pos);
                    float fog_edge = 80.0 - (u_intensity * 30.0);
                    v_alpha = clamp(1.0 - (dist_to_cam / fog_edge), 0.0, 1.0);

                    gl_Position = u_mvp * vec4(pos, 1.0);
                    gl_PointSize = 3.0 + (v_pulse * 10.0);
                }
            """,
            fragment_shader="""
                #version 330
                in vec3 v_color;
                in float v_alpha;
                in float v_pulse;
                out vec4 f_color;
                void main() {
                    vec3 pulse_col = vec3(0.0, 1.0, 1.0); 
                    vec3 final_rgb = mix(v_color, pulse_col, v_pulse);
                    f_color = vec4(final_rgb, v_alpha);
                }
            """,
        )
        self.hud_prog = self._build_hud_shader()

    def build_vao(self, data):
        if data is None or len(data) == 0:
            return None
        vbo = self.ctx.buffer(data.tobytes())
        return self.ctx.vertex_array(
            self.prog, [(vbo, "3f4 3f4", "in_vert", "in_color")]
        )

    def render_frame(self, vao, mvp, cam_pos, p_state, hud_tex, hud_vao):
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)

        # Mapping our ObserverSystem dict to Shader Uniforms
        self.prog["u_mvp"].write(mvp.astype("f4").tobytes())
        self.prog["u_cam_pos"].write(np.array(cam_pos, "f4").tobytes())
        self.prog["u_time"].value = p_state["u_time"]
        self.prog["u_intensity"].value = p_state["u_intensity"]
        self.prog["u_pulse_time"].value = p_state["u_pulse_time"]
        self.prog["u_pulse_origin"].write(
            p_state["u_pulse_origin"].astype("f4").tobytes()
        )

        if vao:
            vao.render(moderngl.POINTS)

        if hud_tex and hud_vao:
            self.ctx.disable(moderngl.DEPTH_TEST)
            hud_tex.use(0)
            hud_vao.render(moderngl.TRIANGLE_STRIP)
            self.ctx.enable(moderngl.DEPTH_TEST)

    def _build_hud_shader(self):
        return self.ctx.program(
            vertex_shader="#version 330\nin vec2 in_vert; in vec2 in_texcoord; out vec2 v_tex; void main() { v_tex = vec2(in_texcoord.x, 1.0 - in_texcoord.y); gl_Position = vec4(in_vert, 0.0, 1.0); }",
            fragment_shader="#version 330\nuniform sampler2D t; in vec2 v_tex; out vec4 f; void main() { f = texture(t, v_tex); }",
        )

    def build_hud_vao(self):
        vbo = self.ctx.buffer(
            np.array([-1, 1, 0, 1, -1, -1, 0, 0, 1, 1, 1, 1, 1, -1, 1, 0], "f4")
        )
        return self.ctx.vertex_array(
            self.hud_prog, [(vbo, "2f4 2f4", "in_vert", "in_texcoord")]
        )
