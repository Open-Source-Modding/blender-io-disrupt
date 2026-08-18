"""Havok HKX packfile format parser and writer.

Supports two formats:
1. Old packfile (Havok 2012): __classnames__, __types__, __data__ sections
2. TAG0 format (Havok 2017+): TAG0, SDKV, DATA, TYPE, INDX, ITEM, PTCH chunks

This module reads and writes HKX files without Blender dependencies.
"""

import struct
import copy
from dataclasses import dataclass, field
from typing import Optional, Dict, List, Tuple, Any


# ── Magic numbers ───────────────────────────────────────────────────────────
HAVOK_MAGIC = b'\x57\xe0\xe0\x57\x10\xc0\xc0\x10'
TAG0_MAGIC = b'TAG0'
SDKV_MAGIC = b'SDKV'
DATA_MAGIC = b'DATA'
TYPE_MAGIC = b'TYPE'
INDX_MAGIC = b'INDX'
ITEM_MAGIC = b'ITEM'
PTCH_MAGIC = b'PTCH'


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class HkxSection:
    """A section in the old packfile format."""
    tag: str
    abs: int
    local: int
    global_offset: int
    virtual: int
    exports: int
    imports: int
    end: int


@dataclass
class HkxChunk:
    """A chunk in the TAG0 format."""
    tag: str
    flags: int
    size: int
    offset: int  # offset of chunk data (after 8-byte header)


@dataclass
class HkxItem:
    """An item in the ITEM table (TAG0 format)."""
    index: int
    type_id: int
    flags: int
    data_offset: int
    count: int


@dataclass
class HkxFixup:
    """A fixup entry (PTCH table)."""
    pointer_type: int
    pointer_location: int
    target_item: int


# ── Old packfile parser ─────────────────────────────────────────────────────

class OldPackfileParser:
    """Parser for Havok 2012 old packfile format."""
    
    def __init__(self, data: bytes):
        self.raw = data
        self.wrapper = 0
        self.base = 0
        self.sections: Dict[str, HkxSection] = {}
        self.objects: Dict[int, str] = {}
        self.local: Dict[int, int] = {}
        self.glob: Dict[int, int] = {}
        
        self._parse()
    
    def _parse(self):
        """Parse the old packfile structure."""
        # Find Havok magic
        idx = self.raw.find(HAVOK_MAGIC)
        if idx < 0:
            raise ValueError("Not a Havok packfile")
        self.wrapper = idx
        d = self.raw[self.wrapper:]
        
        # Check pointer size
        ptr_size = d[16]
        if ptr_size != 8:
            raise ValueError(f"Expected 64-bit packfile, got {ptr_size}-bit")
        
        # Parse sections
        num_sections = struct.unpack_from('<i', d, 20)[0]
        for i in range(num_sections):
            off = 64 + i * 48
            tag = d[off:off+19].split(b'\0')[0].decode('latin-1')
            vals = struct.unpack_from('<7i', d, off + 20)
            self.sections[tag] = HkxSection(
                tag=tag, abs=vals[0], local=vals[1],
                global_offset=vals[2], virtual=vals[3],
                exports=vals[4], imports=vals[5], end=vals[6]
            )
        
        dat = self.sections['__data__']
        self.base = dat.abs
        
        # Parse class names
        cn = self.sections['__classnames__']
        cn_abs = cn.abs
        
        def classname(off):
            e = d.index(b'\0', cn_abs + off)
            return d[cn_abs + off:e].decode('latin-1')
        
        # Virtual fixups (class name mapping)
        p = self.base + dat.virtual
        while p + 12 <= self.base + dat.exports:
            o, s, c = struct.unpack_from('<3i', d, p)
            p += 12
            if o != -1:
                self.objects[o] = classname(c)
        
        # Local fixups
        p = self.base + dat.local
        while p + 8 <= self.base + dat.global_offset:
            f, t = struct.unpack_from('<2i', d, p)
            p += 8
            if f != -1:
                self.local[f] = t
        
        # Global fixups
        p = self.base + dat.global_offset
        while p + 12 <= self.base + dat.virtual:
            f, s, t = struct.unpack_from('<3i', d, p)
            p += 12
            if f != -1:
                self.glob[f] = t
    
    def read_u32(self, obj_off, rel):
        # obj_off: data-relative offset within __data__ section
        # rel: field offset within the object
        # base = dat['abs'] = file offset of __data__ section start
        # File offset = base + obj_off + rel
        return struct.unpack_from('<I', self.raw, self.base + obj_off + rel)[0]
    
    def read_f32(self, obj_off, rel):
        return struct.unpack_from('<f', self.raw, self.base + obj_off + rel)[0]


# ── TAG0 format parser ──────────────────────────────────────────────────────

class Tag0Parser:
    """Parser for TAG0 (Havok 2017+) packfile format."""
    
    def __init__(self, data: bytes):
        self.raw = data
        self.items: List[HkxItem] = []
        self.fixups: List[HkxFixup] = []
        self.data_offset = -1
        self.sdk_version = ''
        
        self._parse()
    
    def _parse(self):
        """Parse the TAG0 structure."""
        pos = 0
        while pos < len(self.raw) - 8:
            chunk = self._read_chunk(pos)
            if chunk is None:
                break
            
            if chunk.tag == 'TAG0':
                self._parse_tag0(chunk)
            elif chunk.tag == 'SDKV':
                self.sdk_version = self.raw[chunk.offset:chunk.offset + chunk.size].split(b'\0')[0].decode('latin-1')
            elif chunk.tag == 'DATA':
                self.data_offset = chunk.offset
            elif chunk.tag == 'ITEM':
                self._parse_item(chunk)
            elif chunk.tag == 'PTCH':
                self._parse_ptch(chunk)
            
            pos = chunk.offset + chunk.size
    
    def _read_chunk(self, pos):
        """Read a chunk header."""
        if pos + 8 > len(self.raw):
            return None
        
        # Chunk header: flags(u8) + size(u24) + magic(u32)
        # But the actual format might be different — let me try the standard
        # approach: size_and_flags (u32) + magic (u32)
        
        size_and_flags = struct.unpack_from('<I', self.raw, pos)[0]
        magic = self.raw[pos+4:pos+8]
        
        # Try interpreting as: size_and_flags contains size in lower bits
        size = size_and_flags  # raw value
        
        if magic in [b'TAG0', b'SDKV', b'DATA', b'TYPE', b'INDX', b'ITEM', b'PTCH']:
            return HkxChunk(
                tag=magic.decode('ascii'),
                flags=0,
                size=size,
                offset=pos + 8
            )
        
        # Try: the magic might be at a different offset
        for offset in [0, 4, 8]:
            if pos + offset + 4 <= len(self.raw):
                m = self.raw[pos+offset:pos+offset+4]
                if m in [b'TAG0', b'SDKV', b'DATA', b'TYPE', b'INDX', b'ITEM', b'PTCH']:
                    # Found magic — the chunk header is before it
                    header_pos = pos + offset - 4
                    if header_pos >= 0:
                        s_and_f = struct.unpack_from('<I', self.raw, header_pos)[0]
                        return HkxChunk(
                            tag=m.decode('ascii'),
                            flags=s_and_f >> 30,
                            size=s_and_f & 0x3FFFFFFF,
                            offset=pos + offset + 4
                        )
        
        return None
    
    def _parse_tag0(self, chunk):
        """Parse TAG0 chunk contents."""
        pos = chunk.offset
        while pos < chunk.offset + chunk.size - 8:
            sub = self._read_chunk(pos)
            if sub is None:
                break
            if sub.tag == 'SDKV':
                self.sdk_version = self.raw[sub.offset:sub.offset + min(sub.size, 32)].split(b'\0')[0].decode('latin-1')
            elif sub.tag == 'DATA':
                self.data_offset = sub.offset
            elif sub.tag == 'ITEM':
                self._parse_item(sub)
            elif sub.tag == 'PTCH':
                self._parse_ptch(sub)
            pos = sub.offset + sub.size
    
    def _parse_item(self, chunk):
        """Parse ITEM chunk."""
        pos = chunk.offset
        idx = 0
        while pos + 12 <= chunk.offset + chunk.size:
            type_and_flags, data_offset, count = struct.unpack_from('<III', self.raw, pos)
            pos += 12
            
            type_id = type_and_flags & 0xFFFFFF
            flags = (type_and_flags >> 24) & 0xF
            
            self.items.append(HkxItem(
                index=idx,
                type_id=type_id,
                flags=flags,
                data_offset=data_offset,
                count=count
            ))
            idx += 1
    
    def _parse_ptch(self, chunk):
        """Parse PTCH chunk."""
        pos = chunk.offset
        while pos + 12 <= chunk.offset + chunk.size:
            pointer_type, pointer_location, target_item = struct.unpack_from('<III', self.raw, pos)
            pos += 12
            self.fixups.append(HkxFixup(
                pointer_type=pointer_type,
                pointer_location=pointer_location,
                target_item=target_item
            ))
    
    def get_item_data(self, item):
        """Get raw bytes for an item."""
        if self.data_offset < 0 or item.data_offset == 0:
            return b''
        return self.raw[self.data_offset + item.data_offset:
                        self.data_offset + item.data_offset + item.count]


# ── Public API ──────────────────────────────────────────────────────────────

def parse_hkx(path: str):
    """Parse an HKX file (auto-detect format)."""
    with open(path, 'rb') as f:
        data = f.read()
    
    if HAVOK_MAGIC in data[:32]:
        return OldPackfileParser(data)
    elif TAG0_MAGIC in data[:32]:
        return Tag0Parser(data)
    else:
        # Try finding TAG0 at offset 0x10 (after Dunia header)
        idx = data.find(TAG0_MAGIC)
        if idx >= 0 and idx < 64:
            return Tag0Parser(data[idx-4:])
        raise ValueError("Not a recognized HKX format")
