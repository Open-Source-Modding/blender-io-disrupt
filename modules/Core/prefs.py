"""Addon preferences.

Split out of the monolithic __init__.py (2026-06-09 refactor).
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

    def draw(self, ctx):
        pass
