# TPCToPNG.py
"""
TPC to PNG converter using pykotor's TPC loader and DXT helpers.

Supports: DXT1, DXT3, DXT5, RGB, RGBA, BGR, BGRA, Greyscale (first layer, top mip).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import tempfile
import io

from PIL import Image
from pykotor.resource.formats.tpc import tpc_auto
from pykotor.resource.formats.tpc.convert.dxt.decompress_dxt import (
    dxt1_to_rgb,
    dxt3_to_rgba,
    dxt5_to_rgba,
)
from pykotor.resource.formats.tpc.tpc_data import TPCTextureFormat
import warnings


def decode_tpc(path: Path) -> Image.Image:
    # Suppress noisy TXI warnings from pykotor when present
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
        return Image.frombytes("RGB", (w, h), bytes(rgb))
    if fmt == TPCTextureFormat.DXT3:
        rgba = dxt3_to_rgba(data, w, h)
        return Image.frombytes("RGBA", (w, h), bytes(rgba))
    if fmt == TPCTextureFormat.DXT5:
        rgba = dxt5_to_rgba(data, w, h)
        return Image.frombytes("RGBA", (w, h), bytes(rgba))
    if fmt == TPCTextureFormat.RGB:
        return Image.frombytes("RGB", (w, h), data)
    if fmt == TPCTextureFormat.RGBA:
        return Image.frombytes("RGBA", (w, h), data)
    if fmt == TPCTextureFormat.BGR:
        # swap to RGB
        rgb = bytearray()
        for i in range(0, len(data), 3):
            b, g, r = data[i : i + 3]
            rgb.extend([r, g, b])
        return Image.frombytes("RGB", (w, h), bytes(rgb))
    if fmt == TPCTextureFormat.BGRA:
        rgba = bytearray()
        for i in range(0, len(data), 4):
            b, g, r, a = data[i : i + 4]
            rgba.extend([r, g, b, a])
        return Image.frombytes("RGBA", (w, h), bytes(rgba))
    if fmt == TPCTextureFormat.Greyscale:
        return Image.frombytes("L", (w, h), data)

    raise ValueError(f"Unsupported TPC format: {fmt}")


def tpc_to_png(src: Path, dst: Optional[Path] = None) -> Path:
    img = decode_tpc(src)
    # Fix orientation: invert horizontally then rotate 180°
    img = img.transpose(Image.FLIP_LEFT_RIGHT).rotate(180, expand=False)
    dst = dst or src.with_suffix(".png")
    img.save(dst)
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
        img = decode_tpc(tmp_path)
        img = img.transpose(Image.FLIP_LEFT_RIGHT).rotate(180, expand=False)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
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
