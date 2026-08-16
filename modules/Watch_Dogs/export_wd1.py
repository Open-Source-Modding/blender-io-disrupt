"""Watch Dogs 1 native .xbg (GEOM 97.50) exporter.

Writes a fresh WD1 ``.xbg`` from Blender mesh objects by synthesising every
section of the sequential IBinaryArchive stream (see import_wd.py for the
format and the parser that this writer mirrors field-for-field).

Section order (each round-trip-able, sizes as measured on real files):
  1. Header             MOEG magic, ver 97/50, 16-byte hash, unk, SMemoryNeed
  2. SceneGeometryParams pos offset/scale, bSphere, bBox, nLods + dist, kill
  3. MaterialResources   unk0 + per-LOD skip + CPathID + path per material
  4. MaterialSlotToIndex name_id + u32 per slot
  5. SkinNames           name_id per skin
  6. BonePalettes        n + u16 bone index each
  7. SkelResources       present bool, n bones, o2n mats
  8. ReflexSystem        present bool + size-prefixed FCB blob
  9. SecondaryMotionObjects
 10. ProceduralNodes
 11. LODs                per-LOD mesh descriptors (drawcalls + ranges)
 12. SGfxBuffers         vertex + index buffers
 13. GeomMips            mip list + clothWrinkle

This exporter synthesises a minimal-but-valid file: a single LOD with the
given mesh(es).  Sections 3-10 are emitted empty or with the supplied
materials (no physics / procedural / skeleton), which is sufficient for
static props.  Position/UV use the i16 quantised codec (FVF format bit 0x2
for pos, 0x8 for UV) mirroring inject_wd.component_layout.
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
    """Mirrors import_wd._Reader: u16/u32/f32/mat4 pad to their size before
    writing; u8/bool are unaligned; strings = aligned u32 length + bytes."""

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


def _write_mesh_name_id(w, name):
    w.name_id(name)


# ── Section writers ─────────────────────────────────────────────────────────

def _write_header(w, n_lods, lod_dists, bsphere, bbox, smem=0):
    """Section 1.  `lod_dists` must have exactly n_lods entries.
    WD1 header (after MOEG magic + ver 97.50) is 5 u32s — 3 unk + 2
    SMemoryNeed — then an f32 and a bool.  NOTE: WD2/WDL MOEG files carry a
    16-byte hash here, but WD1 GEOM does NOT (only 5 u32s)."""
    w.u32(0x47454F4D)                       # b'MOEG' in file order
    w.u16(97); w.u16(50)                    # version 97.50
    w.u32(0); w.u32(0); w.u32(0)            # header unk1..3
    w.u32(smem); w.u32(smem)                # SMemoryNeed
    w.f32(0.0)                              # unk1 float
    w.boolean(False)                        # unk2 bool


def _write_params(w, n_lods, lod_dists, bsphere, bbox,
                  pos_off, pos_scale, uv_off, uv_scale):
    """Section 2.  Decompression constants pos = i16*scale+off (same as the
    injector's `off` tuple).  bsphere = (cx,cy,cz,r), bbox=(min3,max3)."""
    w.pad(4)
    w.u32(int(pos_off))                     # gp_unk1 (pos offset, as raw int)
    w.f32(pos_scale)                        # gp_unk2
    w.f32(pos_scale)                        # gp_unk3 (scale, repeated)
    w.f32(uv_off)                           # gp_unk4 (uv offset)
    w.f32(uv_scale)                         # gp_unk5
    w.f32(uv_scale)                         # trailing uv scale (parser reads 5 f32s)
    w.pad(4)
    w.vec(bsphere[:3]); w.f32(bsphere[3])   # bSphere (c + radius)
    w.vec(bbox[:3]); w.vec(bbox[3:])        # bBox (min3, max3)
    w.u32(0); w.u32(0); w.u32(0)
    w.count(lod_dists)                      # n_lods
    for d in lod_dists:
        w.f32(d)
    w.f32(1000.0)                           # killDistance
    w.boolean(True); w.boolean(True)        # 2 bools
    w.u8(0)                                 # trailing u8


def _write_materials(w, materials, n_lods):
    """Section 3.  `materials` = list of path strings (backslash)."""
    w.u32(0)                                # mr_unk0
    for _ in range(n_lods):
        w.f32(0.0)                          # per-LOD skip
    w.count(materials)
    for path in materials:
        w.u32(0)                            # CPathID (hash placeholder)
        w.string(path)


def _write_slots(w, slots):
    """Section 4.  `slots` = list of (name, index)."""
    w.count(slots)
    for name, idx in slots:
        w.name_id(name)
        w.u32(idx)


def _write_skins(w, skins):
    """Section 5.  `skins` = list of names."""
    w.count(skins)
    for name in skins:
        w.name_id(name)


def _write_palettes(w, palettes):
    """Section 6.  `palettes` = list of lists of bone indices."""
    w.count(palettes)
    for pal in palettes:
        w.count(pal)
        for ix in pal:
            w.u16(ix)


def _write_skeleton(w, bones):
    """Section 7.  `bones` = list of dicts with name/pos/quat/parent/o2n;
    obj2Node matrices are emitted as identities.  Empty list -> absent."""
    w.u32(1 if bones else 0)                # present
    if not bones:
        return
    w.count(bones)
    for b in bones:
        w.u8(0); w.u8(0); w.u8(0); w.u8(0) # boneLOD + unused[3]
        w.vec(b['pos'])
        x, y, z, wq = b['quat']             # (x,y,z,w) file order
        w.vec((x, y, z, wq))
        w.u16(b['parent'] if b['parent'] >= 0 else 0xFFFF)
        w.u16(b['o2n'])
        w.name_id(b['name'])
    w.u32(0)                                # unk2
    w.count([])                             # obj2Node matrices (none)


def _write_reflex(w):
    """Section 8.  Empty ReflexSystem FCB."""
    w.u32(0)                                # present=false


def _write_smo(w, sims=()):
    """Section 9.  SecondaryMotionObjects.  Empty by default."""
    w.count(sims)
    for sim in sims:
        w.vec(sim.get('pos', (0, 0, 0)))
        for _ in range(10):
            w.f32(0.0)
        w.u32(0); w.u32(0); w.boolean(False)
        w.count([]); w.count([]); w.count([]); w.count([])   # prims
        w.count([]); w.count([]); w.count([])                # limits
        w.count([])                                          # particles
        w.count([])                                          # particle meshes
        w.count([])                                          # triangles
        w.count([])                                          # connectivities
        w.count([])                                          # springs
        w.u16(0); w.boolean(False)


def _write_procedural(w, nodes=()):
    """Section 10.  ProceduralNodes.  Empty by default."""
    w.count(nodes)
    for _ in nodes:
        w.u16(0); w.u8(0)


def _write_lods(w, lods):
    """Section 11.  `lods` = list of LODs; each LOD = list of mesh dicts:
    {bbox, prim_type, mat_id, format, stride, bone_map, drawcall, ranges}.
    drawcall = {vb_offset, prim_count, index_count, index_start,
                vertex_count, min_index, max_index, group_count}.
    range = {drawcall, name}."""
    for meshes in lods:
        w.count(meshes)
        for m in meshes:
            w.vec(m['bbox'][:3]); w.f32(0.0)
            w.vec(m['bbox'][3:]); w.vec(m['bbox'][:3])  # min/max (approx)
            w.u32(m['prim_type'])
            w.u16(m['mat_id'])
            w.u16(m['format'])
            w.u8(m['stride']); w.u8(0); w.u16(0)
            w.u32(m['bone_map'])
            _write_drawcall(w, m['drawcall'])
            w.count(m['ranges'])
            w.u32(0); w.u32(0)
            for rg in m['ranges']:
                _write_drawcall(w, rg['drawcall'])
                w.vec((0, 0, 0)); w.f32(0.0)
                w.vec((0, 0, 0)); w.vec((0, 0, 0))
                w.name_id(rg['name'])
                w.u16(0); w.u16(0)


def _write_drawcall(w, dc):
    """Basic drawcall (mirrors import_wd._basic_drawcall)."""
    w.pad(4); w.u32(dc['vb_offset'])
    w.pad(4); w.u32(dc['prim_count'])
    w.pad(4); w.u32(dc['index_count'])
    w.pad(4); w.u32(dc['index_start'])
    w.pad(2); w.u16(dc['vertex_count'])
    w.pad(2); w.u16(dc['min_index'])
    w.pad(2); w.u16(dc['max_index'])
    w.pad(2); w.u16(dc['group_count'])


def _write_buffers(w, buffers):
    """Section 12.  `buffers` = list of (vdata, idata) byte strings."""
    w.count(buffers)
    for vdata, idata in buffers:
        w.pad(4); w.u32(len(vdata)); w.raw(vdata)
        w.pad(4); w.u32(len(idata)); w.raw(idata)


def _write_geom_mips(w, mips=()):
    """Section 13.  `mips` = list of (u32,u32,u32,name) tuples + clothWrinkle."""
    w.count(mips)
    for a, b, c, name in mips:
        w.u32(a); w.u32(b); w.u32(c)
        w.string(name)
    w.u32(0)                                # clothWrinkle


# ── Public entry point ──────────────────────────────────────────────────────

def export_wd1(path, mesh_objects, *, lod_dists=(20.0, 30.0, 70.0, 300.0),
               materials=None, name=None):
    """Write a fresh WD1 .xbg from a list of Blender mesh objects.

    Each object is treated as one submesh of a single LOD.  Position + UV use
    the i16 quantised codec; the pos/uv offset+scale are computed from the
    combined bounding box so the file is self-contained (no external bounds
    expansion needed).

    Returns the number of meshes written.
    """
    if bpy is None:
        raise RuntimeError("bpy unavailable")
    if not mesh_objects:
        raise ValueError("no mesh objects to export")

    # ── gather geometry ─────────────────────────────────────────────────
    mats = [m for m in mesh_objects]
    combined_min = [float('inf')] * 3
    combined_max = [float('-inf')] * 3
    for ob in mats:
        for v in ob.data.vertices:
            co = ob.matrix_world @ mathutils.Vector(v.co)
            for i in range(3):
                combined_min[i] = min(combined_min[i], co[i])
                combined_max[i] = max(combined_max[i], co[i])

    # WD1 codec is `pos = i16*scale + off` with ONE scalar offset+scale for
    # ALL three axes.  So `off` must be the global bbox minimum (across every
    # axis) and `scale` the global bbox extent, or per-axis ranges that don't
    # start at that shared offset overflow i16 and clamp.
    pos_off = min(combined_min)
    gmin = min(combined_min)
    gmax = max(combined_max)
    pos_scale = ((gmax - gmin) / 32767.0) or 1.0
    uv_off, uv_scale = 0.0, 1.0 / 32767.0

    bsphere = _compute_bsphere(combined_min, combined_max)
    bbox = combined_min + combined_max

    # per-object vertex pools: each object gets its own drawcall; all share
    # one vertex+index buffer (a single LOD, one SGfxBuffer).
    vdata = bytearray()
    idata = bytearray()
    meshes = []
    idx_base = 0
    for ob in mats:
        me = ob.data
        me.calc_loop_triangles()
        verts = [(ob.matrix_world @ mathutils.Vector(v.co)) for v in me.vertices]
        normals = [tuple(v.normal) for v in me.vertices]
        uvs = _object_uvs(me)
        mats_named = _material_names(ob)

        vcount = len(verts)
        fmt = 0x2 | 0x8 | 0x80          # i16 pos, i16 uv, u8 normal
        stride = 8 + 4 + 4               # 16 bytes
        vstart = len(vdata)
        for vi, co in enumerate(verts):
            _enc_pos(vdata, co, pos_off, pos_scale)
            _enc_uv(vdata, uvs[vi] if uvs else (0.0, 0.0), uv_off, uv_scale)
            _enc_normal(vdata, normals[vi] if vi < len(normals) else (0, 0, 1))
        # indices (file winding = a,c,b for CCW Blender triangles)
        tri_count = 0
        istart = len(idata) // 2
        for lt in me.loop_triangles:
            a, b, c = lt.vertices
            idata += struct.pack('<3H', idx_base + a, idx_base + c, idx_base + b)
            tri_count += 1
        drawcall = {
            'vb_offset': vstart, 'prim_count': tri_count,
            'index_count': tri_count * 3, 'index_start': istart,
            'vertex_count': vcount, 'min_index': 0,
            'max_index': vcount - 1, 'group_count': 0,
        }
        mat_id = _mesh_mat_id(ob, mats_named)
        bbox_m = _mesh_bbox(verts)
        meshes.append({
            'bbox': bbox_m, 'prim_type': 0, 'mat_id': mat_id,
            'format': fmt, 'stride': stride, 'bone_map': 0,
            'drawcall': drawcall, 'ranges': [
                {'drawcall': dict(drawcall),
                 'name': (ob.name or 'mesh%02d' % len(meshes))},
            ],
        })
        idx_base += vcount

    # ── sections 1-13 ──────────────────────────────────────────────────
    # One LOD of geometry; n_lods must match len(lod_dists) or the params
    # count disagrees with the LODs section and the reader desyncs.
    # The single SGfxBuffer maps to the LAST LOD (parser: buffer[i] holds
    # LOD[skip+i], skip = n_lods - n_buffers), so geometry goes in lods[-1].
    n_lods = max(1, len(lod_dists))
    lod_dists = list(lod_dists) + [0.0] * (n_lods - len(lod_dists))
    lods = [[] for _ in range(n_lods - 1)] + [meshes]
    buffers = [(bytes(vdata), bytes(idata))]
    mat_paths = materials or _collect_materials(mats)

    w = _Writer()
    _write_header(w, n_lods, list(lod_dists), bsphere, bbox)
    _write_params(w, n_lods, list(lod_dists), bsphere, bbox,
                  pos_off, pos_scale, uv_off, uv_scale)
    _write_materials(w, mat_paths, n_lods)
    slots = [(os.path.splitext(os.path.basename(p.replace('\\', '/')))[0], i)
             for i, p in enumerate(mat_paths)]
    _write_slots(w, slots)
    _write_skins(w, [])
    _write_palettes(w, [])
    _write_skeleton(w, [])
    _write_reflex(w)
    _write_smo(w)
    _write_procedural(w)
    _write_lods(w, lods)
    w.u32(0)                                    # unk3 (between LODs + SGfxBuffers)
    _write_buffers(w, buffers)
    _write_geom_mips(w)

    with open(path, 'wb') as f:
        f.write(bytes(w.b))
    return len(meshes)


# ── helpers ────────────────────────────────────────────────────────────────

def _compute_bsphere(bmin, bmax):
    c = [(bmin[i] + bmax[i]) / 2.0 for i in range(3)]
    r = max(abs(bmax[i] - c[i]) for i in range(3))
    return (c[0], c[1], c[2], r)


def _mesh_bbox(verts):
    bmin = [min(v[i] for v in verts) for i in range(3)]
    bmax = [max(v[i] for v in verts) for i in range(3)]
    return bmin + bmax


def _object_uvs(me):
    """Return per-vertex UV list (first UV layer), or None."""
    if not me.uv_layers:
        return None
    uv = me.uv_layers[0]
    # per-corner; use loop average keyed by vertex index
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


def _mesh_mat_id(ob, mat_names):
    if mat_names:
        return 0
    return 0


def _collect_materials(objects):
    seen = []
    for ob in objects:
        for m in _material_names(ob):
            if m not in seen:
                seen.append(m)
    # emit as game-style paths (best-effort; the game resolves by name)
    return ['graphics\\_materials\\%s.material.bin' % n for n in seen]


def _enc_pos(buf, co, off, scale):
    for i in range(3):
        buf += struct.pack('<h', _clamp_i16((co[i] - off) / scale))
    buf += b'\x00\x00'                     # w (i16), kept zero


def _enc_uv(buf, uv, off, scale):
    # stored V is flipped vs Blender
    buf += struct.pack('<h', _clamp_i16((uv[0] - off) / scale))
    buf += struct.pack('<h', _clamp_i16((1.0 - uv[1] - off) / scale))


def _enc_normal(buf, n):
    # D3DCOLOR stored B,G,R,A: bytes 2,1,0 = x,y,z
    buf.append(_enc_u8n(n[2]))
    buf.append(_enc_u8n(n[1]))
    buf.append(_enc_u8n(n[0]))
    buf.append(0)


def _clamp_i16(v):
    return max(-32768, min(32767, int(round(v))))


def _enc_u8n(n):
    """(x-1)/127 - 1  inverse -> byte."""
    return max(0, min(255, int(round((n + 1.0) * 127.0)) + 1))
