## Compressed Mesh Format Analysis — WD1/WD2/WDL hkpBvCompressedMeshShape

### Tree Structure (hkpBvCompressedMeshShapeTree)
Location: `o + 0xa0` (160 bytes for 64-bit single-precision)

The tree contains inline data + pointers to global arrays:

| Offset | Field | Value (parking_staircase) | Description |
|--------|-------|---------------------------|-------------|
| +0x00 | m_numPrimitiveKeys | 0x0abc = 2748 | Total primitive keys |
| +0x04 | m_bitsPerKey | 0x0e = 14 | Bits per shape key |
| +0x08 | m_maxKeyValue | 0x2074 = 8308 | Maximum key value |
| +0x0c | m_primitiveStoresIsFlatConvex | 0 | Boolean flag |
| +0x10 | m_sections (local fixup) | → 0x290 | Section headers array |
| +0x18 | m_sections size/cap | 33 / 0x80000021 | 33 sections |
| +0x20 | m_packedVertices (local fixup) | → 0x6540 | Quantized vertex data |
| +0x28 | m_packedVertices size/cap | 2745 / ... | uint[] quantized positions |
| +0x30 | m_primitives (local fixup) | → 0x9030 | Edge/face indices |
| +0x38 | m_primitives size/cap | 2748 / ... | u16 pairs (global indices) |
| +0x40 | m_sharedVerticesIndex (local fixup) | → 0x9650 | ushort[] shared vertex map |
| +0x48 | m_sharedVerticesIndex size/cap | ... | |
| +0x50 | m_primitiveDataRuns (local fixup) | → 0xb730 | Encoded data runs |
| +0x58 | m_primitiveDataRuns size/cap | 380 / ... | PrimitiveDataRun[] |
| +0x60 | (local fixup) | → 0xc310 | Connectivity or extra data |

### Section Header (0x60 bytes each, at sec_ptr + i*0x60)
Contains: AABB codec parameters, vertex/primitive/data-run indices and counts.

### Primitives (u16 pairs at data-rel 0x9030)
- Each primitive stores 2 vertex indices (u16 LE) — likely edge pairs or triangle strip entries
- First 43 are sequential: (0,1), (2,3), (4,5), ..., (84,85)
- After that, indices become non-sequential (mesh connectivity)
- 2748 total primitives, indices up to 65535 (GLOBAL across all sections)

### Data Runs (PrimitiveDataRun at data-rel 0xb730)
- 380 runs × 4 bytes each: `m_value` (ushort), `m_index` (byte), `m_count` (byte)
- `m_value`: offset into primitives data (bit offset, range 12–65147)
- `m_index`: section/type identifier (range 0–248)
- `m_count`: count of items (range 0–93)
- These decode the bitstream into primitives

### Confirmed Section Header Field Mapping (Havok 2012)
| Offset | Field | Description |
|--------|-------|-------------|
| +0x08 | nv (u32) | Total vertices for this section |
| +0x10..+0x27 | m_codecParms[6] (6 floats) | Quantization parameters (AABB min/max) |
| +0x48 | m_firstPackedVertexIndex (u32) | Cumulative index into packedVertices array |
| +0x58 | m_numPackedVertices (byte) | Count of packed vertices for this section |
| +0x59 | m_numPrimitives (byte) | Count of primitives for this section |
| +0x5a | m_numDataRuns (byte) | Count of data runs for this section |

**Validation**: idx48 differences match +0x58 byte values exactly (e.g., section 0→1: 26-0=26, b58=26 ✓).

**Still unknown**: +0x4c, +0x50, +0x54 (cumulative but don't match simple counts). These may be firstSharedVertexIndex, firstPrimitiveIndex, firstDataRunIndex — but the values don't match expected ranges.

### Key Insight
The primitives are already decoded at 0x9030 (byte[4] with global vertex indices). The data runs are PrimitiveDataRun entries (value/index/count) that encode the bitstream.

### Remaining Work
1. Determine exact encoding scheme (strip vs fan vs individual edges)
2. Map +0x4c, +0x50, +0x54 to HKLib fields
3. Reconstruct full triangle mesh from primitives + section transforms
4. Use primitive files (Havok 2017.2) from Legion leak for class layout validation
