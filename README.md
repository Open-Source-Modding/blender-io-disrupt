# Disrupt Engine Importer/Exporter for Blender

A Blender 5.0 add-on for **importing, editing and re-exporting 3D models from Ubisoft
Disrupt engine games** — Watch Dogs 1, 2, and Legion.

> Originally written for Blender 2.49b. Rewritten from the ground up for modern
> Blender. **Expect bugs, things to fix, things to change and more features coming soon.**

---

## Highlights

- **Three games, one add-on** — Watch Dogs 1 (.xbg), 2 (.glm), and Legion (.xbg), each with
  its own self-contained module and a clean game-picker UI.
- **True editing freedom** — not just moving vertices: add and delete geometry, delete
  whole submeshes, join in foreign meshes, edit UVs and bone weights, then write it all
  back into a copy of the game file.
- **HKX collision support** — import collision shapes (convex hulls + boxes) for all three
  games, inject displacement-only edits back with byte-identical round-trips. Format
  documented in the reference docs.
- **Animations** — import skeletal animations (.mab) for Watch Dogs games, and import
  scenes** with their cameras, anchors and timeline markers.
- **Skeletons & collision** — import standalone .skeleton rigs; import HKX collision
  **inject displacement-only collision** for WD2 (bit-identical round-trips) —
  modify any model's collision shape.
- **Custom materials** — bake Blender materials into game-ready texture (.xbt) and
  material (.xbm) files, with DXT compression, template inheritance, glass and glow
  templates.
- **LOD control** — import a chosen LOD or all of them, peek a file's LOD count before
  importing, and edit each mesh's LOD switch distances.
- **Format-exact round-trips** — injection preserves everything you didn't edit
  byte-for-byte (verified with byte-identical unedited re-exports), and oversized
  custom geometry automatically expands the file's bounds/precision instead of
  clamping.
---

## Supported Games

| Game | Format | Model Import | Textures / Materials | Re-export (Inject) | Add/Delete Geometry | Animation | Skeleton File | Collision (HKX) |
|---|---|---|---|---|---|---|---|---|
| **Watch Dogs 1** | .xbg | ✅ Full (+ streamed hi-detail LODs) | ⚠️ slot names only | ✅ | ✅ | ✅ .mab | ✅ import | ✅ import & **inject** (displacement-only) |
| **Watch Dogs 2** | .glm | ✅ Full | ⚠️ slot names | ✅ **.glm export** | ✅ | — | — (rig from model) | ✅ import & **inject** (displacement-only) |
| **Watch Dogs Legion** | .xbg | ✅ (compiled MOEG + .skel) | ⚠️ slot names only | ✅ in-place | ❌ Count changes | ✅ .mab | ✅ import (.skel) | ✅ import |

**Legend / footnotes**

- *Re-export (Inject)* always writes to a **new copy** of the game file — your
  originals are never touched.
- *Add/Delete Geometry* = full rebuild support: change vertex/triangle counts, delete
  submeshes, re-skin new geometry from vertex groups. Games without it support
  reshape/sculpt/UV/color edits at the original vertex count.
- WD1 vehicles with split LOD buffers and streamed-LOD meshes patch in place (no count
  changes); WD1 also auto-updates the companion `.high.xbgmip` streamed-LOD file so
  edits don't "revert" at close range.
- WD2 export preserves materials/skeleton/physics blocks byte-for-byte and hands you a
  .glm ready for a GLM2XBG converter.

---

## Requirements

- **Blender 5.0** or newer
- Game files for the game you want to mod (extracted where the game ships archives —

---

## Installation

1. Download the latest release `.zip` from the [Releases](../../releases) page.
2. In Blender: **Edit → Preferences → Add-ons → Install**, pick the zip, enable
   **XBG Importer**.
3. In the add-on preferences, set the data-folder path(s) for your game(s) — this is
   what powers automatic texture loading. 

> **Upgrading from v2.x?** Do a fresh install from the zip (remove the old add-on
> first) — v2.x's game modules are incompatible with v3.0.0's layout.

### Updates

There is no in-app updater. To update, download the latest release `.zip` from the
[Releases](../../releases) page (or grab the `Dev` branch source for the newest
in-progress fixes) and reinstall it the same way as the initial install — remove the
old add-on first, then install the new zip. A previous auto-updater was removed in
v3.0.0 because it could leave the add-on in a broken, un-listed state after applying
an update; manual reinstall is slower but always leaves you with a known-good copy.

---

## Using the Add-on

Open the **N-panel** (`N` in the 3D Viewport) → **XBG Import** tab → **pick your
game**. Every game uses the same layout:

| Panel | Visible | What it does |
|---|---|---|
| **Import** | always | Data-folder setting, texture options, LOD peek, the big import button |
| **Advanced Mode** | always (toggle) | Reveals everything below |
| **Inject / Export** | advanced | Status of the linked source file, bounds check, the big inject button |
| **Animation** | advanced | .mab import with resampling/helper options (games with animation) |
| **Skeleton / HKX** | per game | Standalone skeleton import, collision import/export |
| **Model Info / Debug** | advanced | What the importer captured; verbose logging controls |

### Typical workflow: edit a model and put it back in the game

1. **Import** the model with **Separate Primitives ON** (Advanced Mode → import
   options). This keeps one Blender object per game submesh — required for writing
   back. (Imported with it off? The object is flagged as *joined* and the inject panel
   will tell you to re-import.)
2. **Edit** in Blender: sculpt, move vertices, restructure UVs, repaint vertex colors,
   assign weights. On games with full rebuild support you can extrude/delete geometry,
   delete entire submeshes, or `Ctrl+J`-join a completely different mesh into an
   imported object (make the imported object active so its metadata survives).
3. Select the edited objects and press the game's **Inject** button. Pick the output
   path (pre-filled next to the source) — a patched copy is written, ready to pack back
   into the game.

### Typical workflow: view an animation

1. Import the model (the armature is created from the file).
2. Advanced Mode → **Animation** → pick the `.mab`. Bones are matched automatically
   (by name hash or skeleton file, depending on the game); options cover smooth
   resampling, helper-bone emulation and twist baking.
   scene — cameras, anchors and timeline markers included.


1. Set up your material in Blender on the imported mesh.
2. Advanced Mode → **Export Custom Materials** — choose a template (standard, glass,
   glow…), and the add-on bakes game-ready `.xbt` textures + `.xbm` material files into
   your patch folder.

---

## Repository Layout

```
__init__.py        # add-on entry point (registration, version)
modules/
  Core/            # preferences, logging, shared settings
  UI/              # game picker + one panel file per game
  Far_Cry_1/  Far_Cry_2/  Far_Cry_3/  Far_Cry_4/  Far_Cry_5/
  Far_Cry_Primal/  Far_Cry_Instincts/  Far_Cry_6/ (placeholder)
  Watch_Dogs/  Watch_Dogs_2/  Watch_Dogs_Legion/
```

Every game's code is deliberately isolated — no cross-game imports — so a fix or
experiment in one game can never break another.

---

## Branches

| Branch | Description |
|---|---|
| `main` / `public` | Stable release |
| `Dev` | Latest work-in-progress with recent fixes and features |

---

## Credits

**Authors:** Selene0623, Quiet Joker

**Special thanks:** EncryptedStudios, Jasper_Zebra, legendhavoc175, and qstlijku


Rewritten and expanded for Blender 5.0 by Selene0623

## Want to help?

