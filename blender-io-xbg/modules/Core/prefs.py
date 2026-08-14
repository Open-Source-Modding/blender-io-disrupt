"""Addon preferences.

Split out of the monolithic __init__.py (2026-06-09 refactor).

The auto-updater that used to live here has been removed (2026-07-04): it
kept leaving the addon in a broken, un-listed state after "Update Now" +
restart, on at least one machine, with no clear repro. Rather than keep
patching a background self-modifying updater, users now update manually —
download the latest release zip from GitHub (or pull the Dev branch) and
reinstall through Blender's Add-on Install button, same as any other addon.
"""
import bpy

# The addon root package name: "V12"-style folder for a legacy addon, or
# the full "bl_ext.<repo>.<name>" when installed as a Blender extension.
# split('.')[0] would break for extensions, so strip our own subpath instead.
ADDON_ID = __package__.rsplit('.modules.', 1)[0]


def get_prefs(ctx):
    """The addon preferences, regardless of which module asks."""
    return ctx.preferences.addons[ADDON_ID].preferences


# ---------------------------------------------------------------------------
# Addon preferences
# ---------------------------------------------------------------------------

class XBGAddonPreferences(bpy.types.AddonPreferences):
    # MUST be the addon root module name — with __name__ this class would
    # silently fail to bind (get_prefs() returns None, panel draws crash)
    bl_idname = ADDON_ID
    data_folder: bpy.props.StringProperty(
        name="Avatar / Far Cry 2 — Extracted Game Data",
        description="Path to the extracted game-data folder for Avatar: The "
                    "Game or Far Cry 2 (shared by both — point it at whichever "
                    "game's data you're working with; the original unpacked "
                    "files are read from here)",
        default="",
        subtype='DIR_PATH'
    )
    patch_folder: bpy.props.StringProperty(
        name="Avatar Game — Extracted Patch Folder",
        description="Destination patch/mod folder for the Avatar game. Your "
                    "custom files (baked materials/textures, patched skeleton + "
                    "proceduralbones.xml) are written here, mirroring their "
                    "relative path under the extracted game-data folder",
        default="",
        subtype='DIR_PATH'
    )
    fci_data_folder: bpy.props.StringProperty(
        name="Far Cry Instincts — Extracted Archive Folder",
        description="Path to a Far Cry Instincts .dat/.fat archive dump "
                    "(the output folder of fci_extract.py). Used to look up "
                    "a model's texture by its embedded in-game path",
        default="",
        subtype='DIR_PATH'
    )
    fc1_data_folder: bpy.props.StringProperty(
        name="Far Cry 1 — FCData Folder",
        description="Path to the Far Cry 1 FCData game-data folder (contains "
                    "Objects/Objects1/Objects2, Textures/Textures1/Textures2, "
                    "etc). Used to look up a model's textures by their "
                    "embedded in-game .dds path",
        default="",
        subtype='DIR_PATH'
    )

    def draw(self, ctx):
        self.layout.prop(self, "data_folder")
        self.layout.prop(self, "patch_folder")
        self.layout.prop(self, "fci_data_folder")
        self.layout.prop(self, "fc1_data_folder")


# ---------------------------------------------------------------------------
# Operators — Expand Bounds / Save Bounds
# ---------------------------------------------------------------------------

