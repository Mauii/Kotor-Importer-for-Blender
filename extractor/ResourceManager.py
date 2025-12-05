# ResourceManager.py
import os
from pathlib import Path
from KeyFormat import Key
from BifFormat import BIF
from ErfFormat import ERF
from RimFormat import RIM
from ResourceTypes import ResourceTypeInfo
from Sanitize import sanitize_resref
from TextureLookup import TextureLookup


class ResourceManager:
    def __init__(self, key_path=None, erf_path=None):
        """
        Load either a KEY (with BIFFs) or a standalone ERF/HAK/MOD archive.
        Exactly one of key_path or erf_path must be provided.
        """
        if (key_path is None) == (erf_path is None):
            raise ValueError("Provide exactly one of key_path or erf_path")

        self.key_path = key_path
        self.erf_path = erf_path

        self.key = Key(key_path) if key_path else None
        self.erf = None
        self._texture_lookup = None  # lazy init for fallback textures
        if erf_path:
            if str(erf_path).lower().endswith(".rim"):
                self.erf = RIM(erf_path)
            else:
                self.erf = ERF(erf_path)

        self.bif_cache = {}

        # lookup tables (keep ALL duplicates per resref to avoid picking wrong type)
        if self.key:
            self.by_resref = {}
            for e in self.key.key_table:
                self.by_resref.setdefault(e.ResRef.lower(), []).append(e)

            self.by_resid = {e.ResID: e for e in self.key.key_table}
            self.by_entry_index = {e.EntryIndex: e for e in self.key.key_table}
        else:
            self.by_resref = {}
            self.by_resid = {}
            self.by_entry_index = {}

    # --------------------------------------------------------------

    def _load_bif(self, index):
        if index not in self.bif_cache:
            path = self.key.get_bif_path(index)
            if not os.path.exists(path):
                raise FileNotFoundError(f"BIF not found: {path}")
            self.bif_cache[index] = BIF(path)
        return self.bif_cache[index]

    # --------------------------------------------------------------

    def get_resource_entries(self, resref):
        if self.erf:
            return self.erf.get_entries(resref)
        return self.by_resref.get(resref.lower(), [])

    def get_resource_entry(self, resref, resource_type=None):
        """
        Return an entry for a resref.

        If multiple resource types share the same ResRef (e.g. mdl + mdx),
        you must pass resource_type to disambiguate; otherwise we raise to
        avoid exporting the wrong file.
        """
        entries = self.get_resource_entries(resref)
        if not entries:
            return None

        if resource_type is None:
            types = {e.ResType for e in entries} if self.erf else {e.ResourceType for e in entries}
            if len(types) > 1:
                raise ValueError(
                    f"ResRef '{resref}' exists in multiple resource types: {sorted(types)}; "
                    f"pass resource_type explicitly."
                )
            return entries[0]

        for e in entries:
            etype = e.ResType if self.erf else e.ResourceType
            if etype == resource_type:
                return e
        return None

    def get_resource_entry_by_resid(self, resid):
        if self.erf:
            return None
        return self.by_resid.get(resid)

    def get_resource_entry_by_index(self, entry_index):
        if self.erf:
            return None
        return self.by_entry_index.get(entry_index)

    def extract_entry(self, entry):
        """
        Extract raw bytes for a specific KeyEntry.
        Handles both variable and (if present) fixed resources.
        """
        if self.erf:
            return self.erf.extract_entry(entry)

        bif = self._load_bif(entry.BIFIndex)

        if entry.ResourceIndex is not None and entry.ResourceIndex < len(bif.variable_resources):
            return bif.get_variable_resource_data(entry.ResourceIndex)

        if bif.fixed_resources and entry.FixedIndex is not None and entry.FixedIndex < len(bif.fixed_resources):
            return bif.get_fixed_resource_data(entry.FixedIndex)

        raise IndexError("Resource index exceeds available resources in BIF")

    def extract_resref(self, resref, resource_type=None):
        entry = None
        try:
            entry = self.get_resource_entry(resref, resource_type)
        except Exception:
            entry = None

        if entry is not None:
            return self.extract_entry(entry)

        # Fallback: texture lookup via TexturePacks/patch.erf if we have a game path
        fetched = self._fetch_texture_bytes(resref)
        if fetched:
            data, _mime, _name = fetched
            return data

        raise KeyError(f"Unknown resource: {resref}")

    def extract_resid(self, resid):
        entry = self.get_resource_entry_by_resid(resid)
        if entry is None:
            raise KeyError(f"Unknown ResID: {resid}")
        return self.extract_entry(entry)

    # --------------------------------------------------------------

    def export_entry(self, entry, out_folder):
        """
        Export a specific entry to disk.

        Falls back to TextureLookup when the backing archive is missing (e.g., texture packs not on disk).
        """
        primary_error = None
        try:
            data = self.extract_entry(entry)

            res_type = entry.ResType if self.erf else entry.ResourceType
            ext = ResourceTypeInfo.get_extension(res_type) or "bin"

            os.makedirs(out_folder, exist_ok=True)

            safe = sanitize_resref(entry.ResRef)
            out_path = os.path.join(out_folder, f"{safe}.{ext}")

            with open(out_path, "wb") as f:
                f.write(data)

            return out_path
        except Exception as exc:
            primary_error = exc

        # Fallback: texture lookup (TexturePacks / patch.erf)
        fetched = self._fetch_texture_bytes(entry.ResRef)
        if fetched:
            data, _mime, name = fetched
            os.makedirs(out_folder, exist_ok=True)
            name_path = Path(name)
            safe_stem = sanitize_resref(name_path.stem)
            target = Path(out_folder) / f"{safe_stem}{name_path.suffix}"
            with open(target, "wb") as f:
                f.write(data)
            return str(target)

        # No fallback available; re-raise the original error
        if primary_error:
            raise primary_error
        raise FileNotFoundError(f"Unable to export {entry.ResRef}")

    def export_resource(self, resref, out_folder, resource_type=None):
        """
        Backwards-compatible export by resref.
        If multiple entries share a resref, resource_type is required.
        """
        entry = None
        try:
            entry = self.get_resource_entry(resref, resource_type)
        except Exception:
            entry = None

        if entry is not None:
            return self.export_entry(entry, out_folder)

        # Fallback: texture lookup via TexturePacks/patch.erf if available
        fetched = self._fetch_texture_bytes(resref)
        if fetched:
            data, _mime, name = fetched
            os.makedirs(out_folder, exist_ok=True)
            target = Path(out_folder) / name
            with open(target, "wb") as f:
                f.write(data)
            return str(target)

        raise KeyError(f"Unknown resource: {resref}")

    # --------------------------------------------------------------
    def _fetch_texture_bytes(self, resref):
        """
        Texture fallback using TexturePacks ERFs then patch.erf when in KEY mode.
        Returns (data, mime, name) or None.
        """
        if not self.key_path:
            return None
        if self._texture_lookup is None:
            try:
                self._texture_lookup = TextureLookup(Path(self.key_path).parent)
            except Exception:
                self._texture_lookup = False
        if not self._texture_lookup:
            return None
        return self._texture_lookup.fetch_texture(Path(resref).stem)
