"""XBG FNV-1a 64-bit hash utilities.

WD1/WD2/WDL .xbg files embed a 64-bit FNV-1a hash of the file contents
(used for cache validation / asset identity).  This module provides the
hash calculation and file-patching routines, matching Xbg.Net48's
XBGHashUpdater implementation.

FNV-1a 64-bit parameters:
    prime  = 0x100000001B3
    offset = 0xCBF29CE484222325  (FNV1_64A_INIT)
"""

import os
import struct

FNV1A_64_PRIME = 0x100000001B3
FNV1A_64_INIT = 0xCBF29CE484222325


def fnv1a_64(data):
    h = FNV1A_64_INIT
    for b in data:
        h ^= b
        h = (h * FNV1A_64_PRIME) & 0xFFFFFFFFFFFFFFFF
    return h


def read_xbg_hash(filepath):
    with open(filepath, 'rb') as f:
        hdr = f.read(24)
    return struct.unpack_from('<Q', hdr, 0x18)[0]


def calculate_xbg_hash(filepath):
    with open(filepath, 'rb') as f:
        data = f.read()
    return fnv1a_64(data)


def update_xbg_hash(filepath, output_path=None):
    h = calculate_xbg_hash(filepath)
    with open(filepath, 'r+b') as f:
        f.seek(0x18)
        f.write(struct.pack('<Q', h))
    if output_path and output_path != filepath:
        import shutil
        shutil.copy2(filepath, output_path)
    return h
