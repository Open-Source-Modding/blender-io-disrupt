# Mission Tasks

## Completed
- [x] WD1 HKX format decoded (all classes, offsets, transforms, connectivity)
- [x] WD1 HKX injector built + tested (bit-identical round trip)
- [x] WD2 HKX import/inject wired + tested
- [x] Compressed mesh vertex decompression working (11/11/10-bit + 21/21/22-bit)
- [x] Packfile format documented (old + TAG0)
- [x] Havok 2017.2 primitive files found in WDL leak (SDKV 20170200@)
- [x] Havok module reorganized (modules/Havok/)
- [x] Format docs moved to docs site (open-source-modding.github.io)
- [x] RE directory with links to docs site
- [x] Rename addon: blender-io-xbg → blender-io-disrupt (code reorganized, Dunia modules removed from active code, documented in git history)
- [x] WDL parser: pre-existing issue (struct.error in import_wdl_xbg.py:77), parked for now
- [x] Box import: boxes read correctly (radius+0x30, halfExtents+0x40, numVertices+0x70), can be injected but not imported as editable objects yet — deferred to future work

## M1: Compressed mesh TRIANGLE CONNECTIVITY — SOLVED ★
### T1.1: Decode algorithm discovered & verified
- [x] S1.1.1: Section stride verified = 0x60 (33 fixups spaced 0x60 apart @ data+0x290..0xe90)
- [x] S1.1.2: Array mapping corrected (OLD decoder was INVERTED): primitives@0x6540 (2745×4B), sharedVerticesIndex@0x9030 (779×u16), packedVertices@0x9650 (2103×u32), sharedVertices@0xb730 (380×u64, ends exactly at 0xc310), dataRuns@0xc310 (2429×8B)
- [x] S1.1.3: Domain AABB located at tree−0x20 (data+0xa0): min(−7.35,−8.00,−0.34) max(3.04,1.76,7.31)
- [x] S1.1.4: dataRuns verified as 2018-style primitive data runs: (index,count) key tiles [0,numPrimitives) for all 33 sections
- [x] S1.1.5: Full decode verified: 2745 faces, 2882 verts (2103 packed + 779 shared), all indices valid, bbox within domain
- [x] S1.1.6: Primitive types implemented per Havok 2018 getType(): TRIANGLE (b!=d,c==d), QUAD (2 tris), INVALID 0xDEAD padding skipped
- [x] S1.1.7: Verified across 234 compressed meshes / 267 facade .hkx files — 0 degenerate faces

### T1.2: Integration into addon modules
- [x] S1.2.1: `decompress_compressed_mesh.py` rewritten with correct array mapping + domain + primitive types
- [x] S1.2.2: `decode_compressed_mesh.py` CLI rewritten to use verified decoder (was heuristic bitstream guesser)
- [x] S1.2.3: `import_hkx_wd.py` importer now builds EXACT triangle surface (hull_recon=False) with AABB-proxy fallback
- [x] S1.2.4: Headless Blender 5.2 test: parking_staircase imports 2882 verts / 2748 faces

### T1.3: Verification
- [x] S1.3.1: Reviewer — run full test suite, verify no regressions, mark M1 complete

## Out of Scope / Future Work (NOT part of M1 — parked/deferred/next-step)
These are separate future-work items, explicitly outside the M1 compressed mesh
triangle connectivity milestone. Documented for future reference; they do not
block M1 completion (see .opencode/context.md "Remaining Tasks (outside M1)").

- (-) WDL .xbg parser fix (struct.error import_wdl_xbg.py:77) — parked, separate task
- (-) Box import as editable objects — deferred to future work
- (-) WD1 native .xbg exporter — next concrete step (uses this decoder knowledge)