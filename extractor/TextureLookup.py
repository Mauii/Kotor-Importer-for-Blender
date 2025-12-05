# TextureLookup.py
from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from ErfFormat import ERF
from ResourceTypes import ResourceTypeInfo
from TPCToPNG import tpc_bytes_to_png_bytes


ALLOWED_TEXTURE_TYPES = {3007, 2007, 2033}  # TPC/PC texture/DDS


TextureResult = Tuple[bytes, str, str]


class TextureLookup:
    """
    Resolve texture resrefs by scanning game TexturePack ERFs first, then patch.erf.

    Search order (stop at first hit):
    1) <game>/TexturePacks/*.erf
    2) <game>/patch.erf
    """

    def __init__(self, game_path: Path):
        self.game_path = Path(game_path)
        self._erf_cache: Dict[Path, ERF] = {}
        self._result_cache: Dict[str, Optional[TextureResult]] = {}

        self.texturepack_erfs = self._collect_texturepack_erfs()
        self.patch_erf_path = self.game_path / "patch.erf"

    # ------------------------------------------------------------------
    def _collect_texturepack_erfs(self) -> List[Path]:
        tex_dir = self.game_path / "TexturePacks"
        if not tex_dir.exists():
            return []
        return sorted(p for p in tex_dir.glob("*.erf") if p.is_file())

    def _load_erf(self, path: Path) -> ERF:
        if path not in self._erf_cache:
            self._erf_cache[path] = ERF(str(path))
        return self._erf_cache[path]

    def _substring_candidates(self, resref: str) -> List[str]:
        """
        Generate fallback substring candidates (strip trailing digits/segments) for fuzzy search.
        """
        name = resref.lower()
        candidates: List[str] = []

        def add(s: str):
            s = s.strip("_")
            if len(s) >= 3 and s not in candidates:
                candidates.append(s)

        add(name)
        # strip trailing digits
        add(name.rstrip("0123456789"))
        # progressively strip trailing underscore segments: a_b_c -> a_b -> a
        parts = name.split("_")
        while len(parts) > 1:
            parts = parts[:-1]
            add("_".join(parts))

        return candidates

    def _find_in_erfs(self, paths: Iterable[Path], resref: str, *, allow_partial: bool = False):
        substrings = self._substring_candidates(resref) if allow_partial else [resref.lower()]
        for path in paths:
            try:
                erf = self._load_erf(path)
            except Exception:
                continue
            if not allow_partial:
                for res_type in ALLOWED_TEXTURE_TYPES:
                    entry = erf.get_entry(resref, res_type)
                    if entry:
                        return entry, erf
            else:
                best_match = None  # (score, entry)
                for entry in erf.entries:
                    if entry.ResType not in ALLOWED_TEXTURE_TYPES:
                        continue
                    name = entry.ResRef.lower()
                    score = max((len(sub) for sub in substrings if sub and sub in name), default=0)
                    if score:
                        if not best_match or score > best_match[0]:
                            best_match = (score, entry)
                if best_match:
                    return best_match[1], erf
        return None, None

    # ------------------------------------------------------------------
    def _convert_result(self, entry, erf) -> TextureResult:
        data = erf.extract_entry(entry)
        ext = ResourceTypeInfo.get_extension(entry.ResType) or "bin"
        resref = entry.ResRef

        if entry.ResType in (2007, 3007):  # TPC -> PNG
            try:
                png_bytes = tpc_bytes_to_png_bytes(data)
                return png_bytes, "image/png", f"{resref}.png"
            except Exception:
                # Fallback to raw TPC if conversion fails
                return data, "application/octet-stream", f"{resref}.tpc"

        if entry.ResType == 2033:  # DDS
            return data, "image/vnd.ms-dds", f"{resref}.dds"

        return data, "application/octet-stream", f"{resref}.{ext}"

    # ------------------------------------------------------------------
    def fetch_texture(self, resref: str) -> Optional[TextureResult]:
        """
        Returns tuple(bytes, mime, filename) or None if not found.
        """
        key = resref.lower()
        if key in self._result_cache:
            return self._result_cache[key]

        entry, erf = self._find_in_erfs(self.texturepack_erfs, resref, allow_partial=False)
        if not entry and self.patch_erf_path.exists():
            entry, erf = self._find_in_erfs([self.patch_erf_path], resref, allow_partial=False)

        # Fuzzy fallback: try substring matches (e.g., Logo_SW_001 -> Logo_SW)
        if not entry:
            entry, erf = self._find_in_erfs(self.texturepack_erfs, resref, allow_partial=True)
        if not entry and self.patch_erf_path.exists():
            entry, erf = self._find_in_erfs([self.patch_erf_path], resref, allow_partial=True)

        if entry and erf:
            result = self._convert_result(entry, erf)
        else:
            result = None

        self._result_cache[key] = result
        return result
