from __future__ import annotations

bl_info = {
    "name": "Import Game GLM (text)",
    "author": "OpenAI",
    "version": (0, 3, 0),
    "blender": (3, 3, 0),
    "location": "File > Import > Game GLM (.glm)",
    "description": "Import plain-text .glm geometry with LODs, UVs, vertex colors, materials, skeleton and skin weights.",
    "category": "Import-Export",
}

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import bpy  # type: ignore
    from mathutils import Matrix, Vector  # type: ignore
    from bpy.props import BoolProperty, IntProperty, StringProperty  # type: ignore
    from bpy_extras.io_utils import ImportHelper  # type: ignore
except Exception:  # pragma: no cover - allows parser to run outside Blender
    bpy = None
    Matrix = None
    Vector = None
    ImportHelper = object
    def BoolProperty(**kwargs):  # type: ignore
        return None
    def StringProperty(**kwargs):  # type: ignore
        return None
    def IntProperty(**kwargs):  # type: ignore
        return None


_TOKEN_RE = re.compile(r'"[^"]*"|\S+')
_LOD_RE = re.compile(r"(?:^|_)(LOD)(\d+)$", re.IGNORECASE)


def split_tokens(line: str) -> List[str]:
    tokens = _TOKEN_RE.findall(line)
    return [t[1:-1] if len(t) >= 2 and t[0] == '"' and t[-1] == '"' else t for t in tokens]


@dataclass
class MaterialRef:
    shader: str = ""
    shaderrefid: str = ""
    slotname: str = ""


@dataclass
class BoneDef:
    name: str = ""
    parent: str = ""
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # axis-angle
    scale: Tuple[float, float, float] = (1.0, 1.0, 1.0)


@dataclass
class MeshFace:
    index: int
    verts: Tuple[int, int, int]
    normal_indices: Tuple[int, int, int]
    uv_indices: List[Tuple[int, int, int]]
    face_flag: int
    material_id: int
    color_indices: Dict[int, Tuple[int, int, int]] = field(default_factory=dict)


@dataclass
class MeshDef:
    name: str = ""
    mesh_state_index: int = -1
    num_tvertex_channels: int = 0
    num_cvertex_channels: int = 0
    face_uv_channel_count: int = 0
    vertices: List[Tuple[float, float, float]] = field(default_factory=list)
    normals: List[Tuple[float, float, float]] = field(default_factory=list)
    tvert_channels: List[List[Tuple[float, float, float]]] = field(default_factory=list)
    tvert_original_channels: List[int] = field(default_factory=list)
    vertex_colors: List[Tuple[float, float, float, float]] = field(default_factory=list)
    faces: List[MeshFace] = field(default_factory=list)
    blend_weights: Dict[int, List[Tuple[str, float]]] = field(default_factory=dict)
    declared_counts: Dict[str, int] = field(default_factory=dict)


@dataclass
class GLMData:
    version: Optional[float] = None
    type_name: str = ""
    object_name: str = ""
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    materials: List[MaterialRef] = field(default_factory=list)
    bones: List[BoneDef] = field(default_factory=list)
    lod_distances: Dict[int, float] = field(default_factory=dict)
    meshes: List[MeshDef] = field(default_factory=list)


class GLMParseError(RuntimeError):
    pass


class GLMParser:
    def __init__(self, filepath: str):
        self.filepath = filepath

    def parse(self) -> GLMData:
        data = GLMData()
        stack: List[str] = []

        current_material: Optional[MaterialRef] = None
        current_bone: Optional[BoneDef] = None
        current_mesh: Optional[MeshDef] = None
        current_blend_vertex: Optional[int] = None
        current_blend_weights: List[Tuple[str, float]] = []
        current_tvert_channel_index: Optional[int] = None

        with open(self.filepath, "r", encoding="utf-8", errors="replace") as f:
            for lineno, raw in enumerate(f, start=1):
                line = raw.strip()
                if not line:
                    continue

                if line.endswith("{"):
                    label = line[:-1].strip()
                    stack.append(label)
                    if label == "MATERIAL":
                        current_material = MaterialRef()
                    elif label == "BONE":
                        current_bone = BoneDef()
                    elif label == "TRIMESH":
                        current_mesh = MeshDef()
                    elif label == "BLEND_VERTEX":
                        current_blend_vertex = None
                        current_blend_weights = []
                    elif label == "TVERT_LIST":
                        if current_mesh is None:
                            raise GLMParseError(f"Line {lineno}: TVERT_LIST found outside TRIMESH")
                        current_tvert_channel_index = None
                    continue

                if line == "}":
                    if not stack:
                        raise GLMParseError(f"Line {lineno}: unexpected closing brace")
                    label = stack.pop()
                    if label == "MATERIAL":
                        if current_material is not None:
                            data.materials.append(current_material)
                        current_material = None
                    elif label == "BONE":
                        if current_bone is not None:
                            data.bones.append(current_bone)
                        current_bone = None
                    elif label == "TRIMESH":
                        if current_mesh is not None:
                            self._validate_mesh(current_mesh, lineno)
                            data.meshes.append(current_mesh)
                        current_mesh = None
                    elif label == "BLEND_VERTEX":
                        if current_mesh is not None and current_blend_vertex is not None:
                            current_mesh.blend_weights[current_blend_vertex] = list(current_blend_weights)
                        current_blend_vertex = None
                        current_blend_weights = []
                    elif label == "TVERT_LIST":
                        current_tvert_channel_index = None
                    continue

                tokens = split_tokens(line)
                if not tokens:
                    continue
                key = tokens[0]
                ctx = stack[-1] if stack else ""

                try:
                    if key == "VERSION":
                        data.version = float(tokens[1])
                    elif key == "TYPE":
                        data.type_name = tokens[1]
                    elif key == "OBJECT_NAME":
                        data.object_name = tokens[1]
                    elif key == "POSITION":
                        xyz = tuple(float(v) for v in tokens[1:4])
                        if ctx == "BONE":
                            if current_bone is None:
                                raise GLMParseError("POSITION inside BONE without active bone")
                            current_bone.position = xyz
                        else:
                            data.position = xyz
                    elif key == "ROTATION":
                        xyzw = tuple(float(v) for v in tokens[1:5])
                        if ctx == "BONE":
                            if current_bone is None:
                                raise GLMParseError("ROTATION inside BONE without active bone")
                            current_bone.rotation = xyzw
                        else:
                            data.rotation = xyzw
                    elif key == "SHADER" and current_material is not None:
                        current_material.shader = tokens[1]
                    elif key == "SHADERREFID" and current_material is not None:
                        current_material.shaderrefid = tokens[1]
                    elif key == "SLOTNAME" and current_material is not None:
                        current_material.slotname = tokens[1]
                    elif key == "NAME" and current_bone is not None:
                        current_bone.name = tokens[1]
                    elif key == "PARENT" and current_bone is not None:
                        current_bone.parent = tokens[1]
                    elif key == "SCALE" and current_bone is not None:
                        current_bone.scale = tuple(float(v) for v in tokens[1:4])
                    elif key == "LOD":
                        data.lod_distances[int(tokens[1])] = float(tokens[2])
                    elif key == "MESH_NAME" and current_mesh is not None:
                        current_mesh.name = tokens[1]
                    elif key == "MESH_STATE_INDEX" and current_mesh is not None:
                        current_mesh.mesh_state_index = int(tokens[1])
                    elif key == "NUM_TVERTEX_CHANNEL" and current_mesh is not None:
                        current_mesh.num_tvertex_channels = int(tokens[1])
                    elif key == "NUM_CVERTEX_CHANNEL" and current_mesh is not None:
                        current_mesh.num_cvertex_channels = int(tokens[1])
                    elif key == "NB_VERTEX" and current_mesh is not None and ctx == "VERTEX_LIST":
                        current_mesh.declared_counts["vertex"] = int(tokens[1])
                    elif key == "VERTEX" and current_mesh is not None and ctx == "VERTEX_LIST":
                        idx = int(tokens[1])
                        xyz = tuple(float(v) for v in tokens[2:5])
                        if idx != len(current_mesh.vertices):
                            raise GLMParseError(f"Line {lineno}: unexpected vertex index {idx}, expected {len(current_mesh.vertices)}")
                        current_mesh.vertices.append(xyz)
                    elif key == "NB_NORMAL" and current_mesh is not None:
                        current_mesh.declared_counts["normal"] = int(tokens[1])
                    elif key == "NORMAL" and current_mesh is not None:
                        idx = int(tokens[1])
                        xyz = tuple(float(v) for v in tokens[2:5])
                        if idx != len(current_mesh.normals):
                            raise GLMParseError(f"Line {lineno}: unexpected normal index {idx}, expected {len(current_mesh.normals)}")
                        current_mesh.normals.append(xyz)
                    elif key == "CHANNEL" and current_mesh is not None and ctx == "TVERT_LIST":
                        current_tvert_channel_index = int(tokens[1])
                        while len(current_mesh.tvert_channels) <= current_tvert_channel_index:
                            current_mesh.tvert_channels.append([])
                            current_mesh.tvert_original_channels.append(-1)
                    elif key == "ORIGINAL_CHANNEL" and current_mesh is not None and ctx == "TVERT_LIST":
                        if current_tvert_channel_index is None:
                            raise GLMParseError(f"Line {lineno}: ORIGINAL_CHANNEL before CHANNEL")
                        current_mesh.tvert_original_channels[current_tvert_channel_index] = int(tokens[1])
                    elif key == "NB_TVERT" and current_mesh is not None and ctx == "TVERT_LIST":
                        if current_tvert_channel_index is None:
                            raise GLMParseError(f"Line {lineno}: NB_TVERT before CHANNEL")
                        current_mesh.declared_counts[f"tvert_{current_tvert_channel_index}"] = int(tokens[1])
                    elif key == "TVERT" and current_mesh is not None and ctx == "TVERT_LIST":
                        if current_tvert_channel_index is None:
                            raise GLMParseError(f"Line {lineno}: TVERT before CHANNEL")
                        idx = int(tokens[1])
                        uvw = tuple(float(v) for v in tokens[2:5])
                        channel = current_mesh.tvert_channels[current_tvert_channel_index]
                        if idx != len(channel):
                            raise GLMParseError(
                                f"Line {lineno}: unexpected TVERT index {idx}, expected {len(channel)} for channel {current_tvert_channel_index}"
                            )
                        channel.append(uvw)
                    elif key == "NB_UV_CHANNELS" and current_mesh is not None and ctx == "FACE_LIST":
                        current_mesh.face_uv_channel_count = int(tokens[1])
                    elif key == "NB_VERTEXCOLOR" and current_mesh is not None:
                        current_mesh.declared_counts["vertexcolor"] = int(tokens[1])
                    elif key == "VC" and current_mesh is not None:
                        idx = int(tokens[1])
                        rgba = tuple(float(v) for v in tokens[2:6])
                        if idx != len(current_mesh.vertex_colors):
                            raise GLMParseError(
                                f"Line {lineno}: unexpected vertex color index {idx}, expected {len(current_mesh.vertex_colors)}"
                            )
                        current_mesh.vertex_colors.append(rgba)
                    elif key == "NB_FACE" and current_mesh is not None:
                        current_mesh.declared_counts["face"] = int(tokens[1])
                    elif key == "FACE" and current_mesh is not None:
                        ints = [int(v) for v in tokens[1:]]
                        face_index = ints[0]
                        payload = ints[1:]
                        uv_channel_count = current_mesh.face_uv_channel_count or current_mesh.num_tvertex_channels
                        expected = 3 + 3 + (3 * uv_channel_count) + 2
                        if len(payload) != expected:
                            raise GLMParseError(
                                f"Line {lineno}: FACE payload length {len(payload)} does not match expected {expected}"
                            )
                        verts = tuple(payload[0:3])
                        normals = tuple(payload[3:6])
                        uv_indices: List[Tuple[int, int, int]] = []
                        offset = 6
                        for _ in range(uv_channel_count):
                            uv_indices.append(tuple(payload[offset:offset + 3]))
                            offset += 3
                        face_flag = payload[offset]
                        material_id = payload[offset + 1]
                        if face_index != len(current_mesh.faces):
                            raise GLMParseError(f"Line {lineno}: unexpected face index {face_index}, expected {len(current_mesh.faces)}")
                        current_mesh.faces.append(
                            MeshFace(
                                index=face_index,
                                verts=verts,
                                normal_indices=normals,
                                uv_indices=uv_indices,
                                face_flag=face_flag,
                                material_id=material_id,
                            )
                        )
                    elif key == "CFACE" and current_mesh is not None:
                        ints = [int(v) for v in tokens[1:]]
                        face_index = ints[0]
                        channel = ints[1]
                        color_indices = tuple(ints[2:5])
                        current_mesh.faces[face_index].color_indices[channel] = color_indices
                    elif key == "VERTEX" and ctx == "BLEND_VERTEX":
                        current_blend_vertex = int(tokens[1])
                    elif key == "BONE_LINK" and ctx == "BLEND_VERTEX":
                        current_blend_weights.append((tokens[1], float(tokens[2])))
                    # keys intentionally ignored: NB_BONE, NB_MATERIAL, NB_SKELETONS, NB_CHANNELS,
                    # COLOR_WELDING_TOLERANCE, VERTEX_WELDING_TOLERANCE, NB_UV_CHANNELS, GENERATE*...
                except (IndexError, ValueError) as exc:
                    raise GLMParseError(f"Line {lineno}: failed to parse '{line}': {exc}") from exc

        if stack:
            raise GLMParseError(f"Unclosed blocks at EOF: {stack}")
        return data

    @staticmethod
    def _validate_mesh(mesh: MeshDef, lineno: int) -> None:
        def check(name: str, actual: int) -> None:
            expected = mesh.declared_counts.get(name)
            if expected is not None and expected != actual:
                raise GLMParseError(
                    f"Line {lineno}: mesh '{mesh.name}' expected {expected} {name} entries but parsed {actual}"
                )

        check("vertex", len(mesh.vertices))
        check("normal", len(mesh.normals))
        check("vertexcolor", len(mesh.vertex_colors))
        check("face", len(mesh.faces))
        for i, channel in enumerate(mesh.tvert_channels):
            check(f"tvert_{i}", len(channel))


# ---------------------------
# Blender import helpers
# ---------------------------


def axis_angle_to_matrix(axis_angle: Tuple[float, float, float, float]):
    if Matrix is None or Vector is None:
        return None
    ax, ay, az, angle = axis_angle
    axis = Vector((ax, ay, az))
    if axis.length < 1e-8 or abs(angle) < 1e-8:
        return Matrix.Identity(4)
    axis.normalize()
    return Matrix.Rotation(angle, 4, axis)



def mirror_x_vec3(vec: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (-vec[0], vec[1], vec[2])



def convert_position(vec: Tuple[float, float, float], mirror_x: bool = False) -> Tuple[float, float, float]:
    return mirror_x_vec3(vec) if mirror_x else vec



def convert_direction(vec: Tuple[float, float, float], mirror_x: bool = False) -> Tuple[float, float, float]:
    return mirror_x_vec3(vec) if mirror_x else vec



def convert_rotation_matrix(rotation_matrix, mirror_x: bool = False):
    if not mirror_x or Matrix is None:
        return rotation_matrix
    mirror = Matrix((
        (-1.0, 0.0, 0.0, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    ))
    return mirror @ rotation_matrix @ mirror



def transform_matrix(position: Tuple[float, float, float], rotation: Tuple[float, float, float, float], mirror_x: bool = False):
    if Matrix is None or Vector is None:
        return None
    pos = convert_position(position, mirror_x=mirror_x)
    rot = convert_rotation_matrix(axis_angle_to_matrix(rotation), mirror_x=mirror_x)
    return Matrix.Translation(Vector(pos)) @ rot


@dataclass
class BuiltBone:
    name: str
    matrix: object



def build_armature(glm: GLMData, collection, armature_name: Optional[str] = None, mirror_x: bool = False):
    if bpy is None:
        raise RuntimeError("This function must run inside Blender")

    arm_name = armature_name or f"{glm.object_name}_Armature"
    arm_data = bpy.data.armatures.new(arm_name)
    arm_obj = bpy.data.objects.new(arm_name, arm_data)
    collection.objects.link(arm_obj)

    view_layer = bpy.context.view_layer
    prev_active = view_layer.objects.active
    prev_mode = bpy.context.mode

    try:
        bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass
    bpy.ops.object.select_all(action='DESELECT')
    arm_obj.select_set(True)
    view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='EDIT')

    built: Dict[str, BuiltBone] = {}
    root_name = glm.object_name
    root_matrix = transform_matrix(glm.position, glm.rotation, mirror_x=mirror_x)

    remaining = {bone.name: bone for bone in glm.bones}
    safety = 0
    while remaining:
        safety += 1
        if safety > len(glm.bones) + 5:
            unresolved = ", ".join(sorted(remaining.keys())[:10])
            raise RuntimeError(f"Could not resolve bone hierarchy. Remaining: {unresolved}")

        progressed = False
        for bone_name in list(remaining.keys()):
            bone = remaining[bone_name]
            if bone.parent and bone.parent != root_name and bone.parent not in built:
                continue

            parent_matrix = root_matrix if bone.parent == root_name or not bone.parent else built.get(bone.parent, BuiltBone("", root_matrix)).matrix
            local_matrix = transform_matrix(bone.position, bone.rotation, mirror_x=mirror_x)
            world_matrix = parent_matrix @ local_matrix

            edit_bone = arm_data.edit_bones.new(bone.name)
            if bone.parent and bone.parent != root_name and bone.parent in arm_data.edit_bones:
                edit_bone.parent = arm_data.edit_bones[bone.parent]

            head = world_matrix.to_translation()
            y_axis = (world_matrix.to_3x3() @ Vector((0.0, 0.05, 0.0)))
            if y_axis.length < 1e-8:
                y_axis = Vector((0.0, 0.05, 0.0))
            tail = head + y_axis
            if (tail - head).length < 1e-6:
                tail = head + Vector((0.0, 0.05, 0.0))

            edit_bone.head = head
            edit_bone.tail = tail
            try:
                z_axis = world_matrix.to_3x3() @ Vector((0.0, 0.0, 1.0))
                if z_axis.length > 1e-8:
                    edit_bone.align_roll(z_axis)
            except Exception:
                pass

            try:
                edit_bone["glm_parent"] = bone.parent
                edit_bone["glm_rotation_axis_angle"] = bone.rotation
                edit_bone["glm_scale"] = bone.scale
            except Exception:
                pass

            built[bone.name] = BuiltBone(bone.name, world_matrix)
            del remaining[bone_name]
            progressed = True

        if not progressed:
            unresolved = ", ".join(sorted(remaining.keys())[:10])
            raise RuntimeError(f"Could not progress while building armature. Remaining: {unresolved}")

    bpy.ops.object.mode_set(mode='OBJECT')

    if prev_active is not None:
        view_layer.objects.active = prev_active
        try:
            bpy.ops.object.mode_set(mode=prev_mode)
        except Exception:
            pass

    return arm_obj



def get_or_create_materials(glm: GLMData) -> List[object]:
    if bpy is None:
        raise RuntimeError("This function must run inside Blender")
    result = []
    for i, src in enumerate(glm.materials):
        name = src.slotname or f"Material_{i}"
        mat = bpy.data.materials.get(name)
        if mat is None:
            mat = bpy.data.materials.new(name=name)
        mat["glm_shader"] = src.shader
        mat["glm_shaderrefid"] = src.shaderrefid
        mat["glm_slotname"] = src.slotname
        result.append(mat)
    return result



def extract_lod_index(name: str) -> int:
    m = _LOD_RE.search(name)
    return int(m.group(2)) if m else -1


def strip_lod_suffix(name: str) -> str:
    return _LOD_RE.sub("", name).rstrip("_") or name


def get_or_create_child_collection(parent_collection, name: str):
    if bpy is None:
        raise RuntimeError("This function must run inside Blender")
    existing = bpy.data.collections.get(name)
    if existing is not None:
        already_linked = any(child == existing for child in parent_collection.children)
        if not already_linked:
            parent_collection.children.link(existing)
        return existing
    child = bpy.data.collections.new(name)
    parent_collection.children.link(child)
    return child


def choose_primary_bone(weights: List[Tuple[str, float]]) -> Optional[Tuple[str, float]]:
    if not weights:
        return None
    return max(weights, key=lambda item: (item[1], item[0]))


def choose_face_part(mesh_def: MeshDef, face: MeshFace) -> str:
    counts: Dict[str, int] = {}
    sums: Dict[str, float] = {}
    for vertex_index in face.verts:
        primary = choose_primary_bone(mesh_def.blend_weights.get(vertex_index, []))
        if primary is None:
            continue
        bone_name, weight = primary
        counts[bone_name] = counts.get(bone_name, 0) + 1
        sums[bone_name] = sums.get(bone_name, 0.0) + weight
    if not counts:
        return "Unweighted"
    return max(counts.keys(), key=lambda name: (counts[name], sums.get(name, 0.0), name))


def split_faces_by_part(mesh_def: MeshDef) -> Dict[str, List[int]]:
    grouped: Dict[str, List[int]] = {}
    for face_index, face in enumerate(mesh_def.faces):
        part_name = choose_face_part(mesh_def, face)
        grouped.setdefault(part_name, []).append(face_index)
    return grouped



def _set_corner_colors(mesh_data, attr_name: str, rgba_values: List[float]):
    if hasattr(mesh_data, "color_attributes"):
        attr = mesh_data.color_attributes.new(name=attr_name, type='FLOAT_COLOR', domain='CORNER')
        attr.data.foreach_set("color", rgba_values)
        return attr

    # Legacy fallback
    vcol = mesh_data.vertex_colors.new(name=attr_name)
    vcol.data.foreach_set("color", rgba_values)
    return vcol




def build_mesh_object_from_faces(glm: GLMData, mesh_def: MeshDef, materials: List[object], armature_obj, collection,
                                 face_indices: List[int], object_name: str, flip_v: bool = False,
                                 import_custom_normals: bool = True, import_vertex_colors: bool = True,
                                 mirror_x: bool = False, part_name: Optional[str] = None):
    if bpy is None:
        raise RuntimeError("This function must run inside Blender")
    if not face_indices:
        return None

    mesh_data = bpy.data.meshes.new(object_name)
    mesh_obj = bpy.data.objects.new(object_name, mesh_data)
    collection.objects.link(mesh_obj)

    corner_order = (0, 2, 1) if mirror_x else (0, 1, 2)
    selected_faces = [mesh_def.faces[i] for i in face_indices]

    used_vertex_indices: List[int] = []
    seen_vertices = set()
    for face in selected_faces:
        for vertex_index in face.verts:
            if vertex_index not in seen_vertices:
                seen_vertices.add(vertex_index)
                used_vertex_indices.append(vertex_index)
    vertex_remap = {old_index: new_index for new_index, old_index in enumerate(used_vertex_indices)}

    converted_vertices = [convert_position(mesh_def.vertices[old_index], mirror_x=mirror_x) for old_index in used_vertex_indices]
    face_verts = [tuple(vertex_remap[face.verts[i]] for i in corner_order) for face in selected_faces]
    mesh_data.from_pydata(converted_vertices, [], face_verts)
    mesh_data.update(calc_edges=True)

    for mat in materials:
        mesh_data.materials.append(mat)

    poly_count = len(selected_faces)
    loop_count = poly_count * 3

    if poly_count:
        mesh_data.polygons.foreach_set("use_smooth", [True] * poly_count)

    material_indices = [max(0, min(face.material_id, max(0, len(materials) - 1))) for face in selected_faces]
    if poly_count and materials:
        mesh_data.polygons.foreach_set("material_index", material_indices)

    if hasattr(mesh_data, "attributes"):
        try:
            flag_attr = mesh_data.attributes.new(name="glm_face_flag", type='INT', domain='FACE')
            flag_attr.data.foreach_set("value", [face.face_flag for face in selected_faces])
        except Exception:
            pass
        try:
            src_face_attr = mesh_data.attributes.new(name="glm_source_face", type='INT', domain='FACE')
            src_face_attr.data.foreach_set("value", face_indices)
        except Exception:
            pass
        try:
            src_vert_attr = mesh_data.attributes.new(name="glm_source_vertex", type='INT', domain='POINT')
            src_vert_attr.data.foreach_set("value", used_vertex_indices)
        except Exception:
            pass

    for channel_index, tverts in enumerate(mesh_def.tvert_channels):
        if not tverts:
            continue
        original_channel = mesh_def.tvert_original_channels[channel_index]
        layer_name = f"UV{original_channel if original_channel >= 0 else channel_index}"
        uv_layer = mesh_data.uv_layers.new(name=layer_name)
        flat_uvs = [0.0] * (loop_count * 2)
        for subset_face_index, face in enumerate(selected_faces):
            if channel_index >= len(face.uv_indices):
                continue
            uv_indices = face.uv_indices[channel_index]
            for corner in range(3):
                loop_index = subset_face_index * 3 + corner
                source_corner = corner_order[corner]
                uv_index = uv_indices[source_corner]
                if uv_index < 0 or uv_index >= len(tverts):
                    continue
                uv = tverts[uv_index]
                flat_uvs[loop_index * 2] = uv[0]
                flat_uvs[loop_index * 2 + 1] = 1.0 - uv[1] if flip_v else uv[1]
        uv_layer.data.foreach_set("uv", flat_uvs)

    if import_vertex_colors and mesh_def.vertex_colors:
        channels_present = sorted({ch for face in selected_faces for ch in face.color_indices.keys()})
        for color_channel in channels_present:
            attr_name = "Col" if color_channel == 0 else f"Col_{color_channel}"
            rgba_values = [1.0] * (loop_count * 4)
            has_any_valid_color = False
            for subset_face_index, face in enumerate(selected_faces):
                if color_channel not in face.color_indices:
                    continue
                col_indices = face.color_indices[color_channel]
                for corner in range(3):
                    loop_index = subset_face_index * 3 + corner
                    source_corner = corner_order[corner]
                    color_index = col_indices[source_corner]
                    if color_index < 0 or color_index >= len(mesh_def.vertex_colors):
                        continue
                    has_any_valid_color = True
                    rgba = mesh_def.vertex_colors[color_index]
                    base = loop_index * 4
                    rgba_values[base:base + 4] = rgba
            if has_any_valid_color:
                _set_corner_colors(mesh_data, attr_name, rgba_values)

    if import_custom_normals and mesh_def.normals:
        custom_normals = [(0.0, 0.0, 1.0)] * loop_count
        for subset_face_index, face in enumerate(selected_faces):
            for corner in range(3):
                loop_index = subset_face_index * 3 + corner
                source_corner = corner_order[corner]
                normal_index = face.normal_indices[source_corner]
                if normal_index < 0 or normal_index >= len(mesh_def.normals):
                    continue
                custom_normals[loop_index] = convert_direction(mesh_def.normals[normal_index], mirror_x=mirror_x)
        try:
            mesh_data.normals_split_custom_set(custom_normals)
            if hasattr(mesh_data, "use_auto_smooth"):
                mesh_data.use_auto_smooth = True
        except Exception:
            pass

    if armature_obj is not None and mesh_def.blend_weights:
        used_bones = sorted({
            bone_name
            for old_vertex_index in used_vertex_indices
            for bone_name, _ in mesh_def.blend_weights.get(old_vertex_index, [])
        })
        group_map = {}
        for bone_name in used_bones:
            group_map[bone_name] = mesh_obj.vertex_groups.new(name=bone_name)

        for old_vertex_index in used_vertex_indices:
            new_vertex_index = vertex_remap[old_vertex_index]
            for bone_name, weight in mesh_def.blend_weights.get(old_vertex_index, []):
                group = group_map.get(bone_name)
                if group is not None:
                    group.add([new_vertex_index], weight, 'REPLACE')

        arm_mod = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')
        arm_mod.object = armature_obj
        mesh_obj.parent = armature_obj

    lod_index = extract_lod_index(mesh_def.name)
    mesh_obj["glm_lod_index"] = lod_index
    if lod_index in glm.lod_distances:
        mesh_obj["glm_lod_distance"] = glm.lod_distances[lod_index]
    mesh_obj["glm_mesh_state_index"] = mesh_def.mesh_state_index
    mesh_obj["glm_num_uv_channels"] = mesh_def.num_tvertex_channels
    mesh_obj["glm_face_uv_channel_count"] = mesh_def.face_uv_channel_count or len(mesh_def.faces[0].uv_indices) if mesh_def.faces else mesh_def.num_tvertex_channels
    mesh_obj["glm_num_color_channels"] = mesh_def.num_cvertex_channels
    mesh_obj["glm_source_mesh_name"] = mesh_def.name
    if part_name is not None:
        mesh_obj["glm_part_name"] = part_name

    return mesh_obj


def build_mesh_objects(glm: GLMData, mesh_def: MeshDef, materials: List[object], armature_obj, collection, flip_v: bool = False,
                       import_custom_normals: bool = True, import_vertex_colors: bool = True, mirror_x: bool = False,
                       split_into_parts: bool = True):
    if split_into_parts and mesh_def.blend_weights:
        part_faces = split_faces_by_part(mesh_def)
        built_objects = []
        lod_index = extract_lod_index(mesh_def.name)
        for part_name in sorted(part_faces.keys()):
            face_indices = part_faces[part_name]
            object_name = f"{part_name}_LOD{lod_index}" if lod_index >= 0 else part_name
            built = build_mesh_object_from_faces(
                glm=glm,
                mesh_def=mesh_def,
                materials=materials,
                armature_obj=armature_obj,
                collection=collection,
                face_indices=face_indices,
                object_name=object_name,
                flip_v=flip_v,
                import_custom_normals=import_custom_normals,
                import_vertex_colors=import_vertex_colors,
                mirror_x=mirror_x,
                part_name=part_name,
            )
            if built is not None:
                built_objects.append(built)
        return built_objects

    built = build_mesh_object_from_faces(
        glm=glm,
        mesh_def=mesh_def,
        materials=materials,
        armature_obj=armature_obj,
        collection=collection,
        face_indices=list(range(len(mesh_def.faces))),
        object_name=mesh_def.name,
        flip_v=flip_v,
        import_custom_normals=import_custom_normals,
        import_vertex_colors=import_vertex_colors,
        mirror_x=mirror_x,
        part_name=strip_lod_suffix(mesh_def.name),
    )
    return [built] if built is not None else []


def import_glm(filepath: str, flip_v: bool = False, import_custom_normals: bool = True,
               import_vertex_colors: bool = True, create_armature: bool = True, mirror_x: bool = True,
               split_into_parts: bool = True, create_lod_collections: bool = True,
               import_all_lods: bool = True, selected_lod: int = 0):
    if bpy is None:
        raise RuntimeError("This script must run inside Blender to import meshes")

    parser = GLMParser(filepath)
    glm = parser.parse()

    coll_name = glm.object_name or Path(filepath).stem
    collection = bpy.data.collections.new(coll_name)
    bpy.context.scene.collection.children.link(collection)

    collection["glm_source_file"] = filepath
    for lod_index, distance in glm.lod_distances.items():
        collection[f"glm_lod_{lod_index}"] = distance

    collection["glm_import_all_lods"] = bool(import_all_lods)
    collection["glm_selected_lod"] = int(selected_lod)

    materials = get_or_create_materials(glm)
    armature_obj = build_armature(glm, collection, mirror_x=mirror_x) if create_armature and glm.bones else None

    lod_collections: Dict[int, object] = {}
    created_objects = []
    for mesh_def in glm.meshes:
        lod_index = extract_lod_index(mesh_def.name)
        if not import_all_lods and lod_index != selected_lod:
            continue

        target_collection = collection
        if create_lod_collections and lod_index >= 0:
            if lod_index not in lod_collections:
                lod_name = f"{coll_name}_LOD{lod_index}"
                lod_collection = get_or_create_child_collection(collection, lod_name)
                lod_collection["glm_lod_index"] = lod_index
                if lod_index in glm.lod_distances:
                    lod_collection["glm_lod_distance"] = glm.lod_distances[lod_index]
                lod_collections[lod_index] = lod_collection
            target_collection = lod_collections[lod_index]

        built_objects = build_mesh_objects(
            glm=glm,
            mesh_def=mesh_def,
            materials=materials,
            armature_obj=armature_obj,
            collection=target_collection,
            flip_v=flip_v,
            import_custom_normals=import_custom_normals,
            import_vertex_colors=import_vertex_colors,
            mirror_x=mirror_x,
            split_into_parts=split_into_parts,
        )
        created_objects.extend(built_objects)

    created_objects.sort(key=lambda obj: (obj.get("glm_lod_index", 9999), obj.name))

    return {
        "glm": glm,
        "collection": collection,
        "armature": armature_obj,
        "lod_collections": lod_collections,
        "objects": created_objects,
    }


# ---------------------------
# Blender operator / menu
# ---------------------------


if bpy is not None:

    class IMPORT_OT_game_glm(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.game_glm_text"
        bl_label = "Import Game GLM (.glm)"
        bl_options = {'UNDO'}

        filename_ext = ".glm"
        filter_glob: StringProperty(default="*.glm", options={'HIDDEN'})

        mirror_x: BoolProperty(
            name="Mirror X (for mirrored assets)",
            description="Use this only for GLM files that import left-right mirrored",
            default=False,
        )
        flip_v: BoolProperty(
            name="Flip UV V",
            description="Flip the V axis of all imported UV layers",
            default=False,
        )
        import_custom_normals: BoolProperty(
            name="Import custom normals",
            description="Apply split normals from the GLM so shading matches the game asset",
            default=True,
        )
        import_vertex_colors: BoolProperty(
            name="Import color attributes",
            description="Import loop-corner vertex colors from the GLM",
            default=True,
        )
        create_armature: BoolProperty(
            name="Create skeleton",
            description="Build the bone hierarchy and bind imported objects to it",
            default=True,
        )
        split_into_parts: BoolProperty(
            name="Split into part objects",
            description="Create separate objects from the dominant bone per face, such as Chassis or A_ArmFront_R",
            default=True,
        )
        create_lod_collections: BoolProperty(
            name="Create collections per LOD",
            description="Place imported objects into child collections like Asset_LOD0, Asset_LOD1, and so on",
            default=True,
        )
        import_all_lods: BoolProperty(
            name="Import all LODs",
            description="Import every LOD found in the GLM file",
            default=True,
        )
        selected_lod: IntProperty(
            name="LOD index",
            description="Import only this LOD when 'Import all LODs' is disabled",
            default=0,
            min=0,
            max=99,
            soft_min=0,
            soft_max=10,
        )

        def draw(self, context):
            layout = self.layout

            box = layout.box()
            box.label(text="Orientation")
            box.prop(self, "mirror_x")
            box.prop(self, "flip_v")

            box = layout.box()
            box.label(text="Imported data")
            box.prop(self, "create_armature")
            box.prop(self, "import_custom_normals")
            box.prop(self, "import_vertex_colors")

            box = layout.box()
            box.label(text="Scene organization")
            box.prop(self, "split_into_parts")
            box.prop(self, "create_lod_collections")

            box = layout.box()
            box.label(text="LOD selection")
            box.prop(self, "import_all_lods")
            row = box.row()
            row.enabled = not self.import_all_lods
            row.prop(self, "selected_lod", slider=True)

        def execute(self, context):
            try:
                import_glm(
                    filepath=self.filepath,
                    flip_v=self.flip_v,
                    import_custom_normals=self.import_custom_normals,
                    import_vertex_colors=self.import_vertex_colors,
                    create_armature=self.create_armature,
                    mirror_x=self.mirror_x,
                    split_into_parts=self.split_into_parts,
                    create_lod_collections=self.create_lod_collections,
                    import_all_lods=self.import_all_lods,
                    selected_lod=self.selected_lod,
                )
            except Exception as exc:
                self.report({'ERROR'}, str(exc))
                raise
            self.report({'INFO'}, f"Imported GLM: {Path(self.filepath).name}")
            return {'FINISHED'}


    def menu_func_import(self, context):
        self.layout.operator(IMPORT_OT_game_glm.bl_idname, text="Game GLM (.glm)")


    def register():
        bpy.utils.register_class(IMPORT_OT_game_glm)
        bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


    def unregister():
        bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
        bpy.utils.unregister_class(IMPORT_OT_game_glm)


# ---------------------------
# Standalone summary mode
# ---------------------------


def summarize_glm(filepath: str) -> str:
    glm = GLMParser(filepath).parse()
    lines = [
        f"Object: {glm.object_name}",
        f"Version: {glm.version}",
        f"Type: {glm.type_name}",
        f"Materials: {len(glm.materials)}",
        f"Bones: {len(glm.bones)}",
        f"Meshes: {len(glm.meshes)}",
    ]
    for mesh in glm.meshes:
        lines.append(
            f"  - {mesh.name}: {len(mesh.vertices)} verts, {len(mesh.faces)} faces, {len(mesh.normals)} normals, "
            f"UVs={[(mesh.tvert_original_channels[i], len(ch)) for i, ch in enumerate(mesh.tvert_channels)]}, "
            f"colors={len(mesh.vertex_colors)}"
        )
    return "\n".join(lines)


if __name__ == "__main__" and bpy is None:
    import argparse
    ap = argparse.ArgumentParser(description="Parse a plain-text game .glm file and print a summary.")
    ap.add_argument("filepath", help="Path to .glm file")
    args = ap.parse_args()
    print(summarize_glm(args.filepath))
