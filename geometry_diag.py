# SPDX-License-Identifier: GPL-3.0-or-later
"""Geometry diagnostics for LiquiFeel (wall thickness + preview GN).

Independent of the production fill node groups. Used by Check Geometry and
Preview Geometry Diag.
"""

from __future__ import annotations

import bpy
import bmesh
import mathutils
from mathutils.bvhtree import BVHTree

GEOMETRY_DIAG_NG_NAME = 'LiquiFeel_GeometryDiag'
GEOMETRY_DIAG_ATTR = 'LQFL_Diag'
GEOMETRY_DIAG_VERSION = 1

# Real-world wall thickness band (millimetres), scaled via mesh unit factor.
THICKNESS_MIN_MM = 0.5
THICKNESS_MAX_MM = 15.0
# Share of faces with no opposite hit → Problem (single-surface / open sheet).
NO_SHELL_PROBLEM_RATIO = 0.40
NO_SHELL_WARNING_RATIO = 0.15
# Share of deep hits (beyond max wall) → Warning (solid block, not shell).
DEEP_HIT_WARNING_RATIO = 0.50


def _median(values):
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return 0.5 * (float(ordered[mid - 1]) + float(ordered[mid]))


def analyze_wall_thickness(obj__, mm_unit_factor):
    """Raycast opposite wall from each face center along -normal.

    Returns dict with counts, ratios, thickness stats (object-local units).
    """
    mesh = obj__.data
    face_count = len(mesh.polygons)
    empty = {
        'face_count': face_count,
        'sample_count': 0,
        'hit_count': 0,
        'no_hit_count': 0,
        'good_count': 0,
        'thin_count': 0,
        'deep_count': 0,
        'no_hit_ratio': 1.0 if face_count else 0.0,
        'good_ratio': 0.0,
        'deep_ratio': 0.0,
        'thickness_min': 0.0,
        'thickness_median': 0.0,
        'thickness_max': 0.0,
        'min_thick': 0.0,
        'max_thick': 0.0,
        'per_face': [],  # list of (category, thickness_or_0)
    }
    if face_count == 0:
        return empty

    min_thick = float(THICKNESS_MIN_MM) * float(mm_unit_factor)
    max_thick = float(THICKNESS_MAX_MM) * float(mm_unit_factor)
    # Ray length: allow finding the opposite shell wall, not the far side of a room.
    ray_len = max(max_thick * 4.0, min_thick * 20.0)
    eps = max(min_thick * 0.05, 1e-7)

    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bmesh.ops.triangulate(bm, faces=bm.faces[:])
        bm.faces.ensure_lookup_table()
        tree = BVHTree.FromBMesh(bm, epsilon=0.0)
    finally:
        bm.free()

    per_face = []
    thicknesses = []
    hit_count = 0
    no_hit_count = 0
    good_count = 0
    thin_count = 0
    deep_count = 0

    for poly in mesh.polygons:
        origin = mathutils.Vector(poly.center) - mathutils.Vector(poly.normal) * eps
        direction = -mathutils.Vector(poly.normal)
        hit = tree.ray_cast(origin, direction, ray_len)
        if hit[0] is None:
            no_hit_count += 1
            per_face.append(('no_shell', 0.0))
            continue
        dist = float(hit[3])
        hit_count += 1
        thicknesses.append(dist)
        if dist < min_thick:
            thin_count += 1
            per_face.append(('thin', dist))
        elif dist > max_thick:
            deep_count += 1
            per_face.append(('deep', dist))
        else:
            good_count += 1
            per_face.append(('ok', dist))

    sample = face_count
    return {
        'face_count': face_count,
        'sample_count': sample,
        'hit_count': hit_count,
        'no_hit_count': no_hit_count,
        'good_count': good_count,
        'thin_count': thin_count,
        'deep_count': deep_count,
        'no_hit_ratio': (no_hit_count / sample) if sample else 0.0,
        'good_ratio': (good_count / sample) if sample else 0.0,
        'deep_ratio': (deep_count / sample) if sample else 0.0,
        'thickness_min': min(thicknesses) if thicknesses else 0.0,
        'thickness_median': _median(thicknesses),
        'thickness_max': max(thicknesses) if thicknesses else 0.0,
        'min_thick': min_thick,
        'max_thick': max_thick,
        'per_face': per_face,
    }


def paint_geometry_diag_colors(obj__, thickness_result):
    """Write FACE color attribute LQFL_Diag for viewport Attribute shading."""
    mesh = obj__.data
    per_face = thickness_result.get('per_face') or []
    if len(per_face) != len(mesh.polygons):
        return False

    colors = {
        'ok': (0.15, 0.75, 0.25, 1.0),
        'thin': (0.95, 0.55, 0.1, 1.0),
        'deep': (0.35, 0.35, 0.95, 1.0),
        'no_shell': (0.95, 0.15, 0.15, 1.0),
    }

    attr = mesh.color_attributes.get(GEOMETRY_DIAG_ATTR)
    if attr is None:
        attr = mesh.color_attributes.new(
            name=GEOMETRY_DIAG_ATTR,
            type='BYTE_COLOR',
            domain='CORNER',
        )
    elif attr.domain != 'CORNER':
        mesh.color_attributes.remove(attr)
        attr = mesh.color_attributes.new(
            name=GEOMETRY_DIAG_ATTR,
            type='BYTE_COLOR',
            domain='CORNER',
        )

    for poly, (category, _dist) in zip(mesh.polygons, per_face):
        col = colors.get(category, colors['no_shell'])
        for li in range(poly.loop_start, poly.loop_start + poly.loop_total):
            attr.data[li].color = col

    try:
        for i, layer in enumerate(mesh.color_attributes):
            if layer.name == GEOMETRY_DIAG_ATTR:
                mesh.color_attributes.active_color_index = i
                if hasattr(mesh.color_attributes, 'render_color_index'):
                    mesh.color_attributes.render_color_index = i
                break
        mesh.color_attributes.active_color = attr
    except Exception:
        pass
    mesh.update()
    return True


def clear_geometry_diag_colors(obj__):
    mesh = getattr(obj__, 'data', None)
    if mesh is None:
        return
    attr = mesh.color_attributes.get(GEOMETRY_DIAG_ATTR)
    if attr is not None:
        mesh.color_attributes.remove(attr)


def ensure_geometry_diag_node_group():
    """Build (or reuse) a small GN that highlights boundary edges for preview."""
    existing = bpy.data.node_groups.get(GEOMETRY_DIAG_NG_NAME)
    if (
        existing is not None
        and existing.get('liquifeel_diag_version') == GEOMETRY_DIAG_VERSION
    ):
        return existing
    if existing is not None:
        bpy.data.node_groups.remove(existing)

    ng = bpy.data.node_groups.new(GEOMETRY_DIAG_NG_NAME, 'GeometryNodeTree')
    ng['liquifeel_diag_version'] = GEOMETRY_DIAG_VERSION

    # Clear auto-created nodes
    for node in list(ng.nodes):
        ng.nodes.remove(node)

    iface = ng.interface
    iface.new_socket(name='Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    sock_radius = iface.new_socket(
        name='Rim Radius', in_out='INPUT', socket_type='NodeSocketFloat')
    sock_radius.default_value = 0.001
    sock_radius.min_value = 0.0
    sock_radius.max_value = 1.0
    iface.new_socket(name='Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')

    nodes = ng.nodes
    links = ng.links

    n_in = nodes.new('NodeGroupInput')
    n_in.location = (-800, 0)
    n_out = nodes.new('NodeGroupOutput')
    n_out.location = (600, 0)

    # Boundary edges → curve → tube, joined with original mesh for rim viz.
    n_split = nodes.new('GeometryNodeSplitEdges')
    n_split.location = (-500, -120)

    n_edge_neighbors = nodes.new('GeometryNodeInputMeshEdgeNeighbors')
    n_edge_neighbors.location = (-700, -280)

    n_cmp = nodes.new('FunctionNodeCompare')
    n_cmp.data_type = 'INT'
    n_cmp.operation = 'EQUAL'
    n_cmp.location = (-500, -280)
    n_cmp.inputs['B'].default_value = 1  # Face Count == 1 → boundary

    # Separate Geometry (EDGE) with boundary selection → rim curves.
    n_sep = nodes.new('GeometryNodeSeparateGeometry')
    n_sep.domain = 'EDGE'
    n_sep.location = (-300, 40)

    n_m2c = nodes.new('GeometryNodeMeshToCurve')
    n_m2c.location = (-80, 40)

    n_circle = nodes.new('GeometryNodeCurvePrimitiveCircle')
    n_circle.location = (-80, -160)
    try:
        n_circle.mode = 'RADIUS'
    except Exception:
        pass

    n_c2m = nodes.new('GeometryNodeCurveToMesh')
    n_c2m.location = (140, 40)

    n_join = nodes.new('GeometryNodeJoinGeometry')
    n_join.location = (360, 0)

    links.new(n_in.outputs['Geometry'], n_sep.inputs['Geometry'])
    links.new(n_edge_neighbors.outputs['Face Count'], n_cmp.inputs['A'])
    links.new(n_cmp.outputs['Result'], n_sep.inputs['Selection'])

    links.new(n_sep.outputs['Selection'], n_m2c.inputs['Mesh'])
    links.new(n_m2c.outputs['Curve'], n_c2m.inputs['Curve'])
    try:
        links.new(n_in.outputs['Rim Radius'], n_circle.inputs['Radius'])
    except Exception:
        pass
    links.new(n_circle.outputs['Curve'], n_c2m.inputs['Profile Curve'])

    links.new(n_in.outputs['Geometry'], n_join.inputs['Geometry'])
    links.new(n_c2m.outputs['Mesh'], n_join.inputs['Geometry'])
    links.new(n_join.outputs['Geometry'], n_out.inputs['Geometry'])

    # Remove unused leftover from earlier draft
    try:
        ng.nodes.remove(n_split)
    except Exception:
        pass

    return ng


def has_geometry_diag_modifier(obj__):
    for mod in obj__.modifiers:
        if (
            mod.type == 'NODES'
            and mod.node_group is not None
            and mod.node_group.name == GEOMETRY_DIAG_NG_NAME
        ):
            return True
    return False


def assign_geometry_diag_modifier(obj__, rim_radius):
    """Add/replace diagnostic GN modifier at the top of the stack."""
    ng = ensure_geometry_diag_node_group()
    # Remove existing diag mods
    for mod in list(obj__.modifiers):
        if (
            mod.type == 'NODES'
            and (
                mod.name == GEOMETRY_DIAG_NG_NAME
                or mod.name.startswith(GEOMETRY_DIAG_NG_NAME + '.')
                or (mod.node_group and mod.node_group.name == GEOMETRY_DIAG_NG_NAME)
            )
        ):
            obj__.modifiers.remove(mod)

    mod = obj__.modifiers.new(name=GEOMETRY_DIAG_NG_NAME, type='NODES')
    mod.node_group = ng
    # Move to top so it runs on raw mesh before fill.
    try:
        obj__.modifiers.move(obj__.modifiers.find(mod.name), 0)
    except Exception:
        pass
    # Set rim radius socket if present
    try:
        for item in ng.interface.items_tree:
            if getattr(item, 'name', None) == 'Rim Radius' and getattr(item, 'in_out', None) == 'INPUT':
                key = item.identifier
                if key in mod:
                    mod[key] = float(rim_radius)
                break
    except Exception:
        pass
    return mod


def remove_geometry_diag_modifier(obj__):
    removed = False
    for mod in list(obj__.modifiers):
        if (
            mod.type == 'NODES'
            and (
                mod.name == GEOMETRY_DIAG_NG_NAME
                or mod.name.startswith(GEOMETRY_DIAG_NG_NAME + '.')
                or (mod.node_group and mod.node_group.name == GEOMETRY_DIAG_NG_NAME)
            )
        ):
            obj__.modifiers.remove(mod)
            removed = True
    return removed


def set_viewport_attribute_color(context):
    """Show color attributes in Solid viewport shading."""
    screen = getattr(context, 'screen', None)
    if screen is None:
        return
    for area in screen.areas:
        if area.type != 'VIEW_3D':
            continue
        for space in area.spaces:
            if space.type != 'VIEW_3D':
                continue
            space.shading.type = 'SOLID'
            try:
                space.shading.color_type = 'VERTEX'
            except Exception:
                pass
            area.tag_redraw()


def append_thickness_report_lines(lines, thickness, issue_c):
    """Append wall-thickness lines; return updated issue_c."""
    if thickness['face_count'] == 0:
        return issue_c

    no_hit_r = thickness['no_hit_ratio']
    deep_r = thickness['deep_ratio']
    good_r = thickness['good_ratio']
    tmed = thickness['thickness_median']
    tmin = thickness['thickness_min']
    tmax = thickness['thickness_max']
    band_lo = thickness['min_thick']
    band_hi = thickness['max_thick']

    lines.append(
        f"Wall thickness (raycast): median={tmed:.5g}, "
        f"min={tmin:.5g}, max={tmax:.5g} "
        f"(expected shell ~{band_lo:.5g}–{band_hi:.5g})."
    )
    lines.append(
        f"  faces: ok={thickness['good_count']}, "
        f"no opposite={thickness['no_hit_count']}, "
        f"thin={thickness['thin_count']}, deep={thickness['deep_count']}."
    )

    if no_hit_r >= NO_SHELL_PROBLEM_RATIO:
        issue_c += 1
        lines.append(
            f'[Problem] {no_hit_r * 100:.0f}% faces have no opposite wall — '
            'mesh looks single-surface (not a hollow vessel).'
        )
        lines.append(
            'Fix: give the recipient real wall thickness (Solidify / rebuild '
            'inner+outer surfaces), then re-check.'
        )
    elif no_hit_r >= NO_SHELL_WARNING_RATIO:
        lines.append(
            f'[Warning] {no_hit_r * 100:.0f}% faces have no opposite wall — '
            'opening/rim is OK, but large areas may lack a shell.'
        )

    if deep_r >= DEEP_HIT_WARNING_RATIO and good_r < 0.25:
        lines.append(
            f'[Warning] {deep_r * 100:.0f}% hits are deeper than max wall '
            f'({band_hi:.5g}) — object may be a solid block, not a bottle shell.'
        )

    if good_r >= 0.5 and no_hit_r < NO_SHELL_PROBLEM_RATIO:
        lines.append(
            f'[OK] Wall shell looks present on {good_r * 100:.0f}% of faces.'
        )

    return issue_c


def analyze_opening_loops(obj__):
    """Boundary edge loops — bottle mouth detection for Select Outer."""
    mesh = obj__.data
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()
        boundary = [e for e in bm.edges if e.is_boundary]
        visited = set()
        loops = []
        for start in boundary:
            if start in visited:
                continue
            loop_edges = []
            e = start
            prev_v = e.verts[0]
            guard = 0
            while e is not None and e not in visited and guard < 100000:
                visited.add(e)
                loop_edges.append(e)
                # step to next boundary edge through the other vert
                nxt = None
                for v in e.verts:
                    if v == prev_v:
                        continue
                    for e2 in v.link_edges:
                        if e2 is e or e2 in visited or not e2.is_boundary:
                            continue
                        nxt = e2
                        prev_v = v
                        break
                    if nxt is not None:
                        break
                e = nxt
                guard += 1
            if not loop_edges:
                continue
            # loop stats in object space
            coords = []
            for le in loop_edges:
                coords.append(le.verts[0].co)
                coords.append(le.verts[1].co)
            zs = [c.z for c in coords]
            xs = [c.x for c in coords]
            ys = [c.y for c in coords]
            z_avg = sum(zs) / len(zs)
            radius = 0.0
            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)
            for c in coords:
                radius = max(radius, ((c.x - cx) ** 2 + (c.y - cy) ** 2) ** 0.5)
            loops.append({
                'edge_count': len(loop_edges),
                'z_avg': z_avg,
                'z_min': min(zs),
                'z_max': max(zs),
                'radius': radius,
            })
    finally:
        bm.free()

    loops.sort(key=lambda L: L['edge_count'], reverse=True)
    # Object Z extent for "is mouth near top?"
    zs_all = [v.co.z for v in mesh.vertices] if mesh.vertices else [0.0]
    z0, z1 = min(zs_all), max(zs_all)
    z_span = max(z1 - z0, 1e-12)
    mouth = None
    if loops:
        # Prefer largest loop that sits in the upper 35% of height
        upper = []
        for L in loops:
            t = (L['z_avg'] - z0) / z_span
            if t >= 0.65:
                upper.append(L)
        mouth = upper[0] if upper else loops[0]
        if mouth is not None:
            mouth = dict(mouth)
            mouth['height_frac'] = (mouth['z_avg'] - z0) / z_span

    return {
        'loop_count': len(loops),
        'loops': loops[:8],
        'mouth': mouth,
        'z_min': z0,
        'z_max': z1,
        'boundary_edge_count': sum(L['edge_count'] for L in loops),
    }


def analyze_orientation(obj__):
    """Bottle should stand mostly upright (local Z ≈ world up)."""
    mw = obj__.matrix_world
    z_axis = mw.to_3x3() @ mathutils.Vector((0.0, 0.0, 1.0))
    if z_axis.length > 1e-12:
        z_axis.normalize()
    else:
        z_axis = mathutils.Vector((0.0, 0.0, 1.0))
    world_up = mathutils.Vector((0.0, 0.0, 1.0))
    dot = abs(z_axis.dot(world_up))
    dims = tuple(float(v) for v in obj__.dimensions)
    axes = ('X', 'Y', 'Z')
    tallest = axes[max(range(3), key=lambda i: dims[i])] if any(dims) else 'Z'
    return {
        'local_z_dot_world_z': float(dot),
        'dimensions': dims,
        'tallest_axis': tallest,
        'sideways': dot < 0.5,
        'flat': (
            max(dims) > 1e-8 and min(dims) / max(dims) < 0.05
        ),
    }


def analyze_normals_vs_centroid(obj__):
    """How face normals relate to mesh centroid (shell inner/outer cue)."""
    mesh = obj__.data
    if not mesh.vertices or not mesh.polygons:
        return {
            'toward_centroid': 0,
            'away_centroid': 0,
            'toward_ratio': 0.0,
            'mixed_shell_like': False,
        }
    centroid = mathutils.Vector((0.0, 0.0, 0.0))
    for v in mesh.vertices:
        centroid += v.co
    centroid /= len(mesh.vertices)
    toward = 0
    away = 0
    for poly in mesh.polygons:
        n = mathutils.Vector(poly.normal)
        to_c = centroid - mathutils.Vector(poly.center)
        if to_c.length < 1e-12:
            continue
        if n.dot(to_c) > 0.0:
            toward += 1  # normal points toward centroid
        else:
            away += 1
    total = toward + away
    toward_r = (toward / total) if total else 0.0
    # Real bottle shell: outer faces point away, inner toward → both present.
    mixed = 0.15 <= toward_r <= 0.85
    return {
        'toward_centroid': toward,
        'away_centroid': away,
        'toward_ratio': toward_r,
        'mixed_shell_like': mixed,
    }


def append_fill_geometry_probe_lines(lines, obj__, issue_c):
    """Opening / orientation / normals — why Select Outer + Boolean fail."""
    lines.append('--- FILL GEOMETRY PROBE (why liquid may fail) ---')
    opening = analyze_opening_loops(obj__)
    orient = analyze_orientation(obj__)
    normals = analyze_normals_vs_centroid(obj__)

    lines.append(
        f"Opening: {opening['loop_count']} boundary loop(s), "
        f"{opening['boundary_edge_count']} boundary edges, "
        f"Z range [{opening['z_min']:.4g} … {opening['z_max']:.4g}]."
    )
    mouth = opening.get('mouth')
    if opening['loop_count'] == 0:
        issue_c += 1
        lines.append(
            '[Problem] No open rim (0 boundary loops). '
            'Select Outer needs a mouth opening — sealed mesh cannot be filled.'
        )
        lines.append(
            'Fix: open the bottle mouth (delete top cap faces) or enable Seal '
            'only after Select Outer can find a rim.'
        )
    elif mouth is None:
        lines.append('[Warning] Could not identify a mouth loop.')
    else:
        hf = mouth.get('height_frac', 0.0)
        lines.append(
            f"Mouth candidate: {mouth['edge_count']} edges, "
            f"z_avg={mouth['z_avg']:.4g} ({hf * 100:.0f}% of height), "
            f"radius≈{mouth['radius']:.4g}."
        )
        if hf < 0.55:
            lines.append(
                '[Warning] Largest/upper rim is not near the top — '
                'bottle may be upside-down or opening is on the side. '
                'Select Outer / Liquid Level will misbehave.'
            )
        else:
            lines.append('[OK] Mouth loop sits near the top of the mesh.')
        if opening['loop_count'] > 3:
            lines.append(
                f"[Warning] {opening['loop_count']} openings — "
                'extra holes confuse interior detection. Close unintended holes.'
            )

    lines.append(
        f"Orientation: tallest={orient['tallest_axis']}, "
        f"|localZ·worldUp|={orient['local_z_dot_world_z']:.3f}, "
        f"dims={tuple(round(v, 4) for v in orient['dimensions'])}."
    )
    if orient['sideways']:
        issue_c += 1
        lines.append(
            '[Problem] Bottle looks sideways (local Z not aligned with world up). '
            'Rotate upright, then Apply Rotation.'
        )
    elif orient['tallest_axis'] != 'Z':
        lines.append(
            f"[Warning] Tallest axis is {orient['tallest_axis']}, not Z — "
            'Fill height map assumes upright Z.'
        )
    else:
        lines.append('[OK] Orientation looks upright.')
    if orient['flat']:
        lines.append(
            '[Warning] Bounds are extremely flat — unlikely to be a fillable vessel.'
        )

    lines.append(
        f"Normals vs centroid: toward={normals['toward_centroid']}, "
        f"away={normals['away_centroid']} "
        f"(toward_ratio={normals['toward_ratio'] * 100:.0f}%)."
    )
    n_total = normals['toward_centroid'] + normals['away_centroid']
    if n_total == 0:
        lines.append('[Warning] Could not evaluate face normals vs centroid.')
    elif not normals['mixed_shell_like']:
        lines.append(
            '[Warning] Normals are almost all one-sided vs centroid — '
            'typical of a single surface or consistently flipped shell. '
            'Recalculate Outside, ensure inner+outer walls.'
        )
    else:
        lines.append(
            '[OK] Normals look mixed (inner/outer shell pattern).'
        )

    return issue_c, {
        'opening': opening,
        'orientation': orient,
        'normals': normals,
    }
