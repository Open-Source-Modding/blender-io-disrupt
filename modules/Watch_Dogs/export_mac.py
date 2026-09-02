"""Watch Dogs 1 / 2 — MAC + Markup export operators.

Exports Blender armature animations to Disrupt engine MAC (Mesh Animation
Clip) binary format and timeline markers to .markup XML.

Format reference: animation_parser.py + .opencode/docs/animation_markup_format.md
"""

import os

import bpy
from bpy.props import StringProperty, FloatProperty, BoolProperty
from bpy_extras.io_utils import ExportHelper


# ─── MAC Export Operator ─────────────────────────────────────────────────────

class MAC_OT_Export(bpy.types.Operator, ExportHelper):
    """Export an armature animation to a Disrupt engine MAC file."""
    bl_idname = "mac.export_animation"
    bl_label = "Export MAC Animation"
    bl_description = (
        "Export the active armature's action as a Disrupt engine MAC "
        "(Mesh Animation Clip) binary file with rotation/translation/scale "
        "curves on each bone"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".mac"
    filter_glob: StringProperty(default="*.mac", options={'HIDDEN'})

    frame_rate: FloatProperty(
        name="Frame Rate",
        description="Animation sample rate in frames per second",
        default=30.0, min=1.0, max=120.0,
    )
    anim_type: StringProperty(
        name="Animation Type",
        description="StringID type name for this animation "
                    "(e.g. 'walk', 'idle', 'attack01')",
        default="exported",
    )
    export_markup: BoolProperty(
        name="Export Markup",
        description="Also export timeline markers as a .markup XML file "
                    "alongside the MAC",
        default=True,
    )

    @classmethod
    def poll(cls, ctx):
        obj = ctx.active_object
        if obj and obj.type == 'ARMATURE':
            return True
        return any(o.type == 'ARMATURE' for o in ctx.selected_objects)

    def execute(self, ctx):
        from .animation_parser import (
            AnimationFile, StringID, AnimSkeleton, AnimBone,
            AnimDirNode, AnimMomentum, AnimCurve, AnimDiscreteCurve,
            write_mac, write_markup, MarkupDocument, MarkupEvent,
        )

        # Find armature
        arm = None
        if ctx.active_object and ctx.active_object.type == 'ARMATURE':
            arm = ctx.active_object
        else:
            for o in ctx.selected_objects:
                if o.type == 'ARMATURE':
                    arm = o
                    break
        if arm is None:
            self.report({'ERROR'}, "No armature selected")
            return {'CANCELLED'}

        # Get action
        action = arm.animation_data.action if arm.animation_data else None
        if action is None:
            self.report({'ERROR'},
                f"Armature '{arm.name}' has no active action to export")
            return {'CANCELLED'}

        fps = self.frame_rate

        # Build AnimationFile
        af = AnimationFile()
        af.version_legacy = 9.0
        af.file_version = 9
        af.exporter_major = 2
        af.exporter_minor = 2
        af.type_id = StringID(type_id=0, value=self.anim_type)
        af.frame_rate = fps

        # Build skeleton from armature bones
        sk = AnimSkeleton()
        bone_map = {}  # bone_name -> (mac_bone, bone_index)

        for i, bone in enumerate(arm.data.bones):
            mb = AnimBone()
            mb.name = StringID(type_id=0, value=bone.name)
            mb.bone_id = i
            if bone.parent:
                # Find parent index
                parent_idx = None
                for j, b in enumerate(arm.data.bones):
                    if b.name == bone.parent.name:
                        parent_idx = j
                        break
                mb.parent_id = parent_idx if parent_idx is not None else -1
            else:
                mb.parent_id = -1
            bone_map[bone.name] = (mb, i)
            sk.bones.append(mb)

        # Sample keyframes for each bone
        frame_start = int(action.frame_range[0])
        frame_end = int(action.frame_range[1])
        n_frames = frame_end - frame_start + 1

        if n_frames <= 0:
            self.report({'ERROR'}, "Action has no keyframes")
            return {'CANCELLED'}

        # Curve type mapping: Blender data_path suffix + array_index -> CurveDataType
        # RotX=0, RotY=1, RotZ=2, TransX=3, TransY=4, TransZ=5,
        # ScaleX=6, ScaleY=7, ScaleZ=8
        CURVE_MAP = {
            ('rotation_euler', 0): 0,  # RotX
            ('rotation_euler', 1): 1,  # RotY
            ('rotation_euler', 2): 2,  # RotZ
            ('location', 0): 3,        # TransX
            ('location', 1): 4,        # TransY
            ('location', 2): 5,        # TransZ
            ('scale', 0): 6,           # ScaleX
            ('scale', 1): 7,           # ScaleY
            ('scale', 2): 8,           # ScaleZ
        }

        # Collect FCurves by bone
        for fc in action.fcurves:
            # Parse data_path: pose.bones["BoneName"].property
            dp = fc.data_path
            if not dp.startswith('pose.bones["'):
                continue
            # Extract bone name and property
            parts = dp.split('"')
            if len(parts) < 3:
                continue
            bone_name = parts[1]
            prop_part = parts[2]  # e.g. .rotation_euler
            if prop_part.startswith('.'):
                prop_part = prop_part[1:]

            if bone_name not in bone_map:
                continue

            key = (prop_part, fc.array_index)
            curve_type = CURVE_MAP.get(key)
            if curve_type is None:
                continue

            mac_bone, _ = bone_map[bone_name]

            # Sample values at each frame
            values = []
            for fr in range(frame_start, frame_end + 1):
                values.append(fc.evaluate(fr))

            adc = AnimDiscreteCurve(curve_type=curve_type, values=values)
            mac_bone.curves.append(adc)

        af.skeleton = sk

        # Set frame range on the armature for reference
        af.dir_node = AnimDirNode()
        af.momentum = AnimMomentum()

        # Write MAC
        path = self.filepath
        if not path.lower().endswith('.mac'):
            path += '.mac'

        try:
            write_mac(path, af)
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to write MAC: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}

        n_bones = len(sk.bones)
        n_curves = sum(len(b.curves) for b in sk.bones)
        n_sampled = sum(sum(len(c.values) for c in b.curves)
                       for b in sk.bones)

        msg = (f"MAC: {self.anim_type} — {n_bones} bones, "
               f"{n_curves} curves, {n_sampled} values "
               f"({n_frames} frames @ {fps}fps) -> {os.path.basename(path)}")

        # Optionally export markup from timeline markers
        if self.export_markup:
            markers = ctx.scene.timeline_markers
            if markers:
                doc = MarkupDocument()
                for m in markers:
                    t = (m.frame - frame_start) / fps
                    if t < 0:
                        t = 0.0
                    doc.events.append(MarkupEvent(
                        time=t,
                        name=m.name,
                        track="",
                        event_type="",
                    ))
                markup_path = os.path.splitext(path)[0] + '.markup'
                try:
                    write_markup(markup_path, doc)
                    msg += f" | {len(doc.events)} markers -> {os.path.basename(markup_path)}"
                except Exception as exc:
                    self.report({'WARNING'},
                        f"MAC written but markup export failed: {exc}")

        self.report({'INFO'}, msg)
        return {'FINISHED'}


# ─── Markup Export Operator ──────────────────────────────────────────────────

class MAC_OT_ExportMarkup(bpy.types.Operator, ExportHelper):
    """Export timeline markers to a .markup XML event file."""
    bl_idname = "mac.export_markup"
    bl_label = "Export Markup Events"
    bl_description = (
        "Export Blender timeline markers as a Watch Dogs .markup XML "
        "file with time-stamped game events"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".markup"
    filter_glob: StringProperty(default="*.markup", options={'HIDDEN'})

    frame_rate: FloatProperty(
        name="Frame Rate",
        description="Frame rate for converting frames to seconds",
        default=30.0, min=1.0, max=120.0,
    )

    def execute(self, ctx):
        from .animation_parser import (
            write_markup, MarkupDocument, MarkupEvent,
        )

        markers = ctx.scene.timeline_markers
        if not markers:
            self.report({'WARNING'}, "No timeline markers to export")
            return {'CANCELLED'}

        fps = self.frame_rate
        doc = MarkupDocument()
        for m in markers:
            t = m.frame / fps
            if t < 0:
                t = 0.0
            doc.events.append(MarkupEvent(
                time=t,
                name=m.name,
                track="",
                event_type="",
            ))

        path = self.filepath
        if not path.lower().endswith('.markup'):
            path += '.markup'

        try:
            write_markup(path, doc)
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to write markup: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}

        self.report({'INFO'},
            f"Markup: {len(doc.events)} events -> {os.path.basename(path)}")
        return {'FINISHED'}


# ─── Registration ────────────────────────────────────────────────────────────

_classes = (
    MAC_OT_Export,
    MAC_OT_ExportMarkup,
)


def register():
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        try:
            bpy.utils.unregister_class(c)
        except RuntimeError:
            pass
