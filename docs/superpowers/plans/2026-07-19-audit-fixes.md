# LiquiFeel Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 14 verified findings from the 2026-07-19 full-codebase audit (7 Important, 7 Minor) — one silent feature failure, one lifecycle bug, a crash-prone legacy code chain, missing guards, and test-hygiene gaps.

**Architecture:** LiquiFeel is a single-file Blender 5.2 addon: `__init__.py` (~14.7k lines) plus `geometry_diag.py`. All fixes are surgical edits to those two files and the test scripts. The legacy shading chain (Tasks 5–6) is deleted rather than repaired because the `hrdc_*` twins are what the real UI uses.

**Tech Stack:** Python 3 (Blender's bundled interpreter), bpy API for Blender 5.2 LTS, background-mode smoke tests.

**Scope note (decided 2026-07-19):** this plan is Phase 1 — bug fixes only, on the existing single-file layout. Phase 2 (splitting `__init__.py` ~14.7k lines into functional modules: properties / operators / panels / shading / assembly / data) gets its own plan AFTER all tasks here are green. Do not mix the split into these tasks.

---

## Verification commands (used throughout)

```bash
BLENDER=/Applications/blender/stable/blender-5.2.0-macos-arm64+lts.fbe6228777e7/Blender.app/Contents/MacOS/Blender

# Fast syntax gate (no Blender needed)
python3 -m py_compile __init__.py geometry_diag.py

# Pure-python helper checks
python3 tests/test_assembly_helpers.py

# Full smoke test — capture exit code IMMEDIATELY, never after a pipe
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py; echo "exit=$?"
# Expected: exit=0 and the line "All assembly smoke checks passed."

# Geometry-diag smoke test
"$BLENDER" --background --python tests/run_geometry_diag_smoke.py; echo "exit=$?"
# Expected: exit=0, no "FAIL:" lines
```

**Noise to ignore:** a stale installed copy at `~/Library/Application Support/Blender/5.2/scripts/addons/liquifeel/` prints a harmless `Exception in module unregister()` / `unregister_class ... missing bl_rna` at Blender startup/shutdown. Only the test's own OK/FAIL output and exit code matter.

**Line numbers** in this plan are as of commit `cbb48a8`. Tasks 5–6 delete large blocks, so later tasks must match code by **content**, not line number.

---

### Task 1: Rim Radius socket is silently never applied on Blender 5.2 (Important)

On Blender 5.2, `key in mod` on a NodesModifier raises `TypeError: this type doesn't support IDProperties`; the surrounding `except Exception: pass` swallows it, so the Rim Radius socket keeps its 0.001 default and the rim tube renders ~500× too thin. Fix by writing through `mod.properties.inputs.<identifier>.value` (the Blender 5.x path), keeping `mod[key]` only as the pre-5.x fallback.

**Files:**
- Modify: `geometry_diag.py:294-326` (`assign_geometry_diag_modifier`)
- Test: `tests/run_geometry_diag_smoke.py` (add assertion after the first toggle block, after the `LiquiFeel_GeometryDiag node group exists` check ~line 141)

- [ ] **Step 1: Write the failing test**

In `tests/run_geometry_diag_smoke.py`, insert after the `Diagnostic node group missing` check (the `if bpy.data.node_groups.get(...)` block ending ~line 141) and **before** the second `toggle_geometry_diag` call:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
"$BLENDER" --background --python tests/run_geometry_diag_smoke.py; echo "exit=$?"
```
Expected: `FAIL: Rim Radius socket not applied: 0.001 != 0.5` and non-zero exit (or the FAIL line counted in the script's error summary).

- [ ] **Step 3: Fix `assign_geometry_diag_modifier`**

In `geometry_diag.py`, add near the top of the file (after the `GEOMETRY_DIAG_VERSION = 1` constant, do NOT import from the package root — that would be circular):

```python
# Blender 5.x: geometry-nodes modifier inputs moved from id properties
# (mod[identifier]) to mod.properties.inputs.<identifier>.value.
GEONODE_INPUTS_VIA_PROPERTIES = 'properties' in bpy.types.NodesModifier.bl_rna.properties
```

Replace the socket-write block in `assign_geometry_diag_modifier` (lines 316-325):

```python
    # Set rim radius socket if present
    try:
        for item in ng.interface.items_tree:
            if getattr(item, 'name', None) == 'Rim Radius' and getattr(item, 'in_out', None) == 'INPUT':
                key = item.identifier
                if GEONODE_INPUTS_VIA_PROPERTIES:
                    getattr(mod.properties.inputs, key).value = float(rim_radius)
                    # writing .value does not tag the depsgraph
                    mod.id_data.update_tag()
                else:
                    mod[key] = float(rim_radius)
                break
    except Exception as e:
        # A failed write must be visible — a silent no-op caused this bug.
        print(f'LiquiFeel geometry_diag: Rim Radius write failed: {e}')
    return mod
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
python3 -m py_compile geometry_diag.py
"$BLENDER" --background --python tests/run_geometry_diag_smoke.py; echo "exit=$?"
```
Expected: `OK: Rim Radius socket applied (0.5)`, exit=0, no FAIL lines.

- [ ] **Step 5: Commit**

```bash
git add geometry_diag.py tests/run_geometry_diag_smoke.py
git commit -m "fix: write Rim Radius via properties.inputs on Blender 5.2 (was silently ignored)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `unregister()` aborts entirely if any single class fails (Important)

One `missing bl_rna` failure skips deletion of the four pointer properties and `_unload_preview_collections()` (~120 leaked previews, dangling RNA pointers, confusing next enable). Make every step independent and unregister classes in reverse order.

**Files:**
- Modify: `__init__.py:14710-14724` (`unregister`)

- [ ] **Step 1: Replace `unregister()`**

Current code (lines 14710-14724):

```python
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

    _unload_preview_collections()
```

Replace with:

```python
def unregister():
    _unregister_separate_timers()
    _mesh_island_count_cache.clear()
    for cls in reversed(get_classes()):
        try:
            bpy.utils.unregister_class(cls)
        except Exception as e:
            print(f'LIQUIFEEL: unregister_class({cls.__name__}) failed: {e}')
    for owner, attr in (
            (bpy.types.Scene, 'liquifeel_general_controls'),
            (bpy.types.Scene, 'liquifeel_misc_data'),
            (bpy.types.Object, 'hrdc_liquifeel_input_field_props'),
            (bpy.types.Material, 'hrdc_liquifeel_input_field_props')):
        try:
            delattr(owner, attr)
        except Exception as e:
            print(f'LIQUIFEEL: removing {owner.__name__}.{attr} failed: {e}')
    _unload_preview_collections()
```

- [ ] **Step 2: Verify**

```bash
python3 -m py_compile __init__.py
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py; echo "exit=$?"
```
Expected: exit=0, `All assembly smoke checks passed.` (the smoke test's `load_addon()` calls `unregister()` then `register()`, so both paths are exercised).

- [ ] **Step 3: Commit**

```bash
git add __init__.py
git commit -m "fix: make unregister() failure-tolerant (reversed order, per-item guards)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: None guards missing in slot-shading update callbacks (Important)

`resolve_liquifeel_source_object` can return None (`__init__.py:6930-6933`); `hrdc_slot_shade` then does `'liquifeel' not in obj__.keys()` → AttributeError inside an RNA update callback. The fill twins already guard (lines 8820, 8835).

**Files:**
- Modify: `__init__.py:8810-8830` (`hrdc_slot_shading_material_update`, `hrdc_scene_slot_shading_material_update`)

- [ ] **Step 1: Add the guards**

Change:

```python
@undo_push(2)
def hrdc_slot_shading_material_update(slf, context):
    obj__ = resolve_liquifeel_source_object(context.active_object)
    library_key = getattr(slf, 'library')
```

to:

```python
@undo_push(2)
def hrdc_slot_shading_material_update(slf, context):
    obj__ = resolve_liquifeel_source_object(context.active_object)
    if obj__ is None:
        return
    library_key = getattr(slf, 'library')
```

and change:

```python
@undo_push(2)
def hrdc_scene_slot_shading_material_update(slf, context):
    obj__ = resolve_liquifeel_source_object(context.active_object)
    material_name = getattr(slf, 'scene_material')
```

to:

```python
@undo_push(2)
def hrdc_scene_slot_shading_material_update(slf, context):
    obj__ = resolve_liquifeel_source_object(context.active_object)
    if obj__ is None:
        return
    material_name = getattr(slf, 'scene_material')
```

- [ ] **Step 2: Verify and commit**

```bash
python3 -m py_compile __init__.py
python3 tests/test_assembly_helpers.py
git add __init__.py
git commit -m "fix: guard slot-shading update callbacks against None source object

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: `append_data` failures surface as raw tracebacks (Important)

`bpy.data.libraries.load` raises OSError when the master .blend is missing/corrupt; `get_append_name(...)[0]` raises bare IndexError when the requested datablock doesn't exist (realistic case: version-mismatched `LiquidFeel_MASTER.blend`). Users get a cryptic popup.

**Files:**
- Modify: `__init__.py:10067-10072` (`append_data`)

- [ ] **Step 1: Wrap `append_data`**

Current code:

```python
def append_data(posix_filepath, category_key, name_substring):
    with bpy.data.libraries.load(str(posix_filepath)) as (data_from, data_to):
        dat_name = get_append_name(data_from, category_key, name_substring)
        setattr(data_to, category_key, [dat_name])
    dat = getattr(data_to, category_key)[0]
    return dat
```

Replace with:

```python
def append_data(posix_filepath, category_key, name_substring):
    try:
        with bpy.data.libraries.load(str(posix_filepath)) as (data_from, data_to):
            dat_name = get_append_name(data_from, category_key, name_substring)
            setattr(data_to, category_key, [dat_name])
    except OSError as e:
        raise RuntimeError(
            f'LiquiFeel: cannot read asset library {posix_filepath}: {e}') from e
    except IndexError:
        raise RuntimeError(
            f'LiquiFeel: no {category_key} matching {name_substring!r} in '
            f'{posix_filepath} — addon / master-blend version mismatch?') from None
    dat = getattr(data_to, category_key)[0]
    return dat
```

(The `RuntimeError` message reaches the user via Blender's operator error popup and names both the blend path and the missing datablock.)

- [ ] **Step 2: Verify and commit**

```bash
python3 -m py_compile __init__.py
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py; echo "exit=$?"
git add __init__.py
git commit -m "fix: self-diagnosing errors when master blend is missing or lacks a datablock

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Delete the legacy fill_shade chain (Important — latent NameError)

`assign_default_values_to_target_inputs` (line 12493) calls setters with undefined `prop_parent` → NameError. Its only caller is legacy `fill_shade` (12408), reachable via operator `liquifeel.shade_active_object_via_fill` (F3 search only — no panel draws it). The `hrdc_*` twins (used by the real UI) stay.

**Files:**
- Modify: `__init__.py` — delete three blocks at 12385-12414, 12449-12458, 12474-12493

- [ ] **Step 1: Confirm nothing else references the trio**

```bash
grep -n "fill_shade\b\|shade_active_object_via_fill\|assign_default_values_to_target_inputs\b\|ShadeActiveObjectViaFill\b" __init__.py tests/*.py
```
Expected: only the definitions/registrations listed below, the `hrdc_`-prefixed twins (keep those — grep with `\b` excludes `hrdc_fill_shade` but check output carefully), and `tests/test_assembly_helpers.py` if it greps for any of these (adjust the test if so).

- [ ] **Step 2: Delete the three blocks**

Delete `def fill_shade(...)` — the whole function starting `# @undo_push(4)` / `def fill_shade(context, obj__, library_key, material_name):` through `schedule_separate_refresh(obj__, force=True)` (lines 12385-12414). Keep `hrdc_fill_shade` immediately after it.

Delete the operator class and its registration (lines 12449-12458):

```python
class ShadeActiveObjectViaFill(bpy.types.Operator):
    bl_idname = 'liquifeel.shade_active_object_via_fill'
    ...
registerable_classes.append(ShadeActiveObjectViaFill)
```

Keep `HRDC_ShadeActiveObjectViaFill` (12460-12469).

Delete `def assign_default_values_to_target_inputs(...)` — the function plus its two leading comment lines (`# This function handles both the assignment...`), lines 12474-12493, ending at the `prop_parent, obj__, material)` call.

- [ ] **Step 3: Check `get_library_key_and_material_name` for orphaning**

```bash
grep -n "get_library_key_and_material_name" __init__.py
```
If only the bare (non-`hrdc_`) definition remains with no callers, delete that function too. If it has other callers, leave it.

- [ ] **Step 4: Verify**

```bash
python3 -m py_compile __init__.py
python3 tests/test_assembly_helpers.py
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py; echo "exit=$?"
grep -rn "shade_active_object_via_fill" __init__.py && echo "STALE REF" || echo "clean"
```
Expected: all pass, `clean`.

- [ ] **Step 5: Commit**

```bash
git add __init__.py
git commit -m "refactor: delete legacy fill_shade chain (NameError trap; hrdc twins are the live path)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Delete the orphaned generated-setter cluster (Important — second NameError trap)

`set_shader_ng_input_to_value__general_params` (6124-6139) references undefined `val_data` in every branch. It sits in the `underlying_input_setters` dispatch (6148-6152), consumed only by `gen_setter__*` closures, whose products (`input_field_data['setters']`) had exactly one consumer — the function deleted in Task 5 (verified: `grep "\['setters'\]"` hits only line 12491-12492 and a commented line 10622). After Task 5, the whole cluster is dead.

**Files:**
- Modify: `__init__.py` — delete blocks at (pre-Task-5 numbering) 6028-6041, 6124-6152, 6175-6252

- [ ] **Step 1: Prove the cluster is orphaned (must run AFTER Task 5)**

```bash
grep -n "\['setters'\]" __init__.py                 # expect: only commented line ~10622
grep -n "underlying_input_setters\|gen_input_setters\|gen_setter__" __init__.py
```
Expected: hits only inside the 6028-6252 region itself. If anything outside that region references them, STOP and re-audit before deleting.

- [ ] **Step 2: Delete, keeping the live functions**

**KEEP** (used by the live `hrdc` path): `set_geonode_mod_input_to_value` (6011), `set_shader_ng_input_to_value` (6018), `set_geonode_mod_input` (6043), `set_prop_value` / `set_scalar_prop_value` / `set_vectorial_prop_value` (5936-5952).

**DELETE**:
- `set_geonode_mod_input_to_value__general_params` (6028-6041, incl. trailing commented lines)
- `set_shader_ng_input_to_value__general_params` (6124-6139)
- `set_shader_node_input_to_value__general_params` (6141-6146)
- `underlying_input_setters = {...}` (6148-6152)
- `gen_setter__ui_prop_from_default_val` (6175-6184)
- `gen_setter__underlying_input_from_ui_prop` (6193-6206)
- `gen_setter__underlying_input_to_default` (6211-6224)
- `input_types_wo_default_ui_prop_setter` + `gen_input_setters` (6226-6244)
- the module-level augmentation loop `for main_tab_key, main_tab_data in REDUX_INPUT_DATA.items(): ... input_field_data['setters'] = gen_input_setters(input_field_data)` (6246-6252)

- [ ] **Step 3: Grep-gated follow-up deletions**

```bash
grep -n "get_target_attachment_key" __init__.py   # def at 5836
grep -n "set_shader_node_input\b" __init__.py
```
For each: if only the definition remains, delete it too; if there are live callers, keep it.

- [ ] **Step 4: Verify**

```bash
python3 -m py_compile __init__.py
python3 tests/test_assembly_helpers.py
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py; echo "exit=$?"
```
Expected: all green. (The augmentation loop ran at import time, so a successful addon register in the smoke test proves nothing needed it.)

- [ ] **Step 5: Commit**

```bash
git add __init__.py
git commit -m "refactor: delete orphaned generated-setter cluster incl. val_data NameError trap

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: `ExtractMigrationTagData` calls undefined function (Minor, DEV-gated)

Line 12798 calls `extract_migration_tag_data`, which doesn't exist; the intended function is `extract_legacy_asset_tag_data` (defined just above at 12786).

**Files:**
- Modify: `__init__.py:12798`

- [ ] **Step 1: Fix the call**

In `ExtractMigrationTagData.execute`, change:

```python
        pprint(extract_migration_tag_data(context.active_object))
```
to:
```python
        pprint(extract_legacy_asset_tag_data(context.active_object))
```

- [ ] **Step 2: Verify and commit**

```bash
python3 -m py_compile __init__.py
git add __init__.py
git commit -m "fix: ExtractMigrationTagData called nonexistent function (DEV operator)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: `filter_input_data_by_sorting_tag` reads leaked global instead of its parameter (Minor)

Line 5593 uses `mat` (the module-level loop variable that happens to alias the argument today) instead of the `mat_data` parameter. Any future call after import would silently use the last material.

**Files:**
- Modify: `__init__.py:5593`

- [ ] **Step 1: Fix**

In `filter_input_data_by_sorting_tag`, change:

```python
    targets = mat['data']['data']
```
to:
```python
    targets = mat_data['data']['data']
```

- [ ] **Step 2: Verify and commit**

```bash
python3 -m py_compile __init__.py
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py; echo "exit=$?"
git add __init__.py
git commit -m "fix: filter_input_data_by_sorting_tag used leaked global instead of parameter

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Enum item lists embed preview icon ids that go stale on re-enable (Minor)

`main_tab_items` (8719), `recipient_asset_items` (8741), `liquids_shader_items` (8436), `solids_shader_items` (8448) are built once at import with `preview_data['ids'][...]`. On disable→enable, `register()` reloads previews with new ids, so icons render blank/wrong until Blender restarts. `bpy.utils.register_class` reads the items list at registration time, so rebuilding the lists **in place** at the start of `register()` fixes it without touching the EnumProperty definitions (and keeps `default='geometry'`, which a callback-based `items=` would forbid).

**Files:**
- Modify: `__init__.py:8436-8458` (liquids/solids lists), `__init__.py:8719-8748` (tab/asset lists), `register()` (~14696)

- [ ] **Step 1: Wrap the four list builders**

Replace lines 8436-8458 with:

```python
liquids_shader_items = []
def _build_liquids_shader_items():
    """(Re)build in place — preview icon ids change on every addon re-enable."""
    liquids_shader_items.clear()
    for mat_name in INPUT_FIELD_DATA['shading']['liquids'].keys():
        liquids_shader_items.append((
            mat_name, mat_name,
            mat_name,
            preview_data['ids']['material_thumbnails'][
                key_from_name(mat_name)],
            len(liquids_shader_items)
        ))
_build_liquids_shader_items()

solids_shader_items = []
def _build_solids_shader_items():
    solids_shader_items.clear()
    for mat_name in INPUT_FIELD_DATA['shading']['solids'].keys():
        solids_shader_items.append((
            mat_name, mat_name,
            mat_name,
            preview_data['ids']['material_thumbnails'][
                key_from_name(mat_name)],
            len(solids_shader_items)
        ))
_build_solids_shader_items()
```

Replace lines 8719-8732 (`main_tab_items` build loop) with:

```python
main_tab_items = []
def _build_main_tab_items():
    main_tab_items.clear()
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
_build_main_tab_items()
```

Replace lines 8741-8748 (`recipient_asset_items` build loop) with:

```python
recipient_asset_items = []
def _build_recipient_asset_items():
    recipient_asset_items.clear()
    for asset_key, name_data in RECIPIENT_ASSET_NAME_DATA.items():
        recipient_asset_items.append((
            asset_key,
            name_data['thumbnail'], name_data['thumbnail'],
            preview_data['ids']['recipient_asset_thumbnails'][asset_key],
            len(recipient_asset_items)
        ))
_build_recipient_asset_items()
```

- [ ] **Step 2: Rebuild in `register()`**

In `register()`, immediately after `_load_preview_collections()`, add:

```python
    _build_liquids_shader_items()
    _build_solids_shader_items()
    _build_main_tab_items()
    _build_recipient_asset_items()
```

- [ ] **Step 3: Verify**

```bash
python3 -m py_compile __init__.py
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py; echo "exit=$?"
```
Expected: green. The smoke test's unregister→register cycle in `load_addon()` exercises the rebuild path.

- [ ] **Step 4: Commit**

```bash
git add __init__.py
git commit -m "fix: rebuild enum item lists in register() so preview icon ids survive re-enable

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Island-count cache survives file loads; geometry_diag not reloaded on Reload Scripts (Minor)

`_mesh_island_count_cache` is name-keyed and never cleared on opening a different .blend — a same-named object with coincidentally equal vert/edge counts shows a stale island count. Separately, edits to `geometry_diag.py` require a full Blender restart because the reload block is commented out.

**Files:**
- Modify: `__init__.py:31-38` (imports), `__init__.py:~622` (after `count_mesh_islands_cached`), `register()`/`unregister()`

- [ ] **Step 1: Reload `geometry_diag` on script reload**

Replace lines 31-38:

```python
from . import geometry_diag

import importlib

from bpy.app.handlers import persistent

# import properties
# importlib.reload(properties)
```

with:

```python
from . import geometry_diag

import importlib
# Support Blender's "Reload Scripts": re-exec the submodule so edits to
# geometry_diag.py take effect without a Blender restart. Harmless on
# first import (module has no side effects beyond defs).
importlib.reload(geometry_diag)

from bpy.app.handlers import persistent
```

- [ ] **Step 2: Add a load_post handler that clears the cache**

After `count_mesh_islands_cached` (ends ~line 622), add:

```python
@persistent
def _lqfl_clear_island_cache_on_load(_dummy):
    _mesh_island_count_cache.clear()
```

In `register()`, add at the end:

```python
    if _lqfl_clear_island_cache_on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_lqfl_clear_island_cache_on_load)
```

In `unregister()`, add after `_unregister_separate_timers()`:

```python
    try:
        bpy.app.handlers.load_post.remove(_lqfl_clear_island_cache_on_load)
    except ValueError:
        pass
```

- [ ] **Step 3: Verify and commit**

```bash
python3 -m py_compile __init__.py
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py; echo "exit=$?"
git add __init__.py
git commit -m "fix: clear island-count cache on file load; reload geometry_diag on Reload Scripts

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: Data-file load guards, bare excepts, enum string retention (Minor)

Three module-level `json.load` sites fail enable with raw tracebacks on a corrupt install; three `except:` clauses catch `KeyboardInterrupt`/`SystemExit`; `scene_shader_items` returns fresh strings from a dynamic enum callback without keeping references (documented Blender pitfall — labels can garble).

**Files:**
- Modify: `__init__.py` — JSON loads at ~995, ~5564, ~5576; bare excepts at 535, 6503, 8472; `scene_shader_items` at 8460-8473

- [ ] **Step 1: Add a guarded JSON loader**

Immediately above the line `with open(str(FPATHS['recipient_asset_parenting_data']), 'r') as f:` (~line 995), insert:

```python
def _load_bundled_json(fpath):
    try:
        with open(str(fpath), 'r') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise RuntimeError(
            f'LiquiFeel: bundled data file missing or broken: {fpath} ({e})') from e
```

Then replace each of the three load sites:

```python
with open(str(FPATHS['recipient_asset_parenting_data']), 'r') as f:
    RECIPIENT_ASSET_PARENTING_DATA = json.load(f)
```
→ `RECIPIENT_ASSET_PARENTING_DATA = _load_bundled_json(FPATHS['recipient_asset_parenting_data'])`

```python
with open(str(FPATHS['node_socket_data']), 'r') as f:
    NODE_SOCKET_DATA = json.load(f)
```
→ `NODE_SOCKET_DATA = _load_bundled_json(FPATHS['node_socket_data'])`

```python
with open(str(FPATHS['input_ui_type_data']), 'r') as f:
    INPUT_UI_TYPE_DATA = json.load(f)
```
→ `INPUT_UI_TYPE_DATA = _load_bundled_json(FPATHS['input_ui_type_data'])`

- [ ] **Step 2: Narrow the three bare excepts**

- `getattr_rec` (~line 535): `except:` → `except Exception:`
- `has_lqfl_data_structure_attached` (~line 6503): `except:` → `except Exception:`
- `scene_shader_items` (~line 8472): handled in Step 3.

- [ ] **Step 3: Retain enum string references in `scene_shader_items`**

Replace lines 8460-8473:

```python
_scene_shader_items_cache = []

def scene_shader_items(instance, context):
    # Blender does not keep references to dynamic enum item strings;
    # cache the last list so the strings stay alive.
    global _scene_shader_items_cache
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
        _scene_shader_items_cache = items
        return items
    except Exception:
        return _scene_shader_items_cache
```

- [ ] **Step 4: Verify and commit**

```bash
python3 -m py_compile __init__.py
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py; echo "exit=$?"
git add __init__.py
git commit -m "fix: guarded JSON loads, narrowed bare excepts, retained dynamic enum strings

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 12: `debug_panel_draw.py` tests the installed copy, not the working tree (Minor)

It uses `addon_utils.enable('liquifeel')` — the stale installed build — so its panel-draw coverage validates the wrong code. Switch to the `sys.path` + `import LiquiFeel` pattern the smoke tests use.

**Files:**
- Modify: `tests/debug_panel_draw.py:1-7, 19, 57`

- [ ] **Step 1: Rewrite the loader header**

Replace lines 1-7:

```python
"""Reproduce Liquifeel Geometry panel draw crash."""
import sys
import traceback
import bpy
import addon_utils

addon_utils.enable('liquifeel', default_set=True, persistent=True)
```

with:

```python
"""Reproduce Liquifeel Geometry panel draw crash (against the WORKING TREE)."""
import sys
import traceback
from pathlib import Path

import bpy

ADDON_DIR = Path(__file__).resolve().parents[1]
parent = str(ADDON_DIR.parent)
if parent not in sys.path:
    sys.path.insert(0, parent)
import LiquiFeel
try:
    LiquiFeel.unregister()
except Exception:
    pass
LiquiFeel.register()
```

- [ ] **Step 2: Fix the two lowercase imports**

Line 19 (inside the menu draw) and line 57: change `import liquifeel as m` to `import LiquiFeel as m`.

- [ ] **Step 3: Verify and commit**

```bash
"$BLENDER" --background --python tests/debug_panel_draw.py; echo "exit=$?"
```
Expected: exit=0, `DONE`, all three draw probes print `OK` (no `FAIL` + traceback).

```bash
git add tests/debug_panel_draw.py
git commit -m "test: point debug_panel_draw at the working tree, not the installed copy

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 13: Final gate — full verification + static undefined-name scan

**Files:** none modified (verification only; `docs` note optional)

- [ ] **Step 1: Run everything**

```bash
python3 -m py_compile __init__.py geometry_diag.py build_release.py
python3 tests/test_assembly_helpers.py
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py; echo "exit=$?"
"$BLENDER" --background --python tests/run_geometry_diag_smoke.py; echo "exit=$?"
"$BLENDER" --background --python tests/debug_panel_draw.py; echo "exit=$?"
```
Expected: every command exit 0; smoke test prints `All assembly smoke checks passed.`

- [ ] **Step 2: Static undefined-name scan must be clean**

`uvx` is available at `~/.local/bin/uvx` (no ruff install needed):

```bash
uvx ruff check --select F821,F811 __init__.py geometry_diag.py build_release.py
```
Expected: `All checks passed!` — the audit's 5 F821 hits all lived in code deleted/fixed by Tasks 5-7. If anything remains, fix it before finishing.

- [ ] **Step 3: Confirm clean tree state and log**

```bash
git status --short   # expect: empty
git log --oneline cbb48a8..HEAD
```
Expected: ~12 commits matching the tasks above.
