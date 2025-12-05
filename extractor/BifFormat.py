# BifFormat.py
import struct


class BIF:
    def __init__(self, path):
        self.path = path
        self.data = self._open(path)

        self.header = Header()
        self.header.set_variables(self.data[:Header.SIZE])

        self.variable_resources = self._read_variable_table()
        self.fixed_resources = self._read_fixed_table()

        self._assign_entry_indexes()

    def _open(self, path):
        with open(path, "rb") as f:
            return f.read()

    def _read_variable_table(self):
        entries = []
        offset = self.header.VariableTableOffset

        for _ in range(self.header.VariableResourceCount):
            res_id, off, size, typ = struct.unpack_from("<IIII", self.data, offset)
            offset += VariableResourceEntry.SIZE

            entries.append(VariableResourceEntry(res_id, off, size, typ))

        return entries

    def _read_fixed_table(self):
        """
        Fixed resources are uncommon (not used by KOTOR), but parse them per spec.
        The fixed table follows immediately after the variable table.
        """
        if self.header.FixedResourceCount == 0:
            return []

        offset = self.header.VariableTableOffset + (
            self.header.VariableResourceCount * VariableResourceEntry.SIZE
        )
        entries = []

        for _ in range(self.header.FixedResourceCount):
            res_id, off, part_count, size, typ = struct.unpack_from(
                "<IIIII", self.data, offset
            )
            offset += FixedResourceEntry.SIZE
            entries.append(FixedResourceEntry(res_id, off, part_count, size, typ))

        return entries

    def _assign_entry_indexes(self):
        for i, entry in enumerate(self.variable_resources):
            entry.EntryIndex = i
        for i, entry in enumerate(self.fixed_resources):
            entry.EntryIndex = i

    def get_variable_resource_data(self, index):
        e = self.variable_resources[index]
        return self.data[e.Offset : e.Offset + e.FileSize]

    def get_fixed_resource_data(self, index):
        e = self.fixed_resources[index]
        return self.data[e.Offset : e.Offset + e.FileSize]


# ----------------------------------------------------------------------

class Header:
    SIZE = 20

    def __init__(self):
        self.FileType = None
        self.Version = None
        self.VariableResourceCount = None
        self.FixedResourceCount = None
        self.VariableTableOffset = None

    def set_variables(self, data):
        (
            self.FileType,
            self.Version,
            self.VariableResourceCount,
            self.FixedResourceCount,
            self.VariableTableOffset,
        ) = struct.unpack_from("<4s4sIII", data, 0)

        if self.FileType != b"BIFF":
            raise ValueError("Invalid BIFF signature")
        if not self.Version.startswith(b"V1"):
            raise ValueError(f"Unsupported BIFF version: {self.Version!r}")


class VariableResourceEntry:
    SIZE = 16

    def __init__(self, res_id, offset, file_size, res_type):
        self.ID = res_id
        self.Offset = offset
        self.FileSize = file_size
        self.ResourceType = res_type
        self.EntryIndex = None


class FixedResourceEntry:
    SIZE = 20

    def __init__(self, res_id, offset, part_count, file_size, res_type):
        self.ID = res_id
        self.Offset = offset
        self.PartCount = part_count
        self.FileSize = file_size
        self.ResourceType = res_type
        self.EntryIndex = None
