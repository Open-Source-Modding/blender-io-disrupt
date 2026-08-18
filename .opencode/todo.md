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
- [x] Compressed mesh triangle bitstream: vertex decompression working, triangle connectivity blocked (need IDA GUI + primitive files for TAG0 TYPE section parsing)
- [x] WDL parser: pre-existing issue (struct.error in import_wdl_xbg.py:77), parked for now
- [x] Box import: boxes read correctly (radius+0x30, halfExtents+0x40, numVertices+0x70), can be injected but not imported as editable objects yet — deferred to future work
