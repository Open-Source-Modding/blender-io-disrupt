"""Watch Dogs .hkx Havok collision parser (WD1/WD2/WDL).

Faithful port of HavokDisrupt (FrankMK04) HkxParser from IL disassembly
(~/Code/re/havok/hkx_disasm.txt). Handles the Ubisoft Disrupt custom
Havok tagfile wrapper:

  Header:  HeaderField0 (u32 LE) + HeaderCrc (u32 LE) + TagfileTotalSize (u32 LE)
  Chunks:  hkChunk { sizeAndFlags u32 BE, tag u32 LE } — size INCLUDES the
           8-byte header, payload = size & 0x3FFFFFFF - 8
  Sections:
    TAG0   header marker (skip 8)
    INDX   index wrapper (skip 8 — ITEM/PTCH follow as siblings)
    SDKV   sdk version string ("20150100" for WD2)
    DATA   serialized object bytes (the item data)
    TCRF   external compendium signature (24 bytes)
    ITEM   item table:  12 bytes each {u32 typeIdAndFlags, u32 dataOffset, u32 count}
    PTCH   patch table: {u32 pointerType, u32 count, count * u32 pointerLocation}

Type IDs (WD2 static collisions):
  0x21 shape root quantized, 0x49 vertex header, 0x25 vertex/plane, 0x4b face indices
  0x93 shape root full precision, 0x57 vertices, 0x4e planes, 0x0d face indices
  TypeId = word0 & 0xFFFFFF; Flags = (word0 >> 28) & 0xF

References:
  - HavokDisrupt: ~/Code/re/havok/hkx_reverse/HavokDisrupt.exe
  - IL disassembly: ~/Code/re/havok/hkx_disasm.txt
  - HavokLib format_new.cpp / TagTools.py for standard packfile layout
"""

import struct


# ── Section tags (FourCC as little-endian u32) ─────────────────────────────

TAG_TAG0 = 0x30474154    # "TAG0" header marker
TAG_INDX = 0x58444E49    # "INDX" index wrapper
TAG_SDKV = 0x564B4453    # "SDKV" sdk version
TAG_DATA = 0x41544144    # "DATA" serialized object bytes
TAG_TCRF = 0x46524354    # "TCRF" compendium signature
TAG_ITEM = 0x4D455449    # "ITEM" item table
TAG_PTCH = 0x48435450    # "PTCH" patch/fixup table

# HavokDisrupt constants (same values)
FOURCC_TAG0 = 809976148   # TAG0
FOURCC_INDX = 1480871497  # INDX
FOURCC_SDKV = 1447773267  # SDKV
FOURCC_DATA = 1096040772  # DATA
FOURCC_TCRF = 1179796308  # TCRF
FOURCC_ITEM = 1296389193  # ITEM
FOURCC_PTCH = 1212372048  # PTCH

# Type IDs (disasm constants)
TYPE_SHAPE_ROOT_QUANT = 0x21
TYPE_VERTEX_HEADER_QUANT = 0x49
TYPE_VERTEX_OR_PLANE_QUANT = 0x25
TYPE_FACE_INDICES_QUANT = 0x4B
TYPE_SHAPE_DATA_QUANT = 0x2D
TYPE_SHAPE_ROOT_FULL = 0x93
TYPE_VERTICES_FULL = 0x57
TYPE_PLANES_FULL = 0x4E
TYPE_FACE_INDICES_FULL = 0x0D


class HkxItem:
    __slots__ = ('index', 'type_id', 'flags', 'data_offset', 'count', 'bytes')

    def __init__(self, index, type_id, flags, data_offset, count, data=None):
        self.index = index
        self.type_id = type_id
        self.flags = flags
        self.data_offset = data_offset
        self.count = count
        self.bytes = data

    def __repr__(self):
        return (f"HkxItem(idx={self.index} type=0x{self.type_id:02x} "
                f"flags=0x{self.flags:02x} off=0x{self.data_offset:04x} cnt={self.count})")


class HkxFixup:
    __slots__ = ('pointer_type', 'pointer_location', 'target_item_index')

    def __init__(self, pointer_type, pointer_location, target_item_index=-1):
        self.pointer_type = pointer_type
        self.pointer_location = pointer_location
        self.target_item_index = target_item_index

    def __repr__(self):
        return (f"HkxFixup(ptype=0x{self.pointer_type:02x} "
                f"loc=0x{self.pointer_location:04x} target={self.target_item_index})")


class HkxConvexShape:
    """A convex collision hull with quantized or full-precision vertices."""
    __slots__ = ('variant', 'shape_item_index', 'vertex_header_item_index',
                 'aabb_min', 'aabb_max', 'convex_radius', 'quant_scale',
                 'vertices', 'quad_indices')

    def __init__(self):
        self.variant = 0                # 0=Quantized, 1=FullPrecision
        self.shape_item_index = -1
        self.vertex_header_item_index = -1
        self.aabb_min = (0.0, 0.0, 0.0)
        self.aabb_max = (0.0, 0.0, 0.0)
        self.convex_radius = 0.0
        self.quant_scale = (0.0, 0.0, 0.0)
        self.vertices = []              # list of (x, y, z)
        self.quad_indices = []          # flat list, 4 per quad

    @property
    def quad_count(self):
        return len(self.quad_indices) // 4

    def __repr__(self):
        return (f"HkxConvexShape(variant={'Quantized' if self.variant == 0 else 'FullPrecision'} "
                f"shape_item={self.shape_item_index} quads={self.quad_count} "
                f"verts={len(self.vertices)})")


class HkxChildTransform:
    __slots__ = ('child_item_index', 'transform', 'scale')

    def __init__(self, child_item_index, transform, scale):
        self.child_item_index = child_item_index
        self.transform = transform      # 4x4 row-major list of 16 floats
        self.scale = scale              # (x, y, z)


class HkxFile:
    __slots__ = ('header_field0', 'header_crc', 'total_size', 'sdk_version',
                 'data_section', 'tcrf_section', 'items', 'fixups',
                 'root_item_index', 'convex_shapes', 'child_transforms')

    def __init__(self):
        self.header_field0 = 0
        self.header_crc = 0
        self.total_size = 0
        self.sdk_version = ''
        self.data_section = b''
        self.tcrf_section = b''
        self.items = []
        self.fixups = []
        self.root_item_index = -1
        self.convex_shapes = []
        self.child_transforms = {}      # item_index -> HkxChildTransform


def _read_u32_le(data, offset):
    return struct.unpack_from('<I', data, offset)[0]


def _read_u32_be(data, offset):
    """ReadU32BE — big-endian u32 (used for chunk sizes)."""
    return (data[offset] << 24) | (data[offset + 1] << 16) \
        | (data[offset + 2] << 8) | data[offset + 3]


def _read_f32_le(data, offset):
    return struct.unpack_from('<f', data, offset)[0]


def _decode_fourcc(value):
    return struct.pack('<I', value).decode('ascii', errors='replace')


def parse_hkx(path):
    """Parse a .hkx file into an HkxFile container."""
    with open(path, 'rb') as fh:
        return parse_hkx_bytes(fh.read())


def parse_hkx_bytes(data):
    """Faithful port of HkxParser::ParseBytes."""
    if len(data) < 0x18:
        raise ValueError("HKX file too small")

    f = HkxFile()
    f.header_field0 = _read_u32_le(data, 0)
    f.header_crc = _read_u32_le(data, 4)
    f.total_size = _read_u32_le(data, 8)

    pos = 0x10
    while pos + 8 <= len(data):
        chunk_size = _read_u32_be(data, pos)
        chunk_tag = _read_u32_le(data, pos + 4)
        payload_size = chunk_size & 0x3FFFFFFF  # includes 8-byte header

        tag_str = _decode_fourcc(chunk_tag)

        if chunk_tag == FOURCC_TAG0 or chunk_tag == FOURCC_INDX:
            # TAG0 header marker / INDX wrapper: skip the 8-byte header only;
            # ITEM/PTCH follow as sibling chunks.
            pos += 8
            continue

        if chunk_tag == FOURCC_SDKV:
            raw = data[pos + 8:pos + 8 + payload_size - 8]
            f.sdk_version = raw.split(b'\x00')[0].decode('ascii', errors='replace')

        elif chunk_tag == FOURCC_DATA:
            data_size = payload_size - 8
            f.data_section = data[pos + 8:pos + 8 + data_size]

        elif chunk_tag == FOURCC_TCRF:
            f.tcrf_section = data[pos + 8:pos + 8 + payload_size - 8]

        elif chunk_tag == FOURCC_ITEM:
            _read_items(data, pos + 8, payload_size - 8, f)

        elif chunk_tag == FOURCC_PTCH:
            _read_patches(data, pos + 8, payload_size - 8, f)

        pos += payload_size

    if not f.data_section:
        raise ValueError("HKX has no DATA section.")

    _slice_item_bytes(f)
    _resolve_fixups(f)
    _find_root(f)
    _extract_all_convex_shapes(f)
    _extract_child_transforms(f)
    return f


def _read_items(buf, off, length, f):
    """ReadItems — each entry is 12 bytes: {u32 typeAndFlags, u32 dataOffset, u32 count}."""
    count = length // 0x0C
    for i in range(count):
        p = off + i * 0x0C
        word0 = _read_u32_le(buf, p)
        word1 = _read_u32_le(buf, p + 4)
        word2 = _read_u32_le(buf, p + 8)
        type_id = word0 & 0xFFFFFF
        flags = (word0 >> 0x1C) & 0x0F
        item = HkxItem(i, type_id, flags, word1, word2)
        f.items.append(item)


def _read_patches(buf, off, length, f):
    """ReadPatches — {u32 pointerType, u32 count, count * u32 pointerLocation} blocks."""
    end = off + length
    pos = off
    while pos + 8 <= end:
        pointer_type = _read_u32_le(buf, pos)
        count = _read_u32_le(buf, pos + 4)
        pos += 8
        for _ in range(count):
            if pos + 4 > end:
                break
            pointer_location = _read_u32_le(buf, pos)
            f.fixups.append(HkxFixup(pointer_type, pointer_location, -1))
            pos += 4


def _slice_item_bytes(f):
    """SliceItemBytes — each item's bytes span its DataOffset to the next item's."""
    ordered = sorted(f.items, key=lambda it: it.data_offset)
    for i, item in enumerate(ordered):
        if item.type_id == 0:
            item.bytes = b''
            continue
        next_offset = (ordered[i + 1].data_offset if i + 1 < len(ordered)
                       else len(f.data_section))
        length = next_offset - item.data_offset
        if item.data_offset < 0 or item.data_offset + length > len(f.data_section):
            item.bytes = b''
            continue
        item.bytes = f.data_section[item.data_offset:item.data_offset + length]


def _resolve_fixups(f):
    """ResolveFixups — a fixup's target is the u32 stored at its PointerLocation."""
    for fixup in f.fixups:
        if fixup.pointer_location + 4 <= len(f.data_section):
            fixup.target_item_index = _read_u32_le(f.data_section, fixup.pointer_location)


def _find_root(f):
    """FindRoot — first item (type != 0) not referenced by any fixup."""
    referenced = {fix.target_item_index for fix in f.fixups}
    for item in f.items:
        if item.type_id != 0 and item.index not in referenced:
            f.root_item_index = item.index
            return


def _find_owning_item(f, loc):
    """FindOwningItem — the item whose [dataOffset, dataOffset+len) contains loc."""
    for item in f.items:
        if item.type_id == 0:
            continue
        start = item.data_offset
        end = start + (len(item.bytes) if item.bytes else 0)
        if start <= loc < end:
            return item
    return None


def _extract_all_convex_shapes(f):
    """ExtractAllConvexShapes."""
    by_idx = {item.index: item for item in f.items}
    fixups_by_owner = {}
    for fixup in f.fixups:
        owner = _find_owning_item(f, fixup.pointer_location)
        if owner is not None:
            fixups_by_owner.setdefault(owner.index, []).append(fixup)

    for item in f.items:
        if item.bytes is None or len(item.bytes) < 0x30:
            continue
        if item.type_id == TYPE_SHAPE_ROOT_QUANT and item.count == 1:
            shape = _try_decode_quantized_shape(item, by_idx, fixups_by_owner)
            if shape is not None:
                f.convex_shapes.append(shape)
        elif item.type_id == TYPE_SHAPE_ROOT_FULL and item.count == 1:
            shape = _try_decode_full_precision_shape(item, by_idx, fixups_by_owner)
            if shape is not None:
                f.convex_shapes.append(shape)


def _try_decode_quantized_shape(shape, by_idx, fixups_by_owner):
    """TryDecodeQuantizedShape — locate shapeData (type 0x2D) via the shape's fixups."""
    shape_data = None
    for fixup in fixups_by_owner.get(shape.index, []):
        target = by_idx.get(fixup.target_item_index)
        if target is not None and target.type_id == TYPE_SHAPE_DATA_QUANT:
            shape_data = target
            break
    if shape_data is None:
        return None

    hdr = None
    verts = None
    idx = None
    for fixup in fixups_by_owner.get(shape_data.index, []):
        target = by_idx.get(fixup.target_item_index)
        if target is None:
            continue
        if target.type_id == TYPE_VERTEX_HEADER_QUANT and hdr is None:
            hdr = target
        elif target.type_id == TYPE_FACE_INDICES_QUANT and idx is None:
            idx = target
        elif (target.type_id == TYPE_VERTEX_OR_PLANE_QUANT
                and target.count >= 4):
            if verts is None or target.count > verts.count:
                verts = target

    if verts is None:
        return None
    return _decode_quantized(shape, shape_data, hdr, verts, idx)


def _decode_quantized(shape, shape_data, hdr, verts, idx):
    """DecodeQuantized — unpack 11/11/10-bit quantized vertices."""
    convex = HkxConvexShape()
    convex.variant = 0
    convex.shape_item_index = shape.index
    convex.vertex_header_item_index = hdr.index if hdr is not None else -1

    sb = shape.bytes
    convex.convex_radius = _read_f32_le(sb, 0x18)

    db = shape_data.bytes
    min_x = _read_f32_le(db, 0x20)
    min_y = _read_f32_le(db, 0x24)
    min_z = _read_f32_le(db, 0x28)
    max_x = _read_f32_le(db, 0x30)
    max_y = _read_f32_le(db, 0x34)
    max_z = _read_f32_le(db, 0x38)
    convex.aabb_min = (min_x, min_y, min_z)
    convex.aabb_max = (max_x, max_y, max_z)
    convex.quant_scale = ((max_x - min_x) / 2047.0,
                          (max_y - min_y) / 2047.0,
                          (max_z - min_z) / 1023.0)

    vb = verts.bytes
    for v in range(verts.count):
        if v * 4 + 4 > len(vb):
            break
        q = _read_u32_le(vb, v * 4)
        x = q & 2047
        y = (q >> 11) & 2047
        z = (q >> 22) & 1023
        convex.vertices.append((min_x + x * convex.quant_scale[0],
                                min_y + y * convex.quant_scale[1],
                                min_z + z * convex.quant_scale[2]))

    if idx is not None:
        ib = idx.bytes
        n = min(idx.count * 4, len(ib))
        convex.quad_indices.extend(ib[:n])

    return convex


def _try_decode_full_precision_shape(shape, by_idx, fixups_by_owner):
    """TryDecodeFullPrecisionShape."""
    verts = None
    idx = None
    planes = None
    for fixup in fixups_by_owner.get(shape.index, []):
        target = by_idx.get(fixup.target_item_index)
        if target is None:
            continue
        if target.type_id == TYPE_VERTICES_FULL and target.count >= 4 and verts is None:
            verts = target
        elif target.type_id == TYPE_FACE_INDICES_FULL and idx is None:
            idx = target
        elif target.type_id == TYPE_PLANES_FULL and planes is None:
            planes = target

    if verts is None:
        return None

    convex = HkxConvexShape()
    convex.variant = 1
    convex.shape_item_index = shape.index
    convex.convex_radius = _read_f32_le(shape.bytes, 0x18)

    vb = verts.bytes
    vertex_list = []
    for v in range(verts.count):
        if v * 0x10 + 0x0C > len(vb):
            break
        vertex_list.append((_read_f32_le(vb, v * 0x10),
                            _read_f32_le(vb, v * 0x10 + 4),
                            _read_f32_le(vb, v * 0x10 + 8)))
    convex.vertices.extend(vertex_list)

    if vertex_list:
        mn = vertex_list[0]
        mx = vertex_list[0]
        for v in vertex_list:
            mn = (min(mn[0], v[0]), min(mn[1], v[1]), min(mn[2], v[2]))
            mx = (max(mx[0], v[0]), max(mx[1], v[1]), max(mx[2], v[2]))
        convex.aabb_min = mn
        convex.aabb_max = mx
        convex.quant_scale = (0.0, 0.0, 0.0)

    if idx is not None:
        ib = idx.bytes
        n = min(idx.count, len(ib))
        convex.quad_indices.extend(ib[:n])

    return convex


def _mat4_identity():
    return [1.0, 0, 0, 0,
            0, 1.0, 0, 0,
            0, 0, 1.0, 0,
            0, 0, 0, 1.0]


def _mat4_is_identity(m):
    return all(abs(m[i] - [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0][i]) < 1e-9
               for i in range(16))


def _mat4_create_translation(v):
    return [1.0, 0, 0, 0,
            0, 1.0, 0, 0,
            0, 0, 1.0, 0,
            v[0], v[1], v[2], 1.0]


def _mat4_create_from_quaternion(q):
    x, y, z, w = q
    return [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w), 0,
            2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w), 0,
            2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y), 0,
            0, 0, 0, 1.0]


def _mat4_multiply(a, b):
    """Row-major 4x4 multiply (matches System.Numerics.Matrix4x4 op_Multiply)."""
    out = [0.0] * 16
    for r in range(4):
        for c in range(4):
            out[r * 4 + c] = sum(a[r * 4 + k] * b[k * 4 + c] for k in range(4))
    return out


def _transform_point(m, v):
    """Transform a point by row-major matrix (w=1)."""
    x, y, z = v
    return (m[0] * x + m[4] * y + m[8] * z + m[12],
            m[1] * x + m[5] * y + m[9] * z + m[13],
            m[2] * x + m[6] * y + m[10] * z + m[14])


def _extract_child_transforms(f):
    """ExtractChildTransforms — 4 phases of transform recovery."""
    ct = f.child_transforms

    # Phase 1: explicit child transform records (type 0x6C, 128 bytes each)
    for item in f.items:
        if item.type_id != 0x6C or item.count == 0 or not item.bytes:
            continue
        if len(item.bytes) < item.count * 128:
            continue
        b = item.bytes
        for i in range(item.count):
            base = i * 128
            m = [0.0] * 16
            m[0] = _read_f32_le(b, base)
            m[1] = _read_f32_le(b, base + 4)
            m[2] = _read_f32_le(b, base + 8)
            m[4] = _read_f32_le(b, base + 0x10)
            m[5] = _read_f32_le(b, base + 0x14)
            m[6] = _read_f32_le(b, base + 0x18)
            m[8] = _read_f32_le(b, base + 0x20)
            m[9] = _read_f32_le(b, base + 0x24)
            m[10] = _read_f32_le(b, base + 0x28)
            m[12] = _read_f32_le(b, base + 0x30)
            m[13] = _read_f32_le(b, base + 0x34)
            m[14] = _read_f32_le(b, base + 0x38)
            m[3] = m[7] = m[11] = 0.0
            m[15] = 1.0
            child_index = _read_u32_le(b, base + 0x50)
            if child_index > 0 and child_index < len(f.items):
                scale = (_read_f32_le(b, base + 0x40),
                         _read_f32_le(b, base + 0x44),
                         _read_f32_le(b, base + 0x48))
                ct[child_index] = HkxChildTransform(child_index, m, scale)

    # Phase 2: shape AABB centers
    centers = {}
    for shape in f.convex_shapes:
        center = ((shape.aabb_min[0] + shape.aabb_max[0]) * 0.5,
                  (shape.aabb_min[1] + shape.aabb_max[1]) * 0.5,
                  (shape.aabb_min[2] + shape.aabb_max[2]) * 0.5)
        centers[shape.shape_item_index] = center

    # Phase 3: proxy AABB alignment records (type 304 / 0x130, 128 bytes each)
    for item in f.items:
        if item.type_id != 304 or item.count == 0 or not item.bytes:
            continue
        if len(item.bytes) < item.count * 128:
            continue
        b = item.bytes
        for i in range(item.count):
            base = i * 128
            min_v = (_read_f32_le(b, base), _read_f32_le(b, base + 4),
                     _read_f32_le(b, base + 8))
            max_v = (_read_f32_le(b, base + 0x10), _read_f32_le(b, base + 0x14),
                     _read_f32_le(b, base + 0x18))
            child_index = _read_u32_le(b, base + 0x20)
            if (child_index <= 0 or child_index >= len(f.items)
                    or child_index in ct or child_index not in centers):
                continue
            if (min_v[0] != min_v[0]) or max_v[0] in (float('inf'), float('-inf')):
                continue
            if not (max_v[0] >= min_v[0] and max_v[1] >= min_v[1]
                    and max_v[2] >= min_v[2]):
                continue
            offset = ((min_v[0] + max_v[0]) * 0.5 - centers[child_index][0],
                      (min_v[1] + max_v[1]) * 0.5 - centers[child_index][1],
                      (min_v[2] + max_v[2]) * 0.5 - centers[child_index][2])
            ct[child_index] = HkxChildTransform(
                child_index, _mat4_create_translation(offset), (1.0, 1.0, 1.0))

    # Phase 4: node->shape records (type 301 / 0x12D), stride >= 0x40
    for item in f.items:
        if item.type_id != 301 or item.count == 0 or not item.bytes:
            continue
        stride = len(item.bytes) // item.count
        if stride < 0x40:
            continue
        b = item.bytes
        for i in range(item.count):
            loc = item.data_offset + i * stride + 8
            target_index = -1
            for fixup in f.fixups:
                if fixup.pointer_location == loc:
                    target_index = fixup.target_item_index
                    break
            if target_index < 0 or target_index >= len(f.items):
                continue
            t_item = f.items[target_index]
            if t_item.type_id not in (TYPE_SHAPE_ROOT_QUANT, TYPE_SHAPE_ROOT_FULL):
                continue
            if target_index in ct:
                continue

            trans = (_read_f32_le(b, i * stride + 0x20),
                     _read_f32_le(b, i * stride + 0x24),
                     _read_f32_le(b, i * stride + 0x28))
            qx = _read_f32_le(b, i * stride + 0x30)
            qy = _read_f32_le(b, i * stride + 0x34)
            qz = _read_f32_le(b, i * stride + 0x38)
            qw = _read_f32_le(b, i * stride + 0x3C)
            qsum = qx * qx + qy * qy + qz * qz + qw * qw

            if qsum != qsum or qsum < 0.5 or qsum > 2.0:
                ct[target_index] = HkxChildTransform(
                    target_index, _mat4_create_translation(trans), (1.0, 1.0, 1.0))
            else:
                m = _mat4_multiply(_mat4_create_translation(trans),
                                   _mat4_create_from_quaternion((qx, qy, qz, qw)))
                ct[target_index] = HkxChildTransform(target_index, m, (1.0, 1.0, 1.0))


def get_shape_transform(f, shape):
    """GetShapeTransform — the transform for a shape, or identity."""
    ct = f.child_transforms.get(shape.shape_item_index)
    if ct is not None:
        return ct.transform
    return _mat4_identity()


def to_triangle_mesh(shape, reverse_winding=False):
    """ToTriangleMesh — convert quad indices to triangles (with diag selection).

    Returns (positions, triangle_indices).
    """
    positions = list(shape.vertices)
    quad_count = shape.quad_count
    tris = []
    q = shape.quad_indices

    for i in range(quad_count):
        i0 = q[i * 4]
        i1 = q[i * 4 + 1]
        i2 = q[i * 4 + 2]
        i3 = q[i * 4 + 3]
        n = len(positions)
        if i0 >= n or i1 >= n or i2 >= n or i3 >= n:
            continue
        p0, p1, p2, p3 = positions[i0], positions[i1], positions[i2], positions[i3]

        d1 = (p2[0] - p0[0]) ** 2 + (p2[1] - p0[1]) ** 2 + (p2[2] - p0[2]) ** 2
        d2 = (p1[0] - p3[0]) ** 2 + (p1[1] - p3[1]) ** 2 + (p1[2] - p3[2]) ** 2

        if d2 > d1:
            t1 = (i0, i1, i3)
            t2 = (i1, i2, i3)
        else:
            t1 = (i0, i1, i2)
            t2 = (i0, i2, i3)

        if t1[0] == t1[1] or t1[1] == t1[2] or t1[0] == t1[2]:
            pass
        else:
            if reverse_winding:
                tris.extend((t1[0], t1[2], t1[1]))
            else:
                tris.extend(t1)

        if t2[0] == t2[1] or t2[1] == t2[2] or t2[0] == t2[2]:
            continue
        if reverse_winding:
            tris.extend((t2[0], t2[2], t2[1]))
        else:
            tris.extend(t2)

    return positions, tris


def to_transformed_triangle_mesh(f, shape, reverse_winding=False):
    """ToTransformedTriangleMesh — mesh with shape transforms applied."""
    positions, tris = to_triangle_mesh(shape, reverse_winding)
    m = get_shape_transform(f, shape)
    if not _mat4_is_identity(m):
        positions = [_transform_point(m, v) for v in positions]
    return positions, tris


def get_item_data(f, item):
    """Extract raw bytes for an item (already populated by _slice_item_bytes)."""
    return item.bytes


# ── OBJ round trip (HavokDisrupt LoadObj / ExportObj ports) ────────────────

class ObjGroup:
    __slots__ = ('name', 'vertices', 'triangles')

    def __init__(self):
        self.name = ''
        self.vertices = []      # list of (x, y, z)
        self.triangles = []     # flat list of int vertex indices (group-local)

    def __repr__(self):
        return f"ObjGroup({self.name!r} verts={len(self.vertices)} tris={len(self.triangles) // 3})"


def load_obj(path):
    """LoadObj — parse a Wavefront .obj into a list of ObjGroup.

    Supports `o`/`g` groups, `v` vertices and `f` faces (with v/vt/vn and
    negative index forms). Face indices are converted to group-local 0-based.
    """
    groups = []
    all_vertices = []
    current = None
    base_index = 0

    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        lines = fh.readlines()

    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith('#'):
            continue
        if line.startswith('o ') or line.startswith('g '):
            current = ObjGroup()
            current.name = line[2:].strip()
            groups.append(current)
            base_index = len(all_vertices)
        elif line.startswith('v '):
            parts = line.split()
            if len(parts) >= 4:
                v = (float(parts[1]), float(parts[2]), float(parts[3]))
                all_vertices.append(v)
                if current is not None:
                    current.vertices.append(v)
        elif line.startswith('f '):
            if current is None:
                current = ObjGroup()
                current.name = 'default'
                groups.append(current)
                base_index = 0
            parts = line.split()
            indices = []
            for j in range(1, len(parts)):
                idx_str = parts[j].split('/')[0]
                idx = int(idx_str)
                if idx < 0:
                    idx = len(all_vertices) + idx + 1
                idx = idx - 1 - base_index
                indices.append(idx)
            for i in range(1, len(indices) - 1):
                current.triangles.append(indices[0])
                current.triangles.append(indices[i])
                current.triangles.append(indices[i + 1])

    return groups


def export_obj(f, out_path, apply_transforms=True, reverse_winding=False):
    """ExportObj — write all convex shapes to a single Wavefront .obj."""
    with open(out_path, 'w', encoding='utf-8') as fh:
        fh.write("# Exported from Watch Dogs 2 .hkx collision\n")
        fh.write("# Convex shapes: %d\n\n" % len(f.convex_shapes))
        vertex_base = 1
        for i, shape in enumerate(f.convex_shapes):
            if apply_transforms:
                positions, tri_idx = to_transformed_triangle_mesh(f, shape, reverse_winding)
            else:
                positions, tri_idx = to_triangle_mesh(shape, reverse_winding)
            fh.write("o shape_%d_item_%d\n" % (i, shape.shape_item_index))
            for v in positions:
                fh.write("v %.17g %.17g %.17g\n" % v)
            for j in range(0, len(tri_idx), 3):
                fh.write("f %d %d %d\n" % (tri_idx[j] + vertex_base,
                                           tri_idx[j + 1] + vertex_base,
                                           tri_idx[j + 2] + vertex_base))
            vertex_base += len(positions)
            fh.write("\n")


# ── Injection (HavokDisrupt InjectObjIntoShape / InjectFullPrecisionShape /
#    AutoFitAndInject ports) ────────────────────────────────────────────────

def _write_u32(buf, off, val):
    struct.pack_into('<I', buf, off, val & 0xFFFFFFFF)


def _write_f32(buf, off, val):
    struct.pack_into('<f', buf, off, val)


def _locate_data_section(buf):
    """Find the file offset of the DATA payload in raw hkx bytes."""
    pos = 0x10
    while pos + 8 <= len(buf):
        word0 = _read_u32_be(buf, pos)
        tag = _read_u32_le(buf, pos + 4)
        size = word0 & 0x3FFFFFFF
        if tag == FOURCC_TAG0 or tag == FOURCC_INDX:
            pos += 8
            continue
        if tag == FOURCC_DATA:
            return pos + 8
        pos += size
    return -1


def _find_shape_data_item(f, shape_item, by_idx):
    """Locate the shape_data item (type 0x2D) referenced from the shape item."""
    for fixup in f.fixups:
        if fixup.pointer_location < shape_item.data_offset:
            continue
        if fixup.pointer_location >= shape_item.data_offset + len(shape_item.bytes):
            continue
        target = by_idx.get(fixup.target_item_index)
        if target is not None and target.type_id == TYPE_SHAPE_DATA_QUANT:
            return target
    return None


def _find_verts_and_hdr(f, owner_item, by_idx):
    """Find vertex array (0x25, largest Count >= 4) and vertex header (0x49)."""
    verts_item = None
    hdr_item = None
    for fixup in f.fixups:
        if fixup.pointer_location < owner_item.data_offset:
            continue
        if fixup.pointer_location >= owner_item.data_offset + len(owner_item.bytes):
            continue
        target = by_idx.get(fixup.target_item_index)
        if target is None:
            continue
        if target.type_id == TYPE_VERTEX_OR_PLANE_QUANT and target.count >= 4:
            if verts_item is None or target.count > verts_item.count:
                verts_item = target
        elif target.type_id == TYPE_VERTEX_HEADER_QUANT and hdr_item is None:
            hdr_item = target
    return verts_item, hdr_item


def inject_obj_into_shape(f, shape_index, obj, original_file_bytes):
    """InjectObjIntoShape — vertex-displacement-only injection.

    obj.vertices must match the original vertex count and order. Writes into a
    clone of the file bytes and returns the new bytes.
    """
    if shape_index < 0 or shape_index >= len(f.convex_shapes):
        raise ValueError("Invalid shape index.")
    shape = f.convex_shapes[shape_index]

    if shape.variant == 1:
        return inject_full_precision_shape(f, shape_index, obj, original_file_bytes)
    if shape.variant != 0:
        raise NotImplementedError("Unknown shape variant.")

    by_idx = {item.index: item for item in f.items}
    shape_item = by_idx[shape.shape_item_index]

    shape_data = _find_shape_data_item(f, shape_item, by_idx)
    if shape_data is None:
        raise ValueError("Could not locate shape_data for this shape.")

    verts_item, hdr_item = _find_verts_and_hdr(f, shape_data, by_idx)
    if verts_item is None:
        raise ValueError("Could not locate vertex array.")

    original_vertex_count = verts_item.count
    if len(obj.vertices) != original_vertex_count:
        raise ValueError(
            "Vertex count mismatch: OBJ has %d vertices, original has %d. "
            "Injection is VERTEX-DISPLACEMENT-ONLY: you must preserve the "
            "exact vertex count (and order)." % (len(obj.vertices), original_vertex_count))

    new_bytes = bytearray(original_file_bytes)
    data_offset = _locate_data_section(new_bytes)
    if data_offset < 0:
        raise ValueError("Could not locate DATA section.")

    min_v = obj.vertices[0]
    max_v = obj.vertices[0]
    for v in obj.vertices:
        min_v = (min(min_v[0], v[0]), min(min_v[1], v[1]), min(min_v[2], v[2]))
        max_v = (max(max_v[0], v[0]), max(max_v[1], v[1]), max(max_v[2], v[2]))

    # shape_data AABB at +0x20 (min) / +0x30 (max)
    write_pos = data_offset + shape_data.data_offset + 0x20
    _write_f32(new_bytes, write_pos + 0x00, min_v[0])
    _write_f32(new_bytes, write_pos + 0x04, min_v[1])
    _write_f32(new_bytes, write_pos + 0x08, min_v[2])
    _write_f32(new_bytes, write_pos + 0x10, max_v[0])
    _write_f32(new_bytes, write_pos + 0x14, max_v[1])
    _write_f32(new_bytes, write_pos + 0x18, max_v[2])

    # vertex header AABB at +0x10
    if hdr_item is not None:
        hdr_pos = data_offset + hdr_item.data_offset + 0x10
        _write_f32(new_bytes, hdr_pos + 0x00, min_v[0])
        _write_f32(new_bytes, hdr_pos + 0x04, min_v[1])
        _write_f32(new_bytes, hdr_pos + 0x08, min_v[2])
        _write_f32(new_bytes, hdr_pos + 0x10, max_v[0])
        _write_f32(new_bytes, hdr_pos + 0x14, max_v[1])
        _write_f32(new_bytes, hdr_pos + 0x18, max_v[2])

    verts_pos = data_offset + verts_item.data_offset
    scale_x = (max_v[0] - min_v[0]) / 2047.0
    scale_y = (max_v[1] - min_v[1]) / 2047.0
    scale_z = (max_v[2] - min_v[2]) / 1023.0

    for i, v in enumerate(obj.vertices):
        if scale_x > 0.0:
            qx = max(0, min(2047, int(round((v[0] - min_v[0]) / scale_x))))
        else:
            qx = 0
        if scale_y > 0.0:
            qy = max(0, min(2047, int(round((v[1] - min_v[1]) / scale_y))))
        else:
            qy = 0
        if scale_z > 0.0:
            qz = max(0, min(1023, int(round((v[2] - min_v[2]) / scale_z))))
        else:
            qz = 0
        packed = (qy << 0x0B) | qx | (qz << 0x16)
        _write_u32(new_bytes, verts_pos + i * 4, packed)

    return bytes(new_bytes)


def inject_full_precision_shape(f, shape_index, obj, original_file_bytes):
    """InjectFullPrecisionShape — float32 vertex displacement for type-0x93 shapes."""
    shape = f.convex_shapes[shape_index]
    by_idx = {item.index: item for item in f.items}
    shape_item = by_idx[shape.shape_item_index]

    verts_item = None
    planes_item = None
    idx_item = None
    for fixup in f.fixups:
        if fixup.pointer_location < shape_item.data_offset:
            continue
        if fixup.pointer_location >= shape_item.data_offset + len(shape_item.bytes):
            continue
        target = by_idx.get(fixup.target_item_index)
        if target is None:
            continue
        if target.type_id == TYPE_VERTICES_FULL and target.count >= 4:
            verts_item = target
        elif target.type_id == TYPE_PLANES_FULL:
            planes_item = target
        elif target.type_id == TYPE_FACE_INDICES_FULL:
            idx_item = target

    if verts_item is None:
        raise ValueError("Could not locate vertex array (type 87).")

    original_vertex_count = verts_item.count
    if len(obj.vertices) != original_vertex_count:
        raise ValueError(
            "Vertex count mismatch: OBJ has %d vertices, original has %d. "
            "Injection is VERTEX-DISPLACEMENT-ONLY: preserve the exact "
            "vertex count (and order)." % (len(obj.vertices), original_vertex_count))

    new_bytes = bytearray(original_file_bytes)
    data_offset = _locate_data_section(new_bytes)
    if data_offset < 0:
        raise ValueError("No DATA section.")

    verts_pos = data_offset + verts_item.data_offset
    for i, v in enumerate(obj.vertices):
        _write_f32(new_bytes, verts_pos + i * 0x10 + 0x00, v[0])
        _write_f32(new_bytes, verts_pos + i * 0x10 + 0x04, v[1])
        _write_f32(new_bytes, verts_pos + i * 0x10 + 0x08, v[2])

    if planes_item is not None and idx_item is not None:
        if (planes_item.count > 0 and idx_item.count > 0
                and idx_item.count % planes_item.count == 0):
            ratio = idx_item.count // planes_item.count
            planes_pos = data_offset + planes_item.data_offset
            idx_pos = data_offset + idx_item.data_offset
            for p in range(planes_item.count):
                px = _read_f32_le(new_bytes, planes_pos + p * 0x10)
                py = _read_f32_le(new_bytes, planes_pos + p * 0x10 + 4)
                pz = _read_f32_le(new_bytes, planes_pos + p * 0x10 + 8)
                vi = new_bytes[idx_pos + p * ratio]
                if vi < len(obj.vertices):
                    v = obj.vertices[vi]
                    offset = -(px * v[0] + py * v[1] + pz * v[2])
                    _write_f32(new_bytes, planes_pos + p * 0x10 + 0x0C, offset)

    return bytes(new_bytes)


def auto_fit_and_inject(f, shape_index, obj, original_file_bytes,
                        preserve_scale=False, uniform_scale=False):
    """AutoFitAndInject — resample any OBJ onto a shape's vertex set.

    Fits the OBJ into the shape's AABB (optionally preserving scale / using a
    uniform scale), builds a dense point cloud from the fitted surface, then
    projects each original shape vertex onto the cloud along its direction
    from the shape center. The result is a vertex list with the exact original
    count/order, safe for vertex-displacement injection.
    """
    if shape_index < 0 or shape_index >= len(f.convex_shapes):
        raise ValueError("Invalid shape index.")
    if len(obj.vertices) < 4:
        raise ValueError("OBJ needs at least 4 vertices.")
    shape = f.convex_shapes[shape_index]

    shape_center = ((shape.aabb_min[0] + shape.aabb_max[0]) * 0.5,
                    (shape.aabb_min[1] + shape.aabb_max[1]) * 0.5,
                    (shape.aabb_min[2] + shape.aabb_max[2]) * 0.5)
    shape_extents = (shape.aabb_max[0] - shape.aabb_min[0],
                     shape.aabb_max[1] - shape.aabb_min[1],
                     shape.aabb_max[2] - shape.aabb_min[2])

    obj_min = obj.vertices[0]
    obj_max = obj.vertices[0]
    for v in obj.vertices:
        obj_min = (min(obj_min[0], v[0]), min(obj_min[1], v[1]), min(obj_min[2], v[2]))
        obj_max = (max(obj_max[0], v[0]), max(obj_max[1], v[1]), max(obj_max[2], v[2]))
    obj_center = ((obj_min[0] + obj_max[0]) * 0.5,
                  (obj_min[1] + obj_max[1]) * 0.5,
                  (obj_min[2] + obj_max[2]) * 0.5)
    obj_extents = (obj_max[0] - obj_min[0],
                   obj_max[1] - obj_min[1],
                   obj_max[2] - obj_min[2])

    fitted = []
    if preserve_scale:
        for v in obj.vertices:
            fitted.append((v[0] - obj_center[0] + shape_center[0],
                           v[1] - obj_center[1] + shape_center[1],
                           v[2] - obj_center[2] + shape_center[2]))
    else:
        scale_x = shape_extents[0] / obj_extents[0] if obj_extents[0] > 1e-6 else 1.0
        scale_y = shape_extents[1] / obj_extents[1] if obj_extents[1] > 1e-6 else 1.0
        scale_z = shape_extents[2] / obj_extents[2] if obj_extents[2] > 1e-6 else 1.0
        if uniform_scale:
            m = min(scale_x, scale_y, scale_z)
            scale_x = scale_y = scale_z = m
        for v in obj.vertices:
            d = (v[0] - obj_center[0], v[1] - obj_center[1], v[2] - obj_center[2])
            fitted.append((shape_center[0] + d[0] * scale_x,
                           shape_center[1] + d[1] * scale_y,
                           shape_center[2] + d[2] * scale_z))

    transformed = list(fitted)
    tri_count = len(obj.triangles) // 3
    for t in range(tri_count):
        i0 = obj.triangles[t * 3]
        i1 = obj.triangles[t * 3 + 1]
        i2 = obj.triangles[t * 3 + 2]
        if i0 >= len(fitted) or i1 >= len(fitted) or i2 >= len(fitted):
            continue
        p0 = fitted[i0]
        p1 = fitted[i1]
        p2 = fitted[i2]
        transformed.append(((p0[0] + p1[0] + p2[0]) / 3.0,
                            (p0[1] + p1[1] + p2[1]) / 3.0,
                            (p0[2] + p1[2] + p2[2]) / 3.0))
        transformed.append(((p0[0] + p1[0]) * 0.5, (p0[1] + p1[1]) * 0.5, (p0[2] + p1[2]) * 0.5))
        transformed.append(((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5, (p1[2] + p2[2]) * 0.5))
        transformed.append(((p2[0] + p0[0]) * 0.5, (p2[1] + p0[1]) * 0.5, (p2[2] + p0[2]) * 0.5))
        transformed.append((p0[0] * 0.6 + p1[0] * 0.2 + p2[0] * 0.2,
                            p0[1] * 0.6 + p1[1] * 0.2 + p2[1] * 0.2,
                            p0[2] * 0.6 + p1[2] * 0.2 + p2[2] * 0.2))
        transformed.append((p0[0] * 0.2 + p1[0] * 0.6 + p2[0] * 0.2,
                            p0[1] * 0.2 + p1[1] * 0.6 + p2[1] * 0.2,
                            p0[2] * 0.2 + p1[2] * 0.6 + p2[2] * 0.2))
        transformed.append((p0[0] * 0.2 + p1[0] * 0.2 + p2[0] * 0.6,
                            p0[1] * 0.2 + p1[1] * 0.2 + p2[1] * 0.6,
                            p0[2] * 0.2 + p1[2] * 0.2 + p2[2] * 0.6))

    centroid = (0.0, 0.0, 0.0)
    for v in transformed:
        centroid = (centroid[0] + v[0], centroid[1] + v[1], centroid[2] + v[2])
    n = len(transformed)
    centroid = (centroid[0] / n, centroid[1] / n, centroid[2] / n)

    new_verts = []
    for i in range(len(shape.vertices)):
        p = (shape.vertices[i][0] - shape_center[0],
             shape.vertices[i][1] - shape_center[1],
             shape.vertices[i][2] - shape_center[2])
        plen = (p[0] ** 2 + p[1] ** 2 + p[2] ** 2) ** 0.5
        if plen < 1e-6:
            new_verts.append(centroid)
            continue
        p = (p[0] / plen, p[1] / plen, p[2] / plen)
        best_dot = -3.402823466e+38
        for v in transformed:
            d = (v[0] - centroid[0], v[1] - centroid[1], v[2] - centroid[2])
            dot = d[0] * p[0] + d[1] * p[1] + d[2] * p[2]
            if dot > best_dot:
                best_dot = dot
        new_verts.append((centroid[0] + p[0] * best_dot,
                          centroid[1] + p[1] * best_dot,
                          centroid[2] + p[2] * best_dot))

    new_obj = ObjGroup()
    new_obj.name = 'autofit'
    new_obj.vertices = new_verts
    new_obj.triangles = []
    return inject_obj_into_shape(f, shape_index, new_obj, original_file_bytes)