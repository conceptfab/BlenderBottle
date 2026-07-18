"""Blender background smoke test for Bottle Assembly.

Usage:
  /path/to/Blender --background --python tests/run_assembly_blender_smoke.py
"""
from __future__ import annotations

import math
import sys
import traceback
from pathlib import Path

import bpy

ADDON_DIR = Path(__file__).resolve().parents[1]
ERRORS = []


def ok(msg):
    print(f'OK: {msg}')


def fail(msg):
    print(f'FAIL: {msg}')
    ERRORS.append(msg)


def load_addon():
    parent = str(ADDON_DIR.parent)
    if parent not in sys.path:
        sys.path.insert(0, parent)
    # Folder name is LiquiFeel — import as package so relative imports work.
    import LiquiFeel as mod
    try:
        mod.unregister()
    except Exception:
        pass
    mod.register()
    return mod


def mesh_obj(name, loc=(0, 0, 0)):
    mesh = bpy.data.meshes.new(name + '_Mesh')
    mesh.from_pydata(
        [(-0.1, -0.1, 0), (0.1, -0.1, 0), (0.1, 0.1, 0), (-0.1, 0.1, 0),
         (-0.1, -0.1, 0.5), (0.1, -0.1, 0.5), (0.1, 0.1, 0.5), (-0.1, 0.1, 0.5)],
        [],
        [(0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5),
         (2, 3, 7, 6), (3, 0, 4, 7)],
    )
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    obj.location = loc
    return obj


def select_active(obj, also=None):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    if also:
        for o in also:
            o.select_set(True)
    bpy.context.view_layer.objects.active = obj


def main():
    print('=== LiquiFeel Bottle Assembly smoke test ===')
    print('Addon dir:', ADDON_DIR)
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    try:
        mod = load_addon()
    except Exception:
        traceback.print_exc()
        fail('Addon failed to load/register')
        _finish(1)
        return

    bottle = mesh_obj('Bottle', (0, 0, 0))
    cork = mesh_obj('Cork', (0, 0, 0.6))
    cork_child = mesh_obj('CorkShape', (0, 0, 0.6))
    cork_child.parent = cork
    label = mesh_obj('Label', (0.15, 0, 0.25))
    extra = mesh_obj('Extra', (-0.15, 0, 0.25))
    bottle_home = set(c.name for c in bottle.users_collection)

    select_active(bottle)
    result = bpy.ops.liquifeel.assembly_set_bottle()
    ctrl = mod.get_scene_assembly_bottle(bpy.context)
    if 'FINISHED' not in result:
        fail(f'Set as Bottle: {result}')
    elif ctrl is None or not mod.has_assembly(ctrl):
        fail('No controller assembly after Set as Bottle')
    else:
        ok('Set as Bottle')

    # --- Feature: build on COPIES. The controller is a COPY of the selected
    #     object; the ORIGINAL is left untouched outside the collection. ---
    if ctrl is not None and (ctrl is bottle or not mod.is_lqfl_copy_object(ctrl)
                             or ctrl.data is bottle.data):
        fail('controller is not an independent copy of the original')
    else:
        ok('Set as Bottle built a working COPY as the controller')

    lqfl_col = mod.get_liquifeel_collection(ctrl)
    if lqfl_col is None:
        fail('Set as Bottle did not create a collection')
    elif ctrl.name not in lqfl_col.objects:
        fail('working bottle copy is not in the collection')
    elif bottle.name in lqfl_col.objects:
        fail('ORIGINAL bottle ended up in the collection (must stay out)')
    elif set(c.name for c in bottle.users_collection) != bottle_home:
        fail('original bottle was moved out of its collection')
    else:
        ok('collection holds the working copy; original left in place')

    backup = mod.find_bottle_backup(ctrl)
    if backup is None:
        fail('no hidden bottle backup in the collection')
    elif lqfl_col is not None and backup.name not in lqfl_col.objects:
        fail('bottle backup is not in the collection')
    elif backup.data is ctrl.data or backup.data is bottle.data:
        fail('bottle backup is not an independent copy')
    elif not (backup.hide_viewport and backup.hide_render):
        fail('bottle backup is not hidden')
    else:
        ok('collection holds a hidden independent bottle backup')

    # Assign cork (original) -> a COPY (with its child) joins the collection.
    select_active(cork)
    result = bpy.ops.liquifeel.assembly_assign_cork()
    members = mod.list_assembly_member_objects(ctrl)
    cork_copy = members[0] if members else None
    if 'FINISHED' not in result:
        fail(f'Assign cork: {result}')
    elif cork.parent is not None:
        fail('original cork was reparented (must stay untouched)')
    elif cork_copy is None or cork_copy is cork:
        fail('assigned cork is not a copy')
    elif cork_copy.parent != ctrl:
        fail('cork copy is not parented to the bottle copy')
    elif lqfl_col is not None and cork_copy.name not in lqfl_col.objects:
        fail('cork copy is not in the collection')
    elif len([o for o in lqfl_col.objects if o.parent == cork_copy]) < 1:
        fail('cork child (subtree) was not copied into the collection')
    else:
        ok('assign cork copied it (with child); original untouched')

    select_active(label)
    result = bpy.ops.liquifeel.assembly_assign_label()
    if 'FINISHED' not in result or label.parent is not None:
        fail(f'Assign label failed/moved original: {result}, parent={label.parent}')
    else:
        ok('Assign label (copy)')

    select_active(extra)
    result = bpy.ops.liquifeel.assembly_add_extra()
    if 'FINISHED' not in result or extra.parent is not None:
        fail(f'Add extra failed/moved original: {result}, parent={extra.parent}')
    else:
        ok('Add extra (copy)')

    members = mod.list_assembly_member_objects(ctrl)
    if len(members) != 3:
        fail(f'Expected 3 member copies, got {len(members)}: {[m.name for m in members]}')
    else:
        ok('3 member copies linked to the bottle copy')

    m0 = members[0]
    before = m0.matrix_world.translation.copy()
    ctrl.location.z += 1.0
    bpy.context.view_layer.update()
    after = m0.matrix_world.translation.copy()
    if abs((after.z - before.z) - 1.0) > 1e-4:
        fail(f'member copy did not follow bottle move: dz={after.z - before.z}')
    else:
        ok('member copies follow the bottle copy')

    cad = bpy.data.objects.new('CAD_Root', None)
    bpy.context.collection.objects.link(cad)
    mw = ctrl.matrix_world.copy()
    ctrl.parent = cad
    ctrl.matrix_world = mw
    bpy.context.view_layer.update()
    select_active(ctrl)
    result = bpy.ops.liquifeel.bake_parent_transforms()
    if 'FINISHED' not in result:
        fail(f'bake_parent_transforms: {result}')
    elif ctrl.parent is not None:
        fail('bottle copy still has parent after bake')
    elif any(m.parent != ctrl for m in mod.list_assembly_member_objects(ctrl)):
        fail('member copies lost after bake')
    else:
        ok('bake clears CAD parent, keeps member copies')

    # --- Regression: bake FREEZES scale to 1:1 on the bottle COPY ---
    def world_verts(o):
        return [(o.matrix_world @ v.co).copy() for v in o.data.vertices]

    scaled_src = mesh_obj('ScaledBottle', (2, 0, 0))
    scaled_src.scale = (0.1, 0.1, 0.1)
    bpy.context.view_layer.update()
    select_active(scaled_src)
    if 'FINISHED' not in bpy.ops.liquifeel.assembly_set_bottle():
        fail('Set scaled bottle failed')
    scaled = mod.get_scene_assembly_bottle(bpy.context)  # the copy controller

    root = bpy.data.objects.new('SkalaRoot', None)
    bpy.context.collection.objects.link(root)
    mw = scaled.matrix_world.copy()
    scaled.parent = root
    scaled.matrix_world = mw
    root.rotation_euler.z = math.radians(30)
    bpy.context.view_layer.update()

    verts_before = world_verts(scaled)
    select_active(scaled)
    if 'FINISHED' not in bpy.ops.liquifeel.bake_parent_transforms():
        fail('bake on scaled bottle failed')
    bpy.context.view_layer.update()

    if abs(scaled.scale.x - 1.0) > 1e-4 or abs(scaled.scale.z - 1.0) > 1e-4:
        fail(f'Bottle copy scale not frozen to 1:1: scale={tuple(scaled.scale)}')
    else:
        ok('Bottle copy scale frozen to 1:1 through bake')

    verts_after = world_verts(scaled)
    max_drift = max(((a - b).length for a, b in zip(verts_before, verts_after)),
                    default=0.0)
    if max_drift > 1e-4:
        fail(f'Bottle copy appearance changed on bake: drift={max_drift}')
    else:
        ok('Bottle copy appearance preserved through freeze')

    xkey = mod.XFORM_DIAG_KEY
    if xkey not in scaled.keys():
        fail(f'Missing {xkey} after bake_parent_transforms')
    else:
        bpy.context.view_layer.objects.active = scaled
        report = mod.build_liquifeel_diagnostics(bpy.context)
        if 'Last transform event:' not in report:
            fail('diagnostics report missing Last transform event')
        elif 'Object orientation:' not in report:
            fail('diagnostics report missing Object orientation')
        else:
            ok('diagnostics report includes orientation + Last transform')

    # Strip fill keys keeps assembly (on the controller copy).
    marker = dict(mod._lqfl_marker_get(ctrl))
    marker['filled'] = True
    marker['separate_liquid'] = 'dummy'
    mod._lqfl_marker_set(ctrl, marker)
    mod._lqfl_strip_fill_keys_keep_assembly(ctrl)
    if not mod.has_assembly(ctrl):
        fail('Assembly lost after strip fill keys')
    elif 'filled' in mod._lqfl_marker_get(ctrl):
        fail('filled key still present after strip')
    else:
        ok('Clear-fill strip keeps assembly')

    # Marker (de)serialization must survive an IDProperty round-trip.
    rt = mesh_obj('RoundTrip', (9, 9, 9))
    clean = mod._lqfl_sanitize_marker(
        {'role': 'extra', 'controller': ctrl.name,
         'version': list(mod.bl_info['version']), 'nested': {'a': 1}})
    mod._lqfl_marker_set(rt, {'assembly': {'members': {}},
                              'version': clean['version']})
    if mod._lqfl_marker_get(rt).get('version') is None:
        fail('Marker round-trip lost version')
    else:
        ok('Marker round-trip preserves data')

    # --- Regression: Opening Type -> 'straight' must actually RESET the
    #     Select Outer modifier's Lip Threshold to 0 (old code wrote to a
    #     phantom 'lip_threshold' attribute and left the modifier stale) ---
    so_group = bpy.data.node_groups.new(mod.SELECT_OUTER_NG_NAME, 'GeometryNodeTree')
    so_group.interface.new_socket('Lip Threshold', in_out='INPUT',
                                  socket_type='NodeSocketFloat')
    lip_obj = mesh_obj('LipTest', (5, 0, 0))
    so_mod = lip_obj.modifiers.new(mod.SELECT_OUTER_NG_NAME, 'NODES')
    so_mod.node_group = so_group
    bpy.context.view_layer.update()
    select_active(lip_obj)
    mod.set_geonode_mod_input(lip_obj, mod.SELECT_OUTER_NG_NAME,
                              'Lip Threshold', 'float', 5.0)
    before = mod.get_geonode_mod_input(lip_obj, mod.SELECT_OUTER_NG_NAME,
                                       'Lip Threshold')
    props = lip_obj.hrdc_liquifeel_input_field_props.geometry
    props.opening_shape = 'irregular'   # non-straight -> callback no-ops
    props.opening_shape = 'straight'    # fires update -> should reset to 0
    after = mod.get_geonode_mod_input(lip_obj, mod.SELECT_OUTER_NG_NAME,
                                      'Lip Threshold')
    if abs(before - 5.0) > 1e-5:
        fail(f'test setup wrong: Lip Threshold not set to 5.0 (got {before})')
    elif abs(after) > 1e-5:
        fail(f'Opening Type straight did not reset Lip Threshold: {after}')
    else:
        ok('Opening Type straight resets Select Outer Lip Threshold to 0')

    # --- Island-count cache: draw path must not recount on every redraw ---
    if not mod.has_obj_single_mesh_island(bottle):
        fail('bottle cube should be a single mesh island')
    elif bottle.name not in mod._mesh_island_count_cache:
        fail('island count was not cached after has_obj_single_mesh_island')
    else:
        cached = mod._mesh_island_count_cache[bottle.name]
        if cached[2] != 1:
            fail(f'cached island count is {cached[2]}, expected 1')
        else:
            ok('mesh island count cached for draw path')

    # --- Feature: Clear deletes the whole work-copy collection (copies +
    #     backup); every ORIGINAL object stays untouched. ---
    col_name = lqfl_col.name if lqfl_col else None
    select_active(ctrl)
    result = bpy.ops.liquifeel.assembly_clear()
    if 'FINISHED' not in result:
        fail(f'Clear assembly: {result}')
    elif col_name in bpy.data.collections:
        fail('Clear did not remove the LiquiFeel collection')
    elif bottle.name not in bpy.data.objects:
        fail('Clear deleted the ORIGINAL bottle')
    elif cork.name not in bpy.data.objects or cork_child.name not in bpy.data.objects:
        fail('Clear deleted an ORIGINAL part (only copies should go)')
    elif set(c.name for c in bottle.users_collection) != bottle_home:
        fail('original bottle collection changed by Clear')
    else:
        ok('Clear removed collection (copies + backup); originals intact')

    _finish(1 if ERRORS else 0)


def _finish(code):
    print('=== DONE ===')
    if ERRORS:
        print(f'{len(ERRORS)} failure(s):')
        for e in ERRORS:
            print(' -', e)
    else:
        print('All assembly smoke checks passed.')
    sys.exit(code)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
