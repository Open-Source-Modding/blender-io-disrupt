"""WD1/WD2/WDL compressed mesh triangle decoder.

Decodes hkpBvCompressedMeshShape triangle connectivity from the
bitstream. Based on the BlenderAddon implementation (HKX2 library).

The compressed mesh stores:
1. Packed vertices: quantized u32 (11/11/10-bit)
2. Shared vertices: u64 (21/21/22-bit)
3. Primitives: byte[4] with vertex indices
4. Data runs: PrimitiveDataRun entries (value/index/count)

Vertex decompression:
  PackedVertex: x = (vtx & 0x7FF) * scale.x + offset.x
                y = ((vtx >> 11) & 0x7FF) * scale.y + offset.y
                z = ((vtx >> 22) & 0x3FF) * scale.z + offset.z
  SharedVertex: x = (vtx & 0x1FFFFF) / 2097151 * domain_scale.x + domain_min.x
                y = ((vtx >> 21) & 0x1FFFFF) / 2097151 * domain_scale.y + domain_min.y
                z = ((vtx >> 42) & 0x3FFFFF) / 4194303 * domain_scale.z + domain_min.z

Section fields (from BlenderAddon HKX2 library):
  m_codecParms[0..2]: offset (3 floats)
  m_codecParms[3..5]: scale (3 floats)
  m_firstPackedVertex: index into packedVertices array
  m_numPackedVertices: count of packed vertices
  m_numSharedIndices: count of shared vertex indices
  m_sharedVertices.m_data >> 8: index into sharedVerticesIndex array
  m_primitives.m_data >> 8: index into primitives array
  m_primitives.m_data & 0xFF: count of primitives

Primitives: hkcdStaticMeshTreeBasePrimitive with m_indices[4] (byte[4])
"""

import struct


def decompress_packed_vertex(vtx, offset, scale):
    """Decompress a quantized u32 vertex (11/11/10-bit)."""
    x = (vtx & 0x7FF) * scale[0] + offset[0]
    y = ((vtx >> 11) & 0x7FF) * scale[1] + offset[1]
    z = ((vtx >> 22) & 0x3FF) * scale[2] + offset[2]
    return (x, y, z, 1.0)


def decompress_shared_vertex(vtx, domain_min, domain_max):
    """Decompress a u64 shared vertex (21/21/22-bit)."""
    sx = domain_max[0] - domain_min[0]
    sy = domain_max[1] - domain_min[1]
    sz = domain_max[2] - domain_min[2]
    x = (vtx & 0x1FFFFF) / 2097151.0 * sx + domain_min[0]
    y = ((vtx >> 21) & 0x1FFFFF) / 2097151.0 * sy + domain_min[1]
    z = ((vtx >> 42) & 0x3FFFFF) / 4194303.0 * sz + domain_min[2]
    return (x, y, z, 1.0)


def decode_compressed_mesh(f, cm):
    """Decode compressed mesh from WdHkxFile. Returns list of (vertices, primitives)."""
    o = cm['offset']
    base = f.base
    sec_ptr = f.local.get(o + 0xb0)
    n_sec = f.u32(o, 0xb8)
    SEC = 0x60

    # Read tree structure
    tree = o + 0xa0
    domain_min = (struct.unpack_from('<f', f.d, base + tree + 0x10)[0],
                  struct.unpack_from('<f', f.d, base + tree + 0x14)[0],
                  struct.unpack_from('<f', f.d, base + tree + 0x18)[0])
    domain_max = (struct.unpack_from('<f', f.d, base + tree + 0x20)[0],
                  struct.unpack_from('<f', f.d, base + tree + 0x24)[0],
                  struct.unpack_from('<f', f.d, base + tree + 0x28)[0])

    # Read packed vertices
    packed_ptr = f.local.get(tree + 0x20)
    n_packed = struct.unpack_from('<I', f.d, base + tree + 0x28)[0]
    packed_verts = []
    if packed_ptr:
        for i in range(n_packed):
            packed_verts.append(struct.unpack_from('<I', f.d, base + packed_ptr + i * 4)[0])

    # Read shared vertices
    shared_ptr = f.local.get(tree + 0x30)
    n_shared = struct.unpack_from('<I', f.d, base + tree + 0x38)[0]
    shared_verts = []
    if shared_ptr:
        for i in range(n_shared):
            shared_verts.append(struct.unpack_from('<Q', f.d, base + shared_ptr + i * 8)[0])

    # Read shared vertex indices
    idx_ptr = f.local.get(tree + 0x40)
    n_idx = struct.unpack_from('<I', f.d, base + tree + 0x48)[0]
    shared_indices = []
    if idx_ptr:
        for i in range(n_idx):
            shared_indices.append(struct.unpack_from('<H', f.d, base + idx_ptr + i * 2)[0])

    # Read primitives
    prim_ptr = f.local.get(tree + 0x30)
    n_prims = struct.unpack_from('<I', f.d, base + tree + 0x38)[0]
    prims = []
    if prim_ptr:
        for i in range(n_prims):
            b = struct.unpack_from('<4B', f.d, base + prim_ptr + i * 4)
            prims.append(b)

    # Decode each section
    results = []
    for si in range(n_sec):
        so = sec_ptr + si * SEC
        nv = struct.unpack_from('<I', f.d, base + so + 0x08)[0]

        # Read codec parameters
        offset = (struct.unpack_from('<f', f.d, base + so + 0x10)[0],
                  struct.unpack_from('<f', f.d, base + so + 0x14)[0],
                  struct.unpack_from('<f', f.d, base + so + 0x18)[0])
        scale = (struct.unpack_from('<f', f.d, base + so + 0x1c)[0],
                 struct.unpack_from('<f', f.d, base + so + 0x20)[0],
                 struct.unpack_from('<f', f.d, base + so + 0x24)[0])

        # Read section metadata
        first_packed = struct.unpack_from('<I', f.d, base + so + 0x48)[0]
        num_packed = struct.unpack_from('<B', f.d, base + so + 0x58)[0]
        num_prims = struct.unpack_from('<B', f.d, base + so + 0x59)[0]

        # Decompress packed vertices
        verts = []
        for i in range(num_packed):
            if first_packed + i < len(packed_verts):
                vtx = packed_verts[first_packed + i]
                verts.append(decompress_packed_vertex(vtx, offset, scale))

        # Add shared vertices (if any)
        # The shared vertex indices are in the global array
        # For now, just use packed vertices

        results.append({
            'section': si,
            'vertices': verts,
            'num_prims': num_prims,
            'nv': nv,
        })

    return results
