"""Watch Dogs 1 .hkx collision injection — Blender side.

Rewrites edited convex-hull / box collision shapes back into a copy of a WD1
(64-bit Havok 2012) packfile.  Mirrors the WD2 model: VERTEX-DISPLACEMENT-ONLY,
so vertex count/order and all transform bytes are preserved and the untouched
round trip is byte-identical.  (Boxes are patched by half-extents, not verts.)

All edits are in shape-local space (the importer bakes no child transforms),
so only the shape's own float data changes — the hkpStaticCompoundShape
Instances, connectivity and tree bytes are untouched.
"""

import struct

from .import_hkx_wd import WdHkxFile


def inject_hkx_wd(context, path, objects, out_path):
    """Inject edited shapes from imported objects into a copy of a WD1 .hkx.

    Each selected object must carry ``wd_hkx_src`` and ``wd_hkx_shape_off``
    (set by the WD1 importer).  Convex-hull objects (no
    ``wd_hkx_is_hull_reconstruction``) patch the SOA m_rotatedVertices floats;
    the connectivity (vertex-ID based) stays valid.  Box objects patch
    m_halfExtents.  Returns a list of (shape_offset, n_verts_or_0) injected.
    """
    f = WdHkxFile(path)
    data = bytearray(f.raw)
    # d is wrapper-relative? No: d = raw[wrapper:], base = d-relative.
    # We must patch into `data` at the SAME file offsets f uses (which are
    # already relative to self.d = raw[wrapper:]).  Recompute absolute offset.
    injected = []
    for obj in objects:
        off = obj.get('wd_hkx_shape_off')
        if off is None:
            continue
        cls = f.objects.get(off)
        me = obj.data
        verts = [tuple(v.co) for v in me.vertices]

        if cls == 'hkpConvexVerticesShape':
            arr = f.local.get(off + 0x50)
            if arr is None:
                continue
            num = f.u32(off, 0x60)
            if len(verts) != num:
                raise ValueError(
                    "Shape 0x%x vertex count changed: %d vs original %d. "
                    "WD1 HKX injection is VERTEX-DISPLACEMENT-ONLY — move "
                    "vertices, do not add/delete." % (off, len(verts), num))
            _write_fourvectors(data, f.wrapper + f.base + arr, verts)
            injected.append((off, num))

        elif cls == 'hkpBoxShape':
            # Patch the 3 half-extent floats at +0x30.  We need the box's
            # half-extents from the object: the importer didn't store them, so
            # derive from the mesh bounds.
            if not verts:
                continue
            xs = [v[0] for v in verts]
            ys = [v[1] for v in verts]
            zs = [v[2] for v in verts]
            he = ((max(xs) - min(xs)) / 2.0,
                  (max(ys) - min(ys)) / 2.0,
                  (max(zs) - min(zs)) / 2.0)
            p = f.wrapper + f.base + off + 0x30
            data[p:p + 12] = struct.pack('<3f', *he)
            injected.append((off, 0))

    if not injected:
        return injected
    with open(out_path, 'wb') as fh:
        fh.write(bytes(data))
    return injected


def _write_fourvectors(data, abs_off, verts):
    """Rewrite verts into the SOA hkFourVectors array at abs_off (file-absolute).

    The array holds ceil(n/4) 48-byte blocks [x..x][y..y][z..z]; the final
    block pads to 4 (its pad lanes are left untouched by only writing n verts).
    """
    n = len(verts)
    nblocks = (n + 3) // 4
    p = abs_off
    for b in range(nblocks):
        base_idx = b * 4
        xs = [0.0] * 4
        ys = [0.0] * 4
        zs = [0.0] * 4
        for k in range(4):
            i = base_idx + k
            if i < n:
                xs[k], ys[k], zs[k] = verts[i]
        struct.pack_into('<4f', data, p, *xs)
        struct.pack_into('<4f', data, p + 16, *ys)
        struct.pack_into('<4f', data, p + 32, *zs)
        p += 48
