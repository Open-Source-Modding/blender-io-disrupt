"""Main UI — game picker.

The sidebar opens on a "Select the game you wish to modify" screen with one
button per game.  Picking a game swaps the panel content to that game's
tools; the back arrow returns to the picker.  The selection lives in
``Scene.xbg_active_game`` so it survives undo / file boundaries gracefully.

Per-game tool panels are ordinary sub-panels parented to that game's root
container panel (e.g. ``OBJECT_PT_xbg_wd``), so a game's whole UI hides
with one poll check.
"""

import bpy

from ..Core.detect import detect_game_from_path


# (identifier, button label, supported)
GAMES = [
    ('WD1', "Watch Dogs 1",     True),
    ('WD2', "Watch Dogs 2",     True),
    ('WD3', "Watch Dogs Legion", True),
]

GAME_LABELS = {gid: label for gid, label, _ in GAMES}
SUPPORTED = {gid for gid, _, ok in GAMES if ok}

GAME_ENUM_ITEMS = [('NONE', "None", "No game selected")] + [
    (gid, label, label) for gid, label, _ in GAMES
]


def active_game(ctx):
    return getattr(ctx.scene, 'xbg_active_game', 'NONE')


class XBG_OT_SelectGame(bpy.types.Operator):
    """Switch the sidebar to this game's tools (or back to the picker)."""
    bl_idname = "xbg.select_game"
    bl_label = "Select Game"
    bl_options = {'INTERNAL'}

    game: bpy.props.StringProperty(default='NONE')

    def execute(self, ctx):
        ctx.scene.xbg_active_game = self.game
        return {'FINISHED'}


class XBG_OT_DetectGame(bpy.types.Operator):
    """Open a file browser to auto-detect the game from a file's header."""
    bl_idname = "xbg.detect_game"
    bl_label = "Auto-detect Game from File"
    bl_options = {'INTERNAL'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(
        default="*.xbg;*.glm;*.hkx;*.mab;*.skel",
        options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        game = detect_game_from_path(self.filepath)
        if game is None:
            self.report({'WARNING'},
                        "Could not detect game from file header. "
                        "Please select manually.")
            return {'CANCELLED'}
        ctx.scene.xbg_active_game = game
        label = GAME_LABELS.get(game, game)
        self.report({'INFO'}, f"Detected: {label}")
        return {'FINISHED'}


class XBG_PT_Panel(bpy.types.Panel):
    """Root panel: game picker / per-game header."""
    bl_label = "XBG Importer"
    bl_idname = "OBJECT_PT_xbg_import"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "XBG Import"

    def draw(self, ctx):
        l = self.layout

        game = active_game(ctx)

        if game == 'NONE':
            # ── Game picker ─────────────────────────────────────────────
            l.label(text="Select the game you wish to modify:",
                    icon='RESTRICT_SELECT_OFF')
            col = l.column(align=True)
            col.scale_y = 1.4
            for gid, label, supported in GAMES:
                if supported:
                    op = col.operator("xbg.select_game", text=label)
                    op.game = gid
            l.separator()
            op = l.operator("xbg.detect_game", text="Auto-detect from File...",
                            icon='VIEWZOOM')
            return

        # ── A game is selected: back arrow + title ──────────────────────
        row = l.row(align=True)
        op = row.operator("xbg.select_game", text="", icon='BACK')
        op.game = 'NONE'
        row.label(text=GAME_LABELS.get(game, game))


class XBG_PT_WDRoot(bpy.types.Panel):
    """Container for the Watch Dogs 1 / 2 toolset (panels in panels_wd.py)."""
    bl_label = "Watch Dogs Tools"
    bl_idname = "OBJECT_PT_xbg_wd"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "XBG Import"
    bl_parent_id = "OBJECT_PT_xbg_import"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, ctx):
        return active_game(ctx) in ('WD1', 'WD2')

    def draw(self, ctx):
        l = self.layout
        ds = ctx.scene.xbg_debug_settings
        row = l.row()
        row.scale_y = 1.3
        icon = 'SETTINGS' if ds.advanced_mode else 'PREFERENCES'
        row.prop(ds, "advanced_mode", text="Advanced Mode", icon=icon,
                 toggle=True)


class XBG_PT_WDLRoot(bpy.types.Panel):
    """Container for the Watch Dogs Legion toolset (panels in panels_wdl.py)."""
    bl_label = "Watch Dogs Legion Tools"
    bl_idname = "OBJECT_PT_xbg_wdl"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "XBG Import"
    bl_parent_id = "OBJECT_PT_xbg_import"
    bl_options = {'HIDE_HEADER'}

    @classmethod
    def poll(cls, ctx):
        return active_game(ctx) == 'WD3'

    def draw(self, ctx):
        l = self.layout
        ds = ctx.scene.xbg_debug_settings
        row = l.row()
        row.scale_y = 1.3
        icon = 'SETTINGS' if ds.advanced_mode else 'PREFERENCES'
        row.prop(ds, "advanced_mode", text="Advanced Mode", icon=icon,
                 toggle=True)
