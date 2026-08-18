# Project Context — blender-io-disrupt

## Repo
- Renamed: blender-io-xbg → blender-io-disrupt
- Remote: git@github.com:Open-Source-Modding/blender-io-disrupt.git
- Latest commit: 07b4365
- Platform: Linux, Blender 5.2 LTS at /usr/bin/blender

## Mission — ★ COMPLETE (verified by Reviewer)
Decode WD1 HKX compressed mesh (hkcdStaticMeshTree) triangle connectivity and integrate into the addon. **DONE: 24/24 todo items [x], 0 sync issues, status=pass.**

## ★★ SOLVED — CORRECT DECODE ALGORITHM (234/234 meshes verified, 0 degenerate)

### Array mapping (OLD decoder was INVERTED — read primitives from sharedVertices, hence only secs 0-3 "worked")
| Array | tree+tag | data-rel ptr | count | elem | content |
|-------|----------|-------------|-------|------|---------|
| sections | +0x10 | **0x290** | 33 | 0x60 | per-section codec+indices |
| **primitives** | +0x20 | **0x6540** | 2745 | 4B | (a,b,c,d) LOCAL u8 vertex idx |
| **sharedVerticesIndex** | +0x30 | **0x9030** | 779 | u16 | shared slot → shared vert idx |
| **packedVertices** | +0x40 | **0x9650** | 2103 | u32 | 11/11/10-bit quantized |
| **sharedVertices** | +0x50 | **0xb730** | 380 | u64 | 21/21/22-bit (380×8 ends exactly @0xc310 ✓) |
| dataRuns | +0x60 | **0xc310** | 2429 | 8B | {value u32, index u8, count u8, pad u16} |

- Tree: o+0xa0 (o=shape offset 0x20 → tree=0xc0). +0x00 numPrimitiveKeys=2748, +0x04 bitsPerKey, +0x08 maxKeyValue, +0x0c flags; descriptors 16B {ptr fixup @tag, u32 size @tag+0x08}.
- **DOMAIN AABB at tree−0x20 (data+0xa0)**: +0x00 min.xyz(+w), +0x10 max.xyz(+w). min=(−7.3501,−8.0013,−0.3364), max=(3.0387,1.7597,7.3084).

### Section layout (33 × 0x60 @ 0x290)
- +0x00 u64 nodes ptr (fixup), +0x08 size, +0x0c cap|0x80000000
- +0x30/+0x34/+0x38 offset (3f), +0x3c/+0x40/+0x44 scale (3f)
- +0x48 firstPackedVertex (cumulative → packedVertices; total 2103)
- +0x4c packed (firstSharedVertexIndex<<8 | numPackedVertices) — >>8 cumulative = 779
- +0x50 packed (firstPrimitiveIndex<<8 | numPrimitives) — >>8 cumulative = 2745
- +0x54 packed (firstDataRunIndex<<8 | numDataRuns) — >>8 cumulative = 2429
- +0x58 u8 numPackedVertices; +0x59 u8 numSharedIndices

### Vertex/primitive decode (per section)
- packed i: `packedVertices[firstPackedVertex+i]` dequant 11/11/10 with section offset/scale
- shared i: `sharedVertices[ sharedVerticesIndex[firstSharedVertexIndex+i] ]` dequant 21/21/22 with DOMAIN
- primitive type (Havok 2018 getType, from hkcdStaticMeshTree.inl L50-110): b≠d,c==d→TRIANGLE(a,b,c); b≠d,c≠d→QUAD(a,b,c)+(a,c,d); b==d→EXTERNAL/CUSTOM/INVALID `0xde 0xad 0xde 0xad` ("DEAD") padding → SKIP
- dataRuns: 2018 getPrimitiveData binary search (index≤li<index+count → value)

## Sources
- 2013 SDK repo: `/tmp/opencode/havok2013` — `Common/Compat/Patches/2011_1/hkcdPatches_2011_1.cxx` (old classes); `Physics2012/Internal/Collide/BvCompressedMesh/hkpBvCompressedMeshShape.h` (NUM_BYTES_FOR_TREE=160)
- 2018 SDK: `.../hk2018_1_0_r1/Source/Geometry/Internal/DataStructures/StaticMeshTree/hkcdStaticMeshTreeDecoder.inl` (getPrimitiveData L154, decodeVertex); `.../Geometry/Collide/DataStructures/StaticMeshTree/hkcdStaticMeshTree.h` + `.inl`

## Current Status — INTEGRATION COMPLETE + VERIFIED
- `modules/Havok/decompress_compressed_mesh.py` — REWRITTEN: `decode_compressed_mesh(f, cm)` → (verts, faces) triangles
- `modules/Havok/decode_compressed_mesh.py` — CLI rewritten (prints verts/tris/bbox/sample faces)
- `modules/Havok/import_hkx_wd.py` — importer builds EXACT triangle surface (hull_recon=False) w/ AABB-hull + _add_box fallback; decode_compressed_mesh imported via try/except (relative + absolute)
- `AGENTS.md` — documented verified layout
- Reviewer verification (S1.3.1, ses_fe98428e5ffe81grW4N5bT5MBy / task_256c83e4): py_compile PASS; regression 267 facade .hkx → OK=234 BAD=0 degenerate=0 faces=69683; Blender import parking_staircase → (0, 2882, 1), 2882v/2748f hull_recon=False; code review PASS
- .opencode/todo.md: 24/24 [x]; .opencode/status.md: pass; .opencode/work-log.md: 6 rows done; no sync issues
- Git: modified context.md, todo.md, decode_compressed_mesh.py, decompress_compressed_mesh.py, import_hkx_wd.py, AGENTS.md (not committed — user hasn't asked)

## Pending Tasks
1. None for this mission — M1 100% complete. (Committing changes only if user requests.)
2. Deferred/separate: WDL .xbg parser fix (struct.error import_wdl_xbg.py:77); Box import as editable objects; WD1 native .xbg exporter (next concrete step — geometry region regenerated, sections 1-10 preserved; measured: header+sections 1-10 = 3-6% of file, geometry 94-97%).
3. Archived Reviewer task IDs: task_12c0789a (done), task_18e3ffec (done, result was empty output)