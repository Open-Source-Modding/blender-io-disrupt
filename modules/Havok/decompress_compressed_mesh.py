"""Compressed mesh decoder — complete pipeline.

Decodes hkpBvCompressedMeshShape into vertices and faces.
Based on BlenderAddon HKX2 library's ToMesh() implementation and
Havok 2017.2 class layouts from Legion leak primitive files.

The compressed mesh stores (per WdHkxFile, data-relative offsets; tree =
shape offset + 0xa0, e.g. 0xc0 for the first shape):

  Array descriptor          | count  | size   | content
  --------------------------|--------|--------|------------------------------
  sections     tree+0x10    | 33     | 0x60   | per-section codec + indices
  primitives   tree+0x20    | 2745   | 4B     | (a,b,c,c) LOCAL u8 vertex idx
  sharedVIdx   tree+0x30    | 779    | u16    | shared slot -> shared vertex
  packedVerts  tree+0x40    | 2103   | u32    | 11/11/10-bit quantized
  sharedVerts  tree+0x50    | 380    | u64    | 21/21/22-bit quantized
  dataRuns     tree+0x60    | 2429   | 8B     | primitive data runs

Domain AABB (tree domain for shared-vertex dequant) at tree - 0x20:
  +0x00 min.xyz, +0x10 max.xyz (hkVector4 pairs).

Section header layout (0x60 bytes each, @ tree+0x10):
  +0x00: u64 tree-nodes blob ptr (local fixup), +0x08 size, +0x0c cap
  +0x10..+0x44: codec floats (3Axis4): offset @ +0x30, scale @ +0x3c
  +0x48: firstPackedVertex (u32)      — cumulative index into packedVerts
  +0x4c: packed (firstSharedVertexIndex << 8 | numPackedVertices)
  +0x50: packed (firstPrimitiveIndex << 8 | numPrimitives)
  +0x54: packed (firstDataRunIndex << 8 | numDataRuns)
  +0x58: numPackedVertices (u8), +0x59: numSharedIndices (u8)

Local index mapping (primitive byte index li):
  li < numPackedVertices -> packedVertices[firstPackedVertex + li]
  li >= numPackedVertices -> sharedVertices[ sharedVerticesIndex[
        firstSharedVertexIndex + (li - numPackedVertices)] ]

Primitive type (Havok 2018 hkcdStaticMeshTree::Primitive::getType):
  b != d and c == d          -> TRIANGLE (face a,b,c)
  b != d and c != d          -> QUAD     (faces a,b,c and a,c,d)
  b == d, c == EXTERNAL      -> EXTERNAL (skipped)
  b == d, c == CUSTOM        -> CUSTOM   (skipped)
  b == d, a=0xde b=0xad c=0xde d=0xad -> INVALID padding (skipped)

Verified on parking_staircase_01_high.hkx: 2882 verts (2103 packed + 779
shared), 2745 faces, all face indices valid, bbox within domain.
Also verified on 07_antique_hardware_base_high.hkx (1236 triangles + 4
INVALID 0xDEAD padding primitives skipped, 1095 verts).
"""

import struct
from typing import List, Tuple


def decompress_packed_vertex(vtx: int, offset, scale):
    """Decompress a quantized u32 vertex (11/11/10-bit)."""
    x = (vtx & 0x7FF) * scale[0] + offset[0]
    y = ((vtx >> 11) & 0x7FF) * scale[1] + offset[1]
    z = ((vtx >> 22) & 0x3FF) * scale[2] + offset[2]
    return (x, y, z, 1.0)


def decompress_shared_vertex(vtx: int, domain_min, domain_max):
    """Decompress a u64 shared vertex (21/21/22-bit) against the tree domain."""
    sx = domain_max[0] - domain_min[0]
    sy = domain_max[1] - domain_min[1]
    sz = domain_max[2] - domain_min[2]
    x = (vtx & 0x1FFFFF) / 2097151.0 * sx + domain_min[0]
    y = ((vtx >> 21) & 0x1FFFFF) / 2097151.0 * sy + domain_min[1]
    z = ((vtx >> 42) & 0x3FFFFF) / 4194303.0 * sz + domain_min[2]
    return (x, y, z, 1.0)


def decode_compressed_mesh(f, cm):
    """Decode compressed mesh from WdHkxFile.

    Returns (vertices, faces) where vertices is a list of (x,y,z,w) tuples
    and faces is a list of (v0,v1,v2) triangles.
    """
    o = cm['offset']
    base = f.base
    tree = o + 0xa0

    # Domain AABB precedes the tree descriptor block (tree - 0x20).
    domain_min = (struct.unpack_from('<f', f.d, base + tree - 0x20)[0],
                  struct.unpack_from('<f', f.d, base + tree - 0x1c)[0],
                  struct.unpack_from('<f', f.d, base + tree - 0x18)[0])
    domain_max = (struct.unpack_from('<f', f.d, base + tree - 0x10)[0],
                  struct.unpack_from('<f', f.d, base + tree - 0x0c)[0],
                  struct.unpack_from('<f', f.d, base + tree - 0x08)[0])

    # Array descriptors: 16 bytes each {ptr fixup, u32 size @ +0x08}.
    def arr(tag):
        ptr = f.local.get(tree + tag)
        n = struct.unpack_from('<I', f.d, base + tree + tag + 0x08)[0]
        return ptr, n

    sec_ptr, n_sec = arr(0x10)
    prim_ptr, n_prim = arr(0x20)
    svi_ptr, n_svi = arr(0x30)
    packed_ptr, n_packed = arr(0x40)
    shared_ptr, n_shared = arr(0x50)
    SEC = 0x60

    # Pre-decompress shared vertices against the tree domain.
    shared_decompressed = []
    if shared_ptr:
        for i in range(n_shared):
            sv = struct.unpack_from('<Q', f.d, base + shared_ptr + i * 8)[0]
            shared_decompressed.append(decompress_shared_vertex(sv, domain_min, domain_max))

    all_vertices = []
    all_faces = []
    vtx_offset = 0

    for si in range(n_sec):
        so = sec_ptr + si * SEC

        # Per-section codec (3Axis4): offset @ +0x30, scale @ +0x3c.
        offset = (struct.unpack_from('<f', f.d, base + so + 0x30)[0],
                  struct.unpack_from('<f', f.d, base + so + 0x34)[0],
                  struct.unpack_from('<f', f.d, base + so + 0x38)[0])
        scale = (struct.unpack_from('<f', f.d, base + so + 0x3c)[0],
                 struct.unpack_from('<f', f.d, base + so + 0x40)[0],
                 struct.unpack_from('<f', f.d, base + so + 0x44)[0])

        first_packed = struct.unpack_from('<I', f.d, base + so + 0x48)[0]
        num_packed = struct.unpack_from('<B', f.d, base + so + 0x58)[0]
        num_shd = struct.unpack_from('<B', f.d, base + so + 0x59)[0]
        shd_start = struct.unpack_from('<I', f.d, base + so + 0x4c)[0] >> 8
        prim_data = struct.unpack_from('<I', f.d, base + so + 0x50)[0]
        prim_start = prim_data >> 8
        prim_count = prim_data & 0xFF

        # Section vertex list: packed verts first, then shared verts.
        verts = []
        for i in range(num_packed):
            if first_packed + i < n_packed and packed_ptr:
                vtx = struct.unpack_from('<I', f.d, base + packed_ptr + (first_packed + i) * 4)[0]
                verts.append(decompress_packed_vertex(vtx, offset, scale))
        for i in range(num_shd):
            if shd_start + i < n_svi and svi_ptr:
                g = struct.unpack_from('<H', f.d, base + svi_ptr + (shd_start + i) * 2)[0]
                if g < len(shared_decompressed):
                    verts.append(shared_decompressed[g])

        # Primitives: byte[4] with per-type geometry (see module docstring).
        # Indices are LOCAL to the section's vertex list.
        if prim_ptr:
            for i in range(prim_count):
                if prim_start + i < n_prim:
                    a, b, c, d = struct.unpack_from('<4B', f.d, base + prim_ptr + (prim_start + i) * 4)
                    if b != d:
                        if c == d:      # TRIANGLE
                            all_faces.append((vtx_offset + a, vtx_offset + b, vtx_offset + c))
                        else:           # QUAD -> two triangles
                            all_faces.append((vtx_offset + a, vtx_offset + b, vtx_offset + c))
                            all_faces.append((vtx_offset + a, vtx_offset + c, vtx_offset + d))
                    # else: b == d -> EXTERNAL/CUSTOM/INVALID padding, skip

        all_vertices.extend(verts)
        vtx_offset += len(verts)

    return all_vertices, all_faces