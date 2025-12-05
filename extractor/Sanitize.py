# Sanitize.py
import re

def sanitize_resref(name: str) -> str:
    """
    Clean a ResRef for safe Windows/Linux filenames.
    Removes:
      - NULLs
      - control chars
      - non-ASCII garbage
      - weird padding bytes
    Allows:
      A-Z a-z 0-9 _ -
    """
    if not name:
        return "unknown"

    # Remove nulls and invisible control chars
    name = "".join(c for c in name if c.isprintable())

    # Strict ASCII whitelist
    name = re.sub(r"[^A-Za-z0-9_\-]", "", name)

    if not name:
        return "unknown"

    return name
