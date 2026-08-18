# Legion Leak — Havok 2017.2 Primitive Files

## Key Finding
The primitive HKX files in the Legion leak at `data_win64/generated/primitives/` are **Havok 2017.2** (SDKV `20170200@`). They use the **TAG0 format** (not the old packfile format) and contain the exact compressed mesh classes needed.

## File Locations
- `data_win64/generated/primitives/prim_4_*.hkx` — 9 files, ~8KB each
- Format: TAG0/SDKV/DATA/TYPE/INDX/ITEM/PTCH chunks
- SDK version: `20170200@` (Havok 2017.2.0)

## Classes Found in Primitive Files
- `hknpCompressedMeshShape` — the collision shape
- `hknpCompressedMeshShapeData` — contains the mesh tree + connectivity
- `hknpCompressedMeshShapeTree` — the mesh tree with sections/primitives
- `hknpCompressedMeshShapeTreeDataRun` — the data run entries
- `hkcdStaticMeshTreeBase` — the base tree class
- `hkcdStaticMeshTreeCommonConfig` — tree configuration

## TAG0 Format Structure
```
+0x00: header (flags + size + magic)
+0x04: hash
+0x08: total size
+0x0c: flags
+0x10: TAG0 magic
+0x14: SDKV chunk (SDK version string)
+0x1c: DATA chunk (serialized objects)
+0x4b0: TYPE chunk (class definitions)
+0xb72: ITEM chunk (item metadata)
+0x20a8: INDX chunk (index data)
+0x2148: PTCH chunk (patch data)
```

## Next Steps
1. Parse the TYPE section to extract class member layouts for `hknpCompressedMeshShapeTree`
2. Map the binary layout to the HKLib C# class definitions
3. Use this to decode the compressed mesh triangle bitstream
4. Build a decoder for the WD1/WD2/WDL compressed mesh format

## Importance
These files are **Havok 2017.2** — the exact version WDL uses. The `hkCompatFormats.dll` from 2017.2 would be needed for packfile serialization, but these primitive files show the CLASS LAYOUTS which are version-specific. This is the missing piece for understanding the compressed mesh format.
