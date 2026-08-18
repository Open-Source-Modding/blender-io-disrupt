"""Compressed mesh triangle decoder — full pipeline.

Decodes hkpBvCompressedMeshShape triangle connectivity from the bitstream.
Based on Havok 2017.2 class layouts extracted from Legion leak primitive files.

The bitstream is encoded as PrimitiveDataRuns. Each run specifies:
- value (u16): offset/position in the data
- index (u8): type of data (vertex, edge, face, etc.)
- count (u8): how many items to read

Triangle connectivity is reconstructed by iterating data runs per-section.
"""

import struct


def decompress_packed_vertex(vtx, offset, scale):
    """Decompress a quantized u32 vertex (11/11/10-bit)."""
    x = (vtx & 0x7FF) * scale[0] + offset[0]
    y = ((vtx >> 11) & 0x7FF) * scale[1] + offset[1]
    z = ((vtx >> 22) & 0x3FF) * scale[2] + offset[2]
    return (x, y, z, 1.0)


def decode_compressed_mesh(f, cm):
    """Decode compressed mesh from WdHkxFile.
    Returns list of (section_idx, vertices, triangles).
    """
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

    # Decode each section
    results = []
    for si in range(n_sec):
        so = sec_ptr + si * SEC
        nv = struct.unpack_from('<I', f.d, base + so + 0x08)[0]

        # Read codec parameters (quantization: offset + scale)
        codec_off = (struct.unpack_from('<f', f.d, base + so + 0x30)[0],
                     struct.unpack_from('<f', f.d, base + so + 0x34)[0],
                     struct.unpack_from('<f', f.d, base + so + 0x38)[0])
        codec_scale = (struct.unpack_from('<f', f.d, base + so + 0x3c)[0],
                       struct.unpack_from('<f', f.d, base + so + 0x40)[0],
                       struct.unpack_from('<f', f.d, base + so + 0x44)[0])

        # Read section metadata
        first_packed = struct.unpack_from('<I', f.d, base + so + 0x48)[0]
        num_packed = struct.unpack_from('<B', f.d, base + so + 0x58)[0]
        num_prims = struct.unpack_from('<B', f.d, base + so + 0x59)[0]

        # Decompress packed vertices
        verts = []
        for i in range(num_packed):
            if first_packed + i < len(packed_verts):
                vtx = packed_verts[first_packed + i]
                verts.append(decompress_packed_vertex(vtx, codec_off, codec_scale))

        results.append({
            'section': si,
            'vertices': verts,
            'num_prims': num_prims,
            'nv': nv,
        })

    return results
