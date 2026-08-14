# AGENTS.md — blender-io-xbg

Blender 5.0+ addon for importing, editing, and re-exporting 3D models from ten Ubisoft games.

## Structure

```
__init__.py         # Entry point, bl_info (v3.1.0, Blender 5.0.0+), register/unregister
modules/
  Core/             # Shared settings, preferences, debug/verbose logging
  UI/               # Game-picker root panel + per-game panel files
  Avatar/           # Avatar: The Game + Far Cry 2 (Dunia) — largest module (~40 files)
  Far_Cry_1/        # CryEngine 1 .cgf (leaked source based)
  Far_Cry_2/        # Independent clone of Avatar toolset (FC2-specific operators/props)
  Far_Cry_3/        # FC3 + FC4 GEOM path
  Far_Cry_4/        # FC4
  Far_Cry_5/        # Mesh RE in progress
  Far_Cry_Primal/   # FC4-family GEOM (0x0006003A)
  Far_Cry_Instincts/# Xbox 2005 .xbg (unrelated format)
  Far_Cry_6/        # Placeholder — not yet supported
  Watch_Dogs/       # .xbg (WD1)
  Watch_Dogs_2/     # .glm (WD2) — includes binary .xbg importer
  Watch_Dogs_Legion/# .xbg (MOEG binary, same format family as WD2)
```

## Watch Dogs modules

### Watch_Dogs (WD1)
- `import_wd.py` — WD1 .xbg importer
- `import_hkx_wd.py` — HKX skeleton importer
- `import_mab_wd.py` — MAB animation importer
- `import_skeleton_wd.py` — Skeleton importer
- `material_bin.py` — TAM v7 material binary reader/writer (916 parameter names in `materialNames.txt`)
- `material_editor_wd.py` — Material editor (descriptor XML parser + Principled BSDF bridge)
- `materialdescriptors/` — 85 material descriptor XMLs from the Disrupt engine
- `xbt_wd.py` — XBT ↔ DDS texture converter (bit-perfect round trip)
- `inject_wd.py` — Mesh injection (vertex patching)
- `procedural_wd.py` — Procedural mesh tools
- `quat_resample_wd.py` — Quaternion resampling

### Watch_Dogs_2 (WD2)
- `import_wd2_xbg.py` — WD2 binary .xbg importer (ported from Volfin's WD2 Blender tool to modern architecture)
- `operators_wd2.py` — Import/inject operators
- `hash_wd2.py` — FNV-1a 64-bit hash utility (XBG file validation)
- WD2 uses `.glm` format (MOEG v149.70) + `.skel` skeleton

### Watch_Dogs_Legion (WDL)
- `import_wdl_xbg.py` — WDL compiled .xbg importer (MOEG header v0x95/0x46)
- `inject_wdl.py` — Mesh injection (vertex patching, position/UV edits only)
- `import_mab_wdl.py` — WDL .mab animation importer (magic 0x46B4, inner bitstream identical to WD1)
- `operators_wdl.py` — Import/inject/skeleton/mab operators
- WDL uses `.xbg` (MOEG binary) + `.skel` skeleton — same format family as WD2
- **Hybrid format**: WD2's MOEG XBG (v149.70) + WD1's nbCF v3 skeleton

## Conventions

- **Game isolation**: No cross-game imports between game modules. A fix in Avatar cannot break FC3.
- **Naming**: Operators `XBG_OT_<Action>[FC2|FC3|...]`, panels `XBG_PT_<Panel>`, props `XBG*`.
- **Registration order matters**: UI panels listed after their parent panel in `__init__.py:classes`.
- **FC2 is an independent clone** of the Avatar toolset with its own property namespace (`_fc2` suffix on scene props, `FC2` suffix on operator/panel classes).
- **Inject never modifies originals** — always writes a new copy.
- **Separate Primitives ON** required for inject workflow (one Blender object per game submesh).

## Key patterns

- Scene-level state stored on `bpy.types.Scene` (e.g., `xbg_active_game` string for picker).
- Debug logging via `VerboseLogger` in `modules/Core/debug.py` — dual text + JSONL output.
- Addon preferences via `XBGAddonPreferences` in `modules/Core/prefs.py`.
- Get preferences with `get_prefs(ctx)` from the same module.
- Game picker: `Scene.xbg_active_game = 'NONE'` shows the picker, set to game ID to show that game's tools.

## File → Import menu
- `register()` appends `menu_func_import` to `TOPBAR_MT_file_import` in `__init__.py`
- Shows WDL model (.xbg) and skeleton (.skel) importers in File → Import
- Animation imports stay in sidebar (require armature pre-selection)

## WDL .xbg parser quirks
- Vehicle files have `_unk_count != 0` (24 vs 0 for characters) and an extra 28-byte block
  between the LOD section and material declarations
- The parser tries the standard WD2 layout first; if `mat_count > 200` it falls back to
  scanning for the first `graphics\_materials\` string marker and deriving the real count
- Material count is at `marker - 16` bytes in the file, with another u32 skip before the
  first material's hash/string data
- See the WD2ModelStudio.exe `XbgParser.ReadModel()` for reference implementation

## Key references
- **WD2ModelStudio.exe** (`Xbg.Net48`) at `~/Code/game-tools/hV_WD_ModdingKit_PLUS/Tools/Gibbed Tools/` — standalone tool with full XBG/HKX/material parsing
- **Ubisoft leak** at `~/Code/re/ubisoft/extracted/` — `adp_lib.py` (asset pipeline), material descriptors, shader source
- **Gibbed.Disrupt** at `~/Code/game-tools/Gibbed.Disrupt/` — binary object converters, pack/unpack, definitions
- **Noesis plugin** `dunia_xbt.py` — Xbox 360 XBT texture reader (big-endian, tiled)

## WDL format notes

### WDL .hkx collision format (Disrupt serialization)
- **NOT** standard Havok packfile — custom wrapper around Havok serialized data
- Header at offset 0:
  - `+0x00`: u32 version (0x99 for primitives, varies)
  - `+0x04`: u32 CRC32 checksum
  - `+0x08`: u32 total size
  - `+0x0C`: u32 flags (0x0002FFFF typical)
  - `+0x10`: u32 dataSize
  - `+0x14`: `TAG0` magic
  - `+0x1C`: u32 0x10 (section count?)
  - `+0x20`: `SDKV20170200` → Havok SDK 2017.2.0
  - `+0x30`: `DATA` section start
- Internal structure uses **item table** + **fixup table** + **type strings** (not full Havok packfile sections)
- `HkxParserDisrupt` pipeline: `ReadItems(buf,off,len,file)` → `ReadPatches(buf,off,len,file)` → `SliceItemBytes(file)` → `ResolveFixups(file)` → `FindRoot(file)` → `ExtractAllConvexShapes(file)`
- Convex shapes decoded via `DecodeQuantized(shape,shapeData,hdr,verts,idx)` for compressed or `TryDecodeFullPrecisionShape` for float32
- Full precision injection via `InjectFullPrecisionShape(file,index,obj,bytes)` — rebuilds vertex/index buffers
- Referenced in the tool's source path: `C:\Users\Frank\source\repos\Xbg.Net48`

### WDL .xbg model format
- MOEG header: version 0x95 (WD2) or 0x46 (WDL)
- Vertex format: position (float3), normal (int2 normalized), tangent (int2 normalized), color (RGBA byte), UV (float2 or half2)
- Bone weights: up to 4 per vertex, stored as bytes with index lookup
- Submeshes stored as index buffers with material references
- `.skel` file: nbCF v3 format, bones with parent index, position (float3), rotation (quaternion)

### WDL .xbt texture format (XBT ↔ DDS)
- Magic: `TBX\x00` at offset 0
- 0x34-byte wrapper header containing format flags, metadata, and path string
- The rest is a raw DDS file (DXT1/DXT5/BC7/DX10 etc.)
- **XBT → DDS:** `xbt_to_dds(path)` strips the 0x34-byte header, saves DDS + `.xbt.header`
- **DDS → XBT:** `dds_to_xbt(path, header_path=...)` prepends the saved header back
- Round trip is bit-identical (verified on a 5.5 MB BC7 2048×2048 texture)
- Module: `modules/Watch_Dogs/xbt_wd.py`

XBT header layout:
- `+0x00`: u32 magic `TBX\x00` (0x00584254 LE)
- `+0x04`: u32 platform/build version byte — **0x92** for WDL BC7, **0x8F** for WD1 DXT5
- `+0x08`: u32 header size (0x34=52 for BC7, 0x2C=44 for DXT5)
- `+0x0C`: u32 flags (usually 0)
- `+0x10`: u32 format ID — 0x02000003 (BC7), 0x01040401 (DXT5), 0x01010101 (DX10 array)
- `+0x14`: u32 format sub-type/hint (2 for BC7, 1 for DXT5)
- `+0x18`: u32 packed metadata — different byte at +0x19 distinguishes mip levels (0xFF010101=high, 0xFF010301=med)
- `+0x1C`: u32 asset CRC/hash (identical across mip levels of same texture — game-internal asset ID)
- `+0x20`: u32 metadata (0x72 for BC7, 0x02 for DXT5)
- `+0x24`: u32 unknown (varies)
- `+0x28`: u32 padding (usually 0)
- Header is followed by raw DDS data (no embedded path string in PC versions)

Known Noesis Xbox 360 plugin (`dunia_xbt.py`) reads the format differently: big-endian, tiled GPU textures, format encoded as `(fmt & 0x3F)` = 18→DXT1, 19→DXT3, 20→DXT5, 6→RAW.
The `0x18` field can also encode a link to a `_high` mip variant — the game rarely loads `_high` textures even on Ultra, and swapping/changing this field affects which mip level is selected.

### WDL .mab animation format
- **Magic:** 0x46B4 at file offset 0 (vs WD1's 0x329B)
- **Inner `aNi` block at offset 0x20** (vs WD1's 0x14):
  - `+0`: 'aNi' (3) + flags (1)
  - `+4`: u32 animDataSize
  - `+8`: f32 duration
  - `+12`: f32 framerate (~30.0) — **new field**, not in WD1
  - `+16`: u16 numBones (top bit masked)
  - `+18`: u16 counts[7]
  - `+32`: u32 offsets[11] — **aNi-relative** (not absolute, no +0x10 adjustment)
  - `+96`: u32 boneHashes[numBones] (CRC32 of bone names)
  - `+96 + nb*4`: u8 boneFlags[numBones] (same encoding as WD1)
- **Sections** (at `aNi + offs[n]`):
  - `[2]`: key times / misc data
  - `[3]`: unknown
  - `[4]`: JointRotations bitstream (table_size, chunk ends, compressed quaternions)
  - `[5]`: JointConstantRotations (6 bytes per constant bone)
  - `[6-8]`: continuation data
- **Inner bitstream identical to WD1** — smallest-three quaternion codec, same
  `_INTERP_SCALE`, `_unpack_const_quat`, `_decode_bone_block` from WD1 module.
  The `apply_wd1_mab()` function is reused directly.
- **Key times generated** from chunk count × 8 (no explicit key times section).
- **Hashes/CRC** used to match bones to the skeleton, same as WD1.

## Workflow

Test by installing as a Blender addon (Edit → Preferences → Add-ons → Install, pick the repository root as a .zip). There is no headless test suite, no CI, no lint/typecheck config — this is a pure Blender Python addon.

Branches: `main` (stable). Remote: `git@github.com:Open-Source-Modding/blender-io-xbg.git`.
