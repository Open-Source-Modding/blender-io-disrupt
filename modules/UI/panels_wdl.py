"""Watch Dogs Legion — UI panels (children of OBJECT_PT_xbg_wdl in main.py)."""

import bpy

from .main import active_game


def _adv(ctx):
    return ctx.scene.xbg_debug_settings.advanced_mode


# ── Import ──────────────────────────────────────────────────────────────────

class XBG_PT_WDLImport(bpy.types.Panel):
    """Import a Watch Dogs Legion model into Blender."""
    bl_label = "Import XBG"
    bl_idname = "OBJECT_PT_xbg_wdl_import"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "XBG Import"
    bl_parent_id = "OBJECT_PT_xbg_wdl"

    def draw_header(self, ctx):
        self.layout.label(icon='IMPORT')

    def draw(self, ctx):
        l = self.layout
        ds = ctx.scene.xbg_debug_settings

        r = l.row()
        r.scale_y = 1.8
        r.operator("xbg.import_wdl_model",
                   text="   Import WDL Model (.xbg)", icon='IMPORT')
        col = l.column(align=True)
        col.label(text="Compiled MOEG binary + .skel", icon='FILE_CACHE')
        col.label(text="Skeleton · weights · UVs · materials")

        l.separator()
        r2 = l.row()
        r2.scale_y = 1.3
        r2.operator("xbg.import_wdl_skeleton",
                    text="Import WDL Skeleton (.skel)", icon='ARMATURE_DATA')

        if _adv(ctx):
            l.separator()
            b = l.box()
            b.label(text="Import options:", icon='TOOL_SETTINGS')
            b.prop(ds, "separate_primitives",
                   text="Separate Primitives (needed to inject)")
            if not ds.separate_primitives:
                note = b.column(align=True)
                note.scale_y = 0.8
                note.label(text="OFF: submeshes joined into one object",
                           icon='INFO')
                note.label(text="(clean view; can't be injected back).")
        else:
            l.label(text="Enable Advanced Mode for editing / injection.",
                    icon='INFO')


# ── Edit & Inject ───────────────────────────────────────────────────────────

class XBG_PT_WDLInject(bpy.types.Panel):
    """Inject your edited mesh back into the XBG file."""
    bl_label = "Inject / Export"
    bl_idname = "OBJECT_PT_xbg_wdl_inject"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "XBG Import"
    bl_parent_id = "OBJECT_PT_xbg_wdl"

    @classmethod
    def poll(cls, ctx):
        return _adv(ctx) and active_game(ctx) == 'WD3'

    def draw_header(self, ctx):
        self.layout.label(icon='EXPORT')

    def draw(self, ctx):
        l = self.layout
        ds = ctx.scene.xbg_debug_settings

        joined = [o for o in ctx.selected_objects if o.get('wd_joined')]
        if joined:
            w = l.box()
            w.alert = True
            w.label(text="This mesh was imported JOINED.", icon='ERROR')
            w.label(text="Turn on Separate Primitives and")
            w.label(text="re-import to edit & inject it.")
        l.label(text="Edit imported meshes (Edit Mode: add /")
        l.label(text="delete / move verts), then:")
        l.separator()
        r = l.row()
        r.scale_y = 1.8
        r.enabled = any(o.get('wdl_src') for o in ctx.scene.objects)
        r.operator("xbg.inject_wdl_model",
                   text="   Inject WDL Mesh (.xbg)", icon='EXPORT')
        col = l.column(align=True)
        col.scale_y = 0.8
        nsel = len([o for o in ctx.selected_objects if o.get('wdl_src')])
        if nsel:
            col.label(text="SELECTION = keep-list: only selected", icon='RESTRICT_SELECT_OFF')
            col.label(text="meshes are written; unselected ones are")
            col.label(text="DROPPED (smaller file — e.g. select all")
            col.label(text="but the eyes for an eyeless head).")
        else:
            col.label(text="Nothing selected → ALL meshes written.", icon='INFO')
            col.label(text="Select a subset to drop the rest.")
        col.separator()
        col.label(text="New object (2nd head)? Join it (Ctrl+J)", icon='INFO')
        col.label(text="into an imported mesh first — a loose")
        col.label(text="object has no place in the file.")


# ── Model Info ──────────────────────────────────────────────────────────────

class XBG_PT_WDLModelInfo(bpy.types.Panel):
    """What the importer captured on the active mesh."""
    bl_label = "Model Info"
    bl_idname = "OBJECT_PT_xbg_wdl_info"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "XBG Import"
    bl_parent_id = "OBJECT_PT_xbg_wdl"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, ctx):
        o = ctx.active_object
        return o is not None and o.type == 'MESH'

    def draw_header(self, ctx):
        self.layout.label(icon='INFO')

    def draw(self, ctx):
        l = self.layout
        o = ctx.active_object
        me = o.data

        box = l.box()
        col = box.column(align=True)
        col.label(text=o.name, icon='MESH_DATA')
        col.label(text=f"{len(me.vertices)} verts · {len(me.polygons)} tris")

        arm = next((m.object for m in o.modifiers
                    if m.type == 'ARMATURE' and m.object), None)
        if arm:
            col.label(text=f"Skeleton: {arm.name} "
                           f"({len(arm.data.bones)} bones)", icon='ARMATURE_DATA')
        if o.vertex_groups:
            col.label(text=f"{len(o.vertex_groups)} weighted bone groups",
                      icon='GROUP_VERTEX')

        if me.uv_layers:
            col.label(text="UV: " + ", ".join(uv.name for uv in me.uv_layers),
                      icon='UV')

        attrs = me.attributes
        comps = []
        if 'Col' in attrs:
            comps.append("vertex colors")
        if 'xbg_normal' in attrs:
            comps.append("normals")
        if 'xbg_tangent' in attrs:
            comps.append("tangents")
        if 'xbg_binormal' in attrs:
            comps.append("binormals")
        if comps:
            col.label(text="Captured: " + ", ".join(comps), icon='CHECKMARK')


# ── Animation ────────────────────────────────────────────────────────────────

class XBG_PT_WDLAnimation(bpy.types.Panel):
    """Import a WDL .mab animation onto a WDL armature."""
    bl_label = "Animation"
    bl_idname = "OBJECT_PT_xbg_wdl_anim"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "XBG Import"
    bl_parent_id = "OBJECT_PT_xbg_wdl"
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, ctx):
        from .main import active_game
        return active_game(ctx) == 'WD3'

    def draw_header(self, ctx):
        self.layout.label(icon='ARMATURE_DATA')

    def draw(self, ctx):
        l = self.layout
        l.label(text="Animation (.mab) — select armature first:",
                icon='ANIM_DATA')
        ds = ctx.scene.xbg_debug_settings
        l.prop(ds, "mab_emulate_helpers")
        if ds.mab_emulate_helpers:
            l.prop(ds, "mab_twist_bake")
        l.prop(ds, "mab_smooth_resample")
        if ds.mab_smooth_resample:
            l.prop(ds, "mab_resample_fps")
        r = l.row()
        r.scale_y = 1.4
        r.operator("xbg.import_wdl_mab",
                   text="Import WDL MAB", icon='ARMATURE_DATA')
