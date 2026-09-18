# AGENTS.md — blender-io-xbg

## Project Overview

Blender 5.0+ addon for importing, editing, and re-exporting 3D models from Ubisoft Disrupt engine games (Watch Dogs 1/2/Legion). Pure Python, no CI, no lint, no type checking.

## Structure

```
__init__.py         # Entry point (v3.1.2, Blender 5.0.0+)
modules/
  Core/             # Settings, preferences, debug logging, shared builder
  UI/               # Game-picker root panel + per-game panel files
  Havok/            # HKX format support (parser, collision reader, injectors, compressed mesh decoder)
  Watch_Dogs/       # WD1 .xbg importer, exporter, inject, collision, materials, animation
  Watch_Dogs_2/     # WD2 .glm text importer, .xbg binary importer, GLM exporter, collision, materials
  Watch_Dogs_Legion/# WDL .xbg importer, exporter, inject, animation, collision
tests/              # Smoke tests (pytest-blender)
```

**Legacy modules**: Dunia engine modules (Avatar, Far_Cry_1..6, Far_Cry_Primal, Far_Cry_Instincts) are gone. Only Disrupt engine modules remain.

## Critical Conventions

- **Shared modules**: Games share `Core/` (logging, builder, preferences) and `Havok/` (HKX collision). WDL reuses WD1's MAB animation parser. Game-specific import/export stays in each game's directory.
- **Naming**: Operators `XBG_OT_<Action>[FC2|FC3|...]`, panels `XBG_PT_<Panel>`, props `XBG*`.
- **Registration order**: UI panels listed after parent panel in `__init__.py:classes`. This order matters.
- **Inject never modifies originals**, always writes a new copy.
- **Separate Primitives ON** required for inject workflow (one Blender object per game submesh).

## Commands

### Syntax check (no linter/typecheck exists)
```bash
python -m py_compile <file>
```

### Run tests (requires Blender + game data)
```bash
pytest --blender-executable /usr/bin/blender
```

- `pytest.ini` sets `blender-executable`, `testpaths = tests`, `import-mode = importlib`.
- Tests are smoke tests parsing real game files. Set env vars:
- `XBG_REPO_ROOT` (repo root, defaults to auto-detected)
- `XBG_WDL_DIR` (WDL unpacked graphics directory)
- `XBG_WD1_DIR` (WD1 unpacked graphics directory)
- `XBG_WD2_DIR` (WD2 unpacked graphics directory)
- Each test file has a local `_import_modules()` that adds repo root to `sys.path` lazily (avoids importing addon root as package parent of `tests/`).
- The `tests/util` module referenced in `conftest.py` docstring does not exist; tests define `_import_modules()` inline.

### Manual test
Install as Blender addon: Edit → Preferences → Add-ons → Install → pick repo root as .zip.

## Testing Quirks

- Tests depend on external game data directories, won't pass without them.
- `conftest.py` has hardcoded fallback paths (`/home/selene/Documents/Modding/...`).
- No CI, no lint, no typecheck, pure Blender Python addon.

## Format Gotchas

### WDL .xbg parser
- Vehicle files have `_unk_count != 0` (24 vs 0 for characters) with extra 28-byte block before materials.
- Parser tries standard WD2 layout first; if `mat_count > 200` it falls back to scanning for `graphics\_materials\` string marker.
- Material count is at `marker - 16` bytes, with another u32 skip before first material's hash/string data.

### XBG binary format
- Header: `MOEG` + VER_MINOR(u16) + VER_MAJOR(u16) — WD2 static = 0x89/0x46, WDL = 0x95/0x46
- LOD section: lodCount(u32), then `float dist × 2` per LOD (NOT u32 pairs)
- Materials: `tagCount MUST be 1` or material won't apply
- Geometry: faces written **reversed (c,a,b)** for outward normals

### HKX collision
- WDL uses custom Disrupt Havok (not standard Havok packfile)
- Injection is VERTEX-DISPLACEMENT-ONLY (count/order must not change)
- Unmodified inject is bit-identical
- **Havok version mismatch**: Leak uses Havok 2014.2.5 or 2015.1 (varies), WD2 retail uses Havok 2015.1, WD1/WDL retail uses Havok 2017.2, collision from leak doesn't work on retail
- **CI + HKX handshake**: `.ci` (collision index) maps which `.hkx` to use for each entity slot. They must match, mismatched CI/HKX causes missing/broken collision
- Custom collision must be built against the target retail SDK version (2015.1 for WD2, 2017.2 for WD1/WDL), not the leak

### Vertex encoding (static props, stride 32)
- `[0..1]` normal — OCTAHEDRAL as 2×int16 (not 3)
- `[2..4]` position — int16 normalized to mesh AABB
- `[6..7]` UV0 — `(u-0.5)*65536`, V-flipped

## Key Patterns

- Scene-level state on `bpy.types.Scene` (e.g., `xbg_active_game`).
- Debug logging: `VerboseLogger` in `modules/Core/debug.py`.
- Preferences: `XBGAddonPreferences` in `modules/Core/prefs.py`, get with `get_prefs(ctx)`.
- Game picker: `Scene.xbg_active_game = 'NONE'` shows picker.
- `modules/Core/detect.py` — game auto-detection from file headers (magic/version bytes). Exists as a standalone utility but is **not yet wired into the UI/operator flow**.

## Key References

- **OpenSourceModding.github.io** — format docs, guides, and references for Disrupt engine modding (`~/Documents/Code/web/open-source-modding.github.io/`)
- **WD2ModelStudio.exe** — standalone tool with full XBG/HKX/material parsing
- **Gibbed.Disrupt** — binary object converters, pack/unpack
- **HavokDisruptWD2** (github.com/FranciscoManzanilla) — hkx resolver for WD2 (reference for custom serialization)
- **xbgModelModInjector** (github.com/FranciscoManzanilla) — WD2 XBG mesh injector (`XbgParserD.cs`, `XbgMeshInjector.cs`, `XbgVertexPatcher.cs`, `XbgBoundsAnalyzer.cs`) — independent implementation of the same inject/vertex-patch/bounds workflow
- **WD2MSCore** (github.com/FranciscoManzanilla) — "Watch Dogs 2 Model Studio BETA"
- Note: FranciscoManzanilla repos are small AI-assisted source dumps (Spanish docs, no releases) — useful as implementation cross-references, not production tools.
- **GeomParser_r64.dll** (Ubisoft leak) — XBG parser/compiler. Decompiled C available at `~/Documents/Code/re/Ubisoft/Disrupt/leak/` (4.5MB). Key classes: `CGLMParser` (reads .glm), `CTriMesh` (outputs .xbg), `CColladaParser`, `CGamExParser`
- **Animation_r64.dll** (Ubisoft leak) — animation pipeline. Havok 2014.2.5 or 2015.1 format in leak, 2017.2 in retail
- **Havok license keys** — HAVOK_CORP, InternalHavok, UbisoftToronto_WatchDogs3 keys saved at `~/Documents/Code/re/havok/havok-keys.md`

## Havok Version Gate

> **Verified against actual HKX files** (2026-09-04).

| Component | Leak/Beta Version | Retail Version |
|-----------|------------------|----------------|
| Collision (HKX) | Havok 2015.1 (WDL leak) | Havok 2015.1 (WD2) / 2017.2 (WD1/WDL) |
| Animation | Havok 2014.2.5 or 2015.1 | Havok 2017.2 |

**Collision**: CI (collision index) + HKX must handshake. Leak CI/HKX won't work on retail due to version mismatch. WD2 uses Havok 2015.1, WD1/WDL uses 2017.2.

**Animation**: Would need to extract all anims from 2017 format, convert to source format, patch DLL for target version, and recompile. Currently theoretical, no tool exists for this.

## TODO

- Vehicle file support (fix `_unk_count != 0` parser)
- Full round-trip for all Disrupt games (WD1/WD2/WDL)
- Texture export (material editor → XBT → DDS round trip)
- **Animation exporter** (`export_mab_wdl.py`) — write Blender actions back to `.mab` format (inverse of existing `import_mab_wdl.py`). The `.mab` bitstream is custom (not Havok), so this is SDK-independent
- **CombinedMoveFile support** — Dunia/Disrupt animation state machine container (move states, blend trees, motion matching, curves, ragdoll). Reference: `~/Documents/Code/re/Ubisoft/Dunia/MabTools-main/FCBConverter/CombinedMoveFile.cs` (120KB, GPL). Param hashes defined in `OffsetsHashesArray.ParamNames` (CRC32). Currently FC4/FC5/FCNewDawn only, but same format family. Would need: binary parser for `MoveBinDataChunk` (classNameType 7-21), XML↔binary round-trip, Blender integration for state machines/blend trees. **Parity note**: `blender-io-dunia` now has `modules/move_values.py` (shared MoveValueDefinitions) + `import_move_fc4.py`/`import_move_fc5.py` (header + tree structure parsers). FC5 combinedmovefile.bin format is: u32 ver + u32 moveDataSize + u32 fcbDataSize + moveData + fcbData. Tree uses classNameType bytes (7-47) to dispatch node parsing. Port those for WD1/WD2/WDL parity.
