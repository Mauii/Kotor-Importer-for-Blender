# -*- coding: ascii -*-
from __future__ import annotations

import os
import sys
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty, IntProperty, CollectionProperty
from bpy.types import Operator, Panel, UIList, PropertyGroup
from bpy_extras.io_utils import ImportHelper
from mathutils import Matrix, Quaternion, Vector

# ----------------------------------------------------------------------
# Ensure bundled dependencies are on the import path
# ----------------------------------------------------------------------
ADDON_DIR = os.path.dirname(__file__)
if ADDON_DIR not in sys.path:
    sys.path.append(ADDON_DIR)

# Path to the bundled extractor tools (now stored inside the add-on directory)
EXTRACTOR_DIR_CANDIDATES = [
    Path(ADDON_DIR) / "kotor extractor",
    Path(ADDON_DIR) / "extractor",
]
DEFAULT_EXTRACTOR_DIR = next((p for p in EXTRACTOR_DIR_CANDIDATES if p.exists()), EXTRACTOR_DIR_CANDIDATES[0])
for _extractor_path in [DEFAULT_EXTRACTOR_DIR] + [p for p in EXTRACTOR_DIR_CANDIDATES if p != DEFAULT_EXTRACTOR_DIR]:
    if _extractor_path.exists() and str(_extractor_path) not in sys.path:
        sys.path.append(str(_extractor_path))

# Simple debug logger
DEBUG_LOG = True

def _debug(msg: str) -> None:
    if DEBUG_LOG:
        print(f"[KOTOR IMPORT DEBUG] {msg}")

try:
    from pykotor.resource.formats.mdl.io_mdl import MDLBinaryReader
    from pykotor.common.misc import Game
    from pykotor.resource.formats.mdl.mdl_data import (
        MDL,
        MDLBoneVertex,
        MDLLight,
        MDLMesh,
        MDLNode,
        MDLSkin,
    )

    PYKOTOR_ERROR: Optional[Exception] = None
    PYKOTOR_AVAILABLE = True
except Exception as exc:  # pragma: no cover - safety for Blender runtime
    MDLBinaryReader = None  # type: ignore
    Game = None  # type: ignore
    MDL = MDLBoneVertex = MDLLight = MDLMesh = MDLNode = MDLSkin = None  # type: ignore
    PYKOTOR_ERROR = exc
    PYKOTOR_AVAILABLE = False

# PyKotor's MDLNode __hash__ implementation relies on Vector4 which is unhashable in Blender's mathutils.
# Override to use object identity so we can store nodes in dicts/sets safely.
if PYKOTOR_AVAILABLE and MDLNode is not None:  # pragma: no cover - runtime side effect
    try:
        MDLNode.__hash__ = object.__hash__  # type: ignore[attr-defined,assignment]
    except Exception:
        pass


# ----------------------------------------------------------------------
# Add-on info
# ----------------------------------------------------------------------
bl_info = {
    "name": "KotOR MDL/MDX Importer",
    "author": "ChatGPT + Maui",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "File > Import > KotOR MDL (.mdl/.mdx)",
    "description": "Imports KotOR/KotOR2 MDL (binary) with companion MDX geometry, building meshes, armature, weights and textures.",
    "category": "Import-Export",
}


# ----------------------------------------------------------------------
# Utility helpers
# ----------------------------------------------------------------------
def _unique_name(base: str, seen: set[str]) -> str:
    name = base or "node"
    cleaned = bpy.path.clean_name(name)
    if cleaned not in seen:
        seen.add(cleaned)
        return cleaned

    idx = 1
    while f"{cleaned}_{idx}" in seen:
        idx += 1
    final = f"{cleaned}_{idx}"
    seen.add(final)
    return final


def _vec3(v) -> Vector:
    return Vector((float(v.x), float(v.y), float(v.z)))


def _quat(v) -> Quaternion:
    # MDL stores quaternion as (x, y, z, w)
    return Quaternion((float(v.w), float(v.x), float(v.y), float(v.z)))


def _local_matrix(node: MDLNode) -> Matrix:
    trans = Matrix.Translation(_vec3(node.position))
    rot = _quat(node.orientation).to_matrix().to_4x4()
    return trans @ rot


def _compute_world_maps(root: MDLNode) -> Tuple[Dict[MDLNode, Matrix], Dict[MDLNode, Optional[MDLNode]], List[MDLNode]]:
    world: Dict[MDLNode, Matrix] = {}
    parents: Dict[MDLNode, Optional[MDLNode]] = {}
    order: List[MDLNode] = []

    def walk(node: MDLNode, parent: Optional[MDLNode], parent_mat: Matrix) -> None:
        parents[node] = parent
        mat = parent_mat @ _local_matrix(node)
        world[node] = mat
        order.append(node)
        for child in node.children:
            walk(child, node, mat)

    walk(root, None, Matrix.Identity(4))
    return world, parents, order


def _build_node_names(nodes: List[MDLNode]) -> Dict[MDLNode, str]:
    seen: set[str] = set()
    mapping: Dict[MDLNode, str] = {}
    for node in nodes:
        base = node.name.strip() if getattr(node, "name", "") else ""
        fallback = f"node_{node.node_id}" if getattr(node, "node_id", -1) >= 0 else "node"
        mapping[node] = _unique_name(base or fallback, seen)
    return mapping


def _apply_uv_layer(mesh: bpy.types.Mesh, uv_data: List, layer_name: str) -> None:
    if not uv_data:
        return
    uv_layer = mesh.uv_layers.new(name=layer_name)
    for loop in mesh.loops:
        uv = uv_data[loop.vertex_index]
        uv_layer.data[loop.index].uv = (float(uv.x), float(uv.y))


def _apply_normals(mesh: bpy.types.Mesh, normals: Optional[List]) -> None:
    if not normals:
        return
    mesh.normals_split_custom_set_from_vertices([_vec3(n).normalized() for n in normals])


def _resolve_bone_name(idx_val: float, skin: MDLSkin, bone_name_by_id: Dict[int, str]) -> Optional[str]:
    try:
        idx = int(idx_val)
    except (TypeError, ValueError):
        return None
    if idx < 0:
        return None

    # First try the bonemap (preferred)
    if skin.bonemap and idx < len(skin.bonemap):
        bone_id = int(skin.bonemap[idx])
        name = bone_name_by_id.get(bone_id)
        if name:
            return name

    # Fall back to fixed bone_indices array
    if skin.bone_indices and idx < len(skin.bone_indices):
        bone_id = int(skin.bone_indices[idx])
        name = bone_name_by_id.get(bone_id)
        if name:
            return name

    # As a last resort assume the index itself is a node id
    return bone_name_by_id.get(idx)


def _add_skin_weights(
    obj: bpy.types.Object,
    skin: MDLSkin,
    bone_name_by_id: Dict[int, str],
) -> None:
    if not skin.vertex_bones:
        return

    for vert_index, bone_data in enumerate(skin.vertex_bones):
        for idx_val, weight in zip(bone_data.vertex_indices, bone_data.vertex_weights):
            if weight is None or weight <= 0.0:
                continue
            bone_name = _resolve_bone_name(idx_val, skin, bone_name_by_id)
            if not bone_name:
                continue
            group = obj.vertex_groups.get(bone_name)
            if group is None:
                group = obj.vertex_groups.new(name=bone_name)
            group.add([vert_index], float(weight), "ADD")


def _find_texture_file(tex_name: str, texture_root: Optional[Path]) -> Optional[Path]:
    """
    Try to resolve a texture name to an actual file in the supplied root.
    Checks common extensions and performs a case-insensitive fallback scan.
    """
    if not texture_root or not texture_root.exists():
        return None

    stem = Path(tex_name).stem
    preferred = [Path(tex_name), Path(stem)]
    exts = [".png", ".tga", ".dds", ".jpg", ".jpeg", ".bmp", ".tiff"]

    for cand in preferred:
        path_exact = texture_root / cand
        if path_exact.exists():
            return path_exact
        if cand.suffix:
            continue
        for ext in exts:
            candidate = texture_root / f"{cand}{ext}"
            if candidate.exists():
                return candidate

    stem_lower = stem.lower()
    try:
        for file in texture_root.iterdir():
            if file.is_file() and file.stem.lower() == stem_lower:
                return file
    except Exception:
        return None
    return None


def _ensure_material(
    name: str,
    cache: Dict[str, bpy.types.Material],
    texture_root: Optional[Path],
    missing_textures: List[str],
) -> bpy.types.Material:
    """
    Return (or create) a material and hook up an image texture if found.
    """
    # Treat NULL as an intentionally empty texture slot
    if name.strip().upper() == "NULL":
        if name in cache:
            return cache[name]
        mat = bpy.data.materials.new(name="NULL")
        mat.use_nodes = True
        cache[name] = mat
        return mat

    if name in cache:
        return cache[name]

    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True

    nt = mat.node_tree
    if nt:
        nodes = nt.nodes
        links = nt.links
        nodes.clear()

        out_node = nodes.new(type="ShaderNodeOutputMaterial")
        out_node.location = (300, 0)
        principled = nodes.new(type="ShaderNodeBsdfPrincipled")
        principled.location = (0, 0)
        links.new(principled.outputs["BSDF"], out_node.inputs["Surface"])

        tex_path = _find_texture_file(name, texture_root)
        if tex_path:
            try:
                image = bpy.data.images.load(filepath=str(tex_path), check_existing=True)
                tex_node = nodes.new(type="ShaderNodeTexImage")
                tex_node.image = image
                tex_node.location = (-300, 0)
                links.new(tex_node.outputs["Color"], principled.inputs["Base Color"])
                mat["kotor_texture_path"] = str(tex_path)
            except Exception:
                tex_path = None
        else:
            tex_path = None

        if tex_path is None:
            missing_textures.append(name)

    cache[name] = mat
    return mat


# ----------------------------------------------------------------------
# Extractor helpers
# ----------------------------------------------------------------------
def _ensure_extractor_imports():
    for path in [DEFAULT_EXTRACTOR_DIR] + [p for p in EXTRACTOR_DIR_CANDIDATES if p != DEFAULT_EXTRACTOR_DIR]:
        if path.exists() and str(path) not in sys.path:
            sys.path.append(str(path))
    try:
        from ResourceManager import ResourceManager  # noqa: F401
        from ResourceTypes import ResourceTypeInfo  # noqa: F401
    except Exception as exc:
        searched_paths = ", ".join(str(p) for p in EXTRACTOR_DIR_CANDIDATES)
        raise RuntimeError(f"Extractor modules not available (checked: {searched_paths}; default: {DEFAULT_EXTRACTOR_DIR}): {exc}") from exc


def _resolve_key_path(game_path: str) -> Path:
    p = Path(game_path)
    if p.is_dir():
        p = p / "chitin.key"
    return p


def _list_models(key_path: Path) -> List[Tuple[str, bool]]:
    _ensure_extractor_imports()
    from ResourceManager import ResourceManager  # type: ignore

    rm = ResourceManager(key_path=str(key_path))
    buckets: Dict[str, Dict[str, object]] = {}
    for e in rm.key.key_table:
        if e.ResourceType in (2002, 3008):  # mdl / mdx
            key = e.ResRef.lower()
            if key not in buckets:
                buckets[key] = {"name": e.ResRef, "types": set()}
            buckets[key]["types"].add(e.ResourceType)
    models = []
    for entry in buckets.values():
        models.append((entry["name"], 3008 in entry["types"]))  # type: ignore[index]
    models.sort()
    return models


def _gather_textures_from_mdl(mdl_path: Path, mdx_path: Optional[Path]) -> Set[str]:
    textures: Set[str] = set()
    reader = MDLBinaryReader(str(mdl_path), source_ext=str(mdx_path) if mdx_path else None, fast_load=True)
    mdl_obj: MDL = reader.load()
    for node in mdl_obj.all_nodes():
        if node.mesh:
            for tex in (node.mesh.texture_1, node.mesh.texture_2):
                if not tex:
                    continue
                t = tex.strip()
                if not t or t.upper() == "NULL":
                    continue
                textures.add(t)
    return textures


def _convert_to_png(src: Path, dst_dir: Path) -> Path:
    dst = dst_dir / (src.stem + ".png")
    ext = src.suffix.lower()
    if dst.exists():
        return dst
    if ext == ".tpc":
        try:
            _ensure_extractor_imports()
            from TPCToPNG import tpc_to_png  # type: ignore

            return tpc_to_png(src, dst)
        except Exception:
            pass
    try:
        from PIL import Image  # type: ignore
    except Exception:
        shutil.copy(src, dst)
        return dst

    try:
        with Image.open(src) as im:
            im = im.convert("RGBA")
            im.save(dst)
        return dst
    except Exception:
        shutil.copy(src, dst)
    return dst


def _export_textures(
    rm,
    textures: Set[str],
    out_dir: Path,
    override_dir: Optional[Path] = None,
    game_root: Optional[Path] = None,
) -> List[str]:
    _ensure_extractor_imports()
    from ResourceTypes import ResourceTypeInfo  # type: ignore

    out_dir.mkdir(parents=True, exist_ok=True)
    errors: List[str] = []
    override_candidates: List[Path] = []
    erf_paths: List[Path] = []
    erf_cache: Dict[Path, object] = {}
    if override_dir and override_dir.exists():
        try:
            for f in override_dir.iterdir():
                if f.is_file() and f.suffix.lower() in (".tpc", ".tga", ".dds", ".png"):
                    override_candidates.append(f)
        except Exception:
            pass
    if game_root and game_root.exists():
        tp_root = game_root / "TexturePacks"
        preferred = tp_root / "swpc_tex_tpa.erf"
        preferred_root = game_root / "swpc_tex_tpa.erf"
        if preferred.exists():
            erf_paths.append(preferred)
        if preferred_root.exists() and preferred_root not in erf_paths:
            erf_paths.append(preferred_root)
        if tp_root.exists():
            for p in tp_root.glob("*.erf"):
                if p in erf_paths:
                    continue
                erf_paths.append(p)
        for p in game_root.rglob("*.erf"):
            if p in erf_paths:
                continue
            erf_paths.append(p)
        for p in game_root.rglob("*.rim"):
            if p in erf_paths:
                continue
            erf_paths.append(p)

    _debug(f"ERF search order: {[str(p) for p in erf_paths]}")

    def export_from_erf(resref: str, type_id: int) -> Optional[Path]:
        for erf_path in erf_paths:
            try:
                if erf_path not in erf_cache:
                    from ResourceManager import ResourceManager  # type: ignore

                    erf_cache[erf_path] = ResourceManager(erf_path=str(erf_path))
                rm_erf = erf_cache[erf_path]
                entry = rm_erf.get_resource_entry(resref, resource_type=type_id)
                if entry:
                    return Path(rm_erf.export_entry(entry, out_dir))
            except Exception:
                continue
        return None

    for tex in sorted(textures):
        exported = None
        # 1) Try ERFs (TexturePacks preferred)
        if exported is None and erf_paths:
            for ext in ("tpc", "dds", "tga"):
                type_id = ResourceTypeInfo.get_typeid(ext)
                exported = export_from_erf(tex, type_id)
                if exported:
                    _debug(f"Exported from ERF {exported} for {tex}")
                    break

        # 2) Try Override
        if exported is None and override_candidates:
            stem_lower = tex.lower()
            for f in override_candidates:
                if f.stem.lower() == stem_lower:
                    _debug(f"Using Override texture for {tex}: {f}")
                    exported = f
                    break

        # 3) Fall back to BIF via key
        if exported is None:
            for ext in ("tpc", "dds", "tga"):
                type_id = ResourceTypeInfo.get_typeid(ext)
                try:
                    _debug(f"Trying BIF export for {tex}.{ext}")
                    exported = rm.export_resource(tex, out_dir, resource_type=type_id)
                    _debug(f"Exported {tex}.{ext} -> {exported}")
                    break
                except Exception as exc:
                    _debug(f"BIF export failed for {tex}.{ext}: {exc}")
                    exported = None

        if exported is None:
            _debug(f"Missing texture after all attempts: {tex}")
            errors.append(tex)
            continue

        try:
            png_path = _convert_to_png(Path(exported), out_dir)
            if not png_path.exists():
                _debug(f"PNG not found after conversion for {tex}: {png_path}")
                errors.append(tex)
        except Exception as exc:
            _debug(f"Conversion failed for {tex}: {exc}")
            errors.append(tex)
    return errors


# ----------------------------------------------------------------------
# UI data structures
# ----------------------------------------------------------------------
class KotorModelItem(PropertyGroup):
    name: StringProperty()
    resref: StringProperty()
    has_mdx: BoolProperty()


class KOTOR_UL_model_list(UIList):
    def filter_items(self, context, data, propname):
        items = getattr(data, propname)
        flt_flags = []
        flt_neworder = []
        search = (getattr(context.window_manager, "kotor_model_search", "") or "").lower()
        for item in items:
            if search and search not in item.name.lower():
                flt_flags.append(0)
            else:
                flt_flags.append(self.bitflag_filter_item)
        return flt_flags, flt_neworder

    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        row = layout.row()
        row.label(text=item.name)
        if not item.has_mdx:
            row.label(text="MDX missing", icon="ERROR")


class KOTOR_OT_refresh_models(Operator):
    bl_idname = "kotor.refresh_models"
    bl_label = "Refresh Models"
    bl_description = "Read chitin.key/models.bif and list all MDL entries (unique resref)"

    def execute(self, context):
        wm = context.window_manager
        key_path = _resolve_key_path(wm.kotor_game_path)
        if not key_path.exists():
            self.report({"ERROR"}, f"chitin.key not found at {key_path}")
            return {"CANCELLED"}
        try:
            models = _list_models(key_path)
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to list models: {exc}")
            return {"CANCELLED"}

        items = wm.kotor_model_items
        items.clear()
        for resref, has_mdx in models:
            it = items.add()
            it.name = resref
            it.resref = resref
            it.has_mdx = has_mdx
        wm.kotor_model_index = 0 if items else -1
        self.report({"INFO"}, f"Found {len(items)} models")
        return {"FINISHED"}


class KOTOR_OT_import_model(Operator):
    bl_idname = "kotor.import_model"
    bl_label = "Import Selected Model"
    bl_description = "Extract selected model from BIF and import into the scene"

    def execute(self, context):
        wm = context.window_manager
        idx = wm.kotor_model_index
        items = wm.kotor_model_items
        if idx < 0 or idx >= len(items):
            self.report({"ERROR"}, "No model selected")
            return {"CANCELLED"}
        resref = items[idx].resref

        key_path = _resolve_key_path(wm.kotor_game_path)
        if not key_path.exists():
            self.report({"ERROR"}, f"chitin.key not found at {key_path}")
            return {"CANCELLED"}

        game_root = key_path.parent if key_path.is_file() else key_path

        try:
            _ensure_extractor_imports()
            from ResourceManager import ResourceManager  # type: ignore
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        rm = ResourceManager(key_path=str(key_path))
        temp_root = Path(tempfile.mkdtemp(prefix="kotor_import_"))
        mdl_path = None
        mdx_path = None
        try:
            mdl_path = Path(rm.export_resource(resref, temp_root, resource_type=2002))
            try:
                mdx_path = Path(rm.export_resource(resref, temp_root, resource_type=3008))
            except Exception:
                mdx_path = None
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to extract model {resref}: {exc}")
            return {"CANCELLED"}

        texture_names = _gather_textures_from_mdl(mdl_path, mdx_path)
        tex_dir = temp_root / "textures"
        override_dir = game_root / "Override" if game_root and game_root.is_dir() else None
        missing_tex = _export_textures(rm, texture_names, tex_dir, override_dir=override_dir, game_root=game_root)
        wm.kotor_last_tex_dir = str(tex_dir)

        try:
            bpy.ops.import_scene.kotor_mdl(
                filepath=str(mdl_path),
                texture_root=str(tex_dir),
                game=context.window_manager.kotor_game,
                import_walkmesh=context.window_manager.kotor_import_walkmesh,
                import_nonrender_meshes=context.window_manager.kotor_import_nonrender_meshes,
            )
        except Exception as exc:
            self.report({"ERROR"}, f"Import failed: {exc}")
            return {"CANCELLED"}

        if missing_tex:
            self.report({"WARNING"}, f"Imported {resref}, missing {len(missing_tex)} textures: {', '.join(missing_tex[:5])}" + ("..." if len(missing_tex) > 5 else ""))
        else:
            self.report({"INFO"}, f"Imported {resref}")
        return {"FINISHED"}


class KOTOR_OT_copy_textures(Operator):
    bl_idname = "kotor.copy_textures"
    bl_label = "Save Textures"
    bl_description = "Copy last extracted textures (PNG) into the chosen folder"

    def execute(self, context):
        wm = context.window_manager
        src = Path(wm.kotor_last_tex_dir) if wm.kotor_last_tex_dir else None
        dst = Path(wm.kotor_texture_save_dir) if wm.kotor_texture_save_dir else None
        if not src or not src.exists():
            self.report({"ERROR"}, "No textures extracted yet. Import a model first.")
            return {"CANCELLED"}
        if not dst:
            self.report({"ERROR"}, "Set a target folder first.")
            return {"CANCELLED"}

        try:
            dst.mkdir(parents=True, exist_ok=True)
            copied = 0
            for f in src.glob("*.png"):
                shutil.copy(f, dst / f.name)
                copied += 1
            self.report({"INFO"}, f"Copied {copied} textures to {dst}")
        except Exception as exc:
            self.report({"ERROR"}, f"Failed to copy textures: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


class KOTOR_PT_import_panel(Panel):
    bl_label = "KotOR Import"
    bl_category = "KotOR Import"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"

    def draw(self, context):
        wm = context.window_manager
        layout = self.layout

        layout.prop(wm, "kotor_game_path", text="Game Path")
        layout.operator("kotor.refresh_models", icon="FILE_REFRESH")

        layout.prop(wm, "kotor_model_search", text="Search")
        layout.template_list(
            "KOTOR_UL_model_list",
            "",
            wm,
            "kotor_model_items",
            wm,
            "kotor_model_index",
            rows=8,
        )

        layout.label(text="Import Options")
        layout.prop(wm, "kotor_game", expand=True)
        layout.prop(wm, "kotor_import_walkmesh")
        layout.prop(wm, "kotor_import_nonrender_meshes")

        layout.operator("kotor.import_model", icon="IMPORT")

        layout.separator()
        layout.label(text="Save Textures")
        layout.prop(wm, "kotor_texture_save_dir")
        row = layout.row()
        row.enabled = bool(wm.kotor_last_tex_dir)
        row.operator("kotor.copy_textures", icon="FILE_FOLDER")


# ----------------------------------------------------------------------
# Scene construction helpers
# ----------------------------------------------------------------------
def _create_armature(
    nodes: List[MDLNode],
    world: Dict[MDLNode, Matrix],
    parents: Dict[MDLNode, Optional[MDLNode]],
    names: Dict[MDLNode, str],
    collection: bpy.types.Collection,
    armature_name: str,
) -> bpy.types.Object:
    arm_data = bpy.data.armatures.new(f"{armature_name}_Armature")
    arm_obj = bpy.data.objects.new(f"{armature_name}_Armature", arm_data)
    collection.objects.link(arm_obj)

    # Preserve the active object to restore later
    view_layer = bpy.context.view_layer
    prev_active = view_layer.objects.active
    view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")

    bone_map: Dict[MDLNode, bpy.types.EditBone] = {}
    for node in nodes:
        bone = arm_data.edit_bones.new(names[node])
        bone_map[node] = bone
        head = world[node].to_translation()
        orient = world[node].to_quaternion()
        tail_offset = orient @ Vector((0.0, 0.1, 0.0))
        if tail_offset.length < 1e-4:
            tail_offset = Vector((0.0, 0.1, 0.0))
        bone.head = head
        bone.tail = head + tail_offset

    for node in nodes:
        parent = parents.get(node)
        if parent and parent in bone_map:
            bone_map[node].parent = bone_map[parent]

    bpy.ops.object.mode_set(mode="OBJECT")
    view_layer.objects.active = prev_active
    return arm_obj


def _build_empty_hierarchy(
    nodes: List[MDLNode],
    world: Dict[MDLNode, Matrix],
    parents: Dict[MDLNode, Optional[MDLNode]],
    names: Dict[MDLNode, str],
    collection: bpy.types.Collection,
) -> Dict[MDLNode, bpy.types.Object]:
    return {}


def _create_light_for_node(
    node: MDLNode,
    world: Dict[MDLNode, Matrix],
    names: Dict[MDLNode, str],
    collection: bpy.types.Collection,
    parent_obj: Optional[bpy.types.Object],
) -> None:
    if node.light is None:
        return
    light_data = bpy.data.lights.new(f"{names[node]}_Light", type="POINT")
    light_obj = bpy.data.objects.new(f"{names[node]}_Light", light_data)
    light_obj.matrix_world = world[node]
    if isinstance(node.light, MDLLight):
        energy = max(1.0, float(node.light.flare_radius) * 10.0)
        light_data.energy = energy
    if parent_obj:
        light_obj.parent = parent_obj
    collection.objects.link(light_obj)


def _create_mesh_object(
    node: MDLNode,
    world: Dict[MDLNode, Matrix],
    names: Dict[MDLNode, str],
    collection: bpy.types.Collection,
    materials_cache: Dict[str, bpy.types.Material],
    armature_obj: Optional[bpy.types.Object],
    bone_name_by_id: Dict[int, str],
    texture_root: Optional[Path],
    missing_textures: List[str],
    is_collision: bool = False,
    allow_nonrender: bool = False,
) -> Optional[bpy.types.Object]:
    if node.mesh is None:
        return None

    mesh_data: MDLMesh = node.mesh
    if (not mesh_data.render or mesh_data.background_geometry) and not is_collision and not allow_nonrender:
        return None

    obj_name = f"{names[node]}_Mesh"
    mesh = bpy.data.meshes.new(obj_name)

    # Bake node transform into vertex positions so armature and geometry share object space.
    mat = world[node]
    verts = [mat @ _vec3(v) for v in mesh_data.vertex_positions]
    faces = [(f.v1, f.v2, f.v3) for f in mesh_data.faces]
    mesh.from_pydata(verts, [], faces)

    _apply_normals(mesh, mesh_data.vertex_normals)
    if mesh_data.vertex_uv1:
        _apply_uv_layer(mesh, mesh_data.vertex_uv1, "UVMap")
    if mesh_data.vertex_uv2:
        _apply_uv_layer(mesh, mesh_data.vertex_uv2, "UV2")

    mesh.validate()
    obj = bpy.data.objects.new(obj_name, mesh)
    obj.matrix_world = Matrix.Identity(4)

    def _with_png(tex: str) -> str:
        return tex if Path(tex).suffix else f"{tex}.png"

    # Basic materials based on texture names
    if mesh_data.texture_1:
        mat = _ensure_material(mesh_data.texture_1, materials_cache, texture_root, missing_textures)
        obj.data.materials.append(mat)
        mat["kotor_texture1"] = _with_png(mesh_data.texture_1)
    if mesh_data.texture_2:
        mat = _ensure_material(mesh_data.texture_2, materials_cache, texture_root, missing_textures)
        obj.data.materials.append(mat)
        mat["kotor_texture2"] = _with_png(mesh_data.texture_2)

    # Skinning
    if node.skin and armature_obj:
        _add_skin_weights(obj, node.skin, bone_name_by_id)
        modifier = obj.modifiers.new(name="KotOR Armature", type="ARMATURE")
        modifier.object = armature_obj

    collection.objects.link(obj)
    if is_collision:
        obj["kotor_walkmesh"] = True
    return obj


# ----------------------------------------------------------------------
# Blender Operator
# ----------------------------------------------------------------------
class IMPORT_SCENE_OT_kotor_mdl(Operator, ImportHelper):
    """Import KotOR/KotOR2 binary MDL with MDX geometry"""

    bl_idname = "import_scene.kotor_mdl"
    bl_label = "Import KotOR MDL/MDX"
    bl_options = {"UNDO"}

    filename_ext = ".mdl"
    filter_glob: StringProperty(
        default="*.mdl",
        options={"HIDDEN"},
        maxlen=255,
    )

    game: EnumProperty(
        name="Game",
        description="Choose the game variant for parsing",
        items=(
            ("K1", "KotOR 1", "Parse as KotOR 1 model"),
            ("K2", "KotOR 2", "Parse as KotOR 2 model"),
        ),
        default="K2",
    )

    texture_root: StringProperty(
        name="Texture Folder",
        description="Folder to search for texture images (TGA/DDS/PNG/JPG). Leave blank to skip loading images.",
        subtype="DIR_PATH",
        default="",
    )

    import_walkmesh: BoolProperty(
        name="Import Walkmesh (Collision)",
        description="Import AABB walkmesh/collision geometry into a separate collection.",
        default=True,
    )

    import_nonrender_meshes: BoolProperty(
        name="Import Non-render meshes",
        description="Include meshes flagged as non-render/background (often simplified/auxiliary).",
        default=False,
    )

    texture_save_dir: StringProperty(
        name="Texture Save Folder",
        description="Optional folder to copy/convert extracted textures into (in addition to the temp cache).",
        subtype="DIR_PATH",
        default="",
    )
    last_tex_dir: StringProperty(
        name="Last Texture Cache",
        description="Internal: last extracted texture cache folder",
        default="",
        options={"HIDDEN"},
    )

    def execute(self, context):
        if not PYKOTOR_AVAILABLE or MDLBinaryReader is None or Game is None:
            self.report({"ERROR"}, f"Bundled PyKotor could not be loaded: {PYKOTOR_ERROR}")
            return {"CANCELLED"}

        mdl_path = Path(self.filepath)
        mdx_path = mdl_path.with_suffix(".mdx")
        if not mdl_path.exists():
            self.report({"ERROR"}, f"MDL file not found: {mdl_path}")
            return {"CANCELLED"}
        if not mdx_path.exists():
            self.report({"WARNING"}, f"Companion MDX not found: {mdx_path.name}. Importing MDL only.")

        # Default texture lookup folder: user-provided path or the MDL's directory
        texture_root = Path(self.texture_root) if self.texture_root else mdl_path.parent
        if texture_root and not texture_root.exists():
            texture_root = None

        try:
            reader = MDLBinaryReader(
                str(mdl_path),
                source_ext=str(mdx_path) if mdx_path.exists() else None,
                game=Game.K2 if self.game == "K2" else Game.K1,
                fast_load=True,
            )
            mdl: MDL = reader.load()
        except Exception as exc:  # pragma: no cover - runtime error reporting
            self.report({"ERROR"}, f"Failed to read MDL/MDX: {exc}")
            return {"CANCELLED"}

        all_nodes = mdl.all_nodes()
        for node in all_nodes:
            if node.skin:
                node.skin.prepare_bone_lookups(all_nodes)

        world, parents, nodes = _compute_world_maps(mdl.root)
        names = _build_node_names(nodes)
        node_id_name: Dict[int, str] = {
            node.node_id: names[node] for node in nodes if getattr(node, "node_id", -1) >= 0
        }

        coll_name = f"MDL_{mdl.name or mdl_path.stem}"
        collection = bpy.data.collections.new(coll_name)
        context.scene.collection.children.link(collection)

        collision_collection: Optional[bpy.types.Collection] = None

        empties: Dict[MDLNode, bpy.types.Object] = {}

        needs_armature = any(node.skin for node in nodes)
        armature_obj = None
        if needs_armature:
            armature_obj = _create_armature(nodes, world, parents, names, collection, coll_name)

        materials_cache: Dict[str, bpy.types.Material] = {}
        missing_textures: List[str] = []
        for node in nodes:
            is_walkmesh = bool(getattr(node, "aabb", None))
            target_collection = collection
            if is_walkmesh and self.import_walkmesh:
                if collision_collection is None:
                    collision_collection = bpy.data.collections.new(f"{coll_name}_Collision")
                    context.scene.collection.children.link(collision_collection)
                target_collection = collision_collection
            elif is_walkmesh and not self.import_walkmesh:
                continue

            mesh_obj = _create_mesh_object(
                node,
                world,
                names,
                target_collection,
                materials_cache,
                armature_obj,
                node_id_name,
                texture_root,
                missing_textures,
                is_collision=is_walkmesh,
                allow_nonrender=self.import_nonrender_meshes,
            )
            if mesh_obj is None:
                continue
            _create_light_for_node(node, world, names, target_collection, None)

        if missing_textures:
            uniq_missing = sorted(set(missing_textures))
            self.report({"WARNING"}, f"Missing {len(uniq_missing)} textures in folder: {', '.join(uniq_missing[:6])}" + ("..." if len(uniq_missing) > 6 else ""))

        self.report({"INFO"}, f"Imported {coll_name} ({len(nodes)} nodes)")
        return {"FINISHED"}


# ----------------------------------------------------------------------
# Registration
# ----------------------------------------------------------------------
classes = (
    KotorModelItem,
    KOTOR_UL_model_list,
    KOTOR_OT_refresh_models,
    KOTOR_OT_import_model,
    KOTOR_OT_copy_textures,
    KOTOR_PT_import_panel,
    IMPORT_SCENE_OT_kotor_mdl,
)


def menu_func_import(self, context):
    self.layout.operator(IMPORT_SCENE_OT_kotor_mdl.bl_idname, text="KotOR MDL (.mdl)")


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)

    bpy.types.WindowManager.kotor_game_path = StringProperty(
        name="Game Path",
        subtype="DIR_PATH",
        default="",
    )
    bpy.types.WindowManager.kotor_model_search = StringProperty(
        name="Search",
        default="",
    )
    bpy.types.WindowManager.kotor_model_items = CollectionProperty(type=KotorModelItem)
    bpy.types.WindowManager.kotor_model_index = IntProperty(default=-1)
    bpy.types.WindowManager.kotor_game = EnumProperty(
        name="Game",
        items=(
            ("K1", "KotOR 1", ""),
            ("K2", "KotOR 2", ""),
        ),
        default="K2",
    )
    bpy.types.WindowManager.kotor_import_walkmesh = BoolProperty(
        name="Import Walkmesh",
        default=True,
    )
    bpy.types.WindowManager.kotor_import_nonrender_meshes = BoolProperty(
        name="Import Non-render meshes",
        default=False,
    )
    bpy.types.WindowManager.kotor_texture_save_dir = StringProperty(
        name="Texture Save Folder",
        subtype="DIR_PATH",
        default="",
    )
    bpy.types.WindowManager.kotor_last_tex_dir = StringProperty(
        name="Last Texture Cache",
        default="",
    )


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.WindowManager.kotor_game_path
    del bpy.types.WindowManager.kotor_model_search
    del bpy.types.WindowManager.kotor_model_items
    del bpy.types.WindowManager.kotor_model_index
    del bpy.types.WindowManager.kotor_game
    del bpy.types.WindowManager.kotor_import_walkmesh
    del bpy.types.WindowManager.kotor_import_nonrender_meshes
    del bpy.types.WindowManager.kotor_texture_save_dir
    del bpy.types.WindowManager.kotor_last_tex_dir


if __name__ == "__main__":
    register()
