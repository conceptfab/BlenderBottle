bl_info = {
    "name" : "Liquifeel",
    "author" : "BlenderMight",
    "description" : "Fill recipient models with liquid.",
    "blender" : (4, 1, 0),
    "version" : (1, 5),
    "location" : "View3D > UI",
    "warning" : "",
    "category" : "Interface",
}

# bumped on every local patch, shown in diagnostics to verify which build runs
ADDON_BUILD_TAG = 'blender52-port-r27'

import bpy
import mathutils
import idprop
# from mathutils import Vector

import os
import shutil
import pathlib
import json
import functools as ft
import sys

from copy import deepcopy
from pprint import pprint

from .third_party.t3dn_bip import previews

import importlib

from bpy.app.handlers import persistent

# import properties
# importlib.reload(properties)

registerable_classes = []

## MISC FUNCTIONS --------------------------------------------------------------------------------

def key_from_name(name):
    return name.replace(' ', '_').lower().replace(';', '_').replace('/', '_').replace('.', '_')

def name_from_fname(fname):
    return '.'.join(fname.split('.')[:-1])

def name_from_key(key):
    return ' '.join(
        map(lambda elem: elem.capitalize(),
            key.split('_')))

def class_name_from_key(key):
    return ''.join(
        map(lambda elem: elem.capitalize(),
            key.split('_')))

def bl_version_lesser(v1, v2):
    if v1[0] > v2[0]:
        return False
    elif v1[1] > v2[1]:
        return False
    else:
        return v1[2] < v2[2]

def bl_version_greater(v1, v2):
    if v1[0] < v2[0]:
        return False
    elif v1[1] < v2[1]:
        return False
    else:
        return v1[2] > v2[2]

def strip_name(name):
    elems = name.split(' ')
    return ' '.join(
        filter(lambda elem: elem != '', elems)
    )

# This generates a dictionary with correlates stripped keys with unstripped keys.
# it is useful for aiding in the access to data refferenced by keys with accidentally
# included leading or trailing whitespace
def stripped_correlator(data):
    corr = {}
    for key in data.keys():
        corr[strip_name(key)] = key
    return corr

# Read the comment to the function defined above.
def index_stripped(data, key):
    corr = stripped_correlator(data)
    return data[corr[strip_name(key)]]

def does_dict_have_key_path(data, key_path):
    if len(key_path) == 1:
        return key_path[0] in data.keys()
    elif key_path[0] in data.keys():
        return does_dict_have_key_path(data[key_path[0]], key_path[1:])
    else:
        return False

## JSON  -------------

def parse_json_string(json_string):
    data = json.loads(json_string)
    return data

# Silent last-event transform diagnostics for Copy Diagnostics (not the
# liquifeel marker — sanitize/strip must not wipe this).
XFORM_DIAG_KEY = 'liquifeel_xform_diag'
_XFORM_DIAG_MAX_CHILDREN = 24
_XFORM_DIAG_DRIFT_EPS = 1e-3


def _xform_diag_round_vec(v, nd=6):
    return [round(float(c), nd) for c in v]


def _xform_diag_euler_deg(euler):
    """Euler angles in degrees for human-readable diagnostics."""
    import math as _math
    return [round(_math.degrees(float(a)), 3) for a in euler]


def _xform_diag_orientation(obj__):
    """Local + world rotation and which local/world axis looks 'tallest'."""
    _, rot_q, _ = obj__.matrix_world.decompose()
    world_euler = rot_q.to_euler('XYZ')
    dims = tuple(float(v) for v in obj__.dimensions)
    axis_names = ('X', 'Y', 'Z')
    tallest_local = axis_names[max(range(3), key=lambda i: dims[i])]
    # World-space AABB size from the eight bound_box corners — shows how the
    # bottle actually stands in the scene after rotation (vertical vs pancake).
    world_extents = [0.0, 0.0, 0.0]
    try:
        corners = [obj__.matrix_world @ mathutils.Vector(c)
                   for c in obj__.bound_box]
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        zs = [c.z for c in corners]
        world_extents = [
            max(xs) - min(xs),
            max(ys) - min(ys),
            max(zs) - min(zs),
        ]
        tallest_world = axis_names[
            max(range(3), key=lambda i: world_extents[i])]
    except Exception:
        tallest_world = '?'
        world_extents = [0.0, 0.0, 0.0]
    # Object +Z axis direction in world — for a vertical bottle this should
    # point roughly up (world +Z).
    try:
        local_up = (obj__.matrix_world.to_3x3()
                    @ mathutils.Vector((0.0, 0.0, 1.0))).normalized()
        up_dot_world_z = round(float(local_up.z), 4)
    except Exception:
        local_up = mathutils.Vector((0.0, 0.0, 1.0))
        up_dot_world_z = 1.0
    return {
        'rotation_mode': str(obj__.rotation_mode),
        'local_euler_deg': _xform_diag_euler_deg(obj__.rotation_euler),
        'world_euler_deg': _xform_diag_euler_deg(world_euler),
        'dimensions_local': _xform_diag_round_vec(dims, 4),
        'dimensions_world_aabb': _xform_diag_round_vec(world_extents, 4),
        'tallest_local_axis': tallest_local,
        'tallest_world_axis': tallest_world,
        'local_z_dot_world_z': up_dot_world_z,
        'local_z_world_dir': _xform_diag_round_vec(local_up, 4),
    }


def _xform_diag_mpi_is_identity(obj__, eps=1e-5):
    try:
        mpi = obj__.matrix_parent_inverse
        ident = mathutils.Matrix.Identity(4)
        for i in range(4):
            for j in range(4):
                if abs(mpi[i][j] - ident[i][j]) > eps:
                    return False
        return True
    except Exception:
        return True


def _xform_diag_capture(context, obj__):
    """Compact transform snapshot for silent before/after diagnostics."""
    if obj__ is None:
        return {}
    try:
        context.view_layer.update()
    except Exception:
        pass
    _, _, world_scale = obj__.matrix_world.decompose()
    orient = _xform_diag_orientation(obj__)
    chain = []
    _p = obj__.parent
    while _p is not None:
        chain.append(f"{_p.name}{tuple(round(v, 3) for v in _p.scale)}")
        _p = _p.parent
    children = []
    for child in list(obj__.children)[:_XFORM_DIAG_MAX_CHILDREN]:
        try:
            _, cq, _ = child.matrix_world.decompose()
            child_world_euler = _xform_diag_euler_deg(cq.to_euler('XYZ'))
        except Exception:
            child_world_euler = [0.0, 0.0, 0.0]
        children.append({
            'name': child.name,
            'world_loc': _xform_diag_round_vec(child.matrix_world.translation),
            'local_scale': _xform_diag_round_vec(child.scale, 4),
            'local_euler_deg': _xform_diag_euler_deg(child.rotation_euler),
            'world_euler_deg': child_world_euler,
            'mpi_identity': _xform_diag_mpi_is_identity(child),
        })
    try:
        scene_scale_length = float(context.scene.unit_settings.scale_length)
    except Exception:
        scene_scale_length = 1.0
    return {
        'name': obj__.name,
        'local_scale': _xform_diag_round_vec(obj__.scale, 4),
        'world_scale': _xform_diag_round_vec(world_scale, 4),
        'rotation_mode': orient['rotation_mode'],
        'local_euler_deg': orient['local_euler_deg'],
        'world_euler_deg': orient['world_euler_deg'],
        'dimensions_local': orient['dimensions_local'],
        'dimensions_world_aabb': orient['dimensions_world_aabb'],
        'tallest_local_axis': orient['tallest_local_axis'],
        'tallest_world_axis': orient['tallest_world_axis'],
        'local_z_dot_world_z': orient['local_z_dot_world_z'],
        'local_z_world_dir': orient['local_z_world_dir'],
        'parent': (obj__.parent.name if obj__.parent else None),
        'parent_chain': list(chain),
        'mpi_is_identity': _xform_diag_mpi_is_identity(obj__),
        'children': children,
        'scene_scale_length': round(scene_scale_length, 6),
    }


def _xform_diag_as_plain(data):
    """Ensure nested structures are IDProperty-safe plain Python."""
    if isinstance(data, dict):
        return {str(k): _xform_diag_as_plain(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_xform_diag_as_plain(v) for v in data]
    if isinstance(data, bool):
        return data
    if isinstance(data, (int, float)):
        return data
    if data is None:
        return ''
    return str(data)


def _xform_diag_record(context, obj__, op, before, after):
    """Store one last-event transform diag on the object (never raises)."""
    if obj__ is None:
        return
    try:
        before_children = {
            c.get('name'): c for c in (before or {}).get('children', [])
            if isinstance(c, dict) and c.get('name')
        }
        after_children = {
            c.get('name'): c for c in (after or {}).get('children', [])
            if isinstance(c, dict) and c.get('name')
        }
        child_drifts = []
        max_drift = 0.0
        for name, ac in after_children.items():
            bc = before_children.get(name)
            if bc is None:
                continue
            bloc = bc.get('world_loc') or [0.0, 0.0, 0.0]
            aloc = ac.get('world_loc') or [0.0, 0.0, 0.0]
            drift = sum((float(a) - float(b)) ** 2
                        for a, b in zip(aloc, bloc)) ** 0.5
            if drift > max_drift:
                max_drift = drift
            if drift > _XFORM_DIAG_DRIFT_EPS:
                child_drifts.append({
                    'name': name,
                    'drift': round(drift, 6),
                    'world_loc_before': list(bloc),
                    'world_loc_after': list(aloc),
                })

        warnings = []
        if child_drifts:
            warnings.append('CHILD_DRIFT')
        for snap in (before, after):
            if not snap:
                continue
            ws = snap.get('world_scale') or [1.0, 1.0, 1.0]
            if any(abs(float(v) - 1.0) > 1e-3 for v in ws):
                if 'NON_UNIT_WORLD_SCALE' not in warnings:
                    warnings.append('NON_UNIT_WORLD_SCALE')
            if (max(float(v) for v in ws) - min(float(v) for v in ws)) > 1e-4:
                if 'NON_UNIFORM_SCALE' not in warnings:
                    warnings.append('NON_UNIFORM_SCALE')
            if abs(float(snap.get('scene_scale_length', 1.0)) - 1.0) > 1e-6:
                if 'NON_UNIT_SCENE_SCALE' not in warnings:
                    warnings.append('NON_UNIT_SCENE_SCALE')
            if snap.get('mpi_is_identity') is False:
                if 'MPI_NOT_IDENTITY' not in warnings:
                    warnings.append('MPI_NOT_IDENTITY')
            try:
                if abs(float(snap.get('local_z_dot_world_z', 1.0))) < 0.5:
                    if 'SIDEWAYS_ORIENTATION' not in warnings:
                        warnings.append('SIDEWAYS_ORIENTATION')
            except Exception:
                pass
            dims = snap.get('dimensions_local') or []
            try:
                if len(dims) == 3:
                    dmax = max(float(v) for v in dims)
                    dmin = min(float(v) for v in dims)
                    if dmax > 1e-8 and (dmin / dmax) < 0.05:
                        if 'FLAT_LOCAL_BOUNDS' not in warnings:
                            warnings.append('FLAT_LOCAL_BOUNDS')
            except Exception:
                pass

        event = _xform_diag_as_plain({
            'op': op,
            'build': ADDON_BUILD_TAG,
            'before': before or {},
            'after': after or {},
            'warnings': warnings,
            'max_child_drift': round(max_drift, 6),
            'child_drifts': child_drifts,
        })
        if XFORM_DIAG_KEY in obj__.keys():
            try:
                del obj__[XFORM_DIAG_KEY]
            except Exception:
                try:
                    obj__.pop(XFORM_DIAG_KEY, None)
                except Exception:
                    pass
        obj__[XFORM_DIAG_KEY] = event
    except Exception:
        pass


def make_single_user_and_apply_transforms(context, obj__):
    before = _xform_diag_capture(context, obj__)
    select_and_set_active(context, obj__, deselect_all=True)
    bpy.ops.object.make_single_user(object=True, obdata=True, material=True)
    # Freeze rotation AND scale to 1:1 (bakes them into the mesh, no visible
    # change). The fill Geometry Nodes assume unit object scale — absolute
    # thresholds break on non-unit-scaled geometry (e.g. works at 0.025, fails
    # at 0.1). Applying scale gives the nodes true-size geometry.
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    after = _xform_diag_capture(context, obj__)
    _xform_diag_record(context, obj__, 'apply_transforms_fill', before, after)

def bake_parent_transforms(context, obj__):
    """Unparent with Keep Transform, then FREEZE rotation and scale to 1:1.

    LiquiFeel's fill Geometry Nodes assume unit object scale and read world-space
    rotation. Nested CAD parents and non-unit object scale (e.g. 0.1) break
    liquid generation because absolute thresholds in the fill nodes operate on
    scaled geometry (empirically: fill works at scale 0.025 but not 0.1 in the
    same scene). Applying rotation AND scale bakes them into the mesh so object
    scale becomes (1,1,1) with NO visible change, giving the nodes true-size
    geometry.

    Direct children (cork/label/liquid proxy) are snapshotted and their world
    matrices restored after the apply, because transform_apply on a parent does
    not compensate child matrix_parent_inverse.

    Note: child restore via matrix_world is exact for uniform object scale (the
    normal case). Non-uniform scale combined with a baked rotation can introduce
    shear that a loc/rot/scale decomposition cannot represent; such children may
    still distort. A fully general fix would recompute each child's
    matrix_parent_inverse.
    """
    before = _xform_diag_capture(context, obj__)
    select_and_set_active(context, obj__, deselect_all=True)
    bpy.ops.object.make_single_user(object=True, obdata=True, material=True)
    if obj__.parent is not None:
        unparent_keep_transform(obj__)
        context.view_layer.update()
    # Snapshot child world matrices: applying rotation/scale to a parent does not
    # fix child matrix_parent_inverse, so children would otherwise drift.
    child_world = {child: child.matrix_world.copy() for child in obj__.children}
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    # Flush the depsgraph so the child restore reads the parent's freshly
    # evaluated matrix (child.matrix_world depends on it).
    context.view_layer.update()
    for child, mw in child_world.items():
        child.matrix_world = mw
    after = _xform_diag_capture(context, obj__)
    _xform_diag_record(context, obj__, 'bake_parent_transforms', before, after)

def prepare_bottle_world_pose(context, obj__):
    """If bottle sits under a parent: unparent Keep Transform + apply rot/scale.

    Same work as the old separate 'Unparent & Apply Transforms' button —
    folded into Set Bottle / Bottle drop. Returns (ok, err).
    """
    if obj__ is None or obj__.type != 'MESH':
        return False, 'Not a mesh.'
    if (obj__.library or obj__.override_library
            or (obj__.data is not None and obj__.data.library)):
        return (
            False,
            f"'{obj__.name}' is linked from another file. Make it local first.")
    if obj__.parent is not None:
        bake_parent_transforms(context, obj__)
    return True, ''

## BLENDER -------------

def undo_push(n):
    if n == 1:
        def decorator(f):
            def wrapper(arg):
                bpy.ops.ed.undo_push()
                return f(arg)
            return wrapper
        return decorator
    if n == 2:
        def decorator(f):
            def wrapper(instance, context):
                bpy.ops.ed.undo_push()
                return f(instance, context)
            return wrapper
        return decorator
    elif n == 3:
        def decorator(f):
            def wrapper(a, b, c):
                bpy.ops.ed.undo_push()
                return f(a, b, c)
            return wrapper
        return decorator
    elif n == 4:
        def decorator(f):
            def wrapper(a, b, c, d):
                bpy.ops.ed.undo_push()
                return f(a, b, c, d)
            return wrapper
        return decorator

# def undo_push(f):
#     def wrapper(instance, context):
#         bpy.ops.ed.undo_push()
#         return f(instance, context)
#     return wrapper

@undo_push(1)
def unused_data_purge(context):
    bpy.ops.outliner.orphans_purge(
        do_local_ids=True, do_linked_ids=True, do_recursive=True)

def is_active_selected_ob(context):
    ob = context.active_object
    if ob:
        return ob.select_get()
    return False        

def deselect_all_objects(context):
    for ob in context.selected_objects:
        ob.select_set(False)

def select_and_set_active(context, ob, deselect_all=False):
    if deselect_all:
        deselect_all_objects(context)
    context.view_layer.objects.active = ob
    ob.select_set(True)

heavy_render_bounce_params = {
    'max_bounces': 24,
    'transmission_bounces': 24,
    'volume_bounces': 2
}

light_render_bounce_params = {
    'max_bounces': 8,
    'transmission_bounces': 8,
    'volume_bounces': 0
}

def adjust_render_settings(context, light=False):
    if light:
        params = light_render_bounce_params
        for key, val in params.items():
            if getattr(context.scene.cycles, key) > val:
                setattr(context.scene.cycles, key, val)
    else:
        params = heavy_render_bounce_params
        for key, val in params.items():
            if getattr(context.scene.cycles, key) < val:
                setattr(context.scene.cycles, key, val)

## RNA SYSTEM -------

def getattr_rec(obj__, attr_key_path):
    try:
        return ft.reduce(getattr, attr_key_path, obj__)
    except:
        return None

# obsolet, old system, now we use REDUX_INPUT_DATA and it has a
# different hierarchy.
def getattr_rec__by_names(
        obj__, shading_modality_key, library_key, mat_name, target_type, group_name, input_name, prop_key=None):
    lib_key, mat_key, trgt_key, group_key, prop_key__ = map(
        key_from_name,
        [library_key, mat_name, target_type, group_name, input_name])
    if not(prop_key):
        prop_key = prop_key__
    prop_key_chain = [
        f'liquifeel_field_inputs',
        f'{shading_modality_key}_shading',
        f'{lib_key}_inputs',
        f'{mat_key}',
        f'{trgt_key}',
        f'{group_key}',
        f'{prop_key}',
    ]
    return getattr_rec(obj__, prop_key_chain)

# CONCESSION START --------------------------------------------------
# We refference hierarchically placed properties by recursing up the path.

def ref_ob_key_pair_rec__(obj__, key_chain):
    if len(key_chain) == 1:
        return obj__, key_chain[-1]
    else:
        key = key_chain.pop()
        return ref_ob_key_pair_rec__(
            getattr(obj__, key),
            key_chain)

def ref_ob_key_pair(obj__, key_chain):
    key_chain__ = key_chain.copy()
    key_chain__.reverse()
    return ref_ob_key_pair_rec__(obj__, key_chain__)

def ref_input_field_property(
        obj__, shading_modality_key, library_key, mat_name, target_type, group_name, input_name, prop_key=None):
    lib_key, mat_key, trgt_key, group_key, prop_key__ = map(
        key_from_name,
        [library_key, mat_name, target_type, group_name, input_name])
    if not(prop_key):
        prop_key = prop_key__
    prop_key_chain = [
        f'liquifeel_field_inputs',
        f'{shading_modality_key}_shading',
        f'{lib_key}_inputs',
        f'{mat_key}',
        f'{trgt_key}',
        f'{group_key}',
        f'{prop_key}',
    ]
    return ref_ob_key_pair(obj__, prop_key_chain)

# CONCESSION STOP --------------------------------------------------

def load_image(path):
    im = bpy.data.images.load(str(path))
    return im

def maybe_load_image(path):
    fname = path.name
    if fname in bpy.data.images.keys():
        return bpy.data.images[fname]
    else:
        im = bpy.data.images.load(str(path))
        return im

## MESH ISLAND COUNT ---

def get_vert_graph(verts, edges):
    # Initialize the path with all vertices indices
    graph = {v.index: set() for v in verts}
    # Add the possible paths via edges
    for e in edges:
        graph[e.vertices[0]].add(e.vertices[1])
        graph[e.vertices[1]].add(e.vertices[0])
    return graph

def follow_edges(starting_index, paths):
    current_selected_vert_indices = [starting_index]
    follow = True
    while follow:
        # Get indices that are still in the paths
        eligible = set([ind for ind in current_selected_vert_indices if ind in paths])
        if len(eligible) == 0:
            follow = False # Stops if no more
        else:
            # Get the corresponding links
            next = [paths[i] for i in eligible]
            # Remove the previous from the paths
            for key in eligible: paths.pop( key )
            # Get the new links as new inputs
            current_selected_vert_indices = set([ind for sub in next for ind in sub])

def count_mesh_islands(obj__):
    # Prepare the paths/links from each vertex to others
    graph = get_vert_graph(obj__.data.vertices, obj__.data.edges)
    n = 0
    while graph:
        starting_index = next(iter(graph))
        n += 1
        # Deplete the graph dictionary following this starting index
        follow_edges(starting_index, graph)
    return n

# Draw-path cache: keyed on object name, invalidated by vert/edge count
# change. Island topology cannot change in Object Mode without those counts
# changing. {obj_name: (vert_count, edge_count, island_count)}
_mesh_island_count_cache = {}

def count_mesh_islands_cached(obj__):
    mesh = obj__.data
    vert_c = len(mesh.vertices)
    edge_c = len(mesh.edges)
    hit = _mesh_island_count_cache.get(obj__.name)
    if hit is not None and hit[0] == vert_c and hit[1] == edge_c:
        return hit[2]
    n = count_mesh_islands(obj__)
    _mesh_island_count_cache[obj__.name] = (vert_c, edge_c, n)
    return n

def get_mesh_island_vert_counts(obj__):
    graph = get_vert_graph(obj__.data.vertices, obj__.data.edges)
    visited = set()
    sizes = []
    for start in graph.keys():
        if start in visited:
            continue
        visited.add(start)
        stack = [start]
        size = 0
        while stack:
            v = stack.pop()
            size += 1
            for neighbour in graph[v]:
                if neighbour not in visited:
                    visited.add(neighbour)
                    stack.append(neighbour)
        sizes.append(size)
    return sorted(sizes, reverse=True)

# Checked on the raw mesh (before modifiers), same as count_mesh_islands.
def diagnose_fill_geometry(obj__):
    mesh = obj__.data
    edge_face_counts = {}
    for poly in mesh.polygons:
        for key in poly.edge_keys:
            key = (min(key), max(key))
            edge_face_counts[key] = edge_face_counts.get(key, 0) + 1
    verts_in_edges = set()
    wire_edge_c = 0
    boundary_edge_c = 0
    non_manifold_edge_c = 0
    for e in mesh.edges:
        verts_in_edges.add(e.vertices[0])
        verts_in_edges.add(e.vertices[1])
        face_c = edge_face_counts.get(
            (min(e.vertices[0], e.vertices[1]), max(e.vertices[0], e.vertices[1])), 0)
        if face_c == 0:
            wire_edge_c += 1
        elif face_c == 1:
            boundary_edge_c += 1
        elif face_c > 2:
            non_manifold_edge_c += 1
    return {
        'island_sizes': get_mesh_island_vert_counts(obj__),
        'vert_count': len(mesh.vertices),
        'face_count': len(mesh.polygons),
        'loose_vert_count': len(mesh.vertices) - len(verts_in_edges),
        'wire_edge_count': wire_edge_c,
        'boundary_edge_count': boundary_edge_c,
        'non_manifold_edge_count': non_manifold_edge_c,
    }

def build_geometry_check_report(obj__):
    d = diagnose_fill_geometry(obj__)
    island_c = len(d['island_sizes'])
    lines = [f"Geometry check for '{obj__.name}':"]
    issue_c = 0
    if d['face_count'] == 0:
        issue_c += 1
        lines.append('[Problem] Mesh has no faces - nothing to fill.')
    if island_c == 1:
        lines.append('[OK] Single mesh island.')
    else:
        issue_c += 1
        sizes = ', '.join(map(str, d['island_sizes'][:6]))
        if island_c > 6:
            sizes += ', ...'
        lines.append(
            f'[Problem] {island_c} mesh islands (vertex counts: {sizes}) - exactly 1 is required.')
        lines.append(
            'Fix: keep only the recipient part. Use Select > All by Trait > Loose Geometry')
        lines.append(
            'to find debris, or Mesh > Separate > By Loose Parts to split the islands.')
    if d['loose_vert_count'] > 0:
        issue_c += 1
        lines.append(
            f"[Problem] {d['loose_vert_count']} loose vertices (not connected to any edge).")
        lines.append('Fix: Select > All by Trait > Loose Geometry, then delete.')
    if d['wire_edge_count'] > 0:
        issue_c += 1
        lines.append(
            f"[Problem] {d['wire_edge_count']} wire edges (not part of any face).")
    if d['boundary_edge_count'] > 0:
        lines.append(
            f"[Warning] {d['boundary_edge_count']} open (boundary) edges - the walls may have")
        lines.append(
            'no thickness, or the mesh has holes. Consider a Solidify modifier or bridging the rim.')
    if d['non_manifold_edge_count'] > 0:
        lines.append(
            f"[Warning] {d['non_manifold_edge_count']} non-manifold edges (more than 2 faces)")
        lines.append(
            '- these can confuse the interior detection.')
    if issue_c == 0:
        lines.append('Verdict: geometry looks suitable for filling.')
        if d['boundary_edge_count'] > 0 or d['non_manifold_edge_count'] > 0:
            lines.append('(Warnings above may still affect the fill result.)')
    else:
        lines.append('Verdict: fix the problems above, then fill the object.')
    return lines

## CONSTANT DATA --------------------------------------------------------------------------------

## SIMPLE -----------------------------

DEV = False
if DEV:
    debug_buffer = []

SPACING_H = 0.4
SML_H = 1.2
MID_H = 1.8
LRG_H = 2.4

SELECT_OUTER_NG_NAME = 'LiquiFeel_Select Outer'
# FILL_NG_NAME = 'LiquiFeelv1.2'
FILL_NG_NAME = 'LiquiFeelv1.3'
HIDE_RECIPIENT_NG_NAME = 'Hide_Recipient'
DROPLET_GEN_NG_NAME  = 'DropletGen'
CONDENSATION_NG_NAME = 'Condensation_V1.0'

UI_THUMB_SCALE = 13.2 * 0.75
POPUP_THUMB_SCALE = 13.2 / 2

LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR = 0.6

## COMPOUND -----------------------------

LQFL_OBJECT_TAG_ATTACHED_DATA_KEYS = [
    'liquifeel',
]

TEXTURE_RES_KEYS = ['256', '512', '1k', '2k']

image_file_extensions = ['png', 'jpg']

## DYNAMIC -----------------------------

## MAIN TABS ----------

# MAIN_TAB_KEYS = ['fill', 'shading', 'condensation']
# MAIN_TAB_KEYS = ['geometry', 'shading', 'effects', 'recipients']
MAIN_TAB_KEYS = ['geometry', 'shading', 'condensation', 'recipients']
MAIN_TAB_NAMES = {key: key.capitalize() for key in MAIN_TAB_KEYS}
MAIN_TAB_NAMES['recipients'] = '3D Assets'
MAIN_TAB_BUILTIN_ICONS = {
    'shading': 'MATERIAL',
    'render': 'RESTRICT_RENDER_OFF',
    # 'render': 'SCENE',
}

## FILEPATH ----------

def has_extension(fname, extension):
    return get_extension(fname).lower() == extension

def has_image_extension(fname):
    return any(
        map(lambda ext: has_extension(fname, ext),
            image_file_extensions))

def get_fname_with_name(patterns_folderpath, img_name, extension=None, img_extension=False):
    fnames = filter(lambda fname: name_from_fname(fname) == img_name,
                    os.listdir(patterns_folderpath))
    if extension:
        return next(filter(lambda fname: has_extension(fname, extension),
                           fnames))
    elif img_extension:
        return next(filter(has_image_extension,fnames))
    else:
        return next(fnames)

## PATH DATA ---

def assemble_flat_path_data(root_path, gen_key=True):
    path_data = {}
    if gen_key:
        for fname in os.listdir(root_path):
            key = key_from_name(name_from_fname(fname))
            path_data[key] = root_path / fname
    else:
        for fname in os.listdir(root_path):
            key = name_from_fname(fname)
            path_data[key] = root_path / fname
    return path_data

# two layer deep data structure (flat sub-dictionaries)
# {K:{K:V}}
def assemble_recipient_pattern_path_data(fpaths_data):
    recipient_patterns = {}
    for pattern_key in os.listdir(fpaths_data['recipient_patterns_root']):
        recipient_patterns[pattern_key] = {}
        for res_key in TEXTURE_RES_KEYS:
            recipient_patterns[pattern_key][res_key] = fpaths_data['recipient_patterns_root'].joinpath(
                pattern_key, f'{pattern_key}_{res_key}.png')
    return recipient_patterns

# two layer deep data structure (flat sub-dictionaries)
# {K:{K:V}}
def assemble_recipient_roughness_path_data(fpaths_data):
    recipient_roughness_maps = {}
    for roughness_key in os.listdir(fpaths_data['recipient_roughness_maps_root']):
        recipient_roughness_maps[roughness_key] = {}
        for res_key in TEXTURE_RES_KEYS:
            recipient_roughness_maps[roughness_key][res_key] = fpaths_data['recipient_roughness_maps_root'].joinpath(
                roughness_key, f'{roughness_key}_{res_key}.png')
    return recipient_roughness_maps

FPATHS = {}
FPATHS['addon_root'] = pathlib.Path(
    os.path.dirname(os.path.realpath(__file__)))

FPATHS['data_root'] = FPATHS['addon_root'] / 'data'

FPATHS['blendfs_root'] = FPATHS['data_root'] / 'blendfs'
FPATHS['blend_assets'] = FPATHS['blendfs_root'] / 'LiquidFeel_MASTER.blend'

# Filepath data for input data
FPATHS['input_field_data'] = FPATHS['data_root'] / 'ui_control_inputs.json'
# FPATHS['material_input_data'] = FPATHS['data_root'] / 'material_input_data.json'

# Filepath data for icons
FPATHS['icons_root'] = FPATHS['data_root'] / 'icons'
FPATHS['icons'] = assemble_flat_path_data(FPATHS['icons_root'])

# Filepath data for material thumbnails
FPATHS['material_thumbnails_root'] = FPATHS['data_root'] / 'material_thumbnails'
FPATHS['material_thumbnails'] = assemble_flat_path_data(FPATHS['material_thumbnails_root'])

# Filepath data for recipient bump textures
FPATHS['recipient_patterns_root'] = FPATHS['data_root'] / 'recipient_patterns'
FPATHS['recipient_patterns'] = assemble_recipient_pattern_path_data(FPATHS)

# Filepath data for recipient roughness textures
FPATHS['recipient_roughness_maps_root'] = FPATHS['data_root'] / 'recipient_roughness_maps'
FPATHS['recipient_roughness_maps'] = assemble_recipient_roughness_path_data(FPATHS)

# Filepath data for recipient thumbnails
FPATHS['recipient_asset_thumbnails_root'] = FPATHS['data_root'] / 'recipient_asset_thumbnails'
FPATHS['recipient_asset_thumbnails'] = assemble_flat_path_data(FPATHS['recipient_asset_thumbnails_root'], gen_key=False)
# FPATHS['recipient_asset_append_fpath'] = FPATHS['blendfs_root'] / 'LiquiFeel_Glass_Assets.blend'
FPATHS['recipient_asset_parenting_data'] = FPATHS['data_root'] / 'recipient_asset_parenting_data.json'

FPATHS['node_socket_data'] = FPATHS['data_root'] / 'node_socket_data.json'
FPATHS['input_ui_type_data'] = FPATHS['data_root'] / 'input_ui_type_data.json'


# : [(THUMBNAIL_NAME, OBJECT_NAME)]
recipient_asset_namess = [
    ('American Pint Glass', 'American_Pint_Glass'),
    ('Bordeaux Wine Glass', 'Bordeaux Wine Glass'),
    ('Beer Bottle 22oz', 'Bomber 22oz Bottle'),
    ('Beer Mug', 'Beer_Mug'),
    ('Large Bowl', 'Bowl_2in'),
    ('Bowl 6.5in', 'Bowl_6in'),
    ('Bowl 7.5in', 'Bowl_7.5in'),
    ('Bowl 9in', 'Bowl_9in'),
    ('Champagne Bottle', 'Champagne 750mL'),
    ('Hurricane Glass', 'Hurricane Glass'),
    ('Ikea Carafe', 'Ikea 365+ Carafe'),
    ('Pitcher', 'Pitcher'),
    ('Soda Bottle 16.9oz', 'Soda Bottle'),
    ('Whiskey Glass', 'Whiskey Glass'),
    ('Liquifeel Carafe', 'LiquifeelCarafe'),
    ('Pear Glass', 'Pear Glass'),
    ('Patterned Whiskey Glass', 'Patterned Whiskey Glass'),
    ('Vellum Whiskey Bottle', 'Vellum Whiskey Bottle'),
]
# # : [(THUMBNAIL_NAME, OBJECT_NAME)]
# recipient_asset_namess = [
#     ('American Pint Glass', 'American_Pint_Glass'),
#     ('Bordeaux Wine Glass', 'Bordeaux Wine Glass'),
#     ('Beer Bottle 22oz', 'Bomber 22oz Bottle'),
#     ('Beer Mug', 'Beer_Mug'),
#     ('Bowl_2in', 'Bowl_2in'),
#     ('Bowl_6.5in', 'Bowl_6in'),
#     ('Bowl_7.5in', 'Bowl_7.5in'),
#     ('Bowl_9in', 'Bowl_9in'),
#     ('Champagne Bottle', 'Champagne 750mL'),
#     ('Hurricane Glass', 'Hurricane Glass'),
#     ('Ikea Carafe', 'Ikea 365+ Carafe'),
#     ('Pitcher', 'Pitcher'),
#     ('Soda Bottle 16.9oz', 'Soda Bottle'),
#     ('Whiskey Glass', 'Whiskey Glass'),
#     ('Liquifeel Carafe', 'LiquifeelCarafe'),
# ]

# # manual rename operation data
# # : [(THUMBNAIL_NAME, PREVIEW_NAME)]
# preview_recipient_asset_names = {
#     'American Pint Glass': None,
#     'Bordeaux Wine Glass': None,
#     'Beer Bottle 22oz': None,
#     'Beer Mug': None,
#     'Bowl_2in': 'Large Bowl',
#     'Bowl_6.5in': 'Bowl 6.5in',
#     'Bowl_7.5in': 'Bowl 7.5in',
#     'Bowl_9in': 'Bowl 9in',
#     'Champagne Bottle': None,
#     'Hurricane Glass': None,
#     'Ikea Carafe': None,
#     'Pitcher': None,
#     'Soda Bottle 16.9oz': None,
#     'Whiskey Glass': None,
#     'Liquifeel Carafe': None,
# }

with open(str(FPATHS['recipient_asset_parenting_data']), 'r') as f:
    RECIPIENT_ASSET_PARENTING_DATA = json.load(f)
RECIPIENT_ASSET_NAME_DATA = {}

# print()
# print('RECIPIENT_ASSET_PARENTING_DATA')
# pprint(RECIPIENT_ASSET_PARENTING_DATA)
# print()

for thumbnail_name, obj_name in recipient_asset_namess:
    key = key_from_name(thumbnail_name)
    RECIPIENT_ASSET_NAME_DATA[key] = {
        'thumbnail': thumbnail_name,
        'object': obj_name,
    }
# print()
# print('RECIPIENT_ASSET_NAME_DATA')
# pprint(RECIPIENT_ASSET_NAME_DATA)
# print()

## LIBRARY MATERIALS ----------

# with open(str(FPATHS['input_field_data']), 'r') as f:
#     INPUT_FIELD_DATA__PRESERVING_ORDER = json.load(f)

INPUT_FIELD_DATA__PRESERVING_ORDER = [
    {
        'data': [
            {
                'data': [
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 50.0,
                                                        'underlying_input_name': 'Liquid Level',
                                                        'ui_input_name': 'Liquid Amount',
                                                        'key': 'liquid_amount',
                                                        'ui_category_key': 'fill',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Liquid Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    # This socket type's items can't seem to be
                                                    # deducible from the socket object at
                                                    # runtime. We are stuck with having to manually
                                                    # place the items in this data structure.
                                                    # The value which needs to be passed has to be
                                                    # an integer representing the position of the
                                                    # menu item in question. The only way of
                                                    # figuring out which iteger corresponds to which
                                                    # menu string is empirically, accordingly the
                                                    # items entry in this dictionary has to be in
                                                    # the correct order.
                                                    'data': {
                                                        'underlying_input_default_val': 0, # 'Concave Meniscus'
                                                        'underlying_input_name': 'Meniscus Type',
                                                        'ui_input_name': 'Meniscus Type',
                                                        'key': 'meniscus_type',
                                                        'ui_category_key': 'fill',
                                                        'ui_to_underlying_val_mapping': ['Concave Meniscus', 'Convex Meniscus'],
                                                        'items': ['Concave Meniscus', 'Convex Meniscus'],
                                                        'default_val': 'Concave Meniscus',
                                                        'underlying_input_type': 'menu'},
                                                    'key': 'Meniscus Type',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 'straight',
                                                        'ui_to_underlying_val_mapping': [
                                                            'Straight',
                                                            'Irregular'],
                                                        'key': 'opening_shape',
                                                        'ui_category_key': 'fill',
                                                        'underlying_input_type': 'enum'},
                                                    'key': 'Opening '
                                                    'Shape',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'dependency': {
                                                #             'group_name': FILL_NG_NAME,
                                                #             'input_name': 'Opening Shape',
                                                #             'target_type': 'Fill'},
                                                #         'underlying_input_name': 'Lip Threshold',
                                                #         'key': 'lip_threshold',
                                                #         'linked_update_index': 0.0,
                                                #         'ui_category_key': 'fill',
                                                #         'underlying_input_type': 'float',
                                                #         'update_f': 'lip_threshold_update'},
                                                #     'key': 'Lip Threshold',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Seal',
                                                        'key': 'seal_container',
                                                        'ui_category_key': 'fill',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Seal Container',
                                                    'key_type': 'input_name'}],
                                            'key': FILL_NG_NAME,
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Hide Recipient',
                                                        'key': 'hide_recipient',
                                                        'ui_category_key': 'fill',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Hide Recipient',
                                                    'key_type': 'input_name'}],
                                            'key': 'Hide_Recipient',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': FILL_NG_NAME,
                                                            'input_name': 'Opening Shape',
                                                            'target_type': 'Fill'},
                                                        'underlying_input_name': 'Lip Threshold',
                                                        'key': 'lip_threshold',
                                                        'linked_update_index': 0.0,
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'float',
                                                        # 'update_f': 'lip_threshold_update'
                                                    },
                                                    'key': 'Lip Threshold',
                                                    'key_type': 'input_name'}],
                                            'key': 'LiquiFeel_Select Outer',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Liquid Amount',
                                'Meniscus Type',
                                'Opening Shape',
                                'Lip Threshold',
                                'Seal Container',
                                'Hide Recipient']},
                        'key': 'fill',
                        'key_type': 'material/func_name'}],
                'key': 'fill',
                'key_type': 'library'}],
        'key': 'geometry',
        'key_type': 'main_tab'},
    {
        'data': [
            {
                'data': [
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.569447,
                                                            0.0,
                                                            0.838913],
                                                        'underlying_input_name': 'Liquid Color',
                                                        'key': 'liquid_color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Liquid Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 25.0,
                                                        'underlying_input_name': 'Intensity',
                                                        'key': 'intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Intensity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'underlying_input_name': 'Turbidity',
                                                        'key': 'turbidity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Turbidity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.1,
                                                        'underlying_input_name': 'Subsurface',
                                                        'key': 'subsurface',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Subsurface',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [0.35, 0.38, 0.04],
                                                        'underlying_input_name': 'Subsurface Radius',
                                                        'key': 'subsurface_radius',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'vector'},
                                                    'key': 'Subsurface Radius',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'underlying_input_name': 'Particles Opacity',
                                                        'key': 'particles_opacity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Particles Opacity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            1.0,
                                                            0.292314,
                                                            0.756792],
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Color',
                                                        'key': 'foam_color',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Foam Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            1.0,
                                                            0.683388,
                                                            0.650549],
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Secondary Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Secondary Foam Color',
                                                        'key': 'secondary_foam_color',
                                                        'ui_category_key': 'Secondary Foam',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Secondary Foam Color',
                                                    'key_type': 'input_name'}],
                                            'key': 'UberLiquid_Shader',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'},
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'underlying_input_name': 'Transmission',
                                                        'key': 'transmission',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Transmission',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'ui_to_underlying_val_mapping': {
                                                            False: 0.0,
                                                            True: 1.0},
                                                        'underlying_input_name': 'Smoothie',
                                                        'key': 'smoothie',
                                                        'ui_category_key': 'Smoothie',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Smoothie',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Smoothie',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Pulp',
                                                        'key': 'pulp',
                                                        'ui_category_key': 'Smoothie',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Pulp',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.5,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Secondary Foam',
                                                        'key': 'secondary_foam',
                                                        'ui_category_key': 'Secondary Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Secondary Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Secondary Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Secondary Foam Opacity',
                                                        'key': 'secondary_foam_opacity',
                                                        'ui_category_key': 'Secondary Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Secondary Foam Opacity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 25.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Secondary Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Secondary Foam Size',
                                                        'key': 'secondary_foam_scale',
                                                        'ui_category_key': 'Secondary Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Secondary Foam Size',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 150.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.5,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Value',
                                                        'key': 'bubbles_value',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Value',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Small Bubbles Presence',
                                                        'key': 'small_bubbles_presence',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Small Bubbles Presence',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Medium Bubbles Presence',
                                                        'key': 'medium_bubbles_presence',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Medium Bubbles '
                                                    'Presence',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Large Bubbles Presence',
                                                        'key': 'large_bubbles_presence',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Large Bubbles Presence',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Seed',
                                                        'key': 'foam_seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Seed',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 48,
                                                        'underlying_input_name': 'Bubbles Seed',
                                                        'key': 'bubbles_seed',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Bubbles Seed',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Carbonation Bubbles',
                                                        'key': 'carbonation_bubbles',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Carbonation Bubbles',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 50.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Carbonation Bubbles',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Carbonation Bubbles Density',
                                                        'key': 'carbonation_bubbles_quantity',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Carbonation Bubbles Density',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Carbonation Bubbles',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Carbonation Bubbles Scale',
                                                        'key': 'carbonation_bubbles_size',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Carbonation Bubbles Scale',
                                                    'key_type': 'input_name'}],
                                            'key': 'UberLiquid',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Liquid Color',
                                'Transmission',
                                'Intensity',
                                'Turbidity',
                                'Subsurface',
                                'Subsurface Radius',
                                'Smoothie',
                                'Pulp',
                                'Particles Opacity',
                                'Foam',
                                'Foam Amount',
                                'Foam Center Distribution',
                                'Foam Color',
                                'Secondary Foam',
                                'Secondary Foam Color',
                                'Secondary Foam Opacity',
                                'Secondary Foam Size',
                                'Bubbles Scale',
                                'Bubbles Value',
                                'Small Bubbles Presence',
                                'Medium Bubbles Presence',
                                'Large Bubbles Presence',
                                'Normal Strength',
                                'Foam Seed',
                                'Bubbles Seed',
                                'Carbonation Bubbles',
                                'Carbonation Bubbles Density',
                                'Carbonation Bubbles Scale']},
                        'key': 'UberLiquid',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Carbonated',
                                                        'key': 'carbonated',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Carbonated',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 50.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Quantity',
                                                        'key': 'quantity',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Quantity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Size',
                                                        'key': 'size',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Size',
                                                    'key_type': 'input_name'}],
                                            'key': 'Carbonation_Static',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 2.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 315.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Carbonated',
                                'Quantity',
                                'Size',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Beer',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Carbonated',
                                                        'key': 'carbonated',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Carbonated',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 50.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Quantity',
                                                        'key': 'quantity',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Quantity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Size',
                                                        'key': 'size',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Size',
                                                    'key_type': 'input_name'}],
                                            'key': 'Carbonation_Static',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 2.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 315.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Carbonated',
                                'Quantity',
                                'Size',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Black Beer',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.806952,
                                                            0.665387,
                                                            0.412543],
                                                        'underlying_input_name': 'Tea Color',
                                                        'key': 'tea_color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Tea Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 200.0,
                                                        'underlying_input_name': 'Intensity',
                                                        'key': 'intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Intensity',
                                                    'key_type': 'input_name'}],
                                            'key': 'Tea Shader',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Tea Color', 'Intensity']},
                        'key': 'Black Tea',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.603826,
                                                            0.955973,
                                                            1.0],
                                                        'underlying_input_name': 'Color',
                                                        'key': 'color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 415.0,
                                                        'underlying_input_name': 'Intensity',
                                                        'key': 'intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Intensity',
                                                    'key_type': 'input_name'}],
                                            'key': 'Blue Lagoon',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color', 'Intensity']},
                        'key': 'Blue Lagoon',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 220.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Blueberry Juice',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.440597,
                                                            0.300089,
                                                            0.140131],
                                                        'underlying_input_name': 'Liquid Color',
                                                        'key': 'liquid_color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Liquid Color',
                                                    'key_type': 'input_name'}],
                                            'key': 'Cappuccino',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'},
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 850.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed',
                                'Liquid Color']},
                        'key': 'Cappuccino',
                        'key_type': 'material/func_name'},
                    # {
                    #     'data': {
                    #         'data': [
                    #             {
                    #                 'data': [
                    #                     {
                    #                         'data': [
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': [
                    #                                         0.440597,
                    #                                         0.300089,
                    #                                         0.140131],
                    #                                     'underlying_input_name': 'Liquid Color',
                    #                                     'key': 'liquid_color',
                    #                                     'ui_category_key': 'Liquid',
                    #                                     'underlying_input_type': 'color'},
                    #                                 'key': 'Liquid Color',
                    #                                 'key_type': 'input_name'}],
                    #                         'key': 'Cappuccino',
                    #                         'key_type': 'group_name'}],
                    #                 'key': 'Shader NG',
                    #                 'key_type': 'target_type'},
                    #             {
                    #                 'data': [
                    #                     {
                    #                         'data': [
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': 0.025,
                    #                                     'dependency': {
                    #                                         'group_name': 'Cappuccino Utils',
                    #                                         'input_name': 'Foam',
                    #                                         'target_type': 'GeoNode'},
                    #                                     'underlying_input_name': 'Foam Amount',
                    #                                     'key': 'foam_amount',
                    #                                     'ui_category_key': 'Foam',
                    #                                     'subtype': 'percentage',
                    #                                     'underlying_input_type': 'float'},
                    #                                 'key': 'Foam Amount',
                    #                                 'key_type': 'input_name'}],
                    #                         'key': 'Foam Utils',
                    #                         'key_type': 'group_name'},
                    #                     {
                    #                         'data': [
                    #                             # # " Ideea cu cappuccino e ca nu are sens sa fie fara spuma, that's the point of it :)) " -- Alex
                    #                             # {
                    #                             #     'data': {
                    #                             #         'underlying_input_default_val': True,
                    #                             #         'underlying_input_name': 'Foam',
                    #                             #         'key': 'foam',
                    #                             #         'ui_category_key': 'Foam',
                    #                             #         'underlying_input_type': 'bool'},
                    #                             #     'key': 'Foam',
                    #                             #     'key_type': 'input_name'},
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': 850.0,
                    #                                     # 'dependency': {
                    #                                     #     'group_name': 'Cappuccino Utils',
                    #                                     #     'input_name': 'Foam',
                    #                                     #     'target_type': 'GeoNode'},
                    #                                     'underlying_input_name': 'Bubbles Scale',
                    #                                     'key': 'bubbles_scale',
                    #                                     'ui_category_key': 'Foam',
                    #                                     'underlying_input_type': 'float'},
                    #                                 'key': 'Bubbles Scale',
                    #                                 'key_type': 'input_name'},
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': 1.0,
                    #                                     # 'dependency': {
                    #                                     #     'group_name': 'Cappuccino Utils',
                    #                                     #     'input_name': 'Foam',
                    #                                     #     'target_type': 'GeoNode'},
                    #                                     'underlying_input_name': 'Bubbles',
                    #                                     'key': 'bubbles',
                    #                                     'ui_category_key': 'Foam',
                    #                                     'underlying_input_type': 'float'},
                    #                                 'key': 'Bubbles',
                    #                                 'key_type': 'input_name'},
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': 1.0,
                    #                                     # 'dependency': {
                    #                                     #     'group_name': 'Cappuccino Utils',
                    #                                     #     'input_name': 'Foam',
                    #                                     #     'target_type': 'GeoNode'},
                    #                                     'underlying_input_name': 'Normal Strength',
                    #                                     'key': 'normal_strength',
                    #                                     'ui_category_key': 'Foam',
                    #                                     'underlying_input_type': 'float'},
                    #                                 'key': 'Normal Strength',
                    #                                 'key_type': 'input_name'},
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': 0,
                    #                                     # 'dependency': {
                    #                                     #     'group_name': 'Cappuccino Utils',
                    #                                     #     'input_name': 'Foam',
                    #                                     #     'target_type': 'GeoNode'},
                    #                                     'underlying_input_name': 'Seed',
                    #                                     'key': 'seed',
                    #                                     'ui_category_key': 'Foam',
                    #                                     'underlying_input_type': 'int'},
                    #                                 'key': 'Seed',
                    #                                 'key_type': 'input_name'}],
                    #                         'key': 'Cappuccino Utils',
                    #                         'key_type': 'group_name'}],
                    #                 'key': 'GeoNode',
                    #                 'key_type': 'target_type'}],
                    #         'input_order': [
                    #             # 'Foam',
                    #             'Foam Amount',
                    #             'Liquid Color',
                    #             'Bubbles Scale',
                    #             'Bubbles',
                    #             'Normal Strength',
                    #             'Seed']},
                    #     'key': 'Cappuccino',
                    #     'key_type': 'material/func_name'}
                    # ,
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Carbonated',
                                                        'key': 'carbonated',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Carbonated',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 50.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Quantity',
                                                        'key': 'quantity',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Quantity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Size',
                                                        'key': 'size',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Size',
                                                    'key_type': 'input_name'}],
                                            'key': 'Carbonation_Static',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 110.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Carbonated',
                                'Quantity',
                                'Size',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Champagne',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.2,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 50.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.3,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Chocolate Milk',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 175.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'},
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 5.0,
                                                        'underlying_input_name': 'Coffee Intensity',
                                                        'key': 'coffee_intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Coffee Intensity',
                                                    'key_type': 'input_name'}],
                                            'key': 'Coffee',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Coffee Intensity',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Coffee',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Carbonated',
                                                        'key': 'carbonated',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Carbonated',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 50.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Quantity',
                                                        'key': 'quantity',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Quantity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Size',
                                                        'key': 'size',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Size',
                                                    'key_type': 'input_name'}],
                                            'key': 'Carbonation_Static',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 110.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Carbonated',
                                'Quantity',
                                'Size',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Coke',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 175.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.2,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'underlying_input_name': 'Pulp Amount',
                                                        'key': 'pulp_amount',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Pulp Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.114435,
                                                            0.005605,
                                                            0.005605],
                                                        'underlying_input_name': 'Juice Color',
                                                        'key': 'juice_color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Juice Color',
                                                    'key_type': 'input_name'}],
                                            'key': 'Juice Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed',
                                'Pulp Amount',
                                'Juice Color']},
                        'key': 'Cranberry Juice',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Carbonated',
                                                        'key': 'carbonated',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Carbonated',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 50.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Quantity',
                                                        'key': 'quantity',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Quantity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Size',
                                                        'key': 'size',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Size',
                                                    'key_type': 'input_name'}],
                                            'key': 'Carbonation_Static',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 110.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles '
                                                    'Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Carbonated',
                                'Quantity',
                                'Size',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Energy Drink',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.806952,
                                                            0.48515,
                                                            0.0],
                                                        'underlying_input_name': 'Liquid Color',
                                                        'key': 'liquid_color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Liquid Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 50.0,
                                                        'underlying_input_name': 'Intensity',
                                                        'key': 'intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Intensity',
                                                    'key_type': 'input_name'}],
                                            'key': 'Ginger Ale',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'},
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Carbonated',
                                                        'key': 'carbonated',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Carbonated',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 10.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Quantity',
                                                        'key': 'quantity',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Quantity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Size',
                                                        'key': 'size',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Size',
                                                    'key_type': 'input_name'}],
                                            'key': 'Carbonation_Static',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Liquid Color',
                                'Intensity',
                                'Carbonated',
                                'Quantity',
                                'Size']},
                        'key': 'Ginger Ale',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.2,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 400.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.270498,
                                                            0.445201,
                                                            0.030714],
                                                        'underlying_input_name': 'Juice Color',
                                                        'key': 'juice_color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Juice Color',
                                                    'key_type': 'input_name'},
                                            {
                                                    'data': {
                                                        'underlying_input_default_val': 1,
                                                        # 'dependency': {
                                                        #     'group_name': 'Foam Shader Utils',
                                                        #     'input_name': 'Foam',
                                                        #     'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Pulp Amount',
                                                        'key': 'pulp_amount',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Pulp Amount',
                                                    'key_type': 'input_name'}],
                                            'key': 'Juice Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed',
                                'Juice Color',
                                'Pulp Amount']},
                        'key': 'Green Apple Juice',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 120.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'underlying_input_name': 'Pulp Amount',
                                                        'key': 'pulp_amount',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Pulp Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.270498,
                                                            0.445201,
                                                            0.030714],
                                                        'underlying_input_name': 'Juice Color',
                                                        'key': 'juice_color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Juice Color',
                                                    'key_type': 'input_name'}],
                                            'key': 'Juice Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 2.8,
                                                        'underlying_input_name': 'Smoothie Chunks',
                                                        'key': 'smoothie_chunks',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Smoothie Chunks',
                                                    'key_type': 'input_name'}],
                                            'key': 'Smoothie Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed',
                                'Pulp Amount',
                                'Juice Color',
                                'Smoothie Chunks']},
                        'key': 'Greenies Smoothie',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            1.0,
                                                            0.925581,
                                                            0.634816],
                                                        'underlying_input_name': 'Color',
                                                        'key': 'color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 70.0,
                                                        'underlying_input_name': 'Intensity',
                                                        'key': 'intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Intensity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'underlying_input_name': 'Crystallization',
                                                        'key': 'crystallization',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Crystallization',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 2.0,
                                                        'underlying_input_name': 'Crystallization Scale',
                                                        'key': 'crystallization_scale',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Crystallization Scale',
                                                    'key_type': 'input_name'}],
                                            'key': 'Honey',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'},
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Static Bubbles',
                                                        'key': 'static_bubbles',
                                                        'ui_category_key': 'Bubbles',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Static Bubbles',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 10.0,
                                                        'dependency': {
                                                            'group_name': 'Static Bubbles',
                                                            'input_name': 'Static Bubbles',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Quantity',
                                                        'key': 'quantity',
                                                        'ui_category_key': 'Bubbles',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Quantity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Static Bubbles',
                                                            'input_name': 'Static Bubbles',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Size',
                                                        'key': 'size',
                                                        'ui_category_key': 'Bubbles',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Size',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Static Bubbles',
                                                            'input_name': 'Static Bubbles',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Bubbles',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Static Bubbles',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color',
                                'Intensity',
                                'Turbidity',
                                'Crystallization',
                                'Crystallization Scale',
                                'Static Bubbles',
                                'Quantity',
                                'Size',
                                'Seed']},
                        'key': 'Honey',
                        'key_type': 'material/func_name'},
                    # {
                    #     'data': {
                    #         'data': [
                    #             {
                    #                 'data': [
                    #                     {
                    #                         'data': [
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': [
                    #                                         1.0,
                    #                                         0.904783,
                    #                                         0.571125],
                    #                                     'underlying_input_name': 'Color',
                    #                                     'key': 'color',
                    #                                     'ui_category_key': 'Liquid',
                    #                                     'underlying_input_type': 'color'},
                    #                                 'key': 'Color',
                    #                                 'key_type': 'input_name'},
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': 70.0,
                    #                                     'underlying_input_name': 'Intensity',
                    #                                     'key': 'intensity',
                    #                                     'ui_category_key': 'Liquid',
                    #                                     'underlying_input_type': 'float'},
                    #                                 'key': 'Intensity',
                    #                                 'key_type': 'input_name'},
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': 0.3,
                    #                                     'underlying_input_name': 'Turbidity',
                    #                                     'key': 'turbidity',
                    #                                     'ui_category_key': 'Liquid',
                    #                                     'underlying_input_type': 'float'},
                    #                                 'key': 'Turbidity',
                    #                                 'key_type': 'input_name'}],
                    #                         'key': 'Honey',
                    #                         'key_type': 'group_name'}],
                    #                 'key': 'Shader NG',
                    #                 'key_type': 'target_type'},
                    #             {
                    #                 'data': [
                    #                     {
                    #                         'data': [
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': 0.0,
                    #                                     'underlying_input_name': 'Crystallization',
                    #                                     'key': 'crystallization',
                    #                                     'ui_category_key': 'Liquid',
                    #                                     'underlying_input_type': 'float'},
                    #                                 'key': 'Crystallization',
                    #                                 'key_type': 'input_name'}],
                    #                         'key': 'Honey Utils',
                    #                         'key_type': 'group_name'},
                    #                     {
                    #                         'data': [
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': True,
                    #                                     'underlying_input_name': 'Static Bubbles',
                    #                                     'key': 'static_bubbles',
                    #                                     'ui_category_key': 'Bubbles',
                    #                                     'underlying_input_type': 'bool'},
                    #                                 'key': 'Static Bubbles',
                    #                                 'key_type': 'input_name'},
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': 10.0,
                    #                                     'underlying_input_name': 'Density',
                    #                                     'key': 'density',
                    #                                     'ui_category_key': 'Bubbles',
                    #                                     'underlying_input_type': 'float'},
                    #                                 'key': 'Density',
                    #                                 'key_type': 'input_name'},
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': 1.0,
                    #                                     'underlying_input_name': 'Scale',
                    #                                     'key': 'scale',
                    #                                     'ui_category_key': 'Bubbles',
                    #                                     'underlying_input_type': 'float'},
                    #                                 'key': 'Scale',
                    #                                 'key_type': 'input_name'},
                    #                             {
                    #                                 'data': {
                    #                                     'underlying_input_default_val': 0,
                    #                                     'underlying_input_name': 'Seed',
                    #                                     'key': 'seed',
                    #                                     'ui_category_key': 'Bubbles',
                    #                                     'underlying_input_type': 'int'},
                    #                                 'key': 'Seed',
                    #                                 'key_type': 'input_name'}],
                    #                         'key': 'Static Bubbles',
                    #                         'key_type': 'group_name'}],
                    #                 'key': 'GeoNode',
                    #                 'key_type': 'target_type'}],
                    #         'input_order': [
                    #             'Color',
                    #             'Intensity',
                    #             'Turbidity',
                    #             'Crystallization',
                    #             'Static Bubbles',
                    #             'Density',
                    #             'Scale',
                    #             'Seed']},
                    #     'key': 'Honey',
                    #     'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.955973,
                                                            0.814846,
                                                            0.401978],
                                                        'underlying_input_name': 'Color',
                                                        'key': 'color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 120.0,
                                                        'underlying_input_name': 'Intensity',
                                                        'key': 'intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Intensity',
                                                    'key_type': 'input_name'}],
                                            'key': 'Ice Tea',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color', 'Intensity']},
                        'key': 'Ice Tea',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            1.0,
                                                            0.98225,
                                                            0.226966],
                                                        'underlying_input_name': 'Color',
                                                        'key': 'color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.5,
                                                        'underlying_input_name': 'Pulp Particles Opacity',
                                                        'key': 'pulp_particles_opacity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Pulp Particles Opacity',
                                                    'key_type': 'input_name'}],
                                            'key': 'Lemonade',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color',
                                'Pulp Particles Opacity']},
                        'key': 'Lemonade',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 50.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Milk',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.854992,
                                                            0.799102,
                                                            0.114436],
                                                        'underlying_input_name': 'Color',
                                                        'key': 'color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 40.0,
                                                        'underlying_input_name': 'Intensity',
                                                        'key': 'intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Intensity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.1,
                                                        'underlying_input_name': 'Turbidity',
                                                        'key': 'turbidity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Turbidity',
                                                    'key_type': 'input_name'}],
                                            'key': 'Olive Oil',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'},
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Static Bubbles',
                                                        'key': 'static_bubbles',
                                                        'ui_category_key': 'Bubbles',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Static Bubbles',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 10.0,
                                                        'dependency': {
                                                            'group_name': 'Static Bubbles',
                                                            'input_name': 'Static Bubbles',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Quantity',
                                                        'key': 'quantity',
                                                        'ui_category_key': 'Bubbles',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Quantity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Static Bubbles',
                                                            'input_name': 'Static Bubbles',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Size',
                                                        'key': 'size',
                                                        'ui_category_key': 'Bubbles',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Size',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Static Bubbles',
                                                            'input_name': 'Static Bubbles',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Bubbles',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Static Bubbles',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color',
                                'Intensity',
                                'Turbidity',
                                'Static Bubbles',
                                'Quantity',
                                'Size',
                                'Seed']},
                        'key': 'Olive Oil',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 200.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.3,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            1.0,
                                                            0.337163,
                                                            0.026241],
                                                        'underlying_input_name': 'Juice Color',
                                                        'key': 'juice_color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Juice Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 3.0,
                                                        'underlying_input_name': 'Pulp Amount',
                                                        'key': 'pulp_amount',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Pulp Amount',
                                                    'key_type': 'input_name'}],
                                            'key': 'Juice Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed',
                                'Juice Color',
                                'Pulp Amount']},
                        'key': 'Orange Juice',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.2,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 110.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.396755,
                                                            0.088655,
                                                            0.135633],
                                                        'underlying_input_name': 'Juice Color',
                                                        'key': 'juice_color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Juice Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'underlying_input_name': 'Pulp Amount',
                                                        'key': 'pulp_amount',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Pulp Amount',
                                                    'key_type': 'input_name'}],
                                            'key': 'Juice Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed',
                                'Juice Color',
                                'Pulp Amount']},
                        'key': 'Red Fruit Smoothie',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.603827,
                                                            0.0,
                                                            0.038204],
                                                        'underlying_input_name': 'Color',
                                                        'key': 'color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 100.0,
                                                        'underlying_input_name': 'Intensity',
                                                        'key': 'intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Intensity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.1,
                                                        'underlying_input_name': 'Turbidity',
                                                        'key': 'turbidity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Turbidity',
                                                    'key_type': 'input_name'}],
                                            'key': 'Wine',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color',
                                'Intensity',
                                'Turbidity']},
                        'key': 'Red Wine',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            1.0,
                                                            0.396755,
                                                            0.187821],
                                                        'underlying_input_name': 'Color',
                                                        'key': 'color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 40.0,
                                                        'underlying_input_name': 'Intensity',
                                                        'key': 'intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Intensity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.1,
                                                        'underlying_input_name': 'Turbidity',
                                                        'key': 'turbidity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Turbidity',
                                                    'key_type': 'input_name'}],
                                            'key': 'Wine',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color',
                                'Intensity',
                                'Turbidity']},
                        'key': 'Rose Wine',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Carbonated',
                                                        'key': 'carbonated',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Carbonated',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 150.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Quantity',
                                                        'key': 'quantity',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Quantity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Size',
                                                        'key': 'size',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Size',
                                                    'key_type': 'input_name'}],
                                            'key': 'Carbonation_Static',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Carbonated',
                                'Quantity',
                                'Size']},
                        'key': 'Water',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 110.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.3,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal '
                                                    'Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.114435,
                                                            0.005605,
                                                            0.005605],
                                                        'underlying_input_name': 'Juice Color',
                                                        'key': 'juice_color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Juice Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'underlying_input_name': 'Pulp Amount',
                                                        'key': 'pulp_amount',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Pulp Amount',
                                                    'key_type': 'input_name'}],
                                            'key': 'Juice Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed',
                                'Juice Color',
                                'Pulp Amount']},
                        'key': 'Tomato Juice',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Carbonated',
                                                        'key': 'carbonated',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Carbonated',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 50.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Quantity',
                                                        'key': 'quantity',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Quantity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Carbonation_Static',
                                                            'input_name': 'Carbonated',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Size',
                                                        'key': 'size',
                                                        'ui_category_key': 'Carbonation',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Size',
                                                    'key_type': 'input_name'}],
                                            'key': 'Carbonation_Static',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 2.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': True,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 315.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': 1.0,
                                                #         'underlying_input_name': 'Bubbles',
                                                #         'key': 'bubbles',
                                                #         'ui_category_key': 'Foam',
                                                #         'underlying_input_type': 'float'},
                                                #     'key': 'Bubbles',
                                                #     'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Carbonated',
                                'Quantity',
                                'Size',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Unfiltered Beer',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.955973,
                                                            0.879622,
                                                            0.514918],
                                                        'underlying_input_name': 'Color',
                                                        'key': 'color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 230.0,
                                                        'underlying_input_name': 'Intensity',
                                                        'key': 'intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Intensity',
                                                    'key_type': 'input_name'}],
                                            'key': 'Whiskey',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color',
                                'Intensity']},
                        'key': 'Whiskey',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            1.0,
                                                            0.814846,
                                                            0.122139],
                                                        'underlying_input_name': 'Color',
                                                        'key': 'color',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 10.0,
                                                        'underlying_input_name': 'Intensity',
                                                        'key': 'intensity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Intensity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'underlying_input_name': 'Turbidity',
                                                        'key': 'turbidity',
                                                        'ui_category_key': 'Liquid',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Turbidity',
                                                    'key_type': 'input_name'}],
                                            'key': 'Wine',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color',
                                'Intensity',
                                'Turbidity']},
                        'key': 'White Wine',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 120.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal '
                                                    'Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                # 'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Strawberry Milkshake',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.5,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Amount',
                                                        'key': 'foam_amount',
                                                        'ui_category_key': 'Foam',
                                                        'subtype': 'percentage',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Amount',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'UberLiquid',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Displacement',
                                                        'key': 'foam_displacement',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam Displacement',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Utils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Foam',
                                                        'key': 'foam',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Foam',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Foam Center Distribution',
                                                        'key': 'foam_center_distribution',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Foam Center Distribution',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 120.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Bubbles Scale',
                                                        'key': 'bubbles_scale',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Bubbles Scale',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Normal Strength',
                                                        'key': 'normal_strength',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Normal '
                                                    'Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0,
                                                        'dependency': {
                                                            'group_name': 'Foam Shader Utils',
                                                            'input_name': 'Foam',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Seed',
                                                        'key': 'seed',
                                                        'ui_category_key': 'Foam',
                                                        'underlying_input_type': 'int'},
                                                    'key': 'Seed',
                                                    'key_type': 'input_name'}],
                                            'key': 'Foam Shader Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Foam',
                                'Foam Amount',
                                'Foam Displacement',
                                'Foam Center Distribution',
                                'Bubbles Scale',
                                # 'Bubbles',
                                'Normal Strength',
                                'Seed']},
                        'key': 'Coffee Milkshake',
                        'key_type': 'material/func_name'},
                {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        # 'underlying_input_default_val': 0,
                                                        'underlying_input_name': 'Wax Color',
                                                        'key': 'wax_color',
                                                        'ui_category_key': 'Wax',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Wax Color',
                                                    'key_type': 'input_name'},
                                            {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'underlying_input_name': 'Wax Roughness',
                                                        'key': 'wax_roughness',
                                                        'ui_category_key': 'Wax',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Wax Roughness',
                                                    'key_type': 'input_name'}],
                                            'key': 'Wax Utils',
                                            'key_type': 'group_name'}],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Wax Color',
                                'Wax Roughness',
                            ]},
                        'key': 'Wax',
                        'key_type': 'material/func_name'}],
                'key': 'liquids',
                'key_type': 'library'},
            {
                'data': [
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            1.0,
                                                            1.0,
                                                            1.0],
                                                        'underlying_input_name': 'Glass Color',
                                                        'key': 'glass_color',
                                                        'ui_category_key': 'Glass',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Glass Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'underlying_input_name': 'GlassDensity',
                                                        'key': 'glassdensity',
                                                        'ui_category_key': 'Glass',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'GlassDensity',
                                                    'key_type': 'input_name'}],
                                            'key': 'PatternedGlass',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'},
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'dependency': {
                                                            'group_name': 'RoughnessUtils',
                                                            'input_name': 'Custom Roughness Map',
                                                            'target_type': 'GeoNode',
                                                        },
                                                        'underlying_input_name': 'User Roughness Texture',
                                                        'key': 'user_roughness_texture',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'imgtex'},
                                                    'key': 'User Roughness Texture',
                                                    'key_type': 'input_name'}],
                                            'key': 'RoughnessImage_UV; RoughnessImage_Box',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            'abstract_01',
                                                            '1k',
                                                            'liquifeel'],
                                                        'dependency': {
                                                            'group_name': 'PatternUtils',
                                                            'input_name': 'Pattern',
                                                            'target_type': 'GeoNode'},
                                                        'enum_source_fpath_key': 'recipient_patterns',
                                                        'underlying_input_name': 'Pattern Texture; Pattern Texture Resolution; Pattern Library; User Pattern Texture',
                                                        'key': [
                                                            'pattern_texture',
                                                            'pattern_texture_resolution',
                                                            'pattern_library',
                                                            'user_pattern_texture'],
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'imgtex'},
                                                    'key': 'Pattern Texture; Pattern Texture Resolution; Pattern Library; User Pattern Texture',
                                                    'key_type': 'input_name'}],
                                            'key': 'PatternImage_UV; PatternImage_Box',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader Node',
                                    'key_type': 'target_type'},
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Pattern',
                                                        'key': 'pattern',
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Pattern',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        # 'underlying_input_default_val': 'UV',
                                                        # 'underlying_input_default_val': 0,
                                                        'underlying_input_default_val': 1,
                                                        'dependency': {
                                                            'group_name': 'PatternUtils',
                                                            'input_name': 'Pattern',
                                                            'target_type': 'GeoNode'},
                                                        'ui_to_underlying_val_mapping': ['UV', 'Box'],
                                                        'underlying_input_name': 'Mapping Type',
                                                        'key': 'mapping_type',
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'menu'},
                                                    'key': 'Mapping Type',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 'UVMap',
                                                        'dependency': [
                                                            {
                                                                'group_name': 'PatternUtils',
                                                                'input_name': 'Pattern',
                                                                'target_type': 'GeoNode'},
                                                            {
                                                                'eqv': 'UV',
                                                                'group_name': 'PatternUtils',
                                                                'input_name': 'Mapping',
                                                                'target_type': 'GeoNode'}],
                                                        'items_gen_f': 'get_object_uv_maps_items_f()',
                                                        'underlying_input_name': 'UV Name',
                                                        'key': 'uv_name',
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'string'},
                                                    'key': 'UV Name',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'PatternUtils',
                                                            'input_name': 'Pattern',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Use Vertex Group',
                                                        'key': 'use_vertex_group',
                                                        'ui_category_key': 'Pattern',
                                                        'tandem_default_set': {
                                                            'group_name': 'PatternUtils',
                                                            'input_name': 'Vertex Group',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_type': 'bool'},
                                                    'key': 'Use Vertex Group',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'dependency': [
                                                            {
                                                                'group_name': 'PatternUtils',
                                                                'input_name': 'Pattern',
                                                                'target_type': 'GeoNode'},
                                                            {
                                                                'group_name': 'PatternUtils',
                                                                'input_name': 'Use Vertex Group',
                                                                'target_type': 'GeoNode'}],
                                                        'items_gen_f': 'get_object_vertex_groups_items_f()',
                                                        'underlying_input_name': 'Vertex Group',
                                                        'key': 'vertex_group',
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'string'},
                                                    'key': 'Vertex Group',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'PatternUtils',
                                                            'input_name': 'Pattern',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Upper Limit',
                                                        'key': 'upper_limit',
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Upper Limit',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'dependency': {
                                                            'group_name': 'PatternUtils',
                                                            'input_name': 'Pattern',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Lower Limit',
                                                        'key': 'lower_limit',
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Lower Limit',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'dependency': {
                                                            'group_name': 'PatternUtils',
                                                            'input_name': 'Pattern',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Pattern Falloff',
                                                        'key': 'pattern_falloff',
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Pattern Falloff',
                                                    'key_type': 'input_name'}],
                                            'key': 'PatternUtils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'underlying_input_name': 'Custom Roughness Map',
                                                        'key': 'custom_roughness_map',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'bool',
                                                    },
                                                    'key': 'Custom Roughness Map',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        # 'underlying_input_default_val': 'UV',
                                                        # 'underlying_input_default_val': 0,
                                                        'underlying_input_default_val': 1,
                                                        'dependency': {
                                                            'group_name': 'RoughnessUtils',
                                                            'input_name': 'Custom Roughness Map',
                                                            'target_type': 'GeoNode',
                                                        },
                                                        'ui_to_underlying_val_mapping': ['UV', 'Box'],
                                                        'underlying_input_name': 'Mapping Type',
                                                        'key': 'mapping_type',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'menu',
                                                    },
                                                    'key': 'Mapping Type',
                                                    'key_type': 'input_name'}                                                # {
                                                #     'data': {
                                                #         'underlying_input_default_val': True,
                                                #         'dependency': {
                                                #             'group_name': 'RoughnessUtils',
                                                #             'input_name': 'Custom Roughness Map',
                                                #             'target_type': 'GeoNode',
                                                #         },
                                                #         'ui_to_underlying_val_mapping': {
                                                #             'Box': True,
                                                #             'UV': False
                                                #         },
                                                #         'underlying_input_name': 'UV/Box',
                                                #         'key': 'mapping',
                                                #         'ui_category_key': 'Roughness Pattern',
                                                #         'underlying_input_type': 'bool',
                                                #     },
                                                #     'key': 'Mapping',
                                                #     'key_type': 'input_name'}
                                                ,
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 'UVMap',
                                                        'dependency': [
                                                            {
                                                                'group_name': 'RoughnessUtils',
                                                                'input_name': 'Custom Roughness Map',
                                                                'target_type': 'GeoNode',
                                                            },
                                                            {
                                                                'eqv': 'UV',
                                                                'group_name': 'RoughnessUtils',
                                                                'input_name': 'Mapping',
                                                                'target_type': 'GeoNode',
                                                            }],
                                                        'items_gen_f': 'get_object_uv_maps_items_f()',
                                                        'underlying_input_name': 'UV Name',
                                                        'key': 'uv_name',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'string',
                                                    },
                                                    'key': 'UV Name',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'RoughnessUtils',
                                                            'input_name': 'Custom Roughness Map',
                                                            'target_type': 'GeoNode',
                                                        },
                                                        'underlying_input_name': 'Use Vertex Group',
                                                        'key': 'use_vertex_group',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'bool',
                                                    },
                                                    'key': 'Use Vertex Group',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'dependency': [
                                                            {
                                                                'group_name': 'RoughnessUtils',
                                                                'input_name': 'Custom Roughness Map',
                                                                'target_type': 'GeoNode',
                                                            },
                                                            {
                                                                'group_name': 'RoughnessUtils',
                                                                'input_name': 'Use Vertex Group',
                                                                'target_type': 'GeoNode',
                                                            }],
                                                        'items_gen_f': 'get_object_vertex_groups_items_f()',
                                                        'underlying_input_name': 'Vertex Group',
                                                        'key': 'vertex_group',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'string',
                                                    },
                                                    'key': 'Vertex Group',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'RoughnessUtils',
                                                            'input_name': 'Custom Roughness Map',
                                                            'target_type': 'GeoNode',
                                                        },
                                                        'underlying_input_name': 'Upper Limit',
                                                        'key': 'upper_limit',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'float',
                                                    },
                                                    'key': 'Upper Limit',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'dependency': {
                                                            'group_name': 'RoughnessUtils',
                                                            'input_name': 'Custom Roughness Map',
                                                            'target_type': 'GeoNode',
                                                        },
                                                        'underlying_input_name': 'Lower Limit',
                                                        'key': 'lower_limit',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'float',
                                                    },
                                                    'key': 'Lower Limit',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'dependency': {
                                                            'group_name': 'RoughnessUtils',
                                                            'input_name': 'Custom Roughness Map',
                                                            'target_type': 'GeoNode',
                                                        },
                                                        'underlying_input_name': 'Pattern Falloff',
                                                        'key': 'pattern_falloff',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'float',
                                                    },
                                                    'key': 'Pattern Falloff',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'RoughnessUtils',
                                                            'input_name': 'Custom Roughness Map',
                                                            'target_type': 'GeoNode',
                                                        },
                                                        'underlying_input_name': 'Tiling',
                                                        'key': 'tiling',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'float',
                                                    },
                                                    'key': 'Tiling',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.2,
                                                        'dependency': {
                                                            'group_name': 'RoughnessUtils',
                                                            'input_name': 'Custom Roughness Map',
                                                            'target_type': 'GeoNode',
                                                        },
                                                        'underlying_input_name': 'Roughness Strength',
                                                        'key': 'roughness_strength',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'float',
                                                    },
                                                    'key': 'Roughness Strength',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'dependency': {
                                                            'group_name': 'RoughnessUtils',
                                                            'input_name': 'Custom Roughness Map',
                                                            'target_type': 'GeoNode',
                                                        },
                                                        'underlying_input_name': 'Roughness Offset',
                                                        'key': 'roughness_offset',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'float',
                                                    },
                                                    'key': 'Roughness Offset',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': False,
                                                        'dependency': {
                                                            'group_name': 'RoughnessUtils',
                                                            'input_name': 'Custom Roughness Map',
                                                            'target_type': 'GeoNode',
                                                        },
                                                        'underlying_input_name': 'Invert Roughness',
                                                        'key': 'invert_roughness',
                                                        'ui_category_key': 'Roughness Pattern',
                                                        'underlying_input_type': 'bool',
                                                    },
                                                    'key': 'Invert Roughness',
                                                    'key_type': 'input_name'},
                                            ],
                                            'key': 'RoughnessUtils',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'PatternUtils',
                                                            'input_name': 'Pattern',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Lip Threshold',
                                                        'key': 'lip_threshold',
                                                        'linked_update_index': 0.0,
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'float',
                                                        # 'update_f': 'lip_threshold_update'
                                                    },
                                                    'key': 'Lip Threshold',
                                                    'key_type': 'input_name'}],
                                            'key': 'LiquiFeel_Select Outer',
                                            'key_type': 'group_name'},
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.5,
                                                        'dependency': {
                                                            'group_name': 'PatternUtils',
                                                            'input_name': 'Pattern',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Patttern Extrusion',
                                                        'key': 'patttern_extrusion',
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Patttern Extrusion',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'dependency': {
                                                            'group_name': 'PatternUtils',
                                                            'input_name': 'Pattern',
                                                            'target_type': 'GeoNode'},
                                                        'underlying_input_name': 'Pattern Tiling',
                                                        'key': 'pattern_size',
                                                        'ui_category_key': 'Pattern',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Pattern Tiling',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.55,
                                                        'underlying_input_name': 'IoR',
                                                        'key': 'ior',
                                                        'ui_category_key': 'Glass',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'IoR',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'underlying_input_name': 'Rim Darkness',
                                                        'key': 'rim_darkness',
                                                        'ui_category_key': 'Glass',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Rim Darkness',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'underlying_input_name': 'Dispersion',
                                                        'key': 'dispersion',
                                                        'ui_category_key': 'Glass',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Dispersion',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.01,
                                                        'underlying_input_name': 'Glass Roughness',
                                                        'key': 'glass_roughness',
                                                        'ui_category_key': 'Glass',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Glass Roughness',
                                                    'key_type': 'input_name'}],
                                            'key': 'GlassUtils',
                                            'key_type': 'group_name'},
                                    # {
                                    #         'data': [
                                    #             {
                                    #                 'data': {
                                    #                     'underlying_input_default_val': False,
                                    #                     'underlying_input_name': 'Condensation',
                                    #                     'key': 'condensation',
                                    #                     'ui_category_key': 'Droplets',
                                    #                     'underlying_input_type': 'bool'},
                                    #                 'key': 'Condensation',
                                    #                 'key_type': 'input_name'},
                                    #             {
                                    #                 'data': {
                                    #                     'underlying_input_default_val': 1000,
                                    #                     'dependency': {
                                    #                         'group_name': 'Condensation_V1.0',
                                    #                         'input_name': 'Condensation',
                                    #                         'target_type': 'GeoNode'},
                                    #                     'underlying_input_name': 'Density',
                                    #                     'key': 'density',
                                    #                     'ui_category_key': 'Droplets',
                                    #                     'underlying_input_type': 'float'},
                                    #                 'key': 'Density',
                                    #                 'key_type': 'input_name'},
                                    #             {
                                    #                 'data': {
                                    #                     'underlying_input_default_val': 0.1,
                                    #                     'dependency': {
                                    #                         'group_name': 'Condensation_V1.0',
                                    #                         'input_name': 'Condensation',
                                    #                         'target_type': 'GeoNode'},
                                    #                     'underlying_input_name': 'Scale',
                                    #                     'key': 'scale',
                                    #                     'ui_category_key': 'Droplets',
                                    #                     'underlying_input_type': 'float'},
                                    #                 'key': 'Scale',
                                    #                 'key_type': 'input_name'},
                                    #             {
                                    #                 'data': {
                                    #                     'underlying_input_default_val': 'Cold Drink',
                                    #                     'dependency': {
                                    #                         'group_name': 'Condensation_V1.0',
                                    #                         'input_name': 'Condensation',
                                    #                         'target_type': 'GeoNode'},
                                    #                     'underlying_input_name': 'Condensation Type',
                                    #                     'key': 'condensation_type',
                                    #                     'ui_category_key': 'Droplets',
                                    #                     'underlying_input_type': 'menu'},
                                    #                 'key': 'Condensation Type',
                                    #                 'key_type': 'input_name'},
                                    #             {
                                    #                 'data': {
                                    #                     'underlying_input_default_val': False,
                                    #                     'dependency': {
                                    #                         'group_name': 'Condensation_V1.0',
                                    #                         'input_name': 'Condensation',
                                    #                         'target_type': 'GeoNode'},
                                    #                     'underlying_input_name': 'Use Vertex Group',
                                    #                     'key': 'use_vertex_group',
                                    #                     'ui_category_key': 'Droplets',
                                    #                     'underlying_input_type': 'bool'},
                                    #                 'key': 'Use Vertex Group',
                                    #                 'key_type': 'input_name'},
                                    #             {
                                    #                 'data': {
                                    #                     'dependency': {
                                    #                         'group_name': 'Condensation_V1.0',
                                    #                         'input_name': 'Condensation',
                                    #                         'target_type': 'GeoNode'},
                                    #                     'underlying_input_name': 'Vertex Group',
                                    #                     'key': 'vertex_group',
                                    #                     'ui_category_key': 'Droplets',
                                    #                     'underlying_input_type': 'string'},
                                    #                 'key': 'Vertex Group',
                                    #                 'key_type': 'input_name'}],
                                    #         'key': 'Condensation_V1.0',
                                    #         'key_type': 'group_name'}
                                    ],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Glass Color',
                                'GlassDensity',
                                'Pattern Texture; Pattern Texture Resolution; Pattern Library; User Pattern Texture', # pattern
                                'Pattern',               # pattern
                                'Mapping Type',               # pattern
                                'UV Name',               # pattern
                                'Use Vertex Group',      # pattern
                                'Vertex Group',          # pattern
                                'Lip Threshold',         # pattern
                                'Patttern Extrusion',    # pattern
                                'Upper Limit',           # pattern
                                'Lower Limit',           # pattern
                                'Pattern Falloff',       # pattern
                                'Pattern Tiling',        # pattern
                                'User Roughness Texture', # roughness
                                'Custom Roughness Map', # roughness
                                'Mapping Type',            # roughness
                                'UV Name',            # roughness
                                'Use Vertex Group',   # roughness
                                'Vertex Group',       # roughness
                                'Upper Limit',        # roughness
                                'Lower Limit',        # roughness
                                'Pattern Falloff',    # roughness
                                'Tiling',             # roughness
                                'Roughness Strength', # roughness
                                'Roughness Offset', # roughness
                                'Invert Roughness', # roughness
                                'IoR',
                                'Rim Darkness',
                                'Dispersion',
                                'Glass Roughness',
                                # 'Condensation', # condensation
                                # 'Density',      # condensation
                                # 'Scale',        # condensation
                                # 'Condensation Type', # condensation
                                # 'Use Vertex Group',  # condensation
                                # 'Vertex Group',      # condensation
                            ]},
                        'key': 'Uber Glass',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': [
                                                            0.630863,
                                                            1.0,
                                                            0.964617],
                                                        'underlying_input_name': 'Color',
                                                        'key': 'color',
                                                        'ui_category_key': 'Controls',
                                                        'underlying_input_type': 'color'},
                                                    'key': 'Color',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.45,
                                                        'underlying_input_name': 'IOR',
                                                        'key': 'ior',
                                                        'ui_category_key': 'Controls',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'IOR',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'underlying_input_name': 'Roughness',
                                                        'key': 'roughness',
                                                        'ui_category_key': 'Controls',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Roughness',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.2,
                                                        'underlying_input_name': 'Color Intensity',
                                                        'key': 'color_intensity',
                                                        'ui_category_key': 'Controls',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Color Intensity',
                                                    'key_type': 'input_name'},
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 0.0,
                                                        'underlying_input_name': 'Cloudiness',
                                                        'key': 'cloudiness',
                                                        'ui_category_key': 'Controls',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Cloudiness',
                                                    'key_type': 'input_name'}],
                                            'key': 'PET',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'},
                                {
                                    'data': [
                                        # {
                                        #     'data': [
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': False,
                                        #                 'underlying_input_name': 'Condensation',
                                        #                 'key': 'condensation',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'bool'},
                                        #             'key': 'Condensation',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': 1000,
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Density',
                                        #                 'key': 'density',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'float'},
                                        #             'key': 'Density',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': 0.1,
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Scale',
                                        #                 'key': 'scale',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'float'},
                                        #             'key': 'Scale',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': 'Cold Drink',
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Condensation Type',
                                        #                 'key': 'condensation_type',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'menu'},
                                        #             'key': 'Condensation Type',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': False,
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Use Vertex Group',
                                        #                 'key': 'use_vertex_group',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'bool'},
                                        #             'key': 'Use Vertex Group',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Vertex Group',
                                        #                 'key': 'vertex_group',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'string'},
                                        #             'key': 'Vertex Group',
                                        #             'key_type': 'input_name'}],
                                        #     'key': 'Condensation_V1.0',
                                        #     'key_type': 'group_name'}
                                    ],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color',
                                'IOR',
                                'Roughness',
                                'Color Intensity',
                                'Cloudiness',
                                # 'Condensation', # condensation
                                # 'Density',      # condensation
                                # 'Scale',        # condensation
                                # 'Condensation Type', # condensation
                                # 'Use Vertex Group',  # condensation
                                # 'Vertex Group',      # condensation
                            ]},
                        'key': 'PET',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'underlying_input_name': 'Color Brightness',
                                                        'key': 'color_brightness',
                                                        'ui_category_key': 'Controls',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Color Brightness',
                                                    'key_type': 'input_name'}],
                                            'key': 'Brown Bottle',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'},
                                {
                                    'data': [
                                        # {
                                        #     'data': [
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': False,
                                        #                 'underlying_input_name': 'Condensation',
                                        #                 'key': 'condensation',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'bool'},
                                        #             'key': 'Condensation',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': 1000,
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Density',
                                        #                 'key': 'density',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'float'},
                                        #             'key': 'Density',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': 0.1,
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Scale',
                                        #                 'key': 'scale',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'float'},
                                        #             'key': 'Scale',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': 'Cold Drink',
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Condensation Type',
                                        #                 'key': 'condensation_type',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'menu'},
                                        #             'key': 'Condensation Type',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': False,
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Use Vertex Group',
                                        #                 'key': 'use_vertex_group',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'bool'},
                                        #             'key': 'Use Vertex Group',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Vertex Group',
                                        #                 'key': 'vertex_group',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'string'},
                                        #             'key': 'Vertex Group',
                                        #             'key_type': 'input_name'}],
                                        #     'key': 'Condensation_V1.0',
                                        #     'key_type': 'group_name'}
                                    ],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color Brightness',
                                # 'Condensation', # condensation
                                # 'Density',      # condensation
                                # 'Scale',        # condensation
                                # 'Condensation Type', # condensation
                                # 'Use Vertex Group',  # condensation
                                # 'Vertex Group',      # condensation
                            ]},
                        'key': 'Brown Bottle Glass',
                        'key_type': 'material/func_name'},
                    {
                        'data': {
                            'data': [
                                {
                                    'data': [
                                        {
                                            'data': [
                                                {
                                                    'data': {
                                                        'underlying_input_default_val': 1.0,
                                                        'underlying_input_name': 'Color Brightness',
                                                        'key': 'color_brightness',
                                                        'ui_category_key': 'Controls',
                                                        'underlying_input_type': 'float'},
                                                    'key': 'Color Brightness',
                                                    'key_type': 'input_name'}],
                                            'key': 'Green Bottle Glass',
                                            'key_type': 'group_name'}],
                                    'key': 'Shader NG',
                                    'key_type': 'target_type'},
                                {
                                    'data': [
                                        # {
                                        #     'data': [
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': False,
                                        #                 'underlying_input_name': 'Condensation',
                                        #                 'key': 'condensation',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'bool'},
                                        #             'key': 'Condensation',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': 1000,
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Density',
                                        #                 'key': 'density',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'float'},
                                        #             'key': 'Density',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': 0.1,
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Scale',
                                        #                 'key': 'scale',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'float'},
                                        #             'key': 'Scale',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': 'Cold Drink',
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Condensation Type',
                                        #                 'key': 'condensation_type',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'menu'},
                                        #             'key': 'Condensation Type',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'underlying_input_default_val': False,
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Use Vertex Group',
                                        #                 'key': 'use_vertex_group',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'bool'},
                                        #             'key': 'Use Vertex Group',
                                        #             'key_type': 'input_name'},
                                        #         {
                                        #             'data': {
                                        #                 'dependency': {
                                        #                     'group_name': 'Condensation_V1.0',
                                        #                     'input_name': 'Condensation',
                                        #                     'target_type': 'GeoNode'},
                                        #                 'underlying_input_name': 'Vertex Group',
                                        #                 'key': 'vertex_group',
                                        #                 'ui_category_key': 'Droplets',
                                        #                 'underlying_input_type': 'string'},
                                        #             'key': 'Vertex Group',
                                        #             'key_type': 'input_name'}],
                                        #     'key': 'Condensation_V1.0',
                                        #     'key_type': 'group_name'}
                                    ],
                                    'key': 'GeoNode',
                                    'key_type': 'target_type'}],
                            'input_order': [
                                'Color Brightness',
                                # 'Condensation', # condensation
                                # 'Density',      # condensation
                                # 'Scale',        # condensation
                                # 'Condensation Type', # condensation
                                # 'Use Vertex Group',  # condensation
                                # 'Vertex Group',      # condensation
                            ]},
                        'key': 'Green Bottle Glass',
                        'key_type': 'material/func_name'}],
                'key': 'solids',
                'key_type': 'library'}],
        'key': 'shading',
        'key_type': 'main_tab'}]

def lose_order__(data_in):
    if isinstance(data_in, dict) and 'input_order' in data_in.keys():
        return lose_order__(data_in['data'])
    elif isinstance(data_in, list): # I have to skip the dict !!!
        data_out = {}
        for e in data_in:
            data_out[e['key']] = lose_order__(e['data'])
        return data_out
    return data_in 

INPUT_FIELD_DATA = lose_order__(INPUT_FIELD_DATA__PRESERVING_ORDER)

## NODE SOCKET DATA --------------------------------------------------

socket_type_2_type_mapping = {'NodeSocketFloat': 'float',
                              'NodeSocketInt': 'int'}

with open(str(FPATHS['node_socket_data']), 'r') as f:
    NODE_SOCKET_DATA = json.load(f)

# AUGMENTATION WITH NODE SOCKET DATA -----------------------------

# for main_tab_key, main_tab_data in NODE_SOCKET_DATA.items():
#     for library_key, library_data in main_tab_data.items():
#         for mat_name, mat_data in library_data.items():
#             for target_type_key, target_type_data in mat_data.items():
#                 for group_name, group_data in target_type_data.items():
#                     for input_name, ns_input_data in group_data.items():
#                         socket_type = ns_input_data['socket_type']
#                         if socket_type in socket_type_2_type_mapping.keys():
#                             ns_input_data['type'] = socket_type_2_type_mapping[
#                                 socket_type]
#                         print()
#                         print(INPUT_FIELD_DATA[main_tab_key][library_key].keys())
#                         print()
#                         INPUT_FIELD_DATA[main_tab_key][library_key][target_type_key][group_name][input_name][
#                             'node_socket_data'] = ns_input_data

# print()
# print('INPUT_FIELD_DATA')
# pprint(INPUT_FIELD_DATA)
# print()

with open(str(FPATHS['input_ui_type_data']), 'r') as f:
    INPUT_UI_TYPE_DATA = json.load(f)

# !!! This probably needs to be changed to conserve the sorting_tag box category order in the input field ui
def get_sorting_tags(targets):
    sorting_tags = []
    for target in targets:
        for group in target['data']:
            for inpt in group['data']:
                sorting_tag = inpt['data']['ui_category_key']
                if sorting_tag not in sorting_tags:
                    sorting_tags.append(sorting_tag)
    return sorting_tags

# def get_sorting_tags(mat):
#     sorting_tags = set()
#     for target in mat['data']:
#         for group in target['data']:
#             sorting_tags.update(
#                 {inpt['data']['ui_category_key'] for inpt in group['data']})
#     return sorting_tags

def filter_input_data_by_sorting_tag(lib_key, mat_name, mat_data, sorting_tag):
    # print()
    # print('filter_input_data_by_sorting_tag')
    # print('mat_data:')
    # pprint(mat_data)
    # print()
    inputs_data = []
    targets = mat['data']['data']
    for target in targets:
        target_key = target['key']
        for group in target['data']:
            group_name = group['key']
            for inpt in group['data']:
                input_key = inpt['key']
                if inpt['data']['ui_category_key'] == sorting_tag:
                    inputs_data.append({
                        'input_key': input_key,
                        'library_key': lib_key,
                        'material_name': mat_name,
                        'target_type': target_key,
                        'group_name': group_name,
                        'input_data': inpt['data']
                    })
    inputs_data.sort(
        key=lambda e_dat: mat_data['data']['input_order'].index(e_dat['input_key']))
    return inputs_data

# print()
# print('INPUT_FIELD_DATA__PRESERVING_ORDER')
# pprint(INPUT_FIELD_DATA__PRESERVING_ORDER)
# print()

SHADING_INPUT_FIELD_DATA_BY_SORTING_TAG = {}
for tab in INPUT_FIELD_DATA__PRESERVING_ORDER:
    tab_key = tab['key']
    for lib in tab['data']:
        lib_key = lib['key']
        SHADING_INPUT_FIELD_DATA_BY_SORTING_TAG[lib_key] = {}
        for mat in lib['data']:
            mat_name = mat['key']
            SHADING_INPUT_FIELD_DATA_BY_SORTING_TAG[lib_key][mat_name] = {}
            sorting_tags = get_sorting_tags(mat['data']['data']) # the target_data list (Shader NG, Shader Node, Geonode)
            for s_tag in sorting_tags:
                SHADING_INPUT_FIELD_DATA_BY_SORTING_TAG[lib_key][mat_name][s_tag] = filter_input_data_by_sorting_tag(
                    lib_key, mat_name, mat, s_tag)

# print()
# print('SHADING_INPUT_FIELD_DATA_BY_SORTING_TAG')
# pprint(SHADING_INPUT_FIELD_DATA_BY_SORTING_TAG)
# print()


## ANIMATION ----------


# def update_hooks_from_obj(obj__):
#     hooks = []
#     if obj__.animation_data and obj__.animation_data.action:
#         for fcurve in obj__.animation_data.action.fcurves:
#             hooks.append(
#                 prop_value_update_f(obj__, fcurve.data_path))
#     return hooks

# def animation_prop_update_handler(scene):
#     update_hooks = []
#     for obj__ in filter(is_obj_liquifeel_asset, list(scene.objects)):
#         update_hooks.extend(
#             update_hooks_from_obj(obj__))
#     for hook in update_hooks:
#         hook()

# @persistent
# def animation_prop_update_handler(scene):
#     animation_prop_update_handler__(scene)

## REDUX_INPUT_DATA ----------

INPUT_SET_DATA = {}
for tab_key in INPUT_FIELD_DATA.keys():
    tab_input_set_data = {
        'object_attached': {},
        'material_attached': {},
    }
    for library_key, library_data in INPUT_FIELD_DATA[tab_key].items():
        for mat_name, mat_data in library_data.items():
            for target_key, target_data in mat_data.items(): # GeoNode, Shader NG, Shader Node
                if target_key == 'GeoNode':
                    target_attachment_key = 'object_attached'
                else:
                    target_attachment_key = 'material_attached'
                for group_name, group_data in target_data.items():
                    for input_name, input_data in group_data.items():
                        out_input_data = {
                            'path': [tab_key, library_key, mat_name, target_key,
                                     group_name, input_name],
                            'name': input_name,
                            'data': input_data,
                        }
                        if input_name in tab_input_set_data[target_attachment_key].keys():
                            tab_input_set_data[target_attachment_key][input_name].append(
                                out_input_data)
                        else:
                            tab_input_set_data[target_attachment_key][input_name] = [out_input_data]
    INPUT_SET_DATA[tab_key] = tab_input_set_data

def most_common(elems):
    return sorted(elems,
                  key=lambda elem: elems.count(elem),
                  reverse=True)[0]

path_as_mapping_keys = [
    "main_tab",
    "library",
    "material/func_name",
    "target_type",
    "group_name",
]
def path_as_mapping_from_path(path):
    return dict(zip(path_as_mapping_keys, path[:-1]))
data_branch_key_mapping = {
    'underlying_input_name': 'underlying_input_name',
    'prop_key': 'key',
    'ui_category_key': 'ui_category_key',
    'underlying_input_type': 'underlying_input_type',
    'underlying_input_subtype': 'subtype',
    # 'dependency': 'dependency',
}
def reduce_input_data(inputs_data):
    data = {
        'ui_input_name': most_common(
            [d['name'] for d in inputs_data]),
        'paths': [],
    }
    for d in inputs_data:
        data['paths'].append(
            {'list': d['path'],
             'mapping': path_as_mapping_from_path(d['path'])})
    for new_key, old_key in data_branch_key_mapping.items():
        if old_key in d['data'].keys():
            data[new_key] = most_common(
                [d['data'][old_key] for d in filter(
                    lambda d: old_key in d['data'].keys(),
                    inputs_data)])
    return data
# data_branch_key_mapping = {
#     'underlying_input_name': 'underlying_input_name',
#     'prop_key': 'key',
#     'ui_category_key': 'ui_category_key',
#     'underlying_input_type': 'type',
#     'underlying_input_subtype': 'subtype',
#     # 'dependency': 'dependency',
# }
# def reduce_input_data(inputs_data):
#     data = {
#         'ui_input_name': most_common(
#             [d['name'] for d in inputs_data]),
#         'paths': [],
#     }
#     for d in inputs_data:
#         data['paths'].append(
#             {'list': d['path'],
#              'mapping': path_as_mapping_from_path(d['path'])})
#     for new_key, old_key in data_branch_key_mapping.items():
#         if old_key in d['data'].keys():
#             data[new_key] = most_common(
#                 [d['data'][old_key] for d in filter(
#                     lambda d: old_key in d['data'].keys(),
#                     inputs_data)])
#     return data

# This is a function which recurses down a dictionary hierarchy and
# returns the leaf. If the leaf or some node is non existent, None is
# returned
def index_hierarchy_by_path(data, path):
    if path:
        key = path[0]
        if key in data.keys():
            return index_hierarchy_by_path(data[key],
                                           path[1:])
        else:
            # print('index_hierarchy_by_path')
            # print(f'key error: {key}')
            return None
    else:
        return data

def reduce_bounds_data_per_input(input_name, prop_scaffold, node_socket_data):
    redux_input_data = prop_scaffold[input_name]
    boundss = list(
        filter(bool,
               map(lambda i: index_hierarchy_by_path(node_socket_data,
                                                     redux_input_data['paths'][i]['list']),
                   range(len(redux_input_data['paths'])))))
    if boundss:
        if all(['max' in bounds for bounds in boundss]) and all(
                ['min' in bounds for bounds in boundss]):
            return {
                'max': max(map(lambda bounds: bounds['max'], boundss)),
                'min': min(map(lambda bounds: bounds['min'], boundss)),
            }

def augment_scaffold_with_reduced_node_socket_data(prop_scaffold, bounds_data):
    for input_name, redux_input_data in prop_scaffold.items():
        bounds = reduce_bounds_data_per_input(
            input_name, prop_scaffold, bounds_data)
        if bounds:
            redux_input_data['bounds'] = bounds

REDUX_INPUT_DATA = {
    'geometry': {'object_attached': {},
                 'material_attached': {}},
    'shading': {'object_attached': {},
                'material_attached': {}}}
for main_tab_key, main_tab_data in REDUX_INPUT_DATA.items():
    for target_attachment_key, target_attachment_data in main_tab_data.items():
        for input_name, inputs_data in INPUT_SET_DATA[main_tab_key][target_attachment_key].items():
            target_attachment_data[input_name] = reduce_input_data(inputs_data)
        # We add the elements which are common in the paths of the
        # different control inputs represented by the general inputs
        # we declare in these structures.
        for input_name, redux_input_data in target_attachment_data.items():
            paths_as_mappings = [path['mapping'] for path in redux_input_data['paths']]
            unanimous_path_data = {}
            for key in paths_as_mappings[0].keys():
                reference = paths_as_mappings[0][key]
                if all([mapping[key] == reference for mapping in paths_as_mappings]):
                    unanimous_path_data[key] = reference
            redux_input_data['unanimous_path_elems'] = unanimous_path_data
            # Now we add the ui types to the REDUX data structure.
            if input_name in INPUT_UI_TYPE_DATA[main_tab_key][target_attachment_key].keys():
                redux_input_data['ui_input_type'] = INPUT_UI_TYPE_DATA[
                    main_tab_key][target_attachment_key][input_name]
        # Here we attach input bounding data (to permit enabling
        # sliders on numeric props).
        augment_scaffold_with_reduced_node_socket_data(
            target_attachment_data, NODE_SOCKET_DATA)

# INPUT_FIELD_DATA augmentation with the data held by REDUX_INPUT_DATA

def invert_dict_mapping(mapping_dict):
    out_mapping = {}
    for k, v in mapping_dict.items():
        assert len(list(filter(lambda a: a==v, mapping_dict.values()))) == 1
        out_mapping[v] = k
    return out_mapping

for main_tab_key, main_tab_data in REDUX_INPUT_DATA.items():
    for target_attachment_key, target_attachment_data in main_tab_data.items():
        for input_name, redux_input_data in target_attachment_data.items():
            for path in redux_input_data['paths']:
                # augment INPUT_FIELD_DATA at path with redux_input_data.
                input_field_data = index_hierarchy_by_path(INPUT_FIELD_DATA, path['list'])
                input_field_data['redux_input_data_path'] = [
                    main_tab_key, target_attachment_key, input_name]
                input_field_data['prop_key'] = input_field_data['key']
                # input_field_data['underlying_input_type'] = input_field_data['underlying_input_type']
                if 'subtype' in input_field_data.keys():
                    input_field_data['underlying_input_subtype'] = input_field_data['subtype']
                for redux_indat_key in ['ui_input_name', 'ui_input_type']:
                    input_field_data[redux_indat_key] = redux_input_data[redux_indat_key]
                input_field_data['path'] = path
                if 'ui_to_underlying_val_mapping' in input_field_data.keys() and isinstance(
                        input_field_data['ui_to_underlying_val_mapping'], dict):
                    input_field_data['underlying_to_ui_val_mapping'] = invert_dict_mapping(
                        input_field_data['ui_to_underlying_val_mapping'])
                # Augmenting with the ui prop default vals
                if 'underlying_input_default_val' in input_field_data.keys():
                    if input_field_data['underlying_input_type'] == input_field_data[
                            'ui_input_type']:
                        input_field_data['ui_input_default_val'] = input_field_data[
                            'underlying_input_default_val']
                    elif 'underlying_to_ui_val_mapping' in input_field_data.keys():
                        input_field_data['ui_input_default_val'] = input_field_data[
                            'underlying_to_ui_val_mapping'][
                                input_field_data['underlying_input_default_val']]
                    else:
                        # as of 23.03.2024, the only inputs falling
                        # into this case are:
                        # ['UV Name',
                        #  'Pattern Texture; Pattern Texture Resolution; Pattern Library; User Pattern Texture']
                        # Which don't even need default setting. we
                        # won't set defaults for them.
                        pass

# -----------------------------------------------------------------------------
# UNDERLYING INPUT IDENTIFICATION AT RUNTIME


# -----------------------------------------------------------------------------
# INPUT SETTING FUNCTION AUGMENTATION
# We're augmenting the INPUT_FIELD_DATA structure with input setters.

# Why write functions when we can write data?
get_target_attachment_key = {
    'Shader Node': 'material_attached',
    'Shader NG': 'material_attached',
    'GeoNode': 'object_attached',
}

# We're supposed to take the material from the object. The question
# is: what do we do when the material is not in the object's material
# slots, but instead assigned through geometry nodes?
# I guess that instead of taking it from the slots, we shall take it
# from the fill modififer.

def get_library_key_and_material_name(obj__, path_as_mapping=None, shading_modality_key=None):
    if not(path_as_mapping) and shading_modality_key:
        prop_key_chain = [
            'liquifeel_input_field_props',
            'shading', shading_modality_key, 'manual', 'material_selector']
        library_key = getattr_rec(
            obj__, prop_key_chain + ['library'])
        material_name = getattr_rec(
            obj__, prop_key_chain + [f'{library_key}_material'])
    else:
        library_key = path_as_mapping['library']
        material_name = path_as_mapping['material/func_name']
    return library_key, material_name

def hrdc_get_library_key_and_material_name(obj__, path_as_mapping=None, shading_modality_key=None):
    if not(path_as_mapping) and shading_modality_key:
        prop_key_chain = [
            'hrdc_liquifeel_input_field_props', 'shading', shading_modality_key]
        # prop_key_chain = [
        #     'liquifeel_input_field_props',
        #     'shading', shading_modality_key, 'manual', 'material_selector']
        library_key = getattr_rec(
            obj__, prop_key_chain + ['library'])
        material_name = getattr_rec(
            obj__, prop_key_chain + [f'{library_key}_material'])
    else:
        library_key = path_as_mapping['library']
        material_name = path_as_mapping['material/func_name']
    return library_key, material_name

def get_asset_material(obj__, path_as_mapping=None, shading_modality_key=None):
    # print()
    # print(f'get_asset_material(obj__={obj__}, path_as_mapping={path_as_mapping}, shading_modality_key={shading_modality_key})')
    library_key, material_name = get_library_key_and_material_name(
        obj__, path_as_mapping=path_as_mapping, shading_modality_key=shading_modality_key)
    # print(library_key, material_name)
    # print()
    if shading_modality_key == 'slot':
        material_pool = list(obj__.data.materials)
        for mat in material_pool:
            if 'liquifeel' in mat.keys():
                # if material_name in mat['liquifeel']['name']:
                if mat['liquifeel']['name'] == material_name:
                    return mat
        # print(f"material {mat_name} not found in the material slots of object {obj__.name}!")
    elif shading_modality_key == 'fill':
        mat = get_geonode_mod_input(obj__, FILL_NG_NAME, 'Liquid Shader')
        return mat

def hrdc_get_asset_material(obj__, path_as_mapping=None, shading_modality_key=None):
    # print()
    # print(f'get_asset_material(obj__={obj__}, path_as_mapping={path_as_mapping}, shading_modality_key={shading_modality_key})')
    library_key, material_name = hrdc_get_library_key_and_material_name(
        obj__, path_as_mapping=path_as_mapping, shading_modality_key=shading_modality_key)
    # print(library_key, material_name)
    # print()
    if shading_modality_key == 'slot':
        material_pool = list(obj__.data.materials)
        for mat in material_pool:
            if 'liquifeel' in mat.keys():
                # if material_name in mat['liquifeel']['name']:
                if mat['liquifeel']['name'] == material_name:
                    return mat
        # print(f"material {mat_name} not found in the material slots of object {obj__.name}!")
    elif shading_modality_key == 'fill':
        mat = get_geonode_mod_input(obj__, FILL_NG_NAME, 'Liquid Shader')
        return mat

def get_prop_vals(prop_parent, key):
    if isinstance(key, list):
        return {k:getattr(prop_parent, k) for k in key}
    else:
        return getattr(prop_parent, key)

def are_user_defined_maps_present(map_category_key):
    return any(map(lambda im: is_user_defined_image(im, map_category_key),
                   bpy.data.images))

# def are_user_defined_patterns_present():
#     return any(map(lambda im: is_user_defined_image(im, 'pattern'),
#                    bpy.data.images))

# def filter_path_by_material_name(redux_input_data, mat_name):
#     return next(filter(
#         lambda path: path['mapping']['material/func_name'] == mat_name,
#         map(lambda path_: path_,
#             redux_input_data['paths'])))

def filter_path_as_mapping_by_material_name(redux_input_data, mat_name):
    return next(filter(
        lambda pam: pam['material/func_name'] == mat_name,
        map(lambda path: path['mapping'],
            redux_input_data['paths'])))

# GEONODE v

def set_vectorial_prop_value(prop_parent, prop_key, value):
    input_ = getattr(prop_parent, prop_key)
    for i in range(len(value)):
        input_[i] = value[i]

def set_scalar_prop_value(prop_parent, prop_key, value):
    # print(f'set_scalar_prop_value({prop_parent}, {prop_key}, {value})')
    setattr(prop_parent, prop_key, value)

def set_prop_value(prop_parent, prop_key, value, ui_input_type):
    if ui_input_type in ['vector', 'color']:
        set_vectorial_prop_value(prop_parent, prop_key, value)
    else: # int, float, bool, string
        set_scalar_prop_value(prop_parent, prop_key, value)

# Blender 5.x: geometry nodes modifier inputs moved from id properties on the
# modifier (mod[identifier]) to mod.properties.inputs.<identifier>.value
GEONODE_INPUTS_VIA_PROPERTIES = 'properties' in bpy.types.NodesModifier.bl_rna.properties

def get_geonode_mod_input_prop(mod, identifier):
    return getattr(mod.properties.inputs, identifier)

def geonode_input_get(mod, identifier):
    if GEONODE_INPUTS_VIA_PROPERTIES:
        prop = get_geonode_mod_input_prop(mod, identifier)
        rna_val = prop.bl_rna.properties['value']
        if rna_val.type == 'ENUM':
            # menu inputs used to be stored as int indices
            return rna_val.enum_items.find(prop.value)
        return prop.value
    return mod[identifier]

def geonode_input_set(mod, identifier, value):
    if GEONODE_INPUTS_VIA_PROPERTIES:
        prop = get_geonode_mod_input_prop(mod, identifier)
        rna_val = prop.bl_rna.properties['value']
        if rna_val.type == 'ENUM' and not isinstance(value, str):
            value = rna_val.enum_items[value].identifier
        prop.value = value
        # writing .value does not tag the depsgraph, the modifier
        # would not re-evaluate without this
        mod.id_data.update_tag()
    else:
        mod[identifier] = value

def geonode_input_set_component(mod, identifier, index, value):
    if GEONODE_INPUTS_VIA_PROPERTIES:
        get_geonode_mod_input_prop(mod, identifier).value[index] = value
        mod.id_data.update_tag()
    else:
        mod[identifier][index] = value

def set_geonode_mod_vectorial_input(mod, identifier, value):
    for i in range(len(value)):
        geonode_input_set_component(mod, identifier, i, value[i])

def set_geonode_mod_scalar_input(mod, identifier, value):
    geonode_input_set(mod, identifier, value)

# def set_geonode_mod_menu_input(mod, identifier, value, input_data):
#     mod[identifier] = input_data['items'].index(value)

geonode_mod_setters = {
    'bool': set_geonode_mod_scalar_input,
    'int': set_geonode_mod_scalar_input,
    'float': set_geonode_mod_scalar_input,
    'color': set_geonode_mod_vectorial_input, # only vec. thus far
    'string': set_geonode_mod_scalar_input,
    # 'menu': set_geonode_mod_menu_input, # aparently there was no need for a new setter.
    'menu': set_geonode_mod_scalar_input,
}

def set_geonode_mod_input_to_value(mod, identifier, value, underlying_input_type):
    geonode_mod_setters[underlying_input_type](
        mod, identifier, value)
# def set_geonode_mod_input_to_value(mod, identifier, value, underlying_input_type, input_data):
#     geonode_mod_setters[underlying_input_type](
#         mod, identifier, value, input_data)

def set_shader_ng_input_to_value(ng, input_name, value, underlying_input_type):
    if underlying_input_type == 'color' or underlying_input_type == 'vector':
        for i in range(len(value)):
            ng.inputs[input_name].default_value[i] = value[i]
    else:
        ng.inputs[input_name].default_value = value

# All of the setters below should take these params:
# obj__, material, prop_parent, val, input_field_data, redux_input_data, target_attachment_key, shading_modality_key

def set_geonode_mod_input_to_value__general_params(
        obj__, material, prop_parent, val,
        input_field_data, redux_input_data,
        target_attachment_key, shading_modality_key):
    mod = get_geonodes_mod_by_ng_name(
        obj__, input_field_data['path']['mapping']['group_name']) 
    identifier = get_geonodes_field_identifier(
        mod, input_field_data['underlying_input_name'])
    if input_field_data['ui_input_type'] != input_field_data['underlying_input_type']:
        val = input_field_data['ui_to_underlying_val_mapping'][val]
    set_geonode_mod_input_to_value(
        mod, identifier, val, input_field_data['underlying_input_type'])
    # set_geonode_mod_input_to_value(
    #     mod, identifier, val, input_field_data['underlying_input_type'], input_field_data)

def set_geonode_mod_input(obj__, mod_name, input_name, input_type_key, value):
    mod = get_geonodes_modifier__by_mod_name(obj__, mod_name)
    identifier = get_geonodes_field_identifier(mod, input_name)
    if input_type_key == 'color':
        set_geonode_color_input(mod, identifier, value)
    else:
        geonode_input_set(mod, identifier, value)

# def set_geonode_mod_input__at_prop_update(
#         obj__, prop_parent, input_name, redux_input_data, target_attachment_key, shading_modality_key):
#     # debug_buffer.append(redux_input_data) # DEBUG !!!
#     if 'material/func_name' in redux_input_data['unanimous_path_elems'].keys():
#         # ng_name = redux_input_data['paths'][0]['mapping']['group_name']
#         ng_name = redux_input_data['unanimous_path_elems']['group_name']
#         path = redux_input_data['paths'][0]['list']
#     else: # It's shading input
#         material = get_asset_material(
#             obj__,
#             shading_modality_key=shading_modality_key)
#         # debug_buffer.append(
#         #     {'obj__': obj__,
#         #      'shading_modality_key': shading_modality_key,
#         #      'material': material}
#         # ) # !!! DEBUG
#         mat_name = material['liquifeel']['name']
#         path = filter_path_by_material_name(redux_input_data, mat_name)
#         ng_name = path['mapping']['group_name']
#     input_field_data = index_hierarchy_by_path(INPUT_FIELD_DATA, path)
#     val__ = get_prop_vals(prop_parent, redux_input_data['prop_key'])
#     mod = get_geonodes_mod_by_ng_name(obj__, ng_name)
#     identifier = get_geonodes_field_identifier(mod, redux_input_data['underlying_input_name'])
#     if input_data['type'] == 'color': # or <in ['vector', 'color']> but we have no vectors so far
#         set_geonode_color_input(mod, identifier, val__)
#     else:
#         mod[identifier] = val__


# def set_geonode_mod_input__at_prop_update(
#         obj__, prop_parent, input_name, redux_input_data, target_attachment_key, shading_modality_key):
#     # debug_buffer.append(redux_input_data) # DEBUG !!!
#     if 'material/func_name' in redux_input_data['unanimous_path_elems'].keys():
#         # ng_name = redux_input_data['paths'][0]['mapping']['group_name']
#         ng_name = redux_input_data['unanimous_path_elems']['group_name']
#     else: # It's shading input
#         material = get_asset_material(
#             obj__,
#             shading_modality_key=shading_modality_key)
#         # debug_buffer.append(
#         #     {'obj__': obj__,
#         #      'shading_modality_key': shading_modality_key,
#         #      'material': material}
#         # ) # !!! DEBUG
#         mat_name = material['liquifeel']['name']
#         path_as_mapping = filter_path_as_mapping_by_material_name(redux_input_data, mat_name)
#         ng_name = path_as_mapping['group_name']
#     val__ = get_prop_vals(prop_parent, redux_input_data['prop_key'])
#     mod = get_geonodes_mod_by_ng_name(obj__, ng_name)
#     identifier = get_geonodes_field_identifier(mod, redux_input_data['underlying_input_name'])
#     if input_data['type'] == 'color': # or <in ['vector', 'color']> but we have no vectors so far
#         set_geonode_color_input(mod, identifier, val__)
#     else:
#         mod[identifier] = val__

# def set_shader_node_input(
#         obj__, prop_parent, input_name, redux_input_data, material, val=None):
#     mat_name = material['liquifeel']['name']
#     path_as_mapping = filter_path_as_mapping_by_material_name(redux_input_data, mat_name)
#     node_names = path_as_mapping['group_name']
#     # This is because an input can affect multiple nodes simultaneouslty
#     nodes = [get_material_node(material, node_name.strip()) for node_name in node_names.split(';')]
#     # I thik that checking this edge case every time the function runs
#     # is not ergonomic. There is a single input of this type in the
#     # whole program and the best couse of action would be to handle it
#     # on it's own. But i;m letting it be for now because this function
#     # is only called for one input (pattern imgtex), because that is
#     # the only material node input in the whole program.
#     if input_data['underlying_input_type'] == 'imgtex':
#         if not val:
#             val_data = get_prop_vals(prop_parent, ["pattern_texture_resolution", "pattern_library"])
#         else:
#             val_data = val
#         res_key = val_data['pattern_texture_resolution']
#         pat_lib_key = val_data['pattern_library']
#         if pat_lib_key == 'user_defined' and are_user_defined_patterns_present():
#             img_key = get_prop_vals(prop_parent, "user_pattern_texture")
#             img = bpy.data.images[img_key]
#             img_tex_fpath = img.filepath_from_user()
#             assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)
#         elif pat_lib_key == 'liquifeel':
#             img_key = get_prop_vals(prop_parent, "pattern_texture")
#             img_tex_fpath = FPATHS[
#                 input_data['enum_source_fpath_key']][img_key][res_key]
#             img = maybe_load_image(img_tex_fpath)
#             assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)
#     if input_data['underlying_input_type'] == 'color':
#         pass
#     if input_data['underlying_input_type'] == 'vector':
#         pass
#     else:
#         pass

def set_shader_node_input(
        obj__, prop_parent, input_name, redux_input_data, material, val=None):
    mat_name = material['liquifeel']['name']
    path_as_mapping = filter_path_as_mapping_by_material_name(redux_input_data, mat_name)
    node_names = path_as_mapping['group_name']
    # This is because an input can affect multiple nodes simultaneouslty
    nodes = [get_material_node(material, node_name.strip()) for node_name in node_names.split(';')]
    # I thik that checking this edge case every time the function runs
    # is not ergonomic. There is a single input of this type in the
    # whole program and the best couse of action would be to handle it
    # on it's own. But i;m letting it be for now because this function
    # is only called for one input (pattern imgtex), because that is
    # the only material node input in the whole program.
    if input_data['underlying_input_type'] == 'imgtex':
        if not val:
            val_data = get_prop_vals(prop_parent, ["pattern_texture_resolution", "pattern_library"])
        else:
            val_data = val
        res_key = val_data['pattern_texture_resolution']
        pat_lib_key = val_data['pattern_library']
        # if pat_lib_key == 'user_defined' and are_user_defined_patterns_present():
        if pat_lib_key == 'user_defined' and are_user_defined_maps_present('pattern'):
            img_key = get_prop_vals(prop_parent, "user_pattern_texture")
            img = bpy.data.images[img_key]
            img_tex_fpath = img.filepath_from_user()
            assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)
        elif pat_lib_key == 'liquifeel':
            img_key = get_prop_vals(prop_parent, "pattern_texture")
            img_tex_fpath = FPATHS[
                input_data['enum_source_fpath_key']][img_key][res_key]
            img = maybe_load_image(img_tex_fpath)
            assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)
    if input_data['underlying_input_type'] == 'color':
        pass
    if input_data['underlying_input_type'] == 'vector':
        pass
    else:
        pass





    # We probably only need to pass the shading modality key to the
    # shader node setters.  This is because the geonode mods are all
    # together in the same stack regardless of shading modality. This
    # is unfortunate, because it prevents us from giving both the
    # glass and the recipient the same compound material
    # (i.e. beer). But this also means that when the geonode mod input
    # is set (either from it's corresponding slot or fill prop) the
    # same input should be altered regardless.


def set_shader_ng_input_to_value__general_params(
        obj__, material, prop_parent, val,
        input_field_data, redux_input_data,
        target_attachment_key, shading_modality_key):
    mat_name = material['liquifeel']['name']
    ng_name = input_field_data['path']['mapping']['group_name']
    ng = get_shader_ng_by_name(material, ng_name)
    field_name = redux_input_data['underlying_input_name']
    underlying_type = redux_input_data['underlying_input_type']
    if input_field_data['ui_input_type'] != input_field_data['underlying_input_type']:
        val = input_field_data['ui_to_underlying_val_mapping'][val]
    if underlying_type == 'color' or underlying_type == 'vector':
        for i in range(len(val_data)):
            ng.inputs[field_name].default_value[i] = val_data[i]
    else:
        ng.inputs[field_name].default_value = val_data

def set_shader_node_input_to_value__general_params(
        obj__, material, prop_parent, val,
        input_field_data, redux_input_data,
        target_attachment_key, shading_modality_key):
    set_shader_node_input(
        obj__, prop_parent, input_field_data['ui_input_name'], redux_input_data, material, val=val)

underlying_input_setters = {
    'GeoNode': set_geonode_mod_input_to_value__general_params,
    'Shader NG': set_shader_ng_input_to_value__general_params,
    'Shader Node': set_shader_node_input_to_value__general_params,
}

# GEONODE ^
# SHADER_NODE v

# def set_pattern_imgtex

# SHADER_NODE ^
# SHADER_NG v

# SHADER_NG ^

# def set_input_to_default_f(input_data):
#     pass

# def set_input_from_ui_prop_f(input_data):
#     pass

# 'int'
# 'enum'
# 'float'
# 'bool'
# 'float'
# 'color'
# 'bool'
# 'string'
# 'imgtex

# setter_pack_gens = {
#     ('int', 'int'): ,
#     ('enum', 'enum'): ,
#     ('float', 'float'): ,
#     ('bool', 'bool'): ,
#     ('bool', 'float'): ,
#     ('color', 'color'): ,
#     ('enum', 'bool'): ,
#     ('enum', 'string'): ,
#     ('enum', 'imgtex'): ,
# }

# This clojure and it's siblings should only be used on input data
# which does present default values. There are some inputs which
# don't.
def gen_setter__ui_prop_from_default_val(input_field_data):
    if input_field_data['ui_input_default_val'] in ['vector', 'color']:
        setter = set_vectorial_prop_value
    else:
        setter = set_scalar_prop_value
    default_val = input_field_data['ui_input_default_val']
    prop_key = input_field_data['prop_key']
    def set(prop_parent):
        setter(prop_parent, prop_key, default_val)
    return set

# geonode:     obj__, prop_parent, input_name, redux_input_data, target_attachment_key, shading_modality_key
# shader_node: obj__, prop_parent, input_name, redux_input_data, target_attachment_key, shading_modality_key
# shader_ng:   obj__, prop_parent, input_name, redux_input_data, target_attachment_key, shading_modality_key

# Actually, i don't think i need these
# below. gen_setter__ui_prop_from_default_val was the critical one.

def gen_setter__underlying_input_from_ui_prop(input_field_data, shading_modality_key):
    input_name = input_field_data['ui_input_name']
    redux_input_data = index_hierarchy_by_path(
        REDUX_INPUT_DATA, input_field_data['redux_input_data_path'])
    target_type_name = input_field_data['path']['mapping']['target_type']
    prop_key = input_field_data['prop_key']
    setter = underlying_input_setters[target_type_name]
    target_attachment_key = get_target_attachment_key[target_type_name]
    def set(prop_parent, context):
        obj__ = context.active_object
        material = get_asset_material(obj__, shading_modality_key=shading_modality_key)
        val = getattr(prop_parent, prop_key)
        setter(obj__, material, prop_parent, val, input_field_data, redux_input_data, target_attachment_key, shading_modality_key)
    return set

# def gen_setter__underlying_input_from_ui_prop(input_field_data, shading_modality_key):
#     input_name = input_field_data['ui_input_name']
#     redux_input_data = index_hierarchy_by_path(
#         REDUX_INPUT_DATA, input_field_data['redux_input_data_path'])
#     target_type_name = input_field_data['path']['mapping']['target_type']
#     prop_key = input_field_data['prop_key']
#     setter = underlying_input_setters[target_type_name]
#     target_attachment_key = get_target_attachment_key[target_type_name]
#     def set(prop_parent, obj__, material):
#         # obj__ = context.active_object
#         # material = get_asset_material(obj__, shading_modality_key=shading_modality_key)
#         val = getattr(prop_parent, prop_key)
#         setter(obj__, material, prop_parent, val, input_field_data, redux_input_data, target_attachment_key, shading_modality_key)
#     return set

def gen_setter__underlying_input_to_default(input_field_data, shading_modality_key):
    input_name = input_field_data['ui_input_name']
    redux_input_data = index_hierarchy_by_path(
        REDUX_INPUT_DATA, input_field_data['redux_input_data_path'])
    target_type_name = input_field_data['path']['mapping']['target_type']
    prop_key = input_field_data['prop_key']
    setter = underlying_input_setters[target_type_name]
    target_attachment_key = get_target_attachment_key[target_type_name]
    val = input_field_data['underlying_input_default_val']
    def set(prop_parent, obj__, material):
        # obj__ = context.active_object
        # material = get_asset_material(obj__, shading_modality_key=shading_modality_key)
        setter(obj__, material, prop_parent, val, input_field_data, redux_input_data, target_attachment_key, shading_modality_key)
    return set

input_types_wo_default_ui_prop_setter = ['imgtex']
def gen_input_setters(input_field_data):
    setters = {}
    if 'ui_input_default_val' in input_field_data.keys() and input_field_data[
            'ui_input_default_val'] not in input_types_wo_default_ui_prop_setter:
        ui_prop_from_default_setter = gen_setter__ui_prop_from_default_val(
            input_field_data)
        setters['ui_prop_from_default'] = ui_prop_from_default_setter
    per_shading_modality = {'slot': {}, 'fill': {}}
    for shading_modality_key in ['slot', 'fill']:
        underlying_from_ui_prop_setter = gen_setter__underlying_input_from_ui_prop(
            input_field_data, shading_modality_key)
        per_shading_modality[shading_modality_key]['underlying_from_ui_prop'] = underlying_from_ui_prop_setter
        if 'underlying_input_default_val' in input_field_data.keys():
            underlying_to_default_setter = gen_setter__underlying_input_to_default(
                input_field_data, shading_modality_key)
            per_shading_modality[shading_modality_key]['underlying_from_default'] = underlying_to_default_setter
    setters['per_shading_modality'] = per_shading_modality
    return setters

for main_tab_key, main_tab_data in REDUX_INPUT_DATA.items():
    for target_attachment_key, target_attachment_data in main_tab_data.items():
        for input_name, redux_input_data in target_attachment_data.items():
            for path in [p['list'] for p in redux_input_data['paths']]:
                # augment INPUT_FIELD_DATA at path with setters
                input_field_data = index_hierarchy_by_path(INPUT_FIELD_DATA, path)
                input_field_data['setters'] = gen_input_setters(input_field_data)

#!# MANAGERS --------------------------------------------------------------------------------
## DYNAMIC DATA --------------------------------------------------------------------------------

## PREVIEW -----------------------------

# Don't delete the code below, even if it's not directly part of liquifeel, it is helpful.

# from PIL import Image

# # This has nothing to do with liquifeel at runtime, it's a development aid
# def invert_icon(fpath):
#     im = Image.open(fpath)
#     arr = np.array(im)
#     arr[:, :, :3] = (255, 255, 255)
#     im = Image.fromarray(arr)
#     im.save(fpath)

# # This has nothing to do with liquifeel at runtime, it's a development aid
# def invert_icons(folderpath):
#     for fname in os.listdir(folderpath):
#         invert_icon(folderpath / fname)

def new_preview_collection(*args):
    preview = previews.new()
    if len(args) == 1:
        path = args[0]
        preview.images_location = str(path)
    return preview

def load_image_and_get_id(preview_collection, fpath, img_key):
    img = preview_collection.load(
        img_key,
        str(fpath),
        'IMAGE')
    return img.icon_id

def load_images_and_assemble_ids(preview_collection, filepath_data, fpath_preprocess_f=None, img_key_f=None):
    ids = {}
    for img_key in filepath_data.keys():
        if fpath_preprocess_f:
            fpath = fpath_preprocess_f(filepath_data, img_key)
        else:
            fpath = filepath_data[img_key]
        k = img_key_f(img_key) if img_key_f else img_key
        ids[k] = load_image_and_get_id(preview_collection,
                                       fpath,
                                       k)
    return ids

preview_collections = {}
preview_img_ids = {}

def get_recipient_asset_key_from_thumbnail_name(thumbnail_name):
    return next(filter(lambda key: RECIPIENT_ASSET_NAME_DATA[key]['thumbnail'] == thumbnail_name,
                       RECIPIENT_ASSET_NAME_DATA.keys()))

def _load_preview_collections():
    # Loaded in register() (not at import) so enabling the addon has no
    # side effects and unregister() can release the ~120 images cleanly.
    if preview_collections:
        return  # already loaded (idempotent across enable/disable cycles)
    preview_collections['icons'] = new_preview_collection(FPATHS['icons_root'])
    preview_img_ids['icons'] = load_images_and_assemble_ids(
        preview_collections['icons'], FPATHS['icons'])

    preview_collections['material_thumbnails'] = new_preview_collection(
        FPATHS['material_thumbnails_root'])
    preview_img_ids['material_thumbnails'] = load_images_and_assemble_ids(
        preview_collections['material_thumbnails'], FPATHS['material_thumbnails'])

    preview_collections['pattern_thumbnails'] = new_preview_collection(
        FPATHS['recipient_patterns_root'])
    preview_img_ids['pattern_thumbnails'] = load_images_and_assemble_ids(
        preview_collections['pattern_thumbnails'],
        FPATHS['recipient_patterns'],
        fpath_preprocess_f=lambda fpath_data, key: fpath_data[key]['256'])

    preview_collections['roughness_thumbnails'] = new_preview_collection(
        FPATHS['recipient_roughness_maps_root'])
    preview_img_ids['roughness_thumbnails'] = load_images_and_assemble_ids(
        preview_collections['roughness_thumbnails'],
        FPATHS['recipient_roughness_maps'],
        fpath_preprocess_f=lambda fpath_data, key: fpath_data[key]['256'])

    # Populated dynamically; empty at load time.
    preview_collections['user_defined_pattern_thumbnails'] = new_preview_collection()
    preview_img_ids['user_defined_pattern_thumbnails'] = {}
    preview_collections['user_defined_roughness_thumbnails'] = new_preview_collection()
    preview_img_ids['user_defined_roughness_thumbnails'] = {}

    preview_collections['recipient_asset_thumbnails'] = new_preview_collection(
        FPATHS['recipient_asset_thumbnails_root'])
    preview_img_ids['recipient_asset_thumbnails'] = load_images_and_assemble_ids(
        preview_collections['recipient_asset_thumbnails'],
        FPATHS['recipient_asset_thumbnails'],
        img_key_f=get_recipient_asset_key_from_thumbnail_name)

def _unload_preview_collections():
    for pcol in preview_collections.values():
        try:
            previews.remove(pcol)
        except Exception:
            pass
    preview_collections.clear()
    preview_img_ids.clear()

preview_data = {
    'collections': preview_collections,
    'ids': preview_img_ids
}

# Load at import: the module-level EnumProperty item lists below embed
# preview icon ids, so the collections must exist before they are built.
# register() calls this again (idempotent) to reload after a disable/enable
# released the collections; unregister() releases them (fixes the leak).
_load_preview_collections()

def preview_icon_id(key):
    """Custom preview icon id, or 0 if missing/unloaded.

    Never pass 0 as UILayout.operator(..., icon_value=0) — Blender 5.x
    treats that as an invalid custom icon and aborts the whole panel draw.
    """
    try:
        return int(preview_data['ids']['icons'].get(key, 0) or 0)
    except Exception:
        return 0

def layout_operator_with_preview(
        layout, bl_idname, *, text='', icon_key=None, fallback_icon='NONE',
        **kwargs):
    """Like layout.operator(), but skips icon_value when the preview id is 0."""
    if icon_key:
        icon_id = preview_icon_id(icon_key)
        if icon_id:
            return layout.operator(
                bl_idname, text=text, icon_value=icon_id, **kwargs)
        return layout.operator(
            bl_idname, text=text, icon=fallback_icon, **kwargs)
    return layout.operator(bl_idname, text=text, **kwargs)

# print()
# print('preview_data')
# pprint(preview_data)
# print()

## PREDICATES ------------------------------------------------------

def is_lqfl_modifier(mod):
    return has_lqfl_data_structure_attached(mod)

def is_shader_aux_modifier(mod, obj__, shading_modality_key):
    lib_key, mat_name = hrdc_get_library_key_and_material_name(
        obj__, shading_modality_key=shading_modality_key)
    return is_modifier_shader_auxilliary_f(
        lib_key, mat_name)(mod)

# 21_nov_2023
def has_geonode_mod_name_f(name):
    def f(mod):
        if mod.type == 'NODES' and mod.node_group:
            v = mod.node_group.name == name
        else:
            v = False
        # print(f'has_geonode_mod_name_f({name})({mod.name}): {v}')
        return v
    return f

def has_obj_geonode_mod_by_ng_name(obj__, ng_name):
    discriminator = has_geonode_mod_name_f(ng_name)
    return any([discriminator(mod) for mod in list(obj__.modifiers)])

# # 16_nov_2023
# def has_geonode_mod_name_f(name):
#     def f(mod):
#         if mod.type == 'NODES':
#             return mod.node_group.name == name
#         return False
#     return f

is_mod_select_outer = has_geonode_mod_name_f(SELECT_OUTER_NG_NAME)
is_mod_main_fill = has_geonode_mod_name_f(FILL_NG_NAME)
is_mod_hide_recipient = has_geonode_mod_name_f(HIDE_RECIPIENT_NG_NAME)

def is_obj_filled(obj__):
    has_fill_mod = any([is_mod_main_fill(mod) for mod in obj__.modifiers])
    has_hide_recipient_mod = any([is_mod_hide_recipient(mod) for mod in obj__.modifiers])
    return has_fill_mod and has_hide_recipient_mod

# 21_nov_2023
def is_material_from_liquifill_library(material, library_key):
    if material and 'liquifeel' in material.keys():
        v = material['liquifeel']['library'] == library_key
    else:
        v = False
    # print(f'is_material_from_liquifill_library({material.name}, {library_key}): {v}')
    return v

# # 16_nov_2023
# def is_material_from_liquifill_library(material, library_key):
#     if 'liquifeel' in material.keys():
#         return material['liquifeel']['library'] == library_key
#     else:
#         return False

# 21_nov_2023
def is_obj_library_slot_shaded(obj__, library_key):
    if obj__.data.materials:
        # filter out the None material Slots (empty)
        materials = filter(bool, obj__.data.materials)
        v = any(
            [is_material_from_liquifill_library(mat, library_key) for mat in materials])
        # print(f'is_obj_library_slot_shaded({obj__.name}): {v}')
        return v
    return False

def is_obj_library_slot_shaded__anylib(obj__):
    return any(list(map(
        lambda lib_key: is_obj_library_slot_shaded(obj__, lib_key),
        map(lambda item: item[0],
            material_library_items))))

def is_obj_library_fill_shaded__anylib(obj__):
    return any(list(map(
        lambda lib_key: is_obj_library_fill_shaded(obj__, lib_key),
        map(lambda item: item[0],
            material_library_items))))

# # 16_nov_2023
# def is_obj_library_slot_shaded(obj__, library_key):
#     if obj__.data.materials:
#         if obj__.data.materials:
#             return any([is_material_from_liquifill_library(mat, library_key) for mat in obj__.data.materials])
#     return False

def is_obj_library_fill_shaded(obj__, library_key):
    # print('obj__', obj__)
    # print('library_key', library_key)
    mat = get_geonode_mod_input(obj__, FILL_NG_NAME, 'Liquid Shader')
    if mat:
        return is_material_from_liquifill_library(mat, library_key)
    return False

def is_obj_library_shaded(obj__, library_key, shading_modality_key):
    if shading_modality_key == 'slot':
        return is_obj_library_slot_shaded(obj__, library_key)
    elif shading_modality_key == 'fill':
        return is_obj_library_fill_shaded(obj__, library_key)

def has_any_lqfl_tagged_data_attached(obj__):
    return any([key in obj__.keys() for key in LQFL_OBJECT_TAG_ATTACHED_DATA_KEYS])

def is_obj_lqfl_shaded(obj__):
    return is_obj_library_fill_shaded__anylib(obj__) and is_obj_library_slot_shaded__anylib(obj__)

# We neet to check if it has attached data too. there are instances where the object is library slot shaded
# As it has kept it's shader and the shade is part of the lqfl library, but the asset has been applied
# and thus, we don't want to display the shading ui or any ui for that matter.
def is_obj_liquifeel_asset(obj__):
    if obj__.type == 'MESH':
        vs = [is_obj_filled(obj__)]
        for lib_key in INPUT_FIELD_DATA['shading'].keys():
            vs.append(
                is_obj_library_slot_shaded(obj__, lib_key))
        return any(vs) and has_any_lqfl_tagged_data_attached(obj__)

def has_lqfl_data_structure_attached(mod):
    try:
        v = 'liquifeel' in mod.node_group.keys()
        return v
    except:
        return False

def is_mod_shader_aux__fs(prev_mat_library_key, prev_mat_name):
    return [
        lambda mod: mod.type == 'NODES',
        has_lqfl_data_structure_attached,
        lambda mod: all([key in mod.node_group['liquifeel'].keys() for key in ['library', 'material_name']]),
        lambda mod: all(
            map(lambda kv: mod.node_group['liquifeel'][kv[0]] == kv[1],
                zip(['library', 'material_name'],
                    [prev_mat_library_key, prev_mat_name])))
    ]

def is_modifier_shader_auxilliary_f(prev_mat_library_key, prev_mat_name):
    disc_fs = is_mod_shader_aux__fs(prev_mat_library_key, prev_mat_name)
    def is_it__(mod):
        for f in disc_fs:
            if not(f(mod)):
                return False
        return True
    return is_it__

def has_dict_path(data, keys):
    if len(keys) == 0:
        return True
    elif keys[0] not in data.keys():
        return False
    else:
        return has_dict_path(data[keys[0]], keys[1:])

# 07_sep_2024
def is_user_defined_image(im, image_purpose):
    if im and 'liquifeel' in im.keys():
        if isinstance(im['liquifeel'], idprop.types.IDPropertyGroup) and 'purpose' in im['liquifeel'].keys():
            return im['liquifeel']['purpose'] == image_purpose and im['liquifeel']['means'] == 'user_defined'
    return False
# # 10_jun_2024
# def is_user_defined_image(im, image_purpose):
#     if im and 'liquifeel' in im.keys():
#         v = im['liquifeel']['purpose'] == image_purpose and im['liquifeel']['means'] == 'user_defined'
#     else:
#         v = False
#     # print(f'is_user_defined_pattern_image({im.name}): {v}')
#     return v
# # 21_nov_2023
# def is_user_defined_pattern_image(im):
#     if im and 'liquifeel' in im.keys():
#         v = im['liquifeel'] == 'user_defined'
#     else:
#         v = False
#     # print(f'is_user_defined_pattern_image({im.name}): {v}')
#     return v
# # 16_nov_2023
# def is_user_defined_pattern_image(im):
#     if 'liquifeel' in im.keys():
#         return im['liquifeel'] == 'user_defined'
#     else:
#         return False

def modifier_slot_vs_shade_discriminator_f(shading_modality_key):
    def disc__(mod):
        if mod and has_dict_path(mod, ['liquifeel', 'slot_vs_fill']):
            return mod.node_group['liquifeel']['liquifeel']['shading_modality_key']
        else:
            return False
    return disc__

## PROPERTIES --------------------------------------------------------------------------------

def gen_pattern_imgtex_img_items(instance, context):
    items = []
    for pattern_key, pattern_icon_id in preview_data['ids']['pattern_thumbnails'].items():
        items.append(
            (
                pattern_key, # key
                pattern_key, # name
                name_from_key(pattern_key), # description
                pattern_icon_id, # icon_id
                len(items) # order index
            )
        )
    return items

def gen_roughness_imgtex_img_items(instance, context):
    items = []
    for roughness_key, roughness_icon_id in preview_data['ids']['roughness_thumbnails'].items():
        items.append(
            (
                roughness_key, # key
                roughness_key, # name
                name_from_key(roughness_key), # description
                roughness_icon_id, # icon_id
                len(items) # order index
            )
        )
    return items

imgtex_res_items = [
    ('256', '256', '256'),
    ('512', '512', '512'),
    ('1k', '1K', '1K'),
    ('2k', '2K', '2K'),
]
def gen_map_imgtex_res_items(instance, context):
    return imgtex_res_items

def items_from_data(items_data):
    items = []
    for img_fname, data in items_data.items():
        items.append(
            (
                img_fname, # key
                img_fname, # name
                img_fname, # description
                data['thumbnail_id'], # icon_id
                len(items) # order index
            ))
    return items

def get_loaded_user_defined_images(map_category_key):
    return list(filter(lambda im: is_user_defined_image(im, map_category_key),
                       bpy.data.images))

# def get_loaded_user_defined_pattern_images():
#     return list(filter(lambda im: is_user_defined_image(im, 'pattern'),
#                        bpy.data.images))

# map_category_key is either 'pattern' or 'roughness'
def gen_map_user_imgtex_img_items__(items_data, map_category_key):
    preview_collection = preview_data['collections'][f'user_defined_{map_category_key}_thumbnails']
    imgs = get_loaded_user_defined_images(map_category_key)
    for img in imgs:
        img_key = img.name
        if img_key not in items_data.keys():
            img_fpath = img.filepath_from_user()
            if img_key not in preview_collection.keys():
                preview_image = preview_collection.load(
                    img_key,
                    str(img_fpath),
                    'IMAGE')
            else:
                preview_image = preview_collection.get(img_key)
            items_data[img_key] = {
                'filepath': img_fpath,
                'thumbnail_id': preview_image.icon_id
            }
    return items_from_data(items_data)

def gen_pattern_user_imgtex_img_items_f():
    items_data = {}
    def f(instance, context):
        try:
            return gen_map_user_imgtex_img_items__(items_data, 'pattern')
        except AttributeError as e:
            # empty preview collection
            return items_from_data(items_data)
    return f

def gen_roughness_user_imgtex_img_items_f():
    items_data = {}
    def f(instance, context):
        try:
            return gen_map_user_imgtex_img_items__(items_data, 'roughness')
        except AttributeError as e:
            # empty preview collection
            return items_from_data(items_data)
    return f

gen_pattern_user_imgtex_img_items = gen_pattern_user_imgtex_img_items_f()
gen_roughness_user_imgtex_img_items = gen_roughness_user_imgtex_img_items_f()

def get_object_uv_maps_items_f():
    def f(slf, context):
        obj__ = context.active_object
        items = []
        for uv_layer in obj__.data.uv_layers:
            items.append((uv_layer.name, uv_layer.name, uv_layer.name))
        return items
    return f

def get_object_vertex_groups_items_f():
    def f(slf, context):
        obj__ = context.active_object
        items = []
        for vg in obj__.vertex_groups:
            items.append((vg.name, vg.name, vg.name))
        return items
    return f


# ## NEW PROPERTY SYSTEM (EXECD) ---------------------

# def gen_update_f_name(redux_input_data, tab_key, target_attachment_key):
#     return f'{tab_key}_{target_attachment_key}_{redux_input_data["prop_key"]}_updt'

# # def gen_update_f_name(redux_input_data, tab_key, target_attachment_key):
# #     group_name_key = get_prop_key(path_as_mapping['group_name'])
# #     target_type_key = get_prop_key(path_as_mapping['target_type'])
# #     if isinstance(input_data['key'], list):
# #         input_key = input_data['key'][0]
# #     else:
# #         input_key = input_data['key']
# #     return f'{input_key}_{group_name_key}_{target_type_key}_updt'

# def gen_update_f_code(input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key):
#     update_code = f'''
# @undo_push(2)
# def {gen_update_f_name(redux_input_data, tab_key, target_attachment_key)}(slf, context):
#     set_input__at_prop_update(
#         slf,
#         context,
#         \'{input_name}\',
#         \'{tab_key}\',
#         \'{target_attachment_key}\',
#         \'{shading_modality_key}\')'''
#     return update_code

# def gen_int_prop_code(input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key):
#     # if DEV:
#     #     pprint(redux_input_data)
#     update_f_code = gen_update_f_code(input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key)
#     # # I might need to use the bounds data if i want to implement sliders.
#     bounds_data = redux_input_data['bounds']
#     if 'underlying_input_subtype' in redux_input_data:
#         subtype = redux_input_data['underlying_input_subtype'].upper()
#     else:
#         subtype = 'NONE'
#     prop_rows = [
#         f'    {redux_input_data["prop_key"]}: bpy.props.IntProperty(',
#         f'        name=\'{input_name}\',',
#         # f'        default={input_data["default_val"]},',
#         f'        min={bounds_data["min"]},',
#         f'        soft_min={bounds_data["min"]},',
#         f'        max={bounds_data["max"]},',
#         f'        soft_max={bounds_data["max"]},',
#         f'        subtype=\'{subtype}\',',
#         f'        update={gen_update_f_name(redux_input_data, tab_key, target_attachment_key)},',
#         f'    )',
#     ]
#     prop_code = '\n'.join(prop_rows)
#     return prop_code, update_f_code

# # Apparently, for floats I've used custom functions defined
# # classically, maybe i should implement this functionality for all
# # types.
# def gen_float_prop_code(input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key):
#     # This code chunk commented below was for using custom defined
#     # functions (functions defined manually in this file (like for
#     # example lip_threshold_update)) as the update functions of the
#     # synthetically defined property (synthetized by this function
#     # (gen_float_prop_code)). input_data was not referenced before
#     # being accessed and such, the input_data variable was containing
#     # some residual data which didn't have the 'update_f' key in
#     # it. If custom functions are needed, this needs to be rectified,
#     # the redux_input_data strcture has the path to access the
#     # required data.
#     # if DEV:
#     #     debug_buffer.append(redux_input_data) # DEBUG
#     # # input_data = index_hierarchy_by_path(INPUT_FIELD_DATA, redux_input_data['paths'][0]['list'])
#     # # print(input_data.keys()) # DEBUG
#     # if not('update_f' in input_data.keys()):
#     #     update_f_code = gen_update_f_code(
#     #         input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key)
#     #     update_func_name = gen_update_f_name(redux_input_data, tab_key, target_attachment_key)
#     # else:
#     #     update_f_code = []
#     #     update_func_name = input_data['update_f']
#     update_f_code = gen_update_f_code(
#         input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key)
#     # if DEV:
#     #     pprint(redux_input_data)
#     update_func_name = gen_update_f_name(redux_input_data, tab_key, target_attachment_key)
#     bounds_data = redux_input_data['bounds']
#     if 'underlying_input_subtype' in redux_input_data:
#         subtype = redux_input_data['underlying_input_subtype'].upper()
#     else:
#         subtype = 'NONE'
#     prop_rows = [
#         f'    {redux_input_data["prop_key"]}: bpy.props.FloatProperty(',
#         f'        name=\'{input_name}\',',
#         f'        update={update_func_name},',
#         # f'        default={input_data["default_val"]},',
#         f'        min={bounds_data["min"]},',
#         f'        soft_min={bounds_data["min"]},',
#         f'        max={bounds_data["max"]},',
#         f'        soft_max={bounds_data["max"]},',
#         f'        subtype=\'{subtype}\',',
#         f'        precision=3,',
#         f'        step=0.1,',
#         f'    )',
#     ]
#     prop_code = '\n'.join(prop_rows)
#     return prop_code, update_f_code

# def gen_bool_prop_code(input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key):
#     update_f_code = gen_update_f_code(
#         input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key)
#     prop_rows = [
#         f'    {redux_input_data["prop_key"]}: bpy.props.BoolProperty(',
#         f'        name=\'{input_name}\',',
#         f'        update={gen_update_f_name(redux_input_data, tab_key, target_attachment_key)},',
#         # f'        default={input_data["default_val"]}',
#         f'    )'
#     ]
#     prop_code = '\n'.join(prop_rows)
#     return prop_code, update_f_code

# def gen_vector_prop_code(input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key):
#     update_f_code = gen_update_f_code(
#         input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key)
#     prop_rows = [
#         f'    {redux_input_data["prop_key"]}: bpy.props.FloatVectorProperty(',
#         f'        name=\'{input_name}\',',
#         f'        update={gen_update_f_name(redux_input_data, tab_key, target_attachment_key)},',
#         f'        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,',
#         f'        subtype=\'XYZ\',',
#         f'    )',
#     ]
#     prop_code = '\n'.join(prop_rows)
#     return prop_code, update_f_code

# def gen_color_prop_code(input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key):
#     update_f_code = gen_update_f_code(
#         input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key)
#     prop_rows = [
#         f'    {redux_input_data["prop_key"]}: bpy.props.FloatVectorProperty(',
#         f'        name=\'{input_name}\',',
#         f'        update={gen_update_f_name(redux_input_data, tab_key, target_attachment_key)},',
#         # f'        default={tuple(input_data["default_val"])},',
#         f'        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,',
#         f'        subtype=\'COLOR\',',
#         f'    )',
#     ]
#     prop_code = '\n'.join(prop_rows)
#     return prop_code, update_f_code

# # !!!
# def gen_menu_prop_code(input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key):
#     input_data = index_hierarchy_by_path(
#         INPUT_FIELD_DATA, redux_input_data['paths'][0]['list'])
#     if DEV:
#         print()
#         print('INPUT DATA')
#         pprint(input_data)
#         print()
#         print('REDUX INPUT DATA')
#         pprint(redux_input_data)
#         print()
#     update_f_code = gen_update_f_code(
#         input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key)
#     prop_rows = [
#         f'    {redux_input_data["prop_key"]}: bpy.props.EnumProperty(',
#         f'        name=\'{input_name}\',',
#         f'        update={gen_update_f_name(redux_input_data, tab_key, target_attachment_key)},',
#         f'        default={input_data["underlying_input_default_val"]},',
#         f'        items={[(k, k, k) for k in input_data["items"]]},',
#         f'    )',
#     ]
#     # recipient_asset: bpy.props.EnumProperty(
#     #     name='Fill Material',
#     #     items=recipient_asset_items)
#     prop_code = '\n'.join(prop_rows)
#     return prop_code, update_f_code

# prop_gens_by_type = {
#     'int': gen_int_prop_code,
#     'float': gen_float_prop_code,
#     'bool': gen_bool_prop_code,
#     # 'vector': gen_vector_prop_code,
#     # 'string': gen_string_prop_code,
#     'color': gen_color_prop_code,
#     'menu': gen_menu_prop_code, # !!!
#     # 'bool_to_float': gen_bool_prop_code,
#     # 'imgtex': gen_imgtex_props_code,
# }
# man_def_underlying_input_types = ['string', 'enum', 'imgtex']

# def gen_prop_code(input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key):
#     return prop_gens_by_type[redux_input_data['underlying_input_type']](
#         input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key)
#     # return prop_gens_by_type[redux_input_data['ui_input_type']](
#     #     input_name, redux_input_data, tab_key, target_attachment_key, shading_modality_key)

# # # The input property hierarchy follows this outline
# # # - ObjectAttached
# # #   - Geometry
# # #     - Synthetic
# # #     - Manual
# # #   - Shading
# # #     - Synthetic
# # #     - Manual
# # # - MaterialAttached
# # #  - Slot
# # #    - Synthetic
# # #    - Manual
# # #  - Fill
# # #    - Synthetic
# # #    - Manual

# # object_attached_prop_hierarchy_karte = {
# #     # ObjectAttached_InputProps
# #     'liquifeel_input_field_props': {
# #         # ObjectAttached_Geometry_InputProps
# #         'geometry': {
# #             # ObjectAttached_Synthetic_Geometry_InputProps
# #             'synthetic': None,
# #             # ObjectAttached_Manual_Geometry_InputProps
# #             'manual': None
# #         },
# #         # ObjectAttached_Shading_InputProps
# #         'shading': {
# #             # ObjectAttached_Synthetic_Shading_InputProps
# #             'synthetic': {},
# #             # ObjectAttached_Manual_Shading_InputProps
# #             'manual': {}
# #         }
# #     }
# # }

# # material_attached_prop_hierarchy_karte = {
# #     # MaterialAttached_InputProps
# #     'liquifeel_input_field_props': {
# #         # MaterialAttached_SlotShading_InputProps
# #         'slot': {
# #             # MaterialAttached_Synthetic_SlotShading_InputProps
# #             'synthetic': None,
# #             # MaterialAttached_Manual_SlotShading_InputProps
# #             'manual': None
# #         },
# #         # MaterialAttached_FillShading_InputProps
# #         'fill': {
# #             # MaterialAttached_Synthetic_FillShading_InputProps
# #             'synthetic': {},
# #             # MaterialAttached_Manual_FillShading_InputProps
# #             'manual': {}
# #         }
# #     }
# # }

# # The input property hierarchy follows this outline
# # - ObjectAttached
# #   - Geometry
# #     - Synthetic
# #     - Manual
# #   - Shading
# #     - Synthetic
# #     - Manual
# # - MaterialAttached
# #  - Slot
# #    - Synthetic
# #    - Manual
# #  - Fill
# #    - Synthetic
# #    - Manual

# object_attached_prop_hierarchy_karte = {
#     # ObjectAttached_InputProps
#     'liquifeel_input_field_props': {
#         # ObjectAttached_Geometry_InputProps
#         'geometry': {
#             # ObjectAttached_Synthetic_Geometry_InputProps
#             'synthetic': None,
#             # ObjectAttached_Manual_Geometry_InputProps
#             'manual': None
#         },
#         # ObjectAttached_Shading_InputProps
#         'shading': {
#             # ObjectAttached_SlotShading_InputProps
#             'slot': {
#                 # ObjectAttached_Synthetic_SlotShading_InputProps
#                 'synthetic': {},
#                 # ObjectAttached_Manual_SlotShading_InputProps
#                 'manual': {}
#             },
#             # ObjectAttached_FillShading_InputProps
#             'fill': {
#                 # ObjectAttached_Synthetic_FillShading_InputProps
#                 'synthetic': {},
#                 # ObjectAttached_Manual_FillShading_InputProps
#                 'manual': {}
#             },
#         }
#     }
# }

# material_attached_prop_hierarchy_karte = {
#     # MaterialAttached_InputProps
#     'liquifeel_input_field_props': {
#         # MaterialAttached_SlotShading_InputProps
#         'slot': {
#             # MaterialAttached_Synthetic_SlotShading_InputProps
#             'synthetic': None,
#             # MaterialAttached_Manual_SlotShading_InputProps
#             'manual': None
#         },
#         # MaterialAttached_FillShading_InputProps
#         'fill': {
#             # MaterialAttached_Synthetic_FillShading_InputProps
#             'synthetic': {},
#             # MaterialAttached_Manual_FillShading_InputProps
#             'manual': {}
#         }
#     }
# }

def get_declaration_modality_key(redux_input_data):
    if redux_input_data['ui_input_type'] in prop_gens_by_type.keys():
        return 'synthetic'
    else:
        return 'manual'

# def declare_and_register_synthetic_prop_parent(
#         main_tab_key, target_attachment_key, shading_modality_key=None):
#     # debug_buffer.append({
#     #     'f': 'declare_and_register_synthetic_prop_parent',
#     #     'main_tab_key': main_tab_key,
#     #     'target_attachment_key': target_attachment_key,
#     #     'shading_modality_key': shading_modality_key})
#     properties_code = []
#     update_funcs_code = []
#     for input_name, redux_input_data in REDUX_INPUT_DATA[main_tab_key][target_attachment_key].items():
#         # if redux_input_data['ui_input_type'] in prop_gens_by_type.keys():
#         if redux_input_data['underlying_input_type'] in prop_gens_by_type.keys():
#             prop_declaration_code, update_func_declaration_code = gen_prop_code(
#                 input_name, redux_input_data, main_tab_key, target_attachment_key, shading_modality_key)
#             properties_code.append(prop_declaration_code)
#             update_funcs_code.append(update_func_declaration_code)
#     target_attachment_name = ''.join([e.capitalize() for e in target_attachment_key.split('_')])
#     main_tab_name = main_tab_key.capitalize()
#     code_blocks = []
#     code_blocks.extend(update_funcs_code)
#     lines = []
#     if target_attachment_key == 'material_attached':
#         shading_modality_name = shading_modality_key.capitalize()
#         class_name = f'{target_attachment_name}_Synthetic_{shading_modality_name}Shading_InputProps'
#     elif target_attachment_key == 'object_attached':
#         if main_tab_key == 'geometry':
#             class_name = f'{target_attachment_name}_Synthetic_{main_tab_key.capitalize()}_InputProps'
#         elif main_tab_key == 'shading':
#             shading_modality_name = shading_modality_key.capitalize()
#             class_name = f'{target_attachment_name}_Synthetic_{shading_modality_name}Shading_InputProps'
#     # if target_attachment_key == 'material_attached':
#     #     shading_modality_name = shading_modality_key.capitalize()
#     #     class_name = f'{target_attachment_name}_Synthetic_{shading_modality_name}Shading_InputProps'
#     # elif target_attachment_key == 'object_attached':
#     #     class_name = f'{target_attachment_name}_Synthetic_{main_tab_key.capitalize()}_InputProps'
#     lines.append(
#         f'\nclass {class_name}(bpy.types.PropertyGroup):')
#     if properties_code:
#         lines.extend(properties_code)
#     else:
#         lines.append('    pass')
#         print(f'\nclass {class_name} has no properties!\n')
#     lines.append(
#         f'registerable_classes.append({class_name})'
#     )
#     prop_parent_code = "\n".join(lines)
#     code_blocks.append(prop_parent_code)
#     code = "\n".join(code_blocks)
#     # # saving the synthetically generated code to file.
#     # with open(f'{FPATHS["addon_root"]}/synthetic_properties.py', 'a') as f:
#     #     f.write(code)
#     cc = compile(code, '<string>', 'exec')
#     exec(cc, globals())

# # key_chain: ['liquifeel_input_field_props', 'geometry', 'synthetic']
# # path: liquifeel_input_field_props.geometry.synthetic
# # class ObjectAttached_Synthetic_Geometry_InputProps
# declare_and_register_synthetic_prop_parent(
#         'geometry', 'object_attached')
# # class ObjectAttached_Synthetic_Geometry_InputProps(bpy.types.PropertyGroup):
# #     pass
# # registerable_classes.append(ObjectAttached_Synthetic_Geometry_InputProps)

# This is not the main actor of the opening-shape selector functionality.
# 'straight' hides the Lip Threshold slider, so the underlying Select Outer
# modifier input must be reset here — otherwise a stale threshold keeps
# affecting the fill while its control is hidden.
@undo_push(2)
def opening_shape_mandef_update(slf, context):
    if getattr(slf, 'opening_shape') != 'straight':
        return
    obj__ = context.active_object
    if obj__ is None:
        return
    try:
        set_geonode_mod_input(
            obj__, SELECT_OUTER_NG_NAME, 'Lip Threshold', 'float', 0.0)
    except Exception:
        return
    schedule_separate_refresh(obj__)

@undo_push(2)
def hide_liquid_update(slf, context):
    obj__ = context.active_object
    if obj__ is None:
        return
    try:
        mod = get_geonodes_mod_by_ng_name(obj__, FILL_NG_NAME)
        mod.show_viewport = not(getattr(slf, 'hide_liquid'))
    except Exception:
        return
    schedule_separate_refresh(obj__)

@undo_push(2)
def hide_recipient_update(prop_parent, context):
    obj__ = context.active_object
    if obj__ is None:
        return
    try:
        mod = get_geonodes_mod_by_ng_name(obj__, HIDE_RECIPIENT_NG_NAME)
        identifier = get_geonodes_field_identifier(
            mod, 'Hide Recipient')
        val = getattr(prop_parent, 'hide_recipient')
        geonode_input_set(mod, identifier, val)
    except Exception:
        return
    schedule_separate_refresh(obj__)

def separate_objects_update(prop_parent, context):
    # Must not sync/create objects inside the RNA update itself — that crashes
    # Blender (depsgraph re-entrancy). Defer to a timer tick.
    obj__ = context.active_object
    if obj__ is None:
        return
    schedule_separate_refresh(obj__, force=True)

LIQUID_PROXY_ROLE = 'liquid_proxy'
LIQUID_PROXY_SUFFIX = '_LQFL_liquid'
_separate_objects_sync_lock = False
_separate_objects_last_sig = {}
_pending_separate_refresh = set()  # {(object_name, force)}

def _lqfl_marker_get(obj__):
    marker = obj__.get('liquifeel')
    if marker is None:
        return {}
    if hasattr(marker, 'to_dict'):
        return marker.to_dict()
    try:
        return dict(marker)
    except Exception:
        return {}

def _lqfl_sanitize_marker(data):
    """Convert marker data to IDProperty-safe plain Python types."""
    if not data:
        return {'version': list(bl_info['version'])}
    try:
        raw = dict(data)
    except Exception:
        raw = {}
    out = {}
    for key, val in raw.items():
        if key == 'assembly':
            out[key] = _normalize_assembly_dict(val)
            continue
        if key == 'version':
            if hasattr(val, 'to_list'):
                out[key] = [int(x) for x in val.to_list()]
            elif isinstance(val, (tuple, list)):
                out[key] = [int(x) for x in val]
            else:
                out[key] = list(bl_info['version'])
            continue
        if isinstance(val, (str, bool, int, float)):
            out[key] = val
            continue
        if hasattr(val, 'to_dict'):
            try:
                out[key] = dict(val.to_dict())
                continue
            except Exception:
                pass
        if hasattr(val, 'to_list'):
            try:
                out[key] = list(val.to_list())
                continue
            except Exception:
                pass
        # Drop values Blender cannot store on IDProperties.
    if 'version' not in out:
        out['version'] = list(bl_info['version'])
    return out

def _lqfl_marker_set(obj__, data):
    clean = _lqfl_sanitize_marker(data)
    # Replace (don't mutate in place) — avoids Blender 5.x
    # "Error setting Object.liquifeel" when the existing group type conflicts.
    try:
        if 'liquifeel' in obj__.keys():
            del obj__['liquifeel']
    except Exception:
        try:
            obj__.pop('liquifeel', None)
        except Exception:
            pass
    obj__['liquifeel'] = clean

def is_liquid_proxy_object(obj__):
    return _lqfl_marker_get(obj__).get('role') == LIQUID_PROXY_ROLE

def resolve_liquifeel_source_object(obj__):
    """Map a liquid proxy selection back to the filled recipient object."""
    if obj__ is None:
        return None
    if is_liquid_proxy_object(obj__):
        marker = _lqfl_marker_get(obj__)
        src_name = marker.get('source')
        if src_name and src_name in bpy.data.objects:
            return bpy.data.objects[src_name]
        if obj__.parent is not None:
            return obj__.parent
    return obj__

## BOTTLE ASSEMBLY (controller = bottle parent) -----------------------------

ASSEMBLY_ROLE_CORK = 'cork'
ASSEMBLY_ROLE_LABEL = 'label'
ASSEMBLY_ROLE_EXTRA = 'extra'
ASSEMBLY_MEMBER_ROLES = {
    ASSEMBLY_ROLE_CORK, ASSEMBLY_ROLE_LABEL, ASSEMBLY_ROLE_EXTRA,
}

def _normalize_assembly_dict(asm):
    if asm is None:
        return {'cork': '', 'label': '', 'extras': []}
    if hasattr(asm, 'to_dict'):
        d = asm.to_dict()
    else:
        try:
            d = dict(asm)
        except Exception:
            return {'cork': '', 'label': '', 'extras': []}
    extras = d.get('extras', [])
    if hasattr(extras, 'to_list'):
        extras = list(extras)
    elif extras is None:
        extras = []
    else:
        extras = list(extras)
    return {
        'cork': str(d.get('cork') or ''),
        'label': str(d.get('label') or ''),
        'extras': [str(x) for x in extras if x],
    }

def get_assembly_dict(obj__):
    if obj__ is None:
        return None
    marker = _lqfl_marker_get(obj__)
    if 'assembly' not in marker:
        return None
    return _normalize_assembly_dict(marker.get('assembly'))

def has_assembly(obj__):
    return get_assembly_dict(obj__) is not None

def set_assembly_dict(obj__, assembly):
    marker = dict(_lqfl_marker_get(obj__)) if _lqfl_marker_get(obj__) else {}
    if 'version' not in marker:
        marker['version'] = list(bl_info['version'])
    marker['assembly'] = _normalize_assembly_dict(assembly)
    _lqfl_marker_set(obj__, marker)

def clear_assembly_dict(obj__):
    marker = dict(_lqfl_marker_get(obj__))
    if not marker:
        return
    marker.pop('assembly', None)
    if set(marker.keys()) <= {'version'}:
        maybe_remove_lqfl_object_tags(obj__)
    else:
        _lqfl_marker_set(obj__, marker)

def _lqfl_strip_fill_keys_keep_assembly(obj__):
    """Drop fill-related marker keys; keep assembly (+ version) if present."""
    marker = _lqfl_marker_get(obj__)
    if not marker:
        maybe_remove_lqfl_object_tags(obj__)
        return
    marker = dict(marker)
    asm = None
    if 'assembly' in marker:
        asm = _normalize_assembly_dict(marker.get('assembly'))
    marker.pop('filled', None)
    marker.pop('fill_shading', None)
    marker.pop('separate_liquid', None)
    if asm is not None:
        marker['assembly'] = asm
        if 'version' not in marker:
            marker['version'] = bl_info['version']
        _lqfl_marker_set(obj__, marker)
        return
    if set(marker.keys()) <= {'version'}:
        maybe_remove_lqfl_object_tags(obj__)
    else:
        _lqfl_marker_set(obj__, marker)

def parent_keep_transform(child, parent):
    mw = child.matrix_world.copy()
    child.parent = parent
    child.matrix_world = mw

def unparent_keep_transform(child):
    if child.parent is None:
        return
    mw = child.matrix_world.copy()
    child.parent = None
    child.matrix_world = mw

def is_assembly_member_object(obj__):
    if obj__ is None or is_liquid_proxy_object(obj__):
        return False
    role = _lqfl_marker_get(obj__).get('role')
    return role in ASSEMBLY_MEMBER_ROLES

def resolve_assembly_controller_object(obj__):
    """Map an assembly member (or bottle) to the bottle controller."""
    if obj__ is None:
        return None
    if is_liquid_proxy_object(obj__):
        obj__ = resolve_liquifeel_source_object(obj__)
        if obj__ is None:
            return None
    if has_assembly(obj__):
        return obj__
    marker = _lqfl_marker_get(obj__)
    if marker.get('role') in ASSEMBLY_MEMBER_ROLES:
        name = marker.get('controller')
        if name and name in bpy.data.objects:
            ctrl = bpy.data.objects[name]
            if has_assembly(ctrl):
                return ctrl
        if obj__.parent is not None and has_assembly(obj__.parent):
            return obj__.parent
    if obj__.parent is not None and has_assembly(obj__.parent):
        return obj__.parent
    return None

def _set_member_marker(member, role, controller):
    marker = dict(_lqfl_marker_get(member)) if _lqfl_marker_get(member) else {}
    if 'version' not in marker:
        marker['version'] = bl_info['version']
    marker['role'] = role
    marker['controller'] = controller.name
    _lqfl_marker_set(member, marker)

def _clear_member_marker(member):
    marker = dict(_lqfl_marker_get(member))
    if not marker:
        return
    marker.pop('role', None)
    marker.pop('controller', None)
    if set(marker.keys()) <= {'version'}:
        maybe_remove_lqfl_object_tags(member)
    else:
        _lqfl_marker_set(member, marker)

def _lookup_object_by_name(name):
    if not name:
        return None
    return bpy.data.objects.get(name)

def _find_child_member_by_role(controller, role):
    for child in controller.children:
        if is_liquid_proxy_object(child):
            continue
        if _lqfl_marker_get(child).get('role') == role:
            if _lqfl_marker_get(child).get('controller') in (controller.name, None, ''):
                return child
            if _lqfl_marker_get(child).get('controller') == controller.name:
                return child
    for child in controller.children:
        if is_liquid_proxy_object(child):
            continue
        if _lqfl_marker_get(child).get('role') == role:
            return child
    return None

def resolve_assembly_cork(controller):
    asm = get_assembly_dict(controller)
    if asm is None:
        return None
    obj__ = _lookup_object_by_name(asm.get('cork'))
    if obj__ is not None and (
            obj__.parent == controller
            or _lqfl_marker_get(obj__).get('controller') == controller.name):
        return obj__
    return _find_child_member_by_role(controller, ASSEMBLY_ROLE_CORK)

def resolve_assembly_label(controller):
    asm = get_assembly_dict(controller)
    if asm is None:
        return None
    obj__ = _lookup_object_by_name(asm.get('label'))
    if obj__ is not None and (
            obj__.parent == controller
            or _lqfl_marker_get(obj__).get('controller') == controller.name):
        return obj__
    return _find_child_member_by_role(controller, ASSEMBLY_ROLE_LABEL)

def resolve_assembly_extras(controller):
    asm = get_assembly_dict(controller)
    if asm is None:
        return []
    found = []
    seen = set()
    for name in asm.get('extras', []):
        obj__ = _lookup_object_by_name(name)
        if obj__ is None or obj__ in seen:
            continue
        if (obj__.parent == controller
                or _lqfl_marker_get(obj__).get('controller') == controller.name):
            found.append(obj__)
            seen.add(obj__)
    for child in controller.children:
        if child in seen or is_liquid_proxy_object(child):
            continue
        if _lqfl_marker_get(child).get('role') == ASSEMBLY_ROLE_EXTRA:
            found.append(child)
            seen.add(child)
    return found

def list_assembly_member_objects(controller):
    """Cork, label, extras (not liquid proxy)."""
    members = []
    cork = resolve_assembly_cork(controller)
    label = resolve_assembly_label(controller)
    if cork is not None:
        members.append(cork)
    if label is not None and label not in members:
        members.append(label)
    for extra in resolve_assembly_extras(controller):
        if extra not in members:
            members.append(extra)
    return members

def _is_assembly_hide_exempt(ob, controller=None):
    """Never hide the bottle itself or the liquid proxy."""
    if ob is None:
        return True
    if controller is not None and ob == controller:
        return True
    if is_liquid_proxy_object(ob):
        return True
    name = getattr(ob, 'name', '') or ''
    if name.endswith('_liquid') or '_liquid.' in name:
        return True
    return False

def iter_assembly_hide_subtree(root):
    """Root + all descendants. Cork/label often keep child meshes — parent-only hide leaves them visible."""
    if root is None:
        return
    stack = [root]
    seen = set()
    while stack:
        ob = stack.pop()
        if ob is None or ob in seen:
            continue
        seen.add(ob)
        yield ob
        try:
            stack.extend(list(ob.children))
        except Exception:
            pass

def _set_object_viewport_hidden(ob, hidden, view_layer=None):
    """Force Outliner eye + Disable-in-Viewports. Returns True if applied."""
    if ob is None:
        return False
    hidden = bool(hidden)
    ok = False
    try:
        ob.hide_viewport = hidden
        ok = True
    except Exception:
        pass
    try:
        if view_layer is not None:
            try:
                ob.hide_set(hidden, view_layer=view_layer)
            except TypeError:
                ob.hide_set(hidden)
        else:
            ob.hide_set(hidden)
        ok = True
    except Exception:
        pass
    return ok

def collect_assembly_hide_roots(controller, context=None):
    """Everything under the bottle that is not the liquid — markers + children + UI slots."""
    roots = []
    seen = set()

    def add(ob):
        if ob is None or ob in seen:
            return
        if _is_assembly_hide_exempt(ob, controller):
            return
        roots.append(ob)
        seen.add(ob)

    if controller is not None:
        for member in list_assembly_member_objects(controller):
            add(member)
        # Parenting is source of truth: cork/front sit as children after Add
        try:
            for child in controller.children:
                add(child)
        except Exception:
            pass
    if context is not None:
        try:
            for item in context.scene.liquifeel_general_controls.assembly_parts:
                add(item.object)
        except Exception:
            pass
    return roots

def set_assembly_parts_hidden(controller, hidden, context=None):
    """Hide/show cork + label + extras (+ their children). Bottle + liquid stay visible."""
    if controller is None:
        return 0
    view_layer = getattr(context, 'view_layer', None) if context else None
    n = 0
    for root in collect_assembly_hide_roots(controller, context):
        for ob in iter_assembly_hide_subtree(root):
            if _is_assembly_hide_exempt(ob, controller):
                continue
            if _set_object_viewport_hidden(ob, hidden, view_layer=view_layer):
                n += 1
    return n

def set_all_scene_assembly_parts_hidden(context, hidden):
    """Hide extras on every bottle assembly in the file (NORU 100/150/300/500…)."""
    total = 0
    seen_ctrl = set()
    for obj__ in bpy.data.objects:
        if obj__ is None or obj__ in seen_ctrl:
            continue
        if not has_assembly(obj__):
            continue
        seen_ctrl.add(obj__)
        total += set_assembly_parts_hidden(obj__, hidden, context=context)
    # Also any orphaned assembly-tagged parts
    view_layer = getattr(context, 'view_layer', None) if context else None
    for obj__ in bpy.data.objects:
        if not is_assembly_member_object(obj__):
            continue
        for ob in iter_assembly_hide_subtree(obj__):
            if _is_assembly_hide_exempt(ob):
                continue
            if _set_object_viewport_hidden(ob, hidden, view_layer=view_layer):
                total += 1
    return total

def apply_assembly_hide_state(context, hidden):
    """Single entry: apply Hide Extras across the scene. Returns count touched."""
    n = set_all_scene_assembly_parts_hidden(context, hidden)
    bottle = None
    try:
        bottle = context.scene.liquifeel_general_controls.assembly_bottle
    except Exception:
        bottle = None
    if bottle is None:
        bottle = get_scene_assembly_bottle(context)
    if bottle is not None and has_assembly(bottle):
        n += set_assembly_parts_hidden(bottle, hidden, context=context)
    try:
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
            if area.type == 'OUTLINER':
                area.tag_redraw()
    except Exception:
        pass
    try:
        context.view_layer.update()
    except Exception:
        pass
    return n

_hide_extras_applying = False  # guard so a manual apply doesn't double-fire

def assembly_hide_extras_update(self, context):
    if _hide_extras_applying:
        return
    apply_assembly_hide_state(context, bool(self.assembly_hide_extras))

def apply_assembly_hide_extras_if_enabled(context, controller, member=None):
    """Keep newly linked parts hidden when Hide Extras is on."""
    try:
        hide = bool(context.scene.liquifeel_general_controls.assembly_hide_extras)
    except Exception:
        return
    if not hide:
        return
    view_layer = getattr(context, 'view_layer', None)
    if member is not None:
        for ob in iter_assembly_hide_subtree(member):
            if _is_assembly_hide_exempt(ob, controller):
                continue
            _set_object_viewport_hidden(ob, True, view_layer=view_layer)
    else:
        set_assembly_parts_hidden(controller, True, context=context)

def sync_assembly_marker_names(controller):
    """Rewrite assembly name slots from currently resolved members."""
    if not has_assembly(controller):
        return
    cork = resolve_assembly_cork(controller)
    label = resolve_assembly_label(controller)
    extras = resolve_assembly_extras(controller)
    set_assembly_dict(controller, {
        'cork': cork.name if cork else '',
        'label': label.name if label else '',
        'extras': [e.name for e in extras],
    })

def _detach_assembly_member(member):
    if member is None:
        return
    unparent_keep_transform(member)
    _clear_member_marker(member)

def ensure_assembly_controller(obj__):
    """Mark mesh as bottle controller with an empty assembly if needed."""
    if not has_assembly(obj__):
        set_assembly_dict(obj__, {'cork': '', 'label': '', 'extras': []})
    return obj__

def validate_assembly_member_candidate(member, controller):
    """Return (ok, error_message)."""
    if member is None:
        return False, 'No object to assign.'
    if member == controller:
        return False, 'Cannot assign the bottle to itself.'
    if member.type != 'MESH' and member.type != 'EMPTY':
        # Allow EMPTY for decorative extras; meshes for cork/label typically.
        pass
    if is_liquid_proxy_object(member):
        return False, 'Cannot assign a liquid proxy as an assembly member.'
    if has_assembly(member):
        return False, f"'{member.name}' is already a bottle controller."
    other = resolve_assembly_controller_object(member)
    if other is not None and other != controller:
        return False, (
            f"'{member.name}' belongs to assembly '{other.name}'. "
            'Clear that assembly membership first.')
    return True, ''

def assign_assembly_role(controller, member, role):
    ok, err = validate_assembly_member_candidate(member, controller)
    if not ok:
        return False, err
    ensure_assembly_controller(controller)
    asm = get_assembly_dict(controller)
    if role == ASSEMBLY_ROLE_CORK:
        old = resolve_assembly_cork(controller)
        if old is not None and old != member:
            _detach_assembly_member(old)
        parent_keep_transform(member, controller)
        _set_member_marker(member, ASSEMBLY_ROLE_CORK, controller)
        asm['cork'] = member.name
        # Remove from extras/label if reassigned
        if asm.get('label') == member.name:
            asm['label'] = ''
        asm['extras'] = [n for n in asm.get('extras', []) if n != member.name]
    elif role == ASSEMBLY_ROLE_LABEL:
        old = resolve_assembly_label(controller)
        if old is not None and old != member:
            _detach_assembly_member(old)
        parent_keep_transform(member, controller)
        _set_member_marker(member, ASSEMBLY_ROLE_LABEL, controller)
        asm['label'] = member.name
        if asm.get('cork') == member.name:
            asm['cork'] = ''
        asm['extras'] = [n for n in asm.get('extras', []) if n != member.name]
    elif role == ASSEMBLY_ROLE_EXTRA:
        parent_keep_transform(member, controller)
        _set_member_marker(member, ASSEMBLY_ROLE_EXTRA, controller)
        if asm.get('cork') == member.name:
            asm['cork'] = ''
        if asm.get('label') == member.name:
            asm['label'] = ''
        extras = list(asm.get('extras', []))
        if member.name not in extras:
            extras.append(member.name)
        asm['extras'] = extras
    else:
        return False, f'Unknown assembly role: {role}'
    set_assembly_dict(controller, asm)
    sync_assembly_marker_names(controller)
    return True, ''

def collect_assembly_add_roots(context, controller):
    """Hierarchy roots among selected objects (and active), excluding bottle."""
    selected = [o for o in context.selected_objects if o is not None]
    active = context.active_object
    candidates = []
    for o in selected:
        if o != controller and o not in candidates:
            candidates.append(o)
    if active is not None and active != controller and active not in candidates:
        candidates.append(active)
    cand_set = set(candidates)
    roots = [o for o in candidates if o.parent not in cand_set]
    return roots

def add_assembly_elements(controller, members):
    """Parent all member roots to bottle as additional elements (no cork/label split)."""
    if not members:
        return 0, 'No objects to add.'
    ensure_assembly_controller(controller)
    added = 0
    errors = []
    for member in members:
        ok, err = assign_assembly_role(controller, member, ASSEMBLY_ROLE_EXTRA)
        if ok:
            added += 1
        else:
            errors.append(f'{member.name}: {err}')
    if added == 0:
        return 0, '; '.join(errors) if errors else 'Nothing added.'
    return added, ''

_assembly_ui_lock = False

def ensure_assembly_empty_drop_slot(context=None):
    """Guarantee at least one empty PointerProperty drop target (never call from draw)."""
    global _assembly_ui_lock
    if _assembly_ui_lock:
        return
    try:
        if context is None:
            context = bpy.context
        controls = context.scene.liquifeel_general_controls
        parts = controls.assembly_parts
        if len(parts) == 0 or parts[-1].object is not None:
            _assembly_ui_lock = True
            try:
                parts.add()
            finally:
                _assembly_ui_lock = False
    except Exception:
        pass

def _assembly_seed_drop_slots_timer():
    """Deferred seed so Geometry → Assembly always has a drop field even with no selection."""
    try:
        ensure_assembly_empty_drop_slot(bpy.context)
    except Exception:
        pass
    return None

def schedule_assembly_drop_slot_seed():
    try:
        if not bpy.app.timers.is_registered(_assembly_seed_drop_slots_timer):
            bpy.app.timers.register(_assembly_seed_drop_slots_timer, first_interval=0.01)
    except Exception:
        pass

def sync_assembly_ui_slots(context, controller=None):
    """Refresh Outliner-drop slots from the bottle's linked parts + one empty slot."""
    global _assembly_ui_lock
    if _assembly_ui_lock:
        return
    try:
        controls = context.scene.liquifeel_general_controls
    except Exception:
        return
    _assembly_ui_lock = True
    try:
        if controller is None:
            controller = get_scene_assembly_bottle(context)
        if controller is not None and has_assembly(controller):
            if controls.assembly_bottle != controller:
                controls.assembly_bottle = controller
            members = list_assembly_member_objects(controller)
        else:
            members = []
        parts = controls.assembly_parts
        # Match filled slots to members
        while len(parts) > len(members):
            parts.remove(len(parts) - 1)
        while len(parts) < len(members):
            parts.add()
        for i, member in enumerate(members):
            if parts[i].object != member:
                parts[i].object = member
        # Always keep one empty drop target at the end
        if len(parts) == 0 or parts[-1].object is not None:
            parts.add()
    except Exception:
        pass
    finally:
        _assembly_ui_lock = False

def _assembly_part_poll(self, obj):
    if obj is None:
        return False
    if is_liquid_proxy_object(obj):
        return False
    bottle = None
    try:
        bottle = bpy.context.scene.liquifeel_general_controls.assembly_bottle
    except Exception:
        bottle = None
    if bottle is not None and obj == bottle:
        return False
    return obj.type in {'MESH', 'EMPTY', 'CURVE', 'FONT'}

_pending_bottle_bake = set()  # object names awaiting a deferred pose bake


def _flush_bottle_bake_timer():
    global _pending_bottle_bake
    context = bpy.context
    names = list(_pending_bottle_bake)
    _pending_bottle_bake.clear()
    for name in names:
        bottle = bpy.data.objects.get(name)
        if bottle is None or bottle.type != 'MESH' or is_liquid_proxy_object(bottle):
            continue
        try:
            ok, err = prepare_bottle_world_pose(context, bottle)
            if not ok:
                print(f'LIQUIFEEL: bottle pose bake: {err}')
                continue
            ensure_assembly_controller(bottle)
            context.scene[SCENE_ASSEMBLY_BOTTLE_KEY] = bottle.name
            sync_assembly_ui_slots(context, bottle)
        except Exception as exc:
            print(f'LIQUIFEEL: bottle pose bake: {exc}')
    return None


def schedule_bottle_pose_bake(bottle):
    _pending_bottle_bake.add(bottle.name)
    if not bpy.app.timers.is_registered(_flush_bottle_bake_timer):
        bpy.app.timers.register(_flush_bottle_bake_timer, first_interval=0.0)


def assembly_bottle_pointer_update(self, context):
    global _assembly_ui_lock
    if _assembly_ui_lock:
        return
    bottle = self.assembly_bottle
    if bottle is None:
        return
    if bottle.type != 'MESH' or is_liquid_proxy_object(bottle):
        return
    # Operators (make_single_user / transform_apply) must not run inside an RNA
    # update — defer to a one-shot timer, mirroring schedule_separate_refresh.
    schedule_bottle_pose_bake(bottle)

def assembly_part_pointer_update(self, context):
    """When user drops/picks an object into a slot — parent it to the bottle."""
    global _assembly_ui_lock
    if _assembly_ui_lock:
        return
    try:
        controls = context.scene.liquifeel_general_controls
    except Exception:
        return
    bottle = controls.assembly_bottle
    if bottle is None or not has_assembly(bottle):
        if bottle is not None and bottle.type == 'MESH':
            try:
                ensure_assembly_controller(bottle)
            except Exception:
                return
        else:
            return
    obj__ = self.object
    if obj__ is None:
        # Cleared slot: detach any previous member that disappeared from slots
        # Full resync from hierarchy is safer.
        sync_assembly_ui_slots(context, bottle)
        return
    if obj__ == bottle or is_liquid_proxy_object(obj__):
        _assembly_ui_lock = True
        try:
            self.object = None
        finally:
            _assembly_ui_lock = False
        return
    try:
        ok, err = assign_assembly_role(bottle, obj__, ASSEMBLY_ROLE_EXTRA)
        if not ok:
            print(f'LIQUIFEEL: drop assign failed: {err}')
            _assembly_ui_lock = True
            try:
                self.object = None
            finally:
                _assembly_ui_lock = False
            return
        apply_assembly_hide_extras_if_enabled(context, bottle, obj__)
        set_scene_assembly_bottle(context, bottle)
        sync_assembly_ui_slots(context, bottle)
    except Exception as exc:
        print(f'LIQUIFEEL: assembly_part_pointer_update: {exc}')

def clear_assembly_role(controller, role, extra_name=None):
    if not has_assembly(controller):
        return False, 'Object has no assembly.'
    asm = get_assembly_dict(controller)
    if role == ASSEMBLY_ROLE_CORK:
        _detach_assembly_member(resolve_assembly_cork(controller))
        asm['cork'] = ''
    elif role == ASSEMBLY_ROLE_LABEL:
        _detach_assembly_member(resolve_assembly_label(controller))
        asm['label'] = ''
    elif role == ASSEMBLY_ROLE_EXTRA:
        target = None
        if extra_name:
            target = _lookup_object_by_name(extra_name)
        if target is None:
            return False, 'Extra not found.'
        _detach_assembly_member(target)
        asm['extras'] = [n for n in asm.get('extras', []) if n != target.name]
    else:
        return False, f'Unknown assembly role: {role}'
    set_assembly_dict(controller, asm)
    sync_assembly_marker_names(controller)
    return True, ''

def clear_assembly(controller):
    if not has_assembly(controller):
        return False, 'Object has no assembly.'
    for member in list_assembly_member_objects(controller):
        _detach_assembly_member(member)
    clear_assembly_dict(controller)
    return True, ''

SCENE_ASSEMBLY_BOTTLE_KEY = 'liquifeel_assembly_bottle'

def get_scene_assembly_bottle(context):
    # 1) PointerProperty (may be missing after script reload without restart)
    try:
        bottle = context.scene.liquifeel_general_controls.assembly_bottle
        if bottle is not None and has_assembly(bottle):
            return bottle
    except Exception:
        pass
    # 2) Durable scene ID-property (survives PropertyGroup RNA cache issues)
    try:
        name = context.scene.get(SCENE_ASSEMBLY_BOTTLE_KEY, '')
    except Exception:
        name = ''
    if name and name in bpy.data.objects:
        bottle = bpy.data.objects[name]
        if has_assembly(bottle):
            return bottle
    return None

def set_scene_assembly_bottle(context, bottle):
    if bottle is None:
        return
    try:
        context.scene[SCENE_ASSEMBLY_BOTTLE_KEY] = bottle.name
    except Exception:
        pass
    try:
        context.scene.liquifeel_general_controls.assembly_bottle = bottle
    except Exception:
        pass

def _iter_hierarchy_roots(obj__):
    """Walk parents; yield each ancestor and the object itself."""
    seen = set()
    cur = obj__
    while cur is not None and cur not in seen:
        yield cur
        seen.add(cur)
        cur = cur.parent

def _collect_descendants(root):
    stack = list(root.children)
    while stack:
        child = stack.pop()
        yield child
        stack.extend(child.children)

def find_nearby_assembly_bottles(obj__):
    """Prefer assembly bottles that share hierarchy/collection with obj__."""
    if obj__ is None:
        return []
    nearby = []
    # Same collections
    cols = set(obj__.users_collection)
    for o in bpy.data.objects:
        if o.type != 'MESH' or not has_assembly(o) or o == obj__:
            continue
        if cols and (cols & set(o.users_collection)):
            nearby.append(o)
    if nearby:
        return nearby
    # Shared parent chain (e.g. NORU_500 → cork sibling of 500_ML → butelka)
    roots = list(_iter_hierarchy_roots(obj__))
    for root in roots:
        for desc in _collect_descendants(root):
            if desc.type == 'MESH' and has_assembly(desc) and desc != obj__:
                if desc not in nearby:
                    nearby.append(desc)
        if root.type == 'MESH' and has_assembly(root) and root != obj__:
            if root not in nearby:
                nearby.append(root)
    return nearby

def pick_assembly_assign_targets(context):
    """Return (controller, member) for Assign Cork/Label/Extra.

    Workflow: Set as Bottle once, then select cork/label alone and Assign.
    Also supports eyedropper (member chosen later) when only the bottle is active.
    """
    active = context.active_object
    selected = [o for o in context.selected_objects if o is not None]
    if active is None:
        return None, None

    # Active object is already an assembly bottle.
    if has_assembly(active):
        ctrl = active
        set_scene_assembly_bottle(context, ctrl)
        for o in selected:
            if o != ctrl:
                return ctrl, o
        return ctrl, None

    # Active is already linked as a member → its controller.
    ctrl = resolve_assembly_controller_object(active)
    if ctrl is not None and ctrl != active and has_assembly(ctrl):
        set_scene_assembly_bottle(context, ctrl)
        return ctrl, active

    # Selected bottle + active/other member.
    for o in selected:
        if has_assembly(o):
            set_scene_assembly_bottle(context, o)
            member = active if active != o else None
            if member is None:
                for s in selected:
                    if s != o:
                        member = s
                        break
            return o, member

    # Remembered bottle from last Set as Bottle / Assign.
    remembered = get_scene_assembly_bottle(context)
    if remembered is not None and active != remembered:
        return remembered, active

    # Nearby assembly bottle (same NORU_* hierarchy / collection).
    nearby = find_nearby_assembly_bottles(active)
    if len(nearby) == 1:
        set_scene_assembly_bottle(context, nearby[0])
        return nearby[0], active
    if len(nearby) > 1 and remembered in nearby:
        return remembered, active

    # Sole assembly bottle in the file.
    controllers = [
        o for o in bpy.data.objects
        if o.type == 'MESH' and has_assembly(o)]
    if len(controllers) == 1 and active != controllers[0]:
        set_scene_assembly_bottle(context, controllers[0])
        return controllers[0], active

    return None, active

def find_separate_liquid_object(src):
    marker = _lqfl_marker_get(src)
    name = marker.get('separate_liquid')
    if name and name in bpy.data.objects:
        obj__ = bpy.data.objects[name]
        if is_liquid_proxy_object(obj__):
            return obj__
    for child in src.children:
        if is_liquid_proxy_object(child):
            return child
    return None

def should_maintain_separate_liquid(obj__):
    if obj__ is None or obj__.type != 'MESH' or is_liquid_proxy_object(obj__):
        return False
    if not is_obj_filled(obj__):
        return False
    try:
        props = obj__.hrdc_liquifeel_input_field_props.geometry
    except Exception:
        return False
    if not getattr(props, 'separate_objects', False):
        return False
    if getattr(props, 'hide_recipient', False) or getattr(props, 'hide_liquid', False):
        return False
    return True

def _separate_liquid_signature(src):
    """Fingerprint of fill inputs that affect liquid mesh shape / shading."""
    try:
        fill_mod = get_geonodes_mod_by_ng_name(src, FILL_NG_NAME)
        vals = []
        for socket in fill_mod.node_group.interface.items_tree.values():
            if getattr(socket, 'in_out', None) == 'INPUT':
                try:
                    v = geonode_input_get(
                        fill_mod,
                        get_geonodes_field_identifier(fill_mod, socket.name))
                    if hasattr(v, 'name'):
                        v = v.name
                    vals.append((socket.name, v))
                except Exception:
                    vals.append((socket.name, None))
        props = src.hrdc_liquifeel_input_field_props.geometry
        vals.append(('separate', getattr(props, 'separate_objects', False)))
        vals.append(('hide_r', getattr(props, 'hide_recipient', False)))
        vals.append(('hide_l', getattr(props, 'hide_liquid', False)))
        vals.append(('opening', getattr(props, 'opening_shape', '')))
        return tuple(vals)
    except Exception:
        return None

def schedule_separate_refresh(obj__, force=False):
    if obj__ is None:
        return
    _pending_separate_refresh.add((obj__.name, bool(force)))
    if not bpy.app.timers.is_registered(_flush_separate_refresh_timer):
        bpy.app.timers.register(_flush_separate_refresh_timer, first_interval=0.0)

def _flush_separate_refresh_timer():
    pending = list(_pending_separate_refresh)
    context = bpy.context
    # Defer forced refreshes too — touching depsgraph mid-transform cancels G/R.
    if _is_transform_operator_running(context):
        return 0.05
    _pending_separate_refresh.clear()
    for name, force in pending:
        obj__ = bpy.data.objects.get(name)
        if obj__ is None:
            continue
        try:
            refresh_separate_objects_state(context, obj__, force=force)
        except Exception as e:
            print(f"LIQUIFEEL: separate refresh failed for '{name}': {e}")
    _ensure_separate_poll_timer()
    return None

def _any_separate_objects_active():
    for obj__ in bpy.data.objects:
        if obj__.type != 'MESH' or is_liquid_proxy_object(obj__):
            continue
        try:
            if getattr(
                    obj__.hrdc_liquifeel_input_field_props.geometry,
                    'separate_objects', False):
                return True
        except Exception:
            continue
    return False

def _ensure_separate_poll_timer():
    if _any_separate_objects_active():
        if not bpy.app.timers.is_registered(_separate_poll_timer):
            bpy.app.timers.register(_separate_poll_timer, first_interval=0.25)

def _is_transform_operator_running(context):
    """True while Grab/Rotate/Scale (or similar) modal is active."""
    op = getattr(context, 'active_operator', None)
    if op is None:
        return False
    op_id = getattr(op, 'bl_idname', '') or ''
    return (
        op_id.startswith('TRANSFORM_OT_')
        or op_id.startswith('OBJECT_OT_transform')
        or op_id in {
            'TRANSFORM_OT_translate',
            'TRANSFORM_OT_rotate',
            'TRANSFORM_OT_resize',
            'TRANSFORM_OT_skin_resize',
            'TRANSFORM_OT_trackball',
            'TRANSFORM_OT_push_pull',
            'TRANSFORM_OT_edge_slide',
            'TRANSFORM_OT_vert_slide',
        })

def _separate_poll_timer():
    """Keep liquid proxy in sync when modifier inputs change (no depsgraph hook)."""
    if _separate_objects_sync_lock:
        return 0.25
    context = bpy.context
    # Never touch the depsgraph mid-transform — that cancels Grab/Rotate.
    if _is_transform_operator_running(context):
        return 0.25
    any_active = False
    for obj__ in list(bpy.data.objects):
        if obj__.type != 'MESH' or is_liquid_proxy_object(obj__):
            continue
        try:
            maintain = should_maintain_separate_liquid(obj__)
            has_proxy = find_separate_liquid_object(obj__) is not None
            if not (maintain or has_proxy):
                continue
            any_active = True
            if maintain:
                sig = _separate_liquid_signature(obj__)
                ptr = obj__.name
                liquid = find_separate_liquid_object(obj__)
                if (liquid is not None
                        and len(liquid.data.vertices) > 0
                        and _separate_objects_last_sig.get(ptr) == sig):
                    # Nothing changed — do not tag/update the object.
                    continue
            refresh_separate_objects_state(context, obj__)
        except Exception:
            continue
    return 0.25 if any_active or _any_separate_objects_active() else None

def promote_separate_liquid_object(context, src):
    """Turn the live liquid proxy into a permanent, independent object."""
    liquid = find_separate_liquid_object(src)
    if liquid is None:
        try:
            if getattr(
                    src.hrdc_liquifeel_input_field_props.geometry,
                    'separate_objects', False):
                refresh_separate_objects_state(context, src, force=True)
                liquid = find_separate_liquid_object(src)
        except Exception:
            pass
    if liquid is None:
        return None
    before = _xform_diag_capture(context, src)
    try:
        _, _, liq_ws = liquid.matrix_world.decompose()
        before['liquid'] = liquid.name
        before['liquid_world_scale'] = _xform_diag_round_vec(liq_ws, 4)
        before['liquid_parent'] = (
            liquid.parent.name if liquid.parent else None)
    except Exception:
        pass
    try:
        sync_separate_liquid_mesh(context, src, liquid)
    except Exception as e:
        print(f"LIQUIFEEL: final liquid sync before apply failed: {e}")
    # Keep world transform, detach from bottle.
    mw = liquid.matrix_world.copy()
    liquid.parent = None
    liquid.matrix_world = mw
    base_name = f'{src.name}_liquid'
    liquid.name = base_name
    if liquid.data is not None:
        liquid.data.name = base_name
    if 'liquifeel' in liquid.keys():
        liquid.pop('liquifeel')
    marker = _lqfl_marker_get(src)
    if 'separate_liquid' in marker:
        marker = dict(marker)
        marker.pop('separate_liquid', None)
        _lqfl_marker_set(src, marker)
    _separate_objects_last_sig.pop(src.name, None)
    liquid.hide_set(False)
    liquid.hide_viewport = False
    liquid.hide_render = False
    after = _xform_diag_capture(context, src)
    try:
        _, _, liq_ws = liquid.matrix_world.decompose()
        after['liquid'] = liquid.name
        after['liquid_world_scale'] = _xform_diag_round_vec(liq_ws, 4)
        after['liquid_parent'] = (
            liquid.parent.name if liquid.parent else None)
    except Exception:
        pass
    _xform_diag_record(context, src, 'liquid_proxy_detach', before, after)
    return liquid

def _unique_collection_name(base_name):
    name = base_name
    i = 1
    while name in bpy.data.collections:
        name = f'{base_name}.{i:03d}'
        i += 1
    return name

def move_objects_to_new_collection(context, objects, base_name):
    """Create a new collection and put the given objects only there."""
    objs = [o for o in objects if o is not None]
    if not objs:
        return None
    col_name = _unique_collection_name(base_name)
    new_col = bpy.data.collections.new(col_name)
    # Parent under the same collection hierarchy as the first object when possible.
    parent_col = None
    for col in objs[0].users_collection:
        parent_col = col
        break
    if parent_col is not None:
        parent_col.children.link(new_col)
    else:
        context.scene.collection.children.link(new_col)
    for obj__ in objs:
        for col in list(obj__.users_collection):
            col.objects.unlink(obj__)
        if obj__.name not in new_col.objects:
            new_col.objects.link(obj__)
    return new_col

def teardown_separate_liquid_object(context, src):
    global _separate_objects_last_sig
    liquid = find_separate_liquid_object(src)
    if liquid is not None:
        mesh = liquid.data
        bpy.data.objects.remove(liquid, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)
    marker = _lqfl_marker_get(src)
    if 'separate_liquid' in marker:
        marker = dict(marker)
        marker.pop('separate_liquid', None)
        _lqfl_marker_set(src, marker)
    _separate_objects_last_sig.pop(src.name, None)
    if is_obj_filled(src):
        try:
            fill_mod = get_geonodes_mod_by_ng_name(src, FILL_NG_NAME)
            hide_liquid = getattr(
                src.hrdc_liquifeel_input_field_props.geometry, 'hide_liquid', False)
            fill_mod.show_viewport = not hide_liquid
        except Exception:
            pass

def ensure_separate_liquid_object(context, src):
    existing = find_separate_liquid_object(src)
    if existing is not None:
        return existing
    before = _xform_diag_capture(context, src)
    mesh = bpy.data.meshes.new(src.name + LIQUID_PROXY_SUFFIX)
    liquid = bpy.data.objects.new(src.name + LIQUID_PROXY_SUFFIX, mesh)
    linked = False
    for col in src.users_collection:
        col.objects.link(liquid)
        linked = True
    if not linked:
        context.collection.objects.link(liquid)
    liquid.parent = src
    liquid.matrix_parent_inverse.identity()
    liquid.location = (0.0, 0.0, 0.0)
    liquid.rotation_euler = (0.0, 0.0, 0.0)
    liquid.scale = (1.0, 1.0, 1.0)
    _lqfl_marker_set(liquid, {
        'version': bl_info['version'],
        'role': LIQUID_PROXY_ROLE,
        'source': src.name,
    })
    marker = _lqfl_marker_get(src)
    marker = dict(marker) if marker else {'version': bl_info['version']}
    marker['separate_liquid'] = liquid.name
    _lqfl_marker_set(src, marker)
    after = _xform_diag_capture(context, src)
    try:
        _, _, liq_ws = liquid.matrix_world.decompose()
        after['liquid'] = liquid.name
        after['liquid_world_scale'] = _xform_diag_round_vec(liq_ws, 4)
        after['liquid_parent'] = (
            liquid.parent.name if liquid.parent else None)
    except Exception:
        pass
    _xform_diag_record(context, src, 'liquid_proxy_parent', before, after)
    return liquid

def push_liquid_material_to_proxy(src, material):
    """Immediately put the Liquid Shader on the proxy mesh (slot 0, all faces)."""
    liquid = find_separate_liquid_object(src)
    if liquid is None or material is None or liquid.data is None:
        return
    mesh = liquid.data
    mesh.materials.clear()
    mesh.materials.append(material)
    for poly in mesh.polygons:
        poly.material_index = 0
    mesh.update()

def sync_separate_liquid_mesh(context, src, liquid_obj):
    """Bake evaluated liquid geometry onto the proxy, keeping materials/attrs.

    Fill GN often stores Liquid Shader at material slot index 1 (slot 0 empty).
    After bake we normalize the liquid-only mesh to a single Liquid Shader slot
    so shading always shows on the proxy object.
    """
    fill_mod = get_geonodes_mod_by_ng_name(src, FILL_NG_NAME)
    hide_mod = get_geonodes_mod_by_ng_name(src, HIDE_RECIPIENT_NG_NAME)
    hide_id = get_geonodes_field_identifier(hide_mod, 'Hide Recipient')
    saved_fill_vp = fill_mod.show_viewport
    saved_hide = geonode_input_get(hide_mod, hide_id)
    fill_mod.show_viewport = True
    for mod in src.modifiers:
        if is_shader_aux_modifier(mod, src, 'fill'):
            mod.show_viewport = True
    geonode_input_set(hide_mod, hide_id, True)
    src.update_tag()
    deps = context.evaluated_depsgraph_get()
    deps.update()
    ev = src.evaluated_get(deps)
    new_mesh = None
    try:
        new_mesh = bpy.data.meshes.new_from_object(
            ev, preserve_all_data_layers=True, depsgraph=deps)
        liquid_mat = None
        try:
            liquid_mat = get_geonode_mod_input(src, FILL_NG_NAME, 'Liquid Shader')
        except Exception:
            liquid_mat = None
        if liquid_mat is None:
            for slot_mat in new_mesh.materials:
                if slot_mat is not None:
                    liquid_mat = slot_mat
                    break
        # Liquid-only mesh: one material slot, all faces → Liquid Shader.
        if liquid_mat is not None:
            new_mesh.materials.clear()
            new_mesh.materials.append(liquid_mat)
            for poly in new_mesh.polygons:
                poly.material_index = 0
        old_mesh = liquid_obj.data
        liquid_obj.data = new_mesh
        new_mesh = None
        if old_mesh is not None and old_mesh.users == 0:
            bpy.data.meshes.remove(old_mesh)
        liquid_obj.data.update()
        if liquid_mat is not None:
            push_liquid_material_to_proxy(src, liquid_mat)
    finally:
        if new_mesh is not None and new_mesh.users == 0:
            bpy.data.meshes.remove(new_mesh)
        fill_mod.show_viewport = saved_fill_vp
        geonode_input_set(hide_mod, hide_id, saved_hide)
        src.update_tag()

def refresh_separate_objects_state(context, obj__, force=False):
    global _separate_objects_sync_lock
    if _separate_objects_sync_lock or obj__ is None:
        return
    if is_liquid_proxy_object(obj__):
        return
    if _is_transform_operator_running(context) and not force:
        return
    _separate_objects_sync_lock = True
    try:
        if should_maintain_separate_liquid(obj__):
            sig = _separate_liquid_signature(obj__)
            ptr = obj__.as_pointer()
            liquid = find_separate_liquid_object(obj__)
            if (not force
                    and liquid is not None
                    and len(liquid.data.vertices) > 0
                    and _separate_objects_last_sig.get(ptr) == sig):
                fill_mod = get_geonodes_mod_by_ng_name(obj__, FILL_NG_NAME)
                # Only write if needed — writing every tick breaks transforms.
                if fill_mod.show_viewport:
                    fill_mod.show_viewport = False
                return
            fill_mod = get_geonodes_mod_by_ng_name(obj__, FILL_NG_NAME)
            # Bottle stays on the source (Select Outer); liquid lives on the proxy.
            fill_mod.show_viewport = False
            liquid = ensure_separate_liquid_object(context, obj__)
            sync_separate_liquid_mesh(context, obj__, liquid)
            liquid.hide_set(False)
            liquid.hide_viewport = False
            liquid.hide_render = False
            _separate_objects_last_sig[ptr] = sig
        else:
            teardown_separate_liquid_object(context, obj__)
    finally:
        _separate_objects_sync_lock = False

def _unregister_separate_timers():
    if bpy.app.timers.is_registered(_flush_separate_refresh_timer):
        bpy.app.timers.unregister(_flush_separate_refresh_timer)
    if bpy.app.timers.is_registered(_separate_poll_timer):
        bpy.app.timers.unregister(_separate_poll_timer)
    if bpy.app.timers.is_registered(_flush_bottle_bake_timer):
        bpy.app.timers.unregister(_flush_bottle_bake_timer)
    if bpy.app.timers.is_registered(_assembly_seed_drop_slots_timer):
        bpy.app.timers.unregister(_assembly_seed_drop_slots_timer)
    _pending_separate_refresh.clear()
    _pending_bottle_bake.clear()
    _separate_objects_last_sig.clear()

# # key_chain: ['liquifeel_input_field_props', 'geometry', 'manual']
# # path: liquifeel_input_field_props.geometry.manual
# class ObjectAttached_Manual_Geometry_InputProps(bpy.types.PropertyGroup):
#     opening_shape: bpy.props.EnumProperty(
#         name='Opening Shape',
#         update=opening_shape_mandef_update,
#         default='straight',
#         items=[
#             ('straight', 'Straight', 'The mouth of the recipient has no kink.'),
#             ('irregular', 'Irregular', 'The mouth of the recipient has a kink.')])
#     hide_recipient: bpy.props.BoolProperty(
#         name='Hide Recipient',
#         update=hide_recipient_update,
#         default=False)
#     hide_liquid: bpy.props.BoolProperty(
#         name='Hide Liquid',
#         update=hide_liquid_update,
#         default=False)
# registerable_classes.append(ObjectAttached_Manual_Geometry_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'geometry']
# # path: liquifeel_input_field_props.geometry
# class ObjectAttached_Geometry_InputProps(bpy.types.PropertyGroup):
#     synthetic: bpy.props.PointerProperty(type=ObjectAttached_Synthetic_Geometry_InputProps)
#     manual: bpy.props.PointerProperty(type=ObjectAttached_Manual_Geometry_InputProps)
# registerable_classes.append(ObjectAttached_Geometry_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'shading', 'slot', 'synthetic']
# # path: liquifeel_input_field_props.shading.slot.synthetic
# # class ObjectAttached_Synthetic_SlotShading_InputProps
# declare_and_register_synthetic_prop_parent(
#         'shading', 'object_attached', shading_modality_key='slot')
# # class ObjectAttached_Synthetic_SlotShading_InputProps(bpy.types.PropertyGroup):
# #     pass
# # registerable_classes.append(ObjectAttached_Synthetic_SlotShading_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'shading', 'fill', 'synthetic']
# # path: liquifeel_input_field_props.shading.slot.synthetic
# # class ObjectAttached_Synthetic_FillShading_InputProps
# declare_and_register_synthetic_prop_parent(
#         'shading', 'object_attached', shading_modality_key='fill')
# # class ObjectAttached_Synthetic_FillShading_InputProps(bpy.types.PropertyGroup):
# #     pass
# # registerable_classes.append(ObjectAttached_Synthetic_FillShading_InputProps)

# # # key_chain: ['liquifeel_input_field_props', 'shading', 'synthetic']
# # # path: liquifeel_input_field_props.shading.synthetic
# # # class ObjectAttached_Synthetic_Shading_InputProps
# # declare_and_register_synthetic_prop_parent(
# #         'shading', 'object_attached')
# # # class ObjectAttached_Synthetic_Shading_InputProps(bpy.types.PropertyGroup):
# # #     pass
# # # registerable_classes.append(ObjectAttached_Synthetic_Shading_InputProps)

material_library_items = [
    ('solids', 'Solids', 'Shade object with materials from Liquifeel\'s solids library.'),
    ('liquids', 'Liquids', 'Shade object with materials from Liquifeel\'s liquid library.'),
    ('scene', 'Scene materials', 'Shade object with materials present in the scene.')
]

liquids_shader_items = []
for mat_name in INPUT_FIELD_DATA['shading']['liquids'].keys():
    liquids_shader_items.append((
        mat_name, mat_name,
        mat_name,
        # json.dumps(INPUT_FIELD_DATA['shading']['liquids'][mat_name],
        #            indent=2, sort_keys=True),
        preview_data['ids']['material_thumbnails'][
            key_from_name(mat_name)],
        len(liquids_shader_items)
    ))

solids_shader_items = []
for mat_name in INPUT_FIELD_DATA['shading']['solids'].keys():
    solids_shader_items.append((
        mat_name, mat_name,
        mat_name,
        # json.dumps(INPUT_FIELD_DATA['shading']['solids'][mat_name],
        #            indent=2, sort_keys=True),
        preview_data['ids']['material_thumbnails'][
            key_from_name(mat_name)],
        len(solids_shader_items)
    ))

def scene_shader_items(instance, context):
    try:
        items = []
        for mat in bpy.data.materials:
            icon_val = bpy.types.UILayout.icon(mat)
            if not(icon_val):
                icon_val = 'MATERIAL'
            items.append((
                mat.name, mat.name, mat.name,
                icon_val, len(items)
            ))
        return items
    except:
        return []

# @undo_push(2)




# # key_chain: ['liquifeel_input_field_props', 'shading', 'slot', 'manual', 'material_selector']
# # path: liquifeel_input_field_props.shading.slot.manual.material_selector
# class ObjectAttached_Manual_SlotShading_MatSel_InputProps(
#         bpy.types.PropertyGroup):
#     library: bpy.props.EnumProperty(
#         name='Opening Shape',
#         update=slot_library_update,
#         default='solids',
#         items=material_library_items)
#     # pattern_library: bpy.props.EnumProperty(
#     #     name='Pattern Library',
#     #     update=pattern_library_update,
#     #     default='liquifeel',
#     #     items=[
#     #         ('liquifeel', 'Liquifeel', 'Patterns packaged with Liquifeel'),
#     #         ('user_defined', 'User Defined', 'Patterns added by the user.'),
#     #     ])
#     liquids_material: bpy.props.EnumProperty( # formerly library_liquids_material
#         name='Slot Material',
#         update=slot_shading_material_update,
#         default='Water',
#         items=liquids_shader_items)
#     solids_material: bpy.props.EnumProperty( # formerly library_solids_material
#         name='Slot Material',
#         update=slot_shading_material_update,
#         items=solids_shader_items)
#     scene_material: bpy.props.EnumProperty( # formerly scene_material
#         name='Slot Material',
#         update=scene_slot_shading_material_update,
#         items=scene_shader_items)
# registerable_classes.append(
#     ObjectAttached_Manual_SlotShading_MatSel_InputProps)

# # @undo_push(2)
# def fill_library_update(slf, context):
#     pass

# @undo_push(2)
# def fill_shading_material_update(slf, context):
#     obj__ = context.active_object
#     library_key = getattr(slf, 'library')
#     material_name = getattr(slf, f'{library_key}_material')
#     fill_shade(context, obj__, library_key, material_name)

# @undo_push(2)
# def scene_fill_shading_material_update(slf, context):
#     obj__ = context.active_object
#     material_name = getattr(slf, 'scene_material')
#     fill_shade(context, obj__, 'scene', material_name)

# # key_chain: ['liquifeel_input_field_props', 'shading', 'manual', 'fill_material_selector']
# # path: liquifeel_input_field_props.shading.manual.fill_material_selector
# class ObjectAttached_Manual_FillShading_MatSel_InputProps(
#         bpy.types.PropertyGroup):
#     library: bpy.props.EnumProperty(
#         name='Opening Shape',
#         update=fill_library_update,
#         default='liquids',
#         items=material_library_items)
#     # pattern_library: bpy.props.EnumProperty(
#     #     name='Pattern Library',
#     #     update=pattern_library_update,
#     #     default='liquifeel',
#     #     items=[
#     #         ('liquifeel', 'Liquifeel', 'Patterns packaged with Liquifeel'),
#     #         ('user_defined', 'User Defined', 'Patterns added by the user.'),
#     #     ])
#     liquids_material: bpy.props.EnumProperty( # formerly library_liquids_material
#         name='Fill Material',
#         update=fill_shading_material_update,
#         default='Water',
#         items=liquids_shader_items)
#     solids_material: bpy.props.EnumProperty( # formerly library_solids_material
#         name='Fill Material',
#         update=fill_shading_material_update,
#         items=solids_shader_items)
#     scene_material: bpy.props.EnumProperty( # formerly scene_material
#         name='Fill Material',
#         update=scene_fill_shading_material_update,
#         items=scene_shader_items)
# registerable_classes.append(
#     ObjectAttached_Manual_FillShading_MatSel_InputProps)

# # @undo_push(2)
# def pattern_texture_updt(slf, context):
#     obj__ = context.active_object
#     # It's impossible to fill a recipient with patterned glass, so we
#     # won't put the property wielding this callback in the
#     # MaterialAttached_Synthetic_FillShading_InputProps
#     # structure. Thus we can hard-code the shading_modality_key.
#     material = get_asset_material(
#         obj__, shading_modality_key='slot')
#     redux_input_data = index_hierarchy_by_path(
#         REDUX_INPUT_DATA,
#         ['shading', 'material_attached',
#          'Pattern Texture; Pattern Texture Resolution; Pattern Library; User Pattern Texture'])
#     path_as_mapping = redux_input_data['paths'][0]['mapping']
#     input_data = index_hierarchy_by_path(INPUT_FIELD_DATA, redux_input_data['paths'][0]['list'])
#     node_names = path_as_mapping['group_name']
#     nodes = [get_material_node(material, node_name.strip()) for node_name in node_names.split(';')]
#     val_data = get_prop_vals(slf, ["pattern_texture_resolution", "pattern_library"])
#     res_key = val_data['pattern_texture_resolution']
#     pat_lib_key = val_data['pattern_library']
#     # if pat_lib_key == 'user_defined' and are_user_defined_patterns_present():
#     if pat_lib_key == 'user_defined' and are_user_defined_maps_present('pattern'):
#         img_key = get_prop_vals(slf, "user_pattern_texture")
#         img = bpy.data.images[img_key]
#         img_tex_fpath = img.filepath_from_user()
#         assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)
#     elif pat_lib_key == 'liquifeel':
#         img_key = get_prop_vals(slf, "pattern_texture")
#         img_tex_fpath = FPATHS[
#             input_data['enum_source_fpath_key']][img_key][res_key]
#         img = maybe_load_image(img_tex_fpath)
#         assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)

def hrdc_roughness_texture_updt(slf, context):
    obj__ = context.active_object
    material = hrdc_get_asset_material(
        obj__, shading_modality_key='slot')
    node_names = ['RoughnessImage_UV', 'RoughnessImage_Box']
    nodes = [get_material_node(material, node_name) for node_name in node_names]
    # nodes = [get_material_node(material, node_name.strip()) for node_name in node_names.split(';')]
    val_data = get_prop_vals(slf, ["roughness_texture_resolution", "roughness_library"])
    res_key = val_data['roughness_texture_resolution']
    pat_lib_key = val_data['roughness_library']
    if pat_lib_key == 'user_defined' and are_user_defined_maps_present('roughness'):
        img_key = get_prop_vals(slf, "user_roughness_texture")
        img = bpy.data.images[img_key]
        img_tex_fpath = img.filepath_from_user()
        assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)
    elif pat_lib_key == 'liquifeel':
        img_key = get_prop_vals(slf, "roughness_texture")
        img_tex_fpath = FPATHS[
            'recipient_roughness_maps'][img_key][res_key]
        img = maybe_load_image(img_tex_fpath)
        assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)

def hrdc_pattern_texture_updt(slf, context):
    obj__ = context.active_object
    # It's impossible to fill a recipient with patterned glass, so we
    # won't put the property wielding this callback in the
    # MaterialAttached_Synthetic_FillShading_InputProps
    # structure. Thus we can hard-code the shading_modality_key.
    material = hrdc_get_asset_material(
        obj__, shading_modality_key='slot')
    redux_input_data = index_hierarchy_by_path(
        REDUX_INPUT_DATA,
        ['shading', 'material_attached',
         'Pattern Texture; Pattern Texture Resolution; Pattern Library; User Pattern Texture'])
    path_as_mapping = redux_input_data['paths'][0]['mapping']
    input_data = index_hierarchy_by_path(INPUT_FIELD_DATA, redux_input_data['paths'][0]['list'])
    node_names = path_as_mapping['group_name']
    nodes = [get_material_node(material, node_name.strip()) for node_name in node_names.split(';')]
    val_data = get_prop_vals(slf, ["pattern_texture_resolution", "pattern_library"])
    res_key = val_data['pattern_texture_resolution']
    pat_lib_key = val_data['pattern_library']
    if pat_lib_key == 'user_defined' and are_user_defined_maps_present('pattern'):
        img_key = get_prop_vals(slf, "user_pattern_texture")
        img = bpy.data.images[img_key]
        img_tex_fpath = img.filepath_from_user()
        assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)
    elif pat_lib_key == 'liquifeel':
        img_key = get_prop_vals(slf, "pattern_texture")
        img_tex_fpath = FPATHS[
            input_data['enum_source_fpath_key']][img_key][res_key]
        img = maybe_load_image(img_tex_fpath)
        assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)

# # @undo_push(2)
# def roughness_texture_updt(slf, context):
#     obj__ = context.active_object
#     # Only applicable on slot shaded materials (glass)
#     material = get_asset_material(
#         obj__, shading_modality_key='slot')
#     redux_input_data = index_hierarchy_by_path(
#         REDUX_INPUT_DATA,
#         ['shading', 'material_attached',
#          'User Roughness Texture'])
#     path_as_mapping = redux_input_data['paths'][0]['mapping']
#     input_data = index_hierarchy_by_path(INPUT_FIELD_DATA, redux_input_data['paths'][0]['list'])
#     node_names = path_as_mapping['group_name']
#     nodes = [get_material_node(material, node_name.strip()) for node_name in node_names.split(';')]
#     val_data = get_prop_vals(slf, ["pattern_texture_resolution", "pattern_library"])
#     res_key = val_data['pattern_texture_resolution']
#     pat_lib_key = val_data['pattern_library']
#     # if pat_lib_key == 'user_defined' and are_user_defined_patterns_present():
#     if pat_lib_key == 'user_defined' and are_user_defined_maps_present('roughness'):
#         img_key = get_prop_vals(slf, "user_pattern_texture")
#         img = bpy.data.images[img_key]
#         img_tex_fpath = img.filepath_from_user()
#         assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)
#     elif pat_lib_key == 'liquifeel':
#         img_key = get_prop_vals(slf, "pattern_texture")
#         img_tex_fpath = FPATHS[
#             input_data['enum_source_fpath_key']][img_key][res_key]
#         img = maybe_load_image(img_tex_fpath)
#         assign_image_to_nodes(obj__, nodes, img, img_tex_fpath)

# # This is one of the manually defined prop update functions. The
# # function should be as concrete and hard-coded as possible to reduce
# # the run-time load of logic in the body of the function. These
# # functions are stupidly simple.
# mapping_patternutils_updt__mapping = {'Box': True, 'UV': False}
# def mapping_patternutils_updt(prop_parent, context):
#     obj__ = context.active_object
#     # # DEV CRUTCH
#     # prop_parent = obj__.liquifeel_field_inputs.slot_shading.solids_inputs.uber_glass.geonode.patternutils
#     # REDUX_INPUT_DATA['shading'][target_attachment_key][input_name]
#     redux_input_data = REDUX_INPUT_DATA['shading']['object_attached']['Mapping']
#     prop_val_data = get_prop_vals(prop_parent, redux_input_data['prop_key'])
#     ng_name = redux_input_data['unanimous_path_elems']['group_name']
#     mod = get_geonodes_mod_by_ng_name(obj__, ng_name) 
#     identifier = get_geonodes_field_identifier(mod, redux_input_data['underlying_input_name'])
#     val = mapping_patternutils_updt__mapping[prop_val_data]
#     mod[identifier] = val
#     # Update render view
#     update_obj_render_view(context, obj__)

# # hrdc_mapping_patternutils_updt__mapping = {'Box': True, 'UV': False}
# # def hrdc_mapping_patternutils_updt(prop_parent, context):
# #     obj__ = context.active_object
# #     prop_val = getattr(prop_parent, 'pattern_mapping')
# #     mod = get_geonodes_mod_by_ng_name(obj__, 'PatternUtils') 
# #     identifier = get_geonodes_field_identifier(mod, 'UV/Box')
# #     val = hrdc_mapping_patternutils_updt__mapping[prop_val]
# #     mod[identifier] = val
# #     # Update render view
# #     update_obj_render_view(context, obj__)

# # hrdc_mapping_roughnessutils_updt__mapping = {'Box': True, 'UV': False}
# # def hrdc_mapping_roughnessutils_updt(prop_parent, context):
# #     obj__ = context.active_object
# #     prop_val = getattr(prop_parent, 'roughness_mapping')
# #     mod = get_geonodes_mod_by_ng_name(obj__, 'RoughnessUtils') 
# #     identifier = get_geonodes_field_identifier(mod, 'UV/Box')
# #     val = hrdc_mapping_roughnessutils_updt__mapping[prop_val]
# #     mod[identifier] = val
# #     # Update render view
# #     update_obj_render_view(context, obj__)

# def uv_name_patternutils_geonode_mandef_updt(prop_parent, context):
#     obj__ = context.active_object
#     # # DEV CRUTCH
#     # prop_parent = obj__.liquifeel_field_inputs.slot_shading.solids_inputs.uber_glass.geonode.patternutils
#     # REDUX_INPUT_DATA['shading'][target_attachment_key][input_name]
#     redux_input_data = REDUX_INPUT_DATA['shading']['object_attached']['UV Name']
#     val = get_prop_vals(prop_parent, redux_input_data['prop_key'])
#     ng_name = redux_input_data['unanimous_path_elems']['group_name']
#     mod = get_geonodes_mod_by_ng_name(obj__, ng_name) 
#     identifier = get_geonodes_field_identifier(mod, redux_input_data['underlying_input_name'])
#     mod[identifier] = val

def hrdc_uv_name_patternutils_geonode_mandef_updt(prop_parent, context):
    obj__ = context.active_object
    prop_val = getattr(prop_parent, 'pattern_uv_name')
    mod = get_geonodes_mod_by_ng_name(obj__, 'PatternUtils')
    identifier = get_geonodes_field_identifier(mod, 'UV Name')
    geonode_input_set(mod, identifier, prop_val)

def hrdc_uv_name_roughnessutils_geonode_mandef_updt(prop_parent, context):
    obj__ = context.active_object
    prop_val = getattr(prop_parent, 'roughness_uv_name')
    mod = get_geonodes_mod_by_ng_name(obj__, 'RoughnessUtils')
    identifier = get_geonodes_field_identifier(mod, 'UV Name')
    geonode_input_set(mod, identifier, prop_val)

# def vertex_group_patternutils_geonode_mandef_updt(prop_parent, context):
#     obj__ = context.active_object
#     # # DEV CRUTCH
#     # prop_parent = obj__.liquifeel_field_inputs.slot_shading.solids_inputs.uber_glass.geonode.patternutils
#     # REDUX_INPUT_DATA['shading'][target_attachment_key][input_name]
#     redux_input_data = REDUX_INPUT_DATA['shading']['object_attached']['Vertex Group']
#     val = get_prop_vals(prop_parent, redux_input_data['prop_key'])
#     ng_name = redux_input_data['unanimous_path_elems']['group_name']
#     mod = get_geonodes_mod_by_ng_name(obj__, ng_name) 
#     identifier = get_geonodes_field_identifier(mod, redux_input_data['underlying_input_name'])
#     mod[identifier] = val

def hrdc_vertex_group_patternutils_geonode_mandef_updt(prop_parent, context):
    obj__ = context.active_object
    prop_val = getattr(prop_parent, 'pattern_vertex_group')
    mod = get_geonodes_mod_by_ng_name(obj__, 'PatternUtils')
    identifier = get_geonodes_field_identifier(mod, 'Vertex Group')
    geonode_input_set(mod, identifier, prop_val)

def hrdc_vertex_group_roughnessutils_geonode_mandef_updt(prop_parent, context):
    obj__ = context.active_object
    prop_val = getattr(prop_parent, 'roughness_vertex_group')
    mod = get_geonodes_mod_by_ng_name(obj__, 'RoughnessUtils')
    identifier = get_geonodes_field_identifier(mod, 'Vertex Group')
    geonode_input_set(mod, identifier, prop_val)

# @undo_push(2)
# def scene_slot_shading_material_update(slf, context):
#     obj__ = context.active_object
#     material_name = getattr(slf, 'slot_shading_scene_material')
#     slot_shade(context, obj__, 'scene', material_name)

# @undo_push(2)
# def scene_fill_shading_material_update(slf, context):
#     obj__ = context.active_object
#     material_name = getattr(slf, 'fill_shading_scene_material')
#     fill_shade(context, obj__, 'scene', material_name)

# # key_chain: ['liquifeel_input_field_props', 'shading', 'slot', 'manual']
# # path: liquifeel_input_field_props.shading.slot.manual
# class ObjectAttached_Manual_SlotShading_InputProps(bpy.types.PropertyGroup):
#     mapping: bpy.props.EnumProperty(
#         name='Mapping',
#         update=mapping_patternutils_updt,
#         default='Box',
#         items=[
#             ('Box', 'Box', 'Box(True)'),
#             ('UV', 'UV', 'UV(False)'),
#         ])
#     uv_name: bpy.props.EnumProperty(
#         name='UV Name',
#         update=uv_name_patternutils_geonode_mandef_updt,
#         items=get_object_uv_maps_items_f())
#     vertex_group: bpy.props.EnumProperty(
#         name='Vertex Group',
#         update=vertex_group_patternutils_geonode_mandef_updt,
#         items=get_object_vertex_groups_items_f())
#     # material selector properties
#     material_selector: bpy.props.PointerProperty(
#         type=ObjectAttached_Manual_SlotShading_MatSel_InputProps)
# registerable_classes.append(ObjectAttached_Manual_SlotShading_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'shading', 'fill', 'manual']
# # path: liquifeel_input_field_props.shading.fill.manual
# class ObjectAttached_Manual_FillShading_InputProps(bpy.types.PropertyGroup):
#     mapping: bpy.props.EnumProperty(
#         name='Mapping',
#         update=mapping_patternutils_updt,
#         default='Box',
#         items=[
#             ('Box', 'Box', 'Box(True)'),
#             ('UV', 'UV', 'UV(False)'),
#         ])
#     uv_name: bpy.props.EnumProperty(
#         name='UV Name',
#         update=uv_name_patternutils_geonode_mandef_updt,
#         items=get_object_uv_maps_items_f())
#     vertex_group: bpy.props.EnumProperty(
#         name='Vertex Group',
#         update=vertex_group_patternutils_geonode_mandef_updt,
#         items=get_object_vertex_groups_items_f())
#     # material selector properties
#     material_selector: bpy.props.PointerProperty(
#         type=ObjectAttached_Manual_FillShading_MatSel_InputProps)
# registerable_classes.append(ObjectAttached_Manual_FillShading_InputProps)

# # # key_chain: ['liquifeel_input_field_props', 'shading', 'manual']
# # # path: liquifeel_input_field_props.shading.manual
# # class ObjectAttached_Manual_Shading_InputProps(bpy.types.PropertyGroup):
# #     mapping: bpy.props.EnumProperty(
# #         name='Mapping',
# #         update=mapping_patternutils_updt,
# #         default='Box',
# #         items=[
# #             ('Box', 'Box', 'Box(True)'),
# #             ('UV', 'UV', 'UV(False)'),
# #         ])
# #     uv_name: bpy.props.EnumProperty(
# #         name='UV Name',
# #         update=uv_name_patternutils_geonode_mandef_updt,
# #         items=get_object_uv_maps_items_f())
# #     vertex_group: bpy.props.EnumProperty(
# #         name='Vertex Group',
# #         update=vertex_group_patternutils_geonode_mandef_updt,
# #         items=get_object_vertex_groups_items_f())
# #     # material selector properties
# #     slot_material_selector: bpy.props.PointerProperty(
# #         type=ObjectAttached_Manual_SlotShading_MatSel_InputProps)
# #     fill_material_selector: bpy.props.PointerProperty(
# #         type=ObjectAttached_Manual_FillShading_MatSel_InputProps)
# # registerable_classes.append(ObjectAttached_Manual_Shading_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'shading', 'slot']
# # path: liquifeel_input_field_props.shading.slot
# class ObjectAttached_SlotShading_InputProps(bpy.types.PropertyGroup):
#     synthetic: bpy.props.PointerProperty(type=ObjectAttached_Synthetic_SlotShading_InputProps)
#     manual: bpy.props.PointerProperty(type=ObjectAttached_Manual_SlotShading_InputProps)
# registerable_classes.append(ObjectAttached_SlotShading_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'shading', 'fill']
# # path: liquifeel_input_field_props.shading.fill
# class ObjectAttached_FillShading_InputProps(bpy.types.PropertyGroup):
#     synthetic: bpy.props.PointerProperty(type=ObjectAttached_Synthetic_FillShading_InputProps)
#     manual: bpy.props.PointerProperty(type=ObjectAttached_Manual_FillShading_InputProps)
# registerable_classes.append(ObjectAttached_FillShading_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'shading']
# # path: liquifeel_input_field_props.shading
# class ObjectAttached_Shading_InputProps(bpy.types.PropertyGroup):
#     slot: bpy.props.PointerProperty(type=ObjectAttached_SlotShading_InputProps)
#     fill: bpy.props.PointerProperty(type=ObjectAttached_FillShading_InputProps)
# registerable_classes.append(ObjectAttached_Shading_InputProps)

# # # key_chain: ['liquifeel_input_field_props', 'shading']
# # # path: liquifeel_input_field_props.shading
# # class ObjectAttached_Shading_InputProps(bpy.types.PropertyGroup):
# #     synthetic: bpy.props.PointerProperty(type=ObjectAttached_Synthetic_Shading_InputProps)
# #     manual: bpy.props.PointerProperty(type=ObjectAttached_Manual_Shading_InputProps)
# # registerable_classes.append(ObjectAttached_Shading_InputProps)

# # key_chain: ['liquifeel_input_field_props']
# # path: liquifeel_input_field_props
# class ObjectAttached_InputProps(bpy.types.PropertyGroup):
#     geometry: bpy.props.PointerProperty(type=ObjectAttached_Geometry_InputProps)
#     shading: bpy.props.PointerProperty(type=ObjectAttached_Shading_InputProps)
# registerable_classes.append(ObjectAttached_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'slot', 'synthetic']
# # path: liquifeel_input_field_props.slot.synthetic
# # class MaterialAttached_Synthetic_SlotShading_InputProps
# declare_and_register_synthetic_prop_parent(
#         'shading', 'material_attached', shading_modality_key='slot')
# # class MaterialAttached_Synthetic_SlotShading_InputProps(bpy.types.PropertyGroup):
# #     pass
# # registerable_classes.append(MaterialAttached_Synthetic_SlotShading_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'slot', 'manual']
# # path: liquifeel_input_field_props.slot.manual
# class MaterialAttached_Manual_SlotShading_InputProps(bpy.types.PropertyGroup):
#     # pattern properties
#     pattern_texture: bpy.props.EnumProperty(
#         name='Pattern Texture',
#         update=pattern_texture_updt,
#         items=gen_pattern_imgtex_img_items)
#     user_pattern_texture: bpy.props.EnumProperty(
#         name='User Pattern Texture',
#         update=pattern_texture_updt,
#         items=gen_pattern_user_imgtex_img_items)
#     pattern_texture_resolution: bpy.props.EnumProperty(
#         name='Pattern Texture Resolution',
#         update=pattern_texture_updt,
#         items=gen_map_imgtex_res_items)
#     pattern_library: bpy.props.EnumProperty(
#         name='Pattern Library',
#         default='liquifeel',
#         update=pattern_texture_updt,
#         items=[
#             ('liquifeel', 'Liquifeel', 'Patterns packaged with Liquifeel'),
#             ('user_defined', 'User Defined', 'Patterns added by the user.'),
#         ])
#     # roughness map properties
#     # user_roughness_texture: bpy.props.EnumProperty(
#     #     name='User Roughness Texture',
#     #     update=roughness_texture_updt,
#     #     items=gen_roughness_user_imgtex_img_items)
#     # roughness_texture_resolution: bpy.props.EnumProperty(
#     #     name='Roughness Texture Resolution',
#     #     update=roughness_texture_updt,
#     #     items=gen_roughness_imgtex_res_items)
# registerable_classes.append(MaterialAttached_Manual_SlotShading_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'slot']
# # path: liquifeel_input_field_props.slot
# class MaterialAttached_SlotShading_InputProps(bpy.types.PropertyGroup):
#     synthetic: bpy.props.PointerProperty(type=MaterialAttached_Synthetic_SlotShading_InputProps)
#     manual: bpy.props.PointerProperty(type=MaterialAttached_Manual_SlotShading_InputProps)
# registerable_classes.append(MaterialAttached_SlotShading_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'fill', 'synthetic']
# # path: liquifeel_input_field_props.fill.synthetic
# # class MaterialAttached_Synthetic_FillShading_InputProps
# declare_and_register_synthetic_prop_parent(
#         'shading', 'material_attached', shading_modality_key='fill')
# # class MaterialAttached_Synthetic_FillShading_InputProps(bpy.types.PropertyGroup):
# #     pass
# # registerable_classes.append(MaterialAttached_Synthetic_FillShading_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'fill', 'manual']
# # path: liquifeel_input_field_props.fill.manual
# class MaterialAttached_Manual_FillShading_InputProps(bpy.types.PropertyGroup):
#     # pattern properties
#     pattern_texture: bpy.props.EnumProperty(
#         name='Pattern Texture',
#         update=pattern_texture_updt,
#         items=gen_pattern_imgtex_img_items)
#     user_pattern_texture: bpy.props.EnumProperty(
#         name='User Pattern Texture',
#         update=pattern_texture_updt,
#         items=gen_pattern_user_imgtex_img_items)
#     pattern_texture_resolution: bpy.props.EnumProperty(
#         name='Pattern Texture Resolution',
#         update=pattern_texture_updt,
#         items=gen_map_imgtex_res_items)
#     pattern_library: bpy.props.EnumProperty(
#         name='Pattern Library',
#         default='liquifeel',
#         update=pattern_texture_updt,
#         items=[
#             ('liquifeel', 'Liquifeel', 'Patterns packaged with Liquifeel'),
#             ('user_defined', 'User Defined', 'Patterns added by the user.'),
#         ])
#     # library: bpy.props.EnumProperty(
#     #     name='Library',
#     #     update=fill_library_update,
#     #     default='liquids',
#     #     items=material_library_items)
# registerable_classes.append(MaterialAttached_Manual_FillShading_InputProps)

# # key_chain: ['liquifeel_input_field_props', 'fill']
# # path: liquifeel_input_field_props.fill
# class MaterialAttached_FillShading_InputProps(bpy.types.PropertyGroup):
#     synthetic: bpy.props.PointerProperty(type=MaterialAttached_Synthetic_FillShading_InputProps)
#     manual: bpy.props.PointerProperty(type=MaterialAttached_Manual_FillShading_InputProps)
# registerable_classes.append(MaterialAttached_FillShading_InputProps)

# # key_chain: ['liquifeel_input_field_props']
# # path: liquifeel_input_field_props
# class MaterialAttached_InputProps(bpy.types.PropertyGroup):
#     slot: bpy.props.PointerProperty(type=MaterialAttached_SlotShading_InputProps)
#     fill: bpy.props.PointerProperty(type=MaterialAttached_FillShading_InputProps)
# registerable_classes.append(MaterialAttached_InputProps)

# property_types = {
#     'int': bpy.props.IntProperty,
#     'float': bpy.props.FloatProperty,
#     'bool': bpy.props.BoolProperty,
#     'bool_to_float': bpy.props.BoolProperty,
#     'enum': bpy.props.EnumProperty,
#     'color': bpy.props.FloatVectorProperty,
# }

main_tab_items = []
for n, tab_key in enumerate(MAIN_TAB_KEYS):
    if tab_key in MAIN_TAB_BUILTIN_ICONS.keys():
        icon_key = MAIN_TAB_BUILTIN_ICONS[tab_key]
    else:
        icon_key = preview_data['ids']['icons'][tab_key]
    name = MAIN_TAB_NAMES[tab_key]
    main_tab_items.append((
        tab_key, # key
        name, # name
        name, # description
        icon_key, # icon
        n # position
    ))

shading_target_items = [
    ('recipient', 'to Recipient',
     'Apply shader to the liquifeel recipient object'),
    ('liquid', 'to Liquid',
     'Apply shader to the liquifeel liquid object'),
]

recipient_asset_items = []
for asset_key, name_data in RECIPIENT_ASSET_NAME_DATA.items():
    recipient_asset_items.append((
        asset_key,
        RECIPIENT_ASSET_NAME_DATA[asset_key]['thumbnail'], RECIPIENT_ASSET_NAME_DATA[asset_key]['thumbnail'],
        preview_data['ids']['recipient_asset_thumbnails'][asset_key],
        len(recipient_asset_items)
    ))

# # KEEP
# @undo_push(2)
# def performance_render_mode_update(slf, context):
#     print(
#         f'performance_render_mode_update({slf}, context)',
#         ':',
#         getattr(slf, 'performance_render_mode'))
#     adjust_render_settings(
#         context, light=getattr(slf, 'performance_render_mode'))

class LQFL_AssemblyPartItem(bpy.types.PropertyGroup):
    """One drop-target slot for an assembly part (Outliner drag / eyedropper)."""
    object: bpy.props.PointerProperty(
        name='Part',
        type=bpy.types.Object,
        poll=_assembly_part_poll,
        update=assembly_part_pointer_update,
    )
registerable_classes.append(LQFL_AssemblyPartItem)

## The properties which are not asset specific (i.e. main tabs)
class GeneralUIControls(bpy.types.PropertyGroup):
    # The main UI tabs (in the upper right corner of the liquifeel panel)
    # i.e. fill, shading, fx, etc...
    main_tabs: bpy.props.EnumProperty(
        items=main_tab_items,
        default='geometry')
    # The shading tabs (recipient vs liquid) they only appear when a lqfl filled object is selected.
    shading_target: bpy.props.EnumProperty(
        name='Shading for',
        items=shading_target_items)
    # The shading tabs (recipient vs liquid) they only appear when a lqfl filled object is selected.
    material_library: bpy.props.EnumProperty(
        name='Library',
        items=material_library_items)
    recipient_asset: bpy.props.EnumProperty(
        name='Fill Material',
        # No update function needed in this case, it's functionality has shifted to the operator:
        # AddAssetTo3DCursor
        # update=append_recipient_asset,
        items=recipient_asset_items)
    # Assembly: drag bottle + parts from Outliner into these fields.
    assembly_bottle: bpy.props.PointerProperty(
        name='Bottle',
        type=bpy.types.Object,
        description='Bottle mesh — drag from Outliner or use eyedropper',
        update=assembly_bottle_pointer_update)
    assembly_parts: bpy.props.CollectionProperty(type=LQFL_AssemblyPartItem)
    assembly_parts_index: bpy.props.IntProperty(default=0)
    assembly_hide_extras: bpy.props.BoolProperty(
        name='Hide Extras',
        description='Hide cork / label / extras in the viewport (bottle stays visible)',
        default=False,
        update=assembly_hide_extras_update)
    # # KEEP
    # performance_render_mode: bpy.props.BoolProperty(
    #     name='Performance Render Mode',
    #     update=performance_render_mode_update,
    #     default=False)
registerable_classes.append(GeneralUIControls)

## Messages and data
class MiscData(bpy.types.PropertyGroup):
    # Popup message
    info_popup_message: bpy.props.StringProperty(
        name='info_popup_message', default='info popup')
registerable_classes.append(MiscData)

## HARD-CODED ATTEMPT ----------------------------------------------------------------------

## UPDATE FUNCTIONS ----------------------------

@undo_push(2)
def hrdc_slot_shading_material_update(slf, context):
    obj__ = resolve_liquifeel_source_object(context.active_object)
    library_key = getattr(slf, 'library')
    material_name = getattr(slf, f'{library_key}_material')
    hrdc_slot_shade(context, obj__, library_key, material_name)

@undo_push(2)
def hrdc_fill_shading_material_update(slf, context):
    obj__ = resolve_liquifeel_source_object(context.active_object)
    if obj__ is None or not is_obj_filled(obj__):
        return
    library_key = getattr(slf, 'library')
    material_name = getattr(slf, f'{library_key}_material')
    hrdc_fill_shade(context, obj__, library_key, material_name)

@undo_push(2)
def hrdc_scene_slot_shading_material_update(slf, context):
    obj__ = resolve_liquifeel_source_object(context.active_object)
    material_name = getattr(slf, 'scene_material')
    hrdc_slot_shade(context, obj__, 'scene', material_name)

@undo_push(2)
def hrdc_scene_fill_shading_material_update(slf, context):
    obj__ = resolve_liquifeel_source_object(context.active_object)
    if obj__ is None or not is_obj_filled(obj__):
        return
    material_name = getattr(slf, 'scene_material')
    hrdc_fill_shade(context, obj__, 'scene', material_name)

## HIERARCHY -----------------------------------

# @undo_push(2)
# def hrdc__liquid_amount_updt(slf, context):
#     set_input__at_prop_update(
#         slf,
#         context,
#         'Liquid Amount',
#         'geometry',
#         'object_attached',
#         'None')

# @undo_push(2)
# def hrdc__meniscus_type_updt(slf, context):
#     set_input__at_prop_update(
#         slf,
#         context,
#         'Meniscus Type',
#         'geometry',
#         'object_attached',
#         'None')

# @undo_push(2)
# def hrdc__seal_container_updt(slf, context):
#     set_input__at_prop_update(
#         slf,
#         context,
#         'Seal Container',
#         'geometry',
#         'object_attached',
#         'None')

# @undo_push(2)
# def hrdc__hide_recipient_updt(slf, context):
#     set_input__at_prop_update(
#         slf,
#         context,
#         'Hide Recipient',
#         'geometry',
#         'object_attached',
#         'None')

# @undo_push(2)
# def hrdc__lip_threshold_updt(slf, context):
#     set_input__at_prop_update(
#         slf,
#         context,
#         'Lip Threshold',
#         'geometry',
#         'object_attached',
#         'None')

# key_chain: ['hrdc_liquifeel_input_field_props', 'geometry']
# path: hrdc_liquifeel_input_field_props.geometry
class HRDC_ObjAttch_Geometry_InptPrps(bpy.types.PropertyGroup):
    opening_shape: bpy.props.EnumProperty(
        name='Opening Shape',
        update=opening_shape_mandef_update, # !!!
        default='straight',
        items=[
            ('straight', 'Straight', 'The mouth of the recipient has no kink.'),
            ('irregular', 'Irregular', 'The mouth of the recipient has a kink.')])
    hide_recipient: bpy.props.BoolProperty(
        name='Hide Recipient',
        update=hide_recipient_update, # !!! I think this is appropriate. TEST IT!
        default=False)
    hide_liquid: bpy.props.BoolProperty(
        name='Hide Liquid',
        update=hide_liquid_update, # !!! I think this is appropriate. TEST IT!
        default=False)
    separate_objects: bpy.props.BoolProperty(
        name='Separate Objects',
        description=(
            'When bottle and liquid are both visible, keep liquid as a '
            'separate object that stays in sync with LiquiFeel settings'),
        update=separate_objects_update,
        default=False)
    # Copied from synthetically generatd code (from the obsolete execd system)
    # liquid_amount: bpy.props.FloatProperty(
    #     name='Liquid Amount',
    #     update=hrdc__liquid_amount_updt,
    #     min=1.0,
    #     soft_min=1.0,
    #     max=100.0,
    #     soft_max=100.0,
    #     subtype='PERCENTAGE',
    #     precision=3,
    #     step=0.1,
    # )
    # meniscus_type: bpy.props.EnumProperty(
    #     name='Meniscus Type',
    #     update=hrdc__meniscus_type_updt,
    #     default=0,
    #     items=[
    #         ('Concave Meniscus', 'Concave Meniscus', 'Concave Meniscus'),
    #         ('Convex Meniscus', 'Convex Meniscus', 'Convex Meniscus')],
    # )
    # seal_container: bpy.props.BoolProperty(
    #     name='Seal Container',
    #     update=hrdc__seal_container_updt,
    # )
    # hide_recipient: bpy.props.BoolProperty(
    #     name='Hide Recipient',
    #     update=hrdc__hide_recipient_updt,
    # )
    # lip_threshold: bpy.props.FloatProperty(
    #     name='Lip Threshold',
    #     update=hrdc__lip_threshold_updt,
    #     min=0.0,
    #     soft_min=0.0,
    #     max=100.0,
    #     soft_max=100.0,
    #     subtype='NONE',
    #     precision=3,
    #     step=0.1,
    # )
registerable_classes.append(HRDC_ObjAttch_Geometry_InptPrps)

class ObjAttch_Liq_Slt_UberLiquid(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_UberLiquid)

class ObjAttch_Liq_Slt_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Beer)

class ObjAttch_Liq_Slt_Black_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Black_Beer)

class ObjAttch_Liq_Slt_Black_Tea(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Black_Tea)

class ObjAttch_Liq_Slt_Blue_Lagoon(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Blue_Lagoon)

class ObjAttch_Liq_Slt_Blueberry_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Blueberry_Juice)

class ObjAttch_Liq_Slt_Cappuccino(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Cappuccino)

class ObjAttch_Liq_Slt_Champagne(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Champagne)

class ObjAttch_Liq_Slt_Chocolate_Milk(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Chocolate_Milk)

class ObjAttch_Liq_Slt_Coffee(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Coffee)

class ObjAttch_Liq_Slt_Coke(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Coke)

class ObjAttch_Liq_Slt_Cranberry_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Cranberry_Juice)

class ObjAttch_Liq_Slt_Energy_Drink(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Energy_Drink)

class ObjAttch_Liq_Slt_Ginger_Ale(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Ginger_Ale)

class ObjAttch_Liq_Slt_Green_Apple_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Green_Apple_Juice)

class ObjAttch_Liq_Slt_Greenies_Smoothie(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Greenies_Smoothie)

class ObjAttch_Liq_Slt_Honey(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Honey)

class ObjAttch_Liq_Slt_Ice_Tea(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Ice_Tea)

class ObjAttch_Liq_Slt_Lemonade(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Lemonade)

class ObjAttch_Liq_Slt_Milk(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Milk)

class ObjAttch_Liq_Slt_Olive_Oil(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Olive_Oil)

class ObjAttch_Liq_Slt_Orange_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Orange_Juice)

class ObjAttch_Liq_Slt_Red_Fruit_Smoothie(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Red_Fruit_Smoothie)

class ObjAttch_Liq_Slt_Red_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Red_Wine)

class ObjAttch_Liq_Slt_Rose_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Rose_Wine)

class ObjAttch_Liq_Slt_Water(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Water)

class ObjAttch_Liq_Slt_Tomato_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Tomato_Juice)

class ObjAttch_Liq_Slt_Unfiltered_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Unfiltered_Beer)

class ObjAttch_Liq_Slt_Whiskey(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_Whiskey)

class ObjAttch_Liq_Slt_White_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Slt_White_Wine)

# handles Shader NG and Shader Node inputs as the geonode attached
# inputs are tunnelled without a proxy property
# key_chain: ['hrdc_liquifeel_input_field_props', 'shading', 'slot', 'liquids']
# path: hrdc_liquifeel_input_field_props.shading.slot.liquids
class HRDC_ObjAttch_Liq_Slt_Shd_InptPrps(bpy.types.PropertyGroup):
    # UberLiquid
    uber_liquid: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_UberLiquid)
    # Beer
    beer: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Beer)
    # Black Beer
    black_beer: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Black_Beer)
    # Black Tea
    black_tea: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Black_Tea)
    # Blue Lagoon
    blue_lagoon: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Blue_Lagoon)
    # Blueberry Juice
    blueberry_juice: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Blueberry_Juice)
    # Cappuccino
    cappuccino: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Cappuccino)
    # Champagne
    champagne: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Champagne)
    # Chocolate Milk
    chocolate_milk: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Chocolate_Milk)
    # Coffee
    coffee: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Coffee)
    # Coke
    coke: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Coke)
    # Cranberry Juice
    cranberry_juice: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Cranberry_Juice)
    # Energy Drink
    energy_drink: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Energy_Drink)
    # Ginger Ale
    ginger_ale: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Ginger_Ale)
    # Green Apple Juice
    green_apple_juice: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Green_Apple_Juice)
    # Greenies Smoothie
    greenies_smoothie: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Greenies_Smoothie)
    # Honey
    honey: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Honey)
    # Ice Tea
    ice_tea: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Ice_Tea)
    # Lemonade
    lemonade: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Lemonade)
    # Milk
    milk: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Milk)
    # Olive Oil
    olive_oil: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Olive_Oil)
    # Orange Juice
    orange_juice: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Orange_Juice)
    # Red Fruit Smoothie
    red_fruit_smoothie: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Red_Fruit_Smoothie)
    # Red Wine
    red_wine: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Red_Wine)
    # Rose Wine
    rose_wine: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Rose_Wine)
    # Water
    water: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Water)
    # Tomato Juice
    tomato_juice: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Tomato_Juice)
    # Unfiltered Beer
    unfiltered_beer: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Unfiltered_Beer)
    # Whiskey
    whiskey: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_Whiskey)
    # White Wine
    white_wine: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Slt_White_Wine)
registerable_classes.append(HRDC_ObjAttch_Liq_Slt_Shd_InptPrps)

class ObjAttch_Liq_Fll_UberLiquid(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_UberLiquid)

class ObjAttch_Liq_Fll_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Beer)

class ObjAttch_Liq_Fll_Black_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Black_Beer)

class ObjAttch_Liq_Fll_Black_Tea(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Black_Tea)

class ObjAttch_Liq_Fll_Blue_Lagoon(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Blue_Lagoon)

class ObjAttch_Liq_Fll_Blueberry_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Blueberry_Juice)

class ObjAttch_Liq_Fll_Cappuccino(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Cappuccino)

class ObjAttch_Liq_Fll_Champagne(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Champagne)

class ObjAttch_Liq_Fll_Chocolate_Milk(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Chocolate_Milk)

class ObjAttch_Liq_Fll_Coffee(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Coffee)

class ObjAttch_Liq_Fll_Coke(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Coke)

class ObjAttch_Liq_Fll_Cranberry_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Cranberry_Juice)

class ObjAttch_Liq_Fll_Energy_Drink(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Energy_Drink)

class ObjAttch_Liq_Fll_Ginger_Ale(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Ginger_Ale)

class ObjAttch_Liq_Fll_Green_Apple_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Green_Apple_Juice)

class ObjAttch_Liq_Fll_Greenies_Smoothie(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Greenies_Smoothie)

class ObjAttch_Liq_Fll_Honey(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Honey)

class ObjAttch_Liq_Fll_Ice_Tea(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Ice_Tea)

class ObjAttch_Liq_Fll_Lemonade(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Lemonade)

class ObjAttch_Liq_Fll_Milk(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Milk)

class ObjAttch_Liq_Fll_Olive_Oil(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Olive_Oil)

class ObjAttch_Liq_Fll_Orange_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Orange_Juice)

class ObjAttch_Liq_Fll_Red_Fruit_Smoothie(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Red_Fruit_Smoothie)

class ObjAttch_Liq_Fll_Red_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Red_Wine)

class ObjAttch_Liq_Fll_Rose_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Rose_Wine)

class ObjAttch_Liq_Fll_Water(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Water)

class ObjAttch_Liq_Fll_Tomato_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Tomato_Juice)

class ObjAttch_Liq_Fll_Unfiltered_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Unfiltered_Beer)

class ObjAttch_Liq_Fll_Whiskey(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_Whiskey)

class ObjAttch_Liq_Fll_White_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Liq_Fll_White_Wine)

# handles Shader NG and Shader Node inputs as the geonode attached
# inputs are tunnelled without a proxy property
# key_chain: ['hrdc_liquifeel_input_field_props', 'shading', 'fill', 'liquids']
# path: hrdc_liquifeel_input_field_props.shading.fill.liquids
class HRDC_ObjAttch_Liq_Fll_Shd_InptPrps(bpy.types.PropertyGroup):
    # UberLiquid
    uber_liquid: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_UberLiquid)
    # Beer
    beer: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Beer)
    # Black Beer
    black_beer: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Black_Beer)
    # Black Tea
    black_tea: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Black_Tea)
    # Blue Lagoon
    blue_lagoon: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Blue_Lagoon)
    # Blueberry Juice
    blueberry_juice: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Blueberry_Juice)
    # Cappuccino
    cappuccino: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Cappuccino)
    # Champagne
    champagne: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Champagne)
    # Chocolate Milk
    chocolate_milk: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Chocolate_Milk)
    # Coffee
    coffee: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Coffee)
    # Coke
    coke: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Coke)
    # Cranberry Juice
    cranberry_juice: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Cranberry_Juice)
    # Energy Drink
    energy_drink: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Energy_Drink)
    # Ginger Ale
    ginger_ale: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Ginger_Ale)
    # Green Apple Juice
    green_apple_juice: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Green_Apple_Juice)
    # Greenies Smoothie
    greenies_smoothie: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Greenies_Smoothie)
    # Honey
    honey: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Honey)
    # Ice Tea
    ice_tea: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Ice_Tea)
    # Lemonade
    lemonade: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Lemonade)
    # Milk
    milk: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Milk)
    # Olive Oil
    olive_oil: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Olive_Oil)
    # Orange Juice
    orange_juice: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Orange_Juice)
    # Red Fruit Smoothie
    red_fruit_smoothie: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Red_Fruit_Smoothie)
    # Red Wine
    red_wine: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Red_Wine)
    # Rose Wine
    rose_wine: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Rose_Wine)
    # Water
    water: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Water)
    # Tomato Juice
    tomato_juice: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Tomato_Juice)
    # Unfiltered Beer
    unfiltered_beer: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Unfiltered_Beer)
    # Whiskey
    whiskey: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_Whiskey)
    # White Wine
    white_wine: bpy.props.PointerProperty(
        type=ObjAttch_Liq_Fll_White_Wine)
registerable_classes.append(HRDC_ObjAttch_Liq_Fll_Shd_InptPrps)

# !!! I was in the process of customizing this structure. All of the
# !!! properties are just copy-pasted, they all need to be customized
# !!! (especially the update functions)
class ObjAttch_Sld_Slt_Uber_Glass(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Sld_Slt_Uber_Glass)

class ObjAttch_Sld_Slt_Green_Bottle_Glass(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Sld_Slt_Green_Bottle_Glass)

class ObjAttch_Sld_Slt_Brown_Bottle_Glass(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Sld_Slt_Brown_Bottle_Glass)

class ObjAttch_Sld_Slt_Pet(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Sld_Slt_Pet)

# handles Shader NG and Shader Node inputs as the geonode attached
# inputs are tunnelled without a proxy property
# key_chain: ['hrdc_liquifeel_input_field_props', 'shading', 'slot', 'solids']
# path: hrdc_liquifeel_input_field_props.shading.slot.solids
class HRDC_ObjAttch_Sld_Slt_Shd_InptPrps(bpy.types.PropertyGroup):
    # Uber Glass
    uber_glass: bpy.props.PointerProperty(
        type=ObjAttch_Sld_Slt_Uber_Glass)
    # Green Bottle Glass
    green_bottle_glass: bpy.props.PointerProperty(
        type=ObjAttch_Sld_Slt_Green_Bottle_Glass)
    # Brown Bottle Glass
    brown_bottle_glass: bpy.props.PointerProperty(
        type=ObjAttch_Sld_Slt_Brown_Bottle_Glass)
    # PET
    pet: bpy.props.PointerProperty(
        type=ObjAttch_Sld_Slt_Pet)
registerable_classes.append(HRDC_ObjAttch_Sld_Slt_Shd_InptPrps)

class ObjAttch_Sld_Fll_Uber_Glass(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Sld_Fll_Uber_Glass)

class ObjAttch_Sld_Fll_Green_Bottle_Glass(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Sld_Fll_Green_Bottle_Glass)

class ObjAttch_Sld_Fll_Brown_Bottle_Glass(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Sld_Fll_Brown_Bottle_Glass)

class ObjAttch_Sld_Fll_Pet(bpy.types.PropertyGroup):
    pass
registerable_classes.append(ObjAttch_Sld_Fll_Pet)

# handles Shader NG and Shader Node inputs as the geonode attached
# inputs are tunnelled without a proxy property
# key_chain: ['hrdc_liquifeel_input_field_props', 'shading', 'fill', 'solids']
# path: hrdc_liquifeel_input_field_props.shading.fill.solids
class HRDC_ObjAttch_Sld_Fll_Shd_InptPrps(bpy.types.PropertyGroup):
    # Uber Glass
    uber_glass: bpy.props.PointerProperty(
        type=ObjAttch_Sld_Fll_Uber_Glass)
    # Green Bottle Glass
    green_bottle_glass: bpy.props.PointerProperty(
        type=ObjAttch_Sld_Fll_Green_Bottle_Glass)
    # Brown Bottle Glass
    brown_bottle_glass: bpy.props.PointerProperty(
        type=ObjAttch_Sld_Fll_Brown_Bottle_Glass)
    # PET
    pet: bpy.props.PointerProperty(
        type=ObjAttch_Sld_Fll_Pet)
registerable_classes.append(HRDC_ObjAttch_Sld_Fll_Shd_InptPrps)

# key_chain: ['hrdc_liquifeel_input_field_props', 'shading', 'slot']
# path: hrdc_liquifeel_input_field_props.slot.shading
class HRDC_ObjAttch_Slt_Shd_InptPrps(bpy.types.PropertyGroup):
    liquids: bpy.props.PointerProperty(type=HRDC_ObjAttch_Liq_Slt_Shd_InptPrps)
    solids: bpy.props.PointerProperty(type=HRDC_ObjAttch_Sld_Slt_Shd_InptPrps)
    library: bpy.props.EnumProperty(
        name='Library',
        default='solids',
        items=material_library_items)
    liquids_material: bpy.props.EnumProperty(
        name='Slot Material',
        update=hrdc_slot_shading_material_update,
        default='Water',
        items=liquids_shader_items)
    solids_material: bpy.props.EnumProperty(
        name='Slot Material',
        update=hrdc_slot_shading_material_update,
        items=solids_shader_items)
    scene_material: bpy.props.EnumProperty(
        name='Slot Material',
        update=hrdc_scene_slot_shading_material_update,
        items=scene_shader_items)
registerable_classes.append(HRDC_ObjAttch_Slt_Shd_InptPrps)

# key_chain: ['hrdc_liquifeel_input_field_props', 'shading', 'fill']
# path: hrdc_liquifeel_input_field_props.shading.fill
class HRDC_ObjAttch_Fll_Shd_InptPrps(bpy.types.PropertyGroup):
    liquids: bpy.props.PointerProperty(type=HRDC_ObjAttch_Liq_Fll_Shd_InptPrps)
    solids: bpy.props.PointerProperty(type=HRDC_ObjAttch_Sld_Fll_Shd_InptPrps)
    library: bpy.props.EnumProperty(
        name='Library',
        default='liquids',
        items=material_library_items)
    liquids_material: bpy.props.EnumProperty(
        name='Fill Material',
        update=hrdc_fill_shading_material_update,
        default='Water',
        items=liquids_shader_items)
    solids_material: bpy.props.EnumProperty(
        name='Fill Material',
        update=hrdc_fill_shading_material_update,
        items=solids_shader_items)
    scene_material: bpy.props.EnumProperty(
        name='Fill Material',
        update=hrdc_scene_fill_shading_material_update,
        items=scene_shader_items)
registerable_classes.append(HRDC_ObjAttch_Fll_Shd_InptPrps)

# key_chain: ['hrdc_liquifeel_input_field_props', 'shading']
# path: hrdc_liquifeel_input_field_props.shading
class HRDC_ObjAttch_Dual_Shd_InptPrps(bpy.types.PropertyGroup):
    slot: bpy.props.PointerProperty(type=HRDC_ObjAttch_Slt_Shd_InptPrps)
    fill: bpy.props.PointerProperty(type=HRDC_ObjAttch_Fll_Shd_InptPrps)
registerable_classes.append(HRDC_ObjAttch_Dual_Shd_InptPrps)

# key_chain: ['hrdc_liquifeel_input_field_props']
# path: hrdc_liquifeel_input_field_props
class HRDC_ObjAttch_InptPrps(bpy.types.PropertyGroup):
    geometry: bpy.props.PointerProperty(type=HRDC_ObjAttch_Geometry_InptPrps)
    shading: bpy.props.PointerProperty(type=HRDC_ObjAttch_Dual_Shd_InptPrps)
registerable_classes.append(HRDC_ObjAttch_InptPrps)

class MatAttch_Liq_Slt_UberLiquid(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_UberLiquid)

class MatAttch_Liq_Slt_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Beer)

class MatAttch_Liq_Slt_Black_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Black_Beer)

class MatAttch_Liq_Slt_Black_Tea(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Black_Tea)

class MatAttch_Liq_Slt_Blue_Lagoon(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Blue_Lagoon)

class MatAttch_Liq_Slt_Blueberry_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Blueberry_Juice)

class MatAttch_Liq_Slt_Cappuccino(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Cappuccino)

class MatAttch_Liq_Slt_Champagne(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Champagne)

class MatAttch_Liq_Slt_Chocolate_Milk(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Chocolate_Milk)

class MatAttch_Liq_Slt_Coffee(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Coffee)

class MatAttch_Liq_Slt_Coke(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Coke)

class MatAttch_Liq_Slt_Cranberry_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Cranberry_Juice)

class MatAttch_Liq_Slt_Energy_Drink(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Energy_Drink)

class MatAttch_Liq_Slt_Ginger_Ale(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Ginger_Ale)

class MatAttch_Liq_Slt_Green_Apple_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Green_Apple_Juice)

class MatAttch_Liq_Slt_Greenies_Smoothie(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Greenies_Smoothie)

class MatAttch_Liq_Slt_Honey(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Honey)

class MatAttch_Liq_Slt_Ice_Tea(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Ice_Tea)

class MatAttch_Liq_Slt_Lemonade(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Lemonade)

class MatAttch_Liq_Slt_Milk(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Milk)

class MatAttch_Liq_Slt_Olive_Oil(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Olive_Oil)

class MatAttch_Liq_Slt_Orange_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Orange_Juice)

class MatAttch_Liq_Slt_Red_Fruit_Smoothie(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Red_Fruit_Smoothie)

class MatAttch_Liq_Slt_Red_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Red_Wine)

class MatAttch_Liq_Slt_Rose_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Rose_Wine)

class MatAttch_Liq_Slt_Water(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Water)

class MatAttch_Liq_Slt_Tomato_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Tomato_Juice)

class MatAttch_Liq_Slt_Unfiltered_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Unfiltered_Beer)

class MatAttch_Liq_Slt_Whiskey(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_Whiskey)

class MatAttch_Liq_Slt_White_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Slt_White_Wine)

# handles Shader NG and Shader Node inputs as the geonode attached
# inputs are tunnelled without a proxy property
# key_chain: ['hrdc_liquifeel_input_field_props', 'slot', 'liquids']
# path: hrdc_liquifeel_input_field_props.slot.liquids
class HRDC_MatAttch_Liq_Slt_Shd_InptPrps(bpy.types.PropertyGroup):
    # UberLiquid
    uber_liquid: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_UberLiquid)
    # Beer
    beer: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Beer)
    # Black Beer
    black_beer: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Black_Beer)
    # Black Tea
    black_tea: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Black_Tea)
    # Blue Lagoon
    blue_lagoon: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Blue_Lagoon)
    # Blueberry Juice
    blueberry_juice: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Blueberry_Juice)
    # Cappuccino
    cappuccino: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Cappuccino)
    # Champagne
    champagne: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Champagne)
    # Chocolate Milk
    chocolate_milk: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Chocolate_Milk)
    # Coffee
    coffee: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Coffee)
    # Coke
    coke: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Coke)
    # Cranberry Juice
    cranberry_juice: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Cranberry_Juice)
    # Energy Drink
    energy_drink: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Energy_Drink)
    # Ginger Ale
    ginger_ale: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Ginger_Ale)
    # Green Apple Juice
    green_apple_juice: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Green_Apple_Juice)
    # Greenies Smoothie
    greenies_smoothie: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Greenies_Smoothie)
    # Honey
    honey: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Honey)
    # Ice Tea
    ice_tea: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Ice_Tea)
    # Lemonade
    lemonade: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Lemonade)
    # Milk
    milk: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Milk)
    # Olive Oil
    olive_oil: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Olive_Oil)
    # Orange Juice
    orange_juice: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Orange_Juice)
    # Red Fruit Smoothie
    red_fruit_smoothie: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Red_Fruit_Smoothie)
    # Red Wine
    red_wine: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Red_Wine)
    # Rose Wine
    rose_wine: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Rose_Wine)
    # Tomato Juice
    tomato_juice: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Tomato_Juice)
    # Unfiltered Beer
    unfiltered_beer: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Unfiltered_Beer)
    # Water
    water: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Water)
    # Whiskey
    whiskey: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_Whiskey)
    # White Wine
    white_wine: bpy.props.PointerProperty(
        type=MatAttch_Liq_Slt_White_Wine)
registerable_classes.append(HRDC_MatAttch_Liq_Slt_Shd_InptPrps)

class MatAttch_Liq_Fll_UberLiquid(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_UberLiquid)

class MatAttch_Liq_Fll_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Beer)

class MatAttch_Liq_Fll_Black_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Black_Beer)

class MatAttch_Liq_Fll_Black_Tea(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Black_Tea)

class MatAttch_Liq_Fll_Blue_Lagoon(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Blue_Lagoon)

class MatAttch_Liq_Fll_Blueberry_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Blueberry_Juice)

class MatAttch_Liq_Fll_Cappuccino(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Cappuccino)

class MatAttch_Liq_Fll_Champagne(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Champagne)

class MatAttch_Liq_Fll_Chocolate_Milk(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Chocolate_Milk)

class MatAttch_Liq_Fll_Coffee(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Coffee)

class MatAttch_Liq_Fll_Coke(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Coke)

class MatAttch_Liq_Fll_Cranberry_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Cranberry_Juice)

class MatAttch_Liq_Fll_Energy_Drink(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Energy_Drink)

class MatAttch_Liq_Fll_Ginger_Ale(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Ginger_Ale)

class MatAttch_Liq_Fll_Green_Apple_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Green_Apple_Juice)

class MatAttch_Liq_Fll_Greenies_Smoothie(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Greenies_Smoothie)

class MatAttch_Liq_Fll_Honey(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Honey)

class MatAttch_Liq_Fll_Ice_Tea(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Ice_Tea)

class MatAttch_Liq_Fll_Lemonade(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Lemonade)

class MatAttch_Liq_Fll_Milk(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Milk)

class MatAttch_Liq_Fll_Olive_Oil(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Olive_Oil)

class MatAttch_Liq_Fll_Orange_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Orange_Juice)

class MatAttch_Liq_Fll_Red_Fruit_Smoothie(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Red_Fruit_Smoothie)

class MatAttch_Liq_Fll_Red_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Red_Wine)

class MatAttch_Liq_Fll_Rose_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Rose_Wine)

class MatAttch_Liq_Fll_Water(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Water)

class MatAttch_Liq_Fll_Tomato_Juice(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Tomato_Juice)

class MatAttch_Liq_Fll_Unfiltered_Beer(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Unfiltered_Beer)

class MatAttch_Liq_Fll_Whiskey(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_Whiskey)

class MatAttch_Liq_Fll_White_Wine(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Liq_Fll_White_Wine)

# handles Shader NG and Shader Node inputs as the geonode attached
# inputs are tunnelled without a proxy property
# key_chain: ['hrdc_liquifeel_input_field_props', 'fill', 'liquids']
# path: hrdc_liquifeel_input_field_props.fill.liquids
class HRDC_MatAttch_Liq_Fll_Shd_InptPrps(bpy.types.PropertyGroup):
    # UberLiquid
    uber_liquid: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_UberLiquid)
    # Beer
    beer: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Beer)
    # Black Beer
    black_beer: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Black_Beer)
    # Black Tea
    black_tea: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Black_Tea)
    # Blue Lagoon
    blue_lagoon: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Blue_Lagoon)
    # Blueberry Juice
    blueberry_juice: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Blueberry_Juice)
    # Cappuccino
    cappuccino: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Cappuccino)
    # Champagne
    champagne: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Champagne)
    # Chocolate Milk
    chocolate_milk: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Chocolate_Milk)
    # Coffee
    coffee: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Coffee)
    # Coke
    coke: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Coke)
    # Cranberry Juice
    cranberry_juice: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Cranberry_Juice)
    # Energy Drink
    energy_drink: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Energy_Drink)
    # Ginger Ale
    ginger_ale: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Ginger_Ale)
    # Green Apple Juice
    green_apple_juice: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Green_Apple_Juice)
    # Greenies Smoothie
    greenies_smoothie: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Greenies_Smoothie)
    # Honey
    honey: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Honey)
    # Ice Tea
    ice_tea: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Ice_Tea)
    # Lemonade
    lemonade: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Lemonade)
    # Milk
    milk: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Milk)
    # Olive Oil
    olive_oil: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Olive_Oil)
    # Orange Juice
    orange_juice: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Orange_Juice)
    # Red Fruit Smoothie
    red_fruit_smoothie: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Red_Fruit_Smoothie)
    # Red Wine
    red_wine: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Red_Wine)
    # Rose Wine
    rose_wine: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Rose_Wine)
    # Tomato Juice
    tomato_juice: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Tomato_Juice)
    # Unfiltered Beer
    unfiltered_beer: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Unfiltered_Beer)
    # Water
    water: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Water)
    # Whiskey
    whiskey: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_Whiskey)
    # White Wine
    white_wine: bpy.props.PointerProperty(
        type=MatAttch_Liq_Fll_White_Wine)
registerable_classes.append(HRDC_MatAttch_Liq_Fll_Shd_InptPrps)

class MatAttch_Sld_Slt_Uber_Glass(bpy.types.PropertyGroup):
    # Pattern (Bump)
    pattern_texture: bpy.props.EnumProperty( # TEMPLATE ICON VIEW
        name='Pattern Texture',
        update=hrdc_pattern_texture_updt,
        items=gen_pattern_imgtex_img_items)
    user_pattern_texture: bpy.props.EnumProperty( # TEMPLATE ICON VIEW
        name='User Pattern Texture',
        update=hrdc_pattern_texture_updt,
        items=gen_pattern_user_imgtex_img_items)
    pattern_texture_resolution: bpy.props.EnumProperty( # DROP DOWN
        name='Pattern Texture Resolution',
        update=hrdc_pattern_texture_updt,
        items=gen_map_imgtex_res_items)
    pattern_library: bpy.props.EnumProperty( # DROP DOWN
        name='Pattern Library',
        default='liquifeel',
        update=hrdc_pattern_texture_updt,
        items=[
            ('liquifeel', 'Liquifeel', 'Patterns packaged with Liquifeel'),
            ('user_defined', 'User Defined', 'Patterns added by the user.'),
        ])
    # Obsoleted by the geonodes menu item called 'Mapping Type'
    # pattern_mapping: bpy.props.EnumProperty( # DROP DOWN
    #     name='Mapping',
    #     update=hrdc_mapping_patternutils_updt,
    #     default='Box',
    #     items=[
    #         ('Box', 'Box', 'Box(True)'),
    #         ('UV', 'UV', 'UV(False)'),
    #     ])
    pattern_uv_name: bpy.props.EnumProperty( # DROP DOWN
        name='UV Name',
        update=hrdc_uv_name_patternutils_geonode_mandef_updt,
        items=get_object_uv_maps_items_f())
    pattern_vertex_group: bpy.props.EnumProperty( # DROP DOWN
        name='Vertex Group',
        update=hrdc_vertex_group_patternutils_geonode_mandef_updt,
        items=get_object_vertex_groups_items_f())
    # Roughness
    roughness_texture: bpy.props.EnumProperty( # TEMPLATE ICON VIEW
        name='Roughness Texture',
        update=hrdc_roughness_texture_updt,
        items=gen_roughness_imgtex_img_items)
    user_roughness_texture: bpy.props.EnumProperty( # TEMPLATE ICON VIEW
        name='User Roughness Texture',
        update=hrdc_roughness_texture_updt,
        items=gen_roughness_user_imgtex_img_items)
    roughness_texture_resolution: bpy.props.EnumProperty( # DROP DOWN
        name='Roughness Texture Resolution',
        update=hrdc_roughness_texture_updt,
        items=gen_map_imgtex_res_items)
    roughness_library: bpy.props.EnumProperty( # DROP DOWN
        name='Roughness Library',
        default='liquifeel',
        update=hrdc_roughness_texture_updt,
        items=[
            ('liquifeel', 'Liquifeel', 'Roughness Maps packaged with Liquifeel'),
            ('user_defined', 'User Defined', 'Roughness Maps added by the user.'),
        ])
    # Obsoleted by the geonodes menu item called 'Mapping Type'
    # roughness_mapping: bpy.props.EnumProperty( # DROP DOWN
    #     name='Mapping',
    #     update=hrdc_mapping_roughnessutils_updt,
    #     default='Box',
    #     items=[
    #         ('Box', 'Box', 'Box(True)'),
    #         ('UV', 'UV', 'UV(False)'),
    #     ])
    roughness_uv_name: bpy.props.EnumProperty( # DROP DOWN
        name='UV Name',
        update=hrdc_uv_name_roughnessutils_geonode_mandef_updt,
        items=get_object_uv_maps_items_f())
    roughness_vertex_group: bpy.props.EnumProperty( # DROP DOWN
        name='Vertex Group',
        update=hrdc_vertex_group_roughnessutils_geonode_mandef_updt,
        items=get_object_vertex_groups_items_f())
registerable_classes.append(MatAttch_Sld_Slt_Uber_Glass)

class MatAttch_Sld_Slt_Green_Bottle_Glass(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Sld_Slt_Green_Bottle_Glass)

class MatAttch_Sld_Slt_Brown_Bottle_Glass(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Sld_Slt_Brown_Bottle_Glass)

class MatAttch_Sld_Slt_Pet(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Sld_Slt_Pet)

# key_chain: ['hrdc_liquifeel_input_field_props', 'slot', 'solids']
# path: hrdc_liquifeel_input_field_props.slot.solids
class HRDC_MatAttch_Sld_Slt_Shd_InptPrps(bpy.types.PropertyGroup):
    # Uber Glass
    uber_glass: bpy.props.PointerProperty(
        type=MatAttch_Sld_Slt_Uber_Glass)
    # Green Bottle Glass
    green_bottle_glass: bpy.props.PointerProperty(
        type=MatAttch_Sld_Slt_Green_Bottle_Glass)
    # Brown Bottle Glass
    brown_bottle_glass: bpy.props.PointerProperty(
        type=MatAttch_Sld_Slt_Brown_Bottle_Glass)
    # PET
    pet: bpy.props.PointerProperty(
        type=MatAttch_Sld_Slt_Pet)
registerable_classes.append(HRDC_MatAttch_Sld_Slt_Shd_InptPrps)

class MatAttch_Sld_Fll_Uber_Glass(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Sld_Fll_Uber_Glass)

class MatAttch_Sld_Fll_Green_Bottle_Glass(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Sld_Fll_Green_Bottle_Glass)

class MatAttch_Sld_Fll_Brown_Bottle_Glass(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Sld_Fll_Brown_Bottle_Glass)

class MatAttch_Sld_Fll_Pet(bpy.types.PropertyGroup):
    pass
registerable_classes.append(MatAttch_Sld_Fll_Pet)

# key_chain: ['hrdc_liquifeel_input_field_props', 'fill', 'solids']
# path: hrdc_liquifeel_input_field_props.fill.solids
class HRDC_MatAttch_Sld_Fll_Shd_InptPrps(bpy.types.PropertyGroup):
    # Uber Glass
    uber_glass: bpy.props.PointerProperty(
        type=MatAttch_Sld_Fll_Uber_Glass)
    # Green Bottle Glass
    green_bottle_glass: bpy.props.PointerProperty(
        type=MatAttch_Sld_Fll_Green_Bottle_Glass)
    # Brown Bottle Glass
    brown_bottle_glass: bpy.props.PointerProperty(
        type=MatAttch_Sld_Fll_Brown_Bottle_Glass)
    # PET
    pet: bpy.props.PointerProperty(
        type=MatAttch_Sld_Fll_Pet)
registerable_classes.append(HRDC_MatAttch_Sld_Fll_Shd_InptPrps)

# key_chain: ['hrdc_liquifeel_input_field_props', 'slot']
# path: hrdc_liquifeel_input_field_props.slot
class HRDC_MatAttch_Slt_Shd_InptPrps(bpy.types.PropertyGroup):
    liquids: bpy.props.PointerProperty(type=HRDC_MatAttch_Liq_Slt_Shd_InptPrps) # HRDC_MatAttch_Liq_Shd_InptPrps
    solids: bpy.props.PointerProperty(type=HRDC_MatAttch_Sld_Slt_Shd_InptPrps) # HRDC_MatAttch_Sld_Shd_InptPrps
registerable_classes.append(HRDC_MatAttch_Slt_Shd_InptPrps)

# key_chain: ['hrdc_liquifeel_input_field_props', 'fill']
# path: hrdc_liquifeel_input_field_props.slot
class HRDC_MatAttch_Fll_Shd_InptPrps(bpy.types.PropertyGroup):
    liquids: bpy.props.PointerProperty(type=HRDC_MatAttch_Liq_Fll_Shd_InptPrps)
    solids: bpy.props.PointerProperty(type=HRDC_MatAttch_Sld_Fll_Shd_InptPrps)
registerable_classes.append(HRDC_MatAttch_Fll_Shd_InptPrps)

# key_chain: ['hrdc_liquifeel_input_field_props']
# path: hrdc_liquifeel_input_field_props
class HRDC_MatAttch_InptPrps(bpy.types.PropertyGroup):
    slot: bpy.props.PointerProperty(type=HRDC_MatAttch_Slt_Shd_InptPrps)
    fill: bpy.props.PointerProperty(type=HRDC_MatAttch_Fll_Shd_InptPrps)
registerable_classes.append(HRDC_MatAttch_InptPrps)


## DISPLAY --------------------------------------------------------------------------------

def info_popup(context, message):
    setattr(context.scene.liquifeel_misc_data, 'info_popup_message', message)
    if bpy.app.background:
        # calling a popup menu without a UI crashes Blender
        print(f'LIQUIFEEL: {message}')
    else:
        bpy.ops.wm.call_menu(name='OBJECT_MT_info_popup')

## APPEND ---------------------------------------------------------------------------------------

def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def levenshtein_sorting_crit_f(name_substring):
    def sorting_key(target_string):
        return levenshtein_distance(name_substring, target_string)
    return sorting_key

# data_category is the attribute to data_from ('objects',
# 'node_groups', etc...)
def get_append_name(data_from, data_category_key, name_substring):
    return sorted(
        [obj_name for obj_name in getattr(
            data_from, data_category_key) if name_substring in obj_name],
        key=levenshtein_sorting_crit_f(name_substring)
    )[0]

def append_data(posix_filepath, category_key, name_substring):
    with bpy.data.libraries.load(str(posix_filepath)) as (data_from, data_to):
        dat_name = get_append_name(data_from, category_key, name_substring)
        setattr(data_to, category_key, [dat_name])
    dat = getattr(data_to, category_key)[0]
    return dat

def append_recipient_asset__(context, parenting_data):
    obj_name = parenting_data['name']
    # print(f'append_recipient_asset__(): obj_name: {obj_name}')
    asset_key = key_from_name(obj_name)
    glass_asset_append_fpath = FPATHS['blend_assets']
    obj__ = append_data(str(glass_asset_append_fpath), 'objects', obj_name)
    # with bpy.data.libraries.load(str(
    #         glass_asset_append_fpath)) as (data_from, data_to):
    #     print(obj_name)
    #     data_to.objects = [obj_name]
    # obj__ = data_to.objects[0]
    context.collection.objects.link(obj__)
    obj__.location = mathutils.Vector((0, 0, 0))
    obj__.name = obj_name
    if parenting_data['children']:
        children_objss = list(
            map(lambda child_data: append_recipient_asset__(context, child_data),
                parenting_data['children']))
        for child_obj, nephew_objss in children_objss:
            child_obj.parent = obj__
    else:
        children_objss = []
    return obj__, children_objss

def append_geonode_group(node_group_name, posix_filepath):
    return append_data(posix_filepath, 'node_groups', node_group_name)

# def append_geonode_group(node_group_name, posix_filepath):
#     with bpy.data.libraries.load(str(posix_filepath)) as (data_from, data_to):
#         data_to.node_groups = [node_group_name]
#     ng = data_to.node_groups[0]
#     return ng

# Fill NGs that must expose Wall Overlap / Subdivision. An older copy already
# in bpy.data (same addon version marker) would otherwise be reused by
# maybe_append and break assign_fill_default_vals with KeyError.
FILL_NG_REQUIRED_INPUTS = ('Wall Overlap', 'Subdivision')
FILL_NG_REFRESH_TARGETS = (
    (FILL_NG_NAME, FILL_NG_REQUIRED_INPUTS),
    ('LiquiFeelv1.3_Group', FILL_NG_REQUIRED_INPUTS),
)

def geonode_group_input_names(ng):
    names = set()
    for it in ng.interface.items_tree:
        if (getattr(it, 'item_type', None) == 'SOCKET'
                and getattr(it, 'in_out', None) == 'INPUT'):
            names.add(it.name)
    return names

def geonode_group_is_missing_inputs(ng, required_names):
    have = geonode_group_input_names(ng)
    return any(name not in have for name in required_names)

def _unique_node_group_name(base_name):
    if base_name not in bpy.data.node_groups:
        return base_name
    i = 1
    while True:
        candidate = f'{base_name}.{i:03d}'
        if candidate not in bpy.data.node_groups:
            return candidate
        i += 1

def retire_stale_fill_node_groups():
    # If either the main fill tree or its subgroup lacks the sockets this build
    # expects, retire BOTH so a fresh append remaps nested Group references.
    stale = False
    for ng_name, required in FILL_NG_REFRESH_TARGETS:
        ng = bpy.data.node_groups.get(ng_name)
        if ng is not None and geonode_group_is_missing_inputs(ng, required):
            stale = True
            break
    if not stale:
        return
    for ng_name, _required in FILL_NG_REFRESH_TARGETS:
        ng = bpy.data.node_groups.get(ng_name)
        if ng is not None:
            ng.name = _unique_node_group_name(ng_name + '__legacy')

def maybe_append_geonode_group(node_group_name, filepath):
    if node_group_name == FILL_NG_NAME:
        retire_stale_fill_node_groups()
    if node_group_name in bpy.data.node_groups.keys():
        ng__ = bpy.data.node_groups[node_group_name]
        if not is_asset_legacy_configured(ng__):
            return ng__
        ng__.name = _unique_node_group_name(ng__.name + '__legacy')
    return append_geonode_group(node_group_name, filepath)
# def maybe_append_geonode_group(node_group_name, filepath):
#     if node_group_name in bpy.data.node_groups.keys():
#         return bpy.data.node_groups[node_group_name]
#     else:
#         return append_geonode_group(node_group_name, filepath)

def append_material(material_name, posix_filepath):
    return append_data(posix_filepath, 'materials', material_name)

def maybe_append_material(material_name, filepath):
    if material_name in bpy.data.materials.keys():
        mat__ = bpy.data.materials[material_name]
        if not is_asset_legacy_configured(mat__):
            return mat__
        else:
            mat__.name += '__legacy'
    return append_material(material_name, filepath)
# def maybe_append_material(material_name, filepath):
#     if material_name in bpy.data.materials.keys():
#         return bpy.data.materials[material_name]
#     else:
#         return append_material(material_name, filepath)


## FUNCTIONALITY --------------------------------------------------------------------------------

## MODIFIERS ----------------------------

# I think that the cycles glitch where some materials appear blank
# till cycles is reloaded could be resolved by strategically deploying
# this function. !!!
def modifier_viewport_update_trigger(context, mod):
    mod.node_group.interface_update(context)

## RANKING / SORTING ---------

modifier_ranking = [
    {
        'type': 'non-lqfl',
        'discriminator': lambda mod: not(is_lqfl_modifier(mod))},
    {
        'type': 'select_outer',
        'discriminator': is_mod_select_outer},
    {
        'type': 'main_fill',
        'discriminator': is_mod_main_fill},
    {
        'type': 'lqfl-slot',
        'discriminator': modifier_slot_vs_shade_discriminator_f('slot')},
    {
        'type': 'lqfl-fill',
        'discriminator': modifier_slot_vs_shade_discriminator_f('fill')},
]

## ASSIGNING ---------

def load_node_group(ng_name, data_to_attach_as_id_prop):
    ng = maybe_append_geonode_group(
        ng_name,
        FPATHS['blend_assets'])
    ng['liquifeel'] = data_to_attach_as_id_prop
    return ng

def remove_mods(obj__, discriminator):
    # print()
    # print(f'remove_mods(obj__, discriminator):')
    # print('obj__.modifiers', obj__.modifiers)
    satisfactory_mods = [mod for mod in obj__.modifiers if discriminator(mod)]
    # print('satisfactory_mods: ', satisfactory_mods)
    if satisfactory_mods:
        for mod in satisfactory_mods:
            obj__.modifiers.remove(mod)

def remove_geonode_mods_by_ng_name(obj__, ng_name):
    discriminator = lambda mod: (
        mod.type == 'NODES' and mod.node_group and mod.node_group.name == ng_name)
    remove_mods(obj__, discriminator)

def move_mod_in_stack(obj__, mod_name, i):
    obj__.modifiers.move(
        obj__.modifiers.find(mod_name), i)

def assign_liquifeel_modifier(obj__, ng_name, remove_discriminator, get_pos_from_obj):
    remove_mods(obj__, remove_discriminator) # Remove any preexisting homologous mods
    # Also remove stale mods in our namespace (e.g. with a dangling node group
    # after their group was deleted) - they are invisible to the discriminator
    # and would steal the ng_name from the fresh modifier, breaking every
    # by-name lookup afterwards.
    remove_mods(obj__, lambda mod: mod.type == 'NODES' and (
        mod.name == ng_name
        or mod.name.startswith(ng_name + '.')
        or (mod.node_group is None and ng_name in mod.name)))
    # assign the new mod
    ng = load_node_group(
        ng_name,
        {'version': bl_info['version'],
         'feature': 'fill',
         'main_tab': ['fill', 'shading']})
    if ng is None:
        raise RuntimeError(
            f"LiquiFeel: could not append node group '{ng_name}' from the "
            "addon assets. Reinstall the addon or check the data folder.")
    mod = obj__.modifiers.new(
        name=ng_name, type='NODES')
    mod.node_group = ng
    # place it to it's appropriate position in the mod stack
    move_mod_in_stack(obj__, mod.name, get_pos_from_obj(obj__))
    return mod

# Returns the first index after the non-lqfl modifiers. the lqfl modifiers should be placed after the
# original model's modifiers.
def get_first_lqfl_mod_index(obj__):
    return len([mod for mod in obj__.modifiers if not(is_lqfl_modifier(mod))])

def assign_select_outer_geonode_mod(obj__):
    mod = assign_liquifeel_modifier(
        obj__, SELECT_OUTER_NG_NAME, is_mod_select_outer, get_first_lqfl_mod_index)
    return mod

def get_fill_mod_pos_index(obj__):
    return get_first_lqfl_mod_index(obj__) + 1

def get_hide_recipient_mod_pos_index(obj__):
    last_index = get_last_mod_index(obj__)
    if has_obj_condensation(obj__):
        return last_index - 1
    else:
        return last_index

def get_condensation_mod_pos_index(obj__):
    return get_last_mod_index(obj__)

def assign_fill_geonode_mod(obj__):
    mod = assign_liquifeel_modifier(
        obj__, FILL_NG_NAME, is_mod_main_fill, get_fill_mod_pos_index)
    # Just to make sure it's not decoupled from the actual value, we set it.
    setattr(obj__.hrdc_liquifeel_input_field_props.geometry,
            'hide_liquid',
            not(mod.show_viewport))
    # setattr(obj__.liquifeel_input_field_props.geometry.manual,
    #         'hide_liquid',
    #         not(mod.show_viewport))
    return mod

def get_last_mod_index(obj__):
    return len(obj__.modifiers) - 1

def assign_hide_recipient_geonode_mod(obj__):
    mod = assign_liquifeel_modifier(
        obj__, HIDE_RECIPIENT_NG_NAME, has_geonode_mod_name_f(HIDE_RECIPIENT_NG_NAME),
        get_hide_recipient_mod_pos_index)
    return mod

def has_obj_condensation(obj__):
    return has_obj_geonode_mod_by_ng_name(obj__, CONDENSATION_NG_NAME)

def assign_condensation_geonode_mod(obj__):
    mod = assign_liquifeel_modifier(
        obj__, CONDENSATION_NG_NAME, has_geonode_mod_name_f(CONDENSATION_NG_NAME),
        get_condensation_mod_pos_index)
    return mod

## GEONODES ----------------------------

def get_geonodes_modifier__by_mod_name(obj__, mod_name):
    return obj__.modifiers[mod_name]

# get_geonodes_mod_by_ng_name(Sphere, FILL_NG_NAME)
def get_geonodes_mod_by_ng_name(obj__, ng_name):
    # print(f'get_geonodes_mod_by_ng_name({obj__}, {ng_name})')
    return next(filter(
        lambda mod: mod.type == 'NODES' and mod.node_group and mod.node_group.name == ng_name,
        obj__.modifiers))

def get_geonodes_field_identifier(mod, field_name):
    if mod.node_group is None:
        raise RuntimeError(
            f"LiquiFeel modifier '{mod.name}' lost its node group (broken fill "
            "state). Use 'Remove All LiquiFeel Data' in the panel, then fill again.")
    return index_stripped(
        mod.node_group.interface.items_tree,  # bpy.data.objects["American Pint Glass"].modifiers["PatternUtils"]["Input_4"]
        field_name
    ).identifier

def get_geonode_mod_input(obj__, ng_name, field_name):
    mod = get_geonodes_mod_by_ng_name(obj__, ng_name)
    identifier = get_geonodes_field_identifier(mod, field_name)
    return geonode_input_get(mod, identifier)

def set_geonode_color_input(mod, identifier, value):
    # print(f'set_geonode_color_input({mod.name}, {identifier}, {value})')
    for i in range(len(value)):
        geonode_input_set_component(mod, identifier, i, value[i])

json_decoded_value_parser = {
    'bool': {'True': True, 'False': False},
    'bool_to_float': {'true': 1.0, 'false': 0.0}
}

def remove_material_auxiliary_modifiers(obj__, prev_mat_library_key, prev_mat_name):
    # print(f'remove_material_auxiliary_modifiers(obj__:{obj__.name}, {prev_mat_library_key}, {prev_mat_name})')
    filter_f = is_modifier_shader_auxilliary_f(
        prev_mat_library_key, prev_mat_name)
    mods_to_remove = list(filter(filter_f, obj__.modifiers))
    for mod in mods_to_remove:
        obj__.modifiers.remove(mod)

def is_geonode_mod_present(obj__, ng_name):
    return ng_name in map(lambda mod: mod.node_group.name,
                          filter(lambda mod: mod.type == 'NODES' and mod.node_group,
                                 list(obj__.modifiers)))

def install_material_aux_mod(obj__, library_key, material_name, ng_name, shading_modality_key):
    if not(is_geonode_mod_present(obj__, ng_name)):
        node_group = load_node_group(
            ng_name,
            {'version': bl_info['version'],
             'slot_vs_fill': shading_modality_key,
             'main_tab': 'shading',
             'library': library_key,
             'material_name': material_name,})
        mod = obj__.modifiers.new(
            name=ng_name, type='NODES')
        mod.node_group = node_group
    else:
        mod = obj__.modifiers[ng_name]
    return mod

def maybe_install_material_auxiliary_modifiers(obj__, library_key, material_name, shading_modality_key):
    # print()
    # print('maybe_install_material_auxiliary_modifiers(obj__, library_key, material_name, shading_modality_key)')
    material_data = INPUT_FIELD_DATA['shading'][library_key][material_name]
    if 'GeoNode' in material_data.keys():
        for ng_name, geonode_mod_data in material_data['GeoNode'].items():
            mod = install_material_aux_mod(obj__, library_key, material_name, ng_name, shading_modality_key)
            # print('ng_name: ', ng_name)
        # reorder modifiers if neccessary
        if is_obj_filled(obj__):
            move_mod_in_stack(obj__, HIDE_RECIPIENT_NG_NAME, get_last_mod_index(obj__))

## MATERIALS ----------------------------

def is_shader_node_group(node):
    return type(node) == bpy.types.ShaderNodeGroup

def get_shader_ng_by_name(material, ng_name):
    # print()
    # print('material:', material)
    # print('material.name', material.name)
    # print('ng_name', ng_name)
    # print()
    return next(
        filter(lambda node: ng_name in node.node_tree.name,
               filter(lambda node: node.type == 'GROUP',
                      material.node_tree.nodes)))
# def get_shader_ng_by_name(material, ng_name):
#     # print()
#     # print('material:', material)
#     # print('material.name', material.name)
#     # print('ng_name', ng_name)
#     # print()
#     return next(
#         filter(lambda ng: ng_name in ng.node_tree.name,
#                filter(is_shader_node_group,
#                       material.node_tree.nodes)))
# # This is a function i developed sepparately, forgetting about the one
# # defined previously. Maybe we'll need it, i'll leave it here for now.
# def maybe_get_shader_ng_node_by_ng_name(mat, ng_name):
#     try:
#         return next(
#             filter(lambda node: node.node_tree.name == ng_name,
#                    filter(lambda node: node.type == 'GROUP',
#                           mat.node_tree.nodes)))
#     except:
#         return None

def get_shader_ng_input(ng, input_name):
    return ng.inputs[ng.inputs.find(input_name)]

def get_shader_ng_input_from_mat(mat, ng_name, input_name):
    ng = get_shader_ng_by_name(mat, ng_name)
    return get_shader_ng_input(ng, input_name)

def get_material_node(material, node_name):
    # print(f'get_material_node(material: {material}, node_name: {node_name}):')
    return next(
        filter(lambda node: any([f(node) == node_name for f in [lambda n: n.name, lambda n: n.label]]),
               material.node_tree.nodes))

def assign_image_to_nodes(obj__, nodes, img, img_tex_fpath):
    img.filepath = str(img_tex_fpath)
    img.filepath_raw = str(img_tex_fpath)
    img.colorspace_settings.name = 'Non-Color'
    for img_node in nodes:
        img_node.image = img

def set_asset_material(obj__, material, shading_modality_key):
    library_key, material_name = get_library_key_and_material_name(
        obj__, shading_modality_key=shading_modality_key)
    if shading_modality_key == 'slot':
        if obj__.data.materials:
            obj__.data.materials[0] = material
        else:
            obj__.data.materials.append(material)
        obj__['liquifeel']['slot_shading']['material_name'] = material.name
    elif shading_modality_key == 'fill':
        set_geonode_mod_input(
            obj__, FILL_NG_NAME, 'Liquid Shader', 'material', material)
        obj__['liquifeel']['fill_shading']['material_name'] = material.name

def hrdc_set_asset_material(obj__, material, shading_modality_key):
    library_key, material_name = hrdc_get_library_key_and_material_name(
        obj__, shading_modality_key=shading_modality_key)
    if shading_modality_key == 'slot':
        if obj__.data.materials:
            obj__.data.materials[0] = material
        else:
            obj__.data.materials.append(material)
        obj__['liquifeel']['slot_shading']['material_name'] = material.name
    elif shading_modality_key == 'fill':
        set_geonode_mod_input(
            obj__, FILL_NG_NAME, 'Liquid Shader', 'material', material)
        obj__['liquifeel']['fill_shading']['material_name'] = material.name

## GEOMETRY ----------------------------

def has_obj_single_mesh_island(obj__):
    return count_mesh_islands_cached(obj__) == 1

def assert_island_count_f(n):
    def assert_(context, obj__):
        island_c = count_mesh_islands(obj__)
        if island_c < n:
            info_popup(
                context, f'Active object has too few mesh islands.\nAmount should be {n}, but is {island_c}')
            return False
        elif island_c > n:
            info_popup(
                context, f'Active object has too many mesh islands.\nAmount should be {n}, but is {island_c}')
            return False
        else:
            return True
    return assert_

def add_condensation_to_active_object(context, obj__):
    assign_condensation_geonode_mod(obj__)
    if 'liquifeel' not in obj__.keys():
        obj__['liquifeel'] = {
            'version': bl_info['version']
        }
    obj__['liquifeel']['condensation'] = True
    set_geonode_mod_input(obj__, 'Condensation_V1.0', 'Condensation', 'bool', True)

def _object_world_size(obj__):
    """World-space AABB size (max axis), used to guess mesh length units."""
    try:
        corners = [obj__.matrix_world @ mathutils.Vector(c)
                   for c in obj__.bound_box]
        xs = [c.x for c in corners]
        ys = [c.y for c in corners]
        zs = [c.z for c in corners]
        return max(
            max(xs) - min(xs),
            max(ys) - min(ys),
            max(zs) - min(zs),
        )
    except Exception:
        return 0.0


def _mesh_mm_unit_factor(obj__):
    """Factor so that (1 * factor) ≈ 1mm in mesh Blender-units.

    Select Outer hardcodes Lip Threshold * 0.001 (1mm when mesh is in meters).
    CAD scenes often store mm or cm as Blender units — then that constant is
    wrong and lip/opening selection (and therefore liquid height range) breaks,
    which makes the Liquid Level % slider look like it 'works in another scale'.
    """
    size = _object_world_size(obj__)
    if size <= 1e-8:
        return 0.001
    # Typical 500ml bottle: ~0.2m, ~20cm, or ~200mm depending on authoring unit.
    if size > 50.0:
        return 1.0       # mesh likely in millimeters
    if size > 3.0:
        return 0.1       # mesh likely in centimeters
    return 0.001         # mesh likely in meters


def _patch_select_outer_lip_unit_scale(factor):
    """Rewrite the hardcoded Lip Threshold * 0.001 Math in nested Select Outer."""
    try:
        outer = bpy.data.node_groups.get(SELECT_OUTER_NG_NAME)
        if outer is None:
            return False
        # LiquiFeel_Select Outer → Group → node tree "Select Outer"
        inner = None
        for n in outer.nodes:
            if n.type == 'GROUP' and n.node_tree is not None:
                inner = n.node_tree
                break
        if inner is None:
            inner = bpy.data.node_groups.get('Select Outer')
        if inner is None:
            return False
        patched = False
        for n in inner.nodes:
            if n.type != 'MATH' or getattr(n, 'operation', None) != 'MULTIPLY':
                continue
            # Lip path: linked Value * constant (~0.001 default in assets)
            linked = [inp for inp in n.inputs if inp.is_linked]
            unlinked = [inp for inp in n.inputs
                        if (not inp.is_linked)
                        and isinstance(getattr(inp, 'default_value', None),
                                       (int, float))]
            if len(linked) < 1 or not unlinked:
                continue
            const_inp = unlinked[0]
            old = float(const_inp.default_value)
            # Only retune the known mm-scale constant (or a previously patched one).
            if abs(old - 0.001) < 1e-6 or abs(old - 0.1) < 1e-6 or abs(old - 1.0) < 1e-6 or abs(old - float(factor)) < 1e-9:
                const_inp.default_value = float(factor)
                patched = True
        return patched
    except Exception:
        return False


def assign_fill_default_vals(context, obj__):
    obj__ = context.active_object
    prop_parent = obj__.hrdc_liquifeel_input_field_props.geometry
    # Retune Select Outer lip mm-factor to the mesh's length unit BEFORE setting
    # defaults — otherwise Lip Threshold=1 is ~1000× too small/large and the
    # liquid height Map Range collapses to a tiny band.
    lip_mm = _mesh_mm_unit_factor(obj__)
    _patch_select_outer_lip_unit_scale(lip_mm)
    try:
        obj__['liquifeel_lip_mm_factor'] = float(lip_mm)
    except Exception:
        pass
    # dddd : prop : Opening Shape : opening_shape
    set_prop_value(prop_parent, 'opening_shape', 'straight', 'string')
    # dddd : GeoNode : SELECT_OUTER_NG_NAME : Lip Threshold : lip_threshold
    set_geonode_mod_input(obj__, SELECT_OUTER_NG_NAME, 'Lip Threshold', 'float', 1.0)
    # dddd : GeoNode : FILL_NG_NAME : Liquid Level : liquid_level
    # Socket is 0–100 (% of bottle Z range inside the fill GN Map Range).
    set_geonode_mod_input(
        obj__, FILL_NG_NAME, 'Liquid Level', 'float', 50.0)
    # dddd : GeoNode : FILL_NG_NAME : Meniscus Type : meniscus_type
    set_geonode_mod_input(
        obj__, FILL_NG_NAME, 'Meniscus Type', 'menu', 0) # 0 is Concave, 1 is Convex
    # dddd : GeoNode : FILL_NG_NAME : Meniscus Scale : meniscus_scale
    set_geonode_mod_input(
        obj__, FILL_NG_NAME, 'Meniscus Scale', 'float', 1.0)
    # dddd : GeoNode : FILL_NG_NAME : Wall Overlap : wall_overlap
    set_geonode_mod_input(
        obj__, FILL_NG_NAME, 'Wall Overlap', 'float', 0.005)
    # dddd : GeoNode : FILL_NG_NAME : Subdivision : subdivision
    set_geonode_mod_input(
        obj__, FILL_NG_NAME, 'Subdivision', 'int', 0)
    # dddd : GeoNode : FILL_NG_NAME : Seal : seal
    set_geonode_mod_input(
        obj__, FILL_NG_NAME, 'Seal', 'bool', False)
    # dddd : prop : Hide Recipient : hide_recipient
    set_prop_value(prop_parent, 'hide_recipient', False, 'bool')
    # dddd : prop : Hide Liquid : hide_liquid
    set_prop_value(prop_parent, 'hide_liquid', False, 'bool')    

@undo_push(2)
def fill_object(context, obj__):
    if (obj__.library or obj__.override_library
            or (obj__.data is not None and obj__.data.library)):
        info_popup(
            context,
            f"'{obj__.name}' is linked from another file and cannot be modified. "
            "Make it local first: Object > Relations > Make Local > Selected Objects and Data.")
        return
    if assert_island_count_f(1)(context, obj__):
        make_single_user_and_apply_transforms(context, obj__)
        if 'liquifeel' not in obj__.keys():
            obj__['liquifeel'] = {
                'version': bl_info['version']
            }
        obj__['liquifeel']['filled'] = True
        assign_select_outer_geonode_mod(obj__)
        assign_fill_geonode_mod(obj__)
        assign_hide_recipient_geonode_mod(obj__)
        if has_obj_condensation(obj__):
            move_mod_in_stack(
                obj__, CONDENSATION_NG_NAME, get_condensation_mod_pos_index(obj__))
        assign_fill_default_vals(context, obj__)
        schedule_separate_refresh(obj__, force=True)
# def fill_object(context, obj__):
#     if assert_island_count_f(1)(context, obj__):
#         make_single_user_and_apply_transforms(context, obj__)
#         if 'liquifeel' not in obj__.keys():
#             obj__['liquifeel'] = {}
#         obj__['liquifeel']['fill_shading'] = {
#             'filled': True
#         }
#         assign_select_outer_geonode_mod(obj__)
#         assign_fill_geonode_mod(obj__)
#         assign_hide_recipient_geonode_mod(obj__)
#         # Assigning default vals
#         for ui_input_name, redux_input_data in REDUX_INPUT_DATA['geometry']['object_attached'].items():
#             # if DEV:
#             #     print()
#             #     print(f'fill_object({context}, {obj__})')
#             #     print('ui_input_name: ', ui_input_name)
#             #     print()
#             input_field_data = index_hierarchy_by_path(
#                 INPUT_FIELD_DATA, redux_input_data['paths'][0]['list'])
#             declaration_modality_key = get_declaration_modality_key(redux_input_data)
#             prop_key_chain = [
#                 'liquifeel_input_field_props', 'geometry', declaration_modality_key, input_field_data['prop_key']]
#             prop_parent, prop_key = ref_ob_key_pair(obj__, prop_key_chain)
#             # Assigning default values for the relevant ui input props.
#             if 'ui_prop_from_default' in input_field_data['setters'].keys():
#                 input_field_data['setters']['ui_prop_from_default'](prop_parent)
#             underlying_input_setters = input_field_data['setters']['per_shading_modality'][
#                 'slot'] # Random shading_modality_key, in this case, the same update f is in both.
#             # Setting the underlying input with the default val
#             # if all(['underlying_from_default' in underlying_input_setters.keys(),
#             #         declaration_modality_key == 'synthetic']):
#             if input_field_data['ui_input_name'] == 'Liquid Amount':
#                 underlying_input_setters['underlying_from_default'](
#                     prop_parent, obj__, None)

## MENUS --------------------------------------------------------------------------------

class InfoPopup(bpy.types.Menu):
    bl_idname = f'OBJECT_MT_info_popup'
    bl_label = 'Info Popup'
    def draw(self, context):
        self.layout.label(
            text=getattr(context.scene.liquifeel_misc_data, 'info_popup_message'))
registerable_classes.append(InfoPopup)

geometry_check_report_lines = []

class GeometryCheckPopup(bpy.types.Menu):
    bl_idname = 'OBJECT_MT_liquifeel_geometry_check'
    bl_label = 'Geometry Check'
    def draw(self, context):
        for line in geometry_check_report_lines:
            self.layout.label(text=line)
registerable_classes.append(GeometryCheckPopup)

class CheckActiveGeometry(bpy.types.Operator):
    bl_idname = 'liquifeel.check_active_geometry'
    bl_label = 'Check Geometry'
    bl_description = (
        'Verify that the active object is suitable for filling:\n'
        'single mesh island, no loose geometry, walls with thickness')
    def execute(self, context):
        obj__ = resolve_liquifeel_source_object(context.active_object)
        ctrl = resolve_assembly_controller_object(obj__)
        if ctrl is not None:
            obj__ = ctrl
        if not obj__ or obj__.type != 'MESH':
            self.report({'WARNING'}, 'Active object is not a mesh.')
            return {'CANCELLED'}
        global geometry_check_report_lines
        geometry_check_report_lines = build_geometry_check_report(obj__)
        if bpy.app.background:
            for line in geometry_check_report_lines:
                print(line)
        else:
            bpy.ops.wm.call_menu(name='OBJECT_MT_liquifeel_geometry_check')
        return {'FINISHED'}
registerable_classes.append(CheckActiveGeometry)

class BakeParentTransforms(bpy.types.Operator):
    bl_idname = 'liquifeel.bake_parent_transforms'
    bl_label = 'Unparent & Apply Transforms'
    bl_description = (
        'Clear the parent (Keep Transform) and apply rotation/scale.\n'
        'Needed when the object sits under a nested hierarchy so that\n'
        'LiquiFeel can generate liquid correctly')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj__ = context.active_object
        return (
            obj__ is not None
            and obj__.type == 'MESH'
            and obj__.mode == 'OBJECT'
            and obj__.parent is not None)

    def execute(self, context):
        obj__ = context.active_object
        if (obj__.library or obj__.override_library
                or (obj__.data is not None and obj__.data.library)):
            self.report(
                {'ERROR'},
                f"'{obj__.name}' is linked from another file. "
                "Make it local first.")
            return {'CANCELLED'}
        had_parent = obj__.parent.name if obj__.parent else None
        bake_parent_transforms(context, obj__)
        self.report(
            {'INFO'},
            f"Unparented '{obj__.name}' from '{had_parent}' and applied "
            "rotation/scale.")
        return {'FINISHED'}
registerable_classes.append(BakeParentTransforms)

def _assembly_assign_poll(context):
    return context.mode == 'OBJECT'

def _assembly_find_controller(context):
    ctrl, _member = pick_assembly_assign_targets(context)
    if ctrl is not None:
        return ctrl
    ctrl = get_scene_assembly_bottle(context)
    if ctrl is not None:
        return ctrl
    active = context.active_object
    if active is not None:
        nearby = find_nearby_assembly_bottles(active)
        if len(nearby) == 1:
            return nearby[0]
    return None

def _assembly_assign_apply(self, context, ctrl, member, role, role_label):
    if ctrl is None:
        self.report(
            {'ERROR'},
            'No bottle. Select bottle mesh → Set as Bottle first.')
        return {'CANCELLED'}
    if member is None or member == ctrl:
        self.report({'ERROR'}, f'No {role_label} picked.')
        return {'CANCELLED'}
    try:
        ok, err = assign_assembly_role(ctrl, member, role)
    except Exception as exc:
        self.report({'ERROR'}, f'Assign failed: {exc}')
        return {'CANCELLED'}
    if not ok:
        self.report({'ERROR'}, err)
        return {'CANCELLED'}
    set_scene_assembly_bottle(context, ctrl)
    self.report(
        {'INFO'}, f"Assigned {role_label} '{member.name}' → '{ctrl.name}'.")
    return {'FINISHED'}

def _assembly_raycast_object(context, event):
    """Object under mouse in a VIEW_3D area, or None."""
    try:
        from bpy_extras import view3d_utils
    except Exception:
        return None
    for area in context.screen.areas:
        if area.type != 'VIEW_3D':
            continue
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            continue
        space = area.spaces.active
        if space is None or space.region_3d is None:
            continue
        # Mouse must be over this region
        if not (0 <= event.mouse_region_x < region.width
                and 0 <= event.mouse_region_y < region.height):
            # mouse_region_* is relative to the region that has focus;
            # fall through and still try with given coords.
            pass
        try:
            with context.temp_override(
                    window=context.window, area=area, region=region,
                    space_data=space, scene=context.scene):
                coord = (event.mouse_region_x, event.mouse_region_y)
                depsgraph = context.evaluated_depsgraph_get()
                region_3d = space.region_3d
                origin = view3d_utils.region_2d_to_origin_3d(
                    region, region_3d, coord)
                direction = view3d_utils.region_2d_to_vector_3d(
                    region, region_3d, coord)
                result, _loc, _n, _i, hit_obj, _m = context.scene.ray_cast(
                    depsgraph, origin, direction)
                if result and hit_obj is not None:
                    return hit_obj
        except Exception:
            continue
    return None

def _assembly_assign_invoke(self, context, event, role, role_label):
    ctrl, member = pick_assembly_assign_targets(context)
    if ctrl is None:
        ctrl = _assembly_find_controller(context)
    if ctrl is None:
        self.report(
            {'ERROR'},
            'No bottle. Select bottle mesh → Set as Bottle first.')
        return {'CANCELLED'}
    set_scene_assembly_bottle(context, ctrl)
    self.ctrl_name = ctrl.name
    if member is not None and member != ctrl:
        return _assembly_assign_apply(
            self, context, ctrl, member, role, role_label)
    context.window_manager.modal_handler_add(self)
    self.report(
        {'INFO'},
        f'Click the {role_label} in the 3D view '
        f'(bottle: {ctrl.name}). ESC cancels.')
    return {'RUNNING_MODAL'}

def _assembly_assign_modal(self, context, event, role, role_label):
    if event.type in {'RIGHTMOUSE', 'ESC'}:
        self.report({'INFO'}, 'Assign cancelled.')
        return {'CANCELLED'}
    if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
        ctrl = bpy.data.objects.get(self.ctrl_name)
        if ctrl is None or not has_assembly(ctrl):
            self.report({'ERROR'}, 'Bottle lost — Set as Bottle again.')
            return {'CANCELLED'}
        member = _assembly_raycast_object(context, event)
        if member is None:
            member = context.active_object
        if member is None or member == ctrl:
            self.report(
                {'WARNING'},
                f'Click the {role_label} object (not the bottle).')
            return {'RUNNING_MODAL'}
        return _assembly_assign_apply(
            self, context, ctrl, member, role, role_label)
    return {'RUNNING_MODAL'}

def _assembly_assign_execute(self, context, role, role_label):
    ctrl, member = pick_assembly_assign_targets(context)
    if ctrl is None:
        ctrl = _assembly_find_controller(context)
    return _assembly_assign_apply(
        self, context, ctrl, member, role, role_label)

class AssemblySetBottle(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_set_bottle'
    bl_label = 'Use Active as Bottle'
    bl_description = (
        'Mark the active mesh as the bottle.\n'
        'Also unparents it (Keep Transform) and applies rotation/scale\n'
        'so Fill works under CAD hierarchies — one step')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj__ = context.active_object
        return (
            obj__ is not None
            and obj__.type == 'MESH'
            and obj__.mode == 'OBJECT'
            and not is_liquid_proxy_object(obj__)
            and not is_assembly_member_object(obj__))

    def execute(self, context):
        obj__ = context.active_object
        try:
            ok, err = prepare_bottle_world_pose(context, obj__)
            if not ok:
                self.report({'ERROR'}, err)
                return {'CANCELLED'}
            ensure_assembly_controller(obj__)
            set_scene_assembly_bottle(context, obj__)
            try:
                context.scene.liquifeel_general_controls.assembly_bottle = obj__
            except Exception:
                pass
        except Exception as exc:
            self.report({'ERROR'}, f'Set as Bottle failed: {exc}')
            return {'CANCELLED'}
        self.report(
            {'INFO'},
            f"Bottle = '{obj__.name}' (unparented / transforms applied). "
            'Drop other parts into the slots below.')
        sync_assembly_ui_slots(context, obj__)
        return {'FINISHED'}
registerable_classes.append(AssemblySetBottle)

class AssemblyAddSelected(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_add_selected'
    bl_label = 'Add Selected'
    bl_description = (
        'Parent all selected objects (cork, label, multi-part caps, …) '
        'to the bottle so they move together')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if context.mode != 'OBJECT':
            return False
        ctrl = _assembly_find_controller(context)
        if ctrl is None:
            return False
        return bool(collect_assembly_add_roots(context, ctrl))

    def execute(self, context):
        ctrl = _assembly_find_controller(context)
        if ctrl is None:
            self.report(
                {'ERROR'},
                'No bottle. Drop a bottle into the Bottle field first.')
            return {'CANCELLED'}
        roots = collect_assembly_add_roots(context, ctrl)
        if not roots:
            self.report(
                {'ERROR'},
                'Select parts in the viewport/Outliner, or drag them into slots.')
            return {'CANCELLED'}
        try:
            added, err = add_assembly_elements(ctrl, roots)
        except Exception as exc:
            self.report({'ERROR'}, f'Add failed: {exc}')
            return {'CANCELLED'}
        if added == 0:
            self.report({'ERROR'}, err or 'Nothing added.')
            return {'CANCELLED'}
        apply_assembly_hide_extras_if_enabled(context, ctrl)
        set_scene_assembly_bottle(context, ctrl)
        sync_assembly_ui_slots(context, ctrl)
        self.report(
            {'INFO'},
            f"Added {added} element(s) to '{ctrl.name}'.")
        return {'FINISHED'}
registerable_classes.append(AssemblyAddSelected)

class AssemblySlotAdd(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_slot_add'
    bl_label = 'Add Drop Slot'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            context.scene.liquifeel_general_controls.assembly_parts.add()
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'}
registerable_classes.append(AssemblySlotAdd)

class AssemblySlotRemove(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_slot_remove'
    bl_label = 'Remove Part'
    bl_options = {'REGISTER', 'UNDO'}
    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        controls = context.scene.liquifeel_general_controls
        parts = controls.assembly_parts
        idx = self.index
        if idx < 0 or idx >= len(parts):
            return {'CANCELLED'}
        obj__ = parts[idx].object
        bottle = controls.assembly_bottle
        if obj__ is not None and bottle is not None:
            try:
                if obj__.parent == bottle or (
                        _lqfl_marker_get(obj__).get('controller') == bottle.name):
                    _detach_assembly_member(obj__)
                    # Drop from extras / cork / label names
                    asm = get_assembly_dict(bottle)
                    if asm:
                        if asm.get('cork') == obj__.name:
                            asm['cork'] = ''
                        if asm.get('label') == obj__.name:
                            asm['label'] = ''
                        asm['extras'] = [
                            n for n in asm.get('extras', []) if n != obj__.name]
                        set_assembly_dict(bottle, asm)
            except Exception as exc:
                print(f'LIQUIFEEL: slot remove detach: {exc}')
        parts.remove(idx)
        sync_assembly_ui_slots(context, bottle)
        return {'FINISHED'}
registerable_classes.append(AssemblySlotRemove)

class AssemblyAssignCork(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_assign_cork'
    bl_label = 'Assign Cork'
    bl_description = (
        'Assign cork: uses selection, or click object in the viewport')
    bl_options = {'REGISTER', 'UNDO'}
    ctrl_name: bpy.props.StringProperty(default='')

    @classmethod
    def poll(cls, context):
        return _assembly_assign_poll(context)

    def invoke(self, context, event):
        return _assembly_assign_invoke(
            self, context, event, ASSEMBLY_ROLE_CORK, 'cork')

    def modal(self, context, event):
        return _assembly_assign_modal(
            self, context, event, ASSEMBLY_ROLE_CORK, 'cork')

    def execute(self, context):
        return _assembly_assign_execute(
            self, context, ASSEMBLY_ROLE_CORK, 'cork')
registerable_classes.append(AssemblyAssignCork)

class AssemblyAssignLabel(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_assign_label'
    bl_label = 'Assign Label'
    bl_description = (
        'Assign label: uses selection, or click object in the viewport')
    bl_options = {'REGISTER', 'UNDO'}
    ctrl_name: bpy.props.StringProperty(default='')

    @classmethod
    def poll(cls, context):
        return _assembly_assign_poll(context)

    def invoke(self, context, event):
        return _assembly_assign_invoke(
            self, context, event, ASSEMBLY_ROLE_LABEL, 'label')

    def modal(self, context, event):
        return _assembly_assign_modal(
            self, context, event, ASSEMBLY_ROLE_LABEL, 'label')

    def execute(self, context):
        return _assembly_assign_execute(
            self, context, ASSEMBLY_ROLE_LABEL, 'label')
registerable_classes.append(AssemblyAssignLabel)

class AssemblyAddExtra(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_add_extra'
    bl_label = 'Add Extra'
    bl_description = (
        'Assign extra: uses selection, or click object in the viewport')
    bl_options = {'REGISTER', 'UNDO'}
    ctrl_name: bpy.props.StringProperty(default='')

    @classmethod
    def poll(cls, context):
        return _assembly_assign_poll(context)

    def invoke(self, context, event):
        return _assembly_assign_invoke(
            self, context, event, ASSEMBLY_ROLE_EXTRA, 'extra')

    def modal(self, context, event):
        return _assembly_assign_modal(
            self, context, event, ASSEMBLY_ROLE_EXTRA, 'extra')

    def execute(self, context):
        return _assembly_assign_execute(
            self, context, ASSEMBLY_ROLE_EXTRA, 'extra')
registerable_classes.append(AssemblyAddExtra)

class AssemblyClearCork(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_clear_cork'
    bl_label = 'Clear Cork'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj__ = context.active_object
        ctrl = resolve_assembly_controller_object(obj__) if obj__ else None
        return ctrl is not None and resolve_assembly_cork(ctrl) is not None

    def execute(self, context):
        ctrl = resolve_assembly_controller_object(context.active_object)
        ok, err = clear_assembly_role(ctrl, ASSEMBLY_ROLE_CORK)
        if not ok:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        self.report({'INFO'}, 'Cleared cork from assembly.')
        return {'FINISHED'}
registerable_classes.append(AssemblyClearCork)

class AssemblyClearLabel(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_clear_label'
    bl_label = 'Clear Label'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        obj__ = context.active_object
        ctrl = resolve_assembly_controller_object(obj__) if obj__ else None
        return ctrl is not None and resolve_assembly_label(ctrl) is not None

    def execute(self, context):
        ctrl = resolve_assembly_controller_object(context.active_object)
        ok, err = clear_assembly_role(ctrl, ASSEMBLY_ROLE_LABEL)
        if not ok:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        self.report({'INFO'}, 'Cleared label from assembly.')
        return {'FINISHED'}
registerable_classes.append(AssemblyClearLabel)

class AssemblyRemoveMember(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_remove_member'
    bl_label = 'Remove Extra'
    bl_description = 'Unparent an extra from the bottle assembly (Keep Transform)'
    bl_options = {'REGISTER', 'UNDO'}

    member_name: bpy.props.StringProperty(name='Member Name', default='')

    @classmethod
    def poll(cls, context):
        obj__ = context.active_object
        ctrl = resolve_assembly_controller_object(obj__) if obj__ else None
        return ctrl is not None and has_assembly(ctrl)

    def execute(self, context):
        ctrl = resolve_assembly_controller_object(context.active_object)
        if not self.member_name:
            self.report({'ERROR'}, 'No member name.')
            return {'CANCELLED'}
        ok, err = clear_assembly_role(
            ctrl, ASSEMBLY_ROLE_EXTRA, extra_name=self.member_name)
        if not ok:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        self.report({'INFO'}, f"Removed '{self.member_name}' from assembly.")
        return {'FINISHED'}
registerable_classes.append(AssemblyRemoveMember)

class AssemblyToggleHideExtras(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_toggle_hide_extras'
    bl_label = 'Hide Extras'
    bl_description = (
        'Hide / show cork, label and extras (and their children) in the viewport.\n'
        'Bottle and liquid stay visible. Applies to every Assembly bottle in the file.')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        try:
            bottle = context.scene.liquifeel_general_controls.assembly_bottle
        except Exception:
            bottle = None
        if bottle is not None and has_assembly(bottle):
            return True
        return _assembly_find_controller(context) is not None

    def execute(self, context):
        controls = context.scene.liquifeel_general_controls
        new_state = not bool(controls.assembly_hide_extras)
        # Write flag with the callback's apply suppressed, then apply exactly
        # once here (its return is the count used for the report below).
        global _hide_extras_applying
        _hide_extras_applying = True
        try:
            controls.assembly_hide_extras = new_state
        finally:
            _hide_extras_applying = False
        n = apply_assembly_hide_state(context, new_state)
        if new_state:
            if n == 0:
                self.report(
                    {'WARNING'},
                    'Hide Extras ON — nothing to hide. Are parts linked under the bottle?')
            else:
                self.report({'INFO'}, f'Hidden {n} part object(s).')
        else:
            self.report({'INFO'}, f'Shown {n} part object(s).')
        return {'FINISHED'}
registerable_classes.append(AssemblyToggleHideExtras)

class AssemblyClear(bpy.types.Operator):
    bl_idname = 'liquifeel.assembly_clear'
    bl_label = 'Clear Assembly'
    bl_description = (
        'Unparent parts from the bottle and clear assembly markers.\n'
        'Does not delete objects or clear Fill')
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ctrl = _assembly_find_controller(context)
        return ctrl is not None and has_assembly(ctrl)

    def execute(self, context):
        ctrl = _assembly_find_controller(context)
        if ctrl is None:
            return {'CANCELLED'}
        ok, err = clear_assembly(ctrl)
        if not ok:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}
        try:
            controls = context.scene.liquifeel_general_controls
            controls.assembly_parts.clear()
            controls.assembly_bottle = None
        except Exception:
            pass
        try:
            context.scene.pop(SCENE_ASSEMBLY_BOTTLE_KEY, None)
        except Exception:
            pass
        sync_assembly_ui_slots(context, None)
        self.report({'INFO'}, f"Cleared assembly on '{ctrl.name}'.")
        return {'FINISHED'}
registerable_classes.append(AssemblyClear)

def is_liquifeel_leftover_ng(ng):
    return ('liquifeel' in ng.keys()
            or '__legacy' in ng.name
            or ng.name.startswith((
                'LiquiFeel',
                HIDE_RECIPIENT_NG_NAME,
                CONDENSATION_NG_NAME)))

# Internal sub-groups that only LiquiFeel's node network uses. Matched by base
# name (ignoring Blender's .001/.002 duplicate suffixes) so accumulated copies
# get swept too. Deliberately excludes 'Smooth by Angle' (a Blender built-in)
# and the generic 'NodeGroup' name (could belong to the user).
LIQUIFEEL_SUBGROUP_BASENAMES = {
    'Liquid Boolean', 'Liquid Surface', 'Select Outer', 'Select Larger Surface',
    'BlurTopFace', 'Fill Empty Face', 'LiquiFeelv1.3_Group',
}

def strip_datablock_suffix(name):
    # 'Liquid Boolean.002' -> 'Liquid Boolean'
    if len(name) > 4 and name[-4] == '.' and name[-3:].isdigit():
        return name[:-4]
    return name

def is_liquifeel_subgroup_name(name):
    return strip_datablock_suffix(name) in LIQUIFEEL_SUBGROUP_BASENAMES

def collect_node_group_deps(ng, acc):
    # every node group referenced (recursively) inside `ng`
    if ng is None or ng in acc:
        return
    for node in getattr(ng, 'nodes', []):
        sub = getattr(node, 'node_tree', None)
        if sub is not None and sub not in acc:
            acc.add(sub)
            collect_node_group_deps(sub, acc)

# Removes every LiquiFeel datablock from the file: modifiers, markers,
# node groups and materials - including the nested sub-groups that the main
# groups pull in (Liquid Boolean, Liquid Surface, ...). Those are appended
# with a fake user, so a plain orphan-purge never reaps them; they pile up as
# .001 / .002 copies on every re-append and travel inside the saved .blend.
def deep_clean_liquifeel_data(context):
    removed = {'modifiers': 0, 'node_groups': 0, 'materials': 0, 'markers': 0}
    # 1. Identify the top-level LiquiFeel groups and their dependency closure.
    #    Snapshot dependency NAMES (stable strings) up front - removing a top
    #    group can cascade-invalidate the datablock references in `deps`.
    top_groups = [ng for ng in bpy.data.node_groups if is_liquifeel_leftover_ng(ng)]
    dep_objs = set()
    for ng in top_groups:
        collect_node_group_deps(ng, dep_objs)
    top_names = {ng.name for ng in top_groups}
    dep_names = {ng.name for ng in dep_objs} - top_names
    # 2. Strip modifiers and markers from every object; remove liquid proxies.
    for obj in list(bpy.data.objects):
        if is_liquid_proxy_object(obj):
            mesh = obj.data
            bpy.data.objects.remove(obj, do_unlink=True)
            if mesh is not None and mesh.users == 0:
                bpy.data.meshes.remove(mesh)
            continue
        for mod in list(obj.modifiers):
            if mod.type == 'NODES' and (
                    (mod.node_group is None and mod.name.startswith((
                        'LiquiFeel', HIDE_RECIPIENT_NG_NAME, CONDENSATION_NG_NAME)))
                    or (mod.node_group is not None
                        and is_liquifeel_leftover_ng(mod.node_group))):
                obj.modifiers.remove(mod)
                removed['modifiers'] += 1
        if 'liquifeel' in obj.keys():
            del obj['liquifeel']
            removed['markers'] += 1
        obj.update_tag()
    # 3. Remove the top-level groups outright (works despite fake users).
    for name in top_names:
        ng = bpy.data.node_groups.get(name)
        if ng is not None:
            try:
                bpy.data.node_groups.remove(ng)
                removed['node_groups'] += 1
            except Exception:
                pass
    # 4. Clear fake users on LiquiFeel's internal sub-groups so the purge can
    #    reap them: both the ones reachable from the top groups AND any
    #    orphaned .001/.002 copies left over from earlier re-appends. Anything
    #    still genuinely used elsewhere keeps its real users and survives.
    for ng in list(bpy.data.node_groups):
        if ng.name in dep_names or is_liquifeel_subgroup_name(ng.name):
            ng.use_fake_user = False
    for mat in list(bpy.data.materials):
        if 'liquifeel' in mat.keys():
            mat.use_fake_user = False
            bpy.data.materials.remove(mat)
            removed['materials'] += 1
    # 5. Recursively purge whatever is now orphaned (sub-groups, images, ...).
    try:
        before = len(bpy.data.node_groups)
        unused_data_purge(context)
        removed['node_groups'] += max(0, before - len(bpy.data.node_groups))
    except Exception as e:
        print(f'LIQUIFEEL: orphan purge skipped ({e})')
    return removed

class DeepCleanLiquifeelData(bpy.types.Operator):
    bl_idname = 'liquifeel.deep_clean_data'
    bl_label = 'Remove All LiquiFeel Data'
    bl_description = (
        'Remove every LiquiFeel modifier, node group and material from this file\n'
        '(including stale/broken copies). Fills on all objects are cleared.\n'
        'Use this to fix a file where filling stopped working, then fill again')
    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)
    def execute(self, context):
        removed = deep_clean_liquifeel_data(context)
        self.report(
            {'INFO'},
            'LiquiFeel data removed: '
            f"{removed['modifiers']} modifiers, {removed['node_groups']} node groups, "
            f"{removed['materials']} materials, {removed['markers']} object markers.")
        return {'FINISHED'}
registerable_classes.append(DeepCleanLiquifeelData)

def reset_liquifeel_on_object(obj__):
    base_names = (SELECT_OUTER_NG_NAME, FILL_NG_NAME,
                  HIDE_RECIPIENT_NG_NAME, CONDENSATION_NG_NAME)
    for mod in list(obj__.modifiers):
        if mod.type != 'NODES':
            continue
        name_match = any(
            mod.name == n or mod.name.startswith(n + '.') for n in base_names)
        ng_match = (mod.node_group is not None
                    and is_liquifeel_leftover_ng(mod.node_group))
        if name_match or ng_match:
            obj__.modifiers.remove(mod)
    if 'liquifeel' in obj__.keys():
        del obj__['liquifeel']
    obj__.update_tag()

class ResetLiquifeelOnObject(bpy.types.Operator):
    bl_idname = 'liquifeel.reset_active_object'
    bl_label = 'Reset LiquiFeel on This Object'
    bl_description = (
        'Strip all LiquiFeel modifiers and markers from the active object\n'
        '(even broken ones), so the object can be filled again from scratch')
    def execute(self, context):
        obj__ = context.active_object
        if not obj__:
            self.report({'WARNING'}, 'No active object.')
            return {'CANCELLED'}
        reset_liquifeel_on_object(obj__)
        self.report({'INFO'}, f"LiquiFeel state reset on '{obj__.name}'.")
        return {'FINISHED'}
registerable_classes.append(ResetLiquifeelOnObject)

def _eval_vert_count(context, obj__):
    deps = context.evaluated_depsgraph_get()
    ev = obj__.evaluated_get(deps)
    try:
        me = ev.to_mesh()
        n = len(me.vertices)
        ev.to_mesh_clear()
        return n
    except Exception as e:
        return f'no-mesh ({e})'

# Toggles the three fill modifiers on progressively (Select Outer, then + Fill,
# then + Hide Recipient) and measures the evaluated vertex count after each, so
# we can see which stage drops the geometry to zero. Restores all state.
def diagnose_fill_stage_lines(context, obj__):
    stage_names = [SELECT_OUTER_NG_NAME, FILL_NG_NAME, HIDE_RECIPIENT_NG_NAME]
    mods = []
    for n in stage_names:
        try:
            mods.append((n, get_geonodes_mod_by_ng_name(obj__, n)))
        except Exception:
            return [f'Stage isolation: modifier {n} missing, skipped.']
    saved_show = {n: m.show_viewport for n, m in mods}
    # temporarily force Hide Recipient off so a live recipient is measurable
    hide_mod = dict(mods)[HIDE_RECIPIENT_NG_NAME]
    saved_hide = None
    try:
        hid = get_geonodes_field_identifier(hide_mod, 'Hide Recipient')
        saved_hide = geonode_input_get(hide_mod, hid)
        geonode_input_set(hide_mod, hid, False)
    except Exception:
        pass
    lines = ['Stage isolation (evaluated verts as each stage is added, '
             'Hide Recipient forced OFF):']
    try:
        for i in range(len(mods)):
            for j, (n, m) in enumerate(mods):
                m.show_viewport = (j <= i)
            obj__.update_tag()
            chain = ' + '.join(n for n, _ in mods[:i + 1])
            lines.append(f'  after [{chain}]: {_eval_vert_count(context, obj__)}')
    finally:
        for n, m in mods:
            m.show_viewport = saved_show[n]
        if saved_hide is not None:
            try:
                geonode_input_set(hide_mod, hid, saved_hide)
            except Exception:
                pass
        obj__.update_tag()
    return lines

def build_liquifeel_diagnostics(context):
    import sys as sys__, traceback as traceback__
    lines = []
    lines.append(f'LiquiFeel diagnostics | build: {ADDON_BUILD_TAG} | '
                 f'Blender: {bpy.app.version_string} | addon file: {__file__}')
    # Scene scale: a non-unit scale_length (e.g. a millimetre scene at 0.001)
    # changes the world size the fill Geometry Nodes see and is a common cause
    # of mis-sized / mis-placed liquid.
    us = context.scene.unit_settings
    scene_warn = ('  <-- NON-UNIT SCENE SCALE (fill/liquid may be mis-sized)'
                  if abs(us.scale_length - 1.0) > 1e-6 else '')
    lines.append(
        f"Scene units: system={us.system} length={us.length_unit} "
        f"scale_length={round(us.scale_length, 6)}{scene_warn}")
    obj__ = context.active_object
    if obj__ is None:
        lines.append('Active object: None')
    else:
        lines.append(
            f"Active object: '{obj__.name}' type={obj__.type} mode={obj__.mode} "
            f"linked={obj__.library is not None} "
            f"override={obj__.override_library is not None} "
            f"data_linked={getattr(obj__.data, 'library', None) is not None} "
            f"scale={tuple(round(v, 4) for v in obj__.scale)}")
        # World scale (folds in parent scale like a 'skala0.5' CAD root),
        # world dimensions, and non-uniform/non-unit warnings — the geometry
        # the fill nodes actually operate on.
        _, _, world_scale = obj__.matrix_world.decompose()
        orient = _xform_diag_orientation(obj__)
        nonuniform = (max(world_scale) - min(world_scale)) > 1e-4
        obj_warn = ''
        if nonuniform:
            obj_warn += '  <-- NON-UNIFORM SCALE (fill may shear/distort)'
        if any(abs(v - 1.0) > 1e-3 for v in world_scale):
            obj_warn += '  <-- NON-UNIT WORLD SCALE (fill/liquid may be mis-sized)'
        dims_local = orient['dimensions_local']
        try:
            dmax = max(dims_local)
            dmin = min(dims_local)
            if dmax > 1e-8 and (dmin / dmax) < 0.05:
                obj_warn += '  <-- FLAT LOCAL BOUNDS (mesh thin on one axis)'
        except Exception:
            pass
        if abs(float(orient['local_z_dot_world_z'])) < 0.5:
            obj_warn += '  <-- SIDEWAYS (local +Z not aligned with world +Z)'
        lines.append(
            f"Object scale: local={tuple(round(v, 4) for v in obj__.scale)} "
            f"world={tuple(round(v, 4) for v in world_scale)} "
            f"dimensions_local={tuple(dims_local)} "
            f"dimensions_world_aabb="
            f"{tuple(orient['dimensions_world_aabb'])}{obj_warn}")
        lines.append(
            f"Object orientation: mode={orient['rotation_mode']} "
            f"local_euler_deg={tuple(orient['local_euler_deg'])} "
            f"world_euler_deg={tuple(orient['world_euler_deg'])} "
            f"tallest_local={orient['tallest_local_axis']} "
            f"tallest_world={orient['tallest_world_axis']} "
            f"local_z_dot_world_z={orient['local_z_dot_world_z']} "
            f"local_z_world_dir={tuple(orient['local_z_world_dir'])}")
        # Liquid Level is 0–100% of bottle Z; Select Outer lip uses a mm factor.
        try:
            lip_mm = float(obj__.get('liquifeel_lip_mm_factor',
                                     _mesh_mm_unit_factor(obj__)))
        except Exception:
            lip_mm = _mesh_mm_unit_factor(obj__)
        world_size = _object_world_size(obj__)
        lines.append(
            f"Fill scale: world_size={round(world_size, 4)} "
            f"lip_mm_factor={lip_mm} "
            f"(Select Outer uses LipThreshold*{lip_mm} as mesh offset; "
            f"Liquid Level socket is 0-100% of bottle height)")
        try:
            lvl = get_geonodes_mod_input_val(obj__, FILL_NG_NAME, 'Liquid Level')
            lines.append(f"Liquid Level (live): {lvl}  (0-100% of fill height range)")
        except Exception:
            lines.append('Liquid Level (live): unavailable (no fill modifier)')
        chain = []
        _p = obj__.parent
        while _p is not None:
            chain.append(f"{_p.name}{tuple(round(v, 3) for v in _p.scale)}")
            _p = _p.parent
        lines.append('Parent chain (name+scale): '
                     + (' -> '.join(chain) if chain else '(none)'))
        # Live direct children — useful when diagnosing cork/label/liquid drift.
        child_lines = []
        for child in obj__.children:
            try:
                _, cq, cws = child.matrix_world.decompose()
                mpi_ok = _xform_diag_mpi_is_identity(child)
                child_lines.append(
                    f"  '{child.name}' world_loc="
                    f"{tuple(round(v, 4) for v in child.matrix_world.translation)} "
                    f"local_scale={tuple(round(v, 4) for v in child.scale)} "
                    f"world_scale={tuple(round(v, 4) for v in cws)} "
                    f"local_euler_deg="
                    f"{tuple(_xform_diag_euler_deg(child.rotation_euler))} "
                    f"world_euler_deg="
                    f"{tuple(_xform_diag_euler_deg(cq.to_euler('XYZ')))} "
                    f"mpi_identity={mpi_ok}")
            except Exception as e:
                child_lines.append(f"  '{child.name}': <err:{e}>")
        lines.append('Children (live): '
                     + ('(none)' if not child_lines else ''))
        lines.extend(child_lines)
        # Silent last-event from bake/fill/liquid transform hooks.
        xdiag = None
        try:
            if XFORM_DIAG_KEY in obj__.keys():
                raw = obj__[XFORM_DIAG_KEY]
                if hasattr(raw, 'to_dict'):
                    xdiag = raw.to_dict()
                elif isinstance(raw, dict):
                    xdiag = dict(raw)
                else:
                    xdiag = None
        except Exception:
            xdiag = None
        if not xdiag:
            lines.append('Last transform event: (none)')
        else:
            lines.append(
                f"Last transform event: op={xdiag.get('op')} "
                f"build={xdiag.get('build')} "
                f"max_child_drift={xdiag.get('max_child_drift')} "
                f"warnings={list(xdiag.get('warnings') or [])}")
            before = xdiag.get('before') or {}
            after = xdiag.get('after') or {}
            if hasattr(before, 'to_dict'):
                before = before.to_dict()
            if hasattr(after, 'to_dict'):
                after = after.to_dict()
            lines.append(
                f"  before: local_scale={before.get('local_scale')} "
                f"world_scale={before.get('world_scale')} "
                f"local_euler_deg={before.get('local_euler_deg')} "
                f"world_euler_deg={before.get('world_euler_deg')} "
                f"dims_local={before.get('dimensions_local')} "
                f"dims_world={before.get('dimensions_world_aabb')} "
                f"tallest_local/world="
                f"{before.get('tallest_local_axis')}/"
                f"{before.get('tallest_world_axis')} "
                f"local_z_dot_world_z={before.get('local_z_dot_world_z')} "
                f"parent={before.get('parent')!r} "
                f"parent_chain={before.get('parent_chain')}")
            lines.append(
                f"  after:  local_scale={after.get('local_scale')} "
                f"world_scale={after.get('world_scale')} "
                f"local_euler_deg={after.get('local_euler_deg')} "
                f"world_euler_deg={after.get('world_euler_deg')} "
                f"dims_local={after.get('dimensions_local')} "
                f"dims_world={after.get('dimensions_world_aabb')} "
                f"tallest_local/world="
                f"{after.get('tallest_local_axis')}/"
                f"{after.get('tallest_world_axis')} "
                f"local_z_dot_world_z={after.get('local_z_dot_world_z')} "
                f"parent={after.get('parent')!r} "
                f"parent_chain={after.get('parent_chain')}")
            if after.get('liquid') or before.get('liquid'):
                lines.append(
                    f"  liquid: before={before.get('liquid')!r}/"
                    f"{before.get('liquid_world_scale')} "
                    f"after={after.get('liquid')!r}/"
                    f"{after.get('liquid_world_scale')} "
                    f"parent_after={after.get('liquid_parent')!r}")
            drifts = xdiag.get('child_drifts') or []
            if hasattr(drifts, 'to_list'):
                drifts = drifts.to_list()
            elif hasattr(drifts, 'values') and not isinstance(drifts, (list, tuple)):
                try:
                    drifts = list(drifts.values())
                except Exception:
                    drifts = []
            if drifts:
                lines.append('  child drifts (>eps):')
                for d in drifts:
                    if hasattr(d, 'to_dict'):
                        d = d.to_dict()
                    if not isinstance(d, dict):
                        continue
                    lines.append(
                        f"    '{d.get('name')}' drift={d.get('drift')} "
                        f"loc {d.get('world_loc_before')} -> "
                        f"{d.get('world_loc_after')}")
        marker = obj__.get('liquifeel')
        lines.append(f"Object 'liquifeel' marker: "
                     f"{marker.to_dict() if hasattr(marker, 'to_dict') else marker}")
        lines.append('Modifiers:')
        for mod in obj__.modifiers:
            if mod.type == 'NODES':
                ng = mod.node_group
                ng_desc = ('None' if ng is None else
                           f"'{ng.name}' (linked={ng.library is not None}, "
                           f"marker={'liquifeel' in ng.keys()})")
                lines.append(f"  [NODES] '{mod.name}' -> group {ng_desc} "
                             f"viewport={mod.show_viewport}")
            else:
                lines.append(f"  [{mod.type}] '{mod.name}'")
        if obj__.type == 'MESH':
            base_v = len(obj__.data.vertices)
            try:
                deps = context.evaluated_depsgraph_get()
                ev = obj__.evaluated_get(deps)
                ev_me = ev.to_mesh()
                eval_v = len(ev_me.vertices)
                ev.to_mesh_clear()
                eval_desc = str(eval_v)
                if eval_v <= base_v:
                    eval_desc += '  <-- NO LIQUID GENERATED (evaluated <= base)'
            except Exception as e:
                eval_desc = f'to_mesh failed: {e}  <-- modifier output has no mesh'
            lines.append(f'Mesh: base_verts={base_v} evaluated_verts={eval_desc} '
                         f'islands={count_mesh_islands(obj__)}')
            # Per-stage isolation: toggle the LiquiFeel modifiers on one at a
            # time to see exactly which node group zeroes the geometry.
            try:
                lines.extend(diagnose_fill_stage_lines(context, obj__))
            except Exception as e:
                lines.append(f'Stage isolation: failed ({e})')
        # fill modifier input values
        try:
            fmod = get_geonodes_mod_by_ng_name(obj__, FILL_NG_NAME)
            vals = []
            for socket in fmod.node_group.interface.items_tree.values():
                if getattr(socket, 'in_out', None) == 'INPUT':
                    try:
                        v = geonode_input_get(
                            fmod, get_geonodes_field_identifier(fmod, socket.name))
                    except Exception as e:
                        v = f'<err:{e}>'
                    vals.append(f'{socket.name}={v}')
            lines.append('Fill inputs: ' + ', '.join(vals))
        except Exception as e:
            lines.append(f'Fill inputs: unavailable ({e})')
    lines.append('Node groups in file:')
    for ng in bpy.data.node_groups:
        lines.append(f"  '{ng.name}' users={ng.users} fake_user={ng.use_fake_user} "
                     f"linked={ng.library is not None} marker={'liquifeel' in ng.keys()}")
    if getattr(sys__, 'last_traceback', None):
        lines.append('Last Python error in this session:')
        lines.extend('  ' + l.rstrip() for l in traceback__.format_exception(
            sys__.last_type, sys__.last_value, sys__.last_traceback))
    else:
        lines.append('Last Python error in this session: none recorded')
    return '\n'.join(lines)

class CopyLiquifeelDiagnostics(bpy.types.Operator):
    bl_idname = 'liquifeel.copy_diagnostics'
    bl_label = 'Copy LiquiFeel Diagnostics'
    bl_description = ('Collect LiquiFeel state of the file and active object\n'
                      '(plus the last Python error) and copy it to the clipboard')
    def execute(self, context):
        report = build_liquifeel_diagnostics(context)
        context.window_manager.clipboard = report
        print(report)
        self.report({'INFO'}, 'LiquiFeel diagnostics copied to clipboard.')
        return {'FINISHED'}
registerable_classes.append(CopyLiquifeelDiagnostics)

## OPERATORS --------------------------------------------------------------------------------


class UpdateRenderView(bpy.types.Operator):
    bl_idname = 'liquifeel.update_render_view'
    bl_label = 'Launch Feedback Form'
    def execute(self, context):
        update_render_view(context)
        return {'FINISHED'}
registerable_classes.append(UpdateRenderView)


class FillActive(bpy.types.Operator):
    bl_idname = 'liquifeel.fill_active_object'
    bl_label = 'Fill Selected'
    def execute(self, context):
        obj__ = resolve_liquifeel_source_object(context.active_object)
        ctrl = resolve_assembly_controller_object(obj__)
        if ctrl is not None:
            obj__ = ctrl
        if obj__ is None:
            self.report({'ERROR'}, 'No object to fill.')
            return {'CANCELLED'}
        select_and_set_active(context, obj__, deselect_all=True)
        fill_object(context, obj__)
        return {'FINISHED'}
registerable_classes.append(FillActive)

class AddCondensationToActive(bpy.types.Operator):
    bl_idname = 'liquifeel.add_condensation_to_active_object'
    bl_label = 'Add Condensation To Active Object'
    def execute(self, context):
        obj__ = context.active_object
        add_condensation_to_active_object(context, obj__)
        return {'FINISHED'}
registerable_classes.append(AddCondensationToActive)

@undo_push(1)
def append_recipient_asset(context):
    asset_key = context.scene.liquifeel_general_controls.recipient_asset
    obj__, children_objss = append_recipient_asset__(
        context,
        RECIPIENT_ASSET_PARENTING_DATA[asset_key])
    c_loc = context.scene.cursor.location
    obj__.location = c_loc
    obj__.name = RECIPIENT_ASSET_NAME_DATA[asset_key]['thumbnail']
    select_and_set_active(context, obj__, deselect_all=True)

class AddAssetTo3DCursor(bpy.types.Operator):
    bl_idname = 'liquifeel.add_asset_to_3d_cursor'
    bl_label = 'Add Asset To 3D Cursor'
    def execute(self, context):
        append_recipient_asset(context)
        return {'FINISHED'}
registerable_classes.append(AddAssetTo3DCursor)

@undo_push(1)
def clear_asset(context):
    obj__ = context.active_object
    # remove all liquifeel modifiers
    for mod in [mod for mod in obj__.modifiers if is_lqfl_modifier(mod)]:
        obj__.modifiers.remove(mod)
    # remove materials
    obj__.data.materials.clear()
    # remove object tags
    if 'liquifeel' in obj__:
        obj__.pop('liquifeel')

@undo_push(1)
def clear_fill(context, material_only=False):
    obj__ = resolve_liquifeel_source_object(context.active_object)
    ctrl = resolve_assembly_controller_object(obj__)
    if ctrl is not None:
        obj__ = ctrl
    if obj__ is None:
        return
    select_and_set_active(context, obj__, deselect_all=True)
    teardown_separate_liquid_object(context, obj__)
    try:
        obj__.hrdc_liquifeel_input_field_props.geometry.separate_objects = False
    except Exception:
        pass
    # Remove the fill modifier and its auxiliary mods - tolerantly, so that a
    # partially broken fill (missing mods, dangling node groups) can still be
    # cleared instead of raising and leaving the object stuck.
    mod_ng_names_to_remove = [
        SELECT_OUTER_NG_NAME, FILL_NG_NAME, HIDE_RECIPIENT_NG_NAME]
    for ng_name in mod_ng_names_to_remove:
        remove_geonode_mods_by_ng_name(obj__, ng_name)
        remove_mods(obj__, lambda mod, n=ng_name: mod.type == 'NODES' and (
            mod.name == n or mod.name.startswith(n + '.')))
    # remove the material auxiliary modifiers
    for mod in [mod for mod in obj__.modifiers if is_shader_aux_modifier(
            mod, obj__, 'fill')]:
        obj__.modifiers.remove(mod)
    if not(is_obj_library_slot_shaded__anylib(obj__)):
        if has_assembly(obj__):
            _lqfl_strip_fill_keys_keep_assembly(obj__)
        else:
            maybe_remove_lqfl_object_tags(obj__)
    obj__.update_tag()

def apply_condensation(context):
    obj__ = context.active_object
    # apply the condensation geonodes modifier
    bpy.ops.object.modifier_apply(
        modifier=CONDENSATION_NG_NAME)
    # bpy.ops.object.modifier_apply(
    #     modifier=get_geonodes_mod_by_ng_name(obj__, CONDENSATION_NG_NAME).name)
    # If the condensation was the only assigned feature which made the
    # object a liquifeel asset, we can remove the liquifeel tags.
    if not(is_obj_filled(obj__)) and not(is_obj_lqfl_shaded(obj__)):
        maybe_remove_lqfl_object_tags(obj__)

class ApplyCondensation(bpy.types.Operator):
    bl_idname = 'liquifeel.apply_condensation'
    bl_label = 'Apply Condensation'
    def execute(self, context):
        apply_condensation(context)
        return {'FINISHED'}
registerable_classes.append(ApplyCondensation)

@undo_push(1)
def clear_condensation(context):
    obj__ = context.active_object
    remove_geonode_mods_by_ng_name(obj__, CONDENSATION_NG_NAME)

class ClearCondensation(bpy.types.Operator):
    bl_idname = 'liquifeel.clear_condensation'
    bl_label = 'Clear Condensation'
    def execute(self, context):
        clear_condensation(context)
        return {'FINISHED'}
registerable_classes.append(ClearCondensation)

@undo_push(1)
def clear_fill_material(context):
    obj__ = context.active_object
    # remove all fill shader liquifeel modifiers
    set_geonode_mod_input(
        obj__, FILL_NG_NAME, 'Liquid Shader', 'material', None)
    # remove the material auxiliary modifiers
    for mod in [mod for mod in obj__.modifiers if is_shader_aux_modifier(
            mod, obj__, 'fill')]:
        obj__.modifiers.remove(mod)
    if not(is_obj_library_slot_shaded__anylib(obj__)):
        maybe_remove_lqfl_object_tags(obj__)

@undo_push(1)
def clear_slot(context):
    obj__ = context.active_object
    # remove the material auxiliary modifiers
    for mod in [mod for mod in obj__.modifiers if is_shader_aux_modifier(
            mod, obj__, 'slot')]:
        obj__.modifiers.remove(mod)
    # remove materials
    obj__.data.materials.clear()
    # maybe remove object tags
    if not(is_obj_filled(obj__)):
        maybe_remove_lqfl_object_tags(obj__)

class ClearAsset(bpy.types.Operator):
    bl_idname = 'liquifeel.clear_asset'
    bl_label = 'Clear'
    def execute(self, context):
        clear_asset(context)
        return {'FINISHED'}
registerable_classes.append(ClearAsset)

class ClearFill(bpy.types.Operator):
    bl_idname = 'liquifeel.clear_fill'
    bl_label = 'Clear Fill'
    def execute(self, context):
        clear_fill(context)
        return {'FINISHED'}
registerable_classes.append(ClearFill)

class ClearFillMaterial(bpy.types.Operator):
    bl_idname = 'liquifeel.clear_fill_material'
    bl_label = 'Clear Fill'
    def execute(self, context):
        clear_fill_material(context)
        return {'FINISHED'}
registerable_classes.append(ClearFillMaterial)

class ClearSlot(bpy.types.Operator):
    bl_idname = 'liquifeel.clear_slot'
    bl_label = 'Clear Slot Material'
    def execute(self, context):
        clear_slot(context)
        return {'FINISHED'}
registerable_classes.append(ClearSlot)

def maybe_remove_lqfl_object_tags(obj__):
    for tag_key in LQFL_OBJECT_TAG_ATTACHED_DATA_KEYS:
        if tag_key in obj__:
            obj__.pop(tag_key)

@undo_push(1)
def apply_asset(context):
    obj__ = context.active_object
    # apply all liquifeel modifiers
    for mod in [mod for mod in obj__.modifiers if is_lqfl_modifier(mod)]:
        bpy.ops.object.modifier_apply(modifier=mod.name)
    # Ca să nu se mai schimbe inputurile din shader (care ar fi fost comun)
    # atunci când modifici un alt obiect: duplicăm materialul obiectului căruia-i
    # dăm apply.
    bpy.ops.object.make_single_user(material=True)
    # remove object tag attached data
    maybe_remove_lqfl_object_tags(obj__)

@undo_push(1)
def apply_fill(context):
    obj__ = resolve_liquifeel_source_object(context.active_object)
    ctrl = resolve_assembly_controller_object(obj__)
    if ctrl is not None:
        obj__ = ctrl
    if obj__ is None:
        return
    select_and_set_active(context, obj__, deselect_all=True)
    separate_on = False
    try:
        separate_on = bool(getattr(
            obj__.hrdc_liquifeel_input_field_props.geometry,
            'separate_objects', False))
    except Exception:
        separate_on = False
    has_proxy = find_separate_liquid_object(obj__) is not None

    # Separate Objects: keep bottle + liquid as two real objects after apply.
    if separate_on or has_proxy:
        # Detach liquid first so bake_parent / transform_apply on the bottle
        # cannot corrupt the liquid world pose via the parent chain.
        liquid_obj = promote_separate_liquid_object(context, obj__)
        if liquid_obj is None:
            print('LIQUIFEEL: separate apply aborted — no liquid proxy to promote')
            return
        # Free the bottle from CAD/parent hierarchy so it can be moved freely.
        if obj__.parent is not None:
            try:
                bake_parent_transforms(context, obj__)
            except Exception as e:
                print(f'LIQUIFEEL: bake_parent_transforms before apply failed: {e}')
                mw = obj__.matrix_world.copy()
                obj__.parent = None
                obj__.matrix_world = mw
        try:
            obj__.hrdc_liquifeel_input_field_props.geometry.separate_objects = False
        except Exception:
            pass
        if any([is_mod_main_fill(mod) for mod in obj__.modifiers]):
            try:
                fill_mod = get_geonodes_mod_by_ng_name(obj__, FILL_NG_NAME)
                fill_mod.show_viewport = False
            except Exception:
                pass
            # Bake bottle-only geometry (Select Outer), then drop fill stack.
            try:
                bpy.ops.object.modifier_apply(
                    modifier=get_geonodes_mod_by_ng_name(
                        obj__, SELECT_OUTER_NG_NAME).name)
            except Exception:
                remove_geonode_mods_by_ng_name(obj__, SELECT_OUTER_NG_NAME)
            remove_geonode_mods_by_ng_name(obj__, FILL_NG_NAME)
            remove_geonode_mods_by_ng_name(obj__, HIDE_RECIPIENT_NG_NAME)
            for mod in [mod for mod in obj__.modifiers if is_shader_aux_modifier(
                    mod, obj__, 'fill')]:
                obj__.modifiers.remove(mod)
        marker = _lqfl_marker_get(obj__)
        if marker:
            marker = dict(marker)
            marker.pop('filled', None)
            marker.pop('fill_shading', None)
            marker.pop('separate_liquid', None)
            if 'assembly' in marker:
                marker['assembly'] = _normalize_assembly_dict(
                    marker.get('assembly'))
            if set(marker.keys()) <= {'version'}:
                maybe_remove_lqfl_object_tags(obj__)
            else:
                _lqfl_marker_set(obj__, marker)
        elif not(is_obj_library_slot_shaded__anylib(obj__)):
            maybe_remove_lqfl_object_tags(obj__)
        # Parent liquid under bottle so moving/rotating the bottle moves both.
        mw = liquid_obj.matrix_world.copy()
        liquid_obj.parent = obj__
        liquid_obj.matrix_world = mw
        # Bottle + liquid + assembly members in a fresh Outliner collection.
        assembly_members = list_assembly_member_objects(obj__)
        move_objects_to_new_collection(
            context,
            [obj__, liquid_obj] + assembly_members,
            f'{obj__.name}_LiquiFeel')
        return

    teardown_separate_liquid_object(context, obj__)
    try:
        obj__.hrdc_liquifeel_input_field_props.geometry.separate_objects = False
    except Exception:
        pass
    # apply all fill shader liquifeel modifiers
    if any([is_mod_main_fill(mod) for mod in obj__.modifiers]): # has fill mod
        # apply the fill modifier and it's auxiliary mods
        mod_ng_names_to_apply = [
            SELECT_OUTER_NG_NAME, FILL_NG_NAME, HIDE_RECIPIENT_NG_NAME]
        for ng_name in mod_ng_names_to_apply:
            bpy.ops.object.modifier_apply(
                modifier=get_geonodes_mod_by_ng_name(obj__, ng_name).name)
    # apply the material auxiliary modifiers
    for mod in [mod for mod in obj__.modifiers if is_shader_aux_modifier(mod, obj__, 'fill')]:
        bpy.ops.object.modifier_apply(modifier=mod.name)
    if not(is_obj_library_slot_shaded__anylib(obj__)):
        if has_assembly(obj__):
            _lqfl_strip_fill_keys_keep_assembly(obj__)
        else:
            if 'liquifeel' in obj__:
                obj__.pop('liquifeel')
            maybe_remove_lqfl_object_tags(obj__)

class ApplyAsset(bpy.types.Operator):
    bl_idname = 'liquifeel.apply_asset'
    bl_label = 'Apply'
    def execute(self, context):
        apply_asset(context)
        return {'FINISHED'}
registerable_classes.append(ApplyAsset)

class ApplyFill(bpy.types.Operator):
    bl_idname = 'liquifeel.apply_fill'
    bl_label = 'Apply Fill'
    def execute(self, context):
        apply_fill(context)
        return {'FINISHED'}
registerable_classes.append(ApplyFill)

def invoke_file_browser(operator_instance, context, event):
    context.window_manager.fileselect_add(
        operator_instance)

def load_user_defined_pattern(operator_instance, context):
    shading_modality_key = 'slot'
    fpath = pathlib.Path(operator_instance.filepath)
    fname = fpath.name
    img = maybe_load_image(fpath)
    img['liquifeel'] = {
        'version': bl_info['version'],
        'purpose': 'pattern',
        'means': 'user_defined'}
    img.use_fake_user = True
    img.pack
    ## Assigning the pattern automatically when the user adds loads a new, custom, pattern
    obj__ = context.active_object
    library_key, material_name = get_library_key_and_material_name(
        obj__, path_as_mapping=None, shading_modality_key=shading_modality_key)
    material = get_asset_material(
        obj__, shading_modality_key=shading_modality_key)
    node_names = 'PatternImage_UV; PatternImage_Box'
    nodes = [get_material_node(material, node_name.strip()) for node_name in node_names.split(';')]
    prop_key_chain = [
        'liquifeel_input_field_props', shading_modality_key, 'manual', 'user_pattern_texture']
    # prop_key_chain = [
    #     'liquifeel_input_field_props', shading_modality_key, 'manual', 'user_pattern_texture']
    prop_parent, prop_key = ref_ob_key_pair(material, prop_key_chain)
    # prop_parent, prop_key = ref_ob_key_pair(obj__, prop_key_chain)
    set_prop_value(
        prop_parent, prop_key, fname, 'imgtex')
    assign_image_to_nodes(obj__, nodes, img, fpath)

def hrdc_load_user_defined_pattern(operator_instance, context):
    shading_modality_key = 'slot'
    fpath = pathlib.Path(operator_instance.filepath)
    fname = fpath.name
    img = maybe_load_image(fpath)
    img['liquifeel'] = {
        'version': bl_info['version'],
        'purpose': 'pattern',
        'means': 'user_defined'}
    img.use_fake_user = True
    img.pack
    ## Assigning the pattern automatically when the user adds loads a new, custom, pattern
    obj__ = context.active_object
    library_key, material_name = hrdc_get_library_key_and_material_name(
        obj__, path_as_mapping=None, shading_modality_key=shading_modality_key)
    material = hrdc_get_asset_material(
        obj__, shading_modality_key=shading_modality_key)
    node_names = 'PatternImage_UV; PatternImage_Box'
    nodes = [get_material_node(material, node_name.strip()) for node_name in node_names.split(';')]
    prop_key_chain = [
        'hrdc_liquifeel_input_field_props', 'slot', 'solids', 'uber_glass', 'user_pattern_texture']
    # prop_key_chain = [
    #     'liquifeel_input_field_props', shading_modality_key, 'manual', 'user_pattern_texture']
    prop_parent, prop_key = ref_ob_key_pair(material, prop_key_chain)
    set_prop_value(
        prop_parent, prop_key, fname, 'imgtex')
    assign_image_to_nodes(obj__, nodes, img, fpath)

def hrdc_load_user_defined_roughness(operator_instance, context):
    shading_modality_key = 'slot'
    fpath = pathlib.Path(operator_instance.filepath)
    fname = fpath.name
    img = maybe_load_image(fpath)
    img['liquifeel'] = {
        'version': bl_info['version'],
        'purpose': 'roughness',
    'means': 'user_defined'}
    img.use_fake_user = True
    img.pack
    ## Assigning the roughness automatically when the user adds loads a new, custom, roughness
    obj__ = context.active_object
    library_key, material_name = hrdc_get_library_key_and_material_name(
        obj__, path_as_mapping=None, shading_modality_key=shading_modality_key)
    material = hrdc_get_asset_material(
        obj__, shading_modality_key=shading_modality_key)
    node_names = 'RoughnessImage_UV; RoughnessImage_Box'
    nodes = [get_material_node(material, node_name.strip()) for node_name in node_names.split(';')]
    prop_key_chain = [
        'hrdc_liquifeel_input_field_props', 'slot', 'solids', 'uber_glass', 'user_roughness_texture']
    prop_parent, prop_key = ref_ob_key_pair(material, prop_key_chain)
    set_prop_value(
        prop_parent, prop_key, fname, 'imgtex')
    assign_image_to_nodes(obj__, nodes, img, fpath)


class HRDC_LoadUserDefinedPattern(bpy.types.Operator):
    bl_idname = 'liquifeel.hrdc_load_user_defined_pattern'
    bl_label = 'Load User Defined Pattern'
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    def execute(self, context):
        hrdc_load_user_defined_pattern(self, context)
        return {'FINISHED'}
    def invoke(self, context, event):
        invoke_file_browser(self, context, event)
        return {'RUNNING_MODAL'}
registerable_classes.append(HRDC_LoadUserDefinedPattern)

class HRDC_LoadUserDefinedRoughness(bpy.types.Operator):
    bl_idname = 'liquifeel.hrdc_load_user_defined_roughness'
    bl_label = 'Hrdc Load User Defined Roughness'
    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    def execute(self, context):
        hrdc_load_user_defined_roughness(self, context)
        return {'FINISHED'}
    def invoke(self, context, event):
        invoke_file_browser(self, context, event)
        return {'RUNNING_MODAL'}
registerable_classes.append(HRDC_LoadUserDefinedRoughness)

## SHADING ---------------------

def get_material(library_key, material_name):
    material = maybe_append_material(
        material_name, FPATHS['blend_assets'])
    material['liquifeel'] = {
        'version': bl_info['version'],
        'name': material_name,
        'library': library_key}
    return material

## FILL SHADING ---

# I'm keeping all of these code blocks, as the tactic for redreawing
# render view after changing materials via goemetry nodes is a bit of
# hack / blender glitch, so we might have to change it in the future
# if blender changes.

# def render_view_update(context, obj__):
#     pass

# # This approach also does not work.
# def render_view_update(context, obj__):
#     context.view_layer.update()

# # This approach does not work...
# def render_view_update(context, obj__):
#     for area in context.screen.areas:
#         if area.type == 'VIEW_3D':
#             area.tag_redraw()

# # Still does not work
# def render_view_update(context, obj__):
#     obj__.data.update()

# # This approach works. i've used it in the function below defined.
# def render_view_update(context, obj__):
#     obj__.hide_viewport = True
#     obj__.hide_viewport = False

def update_obj_render_view(context, obj__):
    for mod in list(obj__.modifiers):
        if mod.type == 'NODES':
            modifier_viewport_update_trigger(context, mod)
    obj__.hide_viewport = True
    obj__.hide_viewport = False

def update_render_view(context):
    objs = set(context.selected_objects)
    objs.add(context.active_object)
    for obj__ in objs:
        update_obj_render_view(context, obj__)

# @undo_push(4)
def fill_shade(context, obj__, library_key, material_name):
    adjust_render_settings(context)
    # CLEAN THE SLATE
    clear_previous_material('fill', obj__)
    if 'liquifeel' not in obj__.keys():
        obj__['liquifeel'] = {
            'version': bl_info['version']
        }
    obj__['liquifeel']['fill_shading'] = {
        'library': library_key,
        'material_name': material_name
    }
    if library_key == 'scene':
        material = bpy.data.materials[material_name]
    else:
        material = get_material(library_key, material_name)
        # material = get_material(library_key, material_name).copy()
    set_geonode_mod_input(
        obj__, FILL_NG_NAME, 'Liquid Shader', 'material', material)
    if not(library_key == 'scene'):
        # remove_material_auxiliary_modifiers(obj__) This would probably remove the recipient mat aux mods.
        maybe_install_material_auxiliary_modifiers(obj__, library_key, material_name, 'fill')
        assign_default_values_to_target_inputs(obj__, material, 'fill', library_key, material_name)
    modifier_viewport_update_trigger(
        context,
        get_geonodes_mod_by_ng_name(obj__, FILL_NG_NAME))
    update_obj_render_view(context, obj__)
    push_liquid_material_to_proxy(obj__, material)
    schedule_separate_refresh(obj__, force=True)

# @undo_push(4)
def hrdc_fill_shade(context, obj__, library_key, material_name):
    adjust_render_settings(context)
    # CLEAN THE SLATE
    clear_previous_material('fill', obj__)
    if 'liquifeel' not in obj__.keys():
        obj__['liquifeel'] = {
            'version': bl_info['version']
        }
    obj__['liquifeel']['fill_shading'] = {
        'library': library_key,
        'material_name': material_name
    }
    if library_key == 'scene':
        material = bpy.data.materials[material_name]
    else:
        material = get_material(library_key, material_name)
        # material = get_material(library_key, material_name).copy()
    set_geonode_mod_input(
        obj__, FILL_NG_NAME, 'Liquid Shader', 'material', material)
    if not(library_key == 'scene'):
        # remove_material_auxiliary_modifiers(obj__) This would probably remove the recipient mat aux mods.
        maybe_install_material_auxiliary_modifiers(obj__, library_key, material_name, 'fill')
        # !!! I don't know if we need to assign defaults to inputs any
        # !!! more... it is to be discovered.
        hrdc_assign_default_values_to_target_inputs(obj__, material, 'fill', library_key, material_name)
    modifier_viewport_update_trigger(
        context,
        get_geonodes_mod_by_ng_name(obj__, FILL_NG_NAME))
    update_obj_render_view(context, obj__)
    push_liquid_material_to_proxy(obj__, material)
    schedule_separate_refresh(obj__, force=True)

class ShadeActiveObjectViaFill(bpy.types.Operator):
    bl_idname = 'liquifeel.shade_active_object_via_fill'
    bl_label = 'Shade Active Object Via Fill'
    def execute(self, context):
        obj__ = resolve_liquifeel_source_object(context.active_object)
        library_key, material_name = get_library_key_and_material_name(
            obj__, shading_modality_key='fill')
        fill_shade(context, obj__, library_key, material_name)
        return {'FINISHED'}
registerable_classes.append(ShadeActiveObjectViaFill)

class HRDC_ShadeActiveObjectViaFill(bpy.types.Operator):
    bl_idname = 'liquifeel.hrdc_shade_active_object_via_fill'
    bl_label = 'Shade Active Object Via Fill'
    def execute(self, context):
        obj__ = resolve_liquifeel_source_object(context.active_object)
        library_key, material_name = hrdc_get_library_key_and_material_name(
            obj__, shading_modality_key='fill')
        hrdc_fill_shade(context, obj__, library_key, material_name)
        return {'FINISHED'}
registerable_classes.append(HRDC_ShadeActiveObjectViaFill)

## SLOT SHADING ---

# def assign_material(obj__, material):
#     if obj__.data.materials:
#         obj__.data.materials[0] = material
#     else:
#         obj__.data.materials.append(material)

# This function handles both the assignment of the underlying inputs
# and of the properties
def assign_default_values_to_target_inputs(
        obj__, material, shading_modality_key, library_key, material_name):
    # For the old system (obsolete), few days later, i don't think it's obsolete.
    main_tab_key = 'shading'
    material_data = INPUT_FIELD_DATA[main_tab_key][library_key][material_name]
    for target_type_name, target_type_data in material_data.items():
        target_attachment_key = get_target_attachment_key[target_type_name]
        for group_name, group_data in target_type_data.items():
            for input_name, input_field_data in group_data.items():
                redux_input_data = REDUX_INPUT_DATA[
                    main_tab_key][target_attachment_key][input_name]
                # # We've taken out this chunk because there are no props to set default to any more.
                # declaration_modality_key = get_declaration_modality_key(redux_input_data)
                # prop_key_chain = get_prop_key_chain(
                #     redux_input_data, target_attachment_key, main_tab_key,
                #     declaration_modality_key, shading_modality_key)
                # if target_attachment_key == 'material_attached':
                #     top_level_prop_parent = material
                # else: # if target_attachment_key == 'object_attached':
                #     top_level_prop_parent = obj__
                # prop_parent, prop_key = ref_ob_key_pair(
                #     top_level_prop_parent, prop_key_chain)
                # # Setting the ui prop with the default val
                # if 'ui_prop_from_default' in input_field_data['setters'].keys():
                #     # debug_buffer.append(input_field_data) # DEBUG !!!
                #     input_field_data['setters']['ui_prop_from_default'](
                #         prop_parent)
                # Setting the underlying input with the default val
                if 'underlying_from_default' in input_field_data['setters']['per_shading_modality'].keys():
                    input_field_data['setters']['per_shading_modality']['underlying_from_default'](
                        prop_parent, obj__, material)
                # if target_attachment_key == 'material_attached':
                #     set_material_attached_input__at_setup(
                #         prop_parent, input_name,
                #         obj__, redux_input_data, material)
                # else: # target_attachment_key == 'object_attached':
                #     set_geonode_mod_input__at_prop_update(
                #         obj__, prop_parent, input_name, redux_input_data,
                #         target_attachment_key, shading_modality_key)

# # This function handles both the assignment of the underlying inputs
# # and of the propertiesx
# inputs_wo_default_setting_requirement = ['imgtex']
# def assign_default_values_to_target_inputs(
#         obj__, material, shading_modality_key, library_key, material_name):
#     # For the old system (obsolete), few days later, i don't think it's obsolete.
#     main_tab_key = 'shading'
#     material_data = INPUT_FIELD_DATA[main_tab_key][library_key][material_name]
#     for target_type_name, target_type_data in material_data.items():
#         target_attachment_key = get_target_attachment_key[target_type_name]
#         for group_name, group_data in target_type_data.items():
#             for input_name, input_field_data in group_data.items():
#                 if input_field_data['type'] not in inputs_wo_default_setting_requirement:
#                     redux_input_data = REDUX_INPUT_DATA[
#                         main_tab_key][target_attachment_key][input_name]
#                     # For constructing the prop key chain used to
#                     # access the ui property of the input in question.
#                     declaration_modality_key = get_declaration_modality_key(redux_input_data)
#                     prop_key_chain = get_prop_key_chain(
#                         redux_input_data, target_attachment_key, main_tab_key,
#                         declaration_modality_key, shading_modality_key)
#                     if target_attachment_key == 'material_attached':
#                         top_level_prop_parent = material
#                     else: # if target_attachment_key == 'object_attached':
#                         top_level_prop_parent = obj__
#                     prop_parent, prop_key = ref_ob_key_pair(
#                         top_level_prop_parent, prop_key_chain)
#                     # To assign defaults to the props, We need the
#                     # default value in the ui_input_type, not in the
#                     # underlying_input_type, This is what the code
#                     # below tries to accomplish.
#                     # IT DOES NOT WORK IN ALL SITUATIONS, SOMETHING
#                     # SMARTER (OR DUMBER) NEEDS TO BE DEVELOPED !!!
#                     # if 'ui_to_underlying_val_mapping' in input_field_data.keys():
#                         # default_val = next(
#                         #     filter(lambda key_val: key_val[1] == default_val,
#                         #            [(key, json_decoded_value_parser['bool'][val]) for key, val in input_field_data[
#                         #                'ui_to_underlying_val_mapping'].items()]))[0]
#                     default_val = None
#                     if declaration_modality_key == 'synthetic':
#                         # for the synthetically defined inputs, the
#                         # ui_input_type and the underlying_input_type
#                         # are both the same. There is nothing else to
#                         # do to derive it.
#                         default_val = input_field_data['underlying_input_default_val']
#                     elif redux_input_data['ui_input_type'] == 'enum' and isinstance(
#                             input_field_data['ui_to_underlying_val_mapping'], dict):
#                         default_val = invert_dict_mapping(input_field_data['ui_to_underlying_val_mapping'])[
#                             input_field_data['underlying_input_default_val']]
#                         print('ui_default_val:', default_val, '; underlying_default_val:', input_field_data['underlying_input_default_val'])
#                     # else:
#                     #     print(f'\nNot Synthetic, input_name: {input_name}')
#                     #     print(input_field_data)
#                     #     print()
#                     #     default_val = input_field_data['underlying_input_default_val']
#                     if default_val:
#                         # We set the prop to have our default value be
#                         # visible in the ui too, not just in the
#                         # underlying input.
#                         set_prop_value(
#                             prop_parent, prop_key, default_val, redux_input_data['ui_input_type'])
#                         if target_attachment_key == 'material_attached':
#                             # We set the underlying input in conformity
#                             # with the value we set in the property.
#                             # There is no need to pass a value to the
#                             # function, it shall be taken from the prop.
#                             set_material_attached_input__at_setup(
#                                 prop_parent, input_name,
#                                 obj__, redux_input_data, material
#                             )
#                         else: # target_attachment_key == 'object_attached':
#                             # Same here
#                             set_geonode_mod_input__at_prop_update(
#                                 obj__, prop_parent, input_name, redux_input_data,
#                                 target_attachment_key, shading_modality_key)
#                         ## ------------------------------------------------------------
#                         # prop_parent, prop_key = ref_input_field_property(
#                         #     obj__, shading_modality_key, library_key, material_name,
#                         #     target_type_name, group_name, input_name)
#                         # set_input__from_data(
#                         #     prop_parent, input_name,
#                         #     {
#                         #         'library': library_key,
#                         #         'material/func_name': material_name,
#                         #         'target_type': target_type_name,
#                         #         'group_name': group_name
#                         #     },
#                         #     input_field_data,
#                         #     shading_modality_key,
#                         #     obj=obj__, material=material)
#                 # if input_field_data['type'] == 'imgtex':
#                 #     # No need to set defaults in the case of image texture properties
#                 #     pass
#                 # else:
#                 #     prop_parent, prop_key = ref_input_field_property(
#                 #         obj__, shading_modality_key, library_key, material_name, target_type_name, group_name, input_name)
#                 #     set_input__from_data(
#                 #         prop_parent, input_name,
#                 #         {
#                 #             'library': library_key,
#                 #             'material/func_name': material_name,
#                 #             'target_type': target_type_name,
#                 #             'group_name': group_name
#                 #         },
#                 #         input_field_data,
#                 #         shading_modality_key,
#                 #         obj=obj__, material=material)
#     # # For the new system (execd):
#     # # object_attached_prop_hierarchy_karte !!!
#     # material_attached_prop_hierarchy_karte
#     # prop_root = 

def assign_geonode_inputs_to_default_vals(obj__, mat__, target_type_data):
    # print('assign_geonode_inputs_to_default_vals()')
    # print()
    for group_name, group_data in target_type_data.items():
        mod = get_geonodes_mod_by_ng_name(obj__, group_name)
        for input_name, input_field_data in group_data.items():
            if 'underlying_input_default_val' in input_field_data.keys():
                # print('    obj__', obj__)
                # print('    mat__', mat__)
                # print('    group_name', group_name)
                # print('    input_name', input_name)
                # print()
                set_geonode_mod_input_to_value(
                    mod,
                    get_geonodes_field_identifier(mod, input_name), # identifier
                    input_field_data['underlying_input_default_val'], # default value
                    input_field_data['underlying_input_type'])        # value type

def assign_shader_ng_inputs_to_default_vals(obj__, mat__, target_type_data):
    for group_name, group_data in target_type_data.items():
        ng__ = get_shader_ng_by_name(mat__, group_name)
        for input_name, input_field_data in group_data.items():
            if 'underlying_input_default_val' in input_field_data.keys():
                set_shader_ng_input_to_value(
                    ng__,
                    input_name,
                    input_field_data['underlying_input_default_val'], # default value
                    input_field_data['underlying_input_type']) # value type

# These functions below set default vals to unproxied inputs (inputs
# which don't have a property in between the ui and the underly) The
# Shader Node inputs (so far, only the image textures for pattern and
# roughness) are set manually in the hrdc_slot_shade function.

# target types: ['Shader NG', 'Shader Node', 'GeoNode']
inputs_default_setting_procedures__by_target_type = {
    'GeoNode': assign_geonode_inputs_to_default_vals,
    'Shader NG': assign_shader_ng_inputs_to_default_vals,
    # 'Shader Node': assign_shader_node_inputs_to_default_vals
}

def hrdc_assign_default_values_to_target_inputs(
        obj__, mat__, shading_modality_key, library_key, material_name):
    main_tab_key = 'shading'
    material_data = INPUT_FIELD_DATA[main_tab_key][library_key][material_name]
    for target_type_name, target_type_data in material_data.items():
        if target_type_name in inputs_default_setting_procedures__by_target_type.keys():
            # print()
            # print('hrdc_assign_default_values_to_target_inputs()')
            # print('    obj__', obj__)
            # print('    mat__', mat__)
            # print('    shading_modality_key', shading_modality_key)
            # print('    library_key', library_key)
            # print('    material_name', material_name)
            inputs_default_setting_procedures__by_target_type[target_type_name](
                obj__, mat__, target_type_data)
# # This function handles both the assignment of the underlying inputs
# # and of the properties
# def hrdc_assign_default_values_to_target_inputs(
#         obj__, material, shading_modality_key, library_key, material_name):
#     # For the old system (obsolete), few days later, i don't think it's obsolete.
#     main_tab_key = 'shading'
#     material_data = INPUT_FIELD_DATA[main_tab_key][library_key][material_name]
#     for target_type_name, target_type_data in material_data.items():
#         target_attachment_key = get_target_attachment_key[target_type_name]
#         for group_name, group_data in target_type_data.items():
#             for input_name, input_field_data in group_data.items():
#                 redux_input_data = REDUX_INPUT_DATA[
#                     main_tab_key][target_attachment_key][input_name]
#                 # # declaration_modality_key = get_declaration_modality_key(redux_input_data)
#                 # prop_key_chain = get_prop_key_chain(
#                 #     redux_input_data, target_attachment_key, main_tab_key,
#                 #     declaration_modality_key, shading_modality_key)
#                 # if target_attachment_key == 'material_attached':
#                 #     top_level_prop_parent = material
#                 # else: # if target_attachment_key == 'object_attached':
#                 #     top_level_prop_parent = obj__
#                 # prop_parent, prop_key = ref_ob_key_pair(
#                 #     top_level_prop_parent, prop_key_chain)
#                 # Setting the ui prop with the default val
#                 # if 'ui_prop_from_default' in input_field_data['setters'].keys():
#                 #     # debug_buffer.append(input_field_data) # DEBUG !!!
#                 #     input_field_data['setters']['ui_prop_from_default'](
#                 #         prop_parent)
#                 # Setting the underlying input with the default val
#                 if 'underlying_from_default' in input_field_data['setters']['per_shading_modality'].keys():
#                     input_field_data['setters']['per_shading_modality']['underlying_from_default'](
#                         prop_parent, obj__, material)
#                 # if target_attachment_key == 'material_attached':
#                 #     set_material_attached_input__at_setup(
#                 #         prop_parent, input_name,
#                 #         obj__, redux_input_data, material)
#                 # else: # target_attachment_key == 'object_attached':
#                 #     set_geonode_mod_input__at_prop_update(
#                 #         obj__, prop_parent, input_name, redux_input_data,
#                 #         target_attachment_key, shading_modality_key)
 
def clear_previous_material(shading_modality_key, obj__):
    # print(f'clear_previous_material({shading_modality_key}, obj__:{obj__.name})')
    # ID Property tagged data is used to the material name and the
    # library key of the material setup. The same information could be
    # obtained more expensively by analyzing the object (it's material
    # and it's modifier stack) and comparing them with the relevant
    # material data structures, but so far this approach seems
    # sufficient.
    if does_dict_have_key_path(
            obj__,
            ['liquifeel', f'{shading_modality_key}_shading', 'library']):
        # print('we can remove modifiers')
        prev_mat_library = obj__['liquifeel'][f'{shading_modality_key}_shading']['library']
        prev_material_name = obj__['liquifeel'][f'{shading_modality_key}_shading']['material_name']
        if shading_modality_key == 'slot':
            obj__.data.materials.clear() # make room for the new material
            # remove the previous lqfl material modifiers (if any)
        remove_material_auxiliary_modifiers(
            obj__, prev_mat_library, prev_material_name)


@undo_push(4)
def hrdc_slot_shade(context, obj__, library_key, material_name):
    # print('slot_shade(context, obj__, library_key, material_name)')
    # print(f'slot_shade(context, {obj__}, {library_key}, {material_name})')
    shading_modality_key = 'slot'
    adjust_render_settings(context)
    if 'liquifeel' not in obj__.keys():
        obj__['liquifeel'] = {
            'version': bl_info['version']
        }
    # CLEAN THE SLATE
    clear_previous_material(shading_modality_key, obj__)
    # OBJECT TAGGING
    obj__['liquifeel']['slot_shading'] = {
        'library': library_key,
        'material_name': material_name
    }
    # PATTERN PREREQUISITES:
    # solids (so far only UberGlass) have patterns and the pattern is dependent on discrimination between
    # the interior and the exterior of the glass.
    if library_key == 'solids':
        assign_select_outer_geonode_mod(obj__)
    # ASSIGN THE NEW MATERIAL
    if library_key == 'scene':
        material = bpy.data.materials[material_name]
        hrdc_set_asset_material(obj__, material, shading_modality_key)
    else:
        material = get_material(library_key, material_name)
        hrdc_set_asset_material(obj__, material, shading_modality_key)
        maybe_install_material_auxiliary_modifiers(obj__, library_key, material_name, shading_modality_key)
        # ASSIGN RECIPIENT PATTERNS
        if library_key == 'solids' and 'Uber Glass' in material_name:
            prop_key_chain = [
                'hrdc_liquifeel_input_field_props', shading_modality_key, 'solids', 'uber_glass']
            # prop_key_chain = ['hrdc_liquifeel_input_field_props', shading_modality_key, 'manual']
            # PATTERN
            pattern_img_key = getattr_rec(
                material, prop_key_chain + ['pattern_texture'])
            pattern_res_key = getattr_rec(
                material, prop_key_chain + ['pattern_texture_resolution'])
            pattern_node_names = 'PatternImage_UV; PatternImage_Box'
            pattern_nodes = [get_material_node(material, node_name.strip()) for node_name in pattern_node_names.split(';')]
            pattern_img_tex_fpath = FPATHS['recipient_patterns'][pattern_img_key][pattern_res_key]
            pattern_img = maybe_load_image(pattern_img_tex_fpath)
            assign_image_to_nodes(obj__, pattern_nodes, pattern_img, pattern_img_tex_fpath)
            # ROUGHNESS
            roughness_img_key = getattr_rec(
                material, prop_key_chain + ['roughness_texture'])
            roughness_res_key = getattr_rec(
                material, prop_key_chain + ['roughness_texture_resolution'])
            roughness_node_names = 'RoughnessImage_UV; RoughnessImage_Box'
            roughness_nodes = [get_material_node(material, node_name.strip()) for node_name in roughness_node_names.split(';')]
            roughness_img_tex_fpath = FPATHS['recipient_roughness_maps'][roughness_img_key][roughness_res_key]
            roughness_img = maybe_load_image(roughness_img_tex_fpath)
            assign_image_to_nodes(obj__, roughness_nodes, roughness_img, roughness_img_tex_fpath)
        # !!! We have eliminated most of the properties, So i don't
        # !!! think we'll be setting default values any more. it is to
        # !!! be seen if some property needing defaults pops up.
        # SET DEFAULT VALUES TO THE TARGET INPUTS (the intermediate
        # properties have them already set)
        hrdc_assign_default_values_to_target_inputs(
            obj__, material, shading_modality_key, library_key, material_name)

# class ShadeActiveObjectViaSlot(bpy.types.Operator):
#     bl_idname = 'liquifeel.shade_active_object_via_slot'
#     bl_label = 'Shade Active Object Via Slot'
#     def execute(self, context):
#         obj__ = context.active_object
#         library_key, material_name = get_library_key_and_material_name(
#             obj__, shading_modality_key='slot')
#         # library_key = getattr(obj__.liquifeel_field_inputs.slot_shading, 'library')
#         # material_name = getattr(obj__.liquifeel_field_inputs.slot_shading, f'library_{library_key}_material')
#         slot_shade(context, obj__, library_key, material_name)
#         return {'FINISHED'}
# registerable_classes.append(ShadeActiveObjectViaSlot)

class HRDC_ShadeActiveObjectViaSlot(bpy.types.Operator):
    bl_idname = 'liquifeel.hrdc_shade_active_object_via_slot'
    bl_label = 'Shade Active Object Via Slot'
    def execute(self, context):
        obj__ = context.active_object
        library_key, material_name = hrdc_get_library_key_and_material_name(
            obj__, shading_modality_key='slot')
        hrdc_slot_shade(context, obj__, library_key, material_name)
        return {'FINISHED'}
registerable_classes.append(HRDC_ShadeActiveObjectViaSlot)

# # This is not a priority, though it would be quite nice to have.
# class LinkSlotMaterialsFromActive(bpy.types.Operator):
#     bl_idname = f'liquifeel.link_slot_materials_from_active'
#     bl_label = 'Link Slot Materials From Active'
#     def execute(self, context):
#         active_obj = context.active_object
#         selected_objs = filter(lambda obj: not(obj == active_obj),
#                                context.selected_objects)
#         material = get_asset_material(active_obj, 'slot')

def make_active_asset_material_single_user(context, shading_modality_key):
    obj__ = context.active_object
    og_material = get_asset_material(obj__, shading_modality_key=shading_modality_key)
    mat = og_material.copy()
    set_asset_material(obj__, mat, shading_modality_key)
    update_obj_render_view(context, obj__)
    return mat

# This not currently a priority either, but it is more so than
# Linking from active
class MakeSlotMaterialSingleUser(bpy.types.Operator):
    bl_idname = 'liquifeel.make_slot_material_single_user'
    bl_label = 'Make Slot Material Single User'
    def execute(self, context):
        make_active_asset_material_single_user(context, 'slot')
        return {'FINISHED'}
registerable_classes.append(MakeSlotMaterialSingleUser)

# We want to be able to duplicate an asset and sepparate it's material
# while maintaining the values in the asset properties.
class MakeFillMaterialSingleUser(bpy.types.Operator):
    bl_idname = 'liquifeel.make_fill_material_single_user'
    bl_label = 'Make Fill Material Single User'
    def execute(self, context):
        make_active_asset_material_single_user(context, 'fill')
        # make_active_asset_fill_material_single_user(context)
        return {'FINISHED'}
registerable_classes.append(MakeFillMaterialSingleUser)

def switch_to_cycles_render_engine(context):
    # context.scene.render.engine = 'BLENDER_EEVEE'
    context.scene.render.engine = 'CYCLES'

class SwitchToCyclesRenderEngine(bpy.types.Operator):
    bl_idname = 'liquifeel.switch_to_cycles_render_engine'
    bl_label = 'Switch To Cycles Render Engine'
    def execute(self, context):
        switch_to_cycles_render_engine(context)
        return {'FINISHED'}
registerable_classes.append(SwitchToCyclesRenderEngine)

## SCENE UPDATE (DATA MIGRATION) ---------------------

# DATA ACQUISITION ---------

# MODIFIER INPUT VALUES ----

lqfl_input_socket_types = [
    'NodeSocketBool',
    'NodeSocketColor',
    'NodeSocketFloat',
    # 'NodeSocketGeometry',
    'NodeSocketInt',
    'NodeSocketMaterial',
    'NodeSocketMenu',
    'NodeSocketObject',
    'NodeSocketString'
]
socket_types_x_serialization_fs = {
    'NodeSocketColor': lambda v: tuple(v),
    'NodeSocketMaterial': lambda mat: mat['liquifeel']['name'],
    'NodeSocketObject': lambda obj__: obj__.name,
}
def extract_geonode_mod_input_vals(mod__):
    outbound = {}
    for socket in filter(
            lambda socket: socket.in_out == 'INPUT' and socket.socket_type in lqfl_input_socket_types,
            mod__.node_group.interface.items_tree.values()):
        outbound[socket.name] = {
            'socket_identifier': socket.identifier,
            'socket_name': socket.name,
            'socket_index': socket.index,
            'socket_type': socket.socket_type,
            'value': geonode_input_get(mod__, socket.identifier),
        }
        if hasattr(socket, 'subtype'):
            outbound['socket_subtype'] = socket.subtype
        if socket.socket_type in socket_types_x_serialization_fs.keys():
            outbound['serialized_value'] = socket_types_x_serialization_fs[
                socket.socket_type](geonode_input_get(mod__, socket.identifier))
    return outbound

def extract_geonode_mods_input_vals(obj__):
    outbound = {}
    for mod__ in filter(
            lambda mod__: mod__.type == 'NODES',
            obj__.modifiers[:]):
        outbound[mod__.node_group.name] = extract_geonode_mod_input_vals(mod__)
    return outbound

# DEV
class ExtractGeonodeModsInputVals(bpy.types.Operator):
    bl_idname = 'liquifeel.extract_geonode_mods_input_vals'
    bl_label = 'Extract Geonode Mods Input Vals'
    def execute(self, context):
        pprint(extract_geonode_mods_input_vals(context.active_object))
        return {'FINISHED'}
if DEV:
    registerable_classes.append(ExtractGeonodeModsInputVals)

# TAGS ----

def extract_legacy_asset_tag_data(obj__):
    outbound = {}
    if 'liquifeel' in obj__.keys():
        tag_data = obj__['liquifeel'].to_dict()
        outbound.update(tag_data)
    return outbound

# DEV
class ExtractMigrationTagData(bpy.types.Operator):
    bl_idname = 'liquifeel.extract_migration_tag_data'
    bl_label = 'Extract Migration Tag Data'
    def execute(self, context):
        pprint(extract_migration_tag_data(context.active_object))
        return {'FINISHED'}
if DEV:
    registerable_classes.append(ExtractMigrationTagData)    

# MODIFIER STACK SCHEMA ----

def extract_mod_stack_ng_name_list(obj__):
    return list(
        map(lambda mod__: mod__.node_group.name,
            filter(lambda mod__: mod__.type == 'NODES',
                   obj__.modifiers[:])))
            
# CONGLOMERATED DATA ACQUISITION ----

def get_slot_material_named_closest(obj__, aprox_mat_name):
    return sorted(
        obj__.data.materials[:],
        key=lambda mat__: levenshtein_distance(aprox_mat_name, mat__.name),
        reverse=False
    )[0]

def is_tagged_material_name_f(tag_mat_name):
    def f(mat__):
        if 'liquifeel' in mat__.keys():
            return mat__['liquifeel']['name'] == tag_mat_name
        return False
    return f

def maybe_get_slot_material_by_tagged_mat_name(obj__, tag_mat_name):
    try:
        return next(filter(
            is_tagged_material_name_f(tag_mat_name),
            obj__.data.materials[:]))
    except:
        return None

# def extract_legacy_asset_configuration_metadata(obj__):
#     outbound = {}
#     tagss = extract_legacy_asset_tag_data(obj__)
#     outbound

# TO BE CONTINUED

# CLEAR LEGACY ASSETS ---------



## UI --------------------------------------------------------------------------------

## UI DRAWING ---------------------

def is_asset_legacy_configured(ass__):
    try:
        if 'liquifeel' in ass__.keys():
            if 'version' in ass__['liquifeel'].keys():
                return tuple(ass__['liquifeel']['version'].to_list()) != tuple(bl_info['version'])
            else:
                return True
        return False
    except Exception:
        # unreadable/malformed marker - treat as legacy, the panel offers
        # a reset button to recover
        return True

def draw_legacy_asset_configuration_message(context, root_layout):
    root_layout.label(text="The currently selected asset has been")
    root_layout.label(text="configured with a legacy version of")
    root_layout.label(text="LiquiFeel. To access it's configuration please")
    root_layout.label(text="use the legacy LiquiFeel version used to")
    root_layout.label(text="create it originally.")
    apply_clear_row = root_layout.row()
    layout_operator_with_preview(
        apply_clear_row, 'liquifeel.clear_asset',
        text='Clear', icon_key='clear', fallback_icon='X')
    layout_operator_with_preview(
        apply_clear_row, 'liquifeel.apply_asset',
        text='Apply', icon_key='check', fallback_icon='CHECKMARK')
    root_layout.operator(
        'liquifeel.reset_active_object',
        text='Reset LiquiFeel on This Object',
        icon='FILE_REFRESH')


# obsolete, shall be removed in the future. we have a new system (execd).


def draw_spacing(root_layout):
    spacing_row = root_layout.row()
    spacing_row.scale_y = SPACING_H
    spacing_row.label(text='')

def draw_navigation_and_feedback(context, root_layout):
    tab_row = root_layout.row()
    tab_row.prop(
        context.scene.liquifeel_general_controls, 'main_tabs',
        expand=True, icon_only=False)
    # tab_cycle_row = root_layout.row()
    # split = tab_cycle_row.split(factor=LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR)
    # feedback_row = split.row()
    # # # DEACTIVATED FOR LACK OF URLS
    # # feedback_row.operator(
    # #     'liquifeel.launch_feedback_form',
    # #     text='',
    # #     icon_value=preview_data['ids']['icons']['like'],
    # # )
    # # feedback_row.operator(
    # #     'liquifeel.launch_feedback_form',
    # #     text='',
    # #     icon_value=preview_data['ids']['icons']['dislike']
    # # )
    # split.operator(
    #     'liquifeel.cycle_tabs',
    #     text=MAIN_TAB_NAMES[getattr(context.scene.liquifeel_general_controls, 'main_tabs')])
    draw_spacing(root_layout)

# def draw_navigation_and_feedback(context, root_layout):
#     tab_row = root_layout.row()
#     tab_row.label(
#         text='Feeling it?')
#     tab_row.prop(
#         context.scene.liquifeel_general_controls, 'main_tabs',
#         expand=True, icon_only=True)
#     tab_cycle_row = root_layout.row()
#     split = tab_cycle_row.split(factor=LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR)
#     feedback_row = split.row()
#     # # DEACTIVATED FOR LACK OF URLS
#     # feedback_row.operator(
#     #     'liquifeel.launch_feedback_form',
#     #     text='',
#     #     icon_value=preview_data['ids']['icons']['like'],
#     # )
#     # feedback_row.operator(
#     #     'liquifeel.launch_feedback_form',
#     #     text='',
#     #     icon_value=preview_data['ids']['icons']['dislike']
#     # )
#     split.operator(
#         'liquifeel.cycle_tabs',
#         text=MAIN_TAB_NAMES[getattr(context.scene.liquifeel_general_controls, 'main_tabs')])
#     draw_spacing(root_layout)


def draw_filled_geometry_ui(context, root_layout):
    # Liquid proxy → bottle; assembly members are handled in draw_geometry_ui
    # (Fill UI is only drawn when the bottle itself is active).
    obj__ = resolve_liquifeel_source_object(context.active_object)
    box = root_layout.box()
    prop_parent = obj__.hrdc_liquifeel_input_field_props.geometry
    box.prop(prop_parent, 'opening_shape', text='Opening Type')
    lip_threshold_row = box.row()
    if getattr(prop_parent, 'opening_shape') == 'irregular':
        draw_geonodes_mod_prop(
            obj__, SELECT_OUTER_NG_NAME, 'Lip Threshold', box)
    draw_geonodes_mod_prop(
        obj__, FILL_NG_NAME, 'Liquid Level', box, text='Liquid Amount')
    draw_geonodes_mod_prop(
        obj__, FILL_NG_NAME, 'Meniscus Type', box)
    draw_geonodes_mod_prop(
        obj__, FILL_NG_NAME, 'Meniscus Scale', box)
    draw_geonodes_mod_prop(
        obj__, FILL_NG_NAME, 'Wall Overlap', box)
    draw_geonodes_mod_prop(
        obj__, FILL_NG_NAME, 'Subdivision', box)
    draw_geonodes_mod_prop(
        obj__, FILL_NG_NAME, 'Seal', box, text='Seal Container')
    hrdc_draw_hide_controls(obj__, box)
    draw_clear_apply_ui(context, box)

# def draw_filled_geometry_ui(context, root_layout):
#     obj__ = context.active_object
#     if is_asset_legacy_configured(obj__):
#         draw_legacy_asset_configuration_message(context, root_layout)
#     else:
#         box = root_layout.box()
#         prop_parent = obj__.hrdc_liquifeel_input_field_props.geometry
#         box.prop(prop_parent, 'opening_shape', text='Opening Type')
#         lip_threshold_row = box.row()
#         if getattr(prop_parent, 'opening_shape') == 'irregular':
#             draw_geonodes_mod_prop(
#                 obj__, SELECT_OUTER_NG_NAME, 'Lip Threshold', box)
#         draw_geonodes_mod_prop(
#             obj__, FILL_NG_NAME, 'Liquid Level', box, text='Liquid Amount')
#         draw_geonodes_mod_prop(
#             obj__, FILL_NG_NAME, 'Meniscus Type', box)
#         draw_geonodes_mod_prop(
#             obj__, FILL_NG_NAME, 'Meniscus Scale', box)
#         draw_geonodes_mod_prop(
#             obj__, FILL_NG_NAME, 'Seal', box, text='Seal Container')
#         hrdc_draw_hide_controls(obj__, box)
#         draw_clear_apply_ui(context, box)

# def draw_filled_geometry_ui(context, root_layout):
#     obj__ = context.active_object
#     box = root_layout.box()
#     box.prop(obj__.liquifeel_field_inputs.fill, 'opening_shape')
#     lip_threshold_row = box.row()
#     if getattr(obj__.liquifeel_field_inputs.fill, 'opening_shape') == 'irregular':
#         lip_threshold_row.prop(obj__.liquifeel_field_inputs.fill, 'lip_threshold')
#     box.prop(obj__.liquifeel_field_inputs.fill, 'liquid_amount')
#     box.prop(obj__.liquifeel_field_inputs.fill, 'seal_container')
#     draw_hide_controls(obj__, box)
#     # draw_spacing(root_layout)

def draw_bake_parent_transforms_button(obj__, root_layout):
    """Only as a fallback for already-filled bottles that are still parented.

    New bottles use Use Active as Bottle / Bottle drop field, which bake in
    the same step — so we do not show a second button next to Set Bottle.
    """
    if obj__.parent is None:
        return
    if not is_obj_filled(obj__):
        return
    row = root_layout.row()
    row.scale_y = MID_H
    row.operator(
        'liquifeel.bake_parent_transforms',
        text='Unparent & Apply Transforms',
        icon='OBJECT_ORIGIN')

def draw_assembly_ui(context, root_layout, controller, active):
    """Drop targets: Bottle + part slots (drag from Outliner / eyedropper).

    Always drawn — even with no selection — so Outliner drag does not make
    the drop fields disappear mid-gesture.
    """
    box = root_layout.box()
    box.label(text='Assembly', icon='OBJECT_DATA')
    try:
        controls = context.scene.liquifeel_general_controls
    except Exception:
        box.label(text='Restart Blender to enable Assembly drop fields.')
        return

    box.label(text='Drag from Outliner into the fields below')
    box.prop(controls, 'assembly_bottle', text='Bottle')

    bottle = controls.assembly_bottle
    if bottle is not None and has_assembly(bottle):
        controller = bottle
    elif controller is not None and has_assembly(controller):
        pass
    else:
        remembered = get_scene_assembly_bottle(context)
        if remembered is not None:
            controller = remembered

    # Never mutate RNA during draw — schedule a deferred empty slot if needed.
    if len(controls.assembly_parts) == 0:
        schedule_assembly_drop_slot_seed()
        box.label(text='Preparing drop slot…')
    else:
        box.label(text='Other parts')
        for i, item in enumerate(controls.assembly_parts):
            row = box.row(align=True)
            row.prop(item, 'object', text='')
            op = row.operator(
                'liquifeel.assembly_slot_remove', text='', icon='X')
            op.index = i

    row = box.row(align=True)
    row.operator('liquifeel.assembly_slot_add', text='Add Slot', icon='ADD')
    row.operator(
        'liquifeel.assembly_add_selected',
        text='Add Selected',
        icon='IMPORT')

    if controller is not None and has_assembly(controller):
        n_linked = len(list_assembly_member_objects(controller))
        box.label(text=f'Linked: {n_linked}')
        hide_on = bool(controls.assembly_hide_extras)
        hide_row = box.row()
        hide_row.scale_y = MID_H
        hide_row.alert = hide_on
        hide_row.operator(
            'liquifeel.assembly_toggle_hide_extras',
            text='Show Extras' if hide_on else 'Hide Extras',
            icon='HIDE_OFF' if hide_on else 'HIDE_ON',
            depress=hide_on)
        box.operator('liquifeel.assembly_clear', text='Clear Assembly')
    else:
        can_set = (
            active is not None
            and active.type == 'MESH'
            and getattr(active, 'mode', None) == 'OBJECT'
            and not is_liquid_proxy_object(active)
            and not is_assembly_member_object(active))
        if can_set:
            row = box.row()
            row.scale_y = MID_H
            row.operator(
                'liquifeel.assembly_set_bottle',
                text='Use Active as Bottle',
                icon='OBJECT_ORIGIN')

def draw_geometry_ui(context, root_layout):
    try:
        _draw_geometry_ui_impl(context, root_layout)
    except Exception as exc:
        import traceback
        traceback.print_exc()
        root_layout.label(text=f'LiquiFeel Geometry UI error: {exc}', icon='ERROR')
        root_layout.label(text=f'Build: {ADDON_BUILD_TAG}')

def _draw_geometry_ui_impl(context, root_layout):
    active = context.active_object if is_active_selected_ob(context) else None
    controller = None
    if active is not None:
        controller = resolve_assembly_controller_object(active)
    if controller is None:
        controller = get_scene_assembly_bottle(context)

    # Assembly drop fields must stay visible during Outliner drag (selection
    # often clears / changes mid-gesture and used to wipe this whole panel).
    draw_assembly_ui(context, root_layout, controller, active)

    if active is None:
        root_layout.label(
            text='Select the bottle mesh to edit Fill / liquid.')
        return

    # Prop updates use context.active_object — only edit Fill on the bottle.
    fill_controller = resolve_assembly_controller_object(active)
    if fill_controller is not None and active != fill_controller:
        root_layout.label(text='Select the bottle to edit Fill / liquid.')
        return
    obj__ = resolve_liquifeel_source_object(active)
    if obj__ is None:
        root_layout.label(text='No fill target object.')
        return
    if obj__.mode == 'OBJECT':
        if has_obj_single_mesh_island(obj__):
            if is_asset_legacy_configured(obj__):
                draw_legacy_asset_configuration_message(context, root_layout)
            else:
                draw_bake_parent_transforms_button(obj__, root_layout)
                if is_obj_filled(obj__):
                    draw_filled_geometry_ui(context, root_layout)
                else:
                    fill_it_row = root_layout.row()
                    fill_it_row.scale_y = LRG_H
                    layout_operator_with_preview(
                        fill_it_row,
                        'liquifeel.fill_active_object',
                        text='Fill Active Object',
                        icon_key='geometry',
                        fallback_icon='MESH_DATA',
                    )
                    root_layout.operator(
                        'liquifeel.check_active_geometry',
                        text='Check Geometry',
                        icon='VIEWZOOM')
        else:
            root_layout.label(
                text='This object is not composed of a single mesh island.')
            root_layout.label(
                text='Please separate the part that you want to fill and')
            root_layout.label(
                text='make sure it has thickness and a suitable opening')
            draw_bake_parent_transforms_button(obj__, root_layout)
            check_row = root_layout.row()
            check_row.scale_y = MID_H
            check_row.operator(
                'liquifeel.check_active_geometry',
                text='Check Geometry',
                icon='VIEWZOOM')
    else:
        root_layout.label(text='Please enter Object Mode.')
# def draw_geometry_ui(context, root_layout):
#     if is_active_selected_ob(context):
#         obj__ = context.active_object
#         if obj__.mode == 'OBJECT':
#             if is_obj_filled(obj__):
#                 draw_filled_geometry_ui(context, root_layout)
#             else:
#                 fill_it_row = root_layout.row()
#                 fill_it_row.scale_y = LRG_H
#                 fill_it_row.operator(
#                     'liquifeel.fill_active_object',
#                     text='Fill active',
#                     icon_value=preview_data['ids']['icons']['geometry'],
#                 )
#         else:
#             root_layout.label(text='Please enter Object Mode.')
#     else:
#         root_layout.label(
#             text='Please select an object that has one mesh island!')


        # root_layout.prop(
        #     *ref_input_field_property(
        #         obj__, shading_modality_key, library_key, mat_name, target_type, group_name, input_name),
        #     slider=slider)


# def get_prop_key_chain(
#         redux_input_data, target_attachment_key, main_tab_key,
#         declaration_modality_key, shading_modality_key):
#     # The two property hierarchies (material attached and object
#     # attached) do not have the same structure. In obtaining the
#     # property hierarchy key chain (path) i'm taking advantaage of
#     # their sole difference. This is a brittle piece of code, if we
#     # changed the hierarchy structure, it would cease to work.
#     if target_attachment_key == 'material_attached':
#         hierarchy_inconsistent_key = shading_modality_key
#     else: # target_attachment_key == 'object_attached':
#         hierarchy_inconsistent_key = main_tab_key
#     prop_key_chain = [
#         'liquifeel_input_field_props',
#         hierarchy_inconsistent_key, declaration_modality_key,
#         redux_input_data['prop_key']]
#     return prop_key_chain


        # root_layout.prop(
        #     *ref_ob_key_pair(
        #         top_level_prop_parent, prop_key_chain),
        #     slider=slider)




pattern_ui_input_order = [
    'Pattern',
    'Pattern Texture; Pattern Texture Resolution; Pattern Library; User Pattern Texture',
    'Mapping',
    'UV Name',
    'Use Vertex Group',
    'Vertex Group',
    'Lip Threshold',
    'Patttern Extrusion',
    'Upper Limit',
    'Lower Limit',
    'Pattern Falloff',
    'Pattern Tiling'
]
outside_pattern_ui_input_order = len(pattern_ui_input_order) + 1
def pattern_ui_input_order_sorting_metric(extended_input_data):
    ui_input_name = extended_input_data['input_key']
    if ui_input_name in pattern_ui_input_order:
        return pattern_ui_input_order.index(ui_input_name)
    else:
        return outside_pattern_ui_input_order




def hrdc_draw_library_selector(obj__, context, root_layout, shading_modality_key):
    row = root_layout.row()
    split = row.split(factor=LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR)
    split.label(text='Shader Library')
    prop_key_chain = [
        'hrdc_liquifeel_input_field_props', 'shading', shading_modality_key, 'library']
    # prop_key_chain = [
    #     'liquifeel_input_field_props',
    #     'shading', shading_modality_key, 'manual', 'material_selector', 'library']
    prop_parent, prop_key = ref_ob_key_pair(obj__, prop_key_chain)
    split.prop(prop_parent, prop_key, text='')


def hrdc_draw_hide_controls(obj__, root_layout):
    prop_parent = obj__.hrdc_liquifeel_input_field_props.geometry
    hide_recipient_row = root_layout.row()
    hide_recipient_row.enabled = not(
        getattr(prop_parent, 'hide_liquid'))
    hide_liquid_row = root_layout.row()
    hide_liquid_row.enabled = not(
        getattr(prop_parent, 'hide_recipient'))
    hide_recipient_row.prop(
        prop_parent, 'hide_recipient')
    hide_liquid_row.prop(
        prop_parent, 'hide_liquid')
    root_layout.prop(prop_parent, 'separate_objects')


def hrdc_draw_scene_shading_ui(obj__, shading_modality_key, context, root_layout):
    hrdc_draw_library_selector(obj__, context, root_layout, shading_modality_key)
    row = root_layout.row()
    split_row = row.split(
        factor=LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR)
    split_row.label(text='Scene materials:')
    prop_key_chain = [
        'hrdc_liquifeel_input_field_props', 'shading',
        shading_modality_key, 'scene_material']
    # prop_key_chain = [
    #     'liquifeel_input_field_props', 'shading', shading_modality_key,
    #     'manual', 'material_selector', 'scene_material']
    prop_parent, prop_key = ref_ob_key_pair(
        obj__, prop_key_chain)
    split_row.prop(
        prop_parent, prop_key, text='')
    if is_obj_filled(obj__):
        hrdc_draw_hide_controls(obj__, root_layout)
        draw_liquid_amount_slider(obj__, root_layout)
        # root_layout.prop(
        #     obj__.liquifeel_input_field_props.geometry.synthetic, 'liquid_amount')

    # draw_spacing(root_layout)

def draw_shader_ng_prop(mat__, ng_name, input_name, root_layout):
    root_layout.prop(
        get_shader_ng_input_from_mat(mat__, ng_name, input_name),
        'default_value',
        text=input_name)

def draw_geonodes_mod_prop(obj__, ng_name, input_name, root_layout, text=None):
    if not text:
        text=input_name
    # A broken fill (missing modifier / dangling node group) must not crash
    # the whole panel - show a warning row instead, the panel stays usable.
    try:
        mod__ = get_geonodes_mod_by_ng_name(obj__, ng_name)
        input_identifier = get_geonodes_field_identifier(mod__, input_name)
    except (StopIteration, RuntimeError, KeyError, AttributeError):
        warn_row = root_layout.row()
        warn_row.alert = True
        warn_row.label(text=f'{text}: unavailable (broken fill)', icon='ERROR')
        return
    if GEONODE_INPUTS_VIA_PROPERTIES:
        root_layout.prop(
            get_geonode_mod_input_prop(mod__, input_identifier), 'value', text=text)
    else:
        root_layout.prop(mod__, f'["{input_identifier}"]', text=text)

def get_geonodes_mod_input_val(obj__, ng_name, input_name):
    mod__ = get_geonodes_mod_by_ng_name(obj__, ng_name)
    input_identifier = get_geonodes_field_identifier(mod__, input_name)
    return geonode_input_get(mod__, input_identifier)

# --------------------------------
# SOLIDS

mapping_type_menu_val_decoder = ['UV', 'Box']
# oooooooooooooooo
# Uber Glass : uber_glass
def draw_uber_glass_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Glass : glass
    glass_box = root_layout.box()
    glass_box.label(text='Glass')
    # iiii : Shader : PatternedGlass NG : Glass Color : glass_color
    draw_shader_ng_prop(mat__, 'PatternedGlass', 'Glass Color', glass_box)
    # iiii : Shader : PatternedGlass NG : GlassDensity : glassdensity
    draw_shader_ng_prop(mat__, 'PatternedGlass', 'GlassDensity', glass_box)
    # iiii : GeoNode : GlassUtils : IoR : ior
    draw_geonodes_mod_prop(obj__, 'GlassUtils', 'IoR', glass_box)
    # iiii : GeoNode : GlassUtils : Rim Darkness : rim_darkness
    draw_geonodes_mod_prop(obj__, 'GlassUtils', 'Rim Darkness', glass_box)
    # iiii : GeoNode : GlassUtils : Dispersion : dispersion
    draw_geonodes_mod_prop(obj__, 'GlassUtils', 'Dispersion', glass_box)
    # iiii : GeoNode : GlassUtils : Glass Roughness : glass_roughness
    if not get_geonodes_mod_input_val(obj__, 'RoughnessUtils', 'Custom Roughness Map'):
        draw_geonodes_mod_prop(obj__, 'GlassUtils', 'Glass Roughness', glass_box)
    # ++++++++
    # Pattern : pattern
    pattern_box = root_layout.box()
    # # I don't think we need the label, as we have the checkbox and it
    # # seems redundant to have Pattern twice.
    # pattern_box.label(text='Pattern')
    # iiii : GeoNode : PatternUtils : Pattern : pattern
    draw_geonodes_mod_prop(obj__, 'PatternUtils', 'Pattern', pattern_box)
    # The rest of the inputs in this box will only be displayed if the
    # pattern input is checked True.
    # # This one below is a custom job, it's non-standard.
    # iiii : Shader : PatternImage_UV; PatternImage_Box Node : Pattern Texture; Pattern Texture Resolution; Pattern Library; User Pattern Texture : ['pattern_texture', 'pattern_texture_resolution', 'pattern_library', 'user_pattern_texture']
    if get_geonodes_mod_input_val(obj__, 'PatternUtils', 'Pattern'):
        prop_parent_key_chain = ['hrdc_liquifeel_input_field_props', 'slot', 'solids', 'uber_glass']
        # Drawing the library selector
        row = pattern_box.row()
        # split_row = row.split(
        #     factor=LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR)
        split_row = row.split(
            factor=0.3)
        split_row.label(text='Pattern Lixbrary')
        split_row.prop(
            *ref_ob_key_pair(
                mat__,
                prop_parent_key_chain + ['pattern_library']),
            text='')
        # Finding out what library has been selected.
        pattern_lib_key = getattr_rec(mat__, prop_parent_key_chain + ['pattern_library'])
        # Identifying what is the prop holding our image texture key
        pattern_selector_prop_key = {
            'user_defined': 'user_pattern_texture',
            'liquifeel': 'pattern_texture'
        }[pattern_lib_key]
        # We draw the template icon view only if we are outside of the
        # case in which user defined pattern mode is selected and none are
        # present.
        # if not(pattern_lib_key == 'user_defined' and not(are_user_defined_patterns_present())):
        # if not(pattern_lib_key == 'user_defined' and not(are_user_defined_maps_present('roughness'))):
        if not(pattern_lib_key == 'user_defined' and not(are_user_defined_maps_present('pattern'))):
            pattern_box.template_icon_view(
                *ref_ob_key_pair(
                    mat__, prop_parent_key_chain + [pattern_selector_prop_key]),
                show_labels=True, scale=UI_THUMB_SCALE, scale_popup=POPUP_THUMB_SCALE)
        # Then we decide if we display the resoluton selector or not. If
        # we are in user defined mode, we don't need it.
        if not(pattern_lib_key == 'user_defined'):
            # DROP DOWN
            pattern_box.prop(
                *ref_ob_key_pair(
                    mat__, prop_parent_key_chain + ['pattern_texture_resolution']))
        # If we are in user defined mode, we need to be able to load new
        # patterns though. hence the operator provided below.
        else:
            pattern_box.operator('liquifeel.hrdc_load_user_defined_pattern', text='Load custom pattern image')
        # # iiii : GeoNode : PatternUtils !!! : Mapping : mapping
        # # DROP DOWN
        # row = pattern_box.row()
        # split_row = row.split(
        #     factor=LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR)
        # split_row.label(text='Mapping')
        # split_row.prop(
        #     *ref_ob_key_pair(
        #         mat__, prop_parent_key_chain + ['pattern_mapping']),
        #     text='')
        draw_geonodes_mod_prop(obj__, 'PatternUtils', 'Mapping Type', pattern_box)
        # iiii : GeoNode : PatternUtils : UV Name : uv_name
        # if getattr_rec(mat__, prop_parent_key_chain + ['pattern_mapping']) == 'UV': # is mapping set to uv?
        # if mapping_type_menu_val_decoder[
        #         get_geonodes_mod_input_val(obj__, 'PatternUtils', 'Mapping Type')] == 'UV': # is mapping set to uv?
        if get_geonodes_mod_input_val(obj__, 'PatternUtils', 'Mapping Type') == 'UV': # is mapping set to uv?
            # DROP DOWN
            row = pattern_box.row()
            split_row = row.split(
                factor=0.4)
                # factor=LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR)
            split_row.label(text='UV Map')
            split_row.prop(
                *ref_ob_key_pair(
                    mat__, prop_parent_key_chain + ['pattern_uv_name']),
                text='')
        # draw_geonodes_mod_prop(obj__, 'PatternUtils', 'UV Name', pattern_box)
        # iiii : GeoNode : PatternUtils : Use Vertex Group : use_vertex_group
        draw_geonodes_mod_prop(obj__, 'PatternUtils', 'Use Vertex Group', pattern_box)
        # iiii : GeoNode : PatternUtils : Vertex Group : vertex_group
        if get_geonodes_mod_input_val(obj__, 'PatternUtils', 'Use Vertex Group'): # is_vertex_group_on
            row = pattern_box.row()
            split_row = row.split(
                factor=0.4)
            split_row.label(text='Vertex Group')
            split_row.prop(
                *ref_ob_key_pair(
                    mat__, prop_parent_key_chain + ['pattern_vertex_group']),
                text='')        
        # draw_geonodes_mod_prop(obj__, 'PatternUtils', 'Vertex Group', pattern_box)
        # iiii : GeoNode : LiquiFeel_Select Outer : Lip Threshold : lip_threshold
        draw_geonodes_mod_prop(obj__, 'LiquiFeel_Select Outer', 'Lip Threshold', pattern_box)
        # iiii : GeoNode : GlassUtils : Patttern Extrusion : patttern_extrusion
        draw_geonodes_mod_prop(obj__, 'GlassUtils', 'Patttern Extrusion', pattern_box, text='Pattern Height')
        # iiii : GeoNode : PatternUtils : Upper Limit : upper_limit
        draw_geonodes_mod_prop(obj__, 'PatternUtils', 'Upper Limit', pattern_box)
        # iiii : GeoNode : PatternUtils : Lower Limit : lower_limit
        draw_geonodes_mod_prop(obj__, 'PatternUtils', 'Lower Limit', pattern_box)
        # iiii : GeoNode : PatternUtils : Pattern Falloff : pattern_falloff
        draw_geonodes_mod_prop(obj__, 'PatternUtils', 'Pattern Falloff', pattern_box)
        # iiii : GeoNode : GlassUtils : Pattern Tiling : pattern_size
        draw_geonodes_mod_prop(obj__, 'GlassUtils', 'Pattern Tiling', pattern_box)
    # ++++++++
    # Roughness Map : roughness_map
    roughness_map_box = root_layout.box()    
    # iiii : GeoNode : RoughnessUtils : Custom Roughness Map : custom_roughness_map
    draw_geonodes_mod_prop(obj__, 'RoughnessUtils', 'Custom Roughness Map', roughness_map_box)
    # # This one below is a custom job, it's non-standard.
    # iiii : Shader : PatternImage_UV; PatternImage_Box Node : Pattern Texture; Pattern Texture Resolution; Pattern Library; User Pattern Texture : ['pattern_texture', 'pattern_texture_resolution', 'pattern_library', 'user_pattern_texture']
    if get_geonodes_mod_input_val(obj__, 'RoughnessUtils', 'Custom Roughness Map'):
        prop_parent_key_chain = ['hrdc_liquifeel_input_field_props', 'slot', 'solids', 'uber_glass']
        # Drawing the library selector
        row = roughness_map_box.row()
        # split_row = row.split(
        #     factor=LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR)
        split_row = row.split(
            factor=0.3)
        split_row.label(text='Roughness Library')
        split_row.prop(
            *ref_ob_key_pair(
                mat__,
                prop_parent_key_chain + ['roughness_library']),
            text='')
        # Finding out what library has been selected.
        roughness_lib_key = getattr_rec(mat__, prop_parent_key_chain + ['roughness_library'])
        # Identifying what is the prop holding our image texture key
        roughness_selector_prop_key = {
            'user_defined': 'user_roughness_texture',
            'liquifeel': 'roughness_texture'
        }[roughness_lib_key]
        # We draw the template icon view only if we are outside of the
        # case in which user defined roughness mode is selected and none are
        # present.
        # if not(roughness_lib_key == 'user_defined' and not(are_user_defined_roughnesss_present())):
        if not(roughness_lib_key == 'user_defined' and not(are_user_defined_maps_present('roughness'))):
            roughness_map_box.template_icon_view(
                *ref_ob_key_pair(
                    mat__, prop_parent_key_chain + [roughness_selector_prop_key]),
                show_labels=True, scale=UI_THUMB_SCALE, scale_popup=POPUP_THUMB_SCALE)
        # Then we decide if we display the resoluton selector or not. If
        # we are in user defined mode, we don't need it.
        if not(roughness_lib_key == 'user_defined'):
            # DROP DOWN
            roughness_map_box.prop(
                *ref_ob_key_pair(
                    mat__, prop_parent_key_chain + ['roughness_texture_resolution']))
        # If we are in user defined mode, we need to be able to load new
        # roughnesss though. hence the operator provided below.
        else:
            roughness_map_box.operator('liquifeel.hrdc_load_user_defined_roughness', text='Load custom roughness image')
        # # iiii : GeoNode : RoughnessUtils !!! : Mapping : mapping
        # # DROP DOWN
        # row = roughness_map_box.row()
        # split_row = row.split(
        #     factor=LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR)
        # split_row.label(text='Mapping')
        # split_row.prop(
        #     *ref_ob_key_pair(
        #         mat__, prop_parent_key_chain + ['roughness_mapping']),
        #     text='')
        # iiii : GeoNode : RoughnessUtils : UV Name : uv_name
        draw_geonodes_mod_prop(obj__, 'RoughnessUtils', 'Mapping Type', roughness_map_box)
        # if getattr_rec(mat__, prop_parent_key_chain + ['roughness_mapping']) == 'UV': # is mapping set to uv?
        # if mapping_type_menu_val_decoder[
        #         get_geonodes_mod_input_val(obj__, 'RoughnessUtils', 'Mapping Type')] == 'UV': # is mapping set to uv?
        if get_geonodes_mod_input_val(obj__, 'RoughnessUtils', 'Mapping Type') == 'UV': # is mapping set to uv?
            # DROP DOWN
            row = roughness_map_box.row()
            split_row = row.split(
                factor=0.4)
                # factor=LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR)
            split_row.label(text='UV Map')
            split_row.prop(
                *ref_ob_key_pair(
                    mat__, prop_parent_key_chain + ['roughness_uv_name']),
                text='')
        # draw_geonodes_mod_prop(obj__, 'RoughnessUtils', 'UV Name', roughness_map_box)
        # iiii : GeoNode : RoughnessUtils : Use Vertex Group : use_vertex_group
        draw_geonodes_mod_prop(obj__, 'RoughnessUtils', 'Use Vertex Group', roughness_map_box)
        # iiii : GeoNode : RoughnessUtils : Vertex Group : vertex_group
        if get_geonodes_mod_input_val(obj__, 'RoughnessUtils', 'Use Vertex Group'): # is_vertex_group_on
            row = roughness_map_box.row()
            split_row = row.split(
                factor=0.4)
            split_row.label(text='Vertex Group')
            split_row.prop(
                *ref_ob_key_pair(
                    mat__, prop_parent_key_chain + ['roughness_vertex_group']),
                text='')
        # iiii : GeoNode : RoughnessUtils : Upper Limit : upper_limit
        draw_geonodes_mod_prop(obj__, 'RoughnessUtils', 'Upper Limit', roughness_map_box)
        # iiii : GeoNode : RoughnessUtils : Lower Limit : lower_limit
        draw_geonodes_mod_prop(obj__, 'RoughnessUtils', 'Lower Limit', roughness_map_box)
        # iiii : GeoNode : RoughnessUtils : Pattern Falloff : pattern_falloff
        draw_geonodes_mod_prop(obj__, 'RoughnessUtils', 'Pattern Falloff', roughness_map_box)
        # iiii : GeoNode : RoughnessUtils : Tiling : tiling
        draw_geonodes_mod_prop(obj__, 'RoughnessUtils', 'Tiling', roughness_map_box)
        # iiii : GeoNode : RoughnessUtils : Roughness Strength : roughness_strength
        draw_geonodes_mod_prop(obj__, 'RoughnessUtils', 'Roughness Strength', roughness_map_box)
        # iiii : GeoNode : RoughnessUtils : Roughness Offset : roughness_offset
        draw_geonodes_mod_prop(obj__, 'RoughnessUtils', 'Roughness Offset', roughness_map_box)
        # iiii : GeoNode : RoughnessUtils : Invert Roughness : invert_roughnes
        draw_geonodes_mod_prop(obj__, 'RoughnessUtils', 'Invert Roughness', roughness_map_box)

# oooooooooooooooo
# PET : pet
def draw_pet_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Controls : controls
    controls_box = root_layout.box()
    controls_box.label(text='Controls')
    # iiii : Shader : PET NG : Color : color
    draw_shader_ng_prop(mat__, 'PET', 'Color', controls_box)
    # iiii : Shader : PET NG : IOR : ior
    draw_shader_ng_prop(mat__, 'PET', 'IOR', controls_box)
    # iiii : Shader : PET NG : Roughness : roughness
    draw_shader_ng_prop(mat__, 'PET', 'Roughness', controls_box)
    # iiii : Shader : PET NG : Color Intensity : color_intensity
    draw_shader_ng_prop(mat__, 'PET', 'Color Intensity', controls_box)
    # iiii : Shader : PET NG : Cloudiness : cloudiness
    draw_shader_ng_prop(mat__, 'PET', 'Cloudiness', controls_box)

# oooooooooooooooo
# Brown Bottle Glass : brown_bottle_glass
def draw_brown_bottle_glass_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Controls : controls
    controls_box = root_layout.box()
    controls_box.label(text='Controls')
    # iiii : Shader : Brown Bottle NG : Color Brightness : color_brightness
    draw_shader_ng_prop(mat__, 'Brown Bottle', 'Color Brightness', controls_box)

# oooooooooooooooo
# Green Bottle Glass : green_bottle_glass
def draw_green_bottle_glass_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Controls : controls
    controls_box = root_layout.box()
    controls_box.label(text='Controls')
    # iiii : Shader : Green Bottle Glass NG : Color Brightness : color_brightness
    draw_shader_ng_prop(mat__, 'Green Bottle Glass', 'Color Brightness', controls_box)

# --------------------------------
# LIQUIDS

# oooooooooooooooo
# UberLiquid : uberliquid
def draw_uberliquid_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : UberLiquid_Shader NG : Liquid Color : liquid_color
    draw_shader_ng_prop(mat__, 'UberLiquid_Shader', 'Liquid Color', liquid_box)
    # iiii : GeoNode : UberLiquid : Transmission : transmission
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Transmission', liquid_box)
    # iiii : Shader : UberLiquid_Shader NG : Intensity : intensity
    draw_shader_ng_prop(mat__, 'UberLiquid_Shader', 'Intensity', liquid_box)
    # iiii : Shader : UberLiquid_Shader NG : Turbidity : turbidity
    draw_shader_ng_prop(mat__, 'UberLiquid_Shader', 'Turbidity', liquid_box)
    # iiii : Shader : UberLiquid_Shader NG : Subsurface : subsurface
    draw_shader_ng_prop(mat__, 'UberLiquid_Shader', 'Subsurface', liquid_box)
    # iiii : Shader : UberLiquid_Shader NG : Subsurface Radius : subsurface_radius
    draw_shader_ng_prop(mat__, 'UberLiquid_Shader', 'Subsurface Radius', liquid_box)
    # iiii : Shader : UberLiquid_Shader NG : Particles Opacity : particles_opacity
    draw_shader_ng_prop(mat__, 'UberLiquid_Shader', 'Particles Opacity', liquid_box)
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : UberLiquid : Foam : foam
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Foam', foam_box)
    # iiii : GeoNode : UberLiquid : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Foam Amount', foam_box)
    # iiii : GeoNode : UberLiquid : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Foam Center Distribution', foam_box)
    # iiii : Shader : UberLiquid_Shader NG : Foam Color : foam_color
    draw_shader_ng_prop(mat__, 'UberLiquid_Shader', 'Foam Color', foam_box)
    # iiii : GeoNode : UberLiquid : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : UberLiquid : Bubbles Value : bubbles_value
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Bubbles Value', foam_box)
    # iiii : GeoNode : UberLiquid : Small Bubbles Presence : small_bubbles_presence
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Small Bubbles Presence', foam_box)
    # iiii : GeoNode : UberLiquid : Medium Bubbles Presence : medium_bubbles_presence
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Medium Bubbles Presence', foam_box)
    # iiii : GeoNode : UberLiquid : Large Bubbles Presence : large_bubbles_presence
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Large Bubbles Presence', foam_box)
    # iiii : GeoNode : UberLiquid : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Normal Strength', foam_box)
    # iiii : GeoNode : UberLiquid : Foam Seed : foam_seed
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Foam Seed', foam_box)
    # ++++++++
    # Secondary Foam : secondary_foam
    secondary_foam_box = root_layout.box()
    secondary_foam_box.label(text='Secondary Foam')
    # iiii : GeoNode : UberLiquid : Secondary Foam : secondary_foam
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Secondary Foam', secondary_foam_box)
    # iiii : Shader : UberLiquid_Shader NG : Secondary Foam Color : secondary_foam_color
    draw_shader_ng_prop(mat__, 'UberLiquid_Shader', 'Secondary Foam Color', secondary_foam_box)
    # iiii : GeoNode : UberLiquid : Secondary Foam Opacity : secondary_foam_opacity
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Secondary Foam Opacity', secondary_foam_box)
    # iiii : GeoNode : UberLiquid : Secondary Foam Size : secondary_foam_scale
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Secondary Foam Size', secondary_foam_box)
    # ++++++++
    # Smoothie : smoothie
    smoothie_box = root_layout.box()
    smoothie_box.label(text='Smoothie')
    # iiii : GeoNode : UberLiquid : Smoothie : smoothie
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Smoothie', smoothie_box)
    # iiii : GeoNode : UberLiquid : Pulp : pulp
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Pulp', smoothie_box)
    # ++++++++
    # Carbonation : carbonation
    carbonation_box = root_layout.box()
    carbonation_box.label(text='Carbonation')
    # iiii : GeoNode : UberLiquid : Carbonation Bubbles : carbonation_bubbles
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Carbonation Bubbles', carbonation_box)
    # iiii : GeoNode : UberLiquid : Carbonation Bubbles Density : carbonation_bubbles_quantity
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Carbonation Bubbles Density', carbonation_box)
    # iiii : GeoNode : UberLiquid : Carbonation Bubbles Scale : carbonation_bubbles_size
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Carbonation Bubbles Scale', carbonation_box)
    # iiii : GeoNode : UberLiquid : Bubbles Seed : bubbles_seed
    draw_geonodes_mod_prop(obj__, 'UberLiquid', 'Bubbles Seed', carbonation_box)

# oooooooooooooooo
# Beer : beer
def draw_beer_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Carbonation : carbonation;
    carbonation_box = root_layout.box()
    carbonation_box.label(text='Carbonation')
    # iiii : GeoNode : Carbonation_Static : Carbonated : carbonated
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Carbonated', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Quantity : quantity
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Quantity', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Size : size
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Size', carbonation_box)
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Black Beer : black_beer
def draw_black_beer_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Carbonation : carbonation
    carbonation_box = root_layout.box()
    carbonation_box.label(text='Carbonation')
    # iiii : GeoNode : Carbonation_Static : Carbonated : carbonated
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Carbonated', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Quantity : quantity
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Quantity', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Size : size
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Size', carbonation_box)
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Black Tea : black_tea
def draw_black_tea_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Tea Shader NG : Tea Color : tea_color
    draw_shader_ng_prop(mat__, 'Tea Shader', 'Tea Color', liquid_box)
    # iiii : Shader : Tea Shader NG : Intensity : intensity
    draw_shader_ng_prop(mat__, 'Tea Shader', 'Intensity', liquid_box)

# oooooooooooooooo
# Blue Lagoon : blue_lagoon
def draw_blue_lagoon_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Blue Lagoon NG : Color : color
    draw_shader_ng_prop(mat__, 'Blue Lagoon', 'Color', liquid_box)
    # iiii : Shader : Blue Lagoon NG : Intensity : intensity
    draw_shader_ng_prop(mat__, 'Blue Lagoon', 'Intensity', liquid_box)

# oooooooooooooooo
# Blueberry Juice : blueberry_juice
def draw_blueberry_juice_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Cappuccino : cappuccino
def draw_cappuccino_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Cappuccino NG : Liquid Color : liquid_color
    draw_shader_ng_prop(mat__, 'Cappuccino', 'Liquid Color', liquid_box)
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Champagne : champagne
def draw_champagne_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Carbonation : carbonation
    carbonation_box = root_layout.box()
    carbonation_box.label(text='Carbonation')
    # iiii : GeoNode : Carbonation_Static : Carbonated : carbonated
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Carbonated', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Quantity : quantity
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Quantity', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Size : size
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Size', carbonation_box)
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Chocolate Milk : chocolate_milk
def draw_chocolate_milk_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Coffee : coffee
def draw_coffee_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Coffee NG : Coffee Intensity : coffee_intensity
    draw_shader_ng_prop(mat__, 'Coffee', 'Coffee Intensity', liquid_box)

# oooooooooooooooo
# Coke : coke
def draw_coke_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Carbonation : carbonation
    carbonation_box = root_layout.box()
    carbonation_box.label(text='Carbonation')
    # iiii : GeoNode : Carbonation_Static : Carbonated : carbonated
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Carbonated', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Quantity : quantity
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Quantity', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Size : size
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Size', carbonation_box)
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Cranberry Juice : cranberry_juice
def draw_cranberry_juice_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : GeoNode : Juice Utils : Pulp Amount : pulp_amount
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Pulp Amount', liquid_box)
    # iiii : GeoNode : Juice Utils : Juice Color : juice_color
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Juice Color', liquid_box)

# oooooooooooooooo
# Energy Drink : energy_drink
def draw_energy_drink_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Carbonation : carbonation
    carbonation_box = root_layout.box()
    carbonation_box.label(text='Carbonation')
    # iiii : GeoNode : Carbonation_Static : Carbonated : carbonated
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Carbonated', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Quantity : quantity
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Quantity', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Size : size
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Size', carbonation_box)
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Ginger Ale : ginger_ale
def draw_ginger_ale_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Ginger Ale NG : Liquid Color : liquid_color
    draw_shader_ng_prop(mat__, 'Ginger Ale', 'Liquid Color', liquid_box)
    # iiii : Shader : Ginger Ale NG : Intensity : intensity
    draw_shader_ng_prop(mat__, 'Ginger Ale', 'Intensity', liquid_box)
    # ++++++++
    # Carbonation : carbonation
    carbonation_box = root_layout.box()
    carbonation_box.label(text='Carbonation')
    # iiii : GeoNode : Carbonation_Static : Carbonated : carbonated
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Carbonated', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Quantity : quantity
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Quantity', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Size : size
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Size', carbonation_box)

# oooooooooooooooo
# Green Apple Juice : green_apple_juice
def draw_green_apple_juice_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : GeoNode : Juice Utils : Juice Color : juice_color
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Juice Color', liquid_box)
    # iiii : GeoNode : Juice Utils : Pulp Amount : pulp_amount
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Pulp Amount', liquid_box)

# oooooooooooooooo
# Greenies Smoothie : greenies_smoothie
def draw_greenies_smoothie_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : GeoNode : Juice Utils : Pulp Amount : pulp_amount
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Pulp Amount', liquid_box)
    # iiii : GeoNode : Juice Utils : Juice Color : juice_color
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Juice Color', liquid_box)
    # iiii : GeoNode : Smoothie Utils : Smoothie Chunks : smoothie_chunks
    draw_geonodes_mod_prop(obj__, 'Smoothie Utils', 'Smoothie Chunks', liquid_box)

# oooooooooooooooo
# Honey : honey
def draw_honey_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Honey NG : Color : color
    draw_shader_ng_prop(mat__, 'Honey', 'Color', liquid_box)
    # iiii : Shader : Honey NG : Intensity : intensity
    draw_shader_ng_prop(mat__, 'Honey', 'Intensity', liquid_box)
    # iiii : Shader : Honey NG : Crystallization : crystallization
    draw_shader_ng_prop(mat__, 'Honey', 'Crystallization', liquid_box)
    # iiii : Shader : Honey NG : Crystallization Scale : crystallization_scale
    draw_shader_ng_prop(mat__, 'Honey', 'Crystallization Scale', liquid_box)
    # ++++++++
    # Bubbles : bubbles
    bubbles_box = root_layout.box()
    bubbles_box.label(text='Bubbles')
    # iiii : GeoNode : Static Bubbles : Static Bubbles : static_bubbles
    draw_geonodes_mod_prop(obj__, 'Static Bubbles', 'Static Bubbles', bubbles_box)
    # iiii : GeoNode : Static Bubbles : Quantity : quantity
    draw_geonodes_mod_prop(obj__, 'Static Bubbles', 'Quantity', bubbles_box)
    # iiii : GeoNode : Static Bubbles : Size : size
    draw_geonodes_mod_prop(obj__, 'Static Bubbles', 'Size', bubbles_box)
    # iiii : GeoNode : Static Bubbles : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Static Bubbles', 'Seed', bubbles_box)

# oooooooooooooooo
# Ice Tea : ice_tea
def draw_ice_tea_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Ice Tea NG : Color : color
    draw_shader_ng_prop(mat__, 'Ice Tea', 'Color', liquid_box)
    # iiii : Shader : Ice Tea NG : Intensity : intensity
    draw_shader_ng_prop(mat__, 'Ice Tea', 'Intensity', liquid_box)

# oooooooooooooooo
# Lemonade : lemonade
def draw_lemonade_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Lemonade NG : Color : color
    draw_shader_ng_prop(mat__, 'Lemonade', 'Color', liquid_box)
    # iiii : Shader : Lemonade NG : Pulp Particles Opacity : pulp_particles_opacity
    draw_shader_ng_prop(mat__, 'Lemonade', 'Pulp Particles Opacity', liquid_box)

# oooooooooooooooo
# Milk : milk
def draw_milk_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Olive Oil : olive_oil
def draw_olive_oil_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Olive Oil NG : Color : color
    draw_shader_ng_prop(mat__, 'Olive Oil', 'Color', liquid_box)
    # iiii : Shader : Olive Oil NG : Intensity : intensity
    draw_shader_ng_prop(mat__, 'Olive Oil', 'Intensity', liquid_box)
    # iiii : Shader : Olive Oil NG : Turbidity : turbidity
    draw_shader_ng_prop(mat__, 'Olive Oil', 'Turbidity', liquid_box)
    # ++++++++
    # Bubbles : bubbles
    bubbles_box = root_layout.box()
    bubbles_box.label(text='Bubbles')
    # iiii : GeoNode : Static Bubbles : Static Bubbles : static_bubbles
    draw_geonodes_mod_prop(obj__, 'Static Bubbles', 'Static Bubbles', bubbles_box)
    # iiii : GeoNode : Static Bubbles : Quantity : quantity
    draw_geonodes_mod_prop(obj__, 'Static Bubbles', 'Quantity', bubbles_box)
    # iiii : GeoNode : Static Bubbles : Size : size
    draw_geonodes_mod_prop(obj__, 'Static Bubbles', 'Size', bubbles_box)
    # iiii : GeoNode : Static Bubbles : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Static Bubbles', 'Seed', bubbles_box)

# oooooooooooooooo
# Orange Juice : orange_juice
def draw_orange_juice_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : GeoNode : Juice Utils : Juice Color : juice_color
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Juice Color', liquid_box)
    # iiii : GeoNode : Juice Utils : Pulp Amount : pulp_amount
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Pulp Amount', liquid_box)

# oooooooooooooooo
# Red Fruit Smoothie : red_fruit_smoothie
def draw_red_fruit_smoothie_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : GeoNode : Juice Utils : Juice Color : juice_color
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Juice Color', liquid_box)
    # iiii : GeoNode : Juice Utils : Pulp Amount : pulp_amount
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Pulp Amount', liquid_box)

# oooooooooooooooo
# Red Wine : red_wine
def draw_red_wine_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Wine NG : Color : color
    draw_shader_ng_prop(mat__, 'Wine', 'Color', liquid_box)
    # iiii : Shader : Wine NG : Intensity : intensity
    draw_shader_ng_prop(mat__, 'Wine', 'Intensity', liquid_box)
    # iiii : Shader : Wine NG : Turbidity : turbidity
    draw_shader_ng_prop(mat__, 'Wine', 'Turbidity', liquid_box)

# oooooooooooooooo
# Rose Wine : rose_wine
def draw_rose_wine_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Wine NG : Color : color
    draw_shader_ng_prop(mat__, 'Wine', 'Color', liquid_box)
    # iiii : Shader : Wine NG : Intensity : intensity
    draw_shader_ng_prop(mat__, 'Wine', 'Intensity', liquid_box)
    # iiii : Shader : Wine NG : Turbidity : turbidity
    draw_shader_ng_prop(mat__, 'Wine', 'Turbidity', liquid_box)

# oooooooooooooooo
# Water : water
def draw_water_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Carbonation : carbonation
    carbonation_box = root_layout.box()
    carbonation_box.label(text='Carbonation')
    # iiii : GeoNode : Carbonation_Static : Carbonated : carbonated
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Carbonated', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Quantity : quantity
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Quantity', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Size : size
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Size', carbonation_box)

# oooooooooooooooo
# Tomato Juice : tomato_juice
def draw_tomato_juice_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : GeoNode : Juice Utils : Juice Color : juice_color
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Juice Color', liquid_box)
    # iiii : GeoNode : Juice Utils : Pulp Amount : pulp_amount
    draw_geonodes_mod_prop(obj__, 'Juice Utils', 'Pulp Amount', liquid_box)

# oooooooooooooooo
# Unfiltered Beer : unfiltered_beer
def draw_unfiltered_beer_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Carbonation : carbonation
    carbonation_box = root_layout.box()
    carbonation_box.label(text='Carbonation')
    # iiii : GeoNode : Carbonation_Static : Carbonated : carbonated
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Carbonated', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Quantity : quantity
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Quantity', carbonation_box)
    # iiii : GeoNode : Carbonation_Static : Size : size
    draw_geonodes_mod_prop(obj__, 'Carbonation_Static', 'Size', carbonation_box)
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Whiskey : whiskey
def draw_whiskey_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Whiskey NG : Color : color
    draw_shader_ng_prop(mat__, 'Whiskey', 'Color', liquid_box)
    # iiii : Shader : Whiskey NG : Intensity : intensity
    draw_shader_ng_prop(mat__, 'Whiskey', 'Intensity', liquid_box)

# oooooooooooooooo
# White Wine : white_wine
def draw_white_wine_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Liquid : liquid
    liquid_box = root_layout.box()
    liquid_box.label(text='Liquid')
    # iiii : Shader : Wine NG : Color : color
    draw_shader_ng_prop(mat__, 'Wine', 'Color', liquid_box)
    # iiii : Shader : Wine NG : Intensity : intensity
    draw_shader_ng_prop(mat__, 'Wine', 'Intensity', liquid_box)
    # iiii : Shader : Wine NG : Turbidity : turbidity
    draw_shader_ng_prop(mat__, 'Wine', 'Turbidity', liquid_box)

# oooooooooooooooo
# Strawberry Milkshake : strawberry_milkshake
def draw_strawberry_milkshake_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Coffee Milkshake : coffee_milkshake
def draw_coffee_milkshake_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Foam : foam
    foam_box = root_layout.box()
    foam_box.label(text='Foam')
    # iiii : GeoNode : Foam Shader Utils : Foam : foam
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Amount : foam_amount
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Amount', foam_box)
    # iiii : GeoNode : Foam Utils : Foam Displacement : foam_displacement
    draw_geonodes_mod_prop(obj__, 'Foam Utils', 'Foam Displacement', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Foam Center Distribution : foam_center_distribution
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Foam Center Distribution', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Bubbles Scale : bubbles_scale
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Bubbles Scale', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Normal Strength : normal_strength
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Normal Strength', foam_box)
    # iiii : GeoNode : Foam Shader Utils : Seed : seed
    draw_geonodes_mod_prop(obj__, 'Foam Shader Utils', 'Seed', foam_box)

# oooooooooooooooo
# Wax : wax
def draw_wax_shader_controls(obj__, mat__, shading_modality_key, context, root_layout):
    # ++++++++
    # Wax : wax
    wax_box = root_layout.box()
    # wax_box.label(text='Wax')
    # iiii : GeoNode : Wax Shader Utils : Wax : wax
    draw_geonodes_mod_prop(obj__, 'Wax Utils', 'Wax Color', wax_box)
    # iiii : GeoNode : Wax Shader Utils : Wax : wax
    draw_geonodes_mod_prop(obj__, 'Wax Utils', 'Wax Roughness', wax_box)

shader_controls_draw_fs = {
    'solids': {
        'Uber Glass': draw_uber_glass_shader_controls,
        'PET': draw_pet_shader_controls,
        'Brown Bottle Glass': draw_brown_bottle_glass_shader_controls,
        'Green Bottle Glass': draw_green_bottle_glass_shader_controls,
    },
    'liquids': {
        'UberLiquid': draw_uberliquid_shader_controls,
        'Beer': draw_beer_shader_controls,
        'Black Beer': draw_black_beer_shader_controls,
        'Black Tea': draw_black_tea_shader_controls,
        'Blue Lagoon': draw_blue_lagoon_shader_controls,
        'Blueberry Juice': draw_blueberry_juice_shader_controls,
        'Cappuccino': draw_cappuccino_shader_controls,
        'Champagne': draw_champagne_shader_controls,
        'Chocolate Milk': draw_chocolate_milk_shader_controls,
        'Coffee': draw_coffee_shader_controls,
        'Coke': draw_coke_shader_controls,
        'Cranberry Juice': draw_cranberry_juice_shader_controls,
        'Energy Drink': draw_energy_drink_shader_controls,
        'Ginger Ale': draw_ginger_ale_shader_controls,
        'Green Apple Juice': draw_green_apple_juice_shader_controls,
        'Greenies Smoothie': draw_greenies_smoothie_shader_controls,
        'Honey': draw_honey_shader_controls,
        'Ice Tea': draw_ice_tea_shader_controls,
        'Lemonade': draw_lemonade_shader_controls,
        'Milk': draw_milk_shader_controls,
        'Olive Oil': draw_olive_oil_shader_controls,
        'Orange Juice': draw_orange_juice_shader_controls,
        'Red Fruit Smoothie': draw_red_fruit_smoothie_shader_controls,
        'Red Wine': draw_red_wine_shader_controls,
        'Rose Wine': draw_rose_wine_shader_controls,
        'Water': draw_water_shader_controls,
        'Tomato Juice': draw_tomato_juice_shader_controls,
        'Unfiltered Beer': draw_unfiltered_beer_shader_controls,
        'Whiskey': draw_whiskey_shader_controls,
        'White Wine': draw_white_wine_shader_controls,
        'Strawberry Milkshake': draw_strawberry_milkshake_shader_controls,
        'Coffee Milkshake': draw_coffee_milkshake_shader_controls,
        'Wax': draw_wax_shader_controls,
    }
}

def draw_high_level_material_controls(
        context, shading_modality_key, obj__, library_key, mat_name, root_layout):
    box = root_layout.box()
    mat_name_row = box.row()
    split_row = mat_name_row.split(
        factor=0.7)
    material = hrdc_get_asset_material(
        obj__, shading_modality_key=shading_modality_key)
    split_row.label(text=mat_name)
    split_row.label(text=f'{material.users} objects')
    op_row = box.row()
    split_row = op_row.split()
    col = split_row.column()
    col.enabled = material.users > 1
    col.operator(
        f'liquifeel.make_{shading_modality_key}_material_single_user',
        text='Make Single User',
        icon_value=preview_data['ids']['icons']['make_single_user'])
    if shading_modality_key == 'fill':
        op_id = f'liquifeel.clear_fill_material'
    elif shading_modality_key == 'slot':
        op_id = f'liquifeel.clear_slot'
    split_row.operator(
        op_id,
        text='Clear Material',
        icon_value=preview_data['ids']['icons']['clear'])

def draw_high_level_render_controls(
        obj__, context, root_layout, shading_modality_key):
    box = root_layout.box()
    op_row = box.row()
    split_row = op_row.split()
    enable_render_engine_col = split_row.column()
    enable_render_engine_col.enabled = not(context.scene.render.engine == 'CYCLES')
    enable_render_engine_col.operator(
        f'liquifeel.switch_to_cycles_render_engine',
        text='Enable Cycles',
        icon=MAIN_TAB_BUILTIN_ICONS['render'])
    split_row.operator(
        f'liquifeel.update_render_view',
        text='Refresh Render View',
        icon_value=preview_data['ids']['icons']['refresh'])

def hrdc_draw_shader_controls(context, shading_modality_key, obj__, library_key, mat_name, root_layout):
    mat__ = hrdc_get_asset_material(obj__, shading_modality_key=shading_modality_key)
    # if mat_name in shader_controls_draw_fs[library_key]:
    shader_controls_draw_fs[library_key][mat_name](
        obj__, mat__, shading_modality_key, context, root_layout)

def draw_liquid_amount_slider(obj__, root_layout):
    # Blender 5.x stores GN inputs on mod.properties.inputs — the legacy
    # mod["SocketName"] path is a no-op / wrong scale. Reuse the shared drawer.
    draw_geonodes_mod_prop(
        obj__, FILL_NG_NAME, 'Liquid Level', root_layout, text='Liquid Amount')

def hrdc_draw_shading_ui__(shading_modality_key, context, root_layout):  # !!! To be customized into the hardcoded-ui version
    obj__ = resolve_liquifeel_source_object(context.active_object)
    library_key, mat_name = hrdc_get_library_key_and_material_name(
        obj__, shading_modality_key=shading_modality_key)
    # print(library_key, mat_name)
    # print('is_obj_liquifeel_asset(obj__)', is_obj_liquifeel_asset(obj__))
    # print('is_obj_library_shaded(obj__, library_key, shading_modality_key)',
          # is_obj_library_shaded(obj__, library_key, shading_modality_key))
    if is_obj_liquifeel_asset(obj__) and is_obj_library_shaded(
            obj__, library_key, shading_modality_key):
        obj__ = context.active_object
        # draw_material_link_controls(obj__, context, root_layout, shading_modality_key)
        hrdc_draw_library_selector(obj__, context, root_layout, shading_modality_key)
        material_picker_box = root_layout.box()
        selector_prop_key_chain = [
            'hrdc_liquifeel_input_field_props', 'shading', shading_modality_key, f'{library_key}_material']
        selector_prop_parent, selector_prop_key = ref_ob_key_pair(
            obj__, selector_prop_key_chain)
        material_picker_box.template_icon_view(
            selector_prop_parent, selector_prop_key,
            show_labels=True, scale=UI_THUMB_SCALE, scale_popup=POPUP_THUMB_SCALE)
        # material_picker_box.label(
        #     text=mat_name)
        # root_layout.operator(
        #     f'liquifeel.update_render_view',
        #     text='Update Render View',
        # )
        draw_high_level_material_controls(
            context, shading_modality_key, obj__, library_key, mat_name, root_layout)
        if is_obj_filled(obj__):
            hrdc_draw_hide_controls(obj__, root_layout)
            draw_liquid_amount_slider(obj__, root_layout)
        hrdc_draw_shader_controls(context, shading_modality_key, obj__, library_key, mat_name, root_layout)
    elif library_key == 'scene':
        hrdc_draw_scene_shading_ui(obj__, shading_modality_key, context, root_layout)
    else:
        hrdc_draw_library_selector(obj__, context, root_layout, shading_modality_key)
        shade_it_row = root_layout.row()
        shade_it_row.scale_y = LRG_H
        shade_it_row.operator(
            f'liquifeel.hrdc_shade_active_object_via_{shading_modality_key}', # !!! This is where i left the customization process
            text='Shade active',
            icon=MAIN_TAB_BUILTIN_ICONS['shading'],
        )
    draw_high_level_render_controls(obj__, context, root_layout, shading_modality_key)
    # draw_spacing(root_layout)


def hrdc_draw_slot_shading_ui(context, root_layout):
    hrdc_draw_shading_ui__('slot', context, root_layout)

def draw_shading_target_selector(obj__, context, root_layout):
    recipient_vs_liquid_tab_row = root_layout.row()
    recipient_vs_liquid_tab_row.scale_y = MID_H
    general_ctrl__ = context.scene.liquifeel_general_controls
    recipient_vs_liquid_tab_row.prop(
        general_ctrl__, 'shading_target', expand=True)
    draw_spacing(root_layout)


def hrdc_draw_fill_liquid_shading_ui(context, root_layout):
    hrdc_draw_shading_ui__('fill', context, root_layout)    

    # draw_spacing(root_layout)

def hrdc_draw_fill_shading_ui(context, root_layout):
    obj__ = resolve_liquifeel_source_object(context.active_object)
    draw_shading_target_selector(obj__, context, root_layout) # recipient or liquid
    general_ctrl__ = context.scene.liquifeel_general_controls
    if getattr(general_ctrl__, 'shading_target') == 'recipient':
        hrdc_draw_slot_shading_ui(context, root_layout)
    elif getattr(general_ctrl__, 'shading_target') == 'liquid':
        hrdc_draw_fill_liquid_shading_ui(context, root_layout)
    # draw_spacing(root_layout)

        # draw_spacing(root_layout)

def hrdc_draw_shading_ui(context, root_layout):
    if is_active_selected_ob(context):
        obj__ = resolve_liquifeel_source_object(context.active_object)
        if is_asset_legacy_configured(obj__):
            draw_legacy_asset_configuration_message(context, root_layout)
        else:
            if is_obj_filled(obj__):
                hrdc_draw_fill_shading_ui(context, root_layout)
            else:
                hrdc_draw_slot_shading_ui(context, root_layout)
    else:
        root_layout.label(
            text='Please select an object to shade.')
        # draw_spacing(root_layout)

# # Not implemented yet
# def draw_effects_ui(context, root_layout):
#     if is_active_selected_ob(context):
#         pass
#     else:
#         root_layout.label(
#             text='Please select an object to apply effects to.')
#         draw_spacing(root_layout)

def draw_recipients_ui(context, root_layout):
    root_layout.template_icon_view(
        context.scene.liquifeel_general_controls, 'recipient_asset',
        show_labels=True, scale=UI_THUMB_SCALE, scale_popup=POPUP_THUMB_SCALE)
    asset_key = getattr(context.scene.liquifeel_general_controls, 'recipient_asset')
    root_layout.label(
        text=RECIPIENT_ASSET_NAME_DATA[asset_key]['thumbnail'])
    add_asset_row = root_layout.row()
    add_asset_row.scale_y = MID_H
    add_asset_row.operator(
        'liquifeel.add_asset_to_3d_cursor',
        text='Add Asset To 3D Cursor',
        # icon=MAIN_TAB_BUILTIN_ICONS['shading'], # !!! icon?
    )
    # draw_spacing(root_layout)

def draw_condensation_ui(context, root_layout):
    obj__ = context.active_object
    if obj__:
        if has_obj_condensation(obj__):
            condensation_box = root_layout.box()
            # iiii : GeoNode : Condensation_V1.0 : Condensation : condensation
            draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Condensation', condensation_box)
            if not is_obj_filled(obj__):
                condensation_box.label(
                    text='Fill the this recipient to enable additional functionality.')
            if get_geonodes_mod_input_val(obj__, 'Condensation_V1.0', 'Condensation'):
                # iiii : GeoNode : Condensation_V1.0 : Density : density
                draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Density', condensation_box)
                # iiii : GeoNode : Condensation_V1.0 : Scale : scale
                draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Scale', condensation_box)
                if is_obj_filled(obj__):
                    # iiii : GeoNode : Condensation_V1.0 : Condensation Type : condensation_type
                    draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Condensation Type', condensation_box)
                # iiii : GeoNode : Condensation_V1.0 : Use Vertex Group : use_vertex_group
                draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Use Vertex Group', condensation_box)
                # iiii : GeoNode : Condensation_V1.0 : Vertex Group : vertex_group
                draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Vertex Group', condensation_box)
            # High level controls
            clear_apply_box = root_layout.box()
            op_row = clear_apply_box.row()
            split_row = op_row.split()
            col = split_row.column()
            # The Apply button is only available if the object is not filled
            col.enabled = not(is_obj_filled(obj__))
            col.operator(
                'liquifeel.apply_condensation',
                text='Apply Condensation',
                icon_value=preview_data['ids']['icons']['check'])
            split_row.operator(
                'liquifeel.clear_condensation',
                text='Clear Condensation',
                icon_value=preview_data['ids']['icons']['clear'])
        else:
            root_layout.operator(
                'liquifeel.add_condensation_to_active_object',
                text='Add Condensation',
                icon_value=preview_data['ids']['icons']['condensation'])
    else:
        root_layout.label(
            text='Please select an object to add condensation to.')
# def draw_condensation_ui(context, root_layout):
#     obj__ = context.active_object
#     if obj__:
#         if is_obj_filled(obj__):
#             condensation_box = root_layout.box()
#             # iiii : Condensation : condensation : Condensation_V1.0 : GeoNode
#             draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Condensation', condensation_box)
#             if get_geonodes_mod_input_val(obj__, 'Condensation_V1.0', 'Condensation'):
#                 # iiii : Density : density : Condensation_V1.0 : GeoNode
#                 draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Density', condensation_box)
#                 # iiii : Scale : scale : Condensation_V1.0 : GeoNode
#                 draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Scale', condensation_box)
#                 # iiii : Condensation Type : condensation_type : Condensation_V1.0 : GeoNode
#                 draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Condensation Type', condensation_box)
#                 # iiii : Use Vertex Group : use_vertex_group : Condensation_V1.0 : GeoNode
#                 draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Use Vertex Group', condensation_box)
#                 # iiii : Vertex Group : vertex_group : Condensation_V1.0 : GeoNode
#                 draw_geonodes_mod_prop(obj__, 'Condensation_V1.0', 'Vertex Group', condensation_box)
#         else:
#             root_layout.label(
#                 text='Please fill an object from the geometry tab to enable this feature.')
#     else:
#         root_layout.label(
#             text='Please select a Liquifeel filled object.')

# main_tab_draw_fs = {
#     'geometry': draw_geometry_ui,
#     'shading': draw_shading_ui,
#     # 'effects': draw_effects_ui, # Not implemented yet
#     'recipients': draw_recipients_ui
# }

hrdc_main_tab_draw_fs = {
    'geometry': draw_geometry_ui,
    'shading': hrdc_draw_shading_ui,
    # 'effects': draw_effects_ui, # Not implemented yet
    'recipients': draw_recipients_ui,
    'condensation': draw_condensation_ui,
}

def draw_clear_apply_ui(context, root_layout):
    if is_active_selected_ob(context):
        apply_clear_row = root_layout.row()
        obj__ = context.object
        if is_obj_liquifeel_asset(obj__) and obj__.mode == 'OBJECT':
            layout_operator_with_preview(
                apply_clear_row, 'liquifeel.clear_fill',
                text='Clear Fill', icon_key='clear', fallback_icon='X')
            # apply_clear_row.operator(
            #     'liquifeel.clear_asset',
            #     text='Clear',
            # )
            layout_operator_with_preview(
                apply_clear_row, 'liquifeel.apply_fill',
                text='Apply Fill', icon_key='check', fallback_icon='CHECKMARK')
            # apply_clear_row.operator(
            #     'liquifeel.apply_asset',
            #     text='Apply',
            # )
            # draw_spacing(root_layout)
# def draw_clear_apply_ui(context, root_layout):
#     apply_clear_row = root_layout.row()
#     if is_active_selected_ob(context):
#         obj__ = context.object
#         if is_obj_liquifeel_asset(obj__) and obj__.mode == 'OBJECT':
#             apply_clear_row.operator(
#                 'liquifeel.clear_asset',
#                 text='Clear',
#             )
#             apply_clear_row.operator(
#                 'liquifeel.apply_asset',
#                 text='Apply',
#             )
#             draw_spacing(root_layout)
#     apply_clear_row.operator(
#         'liquifeel.purge_unused_data', text='Clean up')
# def draw_clear_apply_ui(context, root_layout):
#     if is_active_selected_ob(context):
#         obj__ = context.object
#         if is_obj_liquifeel_asset(obj__) and obj__.mode == 'OBJECT':
#             apply_clear_row = root_layout.row()
#             apply_clear_row.operator(
#                 'liquifeel.clear_asset',
#                 text='Clear',
#             )
#             apply_clear_row.operator(
#                 'liquifeel.apply_asset',
#                 text='Apply',
#             )
#             draw_spacing(root_layout)

## PANEL ---------------------

# # obsoleted by draw_hrdc_main_panel
# def draw_main_panel(panel__, context):
#     # # KEEP
#     # panel__.layout.prop(
#     #     context.scene.liquifeel_general_controls, 'performance_render_mode')
#     draw_spacing(panel__.layout)
#     draw_navigation_and_feedback(context, panel__.layout)
#     main_tab_draw_fs[getattr(context.scene.liquifeel_general_controls, 'main_tabs')](context, panel__.layout)
#     draw_spacing(panel__.layout)
#     draw_clear_apply_ui(context, panel__.layout)
#     draw_spacing(panel__.layout)

# class MainPanel(bpy.types.Panel):
#     bl_idname = 'OBJECT_PT_liquifeel_main_panel'
#     bl_label = 'Liquifeel'
#     bl_space_type = 'VIEW_3D'
#     bl_region_type = 'UI'
#     bl_category = 'Liquifeel'
#     def draw_header(self, context):
#         self.layout.label(
#             text='',
#             icon_value=preview_data['ids']['icons']['liquifeel_purple'])
#     def draw(self, context):
#         draw_main_panel(self, context)
# registerable_classes.append(MainPanel)

def draw_hrdc_main_panel(panel__, context):
    draw_spacing(panel__.layout)
    draw_navigation_and_feedback(context, panel__.layout)
    tab_key = getattr(context.scene.liquifeel_general_controls, 'main_tabs')
    draw_tab = hrdc_main_tab_draw_fs.get(tab_key)
    if draw_tab is None:
        panel__.layout.label(text=f'Unknown LiquiFeel tab: {tab_key}', icon='ERROR')
    else:
        try:
            draw_tab(context, panel__.layout)
        except Exception as exc:
            import traceback
            traceback.print_exc()
            panel__.layout.label(text=f'LiquiFeel UI error: {exc}', icon='ERROR')
            panel__.layout.label(text=f'Build: {ADDON_BUILD_TAG}')
    draw_spacing(panel__.layout)
    # draw_clear_apply_ui(context, panel__.layout)
    draw_spacing(panel__.layout)
    panel__.layout.operator(
        'liquifeel.deep_clean_data',
        text='Remove All LiquiFeel Data',
        icon='TRASH')
    panel__.layout.operator(
        'liquifeel.copy_diagnostics',
        text='Copy Diagnostics',
        icon='INFO')

class HRDC_MainPanel(bpy.types.Panel):
    bl_idname = 'OBJECT_PT_liquifeel_hrdc_main_panel'
    bl_label = 'Liquifeel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Liquifeel'
    def draw_header(self, context):
        icon_id = preview_icon_id('liquifeel_purple')
        if icon_id:
            self.layout.label(text='', icon_value=icon_id)
        else:
            self.layout.label(text='', icon='FLUID')
    def draw(self, context):
        draw_hrdc_main_panel(self, context)
registerable_classes.append(HRDC_MainPanel)

def get_node_socket_data():
    print('================================================================')
    print('get_node_socket_data()')
    dat = {}
    for tab_key, tab_data in INPUT_FIELD_DATA.items():
        dat[tab_key] = {}
        for lib_key, lib_data in tab_data.items():
            dat[tab_key][lib_key] = {}
            for mat_name, mat_data in lib_data.items():
                dat[tab_key][lib_key][mat_name] = {}
                for target_key, target_data in mat_data.items():
                    dat[tab_key][lib_key][mat_name][target_key] = {}
                    for group_name, group_data in target_data.items():
                        dat[tab_key][lib_key][mat_name][target_key][group_name] = {}
                        for input_name, input_data in group_data.items():
                            # print('----------------------------------------------------------------')
                            # print(tab_key, lib_key, mat_name, target_key, group_name, input_name)
                            dat__ = {}
                            # if target_key == 'Shader NG':
                            if input_data['underlying_input_type'] in ['float', 'int']:
                                ng = index_stripped(bpy.data.node_groups, group_name)
                                input_ob = index_stripped(
                                    ng.interface.items_tree, input_data['underlying_input_name'])
                                if DEV:
                                    debug_buffer.append(input_ob)
                                if hasattr(input_ob, 'min_value') and hasattr(input_ob, 'max_value'):
                                    dat__['min'] = input_ob.min_value
                                    dat__['max'] = input_ob.max_value
                                    dat__['default_val'] = input_ob.default_value
                                    dat__['socket_type'] = input_ob.socket_type
                                # print(dat__)
                                # elif target_key == 'GeoNode':
                                dat[tab_key][lib_key][mat_name][target_key][group_name][input_name] = dat__
    with open(FPATHS['node_socket_data'], 'w') as f:
        json.dump(dat, f, indent=2)
    return dat

class GetBoundingData(bpy.types.Operator):
    bl_idname = 'liquifeel.get_node_socket_data'
    bl_label = 'Get Bounding Data'
    def execute(self, context):
        dat = get_node_socket_data()
        pprint(dat)
        return {'FINISHED'}
if DEV:
    registerable_classes.append(GetBoundingData)

class DevPanel(bpy.types.Panel):
    bl_idname = 'OBJECT_PT_dev_panel'
    bl_label = 'Liquifeel dev'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Liquifeel'
    def draw(self, context):
        self.layout.operator('liquifeel.get_node_socket_data')
        self.layout.operator('liquifeel.extract_geonode_mods_input_vals')
        self.layout.operator('liquifeel.extract_migration_tag_data')
if DEV:
    registerable_classes.append(DevPanel)

## REGISTRATION --------------------------------------------------------------------------------

def get_classes():
    return registerable_classes

if DEV:
    spec = importlib.util.spec_from_file_location(
        'repl',
        '/home/feral/.config/blender/4.0/scripts/addons/calculusrex_repl/__init__.py')
    repl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repl)
    def repl_ns():
        return globals()
    dev_aux_registration = lambda: repl.register(ns=repl_ns)
    dev_aux_unregistration = lambda: repl.unregister()

def register():
    _load_preview_collections()
    classes_to_register = get_classes()
    for cls in classes_to_register:
        bpy.utils.register_class(cls)
    print(f'LIQUIFEEL: registered {len(classes_to_register)} classes')

    bpy.types.Scene.liquifeel_general_controls = bpy.props.PointerProperty(type=GeneralUIControls)
    bpy.types.Scene.liquifeel_misc_data = bpy.props.PointerProperty(type=MiscData)
    # bpy.types.Object.liquifeel_field_inputs = bpy.props.PointerProperty(type=FieldInputProps)
    # bpy.types.Object.liquifeel_input_field_props = bpy.props.PointerProperty(
    #     type=ObjectAttached_InputProps)
    # bpy.types.Material.liquifeel_input_field_props = bpy.props.PointerProperty(
    #     type=MaterialAttached_InputProps)
    bpy.types.Object.hrdc_liquifeel_input_field_props = bpy.props.PointerProperty(
        type=HRDC_ObjAttch_InptPrps)
    bpy.types.Material.hrdc_liquifeel_input_field_props = bpy.props.PointerProperty(
        type=HRDC_MatAttch_InptPrps)

    if DEV:
        dev_aux_registration()

    # # Animation
    
def unregister():
    _unregister_separate_timers()
    _mesh_island_count_cache.clear()
    classes_to_unregister = get_classes()
    for cls in classes_to_unregister:
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.liquifeel_general_controls
    del bpy.types.Scene.liquifeel_misc_data
    # del bpy.types.Object.liquifeel_field_inputs
    # del bpy.types.Object.liquifeel_input_field_props
    # del bpy.types.Material.liquifeel_input_field_props
    del bpy.types.Object.hrdc_liquifeel_input_field_props
    del bpy.types.Material.hrdc_liquifeel_input_field_props

    if DEV:
        dev_aux_unregistration()

    _unload_preview_collections()

    # # Animation

if __name__ == '__main__':
    register()
