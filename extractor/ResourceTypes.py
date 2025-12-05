class ResourceTypeInfo:
    """
    Provides lookup for KOTOR resource type → extension/description.
    Also supports reverse lookup (extension → type ID).
    """

    _TABLE = {
        2002: ("mdl", "Kotor Model"),
        2007: ("tpc", "Texture"),
        2009: ("ncs", "Compiled Script"),
        2010: ("nss", "Source Script"),
        2012: ("are", "Area Information"),
        2014: ("ifo", "Module Information"),
        2016: ("wok", "Walkmesh"),
        2017: ("2da", "2DA Table"),
        2018: ("tlk", "Talk Table"),
        2022: ("txi", "Texture Information"),
        2023: ("git", "Game Instance"),
        2025: ("uti", "Item Template"),
        2027: ("utc", "Creature Template"),
        2029: ("dlg", "Dialogue"),
        2032: ("utt", "Trigger Template"),
        2033: ("dds", "DirectDraw Texture"),
        2035: ("uts", "Sound Template"),
        2036: ("ltr", "Letterboxing / Unknown"),
        2037: ("gff", "Generic File"),
        2038: ("fac", "Faction"),
        2040: ("ute", "Encounter Template"),
        2042: ("utd", "Door Template"),
        2044: ("utp", "Placeable Template"),
        2047: ("gui", "GUI Layout"),
        2051: ("utm", "Merchant Template"),
        2052: ("dwk", "Door Walkmesh"),
        2053: ("pwk", "Placeable Walkmesh"),
        2056: ("jrl", "Journal"),
        2058: ("utw", "Waypoint Template"),
        2060: ("ssf", "Soundset"),
        3000: ("lyt", "Area Layout"),
        3001: ("vis", "Area Visibility Map"),
        3002: ("rim", "Resource Image"),
        3003: ("pth", "Area Path"),
        3004: ("lip", "Lip Sync File"),
        3007: ("tpc", "PC Texture"),
        3008: ("mdx", "Model Extension"),
        9997: ("erf", "Encapsulated Resource"),
        9998: ("bif", "BIF Archive"),
        9999: ("key", "KEY File"),
    }

    # Build reverse lookup (extension → type ID)
    _EXT_LOOKUP = {ext: tid for tid, (ext, desc) in _TABLE.items()}

    @classmethod
    def get_extension(cls, type_id: int) -> str | None:
        """Returns extension for a type ID."""
        return cls._TABLE.get(type_id, (None, None))[0]

    @classmethod
    def get_description(cls, type_id: int) -> str | None:
        """Returns human-readable description."""
        return cls._TABLE.get(type_id, (None, None))[1]

    @classmethod
    def get_typeid(cls, extension: str) -> int | None:
        """Lookup type ID from extension."""
        extension = extension.lower()
        return cls._EXT_LOOKUP.get(extension)

    @classmethod
    def exists(cls, type_id: int) -> bool:
        return type_id in cls._TABLE

    @classmethod
    def __repr__(cls):
        lines = ["<ResourceTypeInfo>"]
        for tid, (ext, desc) in sorted(cls._TABLE.items()):
            lines.append(f"  {tid:<6} {ext:<6} {desc}")
        return "\n".join(lines)
