"""Decoder for hkpBvCompressedMeshShape triangle connectivity.

Command-line tool: decodes the compressed mesh triangle stream that was
previously opaque. Uses the verified hkcdStaticMeshTree array layout
(see decompress_compressed_mesh.py for the full documentation of offsets).
"""
import struct
import sys
import os

# Import WdHkxFile directly from the file
_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _dir)
from import_hkx_wd import WdHkxFile
from decompress_compressed_mesh import decode_compressed_mesh


def decode_compressed_mesh_cli(f, cm):
    """Decode the compressed mesh triangle connectivity for one shape.

    Returns (vertices, faces) — a single global vertex/face list.
    """
    return decode_compressed_mesh(f, cm)


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: python decode_compressed_mesh.py <path_to_hkx>")
        sys.exit(1)

    f = WdHkxFile(sys.argv[1])
    for cm in f.compressed_meshes():
        print(f"Compressed mesh @0x{cm['offset']:x}")
        verts, faces = decode_compressed_mesh(f, cm)
        print(f"  Vertices: {len(verts)}  Triangles: {len(faces)}")
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        zs = [v[2] for v in verts]
        if xs:
            print(f"  BBox: x[{min(xs):.3f},{max(xs):.3f}] "
                  f"y[{min(ys):.3f},{max(ys):.3f}] "
                  f"z[{min(zs):.3f},{max(zs):.3f}]")
        if faces:
            print(f"  Sample faces: {faces[:3]} ... {faces[-3:]}")