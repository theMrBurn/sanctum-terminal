"""Generate a 128x128 tileable stone normal map for triplanar mapping."""
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

def fbm(x, y, size, octaves=5):
    v = 0.0
    amp = 0.5
    freq = 1.0
    for _ in range(octaves):
        v += amp * smooth_noise(x * freq, y * freq, size)
        freq *= 2.17
        amp *= 0.48
    return v

def voronoi_cracks(x, y, size):
    """Voronoi-based crack pattern — returns distance to nearest cell edge."""
    ix = int(x) % size
    iy = int(y) % size
    fx = x - int(x)
    fy = y - int(y)
    min_d1 = 999.0
    min_d2 = 999.0
    for dy in range(-1, 2):
        for dx in range(-1, 2):
            nx = (ix + dx) % size
            ny = (iy + dy) % size
            px = hash2d(nx * 7 + 13, ny * 11 + 7)
            py = hash2d(nx * 13 + 3, ny * 7 + 11)
            ddx = dx + px - fx
            ddy = dy + py - fy
            d = math.sqrt(ddx*ddx + ddy*ddy)
            if d < min_d1:
                min_d2 = min_d1
                min_d1 = d
            elif d < min_d2:
                min_d2 = d
    return min_d2 - min_d1  # edge distance — 0 = on crack, high = cell center

def write_png_rgb(path, width, height, pixels):
    def chunk(ctype, cdata):
        c = ctype + cdata
        return struct.pack(">I", len(cdata)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    sig = b'\x89PNG\r\n\x1a\n'
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8bit RGB
    raw = b''
    for y in range(height):
        raw += b'\x00'  # filter none
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
    pixels = []

    for y in range(size):
        for x in range(size):
            # Large-scale surface undulation
            h1 = fbm(x * 0.08, y * 0.08, size, octaves=4)
            # Fine grain/pitting
            h2 = fbm(x * 0.3, y * 0.3, size, octaves=3) * 0.3
            # Crack pattern
            crack = voronoi_cracks(x * 0.06, y * 0.06, size)
            crack_contribution = max(0, 0.15 - crack) * 4.0  # sharp crack lines

            h = h1 + h2 + crack_contribution

            # Compute normal from height via central differences
            eps = 1.0
            hx = fbm((x+eps) * 0.08, y * 0.08, size, 4) + fbm((x+eps) * 0.3, y * 0.3, size, 3) * 0.3
            hy = fbm(x * 0.08, (y+eps) * 0.08, size, 4) + fbm(x * 0.3, (y+eps) * 0.3, size, 3) * 0.3

            # Add crack to derivatives too
            cx = voronoi_cracks((x+eps) * 0.06, y * 0.06, size)
            cy = voronoi_cracks(x * 0.06, (y+eps) * 0.06, size)
            hx += max(0, 0.15 - cx) * 4.0
            hy += max(0, 0.15 - cy) * 4.0

            dx = (hx - h) * 2.0
            dy = (hy - h) * 2.0

            # Normal map: (dx, dy, 1) normalized, encoded as RGB [0,255]
            length = math.sqrt(dx*dx + dy*dy + 1.0)
            nx = dx / length
            ny = dy / length
            nz = 1.0 / length

            # Encode: 0.5 + 0.5*n maps [-1,1] to [0,1]
            r = int((0.5 + 0.5 * nx) * 255)
            g = int((0.5 + 0.5 * ny) * 255)
            b = int((0.5 + 0.5 * nz) * 255)
            pixels.extend([max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))])

    out_path = os.path.join("godot", "stone_128.png")
    write_png_rgb(out_path, size, size, pixels)
    print(f"Wrote {out_path} ({size}x{size} normal map)")

    # Also generate a simpler organic normal map
    pixels2 = []
    for y in range(64):
        for x in range(64):
            h = fbm(x * 0.12, y * 0.12, 64, octaves=3)
            hx = fbm((x+1) * 0.12, y * 0.12, 64, 3)
            hy = fbm(x * 0.12, (y+1) * 0.12, 64, 3)
            dx = (hx - h) * 1.2
            dy = (hy - h) * 1.2
            length = math.sqrt(dx*dx + dy*dy + 1.0)
            r = int((0.5 + 0.5 * dx / length) * 255)
            g = int((0.5 + 0.5 * dy / length) * 255)
            b = int((0.5 + 0.5 / length) * 255)
            pixels2.extend([max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))])

    out_path2 = os.path.join("godot", "organic_64.png")
    write_png_rgb(out_path2, 64, 64, pixels2)
    print(f"Wrote {out_path2} (64x64 organic normal map)")

if __name__ == "__main__":
    main()
