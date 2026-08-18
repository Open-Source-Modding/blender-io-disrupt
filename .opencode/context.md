# Project Context — blender-io-disrupt

## Completed Work
- WD1 HKX format fully decoded (all classes, offsets, transforms, connectivity)
- WD1 HKX injector built + tested (bit-identical round trip)
- WD2 HKX import/inject wired + tested
- Compressed mesh vertex decompression working (11/11/10-bit + 21/21/22-bit)
- Packfile format documented (old + TAG0)
- Havok 2017.2 primitive files analyzed — full class layouts decoded
- Compressed mesh format documented (sections, primitives, dataRuns, connectivity)
- Addon pushed to Open-Source-Modding/blender-io-disrupt

## Key Files
- `modules/Havok/` — HKX parser, collision reader, injectors, compressed mesh decoder, operators
- `RE/havok/` — format docs + README linking to docs site
- `docs/compressed_mesh_format.md` — decoded Havok 2017.2 class layouts

## Compressed Mesh Format (Havok 2017.2)
- Section header (96B): codecParms[6], firstPackedVertex, sharedVertices, primitives, dataRuns, numPackedVertices, numSharedIndices
- PrimitiveDataRun (4B): value(u16) + index(u8) + count(u8)
- hkcdStaticMeshTreeBase: packedVertices[], sharedVerticesIndex[], primitives[], sections[], primitiveDataRuns[]
- Vertex decompression: 11/11/10-bit packed u32, 21/21/22-bit shared u64
- Triangle connectivity: NOT yet decoded — needs PrimitiveDataRun iteration

## Pending
- Compressed mesh triangle bitstream decoding (PrimitiveDataRun iteration)
- WDL parser fix (pre-existing)
- Box import as editable objects
