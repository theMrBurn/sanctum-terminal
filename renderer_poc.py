"""
renderer_poc.py

wgpu proof-of-concept: 500 instanced cubes via Metal.
Uses rendercanvas for window management, raw wgpu for rendering.
Measures frame time to prove the manifest architecture.

Usage:
    python renderer_poc.py
"""

import time
import math
import struct
import random
import array

import wgpu
from rendercanvas.auto import RenderCanvas, loop


SHADER_CODE = """
struct Camera {
    view_proj: mat4x4<f32>,
    fog_color: vec4<f32>,
    fog_params: vec4<f32>,
    ambient: vec4<f32>,
    cam_pos: vec4<f32>,
};

@group(0) @binding(0) var<uniform> camera: Camera;

struct Instance {
    pos_x: f32,
    pos_y: f32,
    pos_z: f32,
    heading: f32,
    scale: f32,
    color_r: f32,
    color_g: f32,
    color_b: f32,
};

@group(0) @binding(1) var<storage, read> instances: array<Instance>;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) color: vec3<f32>,
    @location(1) fog_factor: f32,
};

fn cube_vertex(idx: u32) -> vec3<f32> {
    let corners = array<vec3<f32>, 8>(
        vec3<f32>(-0.5, -0.5,  0.0),
        vec3<f32>( 0.5, -0.5,  0.0),
        vec3<f32>( 0.5,  0.5,  0.0),
        vec3<f32>(-0.5,  0.5,  0.0),
        vec3<f32>(-0.5, -0.5,  1.0),
        vec3<f32>( 0.5, -0.5,  1.0),
        vec3<f32>( 0.5,  0.5,  1.0),
        vec3<f32>(-0.5,  0.5,  1.0),
    );
    let indices = array<u32, 36>(
        0u,2u,1u, 0u,3u,2u,
        1u,6u,5u, 1u,2u,6u,
        5u,7u,4u, 5u,6u,7u,
        4u,3u,0u, 4u,7u,3u,
        3u,6u,2u, 3u,7u,6u,
        4u,1u,5u, 4u,0u,1u,
    );
    return corners[indices[idx]];
}

fn cube_normal(idx: u32) -> vec3<f32> {
    let face = idx / 6u;
    let normals = array<vec3<f32>, 6>(
        vec3<f32>( 0.0,  0.0, -1.0),
        vec3<f32>( 1.0,  0.0,  0.0),
        vec3<f32>( 0.0,  0.0,  1.0),
        vec3<f32>(-1.0,  0.0,  0.0),
        vec3<f32>( 0.0,  1.0,  0.0),
        vec3<f32>( 0.0, -1.0,  0.0),
    );
    return normals[face];
}

@vertex
fn vs_main(@builtin(vertex_index) vi: u32,
           @builtin(instance_index) ii: u32) -> VertexOutput {
    let inst = instances[ii];
    let local = cube_vertex(vi) * inst.scale;

    let angle = inst.heading * 3.14159265 / 180.0;
    let c = cos(angle);
    let s = sin(angle);
    let rotated = vec3<f32>(
        local.x * c - local.y * s,
        local.x * s + local.y * c,
        local.z,
    );

    let world = rotated + vec3<f32>(inst.pos_x, inst.pos_y, inst.pos_z);

    let dx = inst.pos_x - camera.cam_pos.x;
    let dy = inst.pos_y - camera.cam_pos.y;
    let dist = sqrt(dx * dx + dy * dy);
    let fog = clamp((dist - camera.fog_params.x) / (camera.fog_params.y - camera.fog_params.x), 0.0, 1.0);

    let normal = cube_normal(vi);
    let light_dir = normalize(vec3<f32>(0.3, 0.5, 1.0));
    let ndl = max(dot(normal, light_dir), 0.0);
    let lit = camera.ambient.rgb + vec3<f32>(ndl * 0.4);

    var out: VertexOutput;
    out.position = camera.view_proj * vec4<f32>(world, 1.0);
    out.color = vec3<f32>(inst.color_r, inst.color_g, inst.color_b) * lit;
    out.fog_factor = fog;
    return out;
}

@fragment
fn fs_main(in: VertexOutput) -> @location(0) vec4<f32> {
    let color = mix(in.color, camera.fog_color.rgb, in.fog_factor);
    return vec4<f32>(color, 1.0);
}
"""


def make_perspective(fov, aspect, near, far):
    f = 1.0 / math.tan(math.radians(fov) / 2.0)
    nf = 1.0 / (near - far)
    return [
        f / aspect, 0, 0, 0,
        0, f, 0, 0,
        0, 0, (far + near) * nf, -1,
        0, 0, 2 * far * near * nf, 0,
    ]


def make_view(cx, cy, cz, h, p):
    hr = math.radians(h)
    pr = math.radians(p)
    fx = -math.sin(hr) * math.cos(pr)
    fy = math.cos(hr) * math.cos(pr)
    fz = math.sin(pr)
    rx = math.cos(hr)
    ry = math.sin(hr)
    rz = 0.0
    ux = ry * fz - rz * fy
    uy = rz * fx - rx * fz
    uz = rx * fy - ry * fx
    tx = -(rx*cx + ry*cy + rz*cz)
    ty = -(ux*cx + uy*cy + uz*cz)
    tz = -(-fx*cx + -fy*cy + -fz*cz)
    return [rx, ux, -fx, 0, ry, uy, -fy, 0, rz, uz, -fz, 0, tx, ty, tz, 1]


def mat4_mul(a, b):
    r = [0.0] * 16
    for row in range(4):
        for col in range(4):
            s = 0.0
            for k in range(4):
                s += a[k * 4 + row] * b[col * 4 + k]
            r[col * 4 + row] = s
    return r


def main():
    NUM_INSTANCES = 500

    # Generate instances
    rng = random.Random(42)
    inst_floats = []
    for _ in range(NUM_INSTANCES):
        x = rng.uniform(-80, 80)
        y = rng.uniform(-80, 80)
        z = 0.0
        heading = rng.uniform(0, 360)
        kind = rng.choice(["col", "bld", "cry", "fun", "grs"])
        scale = {"col": 3.0, "bld": 2.0, "cry": 1.5, "fun": 1.5, "grs": 0.4}[kind]
        scale *= rng.uniform(0.7, 1.3)
        colors = {
            "col": (0.45, 0.35, 0.25), "bld": (0.35, 0.65, 0.25),
            "cry": (0.6, 0.7, 0.9), "fun": (0.3, 0.55, 0.2),
            "grs": (0.2, 0.5, 0.15),
        }
        r, g, b = colors[kind]
        inst_floats.extend([x, y, z, heading, scale, r, g, b])

    inst_bytes = struct.pack(f"{len(inst_floats)}f", *inst_floats)

    # State
    cam = {"x": 0.0, "y": -30.0, "z": 2.5, "h": 0.0, "p": -10.0}
    frame_times = []
    keys_pressed = set()
    last_mouse = [None, None]

    canvas = RenderCanvas(size=(960, 540), title="Sanctum — wgpu PoC (500 instances)")
    adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
    device = adapter.request_device_sync()
    context = canvas.get_context("wgpu")
    fmt = context.get_preferred_format(adapter)
    context.configure(device=device, format=fmt, alpha_mode="opaque")

    shader = device.create_shader_module(code=SHADER_CODE)

    cam_buf = device.create_buffer(size=128, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)
    inst_buf = device.create_buffer_with_data(data=inst_bytes, usage=wgpu.BufferUsage.STORAGE)

    # Depth buffer created dynamically per frame to match retina scaling
    depth_view = [None]
    depth_size = [0, 0]

    bgl = device.create_bind_group_layout(entries=[
        {"binding": 0, "visibility": wgpu.ShaderStage.VERTEX | wgpu.ShaderStage.FRAGMENT,
         "buffer": {"type": wgpu.BufferBindingType.uniform}},
        {"binding": 1, "visibility": wgpu.ShaderStage.VERTEX,
         "buffer": {"type": wgpu.BufferBindingType.read_only_storage}},
    ])

    bg = device.create_bind_group(layout=bgl, entries=[
        {"binding": 0, "resource": {"buffer": cam_buf, "size": 128}},
        {"binding": 1, "resource": {"buffer": inst_buf, "size": len(inst_bytes)}},
    ])

    pipeline = device.create_render_pipeline(
        layout=device.create_pipeline_layout(bind_group_layouts=[bgl]),
        vertex={"module": shader, "entry_point": "vs_main"},
        fragment={"module": shader, "entry_point": "fs_main",
                  "targets": [{"format": fmt}]},
        primitive={"topology": wgpu.PrimitiveTopology.triangle_list,
                   "cull_mode": wgpu.CullMode.back},
        depth_stencil={"format": wgpu.TextureFormat.depth24plus,
                       "depth_write_enabled": True,
                       "depth_compare": wgpu.CompareFunction.less},
    )

    last_time = [time.perf_counter()]
    frame_count = [0]

    @canvas.add_event_handler("key_down")
    def on_key_down(event):
        keys_pressed.add(event.get("key", ""))

    @canvas.add_event_handler("key_up")
    def on_key_up(event):
        keys_pressed.discard(event.get("key", ""))

    @canvas.add_event_handler("pointer_move")
    def on_mouse(event):
        x, y = event.get("x", 0), event.get("y", 0)
        if last_mouse[0] is not None:
            dx = x - last_mouse[0]
            dy = y - last_mouse[1]
            cam["h"] += dx * 0.3
            cam["p"] = max(-60, min(60, cam["p"] - dy * 0.3))
        last_mouse[0], last_mouse[1] = x, y

    def draw_frame():
        now = time.perf_counter()
        dt = now - last_time[0]
        last_time[0] = now
        frame_ms = dt * 1000
        frame_times.append(frame_ms)
        if len(frame_times) > 120:
            frame_times.pop(0)
        frame_count[0] += 1

        # Movement
        speed = 8.0 * dt
        fwd_x = -math.sin(math.radians(cam["h"]))
        fwd_y = math.cos(math.radians(cam["h"]))
        if "w" in keys_pressed or "ArrowUp" in keys_pressed:
            cam["x"] += fwd_x * speed; cam["y"] += fwd_y * speed
        if "s" in keys_pressed or "ArrowDown" in keys_pressed:
            cam["x"] -= fwd_x * speed; cam["y"] -= fwd_y * speed
        if "a" in keys_pressed or "ArrowLeft" in keys_pressed:
            cam["x"] -= fwd_y * speed; cam["y"] += fwd_x * speed
        if "d" in keys_pressed or "ArrowRight" in keys_pressed:
            cam["x"] += fwd_y * speed; cam["y"] -= fwd_x * speed
        if "Escape" in keys_pressed:
            canvas.close()
            return

        # Camera uniform
        proj = make_perspective(65, 960/540, 0.5, 80.0)
        view = make_view(cam["x"], cam["y"], cam["z"], cam["h"], cam["p"])
        vp = mat4_mul(proj, view)

        data = struct.pack("16f", *vp)                          # view_proj
        data += struct.pack("4f", 0.22, 0.24, 0.28, 1.0)       # fog_color
        data += struct.pack("4f", 15.0, 55.0, 0.0, 0.0)        # fog_params
        data += struct.pack("4f", 0.72, 0.65, 0.58, 1.0)       # ambient
        data += struct.pack("4f", cam["x"], cam["y"], cam["z"], 0.0)  # cam_pos

        device.queue.write_buffer(cam_buf, 0, data)

        cur_tex = context.get_current_texture()
        tex_view = cur_tex.create_view()
        w, h = cur_tex.size[0], cur_tex.size[1]
        if w != depth_size[0] or h != depth_size[1]:
            dt = device.create_texture(
                size=(w, h, 1), format=wgpu.TextureFormat.depth24plus,
                usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
            depth_view[0] = dt.create_view()
            depth_size[0], depth_size[1] = w, h

        enc = device.create_command_encoder()
        rp = enc.begin_render_pass(
            color_attachments=[{
                "view": tex_view, "resolve_target": None,
                "load_op": wgpu.LoadOp.clear, "store_op": wgpu.StoreOp.store,
                "clear_value": (0.22, 0.24, 0.28, 1.0),
            }],
            depth_stencil_attachment={
                "view": depth_view[0],
                "depth_load_op": wgpu.LoadOp.clear,
                "depth_store_op": wgpu.StoreOp.store,
                "depth_clear_value": 1.0,
            },
        )
        rp.set_pipeline(pipeline)
        rp.set_bind_group(0, bg)
        rp.draw(36, NUM_INSTANCES)
        rp.end()
        device.queue.submit([enc.finish()])

        # Perf report — measure GPU submit time separately
        gpu_end = time.perf_counter()
        gpu_ms = (gpu_end - now) * 1000  # time from start of draw_frame to after submit
        if frame_count[0] % 60 == 0 and len(frame_times) > 10:
            avg = sum(frame_times) / len(frame_times)
            fps = 1000.0 / avg if avg > 0 else 0
            print(f"  avg={avg:.1f}ms  fps={fps:.0f}  gpu={gpu_ms:.1f}ms  instances={NUM_INSTANCES}", flush=True)

        # Request next frame (continuous rendering)
        canvas.request_draw(draw_frame)

    import sys
    print(f"wgpu Metal renderer ready — {NUM_INSTANCES} instances", flush=True)
    print("WASD=move, mouse=look, ESC=quit", flush=True)
    sys.stdout.flush()
    canvas.request_draw(draw_frame)
    loop.run()

    if frame_times:
        avg = sum(frame_times) / len(frame_times)
        print(f"\nFinal: avg={avg:.1f}ms  fps={1000/avg:.0f}  instances={NUM_INSTANCES}")


if __name__ == "__main__":
    main()
