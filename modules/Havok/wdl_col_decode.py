#!/usr/bin/env python3
"""Standalone WDL compressed-mesh decoder (TAG0 .col.hkx) — validation build.

Self-contained: parses the Dunia TAG0 container inline, resolves the PTCH
fixup graph, and decodes hkpBvCompressedMeshShape geometry.

Usage:
    python3 wdl_col_decode.py <file.col.hkx>

Output: vertex/face counts, bounding box, face-index validity check.

Based on blender-io-disrupt modules/Havok/ (tag0_compressed_mesh.py +
import_hkx.py). Item-type -> array mapping (verified on retail + leak):
    0x7e = section headers (0x60 bytes each)
    0x3c = packed vertices (u32, 11/11/10-bit)
    0x80 = primitives (u8[4])
    0x04 = sharedVerticesIndex (u16)
    0x10 = shared vertices data (u64, 21/21/22-bit)
    0x62 = compound shape (domain AABB @ +0x30 min / +0x40 max)
"""

import struct
import sys


# ---------------------------------------------------------------- TAG0 parse
def parse_tag0(path):
    """Parse Dunia TAG0 container. Returns (data_section, items, fixups)."""
    d = open(path, 'rb').read()
    if len(d) < 0x18:
        raise ValueError('too small')
    pos = 0x10  # after 16-byte Dunia header
    chunks = {}
    while pos + 8 <= len(d):
        chunk_size = struct.unpack_from('>I', d, pos)[0]      # BE size
        chunk_tag = struct.unpack_from('<I', d, pos + 4)[0]   # LE fourcc
        payload = chunk_size & 0x3FFFFFFF                     # incl 8-byte hdr
        tag = struct.pack('<I', chunk_tag)
        if tag in (b'TAG0', b'INDX'):
            pos += 8  # wrapper: children follow as siblings
            continue
        chunks.setdefault(tag, []).append((pos + 8, payload - 8))
        pos += payload
    if b'DATA' not in chunks:
        raise KeyError('no DATA chunk')
    dbase, dsize = chunks[b'DATA'][0]
    data_sec = d[dbase:dbase + dsize]

    items, fixups = [], []
    if b'ITEM' in chunks:
        for (base, size) in chunks[b'ITEM']:
            n = size // 0x0C
            for i in range(n):
                e = base + i * 12
                word0 = struct.unpack_from('<I', d, e)[0]
                data_off = struct.unpack_from('<I', d, e + 4)[0]
                count = struct.unpack_from('<I', d, e + 8)[0]
                items.append({
                    'type_id': word0 & 0xFFFFFF,
                    'flags': (word0 >> 0x1C) & 0x0F,
                    'data_offset': data_off, 'count': count,
                    'index': len(items),
                    'bytes': None,  # filled after all items parsed
                })
    # Slice item bytes: each item spans its data_offset to the next item's.
    ordered = sorted(items, key=lambda it: it['data_offset'])
    for i, it in enumerate(ordered):
        if it['type_id'] == 0:
            it['bytes'] = b''
            continue
        next_off = ordered[i + 1]['data_offset'] if i + 1 < len(ordered) else len(data_sec)
        it['bytes'] = data_sec[it['data_offset']:next_off]
    if b'PTCH' in chunks:
        for (base, size) in chunks[b'PTCH']:
            p, end = base, base + size
            while p + 8 <= end:
                ptr_type = struct.unpack_from('<I', d, p)[0]
                count = struct.unpack_from('<I', d, p + 4)[0]
                p += 8
                for _ in range(count):
                    loc = struct.unpack_from('<I', d, p)[0]
                    # target item index = the u32 VALUE stored at loc
                    target = -1
                    if loc + 4 <= len(data_sec):
                        target = struct.unpack_from('<I', data_sec, loc)[0]
                    fixups.append({
                        'pointer_location': loc,
                        'pointer_type': ptr_type,
                        'target_item_index': target,
                    })
                    p += 4
    return data_sec, items, fixups


# ------------------------------------------------------------- decompress
def decompress_packed(vtx, offset, scale):
    x = (vtx & 0x7FF) * scale[0] + offset[0]
    y = ((vtx >> 11) & 0x7FF) * scale[1] + offset[1]
    z = ((vtx >> 22) & 0x3FF) * scale[2] + offset[2]
    return (x, y, z, 1.0)


def decompress_shared(vtx, dmin, dmax):
    sx = dmax[0] - dmin[0]; sy = dmax[1] - dmin[1]; sz = dmax[2] - dmin[2]
    x = (vtx & 0x1FFFFF) / 2097151.0 * sx + dmin[0]
    y = ((vtx >> 21) & 0x1FFFFF) / 2097151.0 * sy + dmin[1]
    z = ((vtx >> 42) & 0x3FFFFF) / 4194303.0 * sz + dmin[2]
    return (x, y, z, 1.0)


# ------------------------------------------------------------------ decode
def decode_mesh(data_sec, items, fixups, shape_item):
    def owner_of(item_idx):
        for fx in fixups:
            if fx['target_item_index'] == item_idx:
                for it in items:
                    if it['type_id'] != 0 and it['bytes']:
                        s, e = it['data_offset'], it['data_offset'] + len(it['bytes'])
                        if s <= fx['pointer_location'] < e:
                            return it
        return None

    owner = owner_of(shape_item['index'])
    if owner is None or owner['type_id'] != 0x7e:
        return [], [], 'no owner (0x7e)'
    sections = owner['bytes']
    gp = owner_of(owner['index'])

    packed = prims = svi = shared = None
    shared_cands = []
    if gp is not None:
        for fx in fixups:
            s, e = gp['data_offset'], gp['data_offset'] + len(gp['bytes'])
            if s <= fx['pointer_location'] < e:
                it = items[fx['target_item_index']]
                if it['type_id'] == 0x3c and packed is None:
                    packed = it['bytes']
                elif it['type_id'] == 0x80 and prims is None:
                    prims = it['bytes']
                elif it['type_id'] == 0x04 and svi is None:
                    svi = it['bytes']
                elif it['type_id'] in (0x10, 0x6f):
                    shared_cands.append(it['bytes'])
        if shared_cands:
            shared = max(shared_cands, key=len)
        dmin = dmax = None
        if gp['type_id'] == 0x62 and len(gp['bytes']) >= 0x50:
            gb = gp['bytes']
            dmin = struct.unpack_from('<3f', gb, 0x30)
            dmax = struct.unpack_from('<3f', gb, 0x40)
    else:
        dmin = dmax = None

    # domain fallback: first section AABB
    if dmin is None and len(sections) >= 0x28:
        dmin = struct.unpack_from('<3f', sections, 0x10)
        dmax = struct.unpack_from('<3f', sections, 0x20)

    shared_dec = []
    if shared and dmin and dmax:
        for i in range(len(shared) // 8):
            sv = struct.unpack_from('<Q', shared, i * 8)[0]
            shared_dec.append(decompress_shared(sv, dmin, dmax))

    all_v, all_f = [], []
    voff = 0
    n_sec = len(sections) // 0x60
    for si in range(n_sec):
        so = si * 0x60
        offset = struct.unpack_from('<3f', sections, so + 0x30)
        scale = struct.unpack_from('<3f', sections, so + 0x3c)
        first_packed = struct.unpack_from('<I', sections, so + 0x48)[0]
        num_packed = sections[so + 0x58]
        num_shd = sections[so + 0x59]
        shd_start = struct.unpack_from('<I', sections, so + 0x4c)[0] >> 8
        pd = struct.unpack_from('<I', sections, so + 0x50)[0]
        prim_start, prim_count = pd >> 8, pd & 0xFF

        verts = []
        if packed:
            for i in range(num_packed):
                idx = first_packed + i
                if idx * 4 + 4 <= len(packed):
                    v = struct.unpack_from('<I', packed, idx * 4)[0]
                    verts.append(decompress_packed(v, offset, scale))
        if svi is not None:
            for i in range(num_shd):
                j = shd_start + i
                if j * 2 + 2 <= len(svi):
                    g = struct.unpack_from('<H', svi, j * 2)[0]
                    if g < len(shared_dec):
                        verts.append(shared_dec[g])

        if prims:
            for i in range(prim_count):
                idx = prim_start + i
                if idx * 4 + 4 <= len(prims):
                    a, b, c, d = struct.unpack_from('<4B', prims, idx * 4)
                    if b != d:
                        if c == d:
                            all_f.append((voff + a, voff + b, voff + c))
                        else:
                            all_f.append((voff + a, voff + b, voff + c))
                            all_f.append((voff + a, voff + c, voff + d))
        all_v.extend(verts)
        voff += len(verts)
    return all_v, all_f, None


# -------------------------------------------------------------------- main
def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    data_sec, items, fixups = parse_tag0(path)
    shapes = [it for it in items if it['type_id'] == 0x94]
    print(f'{path}')
    print(f'  data={len(data_sec)}B items={len(items)} fixups={len(fixups)} shapes={len(shapes)}')
    total_v = total_f = 0
    for sh in shapes:
        v, f, err = decode_mesh(data_sec, items, fixups, sh)
        if err:
            continue
        mx = max((max(fc) for fc in f), default=-1)
        ok = mx < len(v) if f else True
        total_v += len(v); total_f += len(f)
        print(f'  shape[{sh["index"]}] {len(v)} verts {len(f)} faces valid={ok}')
        if v:
            xs = [p[0] for p in v]; ys = [p[1] for p in v]; zs = [p[2] for p in v]
            print(f'    bbox x[{min(xs):.2f},{max(xs):.2f}] y[{min(ys):.2f},{max(ys):.2f}] '
                  f'z[{min(zs):.2f},{max(zs):.2f}]')
    print(f'  TOTAL: {total_v} verts, {total_f} faces')


if __name__ == '__main__':
    main()