# Havok Packfile Format — WD1/WD2 (64-bit, Havok 2012)

## File Structure

```
┌─────────────────────────────────────────────────┐
│ 16-byte wrapper (Dunia engine)                   │
│   +0x00..0x0f: game-specific header              │
├─────────────────────────────────────────────────┤
│ Havok packfile (starts at wrapper+0x10)          │
│   +0x00..0x07: magic 0x57e0e057 10c0c010        │
│   +0x10: bytesInPointer (8 = 64-bit)            │
│   +0x14: numSections (i32)                       │
│   +0x28..0x37: version string (e.g. "hk_2012.2.0-r1\0") │
├─────────────────────────────────────────────────┤
│ Section headers (48 bytes each, starting at +40) │
│   +0x00..0x12: tag (19 bytes, null-terminated)  │
│   +0x14: abs (i32) — absolute address            │
│   +0x18: local (i32) — local fixup offset        │
│   +0x1c: global (i32) — global fixup offset      │
│   +0x20: virtual (i32) — virtual fixup offset    │
│   +0x24: exports (i32) — export offset           │
│   +0x28: imports (i32) — import offset           │
│   +0x2c: end (i32) — end offset                  │
├─────────────────────────────────────────────────┤
│ __classnames__ section: class name strings       │
│ __types__ section: type definitions (optional)   │
│ __data__ section: serialized object data         │
│   Contains: fixup tables + object instances      │
└─────────────────────────────────────────────────┘
```

## Fixup Tables (within __data__)

### Virtual Fixups (class name mapping)
```
Entry: [u32 dataOffset][u32 sectionIdx][u32 nameOffset]
```
- Maps data-relative offsets to class names
- sectionIdx references __classnames__ section
- nameOffset is the string offset within __classnames__

### Local Fixups (pointer resolution)
```
Entry: [u32 from][u32 to]
```
- Both from and to are data-relative offsets
- Resolves internal pointers within the same section
- Used for: array data pointers, nested object pointers

### Global Fixups (object references)
```
Entry: [u32 from][u32 sectionIdx][u32 to]
```
- from: data-relative offset of the pointer slot
- sectionIdx: target section (usually __data__)
- to: data-relative offset of the target object

## How Injection Works

1. **Read** the packfile via `WdHkxFile` (parses all fixups)
2. **Find** shape objects by class name (from virtual fixups)
3. **Resolve** data pointers via local fixups (e.g., `f.local.get(off + 0x50)` → array address)
4. **Patch** float data at resolved addresses (e.g., SOA hkFourVectors)
5. **Write** modified data back (byte-identical except patched floats)

Key insight: fixups store data-relative offsets. To get file-absolute offsets:
```python
abs_offset = f.wrapper + f.base + data_relative_offset
```
Where `f.wrapper` = Dunia header size (0 or 16), `f.base` = __data__ section's abs address.

## Old Packfile vs TAG0 Format

| Feature | Old (WD1/WD2) | TAG0 (Legion) |
|---------|---------------|---------------|
| Magic | 0x57e0e057 10c0c010 | TAG0 chunk |
| Sections | __classnames__, __types__, __data__ | TAG0, SDKV, DATA, TYPE, TNA1, INDX, ITEM, PTCH |
| Fixups | Inline in __data__ | Separate INDX/ITEM chunks |
| Class names | In __classnames__ | In TYPE/TNA1 chunks |
| SDK version | hk_2012.2.0-r1 | 20170200@ |

## Compressed Mesh Storage

Within the packfile, `hkpBvCompressedMeshShape` stores:
- m_tree: 160 bytes inline (BVH nodes, domain AABB, array pointers)
- Tree points to: sections, packedVertices, primitives, dataRuns, sharedVerticesIndex, connectivity
- Sections contain: AABB, codec parameters, first*Index, num* counts
- Primitives: byte[4] with global vertex indices (edge pairs)
- DataRuns: PrimitiveDataRun entries (value/index/count) encoding the bitstream
