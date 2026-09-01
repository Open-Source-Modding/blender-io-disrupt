"""TAG0-format compressed mesh decoder (WDL / retail .col.hkx).

In old packfile format (WD1), a hkpBvCompressedMeshShape stores all tree
arrays INLINE in one contiguous object, and `decompress_compressed_mesh.py`
reads them directly.

In TAG0 format (WD2/WDL retail, Dunia wrapper), the same data is FRAGMENTED
across multiple ITEMs in the DATA section, linked by the PTCH fixup table:

  Item (type 0x7e)  -> section headers array (0x60 bytes each)
  Item (type 0x3c)  -> packed vertices (u32, 11/11/10-bit)
  Item (type 0x80)  -> primitives (u8[4])
  Item (type 0x6f)  -> shared vertices (u64, 21/21/22-bit)
  Item (type 0x94)  -> individual compressed mesh shapes

The domain AABB and codec floats live inside each section header item.

This module reuses the decompression math from decompress_compressed_mesh.py
so the per-vertex/primitive logic is shared (cross-compatible) while the
array sourcing differs by format.
"""

import struct


def decompress_packed_vertex(vtx, offset, scale):
    """Decompress a quantized u32 vertex (11/11/10-bit)."""
    x = (vtx & 0x7FF) * scale[0] + offset[0]
    y = ((vtx >> 11) & 0x7FF) * scale[1] + offset[1]
    z = ((vtx >> 22) & 0x3FF) * scale[2] + offset[2]
    return (x, y, z, 1.0)


def decompress_shared_vertex(vtx, domain_min, domain_max):
    """Decompress a u64 shared vertex (21/21/22-bit) against the domain."""
    sx = domain_max[0] - domain_min[0]
    sy = domain_max[1] - domain_min[1]
    sz = domain_max[2] - domain_min[2]
    x = (vtx & 0x1FFFFF) / 2097151.0 * sx + domain_min[0]
    y = ((vtx >> 21) & 0x1FFFFF) / 2097151.0 * sy + domain_min[1]
    z = ((vtx >> 42) & 0x3FFFFF) / 4194303.0 * sz + domain_min[2]
    return (x, y, z, 1.0)


class Tag0CompressedMesh:
    """Decode a single compressed mesh shape stored as TAG0 items.

    Given a parsed TAG0 file (import_hkx.parse_hkx) and the shape item
    (type 0x94), locate its sibling array items via the fixup graph and
    decode vertices + faces.

    Attributes:
        f: the parsed TAG0 file (import_hkx result)
        shape_item: the type-0x94 item (index into f.items)
        owner_item: the parent item that references the shape (type 0x7e)
    """

    SEC_SIZE = 0x60

    def __init__(self, f, shape_item):
        self.f = f
        self.shape_item = shape_item
        self.owner_item = None
        self._sections = None
        self._packed_verts = None
        self._primitives = None
        self._svi = None
        self._shared_verts = None
        self._domain_min = None
        self._domain_max = None
        self._find_owner_and_arrays()

    def _find_owner_and_arrays(self):
        """Find the parent (owner) item and the array items by fixup graph.

        Graph (single-shape case):
          shape[0x94] <- owned by section-headers[0x7e] <- owned by
          compound[0x62], which ALSO references the array items:
            0x3c = packed verts, 0x80 = primitives, 0x6f = shared verts.
        """
        f = self.f

        def owner_of(item_idx):
            for fixup in f.fixups:
                if fixup.target_item_index == item_idx:
                    for other in f.items:
                        if other.type_id != 0 and other.bytes:
                            start = other.data_offset
                            end = start + len(other.bytes)
                            if start <= fixup.pointer_location < end:
                                return other
            return None

        # owner = section-headers item that references the shape
        self.owner_item = owner_of(self.shape_item.index)
        if self.owner_item is None:
            return

        # Section headers live in the owner item itself (type 0x7e).
        if self.owner_item.type_id == 0x7e and self.owner_item.bytes:
            self._sections = self.owner_item.bytes

        # Grandparent = compound that references the section-headers item.
        grandparent = owner_of(self.owner_item.index)

        # Gather the array items referenced by the grandparent.
        if grandparent is not None:
            shared_candidates = []
            refs = [
                fixup.target_item_index
                for fixup in f.fixups
                if grandparent.data_offset <= fixup.pointer_location
                < grandparent.data_offset + len(grandparent.bytes)
            ]
            for ref_idx in refs:
                if ref_idx >= len(f.items):
                    continue
                item = f.items[ref_idx]
                if item.bytes is None or item.type_id == 0:
                    continue
                if item.type_id == 0x3c and self._packed_verts is None:
                    self._packed_verts = item.bytes
                elif item.type_id == 0x80 and self._primitives is None:
                    self._primitives = item.bytes
                elif item.type_id == 0x04 and self._svi is None:
                    self._svi = item.bytes
                elif item.type_id in (0x10, 0x6f):
                    # 0x10 = shared verts data (u64), 0x6f = sentinel buffer.
                    shared_candidates.append(item.bytes)
            if shared_candidates:
                # Prefer the larger buffer (actual shared verts data).
                self._shared_verts = max(shared_candidates, key=len)

            # Domain AABB: compound item itself (min @ +0x30, max @ +0x40).
            if grandparent.type_id == 0x62 and len(grandparent.bytes) >= 0x50:
                self._domain_min = (struct.unpack_from('<f', grandparent.bytes, 0x30)[0],
                                    struct.unpack_from('<f', grandparent.bytes, 0x34)[0],
                                    struct.unpack_from('<f', grandparent.bytes, 0x38)[0])
                self._domain_max = (struct.unpack_from('<f', grandparent.bytes, 0x40)[0],
                                    struct.unpack_from('<f', grandparent.bytes, 0x44)[0],
                                    struct.unpack_from('<f', grandparent.bytes, 0x48)[0])

        # Fallback: if no grandparent arrays found, use the owner's own refs.
        if self._packed_verts is None or self._primitives is None:
            shared_candidates = []
            refs = [
                fixup.target_item_index
                for fixup in f.fixups
                if self.owner_item.data_offset <= fixup.pointer_location
                < self.owner_item.data_offset + len(self.owner_item.bytes)
            ]
            for ref_idx in refs:
                if ref_idx >= len(f.items):
                    continue
                item = f.items[ref_idx]
                if item.bytes is None or item.type_id == 0:
                    continue
                if item.type_id == 0x3c and self._packed_verts is None:
                    self._packed_verts = item.bytes
                elif item.type_id == 0x80 and self._primitives is None:
                    self._primitives = item.bytes
                elif item.type_id == 0x04 and self._svi is None:
                    self._svi = item.bytes
                elif item.type_id in (0x10, 0x6f):
                    shared_candidates.append(item.bytes)
            if shared_candidates and self._shared_verts is None:
                self._shared_verts = max(shared_candidates, key=len)

    def has_data(self):
        return self._sections is not None

    def decode(self):
        """Decode all sections. Returns (vertices, faces)."""
        if self._sections is None:
            return [], []
        all_vertices = []
        all_faces = []
        vtx_offset = 0
        n_sec = len(self._sections) // self.SEC_SIZE

        # Pre-dequantize all shared vertices against the tree domain.
        shared_decompressed = []
        if self._shared_verts and self._domain_min and self._domain_max:
            n_shared = len(self._shared_verts) // 8
            for i in range(n_shared):
                sv = struct.unpack_from('<Q', self._shared_verts, i * 8)[0]
                shared_decompressed.append(
                    decompress_shared_vertex(sv, self._domain_min, self._domain_max))

        for si in range(n_sec):
            so = si * self.SEC_SIZE
            offset = (struct.unpack_from('<f', self._sections, so + 0x30)[0],
                      struct.unpack_from('<f', self._sections, so + 0x34)[0],
                      struct.unpack_from('<f', self._sections, so + 0x38)[0])
            scale = (struct.unpack_from('<f', self._sections, so + 0x3c)[0],
                     struct.unpack_from('<f', self._sections, so + 0x40)[0],
                     struct.unpack_from('<f', self._sections, so + 0x44)[0])
            first_packed = struct.unpack_from('<I', self._sections, so + 0x48)[0]
            num_packed = struct.unpack_from('<B', self._sections, so + 0x58)[0]
            num_shd = struct.unpack_from('<B', self._sections, so + 0x59)[0]
            shd_start = struct.unpack_from('<I', self._sections, so + 0x4c)[0] >> 8
            prim_data = struct.unpack_from('<I', self._sections, so + 0x50)[0]
            prim_start = prim_data >> 8
            prim_count = prim_data & 0xFF

            # Section local vertex list: packed verts first, then shared.
            verts = []
            if self._packed_verts:
                for i in range(num_packed):
                    idx = first_packed + i
                    if idx * 4 + 4 <= len(self._packed_verts):
                        v = struct.unpack_from('<I', self._packed_verts, idx * 4)[0]
                        verts.append(decompress_packed_vertex(v, offset, scale))
            # Shared indices reference shared slots via the svi indirection.
            if self._svi is not None:
                for i in range(num_shd):
                    svi_idx = shd_start + i
                    if svi_idx * 2 + 2 <= len(self._svi):
                        g = struct.unpack_from('<H', self._svi, svi_idx * 2)[0]
                        if g < len(shared_decompressed):
                            verts.append(shared_decompressed[g])

            if self._primitives:
                for i in range(prim_count):
                    idx = prim_start + i
                    if idx * 4 + 4 <= len(self._primitives):
                        a, b, c, d = struct.unpack_from('<4B', self._primitives, idx * 4)
                        if b != d:
                            if c == d:
                                all_faces.append((vtx_offset + a, vtx_offset + b, vtx_offset + c))
                            else:
                                all_faces.append((vtx_offset + a, vtx_offset + b, vtx_offset + c))
                                all_faces.append((vtx_offset + a, vtx_offset + c, vtx_offset + d))

            all_vertices.extend(verts)
            vtx_offset += len(verts)

        return all_vertices, all_faces
