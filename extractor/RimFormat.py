# RimFormat.py
"""
Minimal RIM reader (per kotor-modding wiki).
Header: 124 bytes
  FileType   4s   "RIM "
  Version    4s   "V1.0"
  Reserved   I
  KeyCount   I
  KeyListOffset I
  Reserved2  100 bytes

Key Entry (32 bytes):
  ResRef[16] (null-padded)
  ResType    uint32
  ResID      uint32
  ResOffset  uint32
  ResSize    uint32
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List

from Sanitize import sanitize_resref
from ResourceTypes import ResourceTypeInfo


@dataclass
class RIMHeader:
    FileType: bytes
    Version: bytes
    Reserved: int
    KeyCount: int
    KeyListOffset: int
    Reserved2: bytes

    SIZE = 124


@dataclass
class RIMEntry:
    ResRef: str
    ResType: int
    ResID: int
    Offset: int
    Size: int


class RIM:
    def __init__(self, path: str):
        self.path = path
        self.data = self._open(path)
        self.header = self._read_header()
        self.entries = self._read_entries()
        self.by_resref = {}
        for e in self.entries:
            self.by_resref.setdefault(e.ResRef.lower(), []).append(e)

    def _open(self, path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def _read_header(self) -> RIMHeader:
        if len(self.data) < RIMHeader.SIZE:
            raise ValueError("File too small for RIM header")
        tup = struct.unpack_from("<4s4sIII100s", self.data, 0)
        hdr = RIMHeader(*tup)
        if hdr.FileType != b"RIM ":
            raise ValueError(f"Invalid RIM FileType: {hdr.FileType!r}")
        if hdr.Version != b"V1.0":
            raise ValueError(f"Unsupported RIM version: {hdr.Version!r}")
        return hdr

    def _read_entries(self) -> List[RIMEntry]:
        out = []
        offset = self.header.KeyListOffset
        for _ in range(self.header.KeyCount):
            resref_raw = self.data[offset : offset + 16]
            offset += 16
            resref = resref_raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore")
            resref = sanitize_resref(resref)
            restype, resid, resoff, ressize = struct.unpack_from("<IIII", self.data, offset)
            offset += 16
            out.append(RIMEntry(resref, restype, resid, resoff, ressize))
        return out

    def get_entries(self, resref: str) -> List[RIMEntry]:
        return self.by_resref.get(resref.lower(), [])

    def extract_entry(self, entry: RIMEntry) -> bytes:
        start = entry.Offset
        end = start + entry.Size
        return self.data[start:end]

    def export_entry(self, entry: RIMEntry, out_folder: str) -> str:
        import os

        data = self.extract_entry(entry)
        ext = ResourceTypeInfo.get_extension(entry.ResType) or "bin"
        os.makedirs(out_folder, exist_ok=True)
        out_path = os.path.join(out_folder, f"{entry.ResRef}.{ext}")
        with open(out_path, "wb") as f:
            f.write(data)
        return out_path
