# Project Context — blender-io-xbg

## Completed Work
- WD1 HKX format fully decoded (all classes, offsets, transforms, connectivity)
- WD1 HKX injector built + tested (bit-identical round trip)
- WD2 HKX import/inject wired + tested
- Compressed mesh vertex decompression working (11/11/10-bit + 21/21/22-bit)
- Packfile format documented (old + TAG0)
- Havok 2017.2 primitive files found in WDL leak (SDKV 20170200@)
- Havok module reorganized: `modules/Havok/` with parser, collision reader, injectors, operators
- Format docs moved to open-source-modding.github.io/reference/watch_dogs/
- RE directory with links to docs site

## Current Files
- `modules/Havok/` — HKX parser, collision reader, injectors, compressed mesh decoder, operators
- `RE/havok/` — format docs snapshots + README linking to docs site
- `open-source-modding.github.io/reference/watch_dogs/` — canonical format docs (packfile, compressed mesh, injection, repos, legion primitives)

## Pending
- [ ] Rename addon: blender-io-xbg → blender-io-disrupt (drop Dunia modules, document in git history)
- [ ] Compressed mesh triangle bitstream decoding (need IDA GUI + primitive files)
- [ ] WDL parser fix (pre-existing)
- [ ] Box import as editable objects (currently only hulls imported as objects)

## Key Havok Findings
- WD1 uses Havok 2012 old packfile format (__data__ section, local/global/virtual fixups)
- WD2 uses Disrupt format (TAG0/SDKV/DATA/TCRF/INDX/ITEM/PTCH chunks)
- WDL uses Havok 2017.2 (SDKV 20170200@) with compact tagfile
- Compressed mesh: packedVertices (11/11/10-bit), sharedVertices (21/21/22-bit), primitives (byte[4]), dataRuns (value/index/count)
- hkCompatFormats.dll from 2017.2 is needed for packfile serialization (not in leak)
