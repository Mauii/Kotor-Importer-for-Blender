# TPCToPNG.py
"""
TPC to PNG converter using pykotor's TPC loader and DXT helpers.

Supports: DXT1, DXT3, DXT5, RGB, RGBA, BGR, BGRA, Greyscale (first layer, top mip).
Relies only on the standard library (no Pillow dependency).
"""
from __future__ import annotations

import binascii
import struct
import tempfile
import warnings
import zlib
from pathlib import Path
from typing import Optional, Tuple

from pykotor.resource.formats.tpc import tpc_auto
from pykotor.resource.formats.tpc.convert.dxt.decompress_dxt import (
    dxt1_to_rgb,
    dxt3_to_rgba,
    dxt5_to_rgba,
)
from pykotor.resource.formats.tpc.tpc_data import TPCTextureFormat


def _flip_vertical(width: int, height: int, channels: int, data: bytes) -> bytes:
    """Flip raw image data vertically (used to match the original orientation)."""
    stride = width * channels
    flipped = bytearray(len(data))
    for y in range(height):
        src = y * stride
        dst = (height - 1 - y) * stride
        flipped[dst : dst + stride] = data[src : src + stride]
    return bytes(flipped)


def _png_chunk(chunk_type: bytes, chunk_data: bytes) -> bytes:
    """Pack a PNG chunk with length and CRC."""
    length = struct.pack("!I", len(chunk_data))
    crc = struct.pack("!I", binascii.crc32(chunk_type + chunk_data) & 0xFFFFFFFF)
    return length + chunk_type + chunk_data + crc


def _encode_png(width: int, height: int, mode: str, data: bytes) -> bytes:
    """Encode raw image bytes into a minimal PNG (8-bit depth)."""
    color_types = {"L": 0, "RGB": 2, "RGBA": 6}
    channels = {"L": 1, "RGB": 3, "RGBA": 4}
    if mode not in color_types:
        raise ValueError(f"Unsupported PNG mode: {mode}")

    stride = width * channels[mode]
    raw = bytearray()
    for y in range(height):
        start = y * stride
        raw.append(0)  # filter type 0 (None) per scanline
        raw.extend(data[start : start + stride])

    ihdr = struct.pack(
        "!IIBBBBB",
        width,
        height,
        8,  # bit depth
        color_types[mode],
        0,  # compression
        0,  # filter
        0,  # interlace
    )

    png = bytearray()
    png.extend(b"\x89PNG\r\n\x1a\n")
    png.extend(_png_chunk(b"IHDR", ihdr))
    png.extend(_png_chunk(b"IDAT", zlib.compress(bytes(raw))))
    png.extend(_png_chunk(b"IEND", b""))
    return bytes(png)


def decode_tpc(path: Path) -> Tuple[int, int, str, bytes]:
    """
    Decode a TPC file into raw image data.

    Returns:
        width, height, mode ("RGB", "RGBA", or "L"), data bytes.
    """
    warnings.filterwarnings("ignore", message="Invalid TXI command.*")
    warnings.filterwarnings("ignore", message="Invalid TXI.*")

    tex = tpc_auto.read_tpc(str(path))
    if not tex.layers:
        raise ValueError("TPC has no layers")
    layer = tex.layers[0]
    if not layer.mipmaps:
        raise ValueError("TPC layer has no mipmaps")
    mip = layer.mipmaps[0]
    fmt = TPCTextureFormat(mip.tpc_format)
    w, h = mip.width, mip.height
    data = mip.data

    if fmt == TPCTextureFormat.DXT1:
        rgb = dxt1_to_rgb(data, w, h)
        return w, h, "RGB", bytes(rgb)
    if fmt == TPCTextureFormat.DXT3:
        rgba = dxt3_to_rgba(data, w, h)
        return w, h, "RGBA", bytes(rgba)
    if fmt == TPCTextureFormat.DXT5:
        rgba = dxt5_to_rgba(data, w, h)
        return w, h, "RGBA", bytes(rgba)
    if fmt == TPCTextureFormat.RGB:
        return w, h, "RGB", bytes(data)
    if fmt == TPCTextureFormat.RGBA:
        return w, h, "RGBA", bytes(data)
    if fmt == TPCTextureFormat.BGR:
        rgb = bytearray()
        for i in range(0, len(data), 3):
            b, g, r = data[i : i + 3]
            rgb.extend([r, g, b])
        return w, h, "RGB", bytes(rgb)
    if fmt == TPCTextureFormat.BGRA:
        rgba = bytearray()
        for i in range(0, len(data), 4):
            b, g, r, a = data[i : i + 4]
            rgba.extend([r, g, b, a])
        return w, h, "RGBA", bytes(rgba)
    if fmt == TPCTextureFormat.Greyscale:
        return w, h, "L", bytes(data)

    raise ValueError(f"Unsupported TPC format: {fmt}")


def tpc_to_png(src: Path, dst: Optional[Path] = None) -> Path:
    """
    Convert a .tpc texture to a PNG file without requiring Pillow.
    """
    width, height, mode, data = decode_tpc(src)
    channels = {"L": 1, "RGB": 3, "RGBA": 4}[mode]
    flipped = _flip_vertical(width, height, channels, data)
    png_bytes = _encode_png(width, height, mode, flipped)

    dst = dst or src.with_suffix(".png")
    dst.write_bytes(png_bytes)
    return dst


def tpc_bytes_to_png_bytes(data: bytes) -> bytes:
    """
    Convert raw TPC bytes to PNG bytes (in-memory).
    Uses a temporary file because pykotor's TPC loader expects a path.
    """
    with tempfile.NamedTemporaryFile(suffix=".tpc", delete=False) as tmp:
        tmp.write(data)
        tmp_path = Path(tmp.name)
    try:
        width, height, mode, raw = decode_tpc(tmp_path)
        channels = {"L": 1, "RGB": 3, "RGBA": 4}[mode]
        flipped = _flip_vertical(width, height, channels, raw)
        return _encode_png(width, height, mode, flipped)
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Convert KOTOR TPC to PNG.")
    parser.add_argument("tpc", type=Path, help="Path to .tpc")
    parser.add_argument("-o", "--out", type=Path, help="Output PNG path")
    args = parser.parse_args()

    out_path = tpc_to_png(args.tpc, args.out)
    print(f"Saved {out_path}")
