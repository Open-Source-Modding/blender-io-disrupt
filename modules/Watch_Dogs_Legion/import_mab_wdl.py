"""Watch Dogs Legion .mab (Disrupt 'aNi', magic 0x46B4) parser.

The inner bitstream is identical to WD1 (same smallest-three quaternion codec,
same chunked JointRotations, same 6-byte JointConstantRotations).  The only
difference is the wrapper header:

    WD1:  aNi at 0x14, hashes at aNi+76, section[6]=JointRot, ConstRot at [4]
    WDL:  aNi at 0x20, hashes at aNi+96, section[4]=JointRot, ConstRot at [5]
          extra f32 framerate field at aNi+12
          offsets are aNi-relative (NOT absolute, no +0x10)
          no explicit KeyTimes section — generated from chunk count

Reuses the WD1 bitstream decoder and the apply function."""

import math
import struct
import zlib

try:
    import bpy
    import mathutils
except ImportError:
    bpy = None
    mathutils = None

from ..Watch_Dogs.import_mab_wd import (
    _BitReader,
    _INTERP_SCALE,
    _unpack_const_quat,
    _decode_bone_block,
)

_WDL_MAB_MAGIC = 0x000046B4
_WD2_MAB_MAGIC = 0x000046AF   # WD2 uses identical layout, different magic
_SUPPORTED_MAGICS = {_WDL_MAB_MAGIC, _WD2_MAB_MAGIC}


def parse_wdl_mab(path):
    d = open(path, 'rb').read()
    magic, = struct.unpack_from('<I', d, 0)
    if magic not in _SUPPORTED_MAGICS:
        raise ValueError(
            "not a WDL/WD2 .mab (magic 0x%08X, expected 0x%08X or 0x%08X)"
            % (magic, _WDL_MAB_MAGIC, _WD2_MAB_MAGIC))

    aNi = d.index(b'aNi')
    if aNi != 0x20:
        raise ValueError(
            "WDL .mab: expected aNi at 0x20, found at 0x%04X" % aNi)

    flags = d[aNi + 3]
    size = struct.unpack_from('<I', d, aNi + 4)[0]
    duration = struct.unpack_from('<f', d, aNi + 8)[0]
    framerate = struct.unpack_from('<f', d, aNi + 12)[0]
    n_bones = struct.unpack_from('<H', d, aNi + 16)[0] & 0x7FFF
    counts = struct.unpack_from('<7H', d, aNi + 18)
    offs = struct.unpack_from('<11I', d, aNi + 32)

    # Bone hashes at aNi+96
    hash_start = aNi + 96
    hashes = ()
    if n_bones and hash_start + 4 * n_bones <= len(d):
        hashes = struct.unpack_from('<%dI' % n_bones, d, hash_start)

    # Per-bone flags right after hashes
    flags_bones = b''
    flag_start = hash_start + 4 * n_bones
    if flag_start + n_bones <= len(d):
        flags_bones = d[flag_start:flag_start + n_bones]

    # JointRotations at section[4] — chunked bitstream
    rot_curves = {}
    n_animated = 0
    n_chunks = 0
    key_times = []

    if counts[4] and offs[4] and len(flags_bones) == n_bones:
        jr_bones = [(bi, (flags_bones[bi] & 0x0F) + 1)
                     for bi in range(n_bones)
                     if (flags_bones[bi] & 0x10)
                     and (flags_bones[bi] & 0x30) != 0x30]
        n_animated = len(jr_bones)
        n_animated = min(n_animated, counts[4])

        jr = aNi + offs[4]
        if jr + 4 <= len(d):
            table_size, = struct.unpack_from('<I', d, jr)
            if table_size < 4 or table_size > len(d) - jr - 4:
                n_chunks = 0
            else:
                n_chunks = table_size // 4 - 1

            table_end = jr + 4 + max(4, table_size)
            if n_chunks > 0 and table_end <= len(d):
                ends = struct.unpack_from('<%dI' % n_chunks, d, jr + 4)
                n_keys_total = n_chunks * 8
                key_times = list(range(n_keys_total))

                prev = table_size
                for chunk_i in range(min(n_chunks, len(ends))):
                    cstart = jr + prev
                    cend = jr + ends[chunk_i]
                    if cstart >= cend or cend > len(d):
                        break
                    r = _BitReader(d, cstart, cend)
                    first = chunk_i * 8
                    nframes = min(8, n_keys_total - first)
                    if nframes <= 0:
                        break
                    for bi, nbits in jr_bones:
                        quats = _decode_bone_block(r, nbits, nframes)
                        cur = rot_curves.setdefault(bi, [])
                        for f in range(nframes):
                            cur.append((key_times[first + f], quats[f]))
                    prev = ends[chunk_i]

    # JointConstantRotations at section[5]
    const_rots = {}
    if counts[2] and offs[5] and len(flags_bones) == n_bones:
        cr = aNi + offs[5]
        if cr + counts[2] * 6 <= len(d):
            ci = 0
            for bi in range(n_bones):
                if (flags_bones[bi] & 0x30) != 0x30:
                    continue
                if ci >= counts[2]:
                    break
                w0, w1, w2 = struct.unpack_from('<3H', d, cr + ci * 6)
                const_rots[bi] = _unpack_const_quat(w0, w1, w2)
                ci += 1

    last_frame = (n_chunks * 8 - 1) if n_chunks else 0

    return {
        'duration': duration,
        'last_frame': last_frame,
        'tick_rate': int(round(framerate)) or 30,
        'n_bones': n_bones,
        'counts': list(counts),
        'hashes': list(hashes),
        'flags': bytes(flags_bones),
        'key_times': key_times,
        'const_rots': const_rots,
        'rot_curves': rot_curves,
        'n_animated': n_animated,
    }
