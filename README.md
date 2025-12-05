<<<<<<< HEAD
# Kotor-Importer-for-Blender
This tool is a very user-friendly tool to import any model you'd like into Blender. It imports the mesh, bones, weights and textures. Allows saving the textures (in .png) aswell.
=======
# Kotor Importer for Blender

Blender addon to browse KotOR models directly from `chitin.key`, extract MDL/MDX (and textures), and import them into Blender. Includes bundled PyKotor and extractor scripts for a turnkey setup.

## Features

- Browse models from `chitin.key` (unique resrefs, no duplicate MDL/MDX entries) in a 3D Viewport N-panel.
- Extract selected model (MDL/MDX) and referenced textures (TPC/DDS/TGA → PNG) from TexturePacks (`swpc_tex_tpa.erf`) and other ERF/RIM/Override sources.
- Import meshes, lights, walkmesh collision, optional non-render meshes.
- No empties; clean scene output. Texture cache retained; you can copy PNGs after import.

## Installation

1. Clone the repo into your Blender addons folder (or install as a zip):  
   `git clone https://github.com/Mauii/Kotor-Importer-for-Blender.git`
2. Launch Blender → Edit → Preferences → Add-ons → Install… → select the folder (or zip) → enable “KotOR MDL/MDX Importer”.

## Usage

1. Open 3D Viewport → press `N` → **KotOR Import** tab.  
2. Set **Game Path** to your KotOR root folder (where `chitin.key` resides).  
3. Click **Refresh Models** to load the list. Use the search box to filter.  
4. Select a model and click **Import Selected Model**.  
   - Textures are extracted/converted to a temp cache and used for the import.  
   - Options: Game (K1/K2), Import Walkmesh, Import Non-render meshes.  
5. Optional: To save the converted PNGs elsewhere, set **Texture Save Folder** and click **Save Textures** (after an import).

## Notes / Limitations

- Animations are not imported (fast load mode).  
- Textures are pulled in this order: `TexturePacks/swpc_tex_tpa.erf` → other ERF/RIM under the game path → `Override` → BIF (fallback).  
- You must supply your own game files; none are included.

## Credits

- Original addon and extractor scripts: Maui  
- Development: Maui & ChatGPT  
- Bundled libraries: PyKotor (NickHugi), utility (PyKotor toolchain), loggerplus (Benjamin Auquite), ply (BSD).

## License

This repository is distributed under the **LGPL-3.0** license (see `LICENSE`). Bundled components retain their own licenses (see `THIRD_PARTY.md`).
>>>>>>> 7e266e2 (Initial import: KotOR Blender addon with extractor, bundled deps, and docs)
