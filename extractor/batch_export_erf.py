"""
Batch export/convert ERF-like archives (erf/hak/mod/nwm/sav).

For each archive under a game path, extracts its contents into a folder named
after the archive, converts TPC -> PNG, and exports other files as-is. MDL/MDX
are kept raw (no GLB conversion). Also supports extracting BIFFs referenced by
a chitin.key.

Usage:
    python batch_export_erf.py --game "C:\\Games\\swkotor" --out "C:\\exports"
"""
from __future__ import annotations

import argparse
import os
import traceback
from pathlib import Path
from typing import Dict, List

from ErfFormat import ERF
from RimFormat import RIM
from ResourceManager import ResourceManager
from ResourceTypes import ResourceTypeInfo
from TPCToPNG import tpc_to_png

ERF_EXTS = {".erf", ".hak", ".mod", ".nwm", ".sav"}


def _log_error(out_root: Path, message: str, *, exc: Exception | None = None) -> None:
    """Append errors to a log file and print to console."""
    console_msg = f"{message} (details in errors.log)" if exc else message
    print(console_msg)
    try:
        out_root.mkdir(parents=True, exist_ok=True)
        log_path = out_root / "errors.log"
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(message + "\n")
            if exc:
                lf.write("".join(traceback.format_exception(exc)) + "\n")
    except Exception:
        pass


def export_archive(erf_path: Path, out_root: Path) -> None:
    print(f"[ERF] {erf_path}")
    er = ERF(str(erf_path))

    archive_name = erf_path.stem
    # Map resref -> entries for pairing mdl/mdx
    resref_map: Dict[str, List] = {}
    for e in er.entries:
        resref_map.setdefault(e.ResRef.lower(), []).append(e)

    def type_dir_for(ext: str) -> Path:
        return out_root / ext.upper() / archive_name

    for entry in er.entries:
        res_type = entry.ResType
        resref = entry.ResRef

        try:
            # TPC -> PNG
            if res_type in (2007, 3007):
                raw_dir = type_dir_for("tpc")
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = er.export_entry(entry, raw_dir)
                png_dir = type_dir_for("png")
                png_dir.mkdir(parents=True, exist_ok=True)
                png_path = tpc_to_png(Path(raw_path), png_dir / (Path(raw_path).stem + ".png"))
                print(f"  TPC -> {png_path.name}")
                continue

            # MDL + MDX -> raw export (no GLB)
            if res_type == 2002:
                mdx_entry = next(
                    (e for e in resref_map.get(resref.lower(), []) if e.ResType == 3008),
                    None,
                )
                if mdx_entry:
                    mdl_dir = type_dir_for("mdl")
                    mdl_dir.mkdir(parents=True, exist_ok=True)
                    raw_mdl = er.export_entry(entry, mdl_dir)
                    raw_mdx = er.export_entry(mdx_entry, mdl_dir)
                    print(f"  saved {Path(raw_mdl).name} and {Path(raw_mdx).name}")
                    continue
                else:
                    # fall through to raw export if no MDX found
                    pass

            # Default: raw export with proper extension
            ext = ResourceTypeInfo.get_extension(res_type)
            target_dir = type_dir_for(ext or "bin")
            target_dir.mkdir(parents=True, exist_ok=True)
            out_path = er.export_entry(entry, target_dir)
            print(f"  saved {Path(out_path).name}")

        except Exception as exc:  # pragma: no cover - best-effort batch
            _log_error(out_root, f"  failed {resref}: {exc!r}", exc=exc)


def find_archives(
    game_path: Path,
    include_erf: bool = True,
    include_mod: bool = True,
    include_rim: bool = False,
    include_hak: bool = True,
) -> List[Path]:
    archives: List[Path] = []
    if include_erf:
        archives.extend(game_path.rglob("*.erf"))
    if include_hak:
        archives.extend(game_path.rglob("*.hak"))
    if include_mod:
        archives.extend(game_path.rglob("*.mod"))
    if include_rim:
        archives.extend(game_path.rglob("*.rim"))
    # de-dup
    return sorted(set(archives))


def export_bif(rm: ResourceManager, bif_index: int, out_root: Path) -> None:
    bif_entry = rm.key.file_table[bif_index]
    archive_name = Path(bif_entry.Filename).stem
    print(f"[BIF] {bif_entry.Filename}")

    entries = [e for e in rm.key.key_table if e.BIFIndex == bif_index]
    resref_map: Dict[str, List] = {}
    for e in entries:
        resref_map.setdefault(e.ResRef.lower(), []).append(e)

    def type_dir_for(ext: str) -> Path:
        return out_root / ext.upper() / archive_name

    for entry in entries:
        res_type = entry.ResourceType
        resref = entry.ResRef

        try:
            # TPC -> PNG
            if res_type in (2007, 3007):
                raw_dir = type_dir_for("tpc")
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = rm.export_entry(entry, raw_dir)
                png_dir = type_dir_for("png")
                png_dir.mkdir(parents=True, exist_ok=True)
                png_path = tpc_to_png(Path(raw_path), png_dir / (Path(raw_path).stem + ".png"))
                print(f"  TPC -> {png_path.name}")
                continue

            # MDL + MDX -> raw export (no GLB)
            if res_type == 2002:
                mdx_entry = next((e for e in resref_map.get(resref.lower(), []) if e.ResourceType == 3008), None)
                if mdx_entry:
                    mdl_dir = type_dir_for("mdl")
                    mdl_dir.mkdir(parents=True, exist_ok=True)
                    raw_mdl = rm.export_entry(entry, mdl_dir)
                    raw_mdx = rm.export_entry(mdx_entry, mdl_dir)
                    print(f"  saved {Path(raw_mdl).name} and {Path(raw_mdx).name}")
                    continue
                else:
                    pass

            # Default
            ext = ResourceTypeInfo.get_extension(res_type)
            target_dir = type_dir_for(ext or "bin")
            target_dir.mkdir(parents=True, exist_ok=True)
            out_path = rm.export_entry(entry, target_dir)
            print(f"  saved {Path(out_path).name}")

        except Exception as exc:  # pragma: no cover
            _log_error(out_root, f"  failed {resref}: {exc!r}", exc=exc)


def export_rim(rim_path: Path, out_root: Path) -> None:
    print(f"[RIM] {rim_path}")
    rim = RIM(str(rim_path))
    archive_name = rim_path.stem

    resref_map: Dict[str, List] = {}
    for e in rim.entries:
        resref_map.setdefault(e.ResRef.lower(), []).append(e)

    def type_dir_for(ext: str) -> Path:
        return out_root / ext.upper() / archive_name

    for entry in rim.entries:
        res_type = entry.ResType
        resref = entry.ResRef

        try:
            if res_type in (2007, 3007):
                raw_dir = type_dir_for("tpc")
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_path = rim.export_entry(entry, raw_dir)
                png_dir = type_dir_for("png")
                png_dir.mkdir(parents=True, exist_ok=True)
                png_path = tpc_to_png(Path(raw_path), png_dir / (Path(raw_path).stem + ".png"))
                print(f"  TPC -> {png_path.name}")
                continue

            if res_type == 2002:
                mdx_entry = next((e for e in resref_map.get(resref.lower(), []) if e.ResType == 3008), None)
                if mdx_entry:
                    mdl_dir = type_dir_for("mdl")
                    mdl_dir.mkdir(parents=True, exist_ok=True)
                    raw_mdl = rim.export_entry(entry, mdl_dir)
                    raw_mdx = rim.export_entry(mdx_entry, mdl_dir)
                    print(f"  saved {Path(raw_mdl).name} and {Path(raw_mdx).name}")
                    continue

            ext = ResourceTypeInfo.get_extension(res_type)
            target_dir = type_dir_for(ext or "bin")
            target_dir.mkdir(parents=True, exist_ok=True)
            out_path = rim.export_entry(entry, target_dir)
            print(f"  saved {Path(out_path).name}")
        except Exception as exc:
            _log_error(out_root, f"  failed {resref}: {exc!r}", exc=exc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch export/convert ERF-like archives.")
    parser.add_argument("--game", required=True, type=Path, help="Root game path to search for archives")
    parser.add_argument("--out", type=Path, default=Path("exports"), help="Output root folder")
    parser.add_argument("--key", type=Path, help="Path to chitin.key (for BIF extraction); defaults to <game>/chitin.key if present")
    parser.add_argument("--erf", action="store_true", default=False, help="Include .erf files")
    parser.add_argument("--hak", action="store_true", default=False, help="Include .hak files")
    parser.add_argument("--mod", action="store_true", default=False, help="Include .mod files")
    parser.add_argument("--rim", action="store_true", default=False, help="Include .rim files")
    parser.add_argument("--bif", nargs="*", type=int, help="Specific BIF indices to export (default: all)")
    args = parser.parse_args()

    # Default to all except rim if none specified
    if not any([args.erf, args.hak, args.mod, args.rim]):
        args.erf = args.hak = args.mod = True

    archives = find_archives(args.game, include_erf=args.erf, include_mod=args.mod, include_rim=args.rim, include_hak=args.hak)
    if not archives:
        print("No ERF-like archives found.")

    args.out.mkdir(parents=True, exist_ok=True)
    for erf_path in archives:
        if erf_path.suffix.lower() == ".rim":
            export_rim(erf_path, args.out)
        else:
            export_archive(erf_path, args.out)

    # BIF extraction via chitin.key
    key_path = args.key or (args.game / "chitin.key")
    if key_path.exists():
        try:
            rm = ResourceManager(key_path=key_path)
            indices = args.bif if args.bif else list(range(len(rm.key.file_table)))
            for idx in indices:
                if idx < 0 or idx >= len(rm.key.file_table):
                    print(f"Skipping invalid BIF index {idx}")
                    continue
                export_bif(rm, idx, args.out)
        except Exception as e:
            print(f"Failed BIF extraction: {e}")
    else:
        print("No chitin.key found; skipped BIF extraction.")


if __name__ == "__main__":
    main()
