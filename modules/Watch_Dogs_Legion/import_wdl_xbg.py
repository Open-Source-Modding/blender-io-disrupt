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
    """Read mesh descriptor list for one LOD (WDL 0x95 layout).

    Layout (verified against XbgParserD.cs + real character/vehicle files):
      u32 meshCount
      per mesh (0x84 = 132 bytes):
        bbox            40B   (10 × f32)
        u32 0           4B
        params          44B   (22 × u16):
          [2]  = matIndex
          [3]  = uvFlag
          [4]  = vertStride
          [14] = faceCount   (NOTE: differs from WD2 0x89 where [10]=faceCount)
          [16] = indexCount  (3 × faceCount for triangle lists)
          [20] = vertexCount (NOTE: WD2 0x89 puts matSubCount here)
        u32 packed      4B    (low16 = maxVertexIndex = vertexCount-1)
        u32 matSubCount 4B    (always 1 in test files)
        u32 meshIdx     4B    (1-based)
        u32 0           4B
        u32s(3)         12B   (vertex-buffer offsets; 0 for first mesh)
        u32s(5)         20B   (repeat: faceCount, indexCount, 0, vertexCount, maxV)
      then matSubCount material sub-entries, each:
        bbox            40B   (repeat of parent bbox)
        u32 hash        4B
        u32 nameLen     4B
        name            (nameLen bytes, null-padded to 4)
        u16s(2)         4B    (0x0000, 0xffff)
    """
    mesh_count = r.u32()
    meshes = []

    for _ in range(mesh_count):
        # 10 f32s: bounding box (min(3) + extent(3) + 4 padding/unused)
        bbox = r.f32s(10)
        bbox_min = tuple(bbox[0:3])
        bbox_ext = tuple(bbox[3:6])

        params = r.u16s(22)
        r.u32()  # packed maxVertexIndex (low16)

        vertStride = params[4]
        vertCount = params[20]
        faceCount = params[14]
        indexCount = params[16]
        faceOffset = 0
        totalVertCount = vertCount
        matID = params[2]
        UVFlag = params[3]

        mat_sub_count = r.u32()   # real material sub-entry count
        r.u32()                   # mesh index (1-based)
        r.u32()                   # 0
        r.u32s(3)                 # vertex-buffer offsets
        r.u32s(5)                 # repeated counts block

        mat_names = []
        for sub_i in range(mat_sub_count):
            r.skip_bytes(40)  # sub-entry bbox (repeat of parent)
            r.u32()           # hash
            s = r.u32()       # name length
            if 0 < s <= 128:
                raw = r.read(s)
                end = raw.find(b'\x00')
                if end >= 0:
                    raw = raw[:end]
                name = raw.decode('latin-1')
                r.align(4)
                r.u16s(2)
                # Multi-part meshes (matSub > 1) carry a 32-byte data tail
                # (3 vertex-buffer offsets + 5 counts) after every sub-entry
                # EXCEPT the last one.
                if mat_sub_count > 1 and sub_i < mat_sub_count - 1:
                    r.skip_bytes(32)
                mat_names.append(name)
            else:
                break

        meshes.append({
            'vertStride': vertStride,
            'vertCount': vertCount,
            'faceCount': faceCount,
            'indexCount': indexCount,
            'faceOffset': faceOffset,
            'totalVertCount': totalVertCount,
            'matID': matID,
            'UVFlag': UVFlag,
            'matCount': mat_sub_count,
            'matNames': mat_names,
            'bbox_min': bbox_min,
            'bbox_ext': bbox_ext,
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

        # ── LOD range for geometry region ──────────────────────────────
        # WDL 0x95 geometry data begins immediately after mesh lists.
        # No skip/d_start/d_end section (unlike WD2 0x89).
        d_start = 0
        d_end = lod_count

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
            try:
                _read_lod_geometry(r, model, lod, lod_idx, path, mat_count, materials)
            except Exception as exc:
                vlog.warn(f"  [wdl-xbg] LOD{lod_idx} geometry read failed: {exc}")
                break

    return model


def _read_lod_geometry(r, model, mesh_params_list, lod_idx, xbg_path,
                       mat_count, materials):
    """Read vertex and face data for one LOD (WDL 0x95 geometry layout).

    WDL 0x95 geometry region layout (verified on character/vehicle files):
      LOD header        32B   (u32 meshCount etc.)
      mesh blocks       index + attribute data (per-mesh, quad-split indices
                        and run-table encoded attributes; NOT in 0..N order)
      position buffer   contiguous i16 positions, mesh order 0..N-1

    Vertex positions (VERIFIED decode):
      buffer at lod_start + 32 + sum(all indexCount)*2
      per mesh at cumulative offset (voff += vertCount*vertStride)
      pos[i] = i16 / 32768.0 * bbox_ext[i] + bbox_min[i]
    """
    lod_start = r.tell()

    # Total index bytes across all meshes in this LOD -> position buffer start
    total_idx_bytes = sum(mp['indexCount'] * 2 for mp in mesh_params_list)
    pos_buf_start = lod_start + 32 + total_idx_bytes

    all_verts = []
    all_uvs = []
    all_uvs2 = []
    all_faces = []
    mat_zones = []
    material_count = 0

    # --- Read positions from the contiguous position buffer (VERIFIED) ---
    voff = pos_buf_start
    mesh_positions = []
    for mp in mesh_params_list:
        vc = mp['vertCount']
        stride = mp['vertStride']
        bmin = mp.get('bbox_min', (0.0, 0.0, 0.0))
        bext = mp.get('bbox_ext', (1.0, 1.0, 1.0))
        verts = []
        for i in range(vc):
            x, y, z = _read_i16s(r, voff + i * stride, 3)
            px = x / 32768.0 * bext[0] + bmin[0]
            py = y / 32768.0 * bext[1] + bmin[1]
            pz = z / 32768.0 * bext[2] + bmin[2]
            verts.append((px, py, pz))
        mesh_positions.append(verts)
        voff += vc * stride

    # --- Faces (best-effort: quad-split index buffers in mesh blocks) ---
    mesh_faces = _try_decode_faces(r, lod_start, mesh_params_list)

    for mp_idx, mp in enumerate(mesh_params_list):
        vert_stride = mp['vertStride']
        vert_count = mp['vertCount']
        mat_id = mp['matID']

        submesh_vert_start = lod_start
        all_verts.extend(mesh_positions[mp_idx])

        if material_count == 0:
            subtract_index = 0
        mat_entry = {
            'matID': mat_id,
            'start': 0,
            'end': vert_count,
        }
        mat_zones.append(mat_entry)
        material_count += 1

        all_uvs.extend([(0.5, 0.5)] * vert_count)
        all_uvs2.extend([(0.5, 0.5)] * vert_count)

        faces = mesh_faces.get(mp_idx, [])
        face_materials = [mp['matID']] * len(faces)

        slot_names = []
        for mz in mat_zones:
            mid = mz['matID']
            if mid < len(materials):
                slot_names.append(materials[mid]['name'])
            else:
                slot_names.append(f"mat_{mid}")

        mesh_name = f"{model['name']}-{lod_idx}-{mp_idx}"
        mesh_entry = {
            'name': mesh_name,
            'verts': mesh_positions[mp_idx],
            'tris': faces,
            'uvs': None,
            'uvs2': None,
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


def _read_i16s(r, off, n):
    """Read n int16 values at absolute file offset (does not disturb seek)."""
    saved = r.tell()
    r.seek(off)
    vals = r.i16s(n)
    r.seek(saved)
    return vals


def _read_u32s(r, off, n):
    """Read n uint32 values at absolute file offset (does not disturb seek)."""
    saved = r.tell()
    r.seek(off)
    vals = r.u32s(n)
    r.seek(saved)
    return vals


def _try_decode_faces(r, lod_start, mesh_params_list):
    """Best-effort decode of quad-split index buffers in the mesh block region.

    Returns {mesh_idx: [(a,b,c), ...]} with faces decoded per mesh where the
    mesh's index block can be identified (plain u16 quad-split indices).
    Meshes whose index data is run-table/compressed are left with no faces.

    Each mesh block has the form:
        [ic u16 quad-split indices] [32B header] [attribute bytes]
    The blocks are stored in a non-sequential mesh order, so each block is
    matched to a mesh by checking the index values are all < that mesh's
    vertex count.
    """
    meshes = list(mesh_params_list)
    result = {}
    pos = lod_start + 32
    max_pos = pos + sum(m['indexCount'] for m in meshes) * 2
    remaining = {i: m for i, m in enumerate(meshes)}
    while remaining and pos < max_pos:
        matched_idx = None
        matched = None
        for i, m in remaining.items():
            ic = m['indexCount']
            try:
                vals = _read_i16s(r, pos, ic)
            except Exception:
                continue
            if vals and max(vals) < m['vertCount']:
                matched_idx, matched = i, m
                break
        if matched is None:
            break
        ic = matched['indexCount']
        vals = _read_i16s(r, pos, ic)
        vc = matched['vertCount']
        faces = []
        for i in range(0, max(0, ic - 5), 6):
            a, b, c, _, d, _ = vals[i:i + 6]
            if a < vc and b < vc and c < vc and d < vc:
                faces.append((a, b, c))
                faces.append((c, d, a))
        result[matched_idx] = faces
        # advance: index bytes + 32B header + attribute bytes (header[1])
        idx_end = pos + ic * 2
        try:
            hdr = _read_u32s(r, idx_end, 2)
            attr = hdr[1]
            pos = idx_end + 32 + attr
        except Exception:
            pos = idx_end + 32
        del remaining[matched_idx]
    return result


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
    from ..Core.disrupt_common import build_blender_scene, join_submeshes
    arm, mesh_objs = (build_blender_scene(context, model) if bpy else (None, []))

    # Stamp source metadata on each mesh object
    for mi, obj in enumerate(mesh_objs):
        obj['wdl_src'] = filepath
        obj['wdl_mesh_index'] = mi

    # Join submeshes when separate_primitives is OFF
    if bpy is not None and not separate_primitives and len(mesh_objs) > 1:
        join_submeshes(context, mesh_objs, model['name'])

    return model, arm
