"""Decoder for hkpBvCompressedMeshShape triangle connectivity.

Based on HKLib class definitions (hkcdStaticMeshTree + PrimitiveDataRun)
and binary analysis of WD1/WD2 .hkx files. This decodes the triangle
bitstream that was previously opaque.
"""
import struct
import sys
import os

# Import WdHkxFile directly from the file
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
from import_hkx_wd import WdHkxFile


def decode_compressed_mesh(f, cm):
    """Decode the compressed mesh triangle connectivity for one hkpBvCompressedMeshShape.
    
    Returns list of (section_idx, triangles) where each triangle is (i0, i1, i2).
    """
    o = cm['offset']
    base = f.base
    sec_ptr = f.local.get(o + 0xb0)
    n_sec = f.u32(o, 0xb8)
    SEC = 0x60
    
    all_triangles = []
    
    for si in range(n_sec):
        so = sec_ptr + si * SEC
        nv = struct.unpack_from('<I', f.d, base + so + 0x08)[0]
        off0 = struct.unpack_from('<I', f.d, base + so + 0x50)[0]
        off1 = struct.unpack_from('<I', f.d, base + so + 0x54)[0]
        
        if nv < 3:
            all_triangles.append((si, []))
            continue
        
        # Try decoding the bitstream
        # The bit offsets are likely byte offsets into a bitstream region
        # after the section headers + vertex data
        
        # Compute where the bitstream starts (after all section headers + vertex data)
        total_verts = sum(struct.unpack_from('<I', f.d, base + sec_ptr + s*SEC + 0x08)[0] 
                         for s in range(n_sec))
        vtx_start = sec_ptr + n_sec * SEC
        bitstream_start = vtx_start + total_verts * 4  # after all vertex data
        
        # Try different decodings
        triangles = try_decode_bitstream(f, base, nv, off0, off1, bitstream_start, si)
        all_triangles.append((si, triangles))
    
    return all_triangles


def try_decode_bitstream(f, base, nv, off0, off1, bitstream_start, section_idx):
    """Try to decode triangle connectivity from the bitstream."""
    triangles = []
    
    # Method 1: Fixed-width indices
    # Each triangle = 3 indices, each ceil(log2(nv)) bits
    bits_per_idx = max(1, (nv - 1).bit_length())
    
    # Try byte offsets first
    for use_bytes in [True, False]:
        if use_bytes:
            start = bitstream_start + off0
            end = bitstream_start + off1
        else:
            start = bitstream_start + off0 // 8
            end = bitstream_start + off1 // 8
        
        if start >= end or start < 0 or end > len(f.d):
            continue
        
        data = f.d[start:end]
        
        # Try fixed-width 3-index triangles
        tri_size = bits_per_idx * 3
        if tri_size > 0:
            n_tris = len(data) * 8 // tri_size
            for t in range(n_tris):
                bits = 0
                for b in range((t * tri_size) // 8, min((t * tri_size + tri_size + 7) // 8, len(data))):
                    bits = (bits << 8) | data[b]
                shift = (t * tri_size) % 8
                mask = (1 << tri_size) - 1
                val = (bits >> (8 * ((tri_size + 7) // 8) - tri_size - shift)) & mask
                
                i0 = (val >> (bits_per_idx * 2)) & ((1 << bits_per_idx) - 1)
                i1 = (val >> bits_per_idx) & ((1 << bits_per_idx) - 1)
                i2 = val & ((1 << bits_per_idx) - 1)
                
                if i0 < nv and i1 < nv and i2 < nv and i0 != i1 and i1 != i2 and i0 != i2:
                    triangles.append((i0, i1, i2))
            
            if triangles:
                print(f"  Section {section_idx}: decoded {len(triangles)} triangles "
                      f"({bits_per_idx}-bit indices, {'byte' if use_bytes else 'bit'} offsets)")
                return triangles
    
    return triangles


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python decode_compressed_mesh.py <path_to_hkx>")
        sys.exit(1)
    
    f = WdHkxFile(sys.argv[1])
    for cm in f.compressed_meshes():
        print(f"Compressed mesh @0x{cm['offset']:x}")
        triangles = decode_compressed_mesh(f, cm)
        total = sum(len(t) for _, t in triangles)
        print(f"  Total triangles decoded: {total}")
