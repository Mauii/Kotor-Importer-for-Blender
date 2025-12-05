# KeyFormat.py
import struct
import os
from Sanitize import sanitize_resref


class Key:
    HEADER_SIZE = 64

    def __init__(self, path):
        self.path = path
        self.data = self._open(path)

        self._read_header()
        self.file_table = self._read_file_table()
        self._read_filename_table()
        self.key_table = self._read_key_table()

        self._assign_bif_indexes()
        self._assign_entry_indexes()

    def _open(self, path):
        with open(path, "rb") as f:
            return f.read()

    def _read_header(self):
        fields = struct.unpack_from("<4s4sIIIIII", self.data, 0)
        (
            self.FileType,
            self.FileVersion,
            self.BIFCount,
            self.KeyCount,
            self.OffsetToFileTable,
            self.OffsetToKeyTable,
            self.BuildYear,
            self.BuildDay,
        ) = fields

        self.Reserved = self.data[32:64]

        if self.FileType != b"KEY ":
            raise ValueError("Invalid KEY signature")
        if not self.FileVersion.startswith(b"V1"):
            raise ValueError(f"Unsupported KEY version: {self.FileVersion!r}")

    # ----------------------------------------------------------------------

    def _read_file_table(self):
        entries = []
        offset = self.OffsetToFileTable

        for _ in range(self.BIFCount):
            file_size, name_offset, name_size, drives = struct.unpack_from(
                "<IIHH", self.data, offset
            )
            offset += 12
            entries.append(KeyFileEntry(file_size, name_offset, name_size, drives))

        return entries

    def _read_filename_table(self):
        for entry in self.file_table:
            start = entry.FilenameOffset
            end = start + entry.FilenameSize

            raw = self.data[start:end]
            clean = raw.split(b"\x00")[0]  # truncate at first null as per spec

            entry.Filename = clean.decode("cp1252", errors="ignore")


    # ----------------------------------------------------------------------

    def _read_key_table(self):
        entries = []
        offset = self.OffsetToKeyTable

        for _ in range(self.KeyCount):

            raw = struct.unpack_from("16s", self.data, offset)[0]
            offset += 16

            # fully null-safe resref
            resref = raw.split(b"\x00")[0].decode("cp1252", errors="ignore")
            resref = sanitize_resref(resref)

            resource_type = struct.unpack_from("<H", self.data, offset)[0]
            offset += 2

            res_id = struct.unpack_from("<I", self.data, offset)[0]
            offset += 4

            entries.append(KeyEntry(resref, resource_type, res_id))

        return entries

    # ----------------------------------------------------------------------

    def _assign_bif_indexes(self):
        for entry in self.key_table:
            rid = entry.ResID
            entry.BIFIndex = (rid >> 20) & 0xFFF
            entry.ResourceIndex = rid & 0xFFFFF  # variable-resource index
            entry.FixedIndex = (rid >> 14) & 0x3F  # fixed-resource index (spec limit 64)

    def _assign_entry_indexes(self):
        for i, entry in enumerate(self.key_table):
            entry.EntryIndex = i

    # ----------------------------------------------------------------------

    def get_bif_path(self, bif_index):
        entry = self.file_table[bif_index]
        base = os.path.dirname(self.path)
        return os.path.join(base, entry.Filename)


# ----------------------------------------------------------------------
# STRUCTS
# ----------------------------------------------------------------------

class KeyFileEntry:
    def __init__(self, file_size, filename_offset, filename_size, drives):
        self.FileSize = file_size
        self.FilenameOffset = filename_offset
        self.FilenameSize = filename_size
        self.Drives = drives
        self.Filename = None


class KeyEntry:
    def __init__(self, ResRef, ResourceType, ResID):
        self.ResRef = ResRef
        self.ResourceType = ResourceType
        self.ResID = ResID

        self.BIFIndex = None
        self.ResourceIndex = None
        self.FixedIndex = None
        self.EntryIndex = None
