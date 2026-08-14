"""Watch Dogs Legion — operators (import + inject; self-contained)."""
import os

import bpy
import mathutils

from .import_wdl_xbg import load_wdl_xbg


class XBG_OT_ImportWDL(bpy.types.Operator):
    """Import a Watch Dogs Legion compiled .xbg model: skeleton, meshes, UVs."""
    bl_idname  = "xbg.import_wdl_model"
    bl_label   = "Import Watch Dogs Legion Model"
    bl_description = (
        "Import a Watch Dogs Legion compiled .xbg "
        "(MOEG binary) model with skeleton and skin weights"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    filter_glob: bpy.props.StringProperty(default="*.xbg", options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        fs = []
        if self.files:
            for f in self.files:
                if f.name.lower().endswith('.xbg'):
                    fs.append(os.path.join(self.directory, f.name))
        elif self.filepath:
            fs.append(self.filepath)
        if not fs:
            self.report({'ERROR'}, "No .xbg file selected")
            return {'CANCELLED'}

        sep = bool(getattr(ctx.scene.xbg_debug_settings,
                           'separate_primitives', True))
        ok = 0
        for fp in fs:
            try:
                model, arm = load_wdl_xbg(ctx, fp,
                                          separate_primitives=sep)
                nv = sum(len(m['verts']) for m in model['meshes'])
                self.report({'INFO'},
                    f"{os.path.basename(fp)}: WDL — "
                    f"{len(model['bones'])} bones, "
                    f"{len(model['meshes'])} meshes, {nv} verts")
                ok += 1
            except Exception as exc:
                self.report({'ERROR'}, f"{os.path.basename(fp)}: {exc}")
                import traceback; traceback.print_exc()
        return {'FINISHED'} if ok else {'CANCELLED'}


class XBG_OT_InjectWDL(bpy.types.Operator):
    """Inject edited WDL meshes back into a copy of the source .xbg."""
    bl_idname  = "xbg.inject_wdl_model"
    bl_label   = "Inject Watch Dogs Legion Mesh"
    bl_description = (
        "Write the selected WDL-imported meshes back into a copy of the "
        "source .xbg (in-place vertex patching — position/UV edits only, "
        "vertex count must match the original)"
    )
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.xbg", options={'HIDDEN'})
    check_existing: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, ctx, ev):
        objs = [o for o in ctx.selected_objects if o.get('wdl_src')]
        if not objs:
            objs = [o for o in ctx.scene.objects if o.get('wdl_src')]
        if objs and not self.filepath:
            src = objs[0]['wdl_src']
            base, ext = os.path.splitext(src)
            self.filepath = base + "_patched" + ext
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from .inject_wdl import inject_wdl_objects
        objs = [o for o in ctx.selected_objects if o.get('wdl_src')]
        if not objs:
            objs = [o for o in ctx.scene.objects if o.get('wdl_src')]
        try:
            n_obj, n_vtx, warns = inject_wdl_objects(objs, self.filepath)
        except Exception as exc:
            self.report({'ERROR'}, f"WDL inject failed: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}
        for w in warns:
            self.report({'WARNING'}, w)
        self.report({'INFO'},
            f"WDL inject: {n_obj} meshes, {n_vtx} verts -> "
            f"{os.path.basename(self.filepath)}")
        return {'FINISHED'}


class XBG_OT_ImportWDLSkeleton(bpy.types.Operator):
    """Import a standalone WDL .skel file as a Blender armature."""
    bl_idname  = "xbg.import_wdl_skeleton"
    bl_label   = "Import WDL Skeleton"
    bl_description = (
        "Import a Watch Dogs Legion .skel file as a standalone Blender armature"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.skel", options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from .import_wdl_xbg import parse_wdl_skel
        try:
            bones = parse_wdl_skel(self.filepath)
            if not bones:
                self.report({'WARNING'},
                    f"No bones found in {os.path.basename(self.filepath)}")
                return {'CANCELLED'}

            arm_data = bpy.data.armatures.new(
                os.path.splitext(os.path.basename(self.filepath))[0])
            arm_obj = bpy.data.objects.new(arm_data.name, arm_data)
            ctx.collection.objects.link(arm_obj)
            ctx.view_layer.objects.active = arm_obj
            arm_obj.select_set(True)

            bpy.ops.object.mode_set(mode='EDIT')
            edit_bones = arm_data.edit_bones

            # First pass: create all bones
            for bd in bones:
                eb = edit_bones.new(bd['name'])
                eb['skel_index'] = bones.index(bd)

            # Second pass: set parents and transforms
            for i, bd in enumerate(bones):
                eb = edit_bones[bd['name']]
                pid = bd['parent']
                if 0 <= pid < len(bones):
                    eb.parent = edit_bones[bones[pid]['name']]

                # Local transform from parent
                pos = mathutils.Vector(bd['pos'])
                quat = mathutils.Quaternion(bd['quat'])
                eb.head = pos
                eb.tail = pos + mathutils.Vector((0, 0.01, 0))
                eb.matrix = mathutils.Matrix.LocRotScale(
                    pos, quat, None)

            bpy.ops.object.mode_set(mode='OBJECT')

            self.report({'INFO'},
                f"Imported {len(bones)} bones from "
                f"{os.path.basename(self.filepath)}")
        except Exception as exc:
            self.report({'ERROR'}, f"Skeleton import failed: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}
        return {'FINISHED'}


class XBG_OT_ImportWDLMab(bpy.types.Operator):
    """Import a Watch Dogs Legion .mab animation onto a WDL armature."""
    bl_idname  = "xbg.import_wdl_mab"
    bl_label   = "Import WDL MAB"
    bl_description = (
        "Select an imported WDL armature, then pick a .mab. Decodes the "
        "constant-pose bones AND the compressed per-keyframe rotation "
        "bitstream (DisruptEditor codec) and keys every animated bone"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.mab", options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from .import_mab_wdl import parse_wdl_mab
        from ..Watch_Dogs.import_mab_wd import apply_wd1_mab
        from .import_wdl_xbg import parse_wdl_xbg

        arm = ctx.active_object
        if arm is None or arm.type != 'ARMATURE':
            arm = next((o for o in ctx.selected_objects
                        if o.type == 'ARMATURE'), None)
        if arm is None:
            self.report({'ERROR'}, "Select a WDL armature first")
            return {'CANCELLED'}

        src = arm.get('wdl_src', '')
        if not src or not os.path.isfile(src):
            self.report({'ERROR'},
                "Armature has no source .xbg recorded — re-import the model "
                "(the WDL importer stores the path)")
            return {'CANCELLED'}

        try:
            mab = parse_wdl_mab(self.filepath)
            model = parse_wdl_xbg(src)
            _ds = ctx.scene.xbg_debug_settings
            applied, missing = apply_wd1_mab(
                ctx, mab, arm, model['bones'],
                smooth_resample=getattr(_ds, 'mab_smooth_resample', True),
                resample_fps=getattr(_ds, 'mab_resample_fps', 60),
                emulate_helpers=getattr(_ds, 'mab_emulate_helpers', True),
                twist_bake=getattr(_ds, 'mab_twist_bake', True))
            msg = (f"WDL MAB: {applied} bones keyed "
                   f"({mab['n_animated']} animated + "
                   f"{len(mab['const_rots'])} constant), "
                   f"{len(mab['key_times'])} keyframes / "
                   f"{mab['duration']:.2f}s")
            if missing:
                msg += f"  ({len(missing)} bone hashes not on this rig)"
            self.report({'WARNING' if missing else 'INFO'}, msg)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to import WDL .mab: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}
