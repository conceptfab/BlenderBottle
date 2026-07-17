"""Reproduce Liquifeel Geometry panel draw crash."""
import sys
import traceback
import bpy
import addon_utils

addon_utils.enable('liquifeel', default_set=True, persistent=True)

bpy.ops.mesh.primitive_cube_add()
obj = bpy.context.active_object
obj.name = 'BottleTest'


class LQFL_MT_debug(bpy.types.Menu):
    bl_label = 'Debug'
    bl_idname = 'LQFL_MT_debug_draw'

    def draw(self, context):
        import liquifeel as m
        print('MENU DRAW START', flush=True)
        try:
            m.draw_assembly_ui(context, self.layout, None, context.active_object)
            print('draw_assembly_ui OK', flush=True)
        except Exception:
            print('draw_assembly_ui FAIL', flush=True)
            traceback.print_exc()
        try:
            m.draw_geometry_ui(context, self.layout)
            print('draw_geometry_ui OK', flush=True)
        except Exception:
            print('draw_geometry_ui FAIL', flush=True)
            traceback.print_exc()
        try:
            m.draw_hrdc_main_panel(self, context)
            print('draw_hrdc_main_panel OK', flush=True)
        except Exception:
            print('draw_hrdc_main_panel FAIL', flush=True)
            traceback.print_exc()


bpy.utils.register_class(LQFL_MT_debug)
try:
    bpy.ops.wm.call_menu(name='LQFL_MT_debug_draw')
except Exception:
    traceback.print_exc()

# Also exercise with real NORU-like hierarchy: parent + multi objects
parent = bpy.data.objects.new('500_ML', None)
bpy.context.collection.objects.link(parent)
obj.parent = parent
cork = bpy.data.objects.new('500_korek', obj.data.copy() if False else bpy.data.meshes.new('c'))
# simple empty cork
cork = bpy.data.objects.new('500_korek', None)
bpy.context.collection.objects.link(cork)

print('is_active_selected', flush=True)
import liquifeel as m
print('has island?', m.has_obj_single_mesh_island(obj), flush=True)
print('is_active_selected_ob', m.is_active_selected_ob(bpy.context), flush=True)

try:
    bpy.ops.wm.call_menu(name='LQFL_MT_debug_draw')
except Exception:
    traceback.print_exc()

print('DONE', flush=True)
sys.exit(0)
