# ErfFormat.py
"""
Minimal ERF/HAK/MOD/NWM reader for BioWare Aurora Engine archives.

Supported per spec (ERF V1.0):
    - Header parsing (type/version checks)
    - Localized string list (stored for reference)
    - Key list (ResRef/ResType/ResID)
    - Resource list (offset/size)
    - Extraction by resref or index

Usage example:
    from ErfFormat import ERF
    erf = ERF("path/to/archive.erf")
    entry = erf.get_entry("some_resref")
    data = erf.extract_entry(entry)
"""

import os
import struct
from dataclasses import dataclass
from typing import List, Optional

from ResourceTypes import ResourceTypeInfo
from Sanitize import sanitize_resref


@dataclass
class ERFHeader:
    FileType: bytes
    Version: bytes
    LanguageCount: int
    LocalizedStringSize: int
    EntryCount: int
    OffsetToLocalizedString: int
    OffsetToKeyList: int
    OffsetToResourceList: int
    BuildYear: int
    BuildDay: int
    DescriptionStrRef: int
    Reserved: bytes

    SIZE = 160  # bytes


@dataclass
class ERFString:
    LanguageID: int
    Text: str


@dataclass
class ERFKeyEntry:
    ResRef: str
    ResID: int
    ResType: int


@dataclass
class ERFResourceEntry:
    OffsetToResource: int
    ResourceSize: int


@dataclass
class ERFEntry:
    ResRef: str
    ResType: int
    ResID: int
    Offset: int
    Size: int


class ERF:
    def __init__(self, path: str):
        self.path = path
        self.data = self._open(path)

        self.header = self._read_header()
        self.localized_strings = self._read_localized_strings()
        self.key_entries = self._read_key_list()
        self.resource_entries = self._read_resource_list()

        self.entries = self._combine_entries()
        self.by_resref = {}
        for e in self.entries:
            self.by_resref.setdefault(e.ResRef.lower(), []).append(e)

    # ------------------------------------------------------------------
    def _open(self, path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    # ------------------------------------------------------------------
    def _read_header(self) -> ERFHeader:
        if len(self.data) < ERFHeader.SIZE:
            raise ValueError("File too small to be a valid ERF")

        header_tuple = struct.unpack_from("<4s4sIIIIIIIII116s", self.data, 0)
        header = ERFHeader(*header_tuple)

        if header.FileType not in (b"ERF ", b"MOD ", b"HAK ", b"SAV ", b"NWM "):
            raise ValueError(f"Unsupported ERF FileType: {header.FileType!r}")
        if header.Version != b"V1.0":
            raise ValueError(f"Unsupported ERF Version: {header.Version!r}")

        return header

    def _read_localized_strings(self) -> List[ERFString]:
        out: List[ERFString] = []
        offset = self.header.OffsetToLocalizedString

        for _ in range(self.header.LanguageCount):
            lang_id, size = struct.unpack_from("<II", self.data, offset)
            offset += 8

            raw = self.data[offset : offset + size]
            offset += size

            text = raw.decode("utf-8", errors="ignore").rstrip("\x00")
            out.append(ERFString(lang_id, text))

        return out

    def _read_key_list(self) -> List[ERFKeyEntry]:
        out: List[ERFKeyEntry] = []
        offset = self.header.OffsetToKeyList

        for _ in range(self.header.EntryCount):
            resref_raw = self.data[offset : offset + 16]
            offset += 16
            resref = resref_raw.split(b"\x00", 1)[0].decode("ascii", errors="ignore")
            resref = sanitize_resref(resref)

            resid, restype, _unused = struct.unpack_from("<IHH", self.data, offset)
            offset += 8

            out.append(ERFKeyEntry(resref, resid, restype))

        return out

    def _read_resource_list(self) -> List[ERFResourceEntry]:
        out: List[ERFResourceEntry] = []
        offset = self.header.OffsetToResourceList

        for _ in range(self.header.EntryCount):
            res_off, res_size = struct.unpack_from("<II", self.data, offset)
            offset += 8
            out.append(ERFResourceEntry(res_off, res_size))

        return out

    def _combine_entries(self) -> List[ERFEntry]:
        entries: List[ERFEntry] = []
        for key, res in zip(self.key_entries, self.resource_entries):
            entries.append(
                ERFEntry(
                    ResRef=key.ResRef,
                    ResType=key.ResType,
                    ResID=key.ResID,
                    Offset=res.OffsetToResource,
                    Size=res.ResourceSize,
                )
            )
        return entries

    # ------------------------------------------------------------------
    # LOOKUPS / EXTRACTION
    # ------------------------------------------------------------------
    def get_entries(self, resref: str) -> List[ERFEntry]:
        return self.by_resref.get(resref.lower(), [])

    def get_entry(self, resref: str, res_type: Optional[int] = None) -> Optional[ERFEntry]:
        entries = self.get_entries(resref)
        if not entries:
            return None
        if res_type is None:
            if len({e.ResType for e in entries}) > 1:
                raise ValueError(
                    f"ResRef '{resref}' exists in multiple resource types: "
                    f"{sorted({e.ResType for e in entries})}; pass res_type explicitly."
                )
            return entries[0]
        for e in entries:
            if e.ResType == res_type:
                return e
        return None

    def extract_entry(self, entry: ERFEntry) -> bytes:
        start = entry.Offset
        end = start + entry.Size
        return self.data[start:end]

    def export_entry(self, entry: ERFEntry, out_folder: str) -> str:
        data = self.extract_entry(entry)
        ext = ResourceTypeInfo.get_extension(entry.ResType)

        os.makedirs(out_folder, exist_ok=True)
        safe = sanitize_resref(entry.ResRef)
        out_path = os.path.join(out_folder, f"{safe}.{ext}")

        with open(out_path, "wb") as f:
            f.write(data)
        return out_path

    def export_resref(self, resref: str, out_folder: str, res_type: Optional[int] = None) -> str:
        entry = self.get_entry(resref, res_type)
        if entry is None:
            raise KeyError(f"Unknown resource: {resref}")
        return self.export_entry(entry, out_folder)
