"""XBG Importer — Ubisoft Disrupt engine model/animation tools for Blender.

Modules:
    modules/Core/       addon prefs, settings PropertyGroups, log ops
    modules/Havok/      HKX collision parser, decompressor, injector
    modules/Watch_Dogs/     WD1 tools (import, export, inject, collision, materials)
    modules/Watch_Dogs_2/   WD2 tools (GLM import/export, .xbg import)
    modules/Watch_Dogs_Legion/  WDL tools (import, inject, animation)
    modules/UI/         game-picker root panel + per-game panels

This file only assembles the pieces and registers them.
"""

bl_info = {
    "name": "Ubisoft Disrupt Engine formats",
    "author": "Selene Bray-Hernandez, Quiet Joker, Jasper_Zebra",
    "version": (3, 1, 2),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > XBG Import / File > Import",
    "description": "Import/edit/re-export models from Watch Dogs 1, 2 and Legion "
                   "(Ubisoft Disrupt engine)",
    "category": "Import-Export",
}

import bpy

from .modules.Core.debug import VerboseLogger

from .modules.Core.prefs import (
    XBGAddonPreferences,
)
from .modules.Core.settings import (
    XBGDebugSettings,
)
from .modules.Core.ops_log import (
    XBG_OT_ResetLog,
    XBG_OT_SaveLog,
)

from .modules.Watch_Dogs.operators_wd import (
    XBG_OT_ImportWD, XBG_OT_ImportWDMab, XBG_OT_InjectWD,
    XBG_OT_WDPeekLODs, XBG_OT_WDSyncNormals,
    XBG_OT_ImportWDSkeleton, XBG_OT_ImportWDHkx,
    XBG_OT_InjectWDHkx, XBG_OT_ExportWD1)
from .modules.Watch_Dogs_2.operators_wd2 import XBG_OT_ImportWD2, XBG_OT_ImportWD2XBG, XBG_OT_ExportWD2, XBG_OT_ImportWD2GLMFull
from .modules.Watch_Dogs_Legion.operators_wdl import (
    XBG_OT_ImportWDL, XBG_OT_InjectWDL, XBG_OT_ImportWDLSkeleton,
    XBG_OT_ImportWDLMab, XBG_OT_ImportWDLHkx)

from .modules.UI.main import (
    XBG_OT_SelectGame,
    XBG_OT_DetectGame,
    XBG_PT_Panel,
    XBG_PT_WDRoot,
    XBG_PT_WDLRoot,
)
from .modules.UI.panels_wd import (
    XBG_PT_WDImport,
    XBG_PT_WDAnimation,
    XBG_PT_WDInject,
    XBG_PT_WDDebug,
    XBG_PT_WDModelInfo,
)
from .modules.UI.panels_wdl import (
    XBG_PT_WDLImport,
    XBG_PT_WDLInject,
    XBG_PT_WDLModelInfo,
    XBG_PT_WDLAnimation,
)


classes = (
    # preferences + settings (PropertyGroups first)
    XBGAddonPreferences,
    XBGDebugSettings,
    # core ops
    XBG_OT_ResetLog,
    XBG_OT_SaveLog,
    # Watch Dogs 1
    XBG_OT_ImportWD,
    XBG_OT_ImportWDMab,
    XBG_OT_InjectWD,
    XBG_OT_WDPeekLODs,
    XBG_OT_WDSyncNormals,
    XBG_OT_ImportWDSkeleton,
    XBG_OT_ImportWDHkx,
    XBG_OT_InjectWDHkx,
    XBG_OT_ExportWD1,
    # Watch Dogs 2
    XBG_OT_ImportWD2,
    XBG_OT_ImportWD2XBG,
    XBG_OT_ExportWD2,
    XBG_OT_ImportWD2GLMFull,
    # Watch Dogs Legion
    XBG_OT_ImportWDL,
    XBG_OT_InjectWDL,
    XBG_OT_ImportWDLSkeleton,
    XBG_OT_ImportWDLMab,
    XBG_OT_ImportWDLHkx,
    # UI (order matters: parents before children)
    XBG_OT_SelectGame,
    XBG_OT_DetectGame,
    XBG_PT_Panel,
    XBG_PT_WDRoot,
    XBG_PT_WDImport,
    XBG_PT_WDAnimation,
    XBG_PT_WDInject,
    XBG_PT_WDDebug,
    XBG_PT_WDModelInfo,
    XBG_PT_WDLRoot,
    XBG_PT_WDLImport,
    XBG_PT_WDLInject,
    XBG_PT_WDLModelInfo,
    XBG_PT_WDLAnimation,
)


def menu_func_import(self, ctx):
    sep = False
    for op_id, label in [
        ("xbg.import_wdl_model", "Watch Dogs Legion Model (.xbg)"),
        ("xbg.import_wdl_skeleton", "Watch Dogs Legion Skeleton (.skel)"),
        ("xbg.import_wdl_hkx", "Watch Dogs Legion Collision (.hkx)"),
        ("xbg.import_wd2_glm_full", "Watch Dogs 2 Model - Full (.glm)"),
    ]:
        if not sep:
            self.layout.separator()
            sep = True
        self.layout.operator(op_id, text=label)

def menu_func_export(self, ctx):
    self.layout.separator()
    self.layout.operator("xbg.export_wd1",
                         text="Watch Dogs 1 Model (.xbg)")

def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.append(menu_func_export)
    S = bpy.types.Scene
    S.xbg_debug_settings     = bpy.props.PointerProperty(type=XBGDebugSettings)
    # game-picker selection; plain string so 'NONE' (the picker screen)
    # needs no enum bookkeeping when new games are added
    S.xbg_active_game = bpy.props.StringProperty(default='NONE')
    # Patch every operator's .report() so WARNING/ERROR popups also get
    # captured in the JSONL stream — otherwise the user dismisses the
    # popup and the only evidence of what went wrong is lost.
    VerboseLogger.install_report_capture(classes)


def unregister():
    S = bpy.types.Scene
    del S.xbg_debug_settings
    del S.xbg_active_game
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    bpy.types.TOPBAR_MT_file_export.remove(menu_func_export)
    for c in reversed(classes):
        try:
            bpy.utils.unregister_class(c)
        except RuntimeError:
            pass


if __name__ == "__main__":
    register()
