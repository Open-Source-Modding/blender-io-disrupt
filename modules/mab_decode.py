"""mab_decode.py — full .mab JointRotations decoder.

Reads a .mab file, parses the wrapper + KeyTimes + JointRotations bitstream,
and emits per-bone, per-stored-keyframe quaternions. Optionally diffs against
a .anim.json oracle (produced by MacToFbx) for validation.

Usage:
    python mab_decode.py <input.mab>
    python mab_decode.py <input.mab> --oracle <anim.json>
    python mab_decode.py <input.mab> --oracle <anim.json> --bone Pelvis

JointRotations format (verified bit-exact via close-fast.mab fixture):
  - Section starts with uint32 table_size + (table_size/4 - 1) chunk-end offsets
  - Each chunk holds up to 8 stored keyframes of all dynamic-rotation bones
    packed contiguously bit-after-bit
  - Per bone: 6-bit cflags + optional sign bits + 3 stored components (each
    16-bit constant OR 16-bit base+slope + N-bit interpolants per frame) +
    smallest-three sqrt-reconstructed implicit component
  - N (interpolant bits) = (bonePathFlag & 0x0F) + 1 per bone
"""
import argparse, json, math, struct, sys, zlib

# Lookup table from ChunkReader.cpp.
MS_INTERP_SCALE = [
    0, 0, 0.33333334, 0.14285715, 0.06666667, 0.032258064,
    0.015873017, 0.0078740157, 0.0039215689, 0.0019569471,
    0.00097751711, 0.00048851978, 0.00024420026, 0.00012208521,
    0.000061038882, 0.000030518509, 0.000015259022,
]


class BitReader:
    """LSB-first bit reader matching ChunkReader's `num >> (bitPos & 7)` pattern."""

    def __init__(self, data):
        self.data = data
        self.bp = 0

    def read(self, n):
        bo, bi = self.bp >> 3, self.bp & 7
        num = 0
        for k in range(4):
            if bo + k < len(self.data):
                num |= self.data[bo + k] << (8 * k)
        v = (num >> bi) & ((1 << n) - 1)
        self.bp += n
        return v


def parse_wrapper(data):
    sig = data[32:35].decode("ascii")
    flags = data[35]
    anim_data_size, = struct.unpack_from("<I", data, 36)
    duration, fps = struct.unpack_from("<ff", data, 40)
    nb_bones, = struct.unpack_from("<H", data, 48)
    data_counts = struct.unpack_from("<11H", data, 50)
    offsets = struct.unpack_from("<12I", data, 72)
    p = 72 + 48 + 4
    last_frame, _zero = struct.unpack_from("<HH", data, p)
    p += 4
    bone_hashes = struct.unpack_from(f"<{nb_bones}I", data, p)
    p += nb_bones * 4
    bone_path_flags = list(data[p:p + nb_bones])
    return {
        "sig": sig, "flags": flags, "animDataSize": anim_data_size,
        "duration": duration, "fps": fps, "nbBones": nb_bones,
        "dataCounts": data_counts, "offsets": offsets,
        "lastFrame": last_frame,
        "boneHashes": bone_hashes, "bonePathFlags": bone_path_flags,
    }


def parse_keytimes(data, offsets):
    kt_start = offsets[0] + 0x10
    kt_size = offsets[1] - offsets[0]
    return list(struct.unpack_from(f"<{kt_size // 2}H", data, kt_start))


def decode_bone_block(r, n_bits, n_frames):
    """Decode one bone's chunk block. Returns dict with cflags/wInd/quats."""
    cflags = r.read(6)
    c_const = [(cflags >> c) & 1 for c in range(3)]
    b_sig = (cflags >> 3) & 1
    w_ind = (cflags >> 4) & 3
    sign_bits = r.read(n_frames) if b_sig else 0

    comp_vals = []
    for c in range(3):
        if c_const[c]:
            w = r.read(16)
            v = w * (1.0 / 32768.0) - 1.0
            comp_vals.append([v] * n_frames)
        else:
            w = r.read(16)
            base = (w & 0xFF) * (1.0 / 127.0) - 1.0
            slope = (w >> 8) * (1.0 / 127.5) * MS_INTERP_SCALE[n_bits]
            comp_vals.append([r.read(n_bits) * slope + base for _ in range(n_frames)])

    quats = []
    for f in range(n_frames):
        q = [0.0, 0.0, 0.0, 0.0]
        s = 0.0
        for c in range(3):
            target = c if c < w_ind else c + 1
            q[target] = comp_vals[c][f]
            s += q[target] ** 2
        implicit = math.sqrt(max(0.0, 1.0 - s))
        if sign_bits & (1 << f):
            implicit = -implicit
        q[w_ind] = implicit
        quats.append(q)
    return {"cflags": cflags, "wInd": w_ind, "signBits": sign_bits, "quats": quats}


def select_jr_bones(wrapper):
    """Return [(bone_idx, flag, N)] for bones contributing to the JR bitstream.

    A bone is in JR if bit 0x10 is set AND bits 0x30 are NOT both set
    (the both-bits case routes through JCRot instead, per GetJointRotations).
    """
    out = []
    for i, f in enumerate(wrapper["bonePathFlags"]):
        if (f & 0x10) and (f & 0x30) != 0x30:
            out.append((i, f, (f & 0x0F) + 1))
    return out


def decode_jrot(data, wrapper, key_times):
    """Decode every chunk of the JR section. Returns {bone_idx: {timeline_frame: block_info}}."""
    offsets = wrapper["offsets"]
    jr_start = offsets[6] + 0x10
    jr_end = offsets[7] + 0x10
    if jr_end - jr_start == 0:
        return {}

    table_size, = struct.unpack_from("<I", data, jr_start)
    n_chunks = table_size // 4 - 1
    chunk_ends = struct.unpack_from(f"<{n_chunks}I", data, jr_start + 4)

    jr_bones = select_jr_bones(wrapper)
    decoded = {idx: {} for idx, _, _ in jr_bones}

    prev_end = table_size
    n_keys_total = len(key_times)
    for chunk_i, chunk_end in enumerate(chunk_ends):
        chunk_bytes = data[jr_start + prev_end:jr_start + chunk_end]
        r = BitReader(chunk_bytes)

        first_key = chunk_i * 8
        last_key = min(first_key + 8, n_keys_total)
        n_frames = last_key - first_key

        for bone_idx, _flag, n_bits in jr_bones:
            info = decode_bone_block(r, n_bits, n_frames)
            for f, q in enumerate(info["quats"]):
                tf = key_times[first_key + f]
                decoded[bone_idx][tf] = {
                    "quat": q,
                    "cflags": info["cflags"],
                    "wInd": info["wInd"],
                    "chunk": chunk_i,
                }

        prev_end = chunk_end
    return decoded


def load_oracle(path):
    """Load .anim.json. Returns ({bone_name: [(t, [x,y,z,w])]}, fps)."""
    doc = json.load(open(path, "r"))
    bones = {}
    for bname, bdata in doc.get("bones", {}).items():
        rot = bdata.get("rotation", [])
        bones[bname] = [(k["t"], k["q"]) for k in rot]
    duration = doc.get("duration", 0.0)
    fps = (len(next(iter(bones.values()))) - 1) / duration if duration > 0 and bones else 30.0
    return bones, fps


def build_crc_map(oracle):
    """Map standard zlib CRC32 of each oracle bone name -> name. Used to label
    .mab boneHashes against the .anim.json's name table.
    """
    out = {}
    for name in oracle:
        out[zlib.crc32(name.encode("utf-8")) & 0xFFFFFFFF] = name
    return out


def find_oracle_quat(oracle_keys, timeline_frame, fps):
    """Return the oracle quat sampled at the timeline-frame's timestamp. The
    oracle is dense per-frame (e.g. 30fps); we just pick the entry whose
    timestamp is closest.
    """
    t = timeline_frame / fps
    return min(oracle_keys, key=lambda kv: abs(kv[0] - t))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("mab")
    ap.add_argument("--oracle", help=".anim.json from MacToFbx for ground-truth diff")
    ap.add_argument("--bone", help="restrict output to bones matching this name substring")
    args = ap.parse_args()

    data = open(args.mab, "rb").read()
    w = parse_wrapper(data)
    print(f"[{args.mab}] {len(data)} bytes")
    print(f"  sig={w['sig']} flags=0x{w['flags']:02X} dur={w['duration']:.3f}s fps={w['fps']:.0f}  "
          f"nbBones={w['nbBones']} lastFrame={w['lastFrame']}")
    dc = w["dataCounts"]
    print(f"  dataCounts: DispRot={dc[0]} DispTrans={dc[1]} "
          f"JCRot={dc[2]} JCTrans={dc[3]} JRot={dc[4]} JTrans={dc[5]}")

    key_times = parse_keytimes(data, w["offsets"])
    print(f"  KeyTimes ({len(key_times)}): {key_times}")

    oracle = None
    crc_to_name = {}
    oracle_fps = w["fps"]
    if args.oracle:
        oracle, oracle_fps = load_oracle(args.oracle)
        crc_to_name = build_crc_map(oracle)
        resolved = sum(1 for h in w["boneHashes"] if h in crc_to_name)
        print(f"  oracle: {len(oracle)} bones, {resolved}/{w['nbBones']} CRCs resolved (standard CRC32)")
        if resolved == 0:
            print("  WARN: no CRCs resolved — .mab uses a non-standard hash; bone names will show as '?'")

    decoded = decode_jrot(data, w, key_times)
    if not decoded:
        print("  no JointRotations data (purely-static or no-rotation fixture)")
        return

    print(f"\nJointRotations decoded ({len(decoded)} bones):")
    total_err = 0.0
    total_compared = 0

    for bone_idx in sorted(decoded):
        bone_hash = w["boneHashes"][bone_idx]
        bone_flag = w["bonePathFlags"][bone_idx]
        n_bits = (bone_flag & 0x0F) + 1
        name = crc_to_name.get(bone_hash, "?")

        if args.bone and args.bone.lower() not in name.lower():
            continue

        print(f"\nbone[{bone_idx}] CRC=0x{bone_hash:08X} ({name}) flag=0x{bone_flag:02X} N={n_bits}")
        for tf in sorted(decoded[bone_idx]):
            info = decoded[bone_idx][tf]
            q = info["quat"]
            print(f"  frame[{tf}]: chunk={info['chunk']} cflags=0x{info['cflags']:02X} wInd={info['wInd']}")
            print(f"    decoded=({q[0]:+.5f}, {q[1]:+.5f}, {q[2]:+.5f}, {q[3]:+.5f})")

            if oracle and name in oracle:
                _ot, oq = find_oracle_quat(oracle[name], tf, oracle_fps)
                err = sum(abs(q[k] - oq[k]) for k in range(4))
                mark = "+" if err < 0.02 else "?" if err < 0.1 else "X"
                print(f"    oracle =({oq[0]:+.5f}, {oq[1]:+.5f}, {oq[2]:+.5f}, {oq[3]:+.5f})  L1 err={err:.5f}  {mark}")
                total_err += err
                total_compared += 1

    if oracle and total_compared > 0:
        print(f"\nSummary: avg L1 error = {total_err / total_compared:.5f} over {total_compared} compared frames")


if __name__ == "__main__":
    main()
