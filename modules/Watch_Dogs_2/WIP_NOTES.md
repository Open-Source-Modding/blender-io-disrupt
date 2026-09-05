# WD2 XBG Binary Import — Character Model Format Notes

## Status: BLOCKED on IDA/Ghidra RE

The `import_wd2_xbg.py` parser works for **static props** (goldengate, metaltable buildings)
where `ReflexSystem count=0`. **Character models** (pers09.xbg, wrench.xbg) have a
completely different format that crashes the parser.

## Root Cause

The C# ground truth (`XbgParserD.cs` from FranciscoManzanilla/WD2MSCore) was only
tested against static props. The `_read_skip_mess` function assumes:
- Entry prefix = 56 bytes (BI(2) + Bf(7) + BI(4) + BI(1))
- Entry type u32 follows prefix (2 = nested hash+string, else = other nested format)
- Entries have nested hash+string structures

Character models violate ALL of these assumptions:
- Entries start with flat float parameters (0.0, -9.8, 1.0, 0.6, 0.1, 0.01)
- No valid entry_type (first u32 after 56-byte prefix is a float value like 0.6)
- Entries have `0xFFFFFFFF` sentinels every 28 bytes
- Zero mesh descriptors found using the static-prop format (40 bytes bbox + 22 u16s + u32)

## Binary Structure Verified (pers09.xbg, 519152 bytes)

```
0x0000: MOEG, version 0x0089/0x0046, hash128, unk_count=5, odd_flag=0
0x0020: 76 bytes bounding data
0x006C: lod_count=1
0x00A4: mat_count=5 (raphaelboyon×3: wd2cloth/wd2skin, slabreche×2: wd2cloth)
0x032C: skeleton_count=1, bone_id_count=322, bone_flag=8
0x1764: bone_count=99
0x3368: matrix section (99 bones, 4×4 f32 matrices)
0x4C3C: ReflexSystem count=3 — UNKNOWN FORMAT for character models
        Entries have flat float parameters, not hash+string structures
        0xFFFFFFFF sentinels appear every 28 bytes
        After ReflexSystem: secondary motion (count unknown)
        Then: mesh descriptors (format unknown for characters)
```

## What's Needed

Reverse-engineer `CGeometryResource::Load()` in `Disrupt_64.dll` at the
`CMP ECX, 'MOEG'` check (address 0x0C002BD0). This function handles both
static props and character models, so understanding its branching logic
will reveal the character model format.

## Working Test Data

- `/home/selene/Documents/Modding/WD2/pers09.xbg` (519152 bytes, character model)
- `/home/selene/Documents/Modding/WD2/pers09_head.xbg` (103KB, character head)
- Static props that work: goldengate/metaltable XBG files (count=0)

## Related Resources

- `XbgParserD.cs` (FranciscoManzanilla/WD2MSCore) — C# ground truth for static props
- `Staticxbgcompiler.cs` (FranciscoManzanilla/GlmCompilerToXBG) — vertex format verified
- `WD2_XBG_GLM_Research_Summary.md` (cached in `.opencode/docs/`)
- `verify_xbg.py` (cached in `.opencode/docs/`) — static prop round-trip test
