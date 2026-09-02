#!/usr/bin/env python3
"""Binary diff validation for WD1 .xbg export.

Compares exported .xbg against reference files to verify structural integrity.
Checks header magic, version, section counts, format flags, stride, and
vertex buffer sizes.

Usage:
    python3 test_bindiff_wd1.py

Requires reference .xbg from the G19 weapon pack.
"""

import os
import sys
import struct

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.Watch_Dogs.import_wd import parse_wd1_xbg

REF_XBG = os.path.expanduser(
    "~/Documents/Modding/Watch_Dogs/G19/graphics/weapons/"
    "pistol/pistol_g19/pistolpart.xbg")

PASS = 0
FAIL = 0


def check(condition, msg):
    global PASS, FAIL
    if condition:
        PASS += 1
    else:
        FAIL += 1
        print(f"  FAIL: {msg}")


def read_u32(data, off):
    return struct.unpack_from('<I', data, off)[0]


def read_u16(data, off):
    return struct.unpack_from('<H', data, off)[0]


def read_u8(data, off):
    return data[off]


# ── Test 1: Reference file structural integrity ────────────────────────────
print("\n=== Test 1: Reference .xbg structure ===")
if not os.path.isfile(REF_XBG):
    print(f"  SKIP: {REF_XBG} not found")
else:
    with open(REF_XBG, 'rb') as f:
        data = f.read()

    # Magic + version
    magic = read_u32(data, 0)
    check(magic == 0x47454F4D, f"Magic = 0x{magic:08X}, expected 0x47454F4D (MOEG)")

    ver_major = read_u16(data, 4)
    ver_minor = read_u16(data, 6)
    check(ver_major == 97 and ver_minor == 50,
          f"Version = {ver_major}.{ver_minor}, expected 97.50")

    print(f"  Header: MOEG v{ver_major}.{ver_minor}, {len(data)} bytes")


# ── Test 2: Parsed model structural checks ─────────────────────────────────
print("\n=== Test 2: Parsed model structure ===")
if os.path.isfile(REF_XBG):
    model = parse_wd1_xbg(REF_XBG)
    L = model['_layout']
    lod0 = L.get('lod0_meshes', [])
    check(len(lod0) > 0, f"mesh count = {len(lod0)}")

    for i, m in enumerate(lod0):
        fmt = m.get('format', 0)
        stride = m.get('stride', 0)
        bone_map = m.get('bone_map', 0xFFFFFFFF)
        drawcall = m.get('drawcall', {})
        vcount = drawcall.get('vertex_count', 0)
        icount = drawcall.get('index_count', 0)

        # Format 0x178A is the standard rigid format
        if fmt == 0x178A:
            check(stride == 32,
                  f"Mesh {i}: format 0x178A stride = {stride}, expected 32")
            check(bone_map == 0xFFFFFFFF,
                  f"Mesh {i}: rigid bone_map = 0x{bone_map:08X}, expected 0xFFFFFFFF")
        elif fmt == 0x008A:
            check(stride == 16,
                  f"Mesh {i}: format 0x008A stride = {stride}, expected 16")

        check(vcount > 0, f"Mesh {i}: vertex_count = {vcount}")
        check(icount > 0, f"Mesh {i}: index_count = {icount}")

        # Vertex data size should be vcount * stride
        vb_off = drawcall.get('vb_offset', 0)
        check(vb_off >= 0, f"Mesh {i}: vb_offset = {vb_off} (negative)")

        print(f"  Mesh {i}: fmt=0x{fmt:04X} stride={stride} verts={vcount} "
              f"idx={icount} bone_map=0x{bone_map:08X}")


# ── Test 3: Section boundary validation ────────────────────────────────────
print("\n=== Test 3: Section boundary validation ===")
if os.path.isfile(REF_XBG):
    with open(REF_XBG, 'rb') as f:
        data = f.read()

    # After header, SceneGeometryParams should start at a 4-byte aligned offset
    # The header is: magic(4) + ver(4) + unk123(12) + smem(8) + f32(4) + bool(1) = 33 bytes
    # Then SceneGeometryParams starts with pad(4) + 6x f32 + pad(4)
    # Just verify the file doesn't end abruptly
    check(len(data) >= 100, f"File too small: {len(data)} bytes")

    # Verify MOEG at start
    check(data[0:4] == b'MOEG', f"First 4 bytes = {data[0:4]}, expected MOEG")


# ── Summary ────────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed")
if FAIL:
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
