"""
Batch export all MDL/MDX pairs from chitin.key/BIFFs. No GLB conversion; raw
MDL/MDX are saved.

Usage:
    python batch_export_mdl.py --key "C:\\Games\\swkotor\\chitin.key" --out "C:\\exports_mdl"
"""
from __future__ import annotations

import argparse
import traceback
from pathlib import Path
from typing import Dict, List, Tuple

from ResourceManager import ResourceManager

def _log(log_path: Path, message: str, *, exc: Exception | None = None) -> None:
    console_msg = f"{message} (details in {log_path.name})" if exc else message
    print(console_msg)
    try:
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(message + "\n")
            if exc:
                lf.write("".join(traceback.format_exception(exc)) + "\n")
    except Exception:
        pass


def find_mdl_mdx_pairs(rm: ResourceManager) -> List[Tuple]:
    pairs = []
    # group by resref lower
    buckets: Dict[str, List] = {}
    for e in rm.key.key_table:
        if e.ResourceType in (2002, 3008):  # mdl/mdx
            buckets.setdefault(e.ResRef.lower(), []).append(e)
    for _, entries in buckets.items():
        mdl_entry = next((e for e in entries if e.ResourceType == 2002), None)
        mdx_entry = next((e for e in entries if e.ResourceType == 3008), None)
        if mdl_entry:
            pairs.append((mdl_entry, mdx_entry))
    return pairs


def export_all(key_path: Path, out_root: Path) -> None:
    rm = ResourceManager(key_path=str(key_path))
    pairs = find_mdl_mdx_pairs(rm)
    out_root.mkdir(parents=True, exist_ok=True)
    log_path = out_root / "mdl_errors.log"
    for mdl_entry, mdx_entry in pairs:
        try:
            mdl_dir = out_root / "mdl"
            mdl_dir.mkdir(parents=True, exist_ok=True)
            raw_mdl = rm.export_entry(mdl_entry, mdl_dir)
            raw_mdx = None
            if mdx_entry:
                raw_mdx = rm.export_entry(mdx_entry, mdl_dir)
            if raw_mdx:
                print(f"{mdl_entry.ResRef}: saved MDL/MDX")
            else:
                print(f"{mdl_entry.ResRef}: MDX missing, saved MDL only")
        except Exception as exc:  # pragma: no cover
            _log(log_path, f"{mdl_entry.ResRef} failed: {exc}", exc=exc)


def main():
    parser = argparse.ArgumentParser(description="Batch export MDL/MDX via chitin.key (no GLB conversion)")
    parser.add_argument("--key", required=True, type=Path, help="Path to chitin.key")
    parser.add_argument("--out", type=Path, default=Path("mdl_exports"), help="Output root folder")
    args = parser.parse_args()
    export_all(args.key, args.out)


if __name__ == "__main__":
    main()
