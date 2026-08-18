"""WD1 HKX collision shape reader.

Extends the base HKX parser to read collision shape objects:
- hkpStaticCompoundShape (compound container)
- hkpBoxShape (axis-aligned box)
- hkpConvexVerticesShape (convex hull)
- hkpConvexVerticesConnectivity (face connectivity)

All reads are object-relative using the packfile's fixup system.
"""

import struct
from . import hkx_format


class BoxShape:
    __slots__ = ('radius', 'half_extents', 'offset')
    def __init__(self, offset, radius, half_extents):
        self.offset = offset
        self.radius = radius
        self.half_extents = half_extents
    def __repr__(self):
        return f"BoxShape(r={self.radius:.3f}, he={self.half_extents})"


class ConvexHull:
    __slots__ = ('offset', 'radius', 'num_vertices', 'vertices', 'connectivity')
    def __init__(self, offset, radius, num_vertices, vertices, connectivity=None):
        self.offset = offset
        self.radius = radius
        self.num_vertices = num_vertices
        self.vertices = vertices
        self.connectivity = connectivity
    def __repr__(self):
        return f"ConvexHull(r={self.radius:.3f}, verts={self.num_vertices})"


class Connectivity:
    __slots__ = ('vertex_indices', 'num_vertices_per_face')
    def __init__(self, vertex_indices, num_vertices_per_face):
        self.vertex_indices = vertex_indices
        self.num_vertices_per_face = num_vertices_per_face
    @property
    def num_faces(self):
        return len(self.num_vertices_per_face)


class CompoundShape:
    __slots__ = ('offset', 'instances')
    def __init__(self, offset, instances):
        self.offset = offset
        self.instances = instances


class Instance:
    __slots__ = ('translation', 'rotation', 'scale', 'shape')
    def __init__(self, translation, rotation, scale, shape):
        self.translation = translation
        self.rotation = rotation
        self.scale = scale
        self.shape = shape


class WD1CollisionReader:
    def __init__(self, parser):
        self.p = parser
        self.base = parser.base
        self.compound = None
        if isinstance(parser, hkx_format.OldPackfileParser):
            self._read()

    def _read(self):
        for o, cls in self.p.objects.items():
            if cls == 'nomadStaticPhysResourceData':
                compound_global = self.p.glob.get(o + 0x10)
                if compound_global and self.p.objects.get(compound_global) == 'hkpStaticCompoundShape':
                    self._read_compound(compound_global)
                break

    def _read_compound(self, offset):
        # m_instances ptr at data-rel 0x98 (local fixup → 0x100)
        # m_instances count at data-rel 0xb0 (= 0x60 + 0x50)
        inst_local = self.p.local.get(0x98)
        inst_count = self.p.read_u32(offset, 0x50)
        if not inst_local:
            return
        instances = []
        for i in range(inst_count):
            io = inst_local + i * 0x50
            tx,ty,tz,tw = struct.unpack_from('<4f', self.p.raw, self.base + io)
            qx,qy,qz,qw = struct.unpack_from('<4f', self.p.raw, self.base + io + 16)
            sx,sy,sz,sw = struct.unpack_from('<4f', self.p.raw, self.base + io + 32)
            shape_global = self.p.glob.get(io + 0x30)
            shape_cls = self.p.objects.get(shape_global, '') if shape_global else ''
            shape = None
            if shape_cls == 'hkpBoxShape':
                shape = self._read_box(shape_global)
            elif shape_cls == 'hkpConvexVerticesShape':
                shape = self._read_convex(shape_global)
            instances.append(Instance((tx,ty,tz,tw),(qx,qy,qz,qw),(sx,sy,sz,sw), shape))
        self.compound = CompoundShape(offset, instances)

    def _read_box(self, o):
        r = self.p.read_f32(o, 0x30)
        he = (self.p.read_f32(o,0x40), self.p.read_f32(o,0x44), self.p.read_f32(o,0x48))
        return BoxShape(o, r, he)

    def _read_convex(self, o):
        r = self.p.read_f32(o, 0x30)
        nv = self.p.read_u32(o, 0x70)
        arr = self.p.local.get(o + 0x50)
        verts = []
        if arr:
            for i in range((nv+3)//4):
                xs = struct.unpack_from('<4f', self.p.raw, self.base + arr + i*48)
                ys = struct.unpack_from('<4f', self.p.raw, self.base + arr + i*48+16)
                zs = struct.unpack_from('<4f', self.p.raw, self.base + arr + i*48+32)
                for k in range(4):
                    idx = i*4+k
                    if idx < nv:
                        verts.append((xs[k], ys[k], zs[k]))
        conn_g = self.p.glob.get(o + 0x78)
        conn = self._read_connectivity(conn_g) if conn_g and self.p.objects.get(conn_g) == 'hkpConvexVerticesConnectivity' else None
        return ConvexHull(o, r, nv, verts, conn)

    def _read_connectivity(self, o):
        vi_local = self.p.local.get(o + 0x10)
        vi_count = self.p.read_u32(o, 0x18)
        vi = []
        if vi_local:
            for i in range(vi_count):
                vi.append(struct.unpack_from('<H', self.p.raw, self.base + vi_local + i*2)[0])
        nvpf_local = self.p.local.get(o + 0x20)
        nvpf_count = self.p.read_u32(o, 0x28)
        nvpf = []
        if nvpf_local:
            for i in range(nvpf_count):
                nvpf.append(self.p.raw[self.base + nvpf_local + i])
        return Connectivity(vi, nvpf)
