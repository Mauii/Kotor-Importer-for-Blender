# KotOR Importer for Blender

Blender add-on to browse KotOR models directly from `chitin.key`, extract MDL/MDX (and textures), and import them into Blender. Includes bundled PyKotor and extractor scripts for a turnkey setup.

## Features

- Browse models from `chitin.key` (unique resrefs, no duplicate MDL/MDX entries) in a 3D Viewport N-panel.
- Extract selected model (MDL/MDX) and referenced textures; supports `.tpc/.tga/.bmp` with TPC converted to PNG for Blender use.
- Imports meshes, walkmesh collision, optional non-render meshes. No empty placeholders; clean scene output.
- Texture caches cleaned after each import (keeps only the latest import’s cache). Optional shallow ERF scan by default for faster/lower-memory imports; set `KOTOR_DEEP_ERF_SCAN=1` to re-enable full recursive ERF/RIM search.

## Installation

1. Clone the repo into your Blender add-ons folder (or install as a zip):  
   `git clone https://github.com/Mauii/Kotor-Importer-for-Blender.git`
2. Blender → Edit → Preferences → Add-ons → Install… → select the folder (or zip) → enable “KotOR MDL/MDX Importer”.

## Usage

1. Open 3D Viewport → press `N` → **KotOR Import** tab.  
2. Set **Game Path** to your KotOR root folder (where `chitin.key` resides).  
3. Click **Refresh Models** to load the list; use the search box to filter.  
4. Select a model and click **Import Selected Model**.  
   - Textures are extracted/converted to a temp cache and used for the import.  
   - Options: Game (K1/K2), Import Walkmesh, Import Non-render meshes.  
5. Optional: To save the converted textures elsewhere, set **Texture Save Folder** and click **Save Textures** after an import.

## Notes / Limitations

- Animations are not imported (nor supported, yet) (fast load mode).  
- Texture search order: `TexturePacks/swpc_tex_tpa.erf` → `TexturePacks/swpc_tex_gui.erf`/`swpc_tex_tpb.erf`/`swpc_tex_tpc.erf` → `patch.erf` → (if enabled) other ERF/RIM under the game path → `Override` → BIF fallback.  
- You must supply your own game files; none are included.

## Credits

- Original add-on and extractor scripts: Maui  
- Development: Maui & ChatGPT  
- Bundled libraries: PyKotor (NickHugi), utility (PyKotor toolchain), loggerplus (Benjamin Auquite), ply (BSD).

## License

Distributed under **LGPL-3.0** (see `LICENSE`). Bundled components retain their own licenses (see `THIRD_PARTY.md`).
