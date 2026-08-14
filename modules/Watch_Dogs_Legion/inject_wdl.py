"""Watch Dogs Legion .xbg geometry injection (in-place vertex editing).

WDL uses the MOEG binary format (same family as WD2).  Vertex data is
stored sequentially per submesh with i16-quantized positions and UVs.

PHASE 1: edit vertex POSITIONS / UVs without changing vertex or triangle
count.  Covers reshaping, sculpting and re-skinning existing geometry.

Per-mesh layout stamped by import_wdl_xbg:
    wdl_src          source .xbg path
    wdl_mesh_index   mesh index in the model dict
"""

import os
import struct

try:
    import bpy
    import mathutils
except Exception:
    bpy = None
    mathutils = None


def _clamp_i16(v):
    return max(-32768, min(32767, int(round(v))))


def patch_wdl_vertex(buf, base, stride, *, co=None, uv=None):
    """Overwrite editable components of one WDL vertex at file offset `base`.

    MOEG vertex layout (fixed):
        bytes 0..15:  8 x i16 (4 unused + pos_x, pos_y, pos_z, pos_w)
        bytes 16..19: 2 x i16 (uv_u, uv_v)
        bytes 20..stride-1: tail data (normals, tangents, etc. — untouched)
    """
    if co is not None:
        # pos at i16 offsets [4],[5],[6] within the 8-i16 header (bytes 8..13)
        struct.pack_into('<h', buf, base + 8, _clamp_i16(co[0] * 32768.0))
        struct.pack_into('<h', buf, base + 10, _clamp_i16(co[1] * 32768.0))
        struct.pack_into('<h', buf, base + 12, _clamp_i16(co[2] * 32768.0))
    if uv is not None:
        u, v = uv[0], 1.0 - uv[1]  # decode flips V
        struct.pack_into('<h', buf, base + 16,
                         _clamp_i16((u - 0.5) * 65536.0))
        struct.pack_into('<h', buf, base + 18,
                         _clamp_i16((v - 0.5) * 65536.0))


# ---------------------------------------------------------------------------
# Blender export helpers
# ---------------------------------------------------------------------------

def _vertex_uvs(me, layer_index):
    if layer_index >= len(me.uv_layers):
        return None
    uvl = me.uv_layers[layer_index].data
    out = [None] * len(me.vertices)
    for loop in me.loops:
        if out[loop.vertex_index] is None:
            uv = uvl[loop.index].uv
            out[loop.vertex_index] = (uv[0], uv[1])
    return out


def _vertex_normals(me, recalculate=False):
    geo = [tuple(v.normal) for v in me.vertices]
    if recalculate:
        return geo
    na = me.attributes.get('xbg_normal')
    if na and na.domain == 'POINT' and len(na.data) == len(me.vertices):
        out = []
        for i in range(len(me.vertices)):
            v = na.data[i].vector
            out.append((v[0], v[1], v[2])
                       if (v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) > 1e-6
                       else geo[i])
        return out
    return geo


# ---------------------------------------------------------------------------
# Phase 1 — in-place vertex patching (same vertex count)
# ---------------------------------------------------------------------------

def inject_wdl_objects(objects, out_path, source_path=None):
    """Patch edited vertices of WDL-imported objects back into a copy of the
    source .xbg.  Returns (n_objects, n_vertices, warnings).

    Only vertex positions and UVs are patched; normals, tangents and other
    tail data are left untouched for round-trip fidelity.
    """
    tagged = [o for o in objects if o.get('wdl_src')]
    if not tagged:
        raise RuntimeError("no WDL-imported meshes selected "
                           "(import a Watch Dogs Legion .xbg first)")
    src = source_path or tagged[0]['wdl_src']
    tagged = [o for o in tagged if o['wdl_src'] == src]

    # Load the full model to get layout info (file offsets, strides)
    from .import_wdl_xbg import parse_wdl_xbg
    model = parse_wdl_xbg(src)
    layout = model['_layout']

    buf = bytearray(open(src, 'rb').read())
    warnings = []
    n_obj = n_vtx = 0

    for ob in tagged:
        me = ob.data
        mi = int(ob['wdl_mesh_index'])

        if mi >= len(model['meshes']):
            warnings.append("%s: mesh index %d out of range — skipped"
                            % (ob.name, mi))
            continue

        mesh_info = model['meshes'][mi]
        vert_file_off = mesh_info['vert_file_off']
        stride = mesh_info['vert_stride']
        orig_vcount = mesh_info['vert_count']

        if len(me.vertices) != orig_vcount:
            warnings.append(
                "%s: vertex count changed (%d -> %d) — phase-1 inject keeps "
                "the count; skipped"
                % (ob.name, orig_vcount, len(me.vertices)))
            continue

        # 0xFFFF is the u16 sentinel / max index — vehicles split large
        # meshes across multiple buffers to stay under this cap.
        if orig_vcount > 65534:
            warnings.append(
                "%s: submesh has %d verts (exceeds u16 limit of 65534) — "
                "inject may produce invalid face indices"
                % (ob.name, orig_vcount))

        uvs = _vertex_uvs(me, 0)

        for vi, v in enumerate(me.vertices):
            foff = vert_file_off + vi * stride
            patch_wdl_vertex(buf, foff, stride,
                             co=(v.co.x, v.co.y, v.co.z),
                             uv=uvs[vi] if uvs else None)
            n_vtx += 1
        n_obj += 1

    with open(out_path, 'wb') as f:
        f.write(buf)
    return n_obj, n_vtx, warnings
