"""Lightweight checks for Bottle Assembly marker helpers (no Blender UI).

Run: python3 tests/test_assembly_helpers.py
"""
from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest import mock


def _install_bpy_stub():
    bpy = types.ModuleType('bpy')
    bpy.data = types.SimpleNamespace(objects={})
    bpy.props = types.SimpleNamespace(
        StringProperty=lambda **kwargs: None,
    )
    bpy.types = types.SimpleNamespace(Operator=object)
    bpy.context = types.SimpleNamespace()
    sys.modules['bpy'] = bpy

    bpy_extras = types.ModuleType('bpy_extras')
    sys.modules['bpy_extras'] = bpy_extras

    mathutils = types.ModuleType('mathutils')
    mathutils.Vector = tuple
    mathutils.Matrix = object
    sys.modules['mathutils'] = mathutils

    idprop = types.ModuleType('idprop')
    idprop.types = types.SimpleNamespace(IDPropertyGroup=dict)
    sys.modules['idprop'] = idprop


class FakeObject:
    def __init__(self, name, obj_type='MESH'):
        self.name = name
        self.type = obj_type
        self.parent = None
        self.children = []
        self._props = {}
        self.matrix_world = f'mw:{name}'
        self.mode = 'OBJECT'
        self.library = None
        self.override_library = None
        self.data = types.SimpleNamespace(library=None)

    def get(self, key, default=None):
        return self._props.get(key, default)

    def keys(self):
        return self._props.keys()

    def __contains__(self, key):
        return key in self._props

    def __getitem__(self, key):
        return self._props[key]

    def __setitem__(self, key, value):
        self._props[key] = value

    def pop(self, key, *args):
        return self._props.pop(key, *args) if args else self._props.pop(key)


class AssemblyHelperTests(unittest.TestCase):
    """API-presence checks only (the addon can't import without Blender).

    Real behavioral coverage of assembly/scale logic lives in
    tests/run_assembly_blender_smoke.py -- run that under `blender --background`.
    """
    @classmethod
    def setUpClass(cls):
        _install_bpy_stub()
        # Import only the helper section by exec'ing a minimal slice is hard;
        # instead re-implement the core normalize/parent logic mirrors used in
        # assertions against the real source text, and import helpers if the
        # addon module can load. Prefer importing functions after stubbing.
        root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(root))
        # Addon __init__ pulls many Blender-only deps; test pure helpers copied
        # from the design contract instead of full import.
        cls.root = root

    def test_source_contains_assembly_api(self):
        src = (self.root / '__init__.py').read_text(encoding='utf-8')
        for needle in [
            'liquifeel.assembly_set_bottle',
            'liquifeel.assembly_assign_cork',
            'liquifeel.assembly_assign_label',
            'liquifeel.assembly_add_extra',
            'liquifeel.assembly_remove_member',
            'liquifeel.assembly_clear',
            'def draw_assembly_ui',
            '_lqfl_strip_fill_keys_keep_assembly',
            'list_assembly_member_objects',
            'parent_keep_transform',
        ]:
            self.assertIn(needle, src)

    def test_apply_fill_includes_assembly_members_in_collection(self):
        src = (self.root / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('[obj__, liquid_obj] + assembly_members', src)
        self.assertIn('list_assembly_member_objects(obj__)', src)

    def test_clear_fill_preserves_assembly(self):
        src = (self.root / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('if has_assembly(obj__):', src)
        self.assertIn('_lqfl_strip_fill_keys_keep_assembly(obj__)', src)


if __name__ == '__main__':
    unittest.main()
