"""Watch Dogs 1 / 2 — .material.bin reader / writer.

Binary material format for the Disrupt engine (Watch Dogs 1, 2, Legion).

Format:
  magic     u32 = 0x004D4154  ("TAM\\0" little-endian)
  version   u32 = 7
  header    60 bytes (reserved + addressing block)
  name      u32 len + UTF-8 string (padded to 4)
  shader    u32 len + UTF-8 string (padded to 4)
  init      6 × u32 (cmd_count in upper 16 bits of last u32)
  cmds      N × Command (tightly packed, no trailing padding)

Command layout:
  u8  type     1=float, 2=vec2, 3=vec3, 4=vec4,
               5=uint, 6=bool, 7=enum, 8=string
  u8  sub_type
  u8  padding[]  align type+sub to next 4-byte boundary
  u32 name_hash  standard zlib CRC32 of parameter name
  u8  data[]     type-specific value data

Data sizes per type:
  1 → f32 (4)       2 → f32,f32 (8)     3 → f32×3 (12)
  4 → f32×4 (16)    5 → u32 (4)         6 → u8 (1)
  7 → u32 (4)       8 → u32 str_len + str_data
"""
from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass, field
from typing import Any


_MAGIC   = 0x004D4154
_VERSION = 7
_HEADER_SIZE = 0x44
_INIT_COUNT   = 6

# ---------------------------------------------------------------------------
# Type codes
# ---------------------------------------------------------------------------

PARAM_FLOAT  = 1
PARAM_VEC2   = 2
PARAM_VEC3   = 3
PARAM_VEC4   = 4
PARAM_UINT   = 5
PARAM_BOOL   = 6
PARAM_ENUM   = 7
PARAM_STRING = 8

_DATA_SIZE: dict[int, int | None] = {
    PARAM_FLOAT:  4,
    PARAM_VEC2:   8,
    PARAM_VEC3:  12,
    PARAM_VEC4:  16,
    PARAM_UINT:   4,
    PARAM_BOOL:   1,
    PARAM_ENUM:   4,
    PARAM_STRING: None,
}

# ---------------------------------------------------------------------------
# Name lookup table (loaded from materialNames.txt)
# ---------------------------------------------------------------------------

_CRC_TO_NAME: dict[int, str] = {}


def _load_name_table(path: str | None = None) -> dict[int, str]:
    if path is None:
        path = os.path.join(os.path.dirname(__file__), "materialNames.txt")
    table: dict[int, str] = {}
    if not os.path.isfile(path):
        return table
    with open(path) as f:
        for line in f:
            name = line.strip()
            if name:
                table[zlib.crc32(name.encode()) & 0xFFFFFFFF] = name
    return table


def _init_name_table():
    global _CRC_TO_NAME
    if not _CRC_TO_NAME:
        _CRC_TO_NAME = _load_name_table()


def resolve_name(name_hash: int) -> str:
    """Look up a CRC32 hash in the material names table."""
    _init_name_table()
    return _CRC_TO_NAME.get(name_hash, "")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Command:
    """A single material parameter / command."""
    type: int
    sub_type: int = 0
    name: str = ""
    name_hash: int = 0
    value: Any = None

    def to_value(self) -> Any:
        if self.type == PARAM_FLOAT:
            return float(self.value) if isinstance(self.value, (int, float)) else 0.0
        if self.type == PARAM_VEC2:
            v = (self.value or []) if isinstance(self.value, (list, tuple)) else []
            return [float(x) for x in v[:2]] + [0.0] * (2 - len(v))
        if self.type == PARAM_VEC3:
            v = (self.value or []) if isinstance(self.value, (list, tuple)) else []
            return [float(x) for x in v[:3]] + [0.0] * (3 - len(v))
        if self.type == PARAM_VEC4:
            v = (self.value or []) if isinstance(self.value, (list, tuple)) else []
            return [float(x) for x in v[:4]] + [0.0] * (4 - len(v))
        if self.type == PARAM_UINT:
            return int(self.value) if self.value is not None else 0
        if self.type == PARAM_BOOL:
            return bool(self.value) if self.value is not None else False
        if self.type == PARAM_ENUM:
            return int(self.value) if self.value is not None else 0
        if self.type == PARAM_STRING:
            return str(self.value) if self.value is not None else ""
        return self.value

    def is_texture(self) -> bool:
        return self.type == PARAM_STRING and isinstance(self.value, str) and (".xbt" in self.value or ".dds" in self.value)


@dataclass
class MaterialBin:
    """Represents a complete .material.bin file."""
    name: str = ""
    shader_name: str = ""
    header_data: bytes = b""
    init_settings: list[int] = field(default_factory=lambda: [0] * _INIT_COUNT)
    commands: list[Command] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    @classmethod
    def read(cls, buf: bytes) -> "MaterialBin":
        _init_name_table()
        self = cls()
        pos = 0

        magic, version = struct.unpack_from("<II", buf, pos)
        if magic != _MAGIC:
            raise ValueError(f"Bad magic: 0x{magic:08X}, expected 0x{_MAGIC:08X}")
        if version != _VERSION:
            raise ValueError(f"Bad version: {version}, expected {_VERSION}")
        self.header_data = buf[: _HEADER_SIZE]
        pos = _HEADER_SIZE

        name_len = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        self.name = buf[pos: pos + name_len].decode("utf-8", errors="replace")
        pos += name_len
        pos = _align4(pos)

        shader_len = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        self.shader_name = buf[pos: pos + shader_len].decode("utf-8", errors="replace")
        pos += shader_len
        pos = _align4(pos)

        init_vals = list(struct.unpack_from(f"<{_INIT_COUNT}I", buf, pos))
        self.init_settings = init_vals
        pos += _INIT_COUNT * 4

        cmd_count = (init_vals[-1] >> 16) & 0xFFFF

        for _ in range(cmd_count):
            if pos + 4 > len(buf):
                break
            cmd_type = buf[pos]
            sub_type = buf[pos + 1]
            pos += 2
            pos = _align4(pos)
            name_hash = struct.unpack_from("<I", buf, pos)[0]
            pos += 4

            cmd = Command(type=cmd_type, sub_type=sub_type, name_hash=name_hash)
            cmd.name = resolve_name(name_hash)

            data_size = _DATA_SIZE.get(cmd_type)

            if data_size == 4:
                if cmd_type == PARAM_FLOAT:
                    cmd.value = struct.unpack_from("<f", buf, pos)[0]
                elif cmd_type == PARAM_UINT:
                    cmd.value = struct.unpack_from("<I", buf, pos)[0]
                elif cmd_type == PARAM_ENUM:
                    cmd.value = struct.unpack_from("<I", buf, pos)[0]
                pos += 4

            elif data_size == 1:  # bool
                cmd.value = bool(buf[pos])
                pos += 1

            elif data_size == 8:  # vec2
                cmd.value = list(struct.unpack_from("<2f", buf, pos))
                pos += 8

            elif data_size == 12:  # vec3
                cmd.value = list(struct.unpack_from("<3f", buf, pos))
                pos += 12

            elif data_size == 16:  # vec4
                cmd.value = list(struct.unpack_from("<4f", buf, pos))
                pos += 16

            elif cmd_type == PARAM_STRING:
                str_len = struct.unpack_from("<I", buf, pos)[0]
                pos += 4
                cmd.value = buf[pos: pos + str_len].decode("utf-8", errors="replace")
                pos += str_len

            else:
                cmd.value = name_hash
                pos += 4

            self.commands.append(cmd)

        return self

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def write(self) -> bytes:
        chunks: list[bytes] = []

        if len(self.header_data) == _HEADER_SIZE:
            chunks.append(self.header_data)
        else:
            hdr = struct.pack("<II", _MAGIC, _VERSION)
            hdr += b"\x00" * (_HEADER_SIZE - len(hdr))
            chunks.append(hdr)

        name_bytes = self.name.encode("utf-8")
        chunks.append(struct.pack("<I", len(name_bytes)))
        chunks.append(name_bytes)
        chunks.append(_pad_to4(name_bytes))

        shader_bytes = self.shader_name.encode("utf-8")
        chunks.append(struct.pack("<I", len(shader_bytes)))
        chunks.append(shader_bytes)
        chunks.append(_pad_to4(shader_bytes))

        init = self.init_settings[:]
        init += [0] * (_INIT_COUNT - len(init))
        init[-1] = (init[-1] & 0xFFFF) | (len(self.commands) << 16)
        chunks.append(struct.pack(f"<{_INIT_COUNT}I", *init))

        # Track the stream position so hash alignment is file-position-relative
        stream_pos = sum(len(c) for c in chunks)

        for cmd in self.commands:
            body = bytearray()
            body.append(cmd.type & 0xFF)
            body.append(cmd.sub_type & 0xFF)

            # Align hash to next 4-byte boundary from current stream position
            hash_file_pos = stream_pos + len(body)
            while hash_file_pos % 4 != 0:
                body.append(0)
                hash_file_pos += 1

            name_hash = cmd.name_hash
            if not name_hash and cmd.name:
                name_hash = zlib.crc32(cmd.name.encode("utf-8")) & 0xFFFFFFFF

            data_size = _DATA_SIZE.get(cmd.type)

            if data_size == 4:
                if cmd.type == PARAM_FLOAT:
                    val = float(cmd.value) if cmd.value is not None else 0.0
                    body += struct.pack("<If", name_hash, val)
                elif cmd.type == PARAM_UINT:
                    val = int(cmd.value) if cmd.value is not None else 0
                    body += struct.pack("<II", name_hash, val)
                elif cmd.type == PARAM_ENUM:
                    val = int(cmd.value) if cmd.value is not None else 0
                    body += struct.pack("<II", name_hash, val)

            elif data_size == 1:  # bool
                val = 1 if cmd.value else 0
                body += struct.pack("<IB", name_hash, val)

            elif data_size == 8:
                v = [float(x) for x in (cmd.value or [0, 0])[:2]]
                body += struct.pack("<I2f", name_hash, *v)

            elif data_size == 12:
                v = [float(x) for x in (cmd.value or [0, 0, 0])[:3]]
                body += struct.pack("<I3f", name_hash, *v)

            elif data_size == 16:
                v = [float(x) for x in (cmd.value or [0, 0, 0, 0])[:4]]
                body += struct.pack("<I4f", name_hash, *v)

            elif cmd.type == PARAM_STRING:
                str_val = str(cmd.value) if cmd.value is not None else ""
                body += struct.pack("<II", name_hash, len(str_val))
                body += str_val.encode("utf-8")

            else:
                body += struct.pack("<I4x", name_hash)

            chunks.append(bytes(body))
            stream_pos += len(body)

        return b"".join(chunks)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def get_command(self, name: str) -> Command | None:
        for cmd in self.commands:
            if cmd.name == name:
                return cmd
        return None

    def get_textures(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for cmd in self.commands:
            if cmd.is_texture() and cmd.name:
                result[cmd.name] = str(cmd.value)
        return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _align4(offset: int) -> int:
    return (offset + 3) & ~3


def _align4_ba(ba: bytearray):
    while len(ba) % 4 != 0:
        ba.append(0)


def _pad_to4(data: bytes) -> bytes:
    """Return padding bytes so that len(data) + len(padding) is a multiple of 4."""
    r = len(data) % 4
    if r == 0:
        return b""
    return b"\x00" * (4 - r)
