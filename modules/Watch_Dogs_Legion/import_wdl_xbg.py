"""Watch Dogs Legion compiled .xbg importer (self-contained).

WDL ships compiled models as binary .xbg files with a MOEG header
(version 0x95/0x46).  The companion .skel file holds the skeleton.

Adapted from Watch_Dogs_2/import_wd2_xbg.py with vertex offset tracking
for injection support.
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
_WDL_VERSION = (0x95, 0x46)


# ── Parser helpers (shared with WD2) ──────────────────────────────────────

def _read_odd_table(r):
    loc_count = r.u32()
    for _ in range(loc_count):
        r.skip_bytes(32)


def _read_skip_mess(r):
    count = r.u32()
    if count == 0:
        return

    for _ in range(count):
        r.skip_bytes(20)
        entry_type = r.u32()

        if entry_type == 2:
            for _group in range(3):
                c = r.u32()
                if _group == 0:
                    for _sub in range(2):
                        sc = r.u32()
                        for _ in range(sc):
                            r.u32()
                            s = r.u32()
                            r.skip_bytes(s)
                            r.align(16)
                            r.skip_bytes(17)
                    c2 = r.u32()
                    for _ in range(c2):
                        r.u32()
                        s = r.u32()
                        r.skip_bytes(s)
                        r.align(16)
                        r.skip_bytes(23)
                else:
                    for _ in range(c):
                        r.u32()
                        s = r.u32()
                        r.skip_bytes(s)
                        r.align(16)
                        r.skip_bytes(23)

            c = r.u32()
            for _ in range(c):
                r.u32()
                c2 = r.u32()
                r.skip_bytes(c2 * 5)

            c = r.u32()
            for _ in range(c):
                r.u32()
                c2 = r.u32()
                r.skip_bytes(c2 * 9)

            c = r.u32()
            for _ in range(c):
                r.u32()
                c2 = r.u32()
                r.skip_bytes(c2 * 9)

            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(4)
                r.skip_bytes(4)

            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(4)

            r.u32()
            r.u32()
            r.u32()
            r.u32()
        else:
            chunk = r.u32()
            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(16)
                r.skip_bytes(17)

            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(16)
                r.skip_bytes(23)

            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(16)
                r.skip_bytes(23)

            chunk = r.u32()
            c = r.u32()
            for _ in range(c):
                r.skip_bytes(12)
                r.skip_bytes(4)

            chunk = r.u32()
            c = r.u32()
            for _ in range(c):
                r.skip_bytes(44)

            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(4)
                r.skip_bytes(4)

            c = r.u32()
            for _ in range(c):
                r.u32()
                s = r.u32()
                r.skip_bytes(s)
                r.align(4)

            c = r.u32()
            r.skip_bytes(c * 6)
            r.align(4)

            chunk = r.u32()
            c = r.u32()
            r.skip_bytes(c * 6)

            chunk = r.u32()
            r.align(4)


def _read_mesh_list(r):
    """Read mesh descriptor list for one LOD. Returns list of dicts."""
    mesh_count = r.u32()
    meshes = []

    for _ in range(mesh_count):
        r.skip_bytes(40)  # 10 f32s: bounding box / LOD distances

        params = r.u16s(22)
        r.u32()

        vertStride = params[4]
        vertCount = 1 + params[16] - params[15]
        faceCount = params[10]
        faceOffset = params[12]
        totalVertCount = params[14]
        matID = params[2]
        UVFlag = params[3]
        matCount = params[20]

        mat_names = []
        for _ in range(matCount):
            r.skip_bytes(34)
            s = r.u32()
            if 0 < s <= 128:
                name = r.str()
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
    count = r.u32()
    for _ in range(count):
        b = r.u16s(4)
        r.f32()
        if b[1] == 6:
            r.u32s(3)


# ── WDL .xbg parser (with vertex offset tracking) ─────────────────────────

def parse_wdl_xbg(path):
    """Parse a WDL compiled .xbg into the neutral model dict.

    Extends the WD2 parser with file offset tracking for each mesh's
    vertex data, enabling in-place injection.

    Returns dict with keys: source, name, bones, meshes, _layout.
    Each mesh entry includes 'vert_file_off' for injection.
    """
    model = {
        'source': 'wdl',
        'name': os.path.splitext(os.path.basename(path))[0],
        'bones': [],
        'meshes': [],
        '_layout': {},
    }

    with open(path, 'rb') as fp:
        r = _Reader(fp)

        # ── Header ─────────────────────────────────────────────────────
        magic = r.read(4)
        if magic != _MAGIC:
            raise ValueError(
                "not a WDL .xbg (magic %r, expected %r)"
                % (magic, _MAGIC))

        ver_major = r.u16()
        ver_minor = r.u16()
        if (ver_major, ver_minor) != _WDL_VERSION:
            raise ValueError(
                "unexpected .xbg version 0x%04X/0x%04X "
                "(expected WDL 0x95/0x46)"
                % (ver_major, ver_minor))

        # ── Header data ────────────────────────────────────────────────
        r.skip_bytes(16)
        _unk_count = r.u32()
        odd_flag = r.u32()

        for _ in range(odd_flag):
            _read_odd_table(r)

        r.skip_bytes(76)

        lod_count = r.u32()

        for _ in range(lod_count):
            r.u32s(2)

        # ── Materials ──────────────────────────────────────────────────
        # Layout varies between file types (character vs vehicle, …).
        # Try the standard WD2 layout first; fall back to scanning for
        # the material path string if the read mat_count is garbage.
        _pos_lod_end = r.tell()
        _buf = fp.read(); fp.seek(_pos_lod_end)
        r.u32s(3)
        mat_count = r.u32()
        r.u32()

        _mark = _buf.find(b'graphics\\_materials\\')
        if _mark > 20:
            _scan_mc = struct.unpack_from('<I', _buf, _mark - 16)[0]
            if 0 < _scan_mc < 200 and (_scan_mc != mat_count or mat_count > 100):
                vlog.log(f"  [wdl-xbg] mat_count override: {mat_count} → {_scan_mc}")
                mat_count = _scan_mc
                r.seek(_pos_lod_end + _mark - 12)
                r.u32()

        materials = []
        tag_count = 0
        for mi in range(mat_count):
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
            r.u32()
            r.str()
            r.align(4)
            r.u32()

        r.align(4)

        # ── Skeleton ───────────────────────────────────────────────────
        skeleton_count = r.u32()
        for _ in range(skeleton_count):
            r.align(4)
            r.u32()
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

        # Skeleton part 2 — bone names
        r.align(4)
        chunk = r.u32()
        if chunk == 1:
            bone_count = r.u32()
            for _ in range(bone_count):
                r.skip_bytes(52)
                r.str()
                r.align(4)

        # ── Object-to-node matrices ────────────────────────────────────
        r.u32()
        matrix_count = r.u32()
        r.align(16)
        r.skip_bytes(matrix_count * 64)

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

        # Store layout info for injection
        model['_layout'] = {
            'mat_count': mat_count,
            'materials': materials,
            'lod_count': lod_count,
            'vertex_data_start': r.tell(),
        }

        # ── Read vertex + face data per LOD ────────────────────────────
        for lod_idx in range(d_end):
            lod = lod_meshes[lod_idx + d_start] if (lod_idx + d_start) < len(lod_meshes) else []
            _read_lod_geometry(r, model, lod, lod_idx, path, mat_count, materials)

    return model


def _read_lod_geometry(r, model, mesh_params_list, lod_idx, xbg_path,
                       mat_count, materials):
    """Read vertex and face data for one LOD, tracking file offsets."""
    vert_sum = 0
    running_face_count = 0
    subtract_index = 0

    all_verts = []
    all_uvs = []
    all_uvs2 = []
    all_faces = []
    mat_zones = []
    material_count = 0

    # Pre-calculate the face block start
    vert_block_size = 0
    for mp in mesh_params_list:
        blocksize = 1 + (mp['vertCount'])
        vert_block_size += blocksize * mp['vertStride']

    face_block_start = r.tell() + vert_block_size + 4
    vert_block_offset = r.tell()

    # Read face count
    r.seek(face_block_start)
    face_count = r.u32() // 2
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

        # Record the file offset where this submesh's vertices start
        submesh_vert_start = r.tell()

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
            tmp = r.i16s(8)
            pos = (tmp[2] / 32768.0, tmp[3] / 32768.0, tmp[4] / 32768.0)
            all_verts.append(pos)

            uvs = r.i16s(2)
            uv = (uvs[0] / 65536.0 + 0.5, 1.0 - (uvs[1] / 65536.0 + 0.5))
            all_uvs.append(uv)

            if vert_stride == 40:
                r.skip_bytes(24)
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
                r.skip_bytes(12)
            elif vert_stride == 24:
                r.skip_bytes(8)
            elif vert_stride == 20:
                r.skip_bytes(4)
            else:
                vlog.warn(f"  [wdl-xbg] unknown vertStride {vert_stride}")

        vert_sum += vert_count
        running_face_count += face_count_local
        vert_block_offset = r.tell()

        if vert_sum == total_vert_count:
            vert_sum = 0

            r.seek(face_block_start)
            faces = []
            for _ in range(running_face_count // 3):
                tri = r.u16s(3)
                faces.append(tri)
            face_block_start = r.tell()

            face_materials = [0] * len(faces)
            if material_count > 0:
                for mz in mat_zones:
                    for j in range(mz['start'], mz['end']):
                        if j < len(face_materials):
                            face_materials[j] = mz['matID']

            slot_names = []
            for mz in mat_zones:
                mid = mz['matID']
                if mid < len(materials):
                    slot_names.append(materials[mid]['name'])
                else:
                    slot_names.append(f"mat_{mid}")

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
                'vert_file_off': submesh_vert_start,
                'vert_stride': vert_stride,
                'vert_count': vert_count,
            }
            model['meshes'].append(mesh_entry)

            all_verts = []
            all_uvs = []
            all_uvs2 = []
            all_faces = []
            mat_zones = []
            material_count = 0
            running_face_count = 0
            subtract_index = 0


# ── .skel file parser ─────────────────────────────────────────────────────

def parse_wdl_skel(path):
    """Parse a WDL .skel file into a list of bone dicts.

    Returns [{'name': str, 'parent': int, 'pos': (x,y,z),
              'quat': (x,y,z,w)}] or empty list on failure.
    """
    if not os.path.exists(path):
        return []

    try:
        with open(path, 'rb') as fp:
            sig = struct.unpack('<I', fp.read(4))[0]

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

            hashes_count = struct.unpack('<I', fp.read(4))[0]
            fp.seek(hashes_count * 4, 1)

            parent_count = struct.unpack('<I', fp.read(4))[0]
            parents = []
            for _ in range(parent_count):
                parents.append(struct.unpack('<i', fp.read(4))[0])

            bone_count = struct.unpack('<I', fp.read(4))[0]
            bones = []
            for i in range(bone_count):
                loc_rot = struct.unpack('<8f', fp.read(32))
                pid = parents[i] if i < len(parents) else -1

                bones.append({
                    'name': bone_names[i] if i < len(bone_names) else f'bone_{i}',
                    'parent': pid,
                    'pos': (-loc_rot[0], loc_rot[1], loc_rot[2]),
                    'quat': (loc_rot[4], loc_rot[5], loc_rot[6], loc_rot[3] * -1),
                })

            return bones
    except Exception as exc:
        vlog.warn(f"  [wdl-xbg] .skel parse failed: {exc}")
        return []


# ── Public API ─────────────────────────────────────────────────────────────

def load_wdl_xbg(context, filepath, separate_primitives=True):
    """Parse a WDL compiled .xbg and build it in Blender.

    Returns (model, armature_object_or_None).
    """
    model = parse_wdl_xbg(filepath)

    # Try to load companion .skel
    skel_path = os.path.splitext(filepath)[0] + '.skel'
    bones = parse_wdl_skel(skel_path)
    if bones:
        model['bones'] = bones

    # Build in Blender
    from ..Watch_Dogs_2.import_wd2 import build_wd_model
    arm, mesh_objs = (build_wd_model(context, model) if bpy else (None, []))

    # Stamp source metadata on each mesh object
    for mi, obj in enumerate(mesh_objs):
        obj['wdl_src'] = filepath
        obj['wdl_mesh_index'] = mi

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
