"""Generate the WORLD_GRAIN base pattern — one texture, all surfaces derive from it.

Voronoi cells + mortar lines + Perlin noise, matching the Panda3D
generate_stone_texture / _generate_material_texture visual language.

Output: godot/world_grain.png (128x128, tileable, grayscale)
This is THE pattern. Every surface in the world samples it at
WORLD_GRAIN × MATERIAL_RATIO scale.
"""
import struct
import zlib
import os
import math


def hash2d(x, y):
    n = x * 374761393 + y * 668265263
    n = (n ^ (n >> 13)) * 1274126177
    return (n & 0xFFFFFFFF) / 0xFFFFFFFF


def smooth_noise(x, y, size):
    ix = int(x) % size
    iy = int(y) % size
    fx = x - int(x)
    fy = y - int(y)
    fx = fx * fx * (3 - 2 * fx)
    fy = fy * fy * (3 - 2 * fy)
    a = hash2d(ix, iy)
    b = hash2d((ix+1) % size, iy)
    c = hash2d(ix, (iy+1) % size)
    d = hash2d((ix+1) % size, (iy+1) % size)
    return a*(1-fx)*(1-fy) + b*fx*(1-fy) + c*(1-fx)*fy + d*fx*fy


def fbm(x, y, size, octaves=4):
    v = 0.0
    amp = 0.5
    freq = 1.0
    for _ in range(octaves):
        v += amp * smooth_noise(x * freq, y * freq, size)
        freq *= 2.13
        amp *= 0.47
    return v


def voronoi(x, y, size):
    """Voronoi cell pattern — returns (cell_distance, edge_distance, cell_id)."""
    ix = int(x) % size
    iy = int(y) % size
    fx = x - int(x)
    fy = y - int(y)
    min_d1 = 999.0
    min_d2 = 999.0
    cell_id = 0
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            nx = (ix + dx) % size
            ny = (iy + dy) % size
            # Cell center position (deterministic from grid)
            px = hash2d(nx * 7 + 13, ny * 11 + 7)
            py = hash2d(nx * 13 + 3, ny * 7 + 11)
            ddx = dx + px - fx
            ddy = dy + py - fy
            d = math.sqrt(ddx*ddx + ddy*ddy)
            if d < min_d1:
                min_d2 = min_d1
                min_d1 = d
                cell_id = hash2d(nx, ny)
            elif d < min_d2:
                min_d2 = d
    edge_dist = min_d2 - min_d1
    return min_d1, edge_dist, cell_id


def write_png_gray(path, width, height, data):
    def chunk(ctype, cdata):
        c = ctype + cdata
        return struct.pack(">I", len(cdata)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    raw = b''
    for y in range(height):
        raw += b'\x00'
        for x in range(width):
            raw += bytes([data[y * width + x]])
    idat = zlib.compress(raw)
    with open(path, 'wb') as f:
        f.write(sig)
        f.write(chunk(b'IHDR', ihdr))
        f.write(chunk(b'IDAT', idat))
        f.write(chunk(b'IEND', b''))


def write_png_rgb(path, width, height, pixels):
    def chunk(ctype, cdata):
        c = ctype + cdata
        return struct.pack(">I", len(cdata)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b''
    for y in range(height):
        raw += b'\x00'
        for x in range(width):
            idx = (y * width + x) * 3
            raw += bytes([pixels[idx], pixels[idx+1], pixels[idx+2]])
    idat = zlib.compress(raw)
    with open(path, 'wb') as f:
        f.write(sig)
        f.write(chunk(b'IHDR', ihdr))
        f.write(chunk(b'IDAT', idat))
        f.write(chunk(b'IEND', b''))


def main():
    size = 128
    cell_scale = 8.0  # Voronoi cell density — matches original ~10 cells visible

    # -- Base pattern: Voronoi cells + mortar + noise --
    pixels_gray = []
    pixels_normal = []

    heightmap = []
    for y in range(size):
        for x in range(size):
            u = x / size * cell_scale
            v = y / size * cell_scale

            cell_d, edge_d, cell_id = voronoi(u, v, size)

            # Mortar line: dark line at cell boundaries
            mortar_width = 0.08
            mortar = 1.0 - max(0, 1.0 - edge_d / mortar_width)

            # Cell-to-cell color variation (subtle, from cell_id)
            cell_var = 0.85 + cell_id * 0.30  # 0.85-1.15 range

            # Perlin noise overlay — surface grain
            noise_val = fbm(x * 0.15, y * 0.15, size, octaves=4)

            # Fine grit
            grit = fbm(x * 0.5, y * 0.5, size, octaves=2) * 0.15

            # Combine: base value + cell variation + mortar darkening + noise
            val = (0.45 + noise_val * 0.25 + grit) * cell_var * mortar
            val = max(0.0, min(1.0, val))

            pixels_gray.append(int(val * 255))
            heightmap.append(val)

    # -- Normal map from heightmap --
    for y in range(size):
        for x in range(size):
            idx = y * size + x
            h = heightmap[idx]
            # Central differences
            hx = heightmap[y * size + (x + 1) % size]
            hy = heightmap[((y + 1) % size) * size + x]
            dx = (hx - h) * 3.0  # strength multiplier
            dy = (hy - h) * 3.0

            length = math.sqrt(dx*dx + dy*dy + 1.0)
            nx = dx / length
            ny = dy / length
            nz = 1.0 / length

            r = int((0.5 + 0.5 * nx) * 255)
            g = int((0.5 + 0.5 * ny) * 255)
            b = int((0.5 + 0.5 * nz) * 255)
            pixels_normal.extend([
                max(0, min(255, r)),
                max(0, min(255, g)),
                max(0, min(255, b)),
            ])

    out_albedo = os.path.join("godot", "world_grain.png")
    out_normal = os.path.join("godot", "world_grain_normal.png")

    write_png_gray(out_albedo, size, size, pixels_gray)
    write_png_rgb(out_normal, size, size, pixels_normal)

    print(f"Wrote {out_albedo} ({size}x{size} — base pattern)")
    print(f"Wrote {out_normal} ({size}x{size} — normal map)")
    print(f"WORLD_GRAIN = 0.10, material ratios: stone_heavy=0.80, stone_light=1.00, dry_organic=1.20, bone=0.90")


if __name__ == "__main__":
    main()
