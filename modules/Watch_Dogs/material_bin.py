#!/usr/bin/env python3
"""material_bin.py — Disrupt engine .material.bin reader/writer.

Standalone module for the ES collaboration.
Supports Watch Dogs 1 (version 7), WDL/Leak (version 15).

Usage:
    from material_bin import MaterialBin

    mat = MaterialBin.from_file("path/to/file.material.bin")
    print(mat.name, mat.shader, len(mat.params))

    # Modify a parameter
    mat.set_param("Opacity", 0.5)

    # Write back
    mat.write("output.material.bin")
"""

from __future__ import annotations
import struct, zlib, os
from dataclasses import dataclass, field
from typing import Any

# ── Constants ──────────────────────────────────────────────────────────────
MAGIC = 0x004D4154  # "TAM\0"
HEADER_SIZE = 68     # 17 × u32

# Type codes (same across versions)
TYPE_U32    = 1
TYPE_VEC2   = 2
TYPE_VEC3   = 3
TYPE_VEC4   = 4
TYPE_I32    = 5
TYPE_BOOL   = 6
TYPE_ENUM   = 7  # u32, stored as CRC32 of enum string
TYPE_STR8   = 8
TYPE_STR9   = 9
TYPE_STR10  = 10
TYPE_U32_2  = 11
TYPE_FLOAT  = TYPE_U32      # alias: floats stored as raw u32 bits

TYPE_NAMES = {
    1:'u32', 2:'vec2', 3:'vec3', 4:'vec4', 5:'i32', 6:'bool',
    7:'u32', 8:'str', 9:'str', 10:'str', 11:'u32'
}

# ── Name dictionary ────────────────────────────────────────────────────────
_CRC_TO_NAME: dict[int, str] = {}

def _load_names(path: str | None = None):
    global _CRC_TO_NAME
    if _CRC_TO_NAME:
        return
    if path is None:
        # Try companion materialNames.txt next to this file
        path = os.path.join(os.path.dirname(__file__), "materialNames.txt")
    if not os.path.isfile(path):
        return
    with open(path) as f:
        for line in f:
            name = line.strip()
            if name:
                _CRC_TO_NAME[zlib.crc32(name.encode()) & 0xFFFFFFFF] = name

def crc32_name(name: str) -> int:
    return zlib.crc32(name.encode()) & 0xFFFFFFFF

def resolve_name(hash_val: int) -> str:
    _load_names()
    return _CRC_TO_NAME.get(hash_val, "")

# ── Data classes ───────────────────────────────────────────────────────────
@dataclass
class Param:
    """A single material parameter."""
    type: int
    name: str
    name_hash: int
    value: Any = None

    def as_float(self) -> float:
        if self.type in (TYPE_U32, TYPE_VEC2, TYPE_VEC3, TYPE_VEC4, TYPE_ENUM, TYPE_U32_2):
            v = self.value[0] if isinstance(self.value, list) else self.value
            return struct.unpack('<f', struct.pack('<I', v))[0]
        return float(self.value) if self.value is not None else 0.0

    def as_floats(self) -> list[float]:
        if isinstance(self.value, list):
            return [struct.unpack('<f', struct.pack('<I', v))[0]
                    if isinstance(v, int) else float(v) for v in self.value]
        return [self.as_float()]

    def is_texture(self) -> bool:
        return self.type in (TYPE_STR8, TYPE_STR9, TYPE_STR10) and isinstance(self.value, str)


@dataclass
class MaterialBin:
    """A complete .material.bin file."""
    version: int = 15
    header: bytes = b""
    name: str = ""
    shader: str = ""
    init_settings: bytes = b""  # raw bytes between shader and params
    unk74: int = 0
    unk75: int = 0
    params: list[Param] = field(default_factory=list)
    gradient: int = 0
    gradient_data: Any = None
    eof: int = 0
    trailing: bytes = b""  # zero padding after EOF

    @classmethod
    def from_bytes(cls, buf: bytes) -> MaterialBin:
        """Decode a .material.bin from raw bytes."""
        _load_names()
        mat = cls()
        off = 0

        # Header
        magic, version = struct.unpack_from('<II', buf, 0)
        if magic != MAGIC:
            raise ValueError(f"Bad magic: 0x{magic:08X}")
        mat.version = version
        mat.header = buf[:HEADER_SIZE]
        off = HEADER_SIZE

        # Name
        name_size = struct.unpack_from('<I', buf, off)[0]; off += 4
        mat.name = buf[off:off+name_size].decode('utf-8', 'replace'); off += name_size
        off += (4 - name_size % 4) % 4

        # Shader
        sh_size = struct.unpack_from('<I', buf, off)[0]; off += 4
        mat.shader = buf[off:off+sh_size].decode('utf-8', 'replace'); off += sh_size
        mod = (4 - sh_size % 4) % 4
        orig_mod = 0
        if mod >= 2:
            orig_mod = mod
            mod -= 2
        off += mod

        # InitSettings
        init_start = off
        unk0 = struct.unpack_from('<H', buf, off)[0]; off += 2
        if orig_mod >= 2: off += 2
        unk2, unk3 = buf[off], buf[off+1]; off += 2
        unk4 = struct.unpack_from('<I', buf, off)[0]; off += 4
        unk5, unk6, unk7 = struct.unpack_from('<iii', buf, off); off += 12
        mat.init_settings = buf[init_start:off]

        # Parameters
        mat.unk74, mat.unk75 = buf[off], buf[off+1]; off += 2
        pcount = struct.unpack_from('<H', buf, off)[0]; off += 2

        for _ in range(pcount):
            pad = 4 - (off % 4) - 1
            type_b = buf[off]; off += 1
            if off % 4 == 0:
                off += 4
            off += pad

            name_hash = None
            if type_b - 1 <= 10:
                name_hash = struct.unpack_from('<I', buf, off)[0]; off += 4

            pname = resolve_name(name_hash) if name_hash else f'?0x{name_hash:08X}' if name_hash else '?'

            # Values
            vals = None
            if type_b == TYPE_U32:
                vals = [struct.unpack_from('<I', buf, off)[0]]; off += 4
            elif type_b == TYPE_VEC2:
                vals = list(struct.unpack_from('<2I', buf, off)); off += 8
            elif type_b == TYPE_VEC3:
                vals = list(struct.unpack_from('<3I', buf, off)); off += 12
            elif type_b == TYPE_VEC4:
                vals = list(struct.unpack_from('<4I', buf, off)); off += 16
            elif type_b == TYPE_I32:
                vals = [struct.unpack_from('<i', buf, off)[0]]; off += 4
            elif type_b == TYPE_BOOL:
                vals = [buf[off]]; off += 1
            elif type_b == TYPE_ENUM:
                vals = [struct.unpack_from('<I', buf, off)[0]]; off += 4
            elif type_b in (TYPE_STR8, TYPE_STR9, TYPE_STR10):
                sz = struct.unpack_from('<I', buf, off)[0]; off += 4
                vals = [buf[off:off+sz].decode('utf-8', 'replace')]; off += sz
            elif type_b == TYPE_U32_2:
                vals = [struct.unpack_from('<I', buf, off)[0]]; off += 4

            mat.params.append(Param(type=type_b, name=pname, name_hash=name_hash or 0, value=vals))

        # Gradient
        while off % 4: off += 1
        mat.gradient = struct.unpack_from('<I', buf, off)[0]; off += 4
        if mat.gradient == 1:
            grad_vec = struct.unpack_from('<i', buf, off)[0]; off += 4
            vecs = [struct.unpack_from('<4I', buf, off+i*16) for i in range(grad_vec)]
            off += grad_vec * 16
            grad_id = struct.unpack_from('<I', buf, off)[0]; off += 4
            unk1 = struct.unpack_from('<I', buf, off)[0]; off += 4
            unk2 = buf[off]; off += 1
            mat.gradient_data = (grad_vec, vecs, grad_id, unk1, unk2)

        # EOF
        if off + 4 <= len(buf):
            mat.eof = struct.unpack_from('<I', buf, off)[0]; off += 4

        mat.trailing = buf[off:]
        return mat

    @classmethod
    def from_file(cls, path: str) -> MaterialBin:
        with open(path, 'rb') as f:
            return cls.from_bytes(f.read())

    # ── Query ──────────────────────────────────────────────────────────
    def get_param(self, name: str) -> Param | None:
        for p in self.params:
            if p.name == name:
                return p
        return None

    def set_param(self, name: str, value: Any):
        """Set a parameter value by name. Adds it if not found."""
        for p in self.params:
            if p.name == name:
                p.value = value if isinstance(value, list) else [value]
                return
        # Add new param
        h = crc32_name(name)
        ptype = TYPE_FLOAT if isinstance(value, float) else TYPE_U32
        self.params.append(Param(type=ptype, name=name, name_hash=h, value=[value]))

    def get_textures(self) -> dict[str, str]:
        return {p.name: p.value[0] for p in self.params if p.is_texture()}

    # ── Dict-like interface (compatibility with material_editor_wd) ──────
    def _param_to_value(self, p: Param):
        """Extract a scalar-friendly value from a Param for dict-like access."""
        if p.is_texture():
            return p.value[0] if p.value else ''
        if p.type in (TYPE_BOOL,):
            return bool(p.value[0]) if p.value else False
        if p.type == TYPE_I32:
            return p.value[0] if p.value else 0
        if p.type in (TYPE_U32, TYPE_VEC2, TYPE_VEC3, TYPE_VEC4, TYPE_ENUM, TYPE_U32_2):
            if p.value and isinstance(p.value[0], float):
                return p.value[0]
            return p.as_float()
        return p.value[0] if p.value else ''

    def __contains__(self, key):
        if key in ('shader', 'name'):
            return True
        return any(p.name == key for p in self.params)

    def __getitem__(self, key):
        if key == 'shader':
            return self.shader
        if key == 'name':
            return self.name
        p = self.get_param(key)
        if p is None:
            raise KeyError(key)
        return self._param_to_value(p)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key, *args):
        """Pop a value by key.  Only removes params; shader/name are read-only."""
        if key == 'shader':
            return self.shader
        if key == 'name':
            return self.name
        for i, p in enumerate(self.params):
            if p.name == key:
                val = self._param_to_value(p)
                self.params.pop(i)
                return val
        if args:
            return args[0]
        raise KeyError(key)

    def items(self):
        """Yield (key, value) pairs: shader, name, then all params."""
        yield 'shader', self.shader
        yield 'name', self.name
        for p in self.params:
            yield p.name, self._param_to_value(p)

    def keys(self):
        yield 'shader'
        yield 'name'
        for p in self.params:
            yield p.name

    def values(self):
        yield self.shader
        yield self.name
        for p in self.params:
            yield self._param_to_value(p)

    def __iter__(self):
        return self.keys()

    def summary(self) -> str:
        lines = [f"material: {self.name}", f"shader: {self.shader}",
                 f"version: {self.version}", f"params: {len(self.params)}",
                 f"gradient: {self.gradient}"]
        for p in self.params:
            v = p.value[0] if p.value else None
            if p.type in (TYPE_U32, TYPE_VEC2, TYPE_VEC3, TYPE_VEC4, TYPE_ENUM):
                fv = p.as_float()
                lines.append(f"  {p.name:40s} type={TYPE_NAMES.get(p.type,'?'):5s} hash=0x{p.name_hash:08X} float={fv:.6f} raw={p.value}")
            elif p.type in (TYPE_STR8, TYPE_STR9, TYPE_STR10):
                lines.append(f"  {p.name:40s} type=str     hash=0x{p.name_hash:08X} val={v}")
            elif p.type == TYPE_BOOL:
                lines.append(f"  {p.name:40s} type=bool    hash=0x{p.name_hash:08X} val={v}")
            elif p.type == TYPE_I32:
                lines.append(f"  {p.name:40s} type=i32     hash=0x{p.name_hash:08X} val={v}")
        return '\n'.join(lines)

    # ── Writing ────────────────────────────────────────────────────────
    def write(self, path: str):
        """Write the material back to a .material.bin file."""
        with open(path, 'wb') as f:
            f.write(self.to_bytes())

    def to_bytes(self) -> bytes:
        """Serialize to bytes."""
        chunks = []

        # Header (preserve original)
        if len(self.header) == HEADER_SIZE:
            chunks.append(self.header)
        else:
            hdr = struct.pack('<II', MAGIC, self.version)
            hdr += b'\x00' * (HEADER_SIZE - len(hdr))
            chunks.append(hdr)

        # Name
        name_bytes = self.name.encode('utf-8')
        chunks.append(struct.pack('<I', len(name_bytes)))
        chunks.append(name_bytes)
        r = len(name_bytes) % 4
        if r: chunks.append(b'\x00' * (4 - r))

        # Shader — pad must match reader: if mod>=2, reduce by 2 (those bytes are InitSettings)
        sh_bytes = self.shader.encode('utf-8')
        chunks.append(struct.pack('<I', len(sh_bytes)))
        chunks.append(sh_bytes)
        mod = (4 - len(sh_bytes) % 4) % 4
        if mod >= 2:
            mod -= 2
        if mod:
            chunks.append(b'\x00' * mod)

        # InitSettings (raw preserved)
        chunks.append(self.init_settings)

        # Parameters header
        chunks.append(bytes([self.unk74, self.unk75]))
        chunks.append(struct.pack('<H', len(self.params)))

        stream_pos = sum(len(c) for c in chunks)

        for p in self.params:
            body = bytearray()

            # Pad: computed before type byte (matches reader's `pad = 4 - (off % 4) - 1`)
            pad = 4 - (stream_pos % 4) - 1

            # Type byte
            body.append(p.type & 0xFF)

            # Align skip (after type, if type pushed offset to 4-byte boundary)
            if (stream_pos + 1) % 4 == 0:
                body.extend(b'\x00' * 4)

            # Pad bytes
            body.extend(b'\x00' * pad)

            # Name hash
            body.extend(struct.pack('<I', p.name_hash))

            # Values
            vals = p.value if isinstance(p.value, list) else [p.value]
            if p.type in (TYPE_U32, TYPE_ENUM, TYPE_U32_2):
                body.extend(struct.pack('<I', vals[0] if vals else 0))
            elif p.type == TYPE_VEC2:
                body.extend(struct.pack('<2I', *(vals + [0, 0])[:2]))
            elif p.type == TYPE_VEC3:
                body.extend(struct.pack('<3I', *(vals + [0, 0, 0])[:3]))
            elif p.type == TYPE_VEC4:
                body.extend(struct.pack('<4I', *(vals + [0, 0, 0, 0])[:4]))
            elif p.type == TYPE_I32:
                body.extend(struct.pack('<i', vals[0] if vals else 0))
            elif p.type == TYPE_BOOL:
                body.append(1 if vals and vals[0] else 0)
            elif p.type in (TYPE_STR8, TYPE_STR9, TYPE_STR10):
                s = str(vals[0]) if vals else ''
                body.extend(struct.pack('<I', len(s)))
                body.extend(s.encode('utf-8'))
            else:
                body.extend(struct.pack('<I', vals[0] if vals else 0))

            chunks.append(bytes(body))
            stream_pos += len(body)

        # Gradient
        while stream_pos % 4:
            chunks.append(b'\x00')
            stream_pos += 1
        chunks.append(struct.pack('<I', self.gradient))
        stream_pos += 4
        if self.gradient == 1 and self.gradient_data:
            grad_vec, vecs, grad_id, unk1, unk2 = self.gradient_data
            chunks.append(struct.pack('<i', grad_vec))
            for v in vecs:
                chunks.append(struct.pack('<4I', *v))
            chunks.extend([struct.pack('<I', grad_id), struct.pack('<I', unk1), bytes([unk2])])

        # EOF + trailing
        chunks.append(struct.pack('<I', self.eof))
        chunks.append(self.trailing)

        return b''.join(chunks)


# ── Legacy compatibility shims ─────────────────────────────────────────────
def read_material_bin(path: str) -> MaterialBin:
    return MaterialBin.from_file(path)

def write_material_bin(path: str, mat: MaterialBin):
    mat.write(path)


# ── CLI ────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        print("Usage: material_bin.py <file.material.bin>")
        sys.exit(1)
    mat = MaterialBin.from_file(sys.argv[1])
    print(mat.summary())
