"""
Minimal MDL/MDX -> glTF (GLB) converter using pykotor + pygltflib.

Usage:
    python mdl_to_gltf.py path/to/model.mdl [path/to/model.mdx] -o out.glb

Notes:
    - Builds a single GLB with node hierarchy and static meshes (positions,
      normals, UV0). Skinning/animations are not exported yet.
    - Requires: pip install pykotor pygltflib
"""
from __future__ import annotations

import argparse
import base64
import math
import os
import struct
import mimetypes
from pathlib import Path
from typing import Dict, List, Tuple

from pykotor.resource.formats.mdl import mdl_auto
from pygltflib import (
    ARRAY_BUFFER,
    ELEMENT_ARRAY_BUFFER,
    Accessor,
    Asset,
    Buffer,
    BufferView,
    GLTF2,
    Image as GLTFImage,
    Material,
    Mesh,
    Node,
    PbrMetallicRoughness,
    Skin,
    Primitive,
    Scene,
    Texture,
)
from TextureLookup import TextureLookup


def align4(data: bytearray) -> None:
    """Pad the buffer to a 4-byte boundary."""
    while len(data) % 4:
        data.append(0)


def vec_min_max(vecs: List[Tuple[float, float, float]]) -> Tuple[List[float], List[float]]:
    xs = [v[0] for v in vecs]
    ys = [v[1] for v in vecs]
    zs = [v[2] for v in vecs]
    return [min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]


def pack_floats(vals: List[float]) -> bytes:
    return struct.pack("<" + "f" * len(vals), *vals)


def quat_to_mat(qx: float, qy: float, qz: float, qw: float) -> List[List[float]]:
    """Convert quaternion to 4x4 rotation matrix (no scale)."""
    x2, y2, z2 = qx + qx, qy + qy, qz + qz
    xx, yy, zz = qx * x2, qy * y2, qz * z2
    xy, xz, yz = qx * y2, qx * z2, qy * z2
    wx, wy, wz = qw * x2, qw * y2, qw * z2
    return [
        [1.0 - (yy + zz), xy - wz, xz + wy, 0.0],
        [xy + wz, 1.0 - (xx + zz), yz - wx, 0.0],
        [xz - wy, yz + wx, 1.0 - (xx + yy), 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]


def mat_mul(a: List[List[float]], b: List[List[float]]) -> List[List[float]]:
    """4x4 matrix multiply."""
    out = [[0.0] * 4 for _ in range(4)]
    for i in range(4):
        for j in range(4):
            out[i][j] = (
                a[i][0] * b[0][j]
                + a[i][1] * b[1][j]
                + a[i][2] * b[2][j]
                + a[i][3] * b[3][j]
            )
    return out


def mat_inv_rigid(m: List[List[float]]) -> List[List[float]]:
    """
    Inverse of a rigid transform matrix (rotation + translation, no scale/shear).
    Assumes bottom row is [0,0,0,1].
    """
    # rotation transpose
    r = [[m[0][0], m[1][0], m[2][0]], [m[0][1], m[1][1], m[2][1]], [m[0][2], m[1][2], m[2][2]]]
    t = [m[0][3], m[1][3], m[2][3]]
    inv_t = [
        -(r[0][0] * t[0] + r[0][1] * t[1] + r[0][2] * t[2]),
        -(r[1][0] * t[0] + r[1][1] * t[1] + r[1][2] * t[2]),
        -(r[2][0] * t[0] + r[2][1] * t[1] + r[2][2] * t[2]),
    ]
    return [
        [r[0][0], r[0][1], r[0][2], inv_t[0]],
        [r[1][0], r[1][1], r[1][2], inv_t[1]],
        [r[2][0], r[2][1], r[2][2], inv_t[2]],
        [0.0, 0.0, 0.0, 1.0],
    ]


def mat_to_list(mat: List[List[float]]) -> List[float]:
    """Flatten 4x4 matrix row-major to a list of 16 floats."""
    return [mat[i][j] for i in range(4) for j in range(4)]


def _resolve_texture(
    tex_candidates: List[str],
    search_dirs: List[Path],
    texture_fetcher=None,
) -> Tuple[bytes, str, str] | None:
    """
    Resolve a texture name to image bytes, mime, and name (for embedding).
    Search order:
    1) local files in provided search_dirs (non-recursive, then recursive)
    2) optional texture_fetcher callback(resref) -> dict/tuple
    """
    exts = [".png", ".tga", ".jpg", ".jpeg"]

    # Pre-scan all files in search dirs (non-recursive)
    files: List[Path] = []
    for folder in search_dirs:
        if folder and folder.exists():
            for ext in exts:
                files.extend(folder.glob(f"*{ext}"))

    def normalize(name: str) -> str:
        return name.lower()

    def load_file(path: Path) -> Tuple[bytes, str, str]:
        mime, _ = mimetypes.guess_type(path.name)
        mime = mime or "image/png"
        return path.read_bytes(), mime, path.name

    for tex_name in tex_candidates:
        if not tex_name:
            continue
        stem = Path(tex_name).stem  # strip any accidental ext
        stem_norm = normalize(stem)
        stem_no_num = stem_norm.rstrip("0123456789")

        # Exact first
        for f in files:
            fstem = normalize(f.stem)
            if fstem == stem_norm:
                return load_file(f)

        # Prefix/suffix
        for f in files:
            fstem = normalize(f.stem)
            if fstem.startswith(stem_norm) or stem_norm.startswith(fstem):
                return load_file(f)
            if stem_no_num and (fstem.startswith(stem_no_num) or stem_no_num.startswith(fstem)):
                return load_file(f)

    # Recursive fallback: search dirs depth-first for any matching stem
    for tex_name in tex_candidates:
        stem = Path(tex_name).stem
        stem_norm = normalize(stem)
        stem_no_num = stem_norm.rstrip("0123456789")
        for folder in search_dirs:
            if not folder or not folder.exists():
                continue
            for ext in exts:
                for f in folder.rglob(f"*{ext}"):
                    fstem = normalize(f.stem)
                    if fstem == stem_norm or fstem.startswith(stem_norm) or stem_norm.startswith(fstem):
                        return load_file(f)
                    if stem_no_num and (fstem.startswith(stem_no_num) or stem_no_num.startswith(fstem)):
                        return load_file(f)

    # Custom fetcher (e.g., pull from ERF texture pack)
    if texture_fetcher:
        for tex_name in tex_candidates:
            resref = Path(tex_name).stem
            try:
                fetched = texture_fetcher(resref)
            except Exception:
                fetched = None
            if not fetched:
                continue
            # fetched can be tuple(bytes, mime, name) or dict
            if isinstance(fetched, tuple) and len(fetched) == 3:
                return fetched
            if isinstance(fetched, dict):
                data = fetched.get("data")
                mime = fetched.get("mime", "image/png")
                name = fetched.get("name", f"{resref}.png")
                if data:
                    return data, mime, name
    return None


def build_gltf(mdl_path: Path, mdx_path: Path, out_path: Path, texture_fetcher=None) -> None:
    mdl = mdl_auto.read_mdl(str(mdl_path), source_ext=str(mdx_path))

    gltf = GLTF2(asset=Asset(version="2.0"))
    gltf.scenes = [Scene(nodes=[])]

    buffers: List[Buffer] = []
    buffer_views: List[BufferView] = []
    accessors: List[Accessor] = []
    meshes: List[Mesh] = []
    materials: List[Material] = []
    textures: List[Texture] = []
    images: List[GLTFImage] = []
    nodes: List[Node] = []
    skins: List[Skin] = []

    bin_data = bytearray()

    # Map MDL mesh nodes -> glTF mesh indices
    mesh_index_map: Dict[int, int] = {}
    material_cache: Dict[str, int] = {}
    mesh_export_count = 0
    node_index_map: Dict[int, int] = {}
    world_mats: Dict[int, List[List[float]]] = {}

    # ------------------------------------------------------------------
    # Build meshes and buffer data
    # ------------------------------------------------------------------
    for mdl_node in mdl.all_nodes():
        mesh = mdl_node.mesh
        if mesh is None:
            continue

        # Positions
        positions = [(v.x, v.y, v.z) for v in mesh.vertex_positions]
        pos_bytes = pack_floats([c for v in positions for c in v])
        pos_offset = len(bin_data)
        bin_data += pos_bytes
        align4(bin_data)
        pos_bv_index = len(buffer_views)
        buffer_views.append(
            BufferView(
                buffer=0,
                byteOffset=pos_offset,
                byteLength=len(pos_bytes),
                target=ARRAY_BUFFER,
            )
        )
        pos_min, pos_max = vec_min_max(positions)
        pos_acc_index = len(accessors)
        accessors.append(
            Accessor(
                bufferView=pos_bv_index,
                byteOffset=0,
                componentType=5126,  # FLOAT
                count=len(positions),
                type="VEC3",
                min=pos_min,
                max=pos_max,
            )
        )

        # Normals (optional)
        attr_norm = None
        if mesh.vertex_normals:
            normals = [(v.x, v.y, v.z) for v in mesh.vertex_normals]
            norm_bytes = pack_floats([c for v in normals for c in v])
            norm_offset = len(bin_data)
            bin_data += norm_bytes
            align4(bin_data)
            norm_bv_index = len(buffer_views)
            buffer_views.append(
                BufferView(
                    buffer=0,
                    byteOffset=norm_offset,
                    byteLength=len(norm_bytes),
                    target=ARRAY_BUFFER,
                )
            )
            norm_acc_index = len(accessors)
            accessors.append(
                Accessor(
                    bufferView=norm_bv_index,
                    byteOffset=0,
                    componentType=5126,  # FLOAT
                    count=len(normals),
                    type="VEC3",
                )
            )
            attr_norm = norm_acc_index

        # UVs (vertex_uv1)
        attr_uv = None
        if mesh.vertex_uv1:
            # Flip V to match glTF/Blender convention (KOTOR UV origin differs)
            uvs = [(v.x, 1.0 - v.y) for v in mesh.vertex_uv1]
            uv_bytes = pack_floats([c for v in uvs for c in v])
            uv_offset = len(bin_data)
            bin_data += uv_bytes
            align4(bin_data)
            uv_bv_index = len(buffer_views)
            buffer_views.append(
                BufferView(
                    buffer=0,
                    byteOffset=uv_offset,
                    byteLength=len(uv_bytes),
                    target=ARRAY_BUFFER,
                )
            )
            uv_acc_index = len(accessors)
            accessors.append(
                Accessor(
                    bufferView=uv_bv_index,
                    byteOffset=0,
                    componentType=5126,  # FLOAT
                    count=len(uvs),
                    type="VEC2",
                )
            )
            attr_uv = uv_acc_index

        # Indices
        indices = []
        for f in mesh.faces:
            indices.extend([f.v1, f.v2, f.v3])
        max_index = max(indices) if indices else 0
        use_uint16 = max_index < 65535
        idx_fmt = "<" + ("H" if use_uint16 else "I") * len(indices)
        idx_bytes = struct.pack(idx_fmt, *indices)
        idx_offset = len(bin_data)
        bin_data += idx_bytes
        align4(bin_data)
        idx_bv_index = len(buffer_views)
        buffer_views.append(
            BufferView(
                buffer=0,
                byteOffset=idx_offset,
                byteLength=len(idx_bytes),
                target=ELEMENT_ARRAY_BUFFER,
            )
        )
        idx_acc_index = len(accessors)
        accessors.append(
            Accessor(
                bufferView=idx_bv_index,
                byteOffset=0,
                componentType=5123 if use_uint16 else 5125,  # UNSIGNED_SHORT / UNSIGNED_INT
                count=len(indices),
                type="SCALAR",
            )
        )

        attributes = {"POSITION": pos_acc_index}
        if attr_norm is not None:
            attributes["NORMAL"] = attr_norm
        if attr_uv is not None:
            attributes["TEXCOORD_0"] = attr_uv

        # Material lookup by texture name(s)
        mat_index = None
        tex_candidates = []
        for tn in (
            getattr(mesh, "texture_1", "") or "",
            getattr(mesh, "texture_2", "") or "",
            getattr(mdl_node, "name", "") or "",
        ):
            tn = tn.strip()
            if tn:
                tex_candidates.append(tn)

        if tex_candidates:
            tex_key = tex_candidates[0]
            if tex_key not in material_cache:
                # Optional image hookup if a matching file exists nearby
                img_index = None
                tex_info = _resolve_texture(
                    tex_candidates,
                    [
                        mdl_path.parent,
                        out_path.parent,
                        out_path.parent.parent / "PNG" / out_path.parent.name,
                        out_path.parent.parent / "png" / out_path.parent.name,
                    ],
                    texture_fetcher=texture_fetcher,
                )
                if tex_info:
                    img_bytes, mime, img_name = tex_info
                    data_uri = f"data:{mime};base64,{base64.b64encode(img_bytes).decode('ascii')}"
                    images.append(GLTFImage(uri=data_uri, name=img_name))
                    textures.append(Texture(source=len(images) - 1))
                    img_index = len(textures) - 1

                m = Material(
                    name=tex_key,
                    pbrMetallicRoughness=PbrMetallicRoughness(
                        baseColorTexture={"index": img_index} if img_index is not None else None,
                        metallicFactor=0.0,
                        roughnessFactor=1.0,
                    ),
                    extras={"texture": tex_candidates},
                )
                material_cache[tex_key] = len(materials)
                materials.append(m)
            mat_index = material_cache.get(tex_key)

        primitive = Primitive(attributes=attributes, indices=idx_acc_index, material=mat_index)
        gltf_mesh = Mesh(primitives=[primitive], name=mdl_node.name)
        mesh_index = len(meshes)
        meshes.append(gltf_mesh)
        mesh_index_map[id(mdl_node)] = mesh_index
        mesh_export_count += 1

    # ------------------------------------------------------------------
    # Build node hierarchy
    # ------------------------------------------------------------------
    def add_node(mdl_node, parent_world: List[List[float]]) -> int:
        node_index = len(nodes)
        node = Node()
        node.name = mdl_node.name
        node.translation = [mdl_node.position.x, mdl_node.position.y, mdl_node.position.z]
        # orientation is stored as quaternion (x, y, z, w)
        node.rotation = [
            mdl_node.orientation.x,
            mdl_node.orientation.y,
            mdl_node.orientation.z,
            mdl_node.orientation.w,
        ]

        if mdl_node.mesh is not None:
            node.mesh = mesh_index_map.get(id(mdl_node))

        # Build local/world transforms (no scale assumed)
        rot_mat = quat_to_mat(
            mdl_node.orientation.x,
            mdl_node.orientation.y,
            mdl_node.orientation.z,
            mdl_node.orientation.w,
        )
        local = [
            [rot_mat[0][0], rot_mat[0][1], rot_mat[0][2], node.translation[0]],
            [rot_mat[1][0], rot_mat[1][1], rot_mat[1][2], node.translation[1]],
            [rot_mat[2][0], rot_mat[2][1], rot_mat[2][2], node.translation[2]],
            [0.0, 0.0, 0.0, 1.0],
        ]
        world = mat_mul(parent_world, local)

        nodes.append(node)
        node_index_map[id(mdl_node)] = node_index
        world_mats[id(mdl_node)] = world

        # children
        child_indices = []
        for child in mdl_node.children:
            child_indices.append(add_node(child, world))
        if child_indices:
            nodes[node_index].children = child_indices
        return node_index

    identity = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]

    root_index = add_node(mdl.root, identity)
    gltf.scenes[0].nodes = [root_index]

    # Map glTF node index -> world matrix for skinning
    gltf_world = {idx: world_mats[node_id] for node_id, idx in node_index_map.items()}

    # ------------------------------------------------------------------
    # Skins (bones/weights) disabled by request
    # ------------------------------------------------------------------
    skins = []

    # ------------------------------------------------------------------
    # Finalize buffers
    # ------------------------------------------------------------------
    buffers.append(Buffer(byteLength=len(bin_data)))
    gltf.buffers = buffers
    gltf.bufferViews = buffer_views
    gltf.accessors = accessors
    gltf.meshes = meshes or []
    # Ensure lists are present (Blender importer expects arrays, not null)
    gltf.materials = materials or []
    gltf.textures = textures or []
    gltf.images = images or []
    gltf.nodes = nodes or []
    gltf.skins = skins or []

    # Embed buffer data (GLB)
    gltf.set_binary_blob(bytes(bin_data))
    gltf.save_binary(str(out_path))
    print(f"Saved GLB: {out_path}")
    print(
        f"Summary: nodes={len(nodes)}, mesh_nodes={mesh_export_count}, "
        f"meshes={len(meshes)}, accessors={len(accessors)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert KOTOR MDL/MDX to glTF (GLB). First arg MUST be the .mdl (or .mdx if you only have that; we will resolve the .mdl next to it)."
    )
    parser.add_argument("mdl", type=Path, help="Path to .mdl file (or .mdx; see notes)")
    parser.add_argument("mdx", nargs="?", type=Path, help="Path to .mdx file (defaults to same basename)")
    parser.add_argument("-o", "--out", type=Path, help="Output .glb path")
    parser.add_argument(
        "--game",
        type=Path,
        help="Game root to resolve textures (TexturePacks ERFs first, then patch.erf).",
    )
    args = parser.parse_args()

    mdl_path = args.mdl
    mdx_path = args.mdx

    # Allow user to pass mdx as first arg by mistake; resolve mdl beside it.
    if mdl_path.suffix.lower() == ".mdx" and mdx_path is None:
        mdx_path = mdl_path
        mdl_path = mdl_path.with_suffix(".mdl")

    if mdl_path.suffix.lower() != ".mdl":
        raise ValueError("First argument should be the .mdl file (or .mdx so we can find the matching .mdl).")

    mdx_path = mdx_path or mdl_path.with_suffix(".mdx")
    out_path = args.out or mdl_path.with_suffix(".glb")

    if not mdl_path.exists():
        raise FileNotFoundError(mdl_path)
    if not mdx_path.exists():
        raise FileNotFoundError(mdx_path)

    texture_fetcher = None
    if args.game:
        try:
            tex_lookup = TextureLookup(args.game)
            texture_fetcher = tex_lookup.fetch_texture
            print(f"Texture lookup enabled (TexturePacks -> patch.erf) from {args.game}")
        except Exception as exc:
            print(f"Failed to initialize texture lookup: {exc}")

    build_gltf(mdl_path, mdx_path, out_path, texture_fetcher=texture_fetcher)


if __name__ == "__main__":
    main()
