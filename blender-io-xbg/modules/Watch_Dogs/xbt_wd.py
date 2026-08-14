"""Watch Dogs XBT (compiled texture) ↔ DDS converter.

The Disrupt engine stores textures as .xbt files: a DDS with a 0x34-byte
wrapper header containing the texture metadata, path, and a checksum.

Usage:
    xbt_to_dds('input.xbt', 'output.dds')
    dds_to_xbt('input.dds', 'output.xbt', tex_path='graphics\\_textures\\tex.dds')
"""

import os
import struct

_XBT_HEADER_SIZE = 0x34  # 52 bytes
_XBT_MAGIC = b'TBX\x00'
_DDS_MAGIC = b'DDS '


def _parse_xbt_header(data):
    """Parse XBT header and return dict with format info."""
    if data[:4] != _XBT_MAGIC:
        raise ValueError(f"not an XBT file (magic={data[:4]!r})")

    return {
        'version': struct.unpack_from('<H', data, 4)[0],
        'width': struct.unpack_from('<I', data, 0x14)[0],
        'height': struct.unpack_from('<I', data, 0x18)[0],
        'mips': struct.unpack_from('<I', data, 0x1C)[0],
        'format': struct.unpack_from('<I', data, 0x10)[0],
        'flags': struct.unpack_from('<I', data, 0xC)[0],
    }


def xbt_to_dds(xbt_path, dds_path=None):
    """Extract the embedded DDS from an XBT file.

    If dds_path is None, derives it from xbt_path (replaces .xbt with .dds).

    Also writes a .xbt.header file for later DDS→XBT reconstruction.
    """
    if dds_path is None:
        dds_path = os.path.splitext(xbt_path)[0] + '.dds'

    with open(xbt_path, 'rb') as f:
        data = f.read()

    header = _parse_xbt_header(data)

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
