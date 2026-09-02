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
    w.f32(3.4028235e+38)                    # unk_float (FLT_MAX, verified from reference)
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
    w.boolean(True); w.boolean(False)       # 2 bools (verified: True, False)
    w.u8(0xFF)                              # trailing u8 (verified: 0xFF)


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
               materials=None, name=None, armature=None, n_lods=1):
    """Write a fresh WD1 .xbg from a list of Blender mesh objects.

    Each object is treated as one submesh of a single LOD.  Position + UV use
    the i16 quantised codec; the pos/uv offset+scale are computed from the
    combined bounding box so the file is self-contained (no external bounds
    expansion needed).

    `armature`: optional Blender armature object. If provided, bone hierarchy
    is extracted and written to SkelResources.

    `n_lods`: number of LOD levels to write (1–4).  Objects are assigned to
    LODs by their ``wd_lod_level`` custom property (default 0 = LOD0).
    LOD distances come from ``lod_dists`` (trimmed to ``n_lods`` entries).
    If only one LOD is requested, all objects go to LOD0 regardless of their
    ``wd_lod_level`` tag.

    Returns the number of meshes written (across all LODs).
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
    # ALL three axes.  Use the original file's constants when available (imported
    # mesh objects store them as obj['wd_scale'] = [pos_off, pos_scale,
    # uv_off, uv_scale]); otherwise recompute from the bounding box.
    wd_scale = None
    for ob in mats:
        if 'wd_scale' in ob and len(ob['wd_scale']) >= 4:
            wd_scale = ob['wd_scale']
            break
    if wd_scale:
        pos_off = float(wd_scale[0])
        pos_scale = float(wd_scale[1])
        uv_off = float(wd_scale[2])
        uv_scale = float(wd_scale[3])
    else:
        pos_off = min(combined_min)
        gmin = min(combined_min)
        gmax = max(combined_max)
        pos_scale = ((gmax - gmin) / 32767.0) or 1.0
        uv_off, uv_scale = 0.0, 1.0 / 32767.0

    bsphere = _compute_bsphere(combined_min, combined_max)
    bbox = combined_min + combined_max

    # ── bones + palettes (needed before mesh loop for bone_map) ─────────
    bones = _extract_bones(armature) if armature else []
    palettes, bone_map = _build_palettes(mats, bones)
    # Resolve palette bone names to indices
    name2idx = {b['name']: i for i, b in enumerate(bones)} if bones else {}
    palettes_idx = []
    for pal in palettes:
        palettes_idx.append([name2idx[n] for n in pal if n in name2idx])

    # per-object vertex pools: each object gets its own drawcall; data is
    # stored per-mesh for later LOD grouping, then assembled into buffers.
    meshes = []
    for ob in mats:
        me = ob.data
        me.calc_loop_triangles()
        verts = [(ob.matrix_world @ mathutils.Vector(v.co)) for v in me.vertices]
        normals = [tuple(v.normal) for v in me.vertices]
        uvs = _object_uvs(me)

        # Second UV channel for uv_comp2 (lightmap / detail UVs)
        uvs2 = None
        if len(me.uv_layers) > 1:
            uv2_layer = me.uv_layers[1]
            uvs2 = [(0.0, 0.0)] * len(me.vertices)
            cnt2 = [0] * len(me.vertices)
            for li, loop in enumerate(me.loops):
                vi = loop.vertex_index
                u2, v2 = uv2_layer.data[li].uv
                uvs2[vi] = (uvs2[vi][0] + u2, uvs2[vi][1] + v2)
                cnt2[vi] += 1
            for vi in range(len(uvs2)):
                if cnt2[vi]:
                    uvs2[vi] = (uvs2[vi][0] / cnt2[vi], uvs2[vi][1] / cnt2[vi])

        # Vertex colors (first color layer) — averaged per-vertex from loops
        color_layer = None
        if hasattr(me, 'color_attributes') and me.color_attributes:
            color_layer = me.color_attributes[0]
        elif hasattr(me, 'vertex_colors') and me.vertex_colors:
            color_layer = me.vertex_colors.active
        per_vert_color = [(1.0, 1.0, 1.0, 1.0)] * len(verts)
        if color_layer is not None:
            ccnt = [0] * len(verts)
            csum = [(0.0, 0.0, 0.0, 0.0)] * len(verts)
            for li, loop in enumerate(me.loops):
                vi = loop.vertex_index
                try:
                    rgba = color_layer.data[li].color
                except Exception:
                    continue
                r, g, b = rgba[0], rgba[1], rgba[2]
                a = rgba[3] if len(rgba) > 3 else 1.0
                old = csum[vi]
                csum[vi] = (old[0]+r, old[1]+g, old[2]+b, old[3]+a)
                ccnt[vi] += 1
            for vi in range(len(verts)):
                if ccnt[vi]:
                    n = ccnt[vi]
                    per_vert_color[vi] = (csum[vi][0]/n, csum[vi][1]/n,
                                          csum[vi][2]/n, csum[vi][3]/n)

        # Tangents and binormals from UV-space computation
        tangents, binormals, tangent_w, binormal_w = \
            _compute_tangents_binormals(me, me.loop_triangles, verts,
                                        uvs if uvs else [(0,0)]*len(verts),
                                        normals)

        mats_named = _material_names(ob)

        vcount = len(verts)
        # point_comp(0x2) + uv_comp(0x8) + uv_comp2(0x1000) +
        # normal_comp(0x80) + color(0x100) + tangent_comp(0x200) +
        # binormal_comp(0x400) = 0x178A, stride = 8+4+4+4+4+4+4 = 32
        fmt = 0x2 | 0x8 | 0x80 | 0x100 | 0x200 | 0x400 | 0x1000
        stride = 8 + 4 + 4 + 4 + 4 + 4 + 4               # 32 bytes
        mv = bytearray()
        for vi, co in enumerate(verts):
            # Component order matches import_wd.py _decode_wd1_mesh:
            # Position → UV1 → UV2 → Normal → Color → Tangent → Binormal
            _enc_pos(mv, co, pos_off, pos_scale)
            _enc_uv(mv, uvs[vi] if uvs else (0.0, 0.0), uv_off, uv_scale)
            if uvs2:
                _enc_uv(mv, uvs2[vi], uv_off, uv_scale)
            else:
                mv += struct.pack('<hh', 0, 0)
            _enc_normal(mv, normals[vi] if vi < len(normals) else (0, 0, 1))
            _enc_color(mv, per_vert_color[vi])
            _enc_tangent_comp(mv, tangents[vi], tangent_w[vi])
            _enc_tangent_comp(mv, binormals[vi], binormal_w[vi])
        # indices (file winding = a,c,b for CCW Blender triangles)
        tri_count = 0
        mi = bytearray()
        for lt in me.loop_triangles:
            a, b, c = lt.vertices
            mi += struct.pack('<3H', a, c, b)
            tri_count += 1
        drawcall = {
            'vb_offset': 0, 'prim_count': tri_count,
            'index_count': tri_count * 3, 'index_start': 0,
            'vertex_count': vcount, 'min_index': 0,
            'max_index': vcount - 1, 'group_count': 0,
        }
        mat_id = _mesh_mat_id(ob, mats_named)
        bbox_m = _mesh_bbox(verts)
        mesh_lod = int(ob.get('lod_level', 0)) if hasattr(ob, 'get') else 0
        meshes.append({
            'bbox': bbox_m, 'prim_type': 0, 'mat_id': mat_id,
            'format': fmt, 'stride': stride,
            'bone_map': bone_map.get(ob.name, 0),
            'wd_lod_level': mesh_lod,
            'vdata': bytes(mv), 'idata': bytes(mi),
            'drawcall': drawcall, 'ranges': [
                {'drawcall': dict(drawcall),
                 'name': (ob.name or 'mesh%02d' % len(meshes))},
            ],
        })

    # ── LOD grouping ────────────────────────────────────────────────────
    # Objects with ``lod_level`` custom property (int 0–4) are assigned
    # to the matching LOD.  If only one LOD is requested, all objects go to
    # LOD0.  Each LOD gets its own vertex+index buffer (SGfxBuffer).
    if n_lods <= 1:
        # Single-LOD mode: everything in LOD0
        lod_map = {0: list(range(len(meshes)))}
    else:
        lod_map = {}
        for mi, m in enumerate(meshes):
            lod_l = int(m.get('wd_lod_level', 0))
            lod_l = max(0, min(n_lods - 1, lod_l))
            lod_map.setdefault(lod_l, []).append(mi)
        # Fill empty LOD levels with empty lists
        for i in range(n_lods):
            lod_map.setdefault(i, [])

    # Build per-LOD mesh lists and buffers
    lods = []
    buffers = []
    for i in range(n_lods):
        lod_indices = lod_map.get(i, [])
        lod_meshes = [meshes[idx] for idx in lod_indices]
        lods.append(lod_meshes)
        if lod_meshes:
            lv = bytearray()
            li = bytearray()
            voff = 0
            ioff = 0
            for m in lod_meshes:
                mv_data = m['vdata']
                mi_data = m['idata']
                micount = m['drawcall']['index_count']
                # Update drawcall to point into the assembled buffer
                m['drawcall']['vb_offset'] = voff
                m['drawcall']['index_start'] = ioff
                # Rebase indices by voff//stride (vertex offset within LOD)
                vstride = m['stride']
                vbase = voff // vstride
                rebased = bytearray()
                for ti in range(0, len(mi_data), 2):
                    idx = mi_data[ti] | (mi_data[ti + 1] << 8)
                    rebased += struct.pack('<H', idx + vbase)
                lv += mv_data
                li += rebased
                # Update ranges drawcalls too
                for r in m['ranges']:
                    r['drawcall']['vb_offset'] = voff
                    r['drawcall']['index_start'] = ioff
                voff += len(mv_data)
                ioff += micount
            buffers.append((bytes(lv), bytes(li)))
        else:
            buffers.append((b'', b''))

    # If no buffers got data (shouldn't happen), fall back to single
    if not any(b[0] for b in buffers):
        n_lods = 1
        lods = [meshes]
        lv = bytearray()
        li = bytearray()
        for m in meshes:
            lv += m['vdata']
            li += m['idata']
        buffers = [(bytes(lv), bytes(li))]

    mat_paths = materials or _collect_materials(mats)
    actual_n_lods = n_lods
    lod_dists_out = list(lod_dists[:actual_n_lods])
    if len(lod_dists_out) < actual_n_lods:
        while len(lod_dists_out) < actual_n_lods:
            lod_dists_out.append(lod_dists_out[-1] * 2.0 if lod_dists_out else 20.0)

    w = _Writer()
    _write_header(w, actual_n_lods, lod_dists_out, bsphere, bbox)
    _write_params(w, actual_n_lods, lod_dists_out, bsphere, bbox,
                  pos_off, pos_scale, uv_off, uv_scale)
    _write_materials(w, mat_paths, actual_n_lods)
    slots = [(os.path.splitext(os.path.basename(p.replace('\\', '/')))[0], i)
             for i, p in enumerate(mat_paths)]
    _write_slots(w, slots)
    _write_skins(w, [])
    _write_palettes(w, palettes_idx)
    _write_skeleton(w, bones)
    _write_reflex(w)
    _write_smo(w)
    _write_procedural(w)
    _write_lods(w, lods)
    w.u32(0)                                    # unk3 (between LODs + SGfxBuffers)
    _write_buffers(w, buffers)
    _write_geom_mips(w)

    with open(path, 'wb') as f:
        f.write(bytes(w.b))
    return sum(len(l) for l in lods)


# ── helpers ────────────────────────────────────────────────────────────────

def _compute_bsphere(bmin, bmax):
    c = [(bmin[i] + bmax[i]) / 2.0 for i in range(3)]
    r = max(abs(bmax[i] - c[i]) for i in range(3))
    return (c[0], c[1], c[2], r)


def _mesh_bbox(verts):
    bmin = [min(v[i] for v in verts) for i in range(3)]
    bmax = [max(v[i] for v in verts) for i in range(3)]
    return bmin + bmax


def _object_uvs(me, layer=0):
    """Return per-vertex UV list (specified UV layer), or None."""
    if len(me.uv_layers) <= layer:
        return None
    uv = me.uv_layers[layer]
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


def _object_vertex_colors(me):
    """Return per-vertex RGBA color list (first color layer), or None."""
    if not hasattr(me, 'color_attributes') or len(me.color_attributes) == 0:
        return None
    ca = me.color_attributes[0]
    out = [(1.0, 1.0, 1.0, 1.0)] * len(me.vertices)
    cnt = [0] * len(me.vertices)
    for li in range(len(me.loops)):
        vi = me.loops[li].vertex_index
        c = ca.data[li].color
        out[vi] = (out[vi][0] + c[0], out[vi][1] + c[1],
                    out[vi][2] + c[2], out[vi][3] + c[3])
        cnt[vi] += 1
    for vi in range(len(out)):
        if cnt[vi]:
            out[vi] = tuple(x / cnt[vi] for x in out[vi])
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


def _enc_color(buf, rgba):
    """Encode vertex color as D3DCOLOR BGRA."""
    r, g, b, a = rgba[:4] if len(rgba) >= 4 else (rgba[0], rgba[1], rgba[2], 1.0)
    buf.append(max(0, min(255, int(round(b * 255)))))  # B → byte0
    buf.append(max(0, min(255, int(round(g * 255)))))  # G → byte1
    buf.append(max(0, min(255, int(round(r * 255)))))  # R → byte2
    buf.append(max(0, min(255, int(round(a * 255)))))  # A → byte3


def _enc_tangent_comp(buf, t, w=1.0):
    """Encode tangent/binormal as D3DCOLOR BGRA with w sign in alpha."""
    buf.append(_enc_u8n(t[2]))                        # z → byte0 (B)
    buf.append(_enc_u8n(t[1]))                        # y → byte1 (G)
    buf.append(_enc_u8n(t[0]))                        # x → byte2 (R)
    buf.append(255 if w >= 0 else 0)                   # w sign → alpha


def _compute_tangents_binormals(me, loop_triangles, verts, uvs, normals):
    """Compute per-vertex tangents and binormals from loop triangles.

    Returns (tangents, binormals, tangent_w, binormal_w) where each is a list
    of (x,y,z) tuples or float w-values, indexed by vertex index.
    Uses the standard UV-space tangent algorithm (cross product of position
    and UV deltas per triangle, accumulated per-vertex, then normalized).
    """
    nverts = len(verts)
    tan = [[0.0, 0.0, 0.0] for _ in range(nverts)]
    bit = [[0.0, 0.0, 0.0] for _ in range(nverts)]

    if not uvs or not loop_triangles:
        return ([(0.0, 0.0, 1.0)] * nverts,
                [(0.0, 0.0, 1.0)] * nverts,
                [1.0] * nverts, [1.0] * nverts)

    for lt in loop_triangles:
        i0, i1, i2 = lt.vertices
        # Positions
        p0, p1, p2 = verts[i0], verts[i1], verts[i2]
        # UVs
        uv0, uv1, uv2 = uvs[i0], uvs[i1], uvs[i2]

        e1 = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2])
        e2 = (p2[0] - p0[0], p2[1] - p0[1], p2[2] - p0[2])
        duv1 = (uv1[0] - uv0[0], uv1[1] - uv0[1])
        duv2 = (uv2[0] - uv0[0], uv2[1] - uv0[1])

        det = duv1[0] * duv2[1] - duv1[1] * duv2[0]
        if abs(det) < 1e-12:
            continue
        r = 1.0 / det

        t = (r * (e1[0] * duv2[1] - e2[0] * duv1[1]),
             r * (e1[1] * duv2[1] - e2[1] * duv1[1]),
             r * (e1[2] * duv2[1] - e2[2] * duv1[1]))
        b = (r * (e2[0] * duv1[0] - e1[0] * duv2[0]),
             r * (e2[1] * duv1[0] - e1[1] * duv2[0]),
             r * (e2[2] * duv1[0] - e1[2] * duv2[0]))

        for i in (i0, i1, i2):
            tan[i][0] += t[0]; tan[i][1] += t[1]; tan[i][2] += t[2]
            bit[i][0] += b[0]; bit[i][1] += b[1]; bit[i][2] += b[2]

    tangents = []
    binormals = []
    tangent_w = []
    binormal_w = []
    for vi in range(nverts):
        n = normals[vi] if vi < len(normals) else (0.0, 0.0, 1.0)
        t = tan[vi]
        b = bit[vi]
        # Gram-Schmidt orthogonalize against normal
        dt = t[0]*n[0] + t[1]*n[1] + t[2]*n[2]
        tg = (t[0] - dt*n[0], t[1] - dt*n[1], t[2] - dt*n[2])
        tl = (tg[0]**2 + tg[1]**2 + tg[2]**2) ** 0.5
        if tl > 1e-12:
            tg = (tg[0]/tl, tg[1]/tl, tg[2]/tl)
        else:
            # Fallback: use normal
            tg = n
        # Recompute binormal as cross(normal, tangent) for orthonormal frame
        bn = (n[1]*tg[2] - n[2]*tg[1],
              n[2]*tg[0] - n[0]*tg[2],
              n[0]*tg[1] - n[1]*tg[0])
        # Sign: compute handiness via cross check
        cross = (tg[1]*bn[2] - tg[2]*bn[1],
                 tg[2]*bn[0] - tg[0]*bn[2],
                 tg[0]*bn[1] - tg[1]*bn[0])
        dot = cross[0]*n[0] + cross[1]*n[1] + cross[2]*n[2]
        sign = 1.0 if dot >= 0.0 else -1.0
        tangents.append(tg)
        binormals.append(bn)
        tangent_w.append(sign)
        binormal_w.append(1.0)

    return tangents, binormals, tangent_w, binormal_w


def _clamp_i16(v):
    return max(-32768, min(32767, int(round(v))))


def _enc_u8n(n):
    """(x-1)/127 - 1  inverse -> byte."""
    return max(0, min(255, int(round((n + 1.0) * 127.0)) + 1))


def _build_palettes(mesh_objects, bones):
    """Build bone palettes for skinned meshes.

    Each mesh's vertex groups reference bones by name.  A palette is a list of
    bone names (resolved to indices at write time) that covers every vertex
    group the mesh uses.  Meshes with identical bone sets share a palette.

    Returns (palettes, bone_map_per_mesh):
      palettes     = list of lists of bone name strings
      bone_map_per_mesh = dict mapping object name -> palette index
    """
    if not bones:
        return [], {}
    name2idx = {b['name']: i for i, b in enumerate(bones)}

    # Collect unique bone sets per mesh
    mesh_bone_sets = {}  # ob.name -> frozenset of bone names used
    for ob in mesh_objects:
        if ob.type != 'MESH':
            continue
        used = set()
        for vg in ob.vertex_groups:
            if vg.name in name2idx:
                used.add(vg.name)
        mesh_bone_sets[ob.name] = frozenset(used)

    # Deduplicate: map bone-set -> palette index
    seen = {}  # frozenset -> palette index
    palettes = []  # list of lists of bone name strings
    bone_map = {}  # ob.name -> palette index

    for ob_name, bone_set in mesh_bone_sets.items():
        if not bone_set:
            bone_map[ob_name] = 0  # rigid mesh, use empty palette
            continue
        key = bone_set
        if key not in seen:
            seen[key] = len(palettes)
            # Sort by bone index for consistency
            pal_names = sorted(bone_set, key=lambda n: name2idx[n])
            palettes.append(pal_names)
        bone_map[ob_name] = seen[key]

    return palettes, bone_map


def _extract_bones(arm_obj):
    """Extract bone hierarchy from a Blender armature for XBG export.

    Returns list of dicts matching import_wd.py's bone format:
    {name, parent (index or -1), pos (3 floats, local), quat (w,x,y,z), o2n}
    o2n (obj2NodeMatInd) is 0 for all bones — identity matrix.
    """
    if arm_obj is None or arm_obj.type != 'ARMATURE':
        return []
    arm = arm_obj.data
    bones_out = []
    name_index = {}
    # Collect bones in armature order (edit_bones sorted by hierarchy)
    bpy.ops.object.mode_set(mode='EDIT')
    ebs = list(arm.edit_bones)
    for i, eb in enumerate(ebs):
        name_index[eb.name] = i
    for i, eb in enumerate(ebs):
        # Local transform = parent.inverted() @ world if parented, else world
        if eb.parent and eb.parent.name in name_index:
            parent_idx = name_index[eb.parent.name]
            parent_mat = eb.parent.matrix_local
            local_mat = parent_mat.inverted() @ eb.matrix_local
        else:
            parent_idx = -1
            local_mat = eb.matrix_local
        pos = local_mat.to_translation()
        quat = local_mat.to_quaternion()  # (w, x, y, z)
        bones_out.append({
            'name': eb.name,
            'parent': parent_idx,
            'pos': (pos.x, pos.y, pos.z),
            'quat': (quat.w, quat.x, quat.y, quat.z),
            'o2n': 0,
        })
    bpy.ops.object.mode_set(mode='OBJECT')
    return bones_out
