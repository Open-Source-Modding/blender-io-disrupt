"""Watch Dogs XBT (compiled texture) ↔ DDS converter.

The Disrupt engine stores textures as .xbt files: a DDS with a variable-length
wrapper header containing texture metadata, string table, and checksums.

Format reference: reference/disrupt/xbt-format.md (shared cross-game spec).

Usage:
    xbt_to_dds('input.xbt', 'output.dds')
    dds_to_xbt('input.dds', 'output.xbt', tex_path='graphics\\_textures\\tex.dds')

    # Parse header for inspection
    header = parse_xbt_header('input.xbt')
    print(header['quality_class'], header['format_code'], header['strings'])
"""

import os
import struct

_XBT_MAGIC = b'TBX\x00'
_DDS_MAGIC = b'DDS '


# ── Header parsing ──────────────────────────────────────────────────────────

def parse_xbt_header(path_or_data):
    """Parse an XBT header into a dict.

    Accepts a file path or raw bytes.  Returns a dict with all header fields
    plus the parsed string table.

    Layout (from xbt-format.md):
        +0x00  TBX\\0 magic (4 bytes)
        +0x04  Version u16 (0x0092 = CTexCompiler)
        +0x06  Padding u16
        +0x08  Header size u32 (total XBT header before DDS; 0x34 if no strings)
        +0x0C  Reserved u32 (0)
        +0x10  Format/density code u32
        +0x14  Bytes-per-pixel/block code u32
        +0x18  Quality bytes u32 ([byte0≈01][byte1=quality class][byte2≈01][byte3=0xFF])
        +0x1C  Source file CRC32 (CSourceCrcEvaluator Hash)
        +0x20  Texture profile ID (ProfileId)
        +0x24  Texture profile CRC32 (ProfileCrc)
        +0x28  Source .meta CRC (CSourceMetaCrcEvaluator Hash, usually 0)
        +0x2C  Constant u32 (0x7F7F7F7F)
        +0x30  String count u8, String table version u8, Reserved u16
        +0x32  String table (variable length, null-terminated strings)
               [DDS starts at header_size]
    """
    if isinstance(path_or_data, (str, os.PathLike)):
        with open(path_or_data, 'rb') as f:
            data = f.read()
    else:
        data = path_or_data

    if len(data) < 0x34:
        raise ValueError(f"XBT too short ({len(data)} bytes, minimum 0x34)")

    if data[:4] != _XBT_MAGIC:
        raise ValueError(f"not an XBT file (magic={data[:4]!r})")

    version = struct.unpack_from('<H', data, 0x04)[0]
    header_size = struct.unpack_from('<I', data, 0x08)[0]
    format_code = struct.unpack_from('<I', data, 0x10)[0]
    bpp_code = struct.unpack_from('<I', data, 0x14)[0]

    # Quality bytes: 4 bytes at +0x18, byte1 = quality/mip class
    q_raw = struct.unpack_from('<I', data, 0x18)[0]
    q_bytes = struct.pack('<I', q_raw)
    quality_class = q_bytes[1]  # byte1 = quality/mip level class

    source_crc = struct.unpack_from('<I', data, 0x1C)[0]
    profile_id = struct.unpack_from('<I', data, 0x20)[0]
    profile_crc = struct.unpack_from('<I', data, 0x24)[0]
    meta_crc = struct.unpack_from('<I', data, 0x28)[0]

    # String table at +0x30..+0x31 header, +0x32 onward is string data
    # Layout: string_count(u8), string_table_version(u8)
    # Then null-terminated strings; first has no prefix, subsequent have a
    # 1-byte type prefix (0x02 = filepath, 0x03 = variant path).
    string_count = data[0x30] if len(data) > 0x30 else 0
    strings = []
    if string_count > 0 and len(data) > 0x32:
        pos = 0x32  # right after the 2-byte string table header
        for i in range(string_count):
            if pos >= len(data):
                break
            # Skip 1-byte type prefix for strings after the first
            if i > 0 and pos < len(data) and data[pos:pos+1] in (b'\x02', b'\x03'):
                pos += 1
            end = data.find(b'\x00', pos)
            if end < 0:
                end = len(data)
            s = data[pos:end].decode('latin-1')
            if s:
                strings.append(s)
            pos = end + 1

    return {
        'version': version,
        'header_size': header_size,
        'format_code': format_code,
        'bpp_code': bpp_code,
        'quality_bytes_raw': q_raw,
        'quality_class': quality_class,
        'source_crc': source_crc,
        'profile_id': profile_id,
        'profile_crc': profile_crc,
        'meta_crc': meta_crc,
        'string_count': string_count,
        'strings': strings,
    }


# ── XBT → DDS extraction ───────────────────────────────────────────────────

def xbt_to_dds(xbt_path, dds_path=None):
    """Extract the embedded DDS from an XBT file.

    If dds_path is None, derives it from xbt_path (replaces .xbt with .dds).

    Also writes a .xbt.header file for later DDS→XBT reconstruction.

    Returns (dds_path, header_dict).
    """
    if dds_path is None:
        dds_path = os.path.splitext(xbt_path)[0] + '.dds'

    with open(xbt_path, 'rb') as f:
        data = f.read()

    header = parse_xbt_header(data)

    # Use the header_size field for DDS offset (authoritative, not a scan)
    dds_start = header['header_size']
    if dds_start >= len(data):
        # Fallback: scan for DDS magic (some files have padding)
        dds_start = data.find(_DDS_MAGIC)
        if dds_start < 0:
            raise ValueError("no DDS signature found in XBT")

    dds_data = data[dds_start:]

    with open(dds_path, 'wb') as f:
        f.write(dds_data)

    # Save the XBT header for DDS→XBT reconstruction
    header_path = xbt_path + '.header'
    with open(header_path, 'wb') as f:
        f.write(data[:dds_start])

    return dds_path, header


# ── DDS → XBT reconstruction ───────────────────────────────────────────────

def dds_to_xbt(dds_path, xbt_path=None, header_path=None, tex_path=''):
    """Reconstruct an XBT from a DDS and its header.

    If xbt_path is None, derives it from dds_path.
    If header_path is None, looks for dds_path + '.header'.
    """
    if xbt_path is None:
        xbt_path = os.path.splitext(dds_path)[0] + '.xbt'

    if header_path is None:
        header_path = dds_path + '.header'

    if not os.path.exists(header_path):
        raise FileNotFoundError(
            f"Header file required for DDS→XBT: {header_path}. "
            "Convert the original XBT first to generate the header.")

    with open(header_path, 'rb') as f:
        header = f.read()

    with open(dds_path, 'rb') as f:
        dds = f.read()

    # Verify DDS signature
    if dds[:4] != _DDS_MAGIC:
        raise ValueError("not a valid DDS file (no DDS signature)")

    with open(xbt_path, 'wb') as f:
        f.write(header)
        f.write(dds)

    return xbt_path


# ── Quality class descriptions ──────────────────────────────────────────────

QUALITY_CLASSES = {
    0x01: 'high (self-contained, single mip)',
    0x02: 'mip level 2',
    0x03: 'mip level 3',
    0x04: 'mip level 4',
    0x08: 'self-contained (no _high variant)',
    0x09: 'regular with _high reference (variant A)',
    0x0A: 'regular with _high reference (variant B)',
    0x0B: 'regular with _high reference (variant C)',
    0x0C: 'regular with _high reference (variant D)',
}


def describe_quality_class(qc):
    """Return a human-readable description of a quality class byte."""
    return QUALITY_CLASSES.get(qc, f'unknown (0x{qc:02X})')
