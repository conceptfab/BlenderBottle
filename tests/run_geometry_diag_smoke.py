"""Blender background smoke test for LiquiFeel geometry diagnostics.

Usage:
  /path/to/Blender --background --python tests/run_geometry_diag_smoke.py
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

import bpy
import bmesh

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
    import LiquiFeel as mod
    try:
        mod.unregister()
    except Exception:
        pass
    mod.register()
    return mod


def make_solid_cube():
    bpy.ops.mesh.primitive_cube_add(size=0.2)
    obj = bpy.context.active_object
    obj.name = 'SolidCube'
    return obj


def make_shell_cube(outer=0.1, thickness=0.01):
    """Manifold hollow box (outer+inner walls connected) as one island."""
    inner = outer - thickness
    # Outer cube faces + inner cube faces (reversed) — classic shell via bmesh
    bpy.ops.mesh.primitive_cube_add(size=outer * 2)
    obj = bpy.context.active_object
    obj.name = 'ShellCube'
    mod = obj.modifiers.new(name='Solidify', type='SOLIDIFY')
    mod.thickness = thickness
    mod.offset = 0.0
    mod.use_rim = True
    # Open one face so Solidify makes a single connected shell with rim
    bpy.ops.object.mode_set(mode='EDIT')
    bm = bmesh.from_edit_mesh(obj.data)
    bm.faces.ensure_lookup_table()
    # delete top face (highest Z center)
    top = max(bm.faces, key=lambda f: f.calc_center_median().z)
    bmesh.ops.delete(bm, geom=[top], context='FACES')
    bmesh.update_edit_mesh(obj.data)
    bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.modifier_apply(modifier=mod.name)
    # Ensure single island
    return obj


def make_plane():
    bpy.ops.mesh.primitive_plane_add(size=0.2)
    obj = bpy.context.active_object
    obj.name = 'FlatPlane'
    return obj


def select_active(obj):
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def main():
    print('=== LiquiFeel geometry diag smoke ===')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)

    try:
        mod = load_addon()
    except Exception:
        traceback.print_exc()
        fail('Addon failed to load/register')
        return _finish(1)

    from LiquiFeel import geometry_diag

    # 1) Flat plane → Problem (no shell)
    plane = make_plane()
    select_active(plane)
    report = mod.build_geometry_check_report(plane)
    text = '\n'.join(report)
    print('--- PLANE ---')
    print(text)
    if '[Problem]' in text and ('no opposite' in text or 'single-surface' in text):
        ok('Plane flagged as missing shell')
    else:
        fail('Plane should be Problem for missing shell')

    # 2) Hollow shell → OK wall shell
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    shell = make_shell_cube(thickness=0.01)
    select_active(shell)
    report = mod.build_geometry_check_report(shell)
    text = '\n'.join(report)
    print('--- SHELL ---')
    print(text)
    if 'Wall shell looks present' in text or '[OK] Wall shell' in text:
        ok('Shell cube reports wall present')
    elif 'Verdict: geometry looks suitable' in text and 'single-surface' not in text:
        ok('Shell cube suitable (no single-surface problem)')
    else:
        fail('Shell cube should pass thickness shell check')

    # 3) Preview toggle builds NG + paints
    assert bpy.ops.liquifeel.toggle_geometry_diag() == {'FINISHED'}
    if geometry_diag.has_geometry_diag_modifier(shell):
        ok('Preview Diag assigned modifier')
    else:
        fail('Preview Diag did not assign modifier')
    if shell.data.color_attributes.get(geometry_diag.GEOMETRY_DIAG_ATTR):
        ok('LQFL_Diag color attribute painted')
    else:
        fail('Missing LQFL_Diag color attribute')
    if bpy.data.node_groups.get(geometry_diag.GEOMETRY_DIAG_NG_NAME):
        ok('LiquiFeel_GeometryDiag node group exists')
    else:
        fail('Diagnostic node group missing')

    # 3b) Rim Radius socket must actually be written (regression:
    # silently ignored on Blender 5.2 via the id-prop path).
    mod_ = geometry_diag.assign_geometry_diag_modifier(shell, rim_radius=0.5)
    rim_item = None
    for it in mod_.node_group.interface.items_tree:
        if getattr(it, 'name', None) == 'Rim Radius' and getattr(it, 'in_out', None) == 'INPUT':
            rim_item = it
            break
    if rim_item is None:
        fail('Diag NG lacks a Rim Radius input socket')
    else:
        if hasattr(mod_, 'properties'):
            rim_val = getattr(mod_.properties.inputs, rim_item.identifier).value
        else:
            rim_val = mod_[rim_item.identifier]
        if abs(float(rim_val) - 0.5) < 1e-6:
            ok('Rim Radius socket applied (0.5)')
        else:
            fail(f'Rim Radius socket not applied: {rim_val!r} != 0.5')

    assert bpy.ops.liquifeel.toggle_geometry_diag() == {'FINISHED'}
    if not geometry_diag.has_geometry_diag_modifier(shell):
        ok('Preview Diag removed modifier')
    else:
        fail('Preview Diag did not remove modifier')

    return _finish(0 if not ERRORS else 1)


def _finish(code):
    if ERRORS:
        print('FAILURES:')
        for e in ERRORS:
            print(' -', e)
    else:
        print('SMOKE_OK')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
