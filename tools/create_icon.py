"""Create the ICO companion for the bundled 无忧28 vector icon.

The generator uses only Python's standard library so a clean build machine
does not need Pillow or ImageMagick.  The ICO embeds a 256px RGBA PNG frame,
which Windows and PyInstaller both accept as the executable icon.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "resources" / "wuyou28.ico"
SIZE = 256


def _pixel(x: int, y: int) -> tuple[int, int, int, int]:
    # Rounded blue tile with a simple white 28 mark.  Keep this geometric so
    # the asset remains deterministic and legible at small taskbar sizes.
    margin = 8
    radius = 54
    inside = margin <= x < SIZE - margin and margin <= y < SIZE - margin
    if inside:
        dx = min(x - margin, SIZE - margin - 1 - x)
        dy = min(y - margin, SIZE - margin - 1 - y)
        inside = dx >= radius or dy >= radius or (dx - radius) ** 2 + (dy - radius) ** 2 <= radius**2
    if not inside:
        return 237, 242, 247, 0
    # White block glyphs approximate the two digits without font dependencies.
    glyph = False
    if 54 <= x <= 116 and 58 <= y <= 80:
        glyph = True
    if 96 <= x <= 116 and 78 <= y <= 116:
        glyph = True
    if 54 <= x <= 116 and 106 <= y <= 128:
        glyph = True
    if 54 <= x <= 76 and 126 <= y <= 180:
        glyph = True
    if 54 <= x <= 116 and 168 <= y <= 190:
        glyph = True
    if 132 <= x <= 194 and 58 <= y <= 80:
        glyph = True
    if 132 <= x <= 194 and 106 <= y <= 128:
        glyph = True
    if 132 <= x <= 194 and 168 <= y <= 190:
        glyph = True
    if 132 <= x <= 154 and 72 <= y <= 174:
        glyph = True
    if 172 <= x <= 194 and 72 <= y <= 174:
        glyph = True
    return (255, 255, 255, 255) if glyph else (43, 110, 209, 255)


def _png() -> bytes:
    rows = []
    for y in range(SIZE):
        row = bytearray([0])
        for x in range(SIZE):
            row.extend(_pixel(x, y))
        rows.append(bytes(row))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
    payload += chunk(b"IEND", b"")
    return payload


def main() -> None:
    png = _png()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    OUTPUT.write_bytes(struct.pack("<HHH", 0, 1, 1) + entry + png)
    print(OUTPUT)


if __name__ == "__main__":
    main()
