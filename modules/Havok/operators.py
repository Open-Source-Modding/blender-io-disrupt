"""WD1 HKX collision Blender operators.

Import and export WD1 .hkx collision files (old packfile format, Havok 2012).
"""

import os
import bpy

from ..Havok.hkx_format import parse_hkx, OldPackfileParser
from ..Havok.wd1_collision_reader import WD1CollisionReader


class XBG_OT_ImportWD1Hkx(bpy.types.Operator):
    """Import a WD1 .hkx collision file as mesh objects."""
    bl_idname = "xbg.import_wd1_hkx"
    bl_label = "Import WD1 HKX Collision"
    bl_description = (
        "Read a Watch Dogs 1 .hkx Havok packfile (64-bit Havok 2012) and build "
        "wireframe collision mesh objects for each shape"
    )
    bl_options = {'REGISTER', 'UNDO'}

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.hkx", options={'HIDDEN'})

    def invoke(self, ctx, ev):
        ctx.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, ctx):
        if not self.filepath or not os.path.isfile(self.filepath):
            self.report({'ERROR'}, "No valid .hkx file selected")
            return {'CANCELLED'}

        try:
            parser = parse_hkx(self.filepath)
            reader = WD1CollisionReader(parser)

            if not reader.compound:
                self.report({'ERROR'}, "No compound shape found")
                return {'CANCELLED'}

            base_name = os.path.splitext(os.path.basename(self.filepath))[0]
            root = bpy.data.objects.new(base_name + "_collision", None)
            root.empty_display_type = 'CUBE'
            root.empty_display_size = 0.25
            root['wd1_hkx_src'] = self.filepath
            ctx.collection.objects.link(root)

            n_shapes = 0
            for i, inst in enumerate(reader.compound.instances):
                if inst.shape is None:
                    continue

                if hasattr(inst.shape, 'vertices') and inst.shape.vertices:
                    me = bpy.data.meshes.new("%s_shape%d" % (base_name, i))
                    me.from_pydata(inst.shape.vertices, [], [])
                    me.update()
                    obj = bpy.data.objects.new(me.name, me)
                    obj.display_type = 'WIRE'
                    obj.show_wire = True
                    obj['wd1_hkx_src'] = self.filepath
                    obj['wd1_hkx_shape_off'] = inst.shape.offset
                    ctx.collection.objects.link(obj)
                    obj.parent = root
                    n_shapes += 1

            self.report({'INFO'},
                "WD1 HKX: %d shapes from %s" % (n_shapes, os.path.basename(self.filepath)))
            return {'FINISHED'}

        except Exception as exc:
            self.report({'ERROR'}, f"Failed to import WD1 HKX: {exc}")
            import traceback; traceback.print_exc()
            return {'CANCELLED'}
