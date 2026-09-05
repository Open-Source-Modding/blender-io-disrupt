# Disrupt Engine Importer/Exporter for Blender

A Blender 5.0 add-on for **importing, editing and re-exporting 3D models from Ubisoft
Disrupt engine games**: Watch Dogs 1, 2, and Legion.

> **Expect bugs.** This is a community tool under active development.

---

## Highlights

- **Three games, one add-on**: Watch Dogs 1 (.xbg), 2 (.glm/.xbg), and Legion (.xbg), each with
  its own module and a game-picker UI.
- **Edit and inject**: move vertices, edit UVs, repaint vertex colors, assign weights, then write
  it all back into a copy of the game file. WD1 supports full rebuild (add/delete geometry);
  WDL/WD2 support displacement-only edits.
- **HKX collision**: import collision shapes for all three games. WD1 and WD2 support
  vertex-displacement injection back into a copy of the .hkx.
- **Animation**: import .mab skeletal animations for WD1 and WDL. Import .mac animation clips
  and .markup event files for WD1.
- **Materials**: import/export .material.bin files (TAM v7/v15) with Principled BSDF mapping.
  TFOWC2 extended material system supported.
- **LOD control** (WD1): import a chosen LOD or all of them, peek a file's LOD count before importing.
- **FaceFX lip-sync**: import FaceFX phoneme .txt files as viseme shape key animations.

---

## Supported Games

| Game | Format | Import | Inject/Export | Animation | Collision | Materials |
|---|---|---|---|---|---|---|
| **Watch Dogs 1** | .xbg | Full (skeleton, weights, UVs, normals, tangents, vertex colors, LODs) | Rebuild (add/delete geometry) + in-place | .mab, .mac, .markup | .hkx import + inject | .material.bin import/export |
| **Watch Dogs 2** | .glm / .xbg | Full (skeleton, weights, UVs) | .glm text export + .xbg inject (displacement-only) | — | .hkx import + inject | .material.bin import/export |
| **Watch Dogs Legion** | .xbg | Full (MOEG binary + .skel) | .xbg export from Blender + inject (displacement-only) | .mab | .hkx import | .material.bin import/export |

**Notes:**

- Inject always writes to a **new copy**, originals are untouched.
- WD1 vehicles with split LOD buffers patch in place (no count changes).
- WD2 .glm export preserves materials/skeleton/physics blocks byte-for-byte.
- WDL export produces a valid .xbg (static props, no physics/procedural).

---

## Requirements

- **Blender 5.0** or newer
- Extracted game files for the game you want to mod

---

## Installation

1. Download the latest release `.zip` from the [Releases](../../releases) page.
2. In Blender: **Edit → Preferences → Add-ons → Install**, pick the zip, enable
   **XBG Importer**.

> **Upgrading from v2.x?** Remove the old add-on first, v2.x modules are
> incompatible with v3.x layout.

### Updates

Download the latest release `.zip` (or grab the `Dev` branch) and reinstall,
removing the old add-on first. A previous auto-updater was removed in v3.0.0
because it could leave the add-on in a broken state.

---

## Using the Add-on

Open the **N-panel** (`N` in the 3D Viewport) → **XBG Import** tab → **pick your
game**.

| Panel | Visible | What it does |
|---|---|---|
| **Import** | always | The import button + LOD options (WD1) |
| **Advanced Mode** | always (toggle) | Reveals Inject/Export, Animation, Debug |
| **Inject / Export** | advanced | Inject edited meshes or export fresh .xbg (WDL) |
| **Animation** | advanced | .mab / .mac import (WD1, WDL) |
| **Model Info** | advanced | What the importer captured on the active mesh |

### Edit and inject (WD1)

1. Import with **Separate Primitives ON** (Advanced Mode → import options).
2. Edit in Blender: sculpt, move verts, restructure UVs, repaint vertex colors, assign weights.
3. Select edited objects → **Inject WD1 Mesh** → pick output path.

### Export fresh model (WDL)

1. Create or import mesh objects in Blender.
2. Select them → **Export WDL Model (.xbg)** → pick output path.

### Import animation

1. Import the model (armature is created from the file).
2. Advanced Mode → **Animation** → pick the `.mab` file.

---

## Repository Layout

```
__init__.py        # add-on entry point (registration, version)
modules/
  Core/            # preferences, logging, shared settings, common builder
  UI/              # game picker + one panel file per game
  Havok/           # HKX collision parser, decompressor, injector
  Watch_Dogs/      # WD1 import, export, inject, collision, materials, animation
  Watch_Dogs_2/    # WD2 GLM/xbg import, export, collision, materials
  Watch_Dogs_Legion/ # WDL import, export, inject, animation, collision
tests/             # Smoke tests (pytest-blender)
```

Games share `Core/` (logging, builder, preferences) and `Havok/` (HKX collision).
WDL reuses WD1's MAB animation parser. Game-specific import/export stays in each game's directory.

---

## Credits

**Authors:** Selene0623, Quiet Joker

**Special thanks:** EncryptedStudios, Jasper_Zebra, legendhavoc175, qstlijku
