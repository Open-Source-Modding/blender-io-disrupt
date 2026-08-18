# WD1/WD2 HKX Injection Internals

## WD2 Injection Pipeline (Disrupt format)

### Format Structure
```
TAG0 header → DATA chunk → ITEM table → PTCH table → TCRF compendium
```

### ITEM Table (12 bytes each)
```c
struct HkxItem {
    uint32 typeIdAndFlags;  // typeId & 0xFFFFFF, flags (typeId >> 28) & 0xF
    uint32 dataOffset;      // offset within DATA section
    uint32 count;           // element count
};
```

### Key Type IDs (WD2 static collisions)
- 0x21: shape root (quantized)
- 0x49: vertex header
- 0x25: vertex/plane data
- 0x4b: face indices
- 0x2D: shape data
- 0x93: shape root (full precision)
- 0x57: vertices (full precision)
- 0x4E: planes (full precision)
- 0x0D: face indices (full precision)

### Injection Flow
1. Parse ITEM table → find shape item by index
2. Follow fixups from shape item → find shape_data (type 0x2D)
3. Follow fixups from shape_data → find vertex array (type 0x25) and header (type 0x49)
4. Update AABB in shape_data (+0x20 min, +0x30 max)
5. Update AABB in vertex header (+0x10 min, +0x20 max)
6. Re-encode vertices as 11/11/10-bit quantized (scale = extent/2047 for x/y, /1023 for z)
7. Write quantized u32s back to DATA section

### PTCH Table (fixups)
```c
struct HkxFixup {
    uint32 pointerType;      // type of pointer
    uint32 pointerLocation;  // offset within DATA
    uint32 targetItemIndex;  // index into ITEM table
};
```
Fixups resolve inter-item references (e.g., shape → shape_data → vertex_array).

## WD1 Injection Pipeline (Old packfile format)

### Format Structure
```
Havok header → __classnames__ → __types__ → __data__
```

### Fixup Tables (within __data__)
- **Virtual fixups**: data offset → class name (12-byte entries)
- **Local fixups**: data offset → data offset (8-byte entries)
- **Global fixups**: data offset → object offset (12-byte entries)

### Injection Flow
1. Parse __data__ section → resolve all fixups
2. Find shape objects by class name (from virtual fixups)
3. Resolve data pointers via local fixups
4. Patch float data at resolved addresses
5. Write modified data back (byte-identical)

## Key Differences

| Feature | WD1 (Old packfile) | WD2 (Disrupt TAG0) |
|---------|--------------------|--------------------|
| Object lookup | Class name strings | Type IDs (0x21, 0x49, etc.) |
| Fixup storage | Inline in __data__ | Separate PTCH table |
| Data location | __data__ section | DATA chunk |
| Compendium | N/A | TCRF (24 bytes) |
| Injection target | Direct byte patching | ITEM table + DATA offset |

## Implications for Compressed Mesh

The compressed mesh data is stored within the packfile as `hkpBvCompressedMeshShape` objects. To decode the bitstream:

1. **Old packfile (WD1)**: Find the compressed mesh object via virtual fixups, resolve the tree pointer via local fixups, read the inline tree data
2. **TAG0 (Legion)**: Find the compressed mesh item via ITEM table, follow fixups to the tree data in DATA section

The tree data contains:
- 160 bytes inline: BVH nodes, domain AABB, array pointers
- Array pointers (local fixups) → sections, packedVertices, primitives, dataRuns, connectivity

The bitstream is encoded within the dataRuns array (PrimitiveDataRun entries). Each run specifies an offset, type, and count for reading primitives from a compact representation.

## What's Still Unknown

1. **Exact mapping of section header fields (+0x4c, +0x50, +0x54)** to HKLib equivalents
2. **How dataRuns decode primitives** — the encoding scheme (strip, fan, individual edges, etc.)
3. **How the connectivity structure maps sections to triangles**
4. **Whether the old packfile and TAG0 formats use the same compressed mesh class layouts** (likely yes, but need validation)
