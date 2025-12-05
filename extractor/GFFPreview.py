# GFFPreview.py
import json
from typing import Any

from pykotor.resource.formats.gff import gff_auto
from pykotor.resource.formats.gff.gff_data import GFFList, GFFStruct
from pykotor.resource.formats.tlk import tlk_auto
from pykotor.resource.formats.tlk.tlk_data import TLK
from ResourceTypes import ResourceTypeInfo

# Known GFF-based resource type IDs
GFF_TYPES = {
    2012,  # are
    2013,  # set (tileset)
    2014,  # ifo
    2015,  # bic
    2016,  # wok (walkmesh) -- not gff, but sometimes considered; exclude to avoid errors
    2017,  # 2da (not gff) -> exclude
    2018,  # tlk (not gff) -> exclude
    2022,  # txi (text) -> exclude
    2023,  # git
    2025,  # uti
    2027,  # utc
    2029,  # dlg
    2030,  # itp
    2032,  # utt
    2035,  # uts
    2036,  # ltr (not gff) -> exclude
    2037,  # gff
    2038,  # fac
    2040,  # ute
    2042,  # utd
    2044,  # utp
    2051,  # utm
    2056,  # jrl
    2058,  # utw
    2064,  # ndb
    2065,  # ptm
    2066,  # ptt
}


def is_gff_type(res_type: int) -> bool:
    return res_type in GFF_TYPES or ResourceTypeInfo.get_extension(res_type) == "gff"


def is_tlk_type(res_type: int) -> bool:
    return ResourceTypeInfo.get_extension(res_type) in ("tlk",)


def _to_basic(val: Any) -> Any:
    if isinstance(val, GFFList):
        return [_to_basic(v) for v in val]
    if isinstance(val, GFFStruct):
        return {k: _to_basic(v) for k, v in val.fields.items()}
    if isinstance(val, bytes):
        return list(val)
    return val


def gff_to_json(data: bytes) -> str:
    gff = gff_auto.read_gff(data)
    py = _to_basic(gff.root)
    return json.dumps(py, indent=2, ensure_ascii=False)


def tlk_to_json(data: bytes) -> str:
    tlk = tlk_auto.read_tlk(data)
    out = []
    for i, entry in enumerate(tlk):
        out.append({"id": i, "text": entry.text, "sound": entry.sound})
    return json.dumps(out, indent=2, ensure_ascii=False)
