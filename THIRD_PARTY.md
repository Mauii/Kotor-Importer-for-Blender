# Third-Party Components and Licenses

This repository bundles third-party libraries to make the Blender addon work out of the box. Please review their licenses before redistribution.

## Bundled Python Libraries

- **PyKotor** – LGPL-3.0-or-later  
  Source: https://github.com/th3w1zard1/PyKotor  
  Purpose: MDL/MDX parsing, TPC decoding

- **utility** – (part of the PyKotor toolchain)  
  Purpose: Common utilities required by PyKotor

- **loggerplus** – LGPL-2.1  
  Source: https://github.com/th3w1zard1/LoggerPlus  
  Purpose: Logging utility used by PyKotor/utility

- **ply** – BSD  
  Purpose: Parsing support required by PyKotor

## Extractor Scripts

Located under `extractor/` (KeyFormat, BifFormat, ResourceManager, etc.). These are custom scripts used to read KotOR game assets (KEY/BIFF/ERF/RIM) and convert TPC to PNG using PyKotor.

## Notes

- The repository as a whole is distributed under the LGPL-3.0 license (see `LICENSE`). Individual bundled components retain their own licenses as noted above.  
- KotOR game assets are not included; you must supply your own game files.
