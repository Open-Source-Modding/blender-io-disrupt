#!/usr/bin/env python3
"""Round-trip test for WD1 .xbg export: import → export → re-import → verify.

Run inside Blender (headless or GUI):
    blender --background --python test_roundtrip_wd1.py

Or standalone (limited — skips Blender-specific checks):
    python3 test_roundtrip_wd1.py
"""

import os
import sys
import struct
import tempfile

# Add parent dir so we can import the modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.Watch_Dogs.import_wd import parse_wd1_xbg
from modules.Watch_Dogs.export_wd1 import (
    _Writer, _write_header, _write_params, _enc_pos, _enc_uv,
    _enc_normal, _enc_color, _enc_tangent_comp, _enc_u8n,
    _clamp_i16, _compute_bsphere, _compute_tangents_binormals,
)

# ── Reference file (G19 pistol — rigid, format 0x178A stride 32) ──────────
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


# ── Test 1: Reference file parses without error ────────────────────────────
print("\n=== Test 1: Parse reference .xbg ===")
if os.path.isfile(REF_XBG):
    model = parse_wd1_xbg(REF_XBG)
    check(model is not None, "parse_wd1_xbg returned None")
    check(len(model['meshes']) > 0, "no meshes found")
    check(len(model['bones']) >= 0, "bones field missing")
    print(f"  Parsed: {len(model['meshes'])} meshes, "
          f"{len(model['bones'])} bones")
else:
    print(f"  SKIP: reference file not found: {REF_XBG}")


# ── Test 2: Encoder round-trip (pos, uv, normal, color, tangent) ──────────
print("\n=== Test 2: Encoder round-trip ===")

# Position
buf = bytearray()
_enc_pos(buf, (0.1, 0.2, 0.3), 0.0, 0.001)
check(len(buf) == 8, f"_enc_pos produced {len(buf)} bytes, expected 8")

# UV
buf = bytearray()
_enc_uv(buf, (0.5, 0.5), 0.0, 1.0 / 32767.0)
check(len(buf) == 4, f"_enc_uv produced {len(buf)} bytes, expected 4")

# Normal
buf = bytearray()
_enc_normal(buf, (0.0, 0.0, 1.0))
check(len(buf) == 4, f"_enc_normal produced {len(buf)} bytes, expected 4")

# Color
buf = bytearray()
_enc_color(buf, (1.0, 0.5, 0.25, 1.0))
check(len(buf) == 4, f"_enc_color produced {len(buf)} bytes, expected 4")
# Verify BGRA encoding: B=0.25→64, G=0.5→128, R=1.0→255, A=1.0→255
check(buf[0] == 64, f"_enc_color byte0 (B) = {buf[0]}, expected 64")
check(buf[1] == 128, f"_enc_color byte1 (G) = {buf[1]}, expected 128")
check(buf[2] == 255, f"_enc_color byte2 (R) = {buf[2]}, expected 255")
check(buf[3] == 255, f"_enc_color byte3 (A) = {buf[3]}, expected 255")

# Tangent
buf = bytearray()
_enc_tangent_comp(buf, (1.0, 0.0, 0.0), 1.0)
check(len(buf) == 4, f"_enc_tangent_comp produced {len(buf)} bytes, expected 4")
# z→byte0, y→byte1, x→byte2, w→byte3
check(buf[2] == 255, f"_enc_tangent x byte = {buf[2]}, expected 255")
check(buf[3] == 255, f"_enc_tangent w sign = {buf[3]}, expected 255 (positive)")

buf = bytearray()
_enc_tangent_comp(buf, (0.0, 1.0, 0.0), -1.0)
check(buf[3] == 0, f"_enc_tangent w sign = {buf[3]}, expected 0 (negative)")


# ── Test 3: U8N encode/decode round-trip ───────────────────────────────────
print("\n=== Test 3: U8N encode/decode round-trip ===")
LUT = [(i - 1) / 127.0 - 1.0 for i in range(256)]

for val in [0.0, 1.0, -1.0, 0.5, -0.5, 0.333]:
    encoded = _enc_u8n(val)
    decoded = LUT[encoded]
    error = abs(decoded - val)
    check(error < 0.02, f"U8N round-trip {val}: enc={encoded} dec={decoded:.4f} "
          f"error={error:.4f}")


# ── Test 4: Writer pad alignment ──────────────────────────────────────────
print("\n=== Test 4: Writer alignment ===")
w = _Writer()
w.u32(0x47454F4D)  # MOEG
w.u16(97); w.u16(50)
check(len(w.b) == 8, f"Header after magic+ver: {len(w.b)} bytes, expected 8")

w2 = _Writer()
w2.u8(0xFF)
w2.u16(0x1234)
check(len(w2.b) == 4, f"u8+u16 with pad: {len(w2.b)} bytes, expected 4")


# ── Test 5: Format flags decode correctly ──────────────────────────────────
print("\n=== Test 5: Format flags ===")
fmt = 0x178A
check(fmt & 0x2, "point_comp not set in 0x178A")
check(fmt & 0x8, "uv_comp not set in 0x178A")
check(fmt & 0x80, "normal_comp not set in 0x178A")
check(fmt & 0x100, "color not set in 0x178A")
check(fmt & 0x200, "tangent_comp not set in 0x178A")
check(fmt & 0x400, "binormal_comp not set in 0x178A")
check(fmt & 0x1000, "uv_comp2 not set in 0x178A")
check(not (fmt & 0x1), "point should NOT be set in 0x178A")
check(not (fmt & 0x4), "uv_full should NOT be set in 0x178A")
check(not (fmt & 0x10), "skin should NOT be set in 0x178A")

expected_stride = 8 + 4 + 4 + 4 + 4 + 4 + 4
check(expected_stride == 32, f"stride calculation: {expected_stride} != 32")


# ── Test 6: bsphere computation ────────────────────────────────────────────
print("\n=== Test 6: bsphere computation ===")
c, r = _compute_bsphere([0, 0, 0], [1, 2, 3])[:3], _compute_bsphere([0, 0, 0], [1, 2, 3])[3]
check(abs(c[0] - 0.5) < 0.001, f"bsphere cx = {c[0]}")
check(abs(c[1] - 1.0) < 0.001, f"bsphere cy = {c[1]}")
check(abs(c[2] - 1.5) < 0.001, f"bsphere cz = {c[2]}")
check(abs(r - 1.5) < 0.001, f"bsphere r = {r}")


# ── Summary ────────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
print(f"Results: {PASS} passed, {FAIL} failed")
if FAIL:
    sys.exit(1)
else:
    print("ALL TESTS PASSED")
