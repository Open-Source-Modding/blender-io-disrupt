"""Watch Dogs Legion .xbg (MOEG 0x95/0x46) exporter.

Writes a fresh WDL ``.xbg`` from Blender mesh objects by synthesising every
section of the sequential IBinaryArchive stream (see import_wdl_xbg.py for
the parser that this writer mirrors field-for-field).

WDL 0x95/0x46 section order (each round-trip-able, sizes measured on real
files):

  1. Header           MOEG magic, ver 0x95/0x46, 16B hash, unk, odd_flag
  2. Odd tables       (usually empty)
  3. Params           76 bytes (bounding info, flags)
  4. LOD count        u32 + per-LOD u32s(2) distance pairs
  5. Materials        u32s(3) + mat_count + per-mat: hash + path + name_hash
                      + name + tag_count + tags
  6. Skeleton         skeleton_count + bone_id/flag (empty for static)
  7. Obj2Node matrices  u32 + count + align16 + count*64B
  8. Skip block       u32 chunk size + data
  9. ReflexSystem     via _read_skip_mess (empty)
 10. SecondaryMotion  via _read_secondary_motion (empty)
 11. Mesh descriptors per-LOD (0x84 per mesh + mat sub-entries)
 12. Geometry data    per-LOD: 32B header + vertex buffers

This exporter synthesises a minimal-but-valid file: a single LOD with the
given mesh(es).  Sections 5-10 are emitted empty or with the supplied
materials (no physics / procedural / skeleton), which is sufficient for
static props.  Positions use per-axis bbox quantisation and UVs use the
i16 codec matching the importer's decode formulas.

Vertex quantisation (WDL-specific, verified against import):
    pos[i] = i16 / 32768.0 * bbox_ext[i] + bbox_min[i]
    uv.u    = i16 / 65536.0 + 0.5
    uv.v    = i16 / 65536.0 + 0.5  (V is flipped in file)
"""

import os
import struct

try:
    import bpy
    import mathutils
except Exception:           # standalone (testing) mode
    bpy = None
    mathutils = None


# ── IBinaryArchive writer (PADDING_IBINARYARCHIVE alignment) ────────────────

class _Writer:
    """Mirrors import_wdl_xbg._Reader: u16/u32/f32/mat4 pad to their size
    before writing; u8/bool are unaligned; strings = aligned u32 length +
    bytes.  Identical to the WD1 export_wd1._Writer class."""

    def __init__(self):
        self.b = bytearray()

    def tell(self):
        return len(self.b)

    def pad(self, n):
        self.b += b'\x00' * ((n - len(self.b) % n) % n)

    def u8(self, v):
        self.b += struct.pack('<B', v & 0xFF)

    def boolean(self, v):
        self.u8(1 if v else 0)

    def u16(self, v):
        self.pad(2)
        self.b += struct.pack('<H', v & 0xFFFF)

    def u32(self, v):
        self.pad(4)
        self.b += struct.pack('<I', v & 0xFFFFFFFF)

    def f32(self, v):
        self.pad(4)
        self.b += struct.pack('<f', float(v))

    def vec(self, vs):
        self.pad(4)
        self.b += struct.pack('<%df' % len(vs), *vs)

    def mat4(self, m):
        self.pad(16)
        self.b += struct.pack('<16f', *m)

    def string(self, s):
        self.u32(len(s))
        self.b += s.encode('latin-1')

    def name_id(self, s):
        """CMeshNameID = u32 CStringID hash + Wstr string.  The hash is
        emitted as a stand-in (the parser ignores it and matches by name);
        string() writes its own u32 length prefix."""
        self.u32(0)
        self.string(s)

    def count(self, items):
        self.u32(len(items))

    def raw(self, data):
        self.b += data


# ── Section writers ─────────────────────────────────────────────────────────

def _write_header(w):
    """Section 1.  WDL MOEG header (0x95/0x46).

    Layout: magic(4) + major(u16) + minor(u16) + hash(16) + unk(u32) +
            odd_flag(u32)
    """
    w.b += b'MOEG'
    w.u16(0x0095)
    w.u16(0x0046)
    # 16-byte hash (zeroed — game doesn't validate on load)
    w.raw(b'\x00' * 16)
    w.u32(0)   # unk_count
    w.u32(0)   # odd_flag (0 = no odd tables)


def _write_odd_tables(w):
    """Section 2.  Odd tables (empty — odd_flag was 0 in header)."""
    pass


def _write_params(w, bsphere, bbox):
    """Section 3.  76-byte params block.

    Contains bounding sphere/box and some flags.  We write the actual
    bounding data where the importer expects it; the remaining bytes are
    zeroed.  The importer skips 76 raw bytes here, but the game engine
    may use some of them, so we fill in what we know.
    """
    # The 76 bytes come right after the odd tables.  From real WDL files:
    # bytes 0-11:  bounding sphere (cx, cy, cz, r) as 3 f32 + 1 f32
    # bytes 12-35: bounding box min(3) + max(3) as 6 f32
    # bytes 36-75: flags / padding (zeroed)
    w.vec(bsphere[:3])
    w.f32(bsphere[3])
    w.vec(bbox[:3])
    w.vec(bbox[3:])
    # Pad to 76 bytes total (4*3 + 4*1 + 4*3 + 4*3 = 48, need 28 more)
    w.raw(b'\x00' * 28)


def _write_lod_info(w, lod_count, lod_dists):
    """Section 4.  LOD count + per-LOD distance pairs."""
    w.u32(lod_count)
    for d in lod_dists:
        w.f32(d)       # switch distance
        w.u32(0)       # unk


def _write_materials(w, materials):
    """Section 5.  Material list.

    Per the parser: u32s(3) + mat_count + u32 + per-mat
    (hash + path + align + name_hash + name + align + tag_count + tags).
    """
    w.u32(0); w.u32(0); w.u32(0)    # u32s(3) header padding
    w.u32(len(materials))
    w.u32(0)                          # unk after count

    for mat in materials:
        w.u32(0)                      # mat_hash (placeholder)
        w.string(mat['path'])
        w.pad(4)
        w.u32(0)                      # mat_name_hash
        w.string(mat['name'])
        w.pad(4)
        w.u32(0)                      # tag_count (no tags)

    w.pad(4)


def _write_skeleton(w):
    """Section 6.  Skeleton (empty for static props).

    The WDL skeleton section contains: skeleton_count entries, then
    bone_id/flag data, then bone names.  For a fresh export without
    an armature, we write the minimal empty skeleton.
    """
    w.u32(0)              # skeleton_count = 0
    w.pad(2)
    w.u16(0)              # bone_id_count = 0
    w.u16(0)              # bone_flag = 0
    # When bone_flag == 0 and bone_id_count == 0, the parser skips 8 bytes
    w.raw(b'\x00' * 8)
    # Skeleton part 2 — bone names
    w.pad(4)
    w.u32(1)              # chunk = 1 (present)
    w.u32(0)              # bone_count = 0


def _write_obj2node(w):
    """Section 7.  Object-to-node matrices (empty)."""
    w.u32(0)              # unk
    w.u32(0)              # matrix_count = 0
    w.pad(16)


def _write_skip_block(w):
    """Section 8.  Skip block (empty)."""
    w.u32(0)              # chunk = 0 (no data)


def _write_reflex_system(w):
    """Section 9.  ReflexSystem / secondary motion / procedural nodes.

    Emitted as an empty structure matching what _read_skip_mess expects
    when encountering a zero count at the start.
    """
    # The parser calls _read_skip_mess(r) which reads u32 count.
    # count == 0 means "no entries" and returns immediately.
    w.u32(0)


def _write_secondary_motion(w):
    """Section 10.  Secondary motion objects (empty)."""
    w.u32(0)              # count = 0


def _write_mesh_descriptors(w, lod_meshes):
    """Section 11.  Mesh descriptor lists (per LOD).

    Per-mesh descriptor is 0x84 (132) bytes:
        bbox            40B   (10 x f32)
        u32 0            4B
        params          44B   (22 x u16)
        u32 packed        4B   (low16 = maxVertexIndex)
        u32 matSubCount   4B
        u32 meshIdx       4B   (1-based)
        u32 0             4B
        u32s(3)          12B   (vertex-buffer offsets)
        u32s(5)          20B   (repeat counts)

    Then per mat-sub: bbox(40B) + hash(u32) + nameLen(u32) + name + u16s(2).
    """
    for meshes in lod_meshes:
        w.u32(len(meshes))
        for mi, m in enumerate(meshes):
            # Bounding box: 10 f32s = min(3) + extent(3) + unused(4)
            bbox = m['bbox']
            bbox_min = bbox[:3]
            bbox_max = bbox[3:]
            bbox_ext = [bbox_max[i] - bbox_min[i] for i in range(3)]
            w.vec(bbox_min)
            w.vec(bbox_ext)
            w.vec([0.0] * 4)        # padding / unused

            w.u32(0)                 # unk zero

            # 22 x u16 params
            params = [0] * 22
            params[2] = m['mat_id']          # matIndex
            params[3] = m.get('uv_flag', 1)  # uvFlag
            params[4] = m['stride']          # vertStride
            params[14] = m['face_count']     # faceCount
            params[16] = m['index_count']    # indexCount
            params[20] = m['vert_count']     # vertexCount
            for p in params:
                w.u16(p)

            # packed maxVertexIndex (low 16 bits)
            w.u32(m['vert_count'] - 1)
            # matSubCount (1 = single material per mesh)
            w.u32(1)
            # meshIdx (1-based)
            w.u32(mi + 1)
            w.u32(0)                 # unk

            # 3 x u32 vertex-buffer offsets (all 0 — first mesh in LOD)
            w.u32(0); w.u32(0); w.u32(0)

            # 5 x u32 repeated counts
            w.u32(m['face_count'])
            w.u32(m['index_count'])
            w.u32(0)
            w.u32(m['vert_count'])
            w.u32(m['vert_count'] - 1)

        # Material sub-entries for each mesh
        for mi, m in enumerate(meshes):
            bbox = m['bbox']
            bbox_min = bbox[:3]
            bbox_max = bbox[3:]
            bbox_ext = [bbox_max[i] - bbox_min[i] for i in range(3)]
            w.vec(bbox_min)
            w.vec(bbox_ext)
            w.vec([0.0] * 4)

            w.u32(0)                 # hash
            mat_name = m.get('mat_name', 'default')
            w.string(mat_name)
            w.pad(4)
            w.u16(0x0000)
            w.u16(0xFFFF)


def _write_geometry(w, lod_meshes):
    """Section 12.  Geometry data for one LOD.

    WDL 0x95 geometry layout:
        LOD header      32B
        vertex buffers  per-mesh contiguous vertex data
    """
    # LOD header (32 bytes): mesh_count(u32) + 7 x u32 padding
    w.u32(len(lod_meshes))
    for _ in range(7):
        w.u32(0)

    # Vertex buffers (contiguous, per-mesh)
    for m in lod_meshes:
        w.raw(m['vdata'])


# ── Vertex encoding helpers ─────────────────────────────────────────────────

def _clamp_i16(v):
    return max(-32768, min(32767, int(round(v))))


def _enc_pos_wdl(buf, co, bbox_min, bbox_ext):
    """Encode position using WDL per-axis bbox quantisation.

    Decode (from import): px = i16 / 32768.0 * bext[i] + bmin[i]
    Encode (inverse):     i16 = (px - bmin[i]) / bext[i] * 32768.0

    Written as 8 x i16: 4 unused + x + y + z + w (matches vertex layout
    at bytes 0..15 of the WDL vertex format).
    """
    for _ in range(4):
        buf += struct.pack('<h', 0)       # 4 unused i16 slots
    for i in range(3):
        ext = bbox_ext[i] if bbox_ext[i] > 1e-12 else 1.0
        val = (co[i] - bbox_min[i]) / ext * 32768.0
        buf += struct.pack('<h', _clamp_i16(val))
    buf += struct.pack('<h', 0)           # pos_w (unused)


def _enc_uv_wdl(buf, uv):
    """Encode UV using WDL codec.

    Decode (from inject): u = i16 / 65536.0 + 0.5
    Encode (inverse):     i16 = (u - 0.5) * 65536.0

    V is flipped in the file (Blender V -> file V = 1.0 - Blender V).
    """
    u, v = uv[0], 1.0 - uv[1]          # flip V
    buf += struct.pack('<h', _clamp_i16((u - 0.5) * 65536.0))
    buf += struct.pack('<h', _clamp_i16((v - 0.5) * 65536.0))


# ── Blender helpers ─────────────────────────────────────────────────────────

def _object_uvs(me, layer=0):
    """Return per-vertex UV list (specified UV layer), or None."""
    if len(me.uv_layers) <= layer:
        return None
    uv = me.uv_layers[layer]
    out = [(0.0, 0.0)] * len(me.vertices)
    cnt = [0] * len(me.vertices)
    for li, loop in enumerate(me.loops):
        vi = loop.vertex_index
        u, v = uv.data[li].uv
        out[vi] = (out[vi][0] + u, out[vi][1] + v)
        cnt[vi] += 1
    for vi in range(len(out)):
        if cnt[vi]:
            out[vi] = (out[vi][0] / cnt[vi], out[vi][1] / cnt[vi])
    return out


def _material_names(ob):
    out = []
    for slot in ob.material_slots:
        if slot.material:
            out.append(slot.material.name)
    return out


def _collect_materials(objects):
    """Collect unique material entries (path + name) from objects."""
    seen = []
    for ob in objects:
        for name in _material_names(ob):
            if name not in [s['name'] for s in seen]:
                seen.append({
                    'name': name,
                    'path': 'graphics\\_materials\\%s.material.bin' % name,
                })
    if not seen:
        seen.append({
            'name': 'default',
            'path': 'graphics\\_materials\\default.material.bin',
        })
    return seen


def _compute_bsphere(bmin, bmax):
    c = [(bmin[i] + bmax[i]) / 2.0 for i in range(3)]
    r = max(abs(bmax[i] - c[i]) for i in range(3))
    return (c[0], c[1], c[2], r)


def _mesh_bbox(verts):
    bmin = [min(v[i] for v in verts) for i in range(3)]
    bmax = [max(v[i] for v in verts) for i in range(3)]
    return bmin + bmax


# ── Public entry point ──────────────────────────────────────────────────────

def export_wdl(path, mesh_objects, *, materials=None, name=None,
               lod_dists=None):
    """Write a fresh WDL .xbg from a list of Blender mesh objects.

    Each object is treated as one submesh of a single LOD.  Positions use
    per-axis bbox quantisation; UVs use the WDL i16 codec.  Materials,
    skeleton and physics sections are emitted minimal (empty).

    ``materials``: optional list of dicts with 'name' and 'path' keys.
    ``lod_dists``: LOD switch distances (default [30.0]).

    Returns the number of meshes written.
    """
    if bpy is None:
        raise RuntimeError("bpy unavailable")
    if not mesh_objects:
        raise ValueError("no mesh objects to export")

    # ── gather geometry ─────────────────────────────────────────────────
    combined_min = [float('inf')] * 3
    combined_max = [float('-inf')] * 3
    for ob in mesh_objects:
        me = ob.data
        for v in me.vertices:
            co = ob.matrix_world @ mathutils.Vector(v.co)
            for i in range(3):
                combined_min[i] = min(combined_min[i], co[i])
                combined_max[i] = max(combined_max[i], co[i])

    bbox = combined_min + combined_max
    bbox_ext = [combined_max[i] - combined_min[i] for i in range(3)]
    bsphere = _compute_bsphere(combined_min, combined_max)

    # WDL stride: 8 x i16 (pos header) + 2 x i16 (UV) = 20 bytes
    stride = 20

    meshes = []
    for ob in mesh_objects:
        me = ob.data
        me.calc_loop_triangles()
        verts = [(ob.matrix_world @ mathutils.Vector(v.co)) for v in me.vertices]
        uvs = _object_uvs(me)

        vcount = len(verts)

        # Encode vertex data
        mv = bytearray()
        for vi, co in enumerate(verts):
            _enc_pos_wdl(mv, co, combined_min, bbox_ext)
            _enc_uv_wdl(mv, uvs[vi] if uvs else (0.5, 0.5))

        # Encode index data (face winding: Blender CCW -> file CW = a,c,b)
        tri_count = len(me.loop_triangles)
        mi = bytearray()
        for lt in me.loop_triangles:
            a, b, c = lt.vertices
            mi += struct.pack('<3H', a, c, b)

        # Material
        mat_names = _material_names(ob)
        mat_name = mat_names[0] if mat_names else 'default'

        meshes.append({
            'bbox': bbox,
            'vert_count': vcount,
            'stride': stride,
            'face_count': tri_count,
            'index_count': tri_count * 3,
            'mat_id': 0,
            'mat_name': mat_name,
            'uv_flag': 1,
            'vdata': bytes(mv),
        })

    # ── materials ───────────────────────────────────────────────────────
    mat_list = materials or _collect_materials(mesh_objects)

    # ── LOD setup ───────────────────────────────────────────────────────
    if lod_dists is None:
        lod_dists = [30.0]
    lod_count = 1
    lod_meshes = [meshes]  # single LOD containing all meshes

    # ── write binary ────────────────────────────────────────────────────
    w = _Writer()
    _write_header(w)
    _write_odd_tables(w)
    _write_params(w, bsphere, bbox)
    _write_lod_info(w, lod_count, lod_dists)
    _write_materials(w, mat_list)
    _write_skeleton(w)
    _write_obj2node(w)
    _write_skip_block(w)
    _write_reflex_system(w)
    _write_secondary_motion(w)
    _write_mesh_descriptors(w, lod_meshes)
    _write_geometry(w, lod_meshes)

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(bytes(w.b))

    return len(meshes)
