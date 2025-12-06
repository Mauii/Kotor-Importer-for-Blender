# Changelog

## 1.1.0
- Improved texture handling in the Blender add-on: prefer `.png`, extract `.tpc/.tga/.bmp`, convert TPC to PNG, and clean temp caches after each import.
- Added optional shallow ERF scanning by default (env `KOTOR_DEEP_ERF_SCAN=1` restores deep search) to reduce memory and speed up imports.
- Hardened MDL loading against missing normals/UVs and invalid plane coefficients to avoid crashes.

## 1.0.0
- Initial release of the KotOR MDL/MDX Blender importer.
