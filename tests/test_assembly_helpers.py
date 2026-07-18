"""Lightweight checks for Bottle Assembly marker helpers (no Blender UI).

Run: python3 tests/test_assembly_helpers.py
"""
from __future__ import annotations

import unittest
from pathlib import Path


class AssemblyHelperTests(unittest.TestCase):
    """API-presence checks only (the addon can't import without Blender).

    Real behavioral coverage of assembly/scale logic lives in
    tests/run_assembly_blender_smoke.py -- run that under `blender --background`.
    """
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]

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

    def test_builds_on_copies_not_originals(self):
        src = (self.root / '__init__.py').read_text(encoding='utf-8')
        # Set as Bottle builds on a COPY in a new top-level collection.
        self.assertIn('def clone_object_into_liquifeel_collection', src)
        self.assertIn('def make_bottle_geometry_backup', src)
        self.assertIn('def remove_liquifeel_collection', src)
        # Members are cloned into the collection at the assign choke point.
        self.assertIn('clone_object_into_liquifeel_collection(\n'
                      '            bpy.context, member, col', src)
        # The old move-based fill relocation must be gone.
        self.assertNotIn('[obj__, liquid_obj] + assembly_members', src)

    def test_clear_fill_preserves_assembly(self):
        src = (self.root / '__init__.py').read_text(encoding='utf-8')
        self.assertIn('if has_assembly(obj__):', src)
        self.assertIn('_lqfl_strip_fill_keys_keep_assembly(obj__)', src)


if __name__ == '__main__':
    unittest.main()
