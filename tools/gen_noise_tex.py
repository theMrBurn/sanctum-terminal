"""Generate a 64x64 tileable noise texture for triplanar detail mapping."""
import struct
import os

def hash2d(x, y):
    """Simple hash for deterministic noise."""
    n = x * 374761393 + y * 668265263
    n = (n ^ (n >> 13)) * 1274126177
    return (n & 0xFFFFFFFF) / 0xFFFFFFFF

def lerp(a, b, t):
    return a + (b - a) * t

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
    return lerp(lerp(a, b, fx), lerp(c, d, fx), fy)

def fbm(x, y, size, octaves=4):
    v = 0.0
    amp = 0.5
    freq = 1.0
    for _ in range(octaves):
        v += amp * smooth_noise(x * freq, y * freq, size)
        freq *= 2.0
        amp *= 0.5
    return v

def main():
    size = 64
    pixels = []
    for y in range(size):
        for x in range(size):
            v = fbm(x, y, size, octaves=4)
            # Map to 0.3-0.7 range (subtle detail, not high contrast)
            gray = int((0.3 + v * 0.4) * 255)
            gray = max(0, min(255, gray))
            pixels.append(gray)

    # Write as PNG (minimal, grayscale)
    # Use raw bytes and write a simple BMP instead for no dependencies
    out_path = os.path.join("godot", "noise_64.png")

    # Actually let's use the struct approach for a minimal grayscale PNG
    # Simpler: write as .exr or just raw. But easiest: write BMP
    # BMP: 14-byte header + 40-byte DIB + palette + pixels
    import zlib

    def write_png_gray(path, width, height, data):
        def chunk(ctype, cdata):
            c = ctype + cdata
            return struct.pack(">I", len(cdata)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

        sig = b'\x89PNG\r\n\x1a\n'
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
        raw = b''
        for y in range(height):
            raw += b'\x00'  # filter none
            for x in range(width):
                raw += bytes([data[y * width + x]])
        idat = zlib.compress(raw)

        with open(path, 'wb') as f:
            f.write(sig)
            f.write(chunk(b'IHDR', ihdr))
            f.write(chunk(b'IDAT', idat))
            f.write(chunk(b'IEND', b''))

    write_png_gray(out_path, size, size, pixels)
    print(f"Wrote {out_path} ({size}x{size})")

if __name__ == "__main__":
    main()
