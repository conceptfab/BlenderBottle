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
    label = mesh_obj('Label', (0.15, 0, 0.25))
    extra = mesh_obj('Extra', (-0.15, 0, 0.25))

    select_active(bottle)
    result = bpy.ops.liquifeel.assembly_set_bottle()
    if 'FINISHED' not in result:
        fail(f'Set as Bottle: {result}')
    elif not mod.has_assembly(bottle):
        fail('Bottle missing assembly marker after Set as Bottle')
    else:
        ok('Set as Bottle')

    select_active(cork)
    result = bpy.ops.liquifeel.assembly_assign_cork()
    if 'FINISHED' not in result:
        fail(f'Assign cork: {result}')
    elif cork.parent != bottle:
        fail(f'Cork parent is {cork.parent!r}, expected bottle')
    else:
        ok('Assign cork (parented)')

    select_active(label)
    result = bpy.ops.liquifeel.assembly_assign_label()
    if 'FINISHED' not in result or label.parent != bottle:
        fail(f'Assign label failed: {result}, parent={label.parent}')
    else:
        ok('Assign label')

    select_active(extra)
    result = bpy.ops.liquifeel.assembly_add_extra()
    if 'FINISHED' not in result or extra.parent != bottle:
        fail(f'Add extra failed: {result}, parent={extra.parent}')
    else:
        ok('Add extra')

    members = mod.list_assembly_member_objects(bottle)
    if len(members) != 3:
        fail(f'Expected 3 members, got {len(members)}: {[m.name for m in members]}')
    else:
        ok('3 children linked in marker')

    cork_before = cork.matrix_world.translation.copy()
    bottle.location.z += 1.0
    bpy.context.view_layer.update()
    cork_after = cork.matrix_world.translation.copy()
    if abs((cork_after.z - cork_before.z) - 1.0) > 1e-4:
        fail(f'Cork did not follow bottle move: dz={cork_after.z - cork_before.z}')
    else:
        ok('Children follow bottle translate')

    bottle.rotation_euler.z = math.radians(45)
    bpy.context.view_layer.update()
    if cork.parent != bottle:
        fail('Cork lost parent after bottle rotate')
    else:
        ok('Parent retained after bottle rotate')

    cad = bpy.data.objects.new('CAD_Root', None)
    bpy.context.collection.objects.link(cad)
    mw = bottle.matrix_world.copy()
    bottle.parent = cad
    bottle.matrix_world = mw
    bpy.context.view_layer.update()
    select_active(bottle)
    result = bpy.ops.liquifeel.bake_parent_transforms()
    if 'FINISHED' not in result:
        fail(f'bake_parent_transforms: {result}')
    elif bottle.parent is not None:
        fail('Bottle still has parent after bake')
    elif cork.parent != bottle or label.parent != bottle or extra.parent != bottle:
        fail('Assembly children lost after bake_parent_transforms')
    else:
        ok('bake_parent clears CAD parent, keeps assembly children')

    # --- Regression: bake FREEZES scale to 1:1 with no visible change and
    #     without dragging children (fill nodes require unit object scale) ---
    def world_verts(o):
        return [(o.matrix_world @ v.co).copy() for v in o.data.vertices]

    scaled = mesh_obj('ScaledBottle', (2, 0, 0))
    scaled.scale = (0.1, 0.1, 0.1)
    bpy.context.view_layer.update()
    select_active(scaled)
    if 'FINISHED' not in bpy.ops.liquifeel.assembly_set_bottle():
        fail('Set scaled bottle failed')
    scap = mesh_obj('ScaledCork', (2, 0, 0.06))
    select_active(scap)
    bpy.ops.liquifeel.assembly_assign_cork()

    root = bpy.data.objects.new('SkalaRoot', None)
    bpy.context.collection.objects.link(root)
    mw = scaled.matrix_world.copy()
    scaled.parent = root
    scaled.matrix_world = mw
    root.rotation_euler.z = math.radians(30)
    bpy.context.view_layer.update()

    verts_before = world_verts(scaled)
    cork_world_before = scap.matrix_world.translation.copy()
    select_active(scaled)
    if 'FINISHED' not in bpy.ops.liquifeel.bake_parent_transforms():
        fail('bake on scaled bottle failed')
    bpy.context.view_layer.update()

    if abs(scaled.scale.x - 1.0) > 1e-4 or abs(scaled.scale.z - 1.0) > 1e-4:
        fail(f'Bottle scale not frozen to 1:1: scale={tuple(scaled.scale)}')
    else:
        ok('Bottle scale frozen to 1:1 through bake')

    verts_after = world_verts(scaled)
    max_drift = max(((a - b).length for a, b in zip(verts_before, verts_after)),
                    default=0.0)
    if max_drift > 1e-4:
        fail(f'Bottle appearance changed on bake: max world-vert drift={max_drift}')
    else:
        ok('Bottle appearance preserved through freeze (no physical change)')

    cork_world_after = scap.matrix_world.translation.copy()
    if (cork_world_after - cork_world_before).length > 1e-3:
        fail(f'Cork drifted on bake: {(cork_world_after - cork_world_before).length}')
    else:
        ok('Cork world position preserved through bake')

    # Silent xform diagnostics last-event (Copy Diagnostics source).
    xkey = mod.XFORM_DIAG_KEY
    if xkey not in scaled.keys():
        fail(f'Missing {xkey} after bake_parent_transforms')
    else:
        raw = scaled[xkey]
        xdiag = raw.to_dict() if hasattr(raw, 'to_dict') else dict(raw)
        if xdiag.get('op') != 'bake_parent_transforms':
            fail(f"xform diag op={xdiag.get('op')!r} "
                 f"(expected 'bake_parent_transforms')")
        elif float(xdiag.get('max_child_drift') or 0.0) > 1e-3:
            fail(f"xform diag max_child_drift="
                 f"{xdiag.get('max_child_drift')} (expected <= 1e-3)")
        else:
            ok('xform diag last-event recorded on bake')
        bpy.context.view_layer.objects.active = scaled
        report = mod.build_liquifeel_diagnostics(bpy.context)
        if 'Last transform event:' not in report:
            fail('diagnostics report missing Last transform event')
        elif 'Children (live):' not in report:
            fail('diagnostics report missing Children (live)')
        elif 'Object orientation:' not in report:
            fail('diagnostics report missing Object orientation')
        else:
            ok('diagnostics report includes orientation + Children + Last transform')

    marker = dict(mod._lqfl_marker_get(bottle))
    marker['filled'] = True
    marker['separate_liquid'] = 'dummy'
    mod._lqfl_marker_set(bottle, marker)
    mod._lqfl_strip_fill_keys_keep_assembly(bottle)
    if not mod.has_assembly(bottle):
        fail('Assembly lost after strip fill keys')
    elif 'filled' in mod._lqfl_marker_get(bottle):
        fail('filled key still present after strip')
    else:
        ok('Clear-fill strip keeps assembly')

    # Marker (de)serialization must survive an IDProperty round-trip.
    sample = {'role': 'extra', 'controller': bottle.name,
              'version': list(mod.bl_info['version']), 'nested': {'a': 1}}
    clean = mod._lqfl_sanitize_marker(dict(sample))
    mod._lqfl_marker_set(cork, {'assembly': {'members': {}},
                               'version': clean['version']})
    got = mod._lqfl_marker_get(cork)
    if got.get('version') is None:
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

    select_active(bottle)
    result = bpy.ops.liquifeel.assembly_clear()
    if 'FINISHED' not in result:
        fail(f'Clear assembly: {result}')
    elif mod.has_assembly(bottle):
        fail('Assembly marker still present after clear')
    elif cork.parent is not None or label.parent is not None or extra.parent is not None:
        fail('Members still parented after Clear Assembly')
    elif cork.name not in bpy.data.objects:
        fail('Cork object deleted by Clear Assembly')
    else:
        ok('Clear Assembly unparents and keeps meshes')

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
