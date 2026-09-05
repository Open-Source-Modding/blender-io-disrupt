"""Watch Dogs 2 compiled .xbg importer (self-contained WD2-owned module).

WD2 ships compiled models as binary .xbg files with a MOEG header (reversed
GEOM, version 0x89/0x46).  The companion .skel file holds the skeleton.

Ported from Volfin's io_scene_WD2 (Blender 2.7) to the modern architecture.
Produces the same neutral model dict as import_wd2.py so build_wd_model()
from that module can be reused for Blender scene construction.
"""

import os
import struct

import numpy as np

try:
    import bpy
    import mathutils
except ImportError:
    bpy = None
    mathutils = None

from ..Core.debug import VerboseLogger as vlog


# ── Binary reader ──────────────────────────────────────────────────────────

class _Reader:
    """Sequential little-endian binary reader with alignment."""

    def __init__(self, fp):
        self._fp = fp

    def tell(self):
        return self._fp.tell()

    def seek(self, off, whence=0):
        self._fp.seek(off, whence)

    def read(self, n):
        return self._fp.read(n)

    def align(self, a):
        pos = self._fp.tell()
        aligned = (pos + a - 1) & ~(a - 1)
        if aligned - pos == a:
            aligned = pos
        self._fp.seek(aligned)

    # ── primitive reads ────────────────────────────────────────────────

    def u8(self):
        return struct.unpack('<B', self._fp.read(1))[0]

    def i8(self):
        return struct.unpack('<b', self._fp.read(1))[0]

    def u16(self):
        self.align(2)
        return struct.unpack('<H', self._fp.read(2))[0]

    def i16(self):
        self.align(2)
        return struct.unpack('<h', self._fp.read(2))[0]

    def u32(self):
        self.align(4)
        return struct.unpack('<I', self._fp.read(4))[0]

    def i32(self):
        self.align(4)
        return struct.unpack('<i', self._fp.read(4))[0]

    def f32(self):
        self.align(4)
        return struct.unpack('<f', self._fp.read(4))[0]

    def u16s(self, n):
        self.align(2)
        return list(struct.unpack('<%dH' % n, self._fp.read(2 * n)))

    def i16s(self, n):
        self.align(2)
        return list(struct.unpack('<%dh' % n, self._fp.read(2 * n)))

    def u32s(self, n):
        self.align(4)
        return list(struct.unpack('<%dI' % n, self._fp.read(4 * n)))

    def f32s(self, n):
        self.align(4)
        return list(struct.unpack('<%df' % n, self._fp.read(4 * n)))

    def f64s(self, n):
        self.align(8)
        return list(struct.unpack('<%dd' % n, self._fp.read(8 * n)))

    def bytes(self, n):
        return list(self._fp.read(n))

    def str(self):
        length = self.u32()
        data = self._fp.read(length)
        end = data.find(b'\x00')
        if end >= 0:
            data = data[:end]
        return data.decode('latin-1')

    def skip_bytes(self, n):
        self._fp.seek(n, 1)


# ── Format constants ───────────────────────────────────────────────────────

_MAGIC = b'MOEG'
# WD2 version 137.70, WDL version 149.70 — same format, different minor
_WD2_VERSIONS = {(0x89, 0x46), (0x95, 0x46)}


# ── WD2 compiled .xbg parser ──────────────────────────────────────────────

def _read_odd_table(r):
    """Read the location/transform lookup table after the header."""
    loc_count = r.u32()
    for _ in range(loc_count):
        r.skip_bytes(32)  # 8 f32


def _read_skip_mess(r):
    """Read the ReflexSystem / secondary-motion / procedural-nodes blob.

    Ported from Volfin's skipMess() (import_WD2.py lines 561-697).
    Per-entry prefix: BI(2) + Bf(7) + BI(4) + BI(1) = 56 bytes, then
    entry_type = BI(1).

    entry_type == 2 → static-props branch (nested hash+string+float groups).
    entry_type != 2 → character-model branch (hash+string+float groups with
    different layout — Bf(4)*4+Bf(1), Bf(23), BH(6)+Bf(4), seek(44), etc.).
    """
    count = r.u32()
    if count == 0:
        return

    for _ in range(count):
        r.skip_bytes(56)  # BI(2) + Bf(7) + BI(4) + BI(1)
        entry_type = r.u32()

        if entry_type == 2:
            # ── Static-props branch ──────────────────────────────────────
            # Three groups of hash+string+skip
            for _group in range(3):
                c = r.u32()
                if _group == 0:
                    # Two sub-groups within first group
                    for _sub in range(2):
                        sc = r.u32()
                        for _ in range(sc):
                            r.u32()  # hash
                            s = r.u32()
                            r.skip_bytes(s)
                            r.align(16)
                            r.skip_bytes(68)  # Bf(17) = 17 floats
                    c2 = r.u32()
                    for _ in range(c2):
                        r.u32()  # hash
                        s = r.u32()
                        r.skip_bytes(s)
                        r.align(16)
                        r.skip_bytes(92)  # Bf(23) = 23 floats
                else:
                    for _ in range(c):
                        r.u32()  # hash
                        s = r.u32()
                        r.skip_bytes(s)
                        r.align(16)
                        r.skip_bytes(92)  # Bf(23) = 23 floats

            # Byte groups
            c = r.u32()
            for _ in range(c):
                cv = r.u32()
                c2 = r.u32()
                r.skip_bytes(c2 * 20)  # Bf(5) = 5 floats

            c = r.u32()
            for _ in range(c):
                cv = r.u32()
                c2 = r.u32()
                r.skip_bytes(c2 * 36)  # Bf(9) = 9 floats

            c = r.u32()
            for _ in range(c):
                cv = r.u32()
                c2 = r.u32()
                r.skip_bytes(c2 * 36)  # Bf(9) = 9 floats

            # String groups
            c = r.u32()
            for _ in range(c):
                r.u32()  # hash
                s = r.u32()
                r.skip_bytes(s)
                r.align(4)
                r.skip_bytes(16)  # Bf(4) = 4 floats

            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(4)

            # Skip trailing counts
            r.u32()
            r.u32()
            r.u32()
            r.u32()
        else:
            # ── Character-model branch (Volfin lines 638-697) ────────────
            r.u32()  # chunk type
            c = r.u32()
            for _ in range(c):
                r.u32()  # hash
                s = r.u32()
                r.skip_bytes(s)
                r.align(16)
                r.skip_bytes(68)  # Bf(4)*4 + Bf(1) = 68 bytes

            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(16)
                r.skip_bytes(92)  # Bf(23) = 92 bytes

            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(16)
                r.skip_bytes(92)  # Bf(23) = 92 bytes

            r.u32()  # chunk
            c = r.u32()
            for _ in range(c):
                r.skip_bytes(12)  # BH(6) = 12 bytes
                r.skip_bytes(16)  # Bf(4) = 16 bytes

            r.u32()  # chunk
            c = r.u32()
            for _ in range(c):
                r.skip_bytes(44)  # seek(44, 1)

            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(4)
                r.skip_bytes(16)  # Bf(4) = 16 bytes

            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(4)

            c = r.u32()
            r.skip_bytes(c * 6)  # BH(3) = 6 bytes
            r.align(4)

            r.u32()  # chunk
            c = r.u32()
            r.skip_bytes(c * 6)  # BH(3) = 6 bytes

            r.u32()  # chunk
            r.align(4)


def _read_mesh_list(r):
    """Read the mesh descriptor list for one LOD level.

    Ported from Volfin's MeshList() (import_WD2.py lines 699-724).

    Returns a list of dicts, one per submesh, with keys:
        vertStride, vertCount, faceCount, faceOffset,
        totalVertCount, matID, UVFlag, matCount, matNames
    """
    mesh_count = r.u32()
    meshes = []

    for _ in range(mesh_count):
        # 10 f32s: bounding box / LOD distances
        r.skip_bytes(40)  # 10 * 4

        # 22 u16s: mesh parameters
        params = r.u16s(22)
        r.u32()  # trailing dword

        vertStride = params[4]
        vertCount = 1 + params[16] - params[15]
        faceCount = params[10]
        faceOffset = params[12]
        totalVertCount = params[14]
        matID = params[2]
        UVFlag = params[3]
        matCount = params[20]

        # Read material name entries for this submesh
        # Volfin's MeshList(): BI(17) + len=BI(1)[0] + file_str(len) + align(4) + BH(2)
        mat_names = []
        for _ in range(matCount):
            r.skip_bytes(68)  # BI(17) = 68 bytes
            s = r.u32()       # string length — must NOT use r.str() here
                              # because r.str() reads its own u32 length,
                              # doubling the read
            if 0 < s <= 128:
                data = r.read(s)
                name = data.decode('latin-1').rstrip('\x00')
                r.align(4)
                r.u16s(2)
                mat_names.append(name)
            else:
                r.seek(-72, 1)

        meshes.append({
            'vertStride': vertStride,
            'vertCount': vertCount,
            'faceCount': faceCount,
            'faceOffset': faceOffset,
            'totalVertCount': totalVertCount,
            'matID': matID,
            'UVFlag': UVFlag,
            'matCount': matCount,
            'matNames': mat_names,
        })

    return meshes


def _read_secondary_motion(r):
    """Read secondary motion / procedural nodes block."""
    count = r.u32()
    for _ in range(count):
        b = r.u16s(4)
        r.f32()
        if b[1] == 6:
            r.u32s(3)


def parse_wd2_xbg(path):
    """Parse a WD2 compiled .xbg into the neutral model dict.

    Returns dict with keys: source, name, bones, meshes.
    The meshes list contains geometry-only dicts (no skin weights yet —
    those come from the .skel file if present).
    """
    model = {
        'source': 'wd2',
        'name': os.path.splitext(os.path.basename(path))[0],
        'bones': [],
        'meshes': [],
    }

    with open(path, 'rb') as fp:
        r = _Reader(fp)

        # ── Header ─────────────────────────────────────────────────────
        magic = r.read(4)
        if magic != _MAGIC:
            raise ValueError(
                "not a Watch Dogs 2 .xbg (magic %r, expected %r)"
                % (magic, _MAGIC))

        ver_major = r.u16()
        ver_minor = r.u16()
        if (ver_major, ver_minor) not in _WD2_VERSIONS:
            raise ValueError(
                "unexpected .xbg version 0x%04X/0x%04X "
                "(expected WD2 0x89/0x46 or WDL 0x95/0x46)"
                % (ver_major, ver_minor))

        # ── Header data ────────────────────────────────────────────────
        r.skip_bytes(16)  # BI(4)
        _unk_count = r.u32()
        odd_flag = r.u32()

        for _ in range(odd_flag):
            _read_odd_table(r)

        r.skip_bytes(76)  # BI(19)

        lod_count = r.u32()

        for _ in range(lod_count):
            r.u32s(2)

        # ── Materials ──────────────────────────────────────────────────
        r.u32s(3)
        mat_count = r.u32()
        r.u32()

        materials = []
        tag_count = 0
        for _ in range(mat_count):
            mat_hash = r.u32()
            mat_path = r.str()
            r.align(4)
            mat_name_hash = r.u32()
            mat_name = r.str()
            r.align(4)

            materials.append({
                'name': mat_name,
                'path': mat_path,
            })

            tag_count = r.u32()
            if tag_count == 0:
                r.u32()

        for _ in range(tag_count):
            r.u32()  # hash
            r.str()  # name
            r.align(4)
            r.u32()  # id

        r.align(4)

        # ── Skeleton ───────────────────────────────────────────────────
        skeleton_count = r.u32()
        for _ in range(skeleton_count):
            r.align(4)
            r.u32()  # hash
            _skele_name = r.str()

        r.align(2)

        bone_id_count = r.u16()
        bone_flag = r.u16()

        if bone_flag != 0:
            if bone_flag == 1:
                r.skip_bytes(bone_id_count * 18)
            elif bone_flag == 2:
                r.skip_bytes(bone_id_count * 20)
            elif bone_flag == 8:
                r.skip_bytes(bone_id_count * 16)
            else:
                r.skip_bytes(bone_id_count * 8)
        else:
            r.skip_bytes(8)

        # Skeleton part 2 — bone names (transforms are in .skel file)
        r.align(4)
        chunk = r.u32()
        if chunk == 1:
            bone_count = r.u32()
            for _ in range(bone_count):
                r.skip_bytes(52)  # BI(13)
                r.str()  # name
                r.align(4)

        # ── Object-to-node matrices ────────────────────────────────────
        r.u32()
        matrix_count = r.u32()
        r.align(16)
        r.skip_bytes(matrix_count * 64)  # 4x4 f32

        # ── Skip block ─────────────────────────────────────────────────
        chunk = r.u32()
        if chunk != 0:
            r.skip_bytes(chunk)

        r.align(4)

        # ── ReflexSystem / secondary motion / procedural nodes ─────────
        _read_skip_mess(r)

        # ── Secondary motion objects ───────────────────────────────────
        _read_secondary_motion(r)

        # ── Mesh descriptor lists (per LOD) ────────────────────────────
        lod_meshes = []
        for _ in range(lod_count):
            lod_meshes.append(_read_mesh_list(r))

        # ── Skip to vertex data ────────────────────────────────────────
        skip_14b = r.u32()

        if skip_14b > 0:
            # Search for 0xFFFFFFFF sentinel in the second half of the file
            file_size = os.path.getsize(path)
            fp.seek(0)
            big = fp.read()
            start_off = 0
            while True:
                found_off = big.find(b'\xff\xff\xff\xff', start_off)
                if found_off < file_size // 2:
                    start_off = found_off + 4
                else:
                    break
            found_off -= 36
            fp.seek(found_off)
        else:
            skip_14c = r.u32()
            if skip_14c > 0:
                r.skip_bytes(skip_14c * 128)
                r.align(16)

        d_start = r.u32()
        d_end = r.u32()

        if d_start == 0 and d_end == 0:
            d_end = 1

        # ── Read vertex + face data per LOD ────────────────────────────
        for lod_idx in range(d_end):
            lod = lod_meshes[lod_idx + d_start] if (lod_idx + d_start) < len(lod_meshes) else []
            _read_lod_geometry(r, model, lod, lod_idx, path, mat_count, materials)

    return model


def _read_lod_geometry(r, model, mesh_params_list, lod_idx, xbg_path,
                       mat_count, materials):
    """Read vertex and face data for one LOD level and append to model['meshes'].

    Volfin's code groups submeshes sharing the same totalVertCount into a
    single Blender mesh object.  We do the same: accumulate submeshes until
    vertSum == totalVertCount, then emit one mesh entry.
    """
    vert_sum = 0
    running_face_count = 0
    subtract_index = 0

    # Accumulators for the current combined mesh
    all_verts = []
    all_uvs = []
    all_uvs2 = []
    all_faces = []
    mat_zones = []
    material_count = 0

    # Volfin's import_mesh() starts with BH(1) + alignPosition(4) before
    # vertex data.  This u16 + alignment exists per-LOD.
    r.u16()            # BH(1) — unknown u16, possibly LOD index or flag
    pos = r.tell()
    r.seek((pos + 3) & ~3)  # alignPosition(4)

    # Pre-calculate the face block start
    # vertCount = 1 + (params[16] - params[15]) — already includes the +1
    vert_block_size = 0
    for mp in mesh_params_list:
        vert_block_size += mp['vertCount'] * mp['vertStride']

    face_block_start = r.tell() + vert_block_size + 4  # skip leading dword
    vert_block_offset = r.tell()

    # Read face count
    r.seek(face_block_start)
    face_count = r.u32() // 2  # block size / 2
    face_block_start = r.tell()
    r.seek(vert_block_offset)

    for mp_idx, mp in enumerate(mesh_params_list):
        r.seek(vert_block_offset)

        vert_stride = mp['vertStride']
        vert_count = mp['vertCount']
        face_count_local = mp['faceCount']
        face_offset = mp['faceOffset']
        total_vert_count = mp['totalVertCount']
        mat_id = mp['matID']

        if material_count == 0:
            subtract_index = face_offset

        mat_entry = {
            'matID': mat_id,
            'start': (face_offset - subtract_index) // 3,
            'end': ((face_offset - subtract_index) + face_count_local) // 3,
        }
        mat_zones.append(mat_entry)
        material_count += 1

        for _ in range(vert_count):
            # First 8 i16: [0-1] unused, [2-4] position(x,y,z), [6-7] UV1
            # Matches Volfin's Bh(8) — UVs come from the same read, not separate
            tmp = r.i16s(8)
            pos = (tmp[2] / 32768.0, tmp[3] / 32768.0, tmp[4] / 32768.0)
            all_verts.append(pos)

            uv = (tmp[6] / 65536.0 + 0.5, 1.0 - (tmp[7] / 65536.0 + 0.5))
            all_uvs.append(uv)

            # Remaining data depends on stride (stride = 16 bytes already read + remainder)
            if vert_stride == 40:
                r.skip_bytes(24)  # 12 i16
            elif vert_stride == 36:
                extra = r.i16s(10)
                all_uvs2.append((
                    extra[0] / 65536.0 + 0.5,
                    1.0 - (extra[1] / 65536.0 + 0.5),
                ))
            elif vert_stride == 32:
                extra = r.i16s(8)
                all_uvs2.append((
                    extra[0] / 65536.0 + 0.5,
                    1.0 - (extra[1] / 65536.0 + 0.5),
                ))
            elif vert_stride == 28:
                r.skip_bytes(12)  # 6 i16
            elif vert_stride == 24:
                r.skip_bytes(8)   # 4 i16
            elif vert_stride == 20:
                r.skip_bytes(4)   # 2 i16
            else:
                vlog.warn(f"  [wd2-xbg] unknown vertStride {vert_stride}")

        vert_sum += vert_count
        running_face_count += face_count_local
        vert_block_offset = r.tell()

        # When we've accumulated all vertices for this mesh group, read faces
        if vert_sum == total_vert_count:
            vert_sum = 0

            # Read face indices
            r.seek(face_block_start)
            faces = []
            for _ in range(running_face_count // 3):
                tri = r.u16s(3)
                faces.append(tri)
            face_block_start = r.tell()

            # Build material mapping
            face_materials = [0] * len(faces)
            if material_count > 0:
                for mz in mat_zones:
                    for j in range(mz['start'], mz['end']):
                        if j < len(face_materials):
                            face_materials[j] = mz['matID']

            # Determine material slot names
            slot_names = []
            for mz in mat_zones:
                mid = mz['matID']
                if mid < len(materials):
                    slot_names.append(materials[mid]['name'])
                else:
                    slot_names.append(f"mat_{mid}")

            # Emit mesh entry
            mesh_name = f"{model['name']}-{lod_idx}-{len(model['meshes'])}"
            mesh_entry = {
                'name': mesh_name,
                'verts': all_verts[:],
                'tris': faces,
                'uvs': all_uvs[:] if all_uvs else None,
                'uvs2': all_uvs2[:] if all_uvs2 else None,
                'loop_uvs': None,
                'normals': None,
                'loop_normals': None,
                'weights': {},
                'material': None,
                'face_materials': face_materials,
                'material_slots': slot_names,
            }
            model['meshes'].append(mesh_entry)

            # Reset accumulators
            all_verts = []
            all_uvs = []
            all_uvs2 = []
            all_faces = []
            mat_zones = []
            material_count = 0
            running_face_count = 0
            subtract_index = 0


# ── .skel file parser ─────────────────────────────────────────────────────

def _parse_skel(path):
    """Parse a WD2 .skel file into a list of bone dicts.

    Returns [{'name': str, 'parent': int, 'pos': (x,y,z),
              'quat': (x,y,z,w)}] or empty list on failure.
    """
    if not os.path.exists(path):
        return []

    try:
        with open(path, 'rb') as fp:
            sig = struct.unpack('<I', fp.read(4))[0]
            # The signature varies; we just try to read what we can.

            fp.seek(0x18)
            bone_block_len = struct.unpack('<I', fp.read(4))[0]

            name_start = fp.tell()
            fp.seek(bone_block_len, 1)

            names_count = struct.unpack('<I', fp.read(4))[0]
            bone_names = []
            for _ in range(names_count):
                offset = struct.unpack('<I', fp.read(4))[0]
                saved = fp.tell()
                fp.seek(name_start + offset)
                name = b''
                while True:
                    b = fp.read(1)
                    if not b or b == b'\x00':
                        break
                    name += b
                bone_names.append(name.decode('latin-1'))
                fp.seek(saved)

            # Skip hash list
            hashes_count = struct.unpack('<I', fp.read(4))[0]
            fp.seek(hashes_count * 4, 1)

            # Parent indices
            parent_count = struct.unpack('<I', fp.read(4))[0]
            parents = []
            for _ in range(parent_count):
                parents.append(struct.unpack('<i', fp.read(4))[0])

            # Bone transforms
            bone_count = struct.unpack('<I', fp.read(4))[0]
            bones = []
            for i in range(bone_count):
                loc_rot = struct.unpack('<8f', fp.read(32))
                parent_name = None
                pid = parents[i] if i < len(parents) else -1
                if pid != -1 and pid < len(bone_names):
                    parent_name = bone_names[pid]

                bones.append({
                    'name': bone_names[i] if i < len(bone_names) else f'bone_{i}',
                    'parent': pid,
                    'pos': (-loc_rot[0], loc_rot[1], loc_rot[2]),
                    'quat': (loc_rot[4], loc_rot[5], loc_rot[6], loc_rot[3] * -1),
                })

            return bones
    except Exception as exc:
        vlog.warn(f"  [wd2-xbg] .skel parse failed: {exc}")
        return []


# ── Public API ─────────────────────────────────────────────────────────────

def load_wd2_xbg(context, filepath, separate_primitives=True):
    """Parse a WD2 compiled .xbg and build it in Blender.

    Returns (model, armature_object_or_None).
    """
    model = parse_wd2_xbg(filepath)

    # Try to load companion .skel
    skel_path = os.path.splitext(filepath)[0] + '.skel'
    bones = _parse_skel(skel_path)
    if bones:
        model['bones'] = bones

    # Build in Blender
    from .import_wd2 import build_wd_model
    arm, mesh_objs = (build_wd_model(context, model) if bpy else (None, []))

    # Stamp source metadata on each mesh object
    for mi, obj in enumerate(mesh_objs):
        obj['wd2_src'] = filepath
        obj['wd2_mesh_index'] = mi

    # Join submeshes when separate_primitives is OFF
    if bpy is not None and not separate_primitives and len(mesh_objs) > 1:
        bpy.ops.object.select_all(action='DESELECT')
        for o in mesh_objs:
            o.select_set(True)
        context.view_layer.objects.active = mesh_objs[0]
        victim_meshes = [o.data for o in mesh_objs[1:]]
        bpy.ops.object.join()
        joined = context.active_object
        joined.name = model['name']
        joined['wd_joined'] = True
        for m in victim_meshes:
            if m.users == 0:
                bpy.data.meshes.remove(m)

    return model, arm
