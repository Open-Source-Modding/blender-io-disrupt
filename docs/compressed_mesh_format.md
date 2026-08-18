# WD1/WD2/WDL Compressed Mesh Format (Havok 2017.2)

## Source
Class definitions extracted from `prim_4_10252363098235285984.hkx` in the Legion leak using hkxparser (Havok 2017.2, SDKV 20170200@).

## Class Hierarchy
```
hknpCompressedMeshShape (144 bytes, align 16)
  └─ m_data: hknpCompressedMeshShapeData (256 bytes, align 16)
       ├─ m_meshTree: hknpCompressedMeshShapeTree (160 bytes, align 16)
       │    └─ extends hkcdStaticMeshTree (160 bytes)
       │         ├─ packedVertices: hkArray<uint32>    (+0x70)
       │         ├─ sharedVertices: hkArray<uint64>    (+0x80)
       │         └─ primitiveDataRuns: hkArray<PrimitiveDataRun> (+0x90)
       ├─ m_simdTree: hkcdSimdTree (16 bytes)
       └─ m_connectivity: hkcdStaticMeshTreeBase::Connectivity (48 bytes)
            ├─ headers: hkArray<SectionHeader>
            ├─ localLinks: hkArray<uint8>
            └─ globalLinks: hkArray<uint32>
```

## Key Structures

### hkcdStaticMeshTreeBase (112 bytes, align 16)
```
+0x30: int32  numPrimitiveKeys
+0x34: int32  bitsPerKey
+0x38: uint32 maxKeyValue
+0x3c: uint8  primitiveStoresIsFlatConvex
+0x40: hkArray<Section>    sections
+0x50: hkArray<Primitive>  primitives
+0x60: hkArray<uint16>     sharedVerticesIndex
```

### Section (96 bytes, align 16)
```
+0x30: float[6]  codecParms       (quantization: AABB min/max)
+0x48: uint32    firstPackedVertex (index into packedVertices)
+0x4c: uint32    sharedVertices    (index into sharedVerticesIndex)
+0x50: uint32    primitives        (index into primitives array)
+0x54: uint32    dataRuns          (index into primitiveDataRuns array)
+0x58: uint8     numPackedVertices
+0x59: uint8     numSharedIndices
+0x5a: uint16    leafIndex
+0x5c: uint8     page
+0x5d: uint8     flags
+0x5e: uint8     layerData
+0x5f: uint8     unusedData
```

### PrimitiveDataRun (4 bytes)
```
+0x00: uint16  value   (data run value)
+0x02: uint8   index   (data run index)
+0x03: uint8   count   (data run count)
```

### hknpCompressedMeshShapeData (256 bytes)
```
+0x20: hknpCompressedMeshShapeTree meshTree  (160 bytes inline)
+0xc0: hkcdSimdTree simdTree
+0xd0: Connectivity connectivity              (48 bytes inline)
```

### Connectivity (48 bytes)
```
+0x00: hkArray<SectionHeader>  headers
+0x10: hkArray<uint8>          localLinks
+0x20: hkArray<uint32>         globalLinks
SectionHeader: {uint32 baseLocal, uint32 baseGlobal}  (8 bytes each)
```

## Key Differences from HKLib (2018)
- HKLib uses `PrimitiveDataRun` with `m_value`(u16) + `m_index`(u8) + `m_count`(u8)
- Binary format uses `PrimitiveDataRunData` (u16) + `index`(u8) + `count`(u8) — same layout!
- Section layout matches our earlier analysis but with confirmed field names
- `numSharedIndices` at +0x59 (NOT numPrimitives as previously assumed)
