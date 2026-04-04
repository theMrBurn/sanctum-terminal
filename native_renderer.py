"""
native_renderer.py

Reusable wgpu/Metal renderer that consumes frame manifests.

Manifest format:
    {
        "camera": (x, y, z, h, p),
        "fog": {"near": 15.0, "far": 55.0, "color": (r, g, b)},
        "ambient": (r, g, b),
        "entities": [(kind_id, x, y, z, heading, sx, sy, sz, r, g, b), ...],
    }

Loads real mesh geometry from data/mesh_library.bin (extracted from Panda3D builders).
Falls back to a cube for any kind not in the library.
"""

import os
import time
import math
import struct

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
    scale_x: f32,
    scale_y: f32,
    scale_z: f32,
    color_r: f32,
    color_g: f32,
    color_b: f32,
    emissive: f32,
    _pad0: f32,
};

@group(0) @binding(1) var<storage, read> instances: array<Instance>;

struct VertexInput {
    @location(0) position: vec3<f32>,
    @location(1) normal: vec3<f32>,
    @location(2) color: vec3<f32>,
};

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) color: vec3<f32>,
    @location(1) fog_factor: f32,
};

@vertex
fn vs_main(vert: VertexInput,
           @builtin(instance_index) ii: u32) -> VertexOutput {
    let inst = instances[ii];

    // Scale mesh vertex by instance scale
    let scaled = vec3<f32>(
        vert.position.x * inst.scale_x,
        vert.position.y * inst.scale_y,
        vert.position.z * inst.scale_z,
    );

    // Rotate around Z by heading
    let angle = inst.heading * 3.14159265 / 180.0;
    let c = cos(angle);
    let s = sin(angle);
    let rotated = vec3<f32>(
        scaled.x * c - scaled.y * s,
        scaled.x * s + scaled.y * c,
        scaled.z,
    );

    let world = rotated + vec3<f32>(inst.pos_x, inst.pos_y, inst.pos_z);

    // Fog based on XY distance from camera
    let dx = inst.pos_x - camera.cam_pos.x;
    let dy = inst.pos_y - camera.cam_pos.y;
    let dist = sqrt(dx * dx + dy * dy);
    let fog = clamp((dist - camera.fog_params.x) / (camera.fog_params.y - camera.fog_params.x), 0.0, 1.0);

    // Lighting: mesh normal (flat shading) + directional
    let light_dir = normalize(vec3<f32>(0.3, 0.5, 1.0));
    let ndl = max(dot(vert.normal, light_dir), 0.0);
    let lit = camera.ambient.rgb * (0.6 + ndl * 0.4);

    // Mesh vertex color modulated by instance color tint
    let base_color = vert.color * vec3<f32>(inst.color_r, inst.color_g, inst.color_b);

    // Emissive: 0.0 = normal ambient-lit, 1.0 = full self-illumination
    let final_color = mix(base_color * lit, base_color * 2.0, inst.emissive);

    // Emissive objects resist fog — they're light sources, visible through mist
    let glow_fog = fog * (1.0 - inst.emissive * 0.7);

    var out: VertexOutput;
    out.position = camera.view_proj * vec4<f32>(world, 1.0);
    out.color = final_color;
    out.fog_factor = glow_fog;
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


# -- Mesh library loader -------------------------------------------------------

def _make_cube_mesh():
    """Fallback cube mesh: 36 vertices (12 tris), unit size, base at z=0."""
    corners = [
        (-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0),
        (-0.5, -0.5, 1.0), (0.5, -0.5, 1.0), (0.5, 0.5, 1.0), (-0.5, 0.5, 1.0),
    ]
    indices = [
        0,2,1, 0,3,2, 1,6,5, 1,2,6,
        5,7,4, 5,6,7, 4,3,0, 4,7,3,
        3,6,2, 3,7,6, 4,1,5, 4,0,1,
    ]
    face_normals = [
        (0,0,-1), (0,0,-1), (1,0,0), (1,0,0),
        (0,0,1), (0,0,1), (-1,0,0), (-1,0,0),
        (0,1,0), (0,1,0), (0,-1,0), (0,-1,0),
    ]
    verts = []
    for tri_idx in range(12):
        nx, ny, nz = face_normals[tri_idx]
        for vi in range(3):
            idx = indices[tri_idx * 3 + vi]
            px, py, pz = corners[idx]
            verts.append((px, py, pz, nx, ny, nz, 0.5, 0.5, 0.5))
    return verts, {"width": 1.0, "depth": 1.0, "height": 1.0}


def load_mesh_library(path="data/mesh_library.bin"):
    """Load binary mesh library. Returns dict of kind_name -> (vertices, bounds)."""
    meshes = {}

    if not os.path.exists(path):
        print(f"  No mesh library at {path} — using cubes", flush=True)
        return meshes

    with open(path, "rb") as f:
        magic = f.read(4)
        if magic != b"MESH":
            print(f"  Invalid mesh library magic: {magic}", flush=True)
            return meshes

        version, num_kinds = struct.unpack("<II", f.read(8))

        for _ in range(num_kinds):
            name_bytes = f.read(32)
            kind_name = name_bytes.split(b"\x00")[0].decode("ascii")
            num_verts = struct.unpack("<I", f.read(4))[0]
            w, d, h = struct.unpack("<fff", f.read(12))

            vertices = []
            for _ in range(num_verts):
                v = struct.unpack("<9f", f.read(36))
                vertices.append(v)

            meshes[kind_name] = (vertices, {"width": w, "depth": d, "height": h})

    print(f"  Loaded {len(meshes)} meshes from {path}", flush=True)
    return meshes


# -- Ground plane mesh ---------------------------------------------------------

def _make_ground_mesh():
    """Large flat quad, base color baked in."""
    # Two triangles forming a quad at z=0
    verts = [
        (-0.5, -0.5, 0.0, 0.0, 0.0, 1.0, 0.5, 0.5, 0.5),
        ( 0.5, -0.5, 0.0, 0.0, 0.0, 1.0, 0.5, 0.5, 0.5),
        ( 0.5,  0.5, 0.0, 0.0, 0.0, 1.0, 0.5, 0.5, 0.5),
        (-0.5, -0.5, 0.0, 0.0, 0.0, 1.0, 0.5, 0.5, 0.5),
        ( 0.5,  0.5, 0.0, 0.0, 0.0, 1.0, 0.5, 0.5, 0.5),
        (-0.5,  0.5, 0.0, 0.0, 0.0, 1.0, 0.5, 0.5, 0.5),
    ]
    return verts, {"width": 1.0, "depth": 1.0, "height": 0.0}


# Ground instance: (kind_id, x, y, z, heading, sx, sy, sz, r, g, b, emissive)
# kind_id = -1 signals ground plane
GROUND_INSTANCE = (-1, 0.0, 0.0, 0.0, 0.0, 400.0, 400.0, 1.0, 0.08, 0.06, 0.05, 0.0)


class NativeRenderer:
    """wgpu/Metal renderer that draws per-kind meshes from manifests."""

    MAX_INSTANCES = 8192

    def __init__(self, title="Sanctum — wgpu", width=960, height=540,
                 kind_names=None):
        """
        kind_names: ordered list of kind names matching KIND_IDS in the bridge.
        """
        self._width = width
        self._height = height
        self._title = title
        self._frame_times = []
        self._frame_count = 0
        self._kind_names = kind_names or []

        self.cam = {"x": 0.0, "y": -30.0, "z": 2.5, "h": 0.0, "p": -10.0}
        self._keys_pressed = set()
        self._last_mouse = [None, None]

    def run(self, frame_callback):
        """Start the render loop."""
        # Load mesh library
        mesh_lib = load_mesh_library()
        cube_mesh, _ = _make_cube_mesh()
        ground_mesh, _ = _make_ground_mesh()

        canvas = RenderCanvas(size=(self._width, self._height), title=self._title)
        adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
        device = adapter.request_device_sync()
        context = canvas.get_context("wgpu")
        fmt = context.get_preferred_format(adapter)
        context.configure(device=device, format=fmt, alpha_mode="opaque")

        shader = device.create_shader_module(code=SHADER_CODE)

        cam_buf = device.create_buffer(
            size=128, usage=wgpu.BufferUsage.UNIFORM | wgpu.BufferUsage.COPY_DST)

        inst_buf_size = self.MAX_INSTANCES * 48
        inst_buf = device.create_buffer(
            size=inst_buf_size,
            usage=wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST)

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
            {"binding": 1, "resource": {"buffer": inst_buf, "size": inst_buf_size}},
        ])

        # Vertex buffer layout: pos(3f) + normal(3f) + color(3f) = 36 bytes
        vb_layout = {
            "array_stride": 36,
            "step_mode": wgpu.VertexStepMode.vertex,
            "attributes": [
                {"format": wgpu.VertexFormat.float32x3, "offset": 0, "shader_location": 0},
                {"format": wgpu.VertexFormat.float32x3, "offset": 12, "shader_location": 1},
                {"format": wgpu.VertexFormat.float32x3, "offset": 24, "shader_location": 2},
            ],
        }

        pipeline = device.create_render_pipeline(
            layout=device.create_pipeline_layout(bind_group_layouts=[bgl]),
            vertex={"module": shader, "entry_point": "vs_main",
                    "buffers": [vb_layout]},
            fragment={"module": shader, "entry_point": "fs_main",
                      "targets": [{"format": fmt}]},
            primitive={"topology": wgpu.PrimitiveTopology.triangle_list,
                       "cull_mode": wgpu.CullMode.back},
            depth_stencil={"format": wgpu.TextureFormat.depth24plus,
                           "depth_write_enabled": True,
                           "depth_compare": wgpu.CompareFunction.less},
        )

        # Create GPU vertex buffers per mesh kind
        def _pack_verts(verts):
            floats = []
            for v in verts:
                floats.extend(v[:9])
            return struct.pack(f"{len(floats)}f", *floats)

        # Map kind_id → GPU vertex buffer + vertex count
        kind_vbufs = {}  # kind_id -> (vbuf, num_verts)

        # Ground mesh (kind_id = -1)
        ground_data = _pack_verts(ground_mesh)
        ground_vbuf = device.create_buffer_with_data(
            data=ground_data, usage=wgpu.BufferUsage.VERTEX)
        kind_vbufs[-1] = (ground_vbuf, len(ground_mesh))

        # Entity meshes
        for kid, kind_name in enumerate(self._kind_names):
            if kind_name in mesh_lib:
                verts, _ = mesh_lib[kind_name]
            else:
                verts = cube_mesh
            data = _pack_verts(verts)
            vbuf = device.create_buffer_with_data(
                data=data, usage=wgpu.BufferUsage.VERTEX)
            kind_vbufs[kid] = (vbuf, len(verts))

        # Fallback cube for unknown kinds
        cube_data = _pack_verts(cube_mesh)
        cube_vbuf = device.create_buffer_with_data(
            data=cube_data, usage=wgpu.BufferUsage.VERTEX)

        last_time = [time.perf_counter()]
        fog_state = {"color": (0.22, 0.24, 0.28), "near": 15.0, "far": 55.0}
        ambient_state = [(0.72, 0.65, 0.58)]
        draw_groups = [{}]  # kind_id -> list of instance tuples

        cam = self.cam

        @canvas.add_event_handler("key_down")
        def on_key_down(event):
            self._keys_pressed.add(event.get("key", ""))

        @canvas.add_event_handler("key_up")
        def on_key_up(event):
            self._keys_pressed.discard(event.get("key", ""))

        @canvas.add_event_handler("pointer_move")
        def on_mouse(event):
            x, y = event.get("x", 0), event.get("y", 0)
            if self._last_mouse[0] is not None:
                dx = x - self._last_mouse[0]
                dy = y - self._last_mouse[1]
                cam["h"] -= dx * 0.3
                cam["p"] = max(-60, min(60, cam["p"] + dy * 0.3))
            self._last_mouse[0], self._last_mouse[1] = x, y

        def draw_frame():
            now = time.perf_counter()
            dt = now - last_time[0]
            last_time[0] = now
            frame_ms = dt * 1000
            self._frame_times.append(frame_ms)
            if len(self._frame_times) > 120:
                self._frame_times.pop(0)
            self._frame_count += 1

            # Movement
            speed = 8.0 * dt
            fwd_x = -math.sin(math.radians(cam["h"]))
            fwd_y = math.cos(math.radians(cam["h"]))
            if "w" in self._keys_pressed or "ArrowUp" in self._keys_pressed:
                cam["x"] += fwd_x * speed; cam["y"] += fwd_y * speed
            if "s" in self._keys_pressed or "ArrowDown" in self._keys_pressed:
                cam["x"] -= fwd_x * speed; cam["y"] -= fwd_y * speed
            if "a" in self._keys_pressed or "ArrowLeft" in self._keys_pressed:
                cam["x"] -= fwd_y * speed; cam["y"] += fwd_x * speed
            if "d" in self._keys_pressed or "ArrowRight" in self._keys_pressed:
                cam["x"] += fwd_y * speed; cam["y"] -= fwd_x * speed
            if "Escape" in self._keys_pressed:
                canvas.close()
                return

            # Ask brain for manifest
            manifest = frame_callback(cam, dt)
            if manifest is not None:
                fog = manifest.get("fog")
                if fog:
                    fog_state["color"] = fog["color"]
                    fog_state["near"] = fog["near"]
                    fog_state["far"] = fog["far"]
                amb = manifest.get("ambient")
                if amb:
                    ambient_state[0] = amb

                # Group entities by kind_id for per-mesh draw calls
                entities = manifest.get("entities", [])
                groups = {}
                for e in entities:
                    kid = e[0]
                    groups.setdefault(kid, []).append(e)
                draw_groups[0] = groups

            # Camera uniform
            fc = fog_state["color"]
            amb = ambient_state[0]
            proj = make_perspective(65, self._width / self._height, 0.5, 120.0)
            view = make_view(cam["x"], cam["y"], cam["z"], cam["h"], cam["p"])
            vp = mat4_mul(proj, view)

            data = struct.pack("16f", *vp)
            data += struct.pack("4f", fc[0], fc[1], fc[2], 1.0)
            data += struct.pack("4f", fog_state["near"], fog_state["far"], 0.0, 0.0)
            data += struct.pack("4f", amb[0], amb[1], amb[2], 1.0)
            data += struct.pack("4f", cam["x"], cam["y"], cam["z"], 0.0)
            device.queue.write_buffer(cam_buf, 0, data)

            cur_tex = context.get_current_texture()
            tex_view = cur_tex.create_view()
            w, h = cur_tex.size[0], cur_tex.size[1]
            if w != depth_size[0] or h != depth_size[1]:
                dt_tex = device.create_texture(
                    size=(w, h, 1), format=wgpu.TextureFormat.depth24plus,
                    usage=wgpu.TextureUsage.RENDER_ATTACHMENT)
                depth_view[0] = dt_tex.create_view()
                depth_size[0], depth_size[1] = w, h

            enc = device.create_command_encoder()
            rp = enc.begin_render_pass(
                color_attachments=[{
                    "view": tex_view, "resolve_target": None,
                    "load_op": wgpu.LoadOp.clear, "store_op": wgpu.StoreOp.store,
                    "clear_value": (fc[0], fc[1], fc[2], 1.0),
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

            # Draw each kind group with its own vertex buffer
            total_instances = 0
            inst_offset = 0  # byte offset into instance buffer

            for kid, group in draw_groups[0].items():
                count = min(len(group), self.MAX_INSTANCES - total_instances)
                if count <= 0:
                    break

                # Pack this group's instances into the storage buffer
                # Entity: (kind_id, x, y, z, heading, sx, sy, sz, r, g, b, emissive)
                # Instance: 12 floats = 10 data + emissive + pad
                floats = []
                for i in range(count):
                    e = group[i]
                    floats.extend(e[1:])  # skip kind_id → 11 floats (includes emissive)
                    floats.append(0.0)  # pad
                inst_data = struct.pack(f"{len(floats)}f", *floats)
                device.queue.write_buffer(inst_buf, inst_offset, inst_data)

                # Get vertex buffer for this kind
                if kid in kind_vbufs:
                    vbuf, num_verts = kind_vbufs[kid]
                else:
                    vbuf, num_verts = cube_vbuf, len(cube_mesh)

                rp.set_vertex_buffer(0, vbuf)
                rp.draw(num_verts, count,
                        first_instance=inst_offset // 48)

                inst_offset += count * 48
                total_instances += count

            rp.end()
            device.queue.submit([enc.finish()])

            # Perf report
            if self._frame_count % 60 == 0 and len(self._frame_times) > 10:
                avg = sum(self._frame_times) / len(self._frame_times)
                fps = 1000.0 / avg if avg > 0 else 0
                print(f"  avg={avg:.1f}ms  fps={fps:.0f}  instances={total_instances}  "
                      f"kinds={len(draw_groups[0])}",
                      flush=True)

            canvas.request_draw(draw_frame)

        import sys
        print(f"{self._title} ready", flush=True)
        print("WASD=move, mouse=look, ESC=quit", flush=True)
        sys.stdout.flush()
        canvas.request_draw(draw_frame)
        loop.run()
