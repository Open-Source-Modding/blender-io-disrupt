"""Scene-level settings PropertyGroups (shared by all game UIs).

Split out of the monolithic __init__.py (2026-06-09 refactor).
"""
import bpy


class XBGDebugSettings(bpy.types.PropertyGroup):
    advanced_mode: bpy.props.BoolProperty(
        name="Advanced Mode",
        description="Show inject, export, and all advanced options",
        default=False
    )
    verbose_logging: bpy.props.BoolProperty(
        name="Verbose Logging",
        description="Print detailed debug information to console (bones, chunks, transforms, etc.)",
        default=False
    )
    separate_primitives: bpy.props.BoolProperty(
        name="Separate Primitives",
        description="Create separate mesh objects for each primitive chunk instead of joining them",
        default=False
    )
    trace_logging: bpy.props.BoolProperty(
        name="Trace-Level Logging",
        description=(
            "EXPENSIVE — only enable when chasing a specific bug. Adds per-vertex / per-face "
            "/ per-byte detail to the verbose log: full hex dumps of encoded vertices, "
            "before/after Blender→world→int16 position transforms, chunk-splice byte maps, "
            "and a structured .jsonl record file written next to the saved log. Generates "
            "hundreds of KB to a few MB of log data per export. Requires Verbose Logging to "
            "be ON; has no effect on its own"
        ),
        default=False
    )
    lod_peek_result: bpy.props.StringProperty(
        name="LOD Peek Result",
        default=""
    )
    mab_emulate_helpers: bpy.props.BoolProperty(
        name="Emulate Twist / Corrective Bones",
        description="The engine drives twist and elbow/knee corrective "
                    "bones procedurally (the .mab has no data for them). "
                    "ON: add constraints that reproduce that behaviour — "
                    "fixes the collapsing wrist and the knee denting "
                    "inward. OFF: leave helper bones at rest",
        default=True
    )
    mab_twist_bake: bpy.props.BoolProperty(
        name="Exact Twist (bake swing-twist)",
        description="How the forearm/upper-arm TWIST bones are emulated. "
                    "ON (recommended): bake true swing-twist keys per frame — "
                    "the bone gets only the hand's ROLL and none of its bend, "
                    "matching the engine's RollExtractionMode (properly fixes "
                    "the candy-wrapper wrist). OFF: a live Copy-Rotation "
                    "constraint (editable, but copies the Euler-Y component so "
                    "it leaks the bend and only approximates)",
        default=True
    )
    mab_smooth_resample: bpy.props.BoolProperty(
        name="Smooth Playback (SQUAD resample)",
        description="The engine stores spline-compressed rotation and "
                    "evaluates a smooth curve at the game framerate, so a "
                    "15 fps clip still plays smoothly. ON: bake dense in-"
                    "between keys with SQUAD (spherical cubic) interpolation "
                    "through the decoded keys, reproducing that smoothing. "
                    "OFF: key only the decoded frames (sparse / choppy, but "
                    "easier to hand-edit)",
        default=True
    )
    mab_resample_fps: bpy.props.IntProperty(
        name="Smooth Target FPS",
        description="Resample target framerate for Smooth Playback. The clip "
                    "is upsampled toward this rate (e.g. a 15 fps clip → 60). "
                    "Original keyframe poses are preserved exactly",
        default=60, min=24, max=120
    )
    wd_reskin_weights: bpy.props.BoolProperty(
        name="Include Bone Weights",
        description="Same as the Avatar inject option: write vertex-group "
                    "weights into the mesh. ON: re-derive EVERY vertex's "
                    "bone weights from its vertex groups (for weight "
                    "painting / re-rigging). OFF: existing vertices keep "
                    "their original weights byte-exact and only newly added "
                    "geometry is skinned from its groups",
        default=False
    )
    wd_recalculate_normals: bpy.props.BoolProperty(
        name="Recalculate Normals + Tangents",
        description="ON: recompute the full TBN frame from geometry — normal "
                    "from face angles, tangent + binormal from UV layout "
                    "(MikkTSpace). Use this after sculpting so normals and "
                    "the normal-map tangent space match the new vertex "
                    "positions. OFF (default): preserve the original authored "
                    "values for unchanged vertices; only newly added geometry "
                    "is recomputed regardless",
        default=False
    )
