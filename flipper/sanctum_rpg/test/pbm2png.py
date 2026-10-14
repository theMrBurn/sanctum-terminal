"""pbm2png — tile 128x64 PBM frames into one PNG contact sheet (stdlib only).

Frames are drawn in the Flipper's LCD colours (black segments on orange),
scaled up with nearest-neighbour so single pixels stay legible.

    python3 test/pbm2png.py out.png [--scale 4] [--cols 2] frame1.pbm frame2.pbm ...
"""
import struct
import sys
import zlib

ON = (0, 0, 0)
OFF = (255, 140, 40)        # Flipper Zero LCD backlight orange
GAP = 4


def read_pbm(path):
    tokens = open(path).read().split()
    assert tokens[0] == "P1"
    w, h = int(tokens[1]), int(tokens[2])
    bits = "".join(tokens[3:])
    return w, h, [[bits[y * w + x] == "1" for x in range(w)] for y in range(h)]


def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(c for px in row for c in px) for row in rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    open(path, "wb").write(png)


def main(argv):
    out, args = argv[1], argv[2:]
    scale, cols = 4, 2
    while args and args[0].startswith("--"):
        if args[0] == "--scale":
            scale = int(args[1])
        elif args[0] == "--cols":
            cols = int(args[1])
        args = args[2:]
    frames = [read_pbm(p) for p in args]
    fw, fh = frames[0][0] * scale, frames[0][1] * scale
    nrows = (len(frames) + cols - 1) // cols
    W, H = cols * fw + (cols + 1) * GAP, nrows * fh + (nrows + 1) * GAP
    canvas = [[(40, 40, 40)] * W for _ in range(H)]
    for i, (w, h, px) in enumerate(frames):
        ox = GAP + (i % cols) * (fw + GAP)
        oy = GAP + (i // cols) * (fh + GAP)
        for y in range(h * scale):
            row = canvas[oy + y]
            src = px[y // scale]
            for x in range(w * scale):
                row[ox + x] = ON if src[x // scale] else OFF
    write_png(out, W, H, canvas)


if __name__ == "__main__":
    main(sys.argv)
