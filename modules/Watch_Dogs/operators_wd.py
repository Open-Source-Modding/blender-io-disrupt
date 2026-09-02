"""Watch Dogs 1 / 2 — operators.

Split out of the monolithic __init__.py (2026-06-09 refactor).
"""
import os

import bpy

from .import_wd import load_wd_model as _wd_load


class XBG_OT_ImportWDSkeleton(bpy.types.Operator):
    """Import a Watch Dogs 1 .skeleton file as a standalone Blender armature."""
    bl_idname  = "xbg.import_wd_skeleton"
    bl_label   = "Import WD1 Skeleton"
    bl_description = (
        "Parse a Watch Dogs 1 .skeleton (nbCF binary format): reads all bone "
        "names, rest-pose quaternions and translations, builds an armature with "
        "the standard WD1 character hierarchy.  Compatible with MAB animation "
        "import and weight painting"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.skeleton", options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from .import_skeleton_wd import parse_wd1_skeleton, build_wd1_skeleton_armature
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "No valid .skeleton file selected")
            return {'CANCELLED'}
        try:
            name   = os.path.splitext(os.path.basename(self.filepath))[0]
            bones  = parse_wd1_skeleton(self.filepath)
            arm    = build_wd1_skeleton_armature(ctx, bones, name)
            arm['wd_skeleton_src'] = self.filepath
            self.report({'INFO'},
                f"WD1 skeleton: {len(bones)} bones -> {arm.name}")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to import .skeleton: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class XBG_OT_ImportWDHkx(bpy.types.Operator):
    """Import a Watch Dogs 1 .hkx collision file (64-bit Havok 2012)."""
    bl_idname  = "xbg.import_wd_hkx"
    bl_label   = "Import WD1 HKX Collision"
    bl_description = (
        "Read a Watch Dogs 1 .hkx Havok packfile (64-bit Havok 2012, e.g. "
        "vehicle physics) and build a wireframe convex-hull object for each "
        "collision shape, plus an editable box mesh for each hkpBoxShape.  "
        "Compressed triangle-mesh shapes are decoded into their exact "
        "triangle surface"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.hkx", options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from ..Havok.import_hkx_wd import import_hkx_wd
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "No valid .hkx file selected")
            return {'CANCELLED'}
        try:
            n_hulls, n_verts, n_meshes, n_boxes = import_hkx_wd(ctx, self.filepath)
            msg = (f"WD1 HKX: {n_hulls} convex hulls"
                   f" from {os.path.basename(self.filepath)}")
            if n_boxes:
                msg += f" + {n_boxes} box(es)"
            if n_meshes:
                msg += (f" + {n_meshes} collision mesh(es) reconstructed "
                        f"per-section from decoded vertices")
            msg += f" ({n_verts} verts)"
            self.report({'INFO'}, msg)
            return {'FINISHED'} if (n_hulls or n_meshes or n_boxes) else {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to import WD1 .hkx: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class XBG_OT_ImportWD2Hkx(bpy.types.Operator):
    """Import a Watch Dogs 2 .hkx collision file (Disrupt MOEG format)."""
    bl_idname  = "xbg.import_wd2_hkx"
    bl_label   = "Import WD2 HKX Collision"
    bl_description = (
        "Read a Watch Dogs 2 .hkx (Disrupt serialized Havok) and build one "
        "mesh object per convex collision shape. Physics-critical data "
        "round-trips bit-identically, so edited shapes can be injected back"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.hkx", options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from .import_hkx_wd2 import import_hkx_wd2
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "No valid .hkx file selected")
            return {'CANCELLED'}
        try:
            n_shapes, n_verts = import_hkx_wd2(ctx, self.filepath)
            self.report({'INFO'},
                f"WD2 HKX: {n_shapes} convex shapes "
                f"({n_verts} verts) from {os.path.basename(self.filepath)}")
            return {'FINISHED'} if n_shapes else {'CANCELLED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to import WD2 .hkx: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class XBG_OT_InjectWD2Hkx(bpy.types.Operator):
    """Write edited WD2 collision vertices back into a copy of the .hkx."""
    bl_idname  = "xbg.inject_wd2_hkx"
    bl_label   = "Inject WD2 HKX Collision"
    bl_description = (
        "Write edited vertices from selected imported WD2 collision shapes "
        "back into a copy of the source .hkx. VERTEX-DISPLACEMENT-ONLY: "
        "the vertex count (and order) must be preserved — move vertices, "
        "do not add or delete. Topology/connectivity is never touched, so "
        "the file stays game-safe"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.hkx", options={'HIDDEN'})
    check_existing: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    @classmethod
    def poll(cls, ctx):
        return any(o.get('wd2_hkx_shape_index') is not None
                   for o in ctx.selected_objects)

    def invoke(self, ctx, ev):
        objs = [o for o in ctx.selected_objects
                if o.get('wd2_hkx_shape_index') is not None]
        if objs and not self.filepath:
            src = objs[0]['wd2_hkx_src']
            base, ext = os.path.splitext(src)
            self.filepath = base + "_edited" + ext
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from .import_hkx_wd2 import inject_hkx_wd2
        objs = [o for o in ctx.selected_objects
                if o.get('wd2_hkx_shape_index') is not None]
        if not objs:
            self.report({'ERROR'},
                "Select imported WD2 collision shapes to inject")
            return {'CANCELLED'}
        srcs = {o['wd2_hkx_src'] for o in objs}
        if len(srcs) != 1:
            self.report({'ERROR'},
                "All selected shapes must come from the same .hkx file")
            return {'CANCELLED'}
        src = objs[0]['wd2_hkx_src']
        if not self.filepath:
            self.report({'ERROR'}, "Choose an output .hkx path")
            return {'CANCELLED'}
        try:
            injected = inject_hkx_wd2(ctx, src, objs, self.filepath)
            self.report({'INFO'},
                "WD2 HKX inject: %d shape(s), %d verts -> %s"
                % (len(injected), sum(v for _, v in injected),
                   os.path.basename(self.filepath)))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to inject WD2 .hkx: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class XBG_OT_InjectWDHkx(bpy.types.Operator):
    """Write edited WD1 collision shapes back into a copy of the .hkx."""
    bl_idname  = "xbg.inject_wd_hkx"
    bl_label   = "Inject WD1 HKX Collision"
    bl_description = (
        "Write edited vertices from selected imported WD1 collision shapes "
        "(convex hulls and boxes) back into a copy of the source .hkx. "
        "VERTEX-DISPLACEMENT-ONLY: the vertex count (and order) must be "
        "preserved — move vertices, do not add or delete. Connectivity and "
        "transform bytes are never touched, so the file stays game-safe"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.hkx", options={'HIDDEN'})
    check_existing: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    @classmethod
    def poll(cls, ctx):
        return any(o.get('wd_hkx_shape_off') is not None
                   and not o.get('wd_hkx_is_hull_reconstruction')
                   for o in ctx.selected_objects)

    def invoke(self, ctx, ev):
        objs = [o for o in ctx.selected_objects
                if o.get('wd_hkx_shape_off') is not None
                and not o.get('wd_hkx_is_hull_reconstruction')]
        if objs and not self.filepath:
            src = objs[0]['wd_hkx_src']
            base, ext = os.path.splitext(src)
            self.filepath = base + "_edited" + ext
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from .inject_hkx_wd import inject_hkx_wd
        objs = [o for o in ctx.selected_objects
                if o.get('wd_hkx_shape_off') is not None
                and not o.get('wd_hkx_is_hull_reconstruction')]
        if not objs:
            self.report({'ERROR'},
                "Select imported WD1 collision shapes to inject")
            return {'CANCELLED'}
        srcs = {o['wd_hkx_src'] for o in objs}
        if len(srcs) != 1:
            self.report({'ERROR'},
                "All selected shapes must come from the same .hkx file")
            return {'CANCELLED'}
        src = objs[0]['wd_hkx_src']
        if not self.filepath:
            self.report({'ERROR'}, "Choose an output .hkx path")
            return {'CANCELLED'}
        try:
            injected = inject_hkx_wd(ctx, src, objs, self.filepath)
            self.report({'INFO'},
                "WD1 HKX inject: %d shape(s), %d verts -> %s"
                % (len(injected), sum(v for _, v in injected),
                   os.path.basename(self.filepath)))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to inject WD1 .hkx: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class XBG_OT_ImportWD(bpy.types.Operator):
    """Import a Watch Dogs 1 .xbg (binary GEOM 97.50) model: skeleton,
    meshes, UVs, normals, skin weights."""
    bl_idname  = "xbg.import_wd_model"
    bl_label   = "Import Watch Dogs 1 Model"
    bl_description = (
        "Import a Watch Dogs 1 .xbg (binary GEOM 97.50) model with skeleton "
        "and skin weights"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    files: bpy.props.CollectionProperty(type=bpy.types.OperatorFileListElement)
    directory: bpy.props.StringProperty(subtype="DIR_PATH")
    filter_glob: bpy.props.StringProperty(default="*.xbg", options={'HIDDEN'})

    import_all_lods: bpy.props.BoolProperty(
        name="Import All LODs",
        description="Import every Level Of Detail present in the file "
                    "(one mesh set per LOD, named _LOD0/_LOD1/…)",
        default=False)
    lod_level: bpy.props.IntProperty(
        name="LOD Level",
        description="Which LOD to import. 0 = highest detail available; "
                    "higher = lower detail. (WD1 streams its very top LOD "
                    "externally, so level 0 is the best LOD in the file.) "
                    "Clamped to the lowest LOD present.",
        default=0, min=0, max=10)
    import_mesh_only: bpy.props.BoolProperty(
        name="Import Mesh Only",
        description="Skip the skeleton and skin binding — import geometry only",
        default=False)

    def draw(self, context):
        layout = self.layout
        box = layout.box()
        box.label(text="LOD Selection:", icon='MOD_MULTIRES')
        box.prop(self, "import_all_lods")
        row = box.row()
        row.enabled = not self.import_all_lods
        row.prop(self, "lod_level")
        if self.import_all_lods:
            box.label(text="Will import ALL LODs", icon='INFO')
        else:
            box.label(text="Will import LOD %d only" % self.lod_level,
                      icon='INFO')

        box = layout.box()
        box.label(text="Other Options:", icon='PREFERENCES')
        box.prop(self, "import_mesh_only")

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
        lod_sel = -1 if self.import_all_lods else self.lod_level
        ok = 0
        for fp in fs:
            try:
                model, arm = _wd_load(
                    ctx, fp, separate_primitives=sep,
                    lod_select=lod_sel,
                    import_mesh_only=self.import_mesh_only)
                nv = sum(len(m['verts']) for m in model['meshes'])
                navail = model.get('n_lods_available')
                lod_msg = ("LODs ALL" if self.import_all_lods
                           else "LOD %d" % min(self.lod_level,
                                               (navail or 1) - 1))
                self.report({'INFO'},
                    f"{os.path.basename(fp)}: {model['source'].upper()} "
                    f"[{lod_msg}] — {len(model['bones'])} bones, "
                    f"{len(model['meshes'])} meshes, {nv} verts")
                ok += 1
            except Exception as exc:
                self.report({'ERROR'}, f"{os.path.basename(fp)}: {exc}")
                import traceback; traceback.print_exc()
        return {'FINISHED'} if ok else {'CANCELLED'}



class XBG_OT_ImportWDMab(bpy.types.Operator):
    """Import a Watch Dogs 1 .mab animation (full rotation decode)."""
    bl_idname  = "xbg.import_wd_mab"
    bl_label   = "Import WD1 MAB"
    bl_description = (
        "Select an imported WD1 armature, then pick a .mab. Decodes the "
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
        from .import_mab_wd import parse_wd1_mab, apply_wd1_mab
        from .import_wd import parse_wd1_xbg
        arm = ctx.active_object
        if arm is None or arm.type != 'ARMATURE':
            arm = next((o for o in ctx.selected_objects
                        if o.type == 'ARMATURE'), None)
        if arm is None:
            self.report({'ERROR'}, "Select a WD1 armature first")
            return {'CANCELLED'}
        src = arm.get('xbg_source_file', '')
        if not src or not os.path.isfile(src):
            self.report({'ERROR'},
                "Armature has no source .xbg recorded — re-import the model "
                "(newer importer stores the path)")
            return {'CANCELLED'}
        try:
            mab = parse_wd1_mab(self.filepath)
            model = parse_wd1_xbg(src)
            _ds = ctx.scene.xbg_debug_settings
            applied, missing = apply_wd1_mab(
                ctx, mab, arm, model['bones'],
                smooth_resample=getattr(_ds, 'mab_smooth_resample', True),
                resample_fps=getattr(_ds, 'mab_resample_fps', 60),
                emulate_helpers=getattr(_ds, 'mab_emulate_helpers', True),
                twist_bake=getattr(_ds, 'mab_twist_bake', True))
            msg = (f"WD1 MAB: {applied} bones keyed "
                   f"({mab['n_animated']} animated + "
                   f"{len(mab['const_rots'])} constant), "
                   f"{len(mab['key_times'])} keyframes / "
                   f"{mab['duration']:.2f}s")
            if missing:
                msg += f"  ({len(missing)} bone hashes not on this rig)"
            self.report({'WARNING' if missing else 'INFO'}, msg)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to import WD1 .mab: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class XBG_OT_InjectWD(bpy.types.Operator):
    """Write edited WD1 mesh vertices back into the source .xbg (in place)."""
    bl_idname  = "xbg.inject_wd_model"
    bl_label   = "Inject WD1 Mesh"
    bl_description = (
        "Patch the selected WD1-imported meshes' edited vertex positions / "
        "normals / UVs / colors back into a copy of the source .xbg. "
        "Same vertex count patches in place; changed counts trigger a full "
        "buffer rebuild (add/remove geometry, re-skin, drop unselected)"
    )
    bl_options = {'REGISTER'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.xbg", options={'HIDDEN'})
    check_existing: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    def invoke(self, ctx, ev):
        objs = [o for o in ctx.selected_objects if o.get('wd_src')]
        if not objs:
            objs = [o for o in ctx.scene.objects if o.get('wd_src')]
        if objs and not self.filepath:
            src = objs[0]['wd_src']
            base, ext = os.path.splitext(src)
            self.filepath = base + "_edited" + ext
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from .inject_wd import inject_wd1_objects, rebuild_wd1_objects
        # The SELECTION is the keep-list: only the selected imported meshes
        # are written; unselected ones are DROPPED (their geometry is removed
        # — select all-but-the-eyes to bake a smaller eyeless head).  Select
        # nothing imported and it falls back to keeping every mesh.
        objs = [o for o in ctx.selected_objects if o.get('wd_src')]
        drop_mode = bool(objs)
        if not objs:
            objs = [o for o in ctx.scene.objects if o.get('wd_src')]
        if not objs:
            self.report({'ERROR'},
                "No WD1-imported meshes — import a Watch Dogs .xbg first")
            return {'CANCELLED'}
        src = objs[0]['wd_src']
        objs = [o for o in objs if o.get('wd_src') == src]
        if not self.filepath:
            self.report({'ERROR'}, "Choose an output .xbg path")
            return {'CANCELLED'}

        # New standalone objects (a fresh mesh you added, e.g. a second head)
        # carry no import metadata, so the injector can't place them on their
        # own.  Tell the user to JOIN them into an imported mesh first.
        new_objs = [o for o in ctx.selected_objects
                    if o.type == 'MESH' and not o.get('wd_src')
                    and not o.get('wd_joined')]
        if new_objs:
            self.report({'WARNING'},
                "%d new object(s) (%s) have no import data and will NOT be "
                "injected — join them (Ctrl+J) into an imported mesh, making "
                "the imported mesh the active object, then inject"
                % (len(new_objs), ", ".join(o.name for o in new_objs[:3])))
        reskin = bool(getattr(ctx.scene.xbg_debug_settings,
                              'wd_reskin_weights', False))
        recalc_norms = bool(getattr(ctx.scene.xbg_debug_settings,
                                    'wd_recalculate_normals', False))
        multibuffer = any(o.get('wd_multibuffer') for o in objs)
        # Streamed-LOD0 meshes (bytes in the companion .xbgmip) can only be
        # patched in place — the rebuild path repacks the .xbg's own buffers
        # and would leave the mip file inconsistent.
        has_mip = any(o.get('wd_mip_src') for o in objs)
        changed = any('wd_vcount' in o.keys()
                      and len(o.data.vertices) != int(o['wd_vcount'])
                      for o in objs if o.type == 'MESH')
        try:
            # Multi-buffer vehicles (helicopter, etc.): rebuild can't safely
            # repack their split buffers — force in-place only.
            if multibuffer or has_mip:
                if drop_mode or reskin:
                    self.report({'WARNING'},
                        "Multi-buffer vehicle: count changes, drop and "
                        "re-skin are not supported — using in-place inject")
                n_obj, n_vtx, warns = inject_wd1_objects(
                    objs, self.filepath, source_path=src,
                    recalculate_normals=recalc_norms)
                mode = ("in-place (multi-buffer)" if multibuffer
                        else "in-place (streamed LOD0)")
            elif drop_mode or changed or reskin:
                n_obj, n_vtx, warns = rebuild_wd1_objects(
                    objs, self.filepath, source_path=src, reskin=reskin,
                    drop_unselected=drop_mode,
                    recalculate_normals=recalc_norms)
                mode = "rebuild" + ("+reskin" if reskin else "")
            else:
                n_obj, n_vtx, warns = inject_wd1_objects(
                    objs, self.filepath, source_path=src,
                    recalculate_normals=recalc_norms)
                mode = "in-place"
            for w in warns:
                self.report({'WARNING'}, w)
                print("[WD1 inject]", w)
            self.report({'INFO'},
                "WD1 inject [%s]: %d meshes, %d verts -> %s%s"
                % (mode, n_obj, n_vtx, os.path.basename(self.filepath),
                   "  (%d notes — see console)" % len(warns) if warns else ""))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Failed to inject WD1 .xbg: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class XBG_OT_WDPeekLODs(bpy.types.Operator):
    """Quickly scan a WD1 .xbg to count how many LODs it contains."""
    bl_idname  = "xbg.wd_peek_lods"
    bl_label   = "Check WD1 LOD Count"
    bl_description = (
        "Scan a Watch Dogs 1 .xbg to show how many LOD levels it contains "
        "and how many are stored in the file vs streamed externally"
    )

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.xbg", options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from .import_wd import parse_wd1_xbg
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "No valid .xbg file selected")
            return {'CANCELLED'}
        try:
            m = parse_wd1_xbg(self.filepath)
            total = m.get('n_lods_total', 0)
            avail = m.get('n_lods_available', 0)
            skip  = m.get('lod_skip', 0)
            fn = os.path.basename(self.filepath)
            if skip:
                result = (f"{fn}: {total} LOD defs, {avail} in file "
                          f"(LOD 0-{skip-1} are external streams; "
                          f"file holds LOD {skip}-{total-1})")
            else:
                result = (f"{fn}: {total} LOD defs, all {avail} in file "
                          f"(LOD 0-{total-1})")
            ctx.scene.xbg_debug_settings.lod_peek_result = result
            self.report({'INFO'}, result)
        except Exception as e:
            result = f"Error: {e}"
            ctx.scene.xbg_debug_settings.lod_peek_result = result
            self.report({'WARNING'}, f"Could not read file: {e}")
        return {'FINISHED'}


class XBG_OT_ExportWD1(bpy.types.Operator):
    """Export selected mesh objects as a fresh Watch Dogs 1 .xbg (GEOM 97.50).

    Synthesises every section of the binary stream from Blender geometry —
    no source .xbg needed.  Each selected mesh becomes a submesh of a LOD.
    Assign ``lod_level`` (0–3) custom property to objects for multi-LOD
    export.  Position/UV are i16-quantised to the combined bounding box;
    the non-geometry sections (materials/skeleton/physics) are emitted
    minimal (empty physics/procedural, one material per object)."""
    bl_idname  = "xbg.export_wd1"
    bl_label   = "Export WD1 Model (.xbg)"
    bl_description = (
        "Write a fresh Watch Dogs 1 .xbg (GEOM 97.50) from the selected "
        "mesh objects"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.xbg", options={'HIDDEN'})
    lod_dists: bpy.props.StringProperty(
        name="LOD Distances",
        description="Comma-separated LOD distances",
        default="20, 30, 70, 300")
    n_lods: bpy.props.IntProperty(
        name="LOD Levels",
        description="Number of LOD levels to write (1 = single LOD)",
        default=1, min=1, max=4)

    @classmethod
    def poll(cls, ctx):
        return any(o.type == 'MESH' for o in ctx.selected_objects)

    def invoke(self, ctx, event):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        objs = [o for o in ctx.selected_objects if o.type == 'MESH']
        if not objs:
            self.report({'ERROR'}, "no mesh objects selected")
            return {'CANCELLED'}
        # Find armature: selected armature, or parent of first mesh
        arm = None
        for o in ctx.selected_objects:
            if o.type == 'ARMATURE':
                arm = o
                break
        if arm is None and objs:
            # Walk up parents to find an armature
            ob = objs[0]
            while ob.parent:
                if ob.parent.type == 'ARMATURE':
                    arm = ob.parent
                    break
                ob = ob.parent
        try:
            dists = [float(x.strip()) for x in self.lod_dists.split(',') if x.strip()]
        except ValueError:
            dists = [20.0, 30.0, 70.0, 300.0]
        if not dists:
            dists = [20.0, 30.0, 70.0, 300.0]
        path = self.filepath
        if not path.lower().endswith('.xbg'):
            path += '.xbg'
        try:
            import importlib
            mod = importlib.import_module(
                'blender-io-disrupt.modules.Watch_Dogs.export_wd1')
            n = mod.export_wd1(path, objs, lod_dists=dists, armature=arm,
                               n_lods=self.n_lods)
        except Exception as e:
            self.report({'ERROR'}, f"Failed to export WD1 .xbg: {e}")
            return {'CANCELLED'}
        if arm:
            self.report({'INFO'}, f"Exported WD1 .xbg: {n} mesh(es), skeleton from {arm.name} -> {path}")
        else:
            self.report({'INFO'}, f"Exported WD1 .xbg: {n} mesh(es) -> {path}")
        return {'FINISHED'}


class XBG_OT_WDSyncNormals(bpy.types.Operator):
    """Bake Blender geometry normals into xbg_normal so injection writes
    normals that match the sculpted/edited mesh shape."""
    bl_idname  = "xbg.wd_sync_normals"
    bl_label   = "Sync Normals from Geometry"
    bl_description = (
        "After sculpting or moving vertices, run this to bake Blender's "
        "computed normals into the xbg_normal attribute.  The next injection "
        "will then write normals that match the new vertex positions."
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, ctx):
        return (ctx.active_object is not None
                and ctx.active_object.type == 'MESH')

    def execute(self, ctx):
        from .inject_wd import sync_normals_to_geometry
        count = 0
        for obj in ctx.selected_objects:
            if obj.type == 'MESH' and obj.get('wd_src'):
                n = sync_normals_to_geometry(obj)
                count += n
        if count:
            self.report({'INFO'},
                f"Synced normals for {count} vertices "
                f"across {len(ctx.selected_objects)} object(s)")
        else:
            self.report({'WARNING'},
                "No WD1-imported meshes selected "
                "(import a Watch Dogs .xbg first)")
        return {'FINISHED'}


class XBG_OT_WDStampMetadata(bpy.types.Operator):
    """Re-parse the source .xbg and fill in missing wd_* properties
    on selected objects (preserves all geometry edits)."""
    bl_idname  = "xbg.wd_stamp_metadata"
    bl_label   = "Stamp Import Metadata"
    bl_description = (
        "For objects imported with an older addon version that are missing "
        "wd_scale / wd_vb_off / etc: re-parses the source .xbg and stamps "
        "all injection metadata so inject/rebuild works again. "
        "Your geometry edits are NOT touched."
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, ctx):
        return any(o.type == 'MESH' and o.get('wd_src')
                   for o in ctx.selected_objects)

    def execute(self, ctx):
        from .import_wd import parse_wd1_xbg

        REQUIRED = ('wd_scale', 'wd_vb_off', 'wd_stride',
                     'wd_format', 'wd_vcount', 'wd_mesh_index',
                     'wd_buf0_off')
        objs = [o for o in ctx.selected_objects
                if o.type == 'MESH' and o.get('wd_src')]
        if not objs:
            self.report({'WARNING'},
                "No WD1-imported meshes selected")
            return {'CANCELLED'}

        # group by source file
        by_src = {}
        for o in objs:
            by_src.setdefault(o['wd_src'], []).append(o)

        stamped = 0
        for src, src_objs in by_src.items():
            try:
                model = parse_wd1_xbg(src)
            except Exception as e:
                self.report({'ERROR'},
                    f"Failed to parse {os.path.basename(src)}: {e}")
                continue
            L = model['_layout']
            off = list(L['scale'])
            lod0 = L.get('lod0_meshes', [])

            for ob in src_objs:
                # already fully stamped?
                if all(k in ob for k in REQUIRED):
                    continue
                mi = int(ob.get('wd_mesh_index', -1))
                if 0 <= mi < len(lod0):
                    mesh_info = lod0[mi]
                    dc = mesh_info['drawcall']
                    ob['wd_scale'] = off
                    ob['wd_vb_off'] = dc['vb_offset']
                    ob['wd_stride'] = mesh_info['stride']
                    ob['wd_format'] = mesh_info['format']
                    ob['wd_vcount'] = dc['vertex_count']
                    ob['wd_mesh_index'] = mi
                    ob['wd_buf0_off'] = L.get('vdata0_off', 0)
                    stamped += 1
                else:
                    self.report({'WARNING'},
                        f"{ob.name}: mesh_index {mi} not found "
                        f"in {os.path.basename(src)} — skipped")

        if stamped:
            self.report({'INFO'},
                f"Stamped import metadata on {stamped} object(s) "
                f"({len(by_src)} source file(s))")
        else:
            self.report({'WARNING'},
                "No objects needed stamping "
                "(all already have metadata, or no matches found)")
        return {'FINISHED'}


# ── Material import/export operators ────────────────────────────────────────


class XBG_OT_ImportWDMaterial(bpy.types.Operator):
    """Import a Watch Dogs .material.bin as a Blender Cycles/Eevee material."""
    bl_idname  = "xbg.import_wd_material"
    bl_label   = "Import WD Material (.material.bin)"
    bl_description = (
        "Parse a Disrupt engine .material.bin (TAM v7/v15): map known PBR "
        "params to Principled BSDF inputs, store game-specific parameters "
        "as custom properties for round-trip export"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(
        default="*.material.bin", options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from .material_editor_wd import material_from_bin
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "No valid .material.bin file selected")
            return {'CANCELLED'}
        try:
            me, shader = material_from_bin(self.filepath)
            if me is None:
                self.report({'ERROR'}, "Failed to create material")
                return {'CANCELLED'}
            self.report({'INFO'},
                f"Imported material '{me.name}' (shader: {shader})")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Material import failed: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


class XBG_OT_ExportWDMaterial(bpy.types.Operator):
    """Export the active Blender material to a Watch Dogs .material.bin file."""
    bl_idname  = "xbg.export_wd_material"
    bl_label   = "Export WD Material (.material.bin)"
    bl_description = (
        "Write the active material's Principled BSDF values and custom "
        "properties back to a Disrupt .material.bin (TAM v7) file"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(
        default="*.material.bin", options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        from .material_editor_wd import material_to_bin
        mat = ctx.active_object.active_material if ctx.active_object else None
        if mat is None:
            self.report({'ERROR'}, "No active material to export")
            return {'CANCELLED'}
        try:
            material_to_bin(mat, self.filepath)
            self.report({'INFO'},
                f"Exported material '{mat.name}' -> {os.path.basename(self.filepath)}")
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, f"Material export failed: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}


# ── MAC / Markup Import ─────────────────────────────────────────────────────

class XBG_OT_ImportWDMac(bpy.types.Operator):
    """Import a Watch Dogs 1 .mac animation clip with optional .markup events."""
    bl_idname  = "xbg.import_wd_mac"
    bl_label   = "Import WD1 MAC Animation"
    bl_description = (
        "Parse a Watch Dogs 1 .mac (AnimationMarkupTool binary clip) and "
        "build a Blender action with rotation/translation/scale curves on "
        "the active armature.  Optionally loads the matching .markup XML "
        "for game event markers"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.mac", options={'HIDDEN'})
    load_markup: bpy.props.BoolProperty(
        name="Load Markup",
        description="Also load the matching .markup XML file if found",
        default=True,
    )

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        import os
        from .parse_mac import parse_mac, parse_markup

        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "No valid .mac file selected")
            return {'CANCELLED'}

        try:
            af = parse_mac(self.filepath)
        except Exception as exc:
            self.report({'ERROR'}, f"MAC parse failed: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}

        # Find matching armature
        arm_obj = None
        if ctx.active_object and ctx.active_object.type == 'ARMATURE':
            arm_obj = ctx.active_object
        else:
            for obj in ctx.selected_objects:
                if obj.type == 'ARMATURE':
                    arm_obj = obj
                    break

        if arm_obj is None:
            self.report({'WARNING'},
                f"MAC loaded: {af.type_id.value}, {len(af.skeleton.bones)} bones, "
                f"{len(af.anim_parts)} parts — no armature selected, skipping action build")
            return {'FINISHED'}

        # Build action from skeleton curves
        action = self._build_action(ctx, arm_obj, af)
        if action is None:
            self.report({'WARNING'},
                f"MAC parsed but no bone curves matched armature '{arm_obj.name}'")
            return {'FINISHED'}

        # Optionally load markup
        markup_doc = None
        if self.load_markup:
            markup_path = os.path.splitext(self.filepath)[0] + '.markup'
            if os.path.isfile(markup_path):
                try:
                    markup_doc = parse_markup(markup_path)
                except Exception:
                    pass

        n_events = len(markup_doc.events) if markup_doc else 0
        self.report({'INFO'},
            f"MAC: {af.type_id.value} | {len(af.skeleton.bones)} bones, "
            f"{len(action.fcurves)} fcurves, {len(af.anim_parts)} parts"
            + (f" | {n_events} markup events" if n_events else ""))
        return {'FINISHED'}

    def _build_action(self, ctx, arm_obj, af):
        """Build a Blender Action from parsed MAC curves."""
        import mathutils

        if not af.skeleton.bones:
            return None

        # Map MAC bone names to armature pose bones
        pb_map = {}
        for bone in af.skeleton.bones:
            name = bone.name.value
            if name in arm_obj.pose.bones:
                pb_map[bone.name.value] = (bone, arm_obj.pose.bones[name])

        if not pb_map:
            return None

        # Create action
        action_name = af.type_id.value or os.path.splitext(
            os.path.basename(self.filepath))[0]
        action = bpy.data.actions.new(name=action_name)
        if arm_obj.animation_data is None:
            arm_obj.animation_data_create()
        arm_obj.animation_data.action = action

        # Determine frame range from curve values
        max_frames = 0
        for bone, pb in pb_map.values():
            for curve in bone.curves:
                if curve.values:
                    max_frames = max(max_frames, len(curve.values))

        if max_frames == 0:
            return action

        # Build fcurves for each bone
        # Curve type -> (property, index)
        TYPE_MAP = {
            0: ('rotation_euler', 0),   # RotX
            1: ('rotation_euler', 1),   # RotY
            2: ('rotation_euler', 2),   # RotZ
            3: ('location', 0),         # TransX
            4: ('location', 1),         # TransY
            5: ('location', 2),         # TransZ
            6: ('scale', 0),            # ScaleX
            7: ('scale', 1),            # ScaleY
            8: ('scale', 2),            # ScaleZ
        }

        for bone_name, (mac_bone, pb) in pb_map.items():
            pb.rotation_mode = 'EULER'
            base_path = f'pose.bones["{bone_name}"]'

            for curve in mac_bone.curves:
                if not curve.values:
                    continue
                prop_idx = TYPE_MAP.get(curve.curve_type)
                if prop_idx is None:
                    continue
                prop, idx = prop_idx
                fc = action.fcurves.new(f'{base_path}.{prop}', index=idx)
                fc.keyframe_points.add(len(curve.values))
                flat = []
                for i, v in enumerate(curve.values):
                    flat.append(float(i + 1))  # 1-based frames
                    flat.append(v)
                fc.keyframe_points.foreach_set('co', flat)
                fc.update()

        return action


class XBG_OT_ImportWDMarkup(bpy.types.Operator):
    """Import a Watch Dogs 1 .markup event file as markers on the timeline."""
    bl_idname  = "xbg.import_wd_markup"
    bl_label   = "Import WD1 Markup Events"
    bl_description = (
        "Parse a Watch Dogs 1 .markup XML and add timeline markers for "
        "each game event (e.g. inPossession, IKPath, Anchor)"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.markup", options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        import os
        from .parse_mac import parse_markup

        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "No valid .markup file selected")
            return {'CANCELLED'}

        try:
            doc = parse_markup(self.filepath)
        except Exception as exc:
            self.report({'ERROR'}, f"Markup parse failed: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}

        if not doc.events:
            self.report({'INFO'}, "Markup file has no events")
            return {'FINISHED'}

        scene = ctx.scene
        fps = scene.render.fps or 30

        # Add markers for each event
        for ev in doc.events:
            frame = int(round(ev.time * fps))
            marker = scene.timeline_markers.new(name=ev.name, frame=frame)

        self.report({'INFO'},
            f"Markup: {len(doc.events)} events placed as timeline markers")
        return {'FINISHED'}
