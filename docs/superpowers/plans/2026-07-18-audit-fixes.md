# LiquiFeel Audit Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the two critical defects found in the 2026-07-18 code audit (broken Opening Type "Straight" callback, import-time pip install), remove the per-redraw mesh-island performance hotspot, and purge ~30% of the codebase that is verified dead (4 whole modules, duplicate definitions, an unreachable legacy UI pipeline, ~1,450 lines of commented-out code).

**Architecture:** All live code is in `__init__.py` (~17k lines) of a Blender addon. Fixes are surgical edits verified by the existing Blender background smoke test; dead-code removal is grep-verified per symbol before deletion (Blender invokes operators via `bl_idname` strings, so every deletion must check string references, not just call sites).

**Tech Stack:** Python 3 (Blender's bundled interpreter), Blender 4.x/5.x `bpy` API, no external deps. Tests run via `blender --background --python tests/run_assembly_blender_smoke.py`.

---

## Conventions used in this plan

- **`$BLENDER`** = path to the Blender binary. On this machine try:
  `BLENDER=/Applications/Blender.app/Contents/MacOS/Blender` (adjust if Blender lives elsewhere; any 4.1+ works).
- **Smoke test** = `"$BLENDER" --background --python tests/run_assembly_blender_smoke.py` run from the repo root's **parent** is not needed — the script inserts the parent dir into `sys.path` itself. Run it from the repo root. Exit code 0 + `All assembly smoke checks passed.` = pass.
- **Syntax check** = `python3 -m py_compile __init__.py` (compiles without importing `bpy`).
- Line numbers cited below are valid at commit `3b4b30b` and **will shift as tasks land**. Always locate code by the quoted symbol/pattern, never by raw line number.
- The audit report this plan implements is summarized at the end of this file (Appendix).

---

### Task 1: Fix Opening Type "Straight" update callback (CRITICAL)

`opening_shape_mandef_update` (`__init__.py:8114`) does `setattr(slf, 'lip_threshold', 0.0)`, but the `lip_threshold` property on `HRDC_ObjAttch_Geometry_InptPrps` is commented out (the UI now drives the modifier input directly via `draw_geonodes_mod_prop`). Every switch to Opening Type "Straight" raises `AttributeError` and the Select Outer modifier's Lip Threshold is never reset — the stale threshold keeps affecting the fill while its slider is hidden.

**Files:**
- Modify: `__init__.py` (function `opening_shape_mandef_update`)
- Test: `tests/run_assembly_blender_smoke.py`

- [ ] **Step 1: Write the failing test**

In `tests/run_assembly_blender_smoke.py`, insert this block inside `main()`, immediately **before** the final `select_active(bottle)` / `bpy.ops.liquifeel.assembly_clear()` section:

```python
    # --- Regression: Opening Type -> 'straight' must not raise (the update
    #     callback used to write to a removed 'lip_threshold' property) ---
    props = bottle.hrdc_liquifeel_input_field_props.geometry
    try:
        props.opening_shape = 'irregular'
        props.opening_shape = 'straight'
        # Also call directly: Blender may swallow exceptions raised inside
        # RNA update callbacks depending on the entry path.
        mod.opening_shape_mandef_update(props, bpy.context)
        ok('Opening Type switch to straight does not raise')
    except Exception as e:
        fail(f'opening_shape update raised: {type(e).__name__}: {e}')
```

(The bottle is unfilled here, so no Select Outer modifier exists — the fixed callback must silently no-op in that case. That is exactly what the `try/except` in the fix below guarantees.)

- [ ] **Step 2: Run the smoke test to verify it fails**

Run: `"$BLENDER" --background --python tests/run_assembly_blender_smoke.py`
Expected: `FAIL: opening_shape update raised: AttributeError: ...'lip_threshold'...` and exit code 1.

- [ ] **Step 3: Fix the callback**

Replace the whole function (keep the explanatory comment above it, updated):

```python
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
```

This mirrors the guard pattern of `hide_recipient_update` and the live `set_geonode_mod_input(obj__, SELECT_OUTER_NG_NAME, 'Lip Threshold', ...)` call used at fill time (currently `__init__.py:12191`).

- [ ] **Step 4: Run the smoke test to verify it passes**

Run: `"$BLENDER" --background --python tests/run_assembly_blender_smoke.py`
Expected: `OK: Opening Type switch to straight does not raise`, exit code 0, all other checks still green.

- [ ] **Step 5: Commit**

```bash
git add __init__.py tests/run_assembly_blender_smoke.py
git commit -m "fix: reset Select Outer lip threshold on Opening Type 'straight' (was writing to removed property)"
```

---

### Task 2: Remove import-time pip install of Pillow (CRITICAL)

`check_and_install_package('Pillow', ...)` runs at module import (`__init__.py:466`): on every Blender launch with the addon enabled it tries `import PIL` and on failure **upgrades pip and pip-installs Pillow into Blender's Python** — network access and interpreter mutation at startup without consent. Fails offline, can corrupt site-packages, and is disallowed on the Blender Extensions platform. The vendored `third_party/t3dn_bip` already degrades gracefully without Pillow.

**Files:**
- Modify: `__init__.py` (the `## PIP -----------------` section, currently lines 417–466)

- [ ] **Step 1: Verify the three pip helpers have no other callers**

Run:
```bash
grep -n "upgrade_pip\|install_package\|check_and_install_package" __init__.py
```
Expected: hits **only** inside the `## PIP` section itself (definitions at ~419/426/437, the call at ~466). If any other live call site appears, stop and re-assess — do not delete.

- [ ] **Step 2: Delete the whole PIP section**

Delete from the line `## PIP -----------------` down to and including `check_and_install_package('Pillow', package_import_name='PIL')` — this removes `upgrade_pip`, `install_package`, `check_and_install_package`, the commented `install_python_package`/`remove_python_package` remnants, and the module-level call.

- [ ] **Step 3: Check whether `subprocess` import is now unused**

Run: `grep -n "subprocess" __init__.py`
Expected: if the only remaining hits are the `import subprocess` line, delete that import too. If other uses exist, leave it.

- [ ] **Step 4: Verify**

Run: `python3 -m py_compile __init__.py`
Expected: no output (success).

Run: `"$BLENDER" --background --python tests/run_assembly_blender_smoke.py`
Expected: all checks pass — proves the addon still imports and registers without the Pillow check.

- [ ] **Step 5: Commit**

```bash
git add __init__.py
git commit -m "fix: remove import-time pip install of Pillow (network/interpreter mutation at startup)"
```

---

### Task 3: Cache mesh-island count out of the panel draw path (PERFORMANCE)

`_draw_geometry_ui_impl` calls `has_obj_single_mesh_island` → `count_mesh_islands` (`__init__.py:655`), which builds a dict-of-sets over **all vertices and edges on every `Panel.draw()`** — i.e., on every mouse move over the sidebar. On the dense CAD meshes this addon targets that is 100s of ms per redraw. Cache the result keyed on `(object name, vert count, edge count)`: islands cannot change without those counts changing while in Object Mode (the draw path only runs the check when `obj__.mode == 'OBJECT'`).

**Files:**
- Modify: `__init__.py` (`## MESH ISLAND COUNT ---` section; `has_obj_single_mesh_island`; `unregister()`)
- Test: `tests/run_assembly_blender_smoke.py`

- [ ] **Step 1: Write the failing test**

In `tests/run_assembly_blender_smoke.py`, insert inside `main()` right after the block added in Task 1:

```python
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
```

- [ ] **Step 2: Run the smoke test to verify it fails**

Run: `"$BLENDER" --background --python tests/run_assembly_blender_smoke.py`
Expected: `AttributeError: module 'LiquiFeel' has no attribute '_mesh_island_count_cache'` (the script's outer `try` prints the traceback and exits 1).

- [ ] **Step 3: Implement the cache**

In the `## MESH ISLAND COUNT ---` section, add after `count_mesh_islands`:

```python
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
```

Then change `has_obj_single_mesh_island` (currently `__init__.py:12074`) to use it:

```python
def has_obj_single_mesh_island(obj__):
    return count_mesh_islands_cached(obj__) == 1
```

Leave `assert_island_count_f` (operator poll-time check) on the uncached `count_mesh_islands` — operators run once per click and should always see fresh topology.

Finally, clear the cache in `unregister()`, next to the existing `_unregister_separate_timers()` call:

```python
    _mesh_island_count_cache.clear()
```

- [ ] **Step 4: Fix the bare `except:` in `count_mesh_islands` while here**

Replace the `while found: try/except` loop (exception-driven termination) with explicit iteration:

```python
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
```

- [ ] **Step 5: Run the smoke test to verify it passes**

Run: `"$BLENDER" --background --python tests/run_assembly_blender_smoke.py`
Expected: `OK: mesh island count cached for draw path`, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add __init__.py tests/run_assembly_blender_smoke.py
git commit -m "perf: cache mesh-island count out of the Geometry panel draw path"
```

---

### Task 4: Remove duplicate top-level function definitions

Two functions are defined twice at module level; the second definition silently shadows the first. Anyone editing the first copy sees no effect.

**Files:**
- Modify: `__init__.py`

- [ ] **Step 1: Confirm both duplicates**

Run: `grep -n "^def hrdc_pattern_texture_updt\|^def set_geonode_mod_input(" __init__.py`
Expected: two hits each — `hrdc_pattern_texture_updt` at ~9749 and ~9794; `set_geonode_mod_input` at ~6889 and ~11934.

- [ ] **Step 2: Delete the shadowed/duplicate copies**

- Delete the **first** `hrdc_pattern_texture_updt` (the ~9749 copy that hardcodes `FPATHS['recipient_patterns']`); the second (REDUX-lookup version) is the live one.
- Delete the **second** `set_geonode_mod_input` (~11934); it is byte-identical to the first (~6889), and the first must stay because Task 1's fix and other earlier code reference it.

- [ ] **Step 3: Verify exactly one definition of each remains**

Run: `grep -c "^def hrdc_pattern_texture_updt" __init__.py && grep -c "^def set_geonode_mod_input(" __init__.py`
Expected: `1` and `1`.

Run: `python3 -m py_compile __init__.py` — expected: success.
Run the smoke test — expected: all green.

- [ ] **Step 4: Commit**

```bash
git add __init__.py
git commit -m "refactor: remove duplicate definitions of hrdc_pattern_texture_updt and set_geonode_mod_input"
```

---

### Task 5: Delete dead sibling modules and stale data files

`constants.py`, `filepaths.py`, `foundational.py`, `synthetic_properties.py` (~3,000 lines) are **never imported** — `__init__.py` contains newer, diverged copies of everything in them. Two are un-importable as written (`filepaths.py` imports from itself; `foundational.py` references names it never imports and pip-installs at import). They are stale (Jul 2024), actively misleading, and `build_release.py` currently ships all four in the release zip. Also dead: `data/node_socket_data__.json` (stale backup of `node_socket_data.json`) and two `*obsolete*` icons that get needlessly loaded into the preview collection.

**Files:**
- Delete: `constants.py`, `filepaths.py`, `foundational.py`, `synthetic_properties.py`
- Delete: `data/node_socket_data__.json`, `data/icons/clear__obsolete.png`, `data/icons/check__obseolete.png`
- Delete (untracked): `.DS_Store`, `dist/.DS_Store`, `third_party/.DS_Store`

- [ ] **Step 1: Verify zero live imports**

Run:
```bash
grep -rn "import constants\|import filepaths\|import foundational\|import synthetic_properties\|from constants\|from filepaths\|from foundational\|from synthetic_properties" --include='*.py' .
```
Expected: only self-referential hits inside the four files themselves and/or commented lines. Any live import elsewhere → stop and re-assess.

Run: `grep -rn "node_socket_data__" --include='*.py' .`
Expected: no hits (the runtime path reads/writes `node_socket_data.json` only).

- [ ] **Step 2: Delete the files**

```bash
git rm constants.py filepaths.py foundational.py synthetic_properties.py
git rm data/node_socket_data__.json data/icons/clear__obsolete.png data/icons/check__obseolete.png
rm -f .DS_Store dist/.DS_Store third_party/.DS_Store
```

- [ ] **Step 3: Verify the addon and packaging still work**

Run the smoke test — expected: all green (it imports the package `LiquiFeel`, which never touched these files).
Run: `python3 build_release.py --out /tmp/lqfl_relcheck && unzip -l /tmp/lqfl_relcheck/*.zip | grep -c "synthetic_properties\|foundational\|filepaths\|constants\.py\|node_socket_data__"`
Expected: build succeeds; the grep count is `0`.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: delete dead sibling modules and stale data files (never imported, superseded by __init__.py)"
```

---

### Task 6: Preview-collection lifecycle + quiet registration

Six `bpy.utils.previews.new()` collections (~120 images) are created at **module import** (`__init__.py:7326-7368`) and never released — every addon disable/enable or upgrade leaks them (Blender warns at exit). Move creation into `register()`, release in `unregister()`. Also: `register()`/`unregister()` print every one of ~150 classes — pure console spam.

**Files:**
- Modify: `__init__.py` (preview setup block, `register()`, `unregister()`)

- [ ] **Step 1: Check for module-level consumers of the preview data**

The refactor is only safe if nothing between the preview block and `register()` reads `preview_img_ids`/`preview_data` **at import time** (draw-time and callback reads are fine). Run:
```bash
grep -n "preview_img_ids\|preview_data\|preview_collections" __init__.py
```
Inspect each hit: usage inside `def`-bodies is fine; any module-level statement (other than the creation block itself and the `preview_data = {...}` literal) that indexes into loaded ids at import time blocks the move — in that case only add the `unregister()` cleanup below plus an idempotent re-load guard, and skip moving creation.

- [ ] **Step 2: Wrap creation in load/unload functions**

Replace the module-level creation block (from `preview_collections['icons'] = new_preview_collection(...)` through the `recipient_asset_thumbnails` load; keep `preview_collections = {}` / `preview_img_ids = {}` and the `get_recipient_asset_key_from_thumbnail_name` def at module level) with:

```python
def _load_preview_collections():
    if preview_collections:
        return  # already loaded (idempotent for enable/disable cycles)
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
            bpy.utils.previews.remove(pcol)
        except Exception:
            pass
    preview_collections.clear()
    preview_img_ids.clear()
```

The `preview_data = {'collections': preview_collections, 'ids': preview_img_ids}` literal stays as-is — it aliases the dicts, which are mutated in place, so draw-time consumers keep working.

Note: `new_preview_collection` may take the root path argument or none — keep the exact existing call signatures shown above (they are copied from the current code).

- [ ] **Step 3: Wire into register/unregister and quiet the prints**

In `register()`, replace:

```python
    classes_to_register = get_classes()
    for cls in classes_to_register:
        print('registering class:', cls)
        bpy.utils.register_class(cls)
```

with:

```python
    _load_preview_collections()
    classes_to_register = get_classes()
    for cls in classes_to_register:
        bpy.utils.register_class(cls)
    print(f'LIQUIFEEL: registered {len(classes_to_register)} classes')
```

In `unregister()`, drop the per-class `print('unregistering class:', cls)` the same way, and add as the **last** statements:

```python
    _unload_preview_collections()
```

(after the `del bpy.types...` lines — draw code may still run between class unregistration steps).

- [ ] **Step 4: Verify**

Run: `python3 -m py_compile __init__.py` — success.
Run the smoke test — all green. Note the smoke test's `load_addon()` calls `unregister()` then `register()`, so it exercises the reload cycle: previews must be recreated by `_load_preview_collections()` on the second `register()`.

- [ ] **Step 5: Commit**

```bash
git add __init__.py
git commit -m "fix: release preview collections on unregister, load them in register, quiet per-class prints"
```

---

### Task 7: Purge dead functions, dead operators, and the legacy extgen/execd pipeline

Reachability analysis from all live roots (registered classes, module-level code, `update=`/`poll=` callbacks, timers, handlers, `bl_idname` strings) shows the following are unreachable. **Protocol for every symbol:** run `grep -n "<name>" __init__.py` first; delete only if all hits are (a) the definition itself, (b) references from other symbols in this same dead list, or (c) commented lines. If a live reference appears, leave the symbol and note it.

**Files:**
- Modify: `__init__.py`
- Modify: `tests/test_assembly_helpers.py` (only if a grep-based check there references a deleted symbol)

- [ ] **Step 1: Delete the legacy extgen/execd draw/setter cluster (~30 functions)**

Verify-then-delete each of:

```
draw_shading_ui  draw_shading_ui__  draw_slot_shading_ui  draw_fill_shading_ui
draw_fill_liquid_shading_ui  draw_input__extgen  draw_input__execd
maybe_draw_input  draw_imgtex_input  draw_drop_dwn__by_redux_data
draw_drop_down__extgen  draw_drop_down__execd  satisfies_draw_dependency
satisfies_simple_draw_dependency  get_prop_key_chain  get_prop_key_chain__from_dep_data
draw_shader_controls  draw_library_selector  draw_scene_shading_ui
draw_hide_controls  draw_material_link_controls  set_input__at_prop_update
set_geonode_mod_input__at_prop_update  set_material_attached_input__at_setup
set_shader_ng_input  set_shader_ng_input__at_prop_update
set_shader_node_input__at_prop_update  slot_shade  slot_library_update
slot_shading_material_update  scene_slot_shading_material_update
lip_threshold_update  get_input_field_data_and_path
```

Helper loop for verification:
```bash
for f in draw_shading_ui draw_slot_shading_ui set_input__at_prop_update lip_threshold_update; do
  echo "== $f"; grep -n "\b$f\b" __init__.py
done
```
(Do this for the full list. `hrdc_*`-prefixed lookalikes are the LIVE versions — do not touch them. `draw_hide_controls` is dead but `hrdc_draw_hide_controls` is live, etc.)

- [ ] **Step 2: Delete unreachable operators (verified: only commented or zero `bl_idname` references)**

For each class below, delete the class **and** its `registerable_classes.append(...)` line:

- `CycleTabs` (`liquifeel.cycle_tabs`) — only commented UI references.
- `PurgeUnusedData` (`liquifeel.purge_unused_data`) — only a commented reference.
- `LoadUserDefinedPattern` (the **non-HRDC** one, ~`:13753`) — its only reference is inside dead `draw_input__extgen` (deleted in Step 1). The `HRDC_LoadUserDefinedPattern*` variants are live — keep them.

Verification per operator (example):
```bash
grep -n "liquifeel.cycle_tabs\|CycleTabs" __init__.py
```
Expected after deletion: no hits (or only inside comment blocks slated for Task 8).

**Do NOT delete** (dynamic/F3/test usage): `AssemblyAssignCork`, `AssemblyAssignLabel`, `AssemblyAddExtra`, `AssemblyClearCork`, `AssemblyClearLabel`, `AssemblyRemoveMember` — exercised by the smoke test via `bpy.ops`. **Flag for the user, do not delete without their decision:** `ShadeActiveObjectViaFill`, `HRDC_ShadeActiveObjectViaFill`, `HRDC_ShadeActiveObjectViaSlot`, `MakeSlotMaterialSingleUser`, `MakeFillMaterialSingleUser` — zero UI references but reachable via F3 operator search; they may be deliberate power-user entry points.

- [ ] **Step 3: Delete the dead animation subsystem**

`animation_prop_update_handler` (`@persistent`), `execute_update_hooks_from_obj`, `prop_value_update_f` — the handler registration in `register()` is commented out. Delete all three functions **and** the commented `# bpy.app.handlers.frame_change_post...` lines in `register()`/`unregister()`.

- [ ] **Step 4: Delete dead small helpers**

Verify-then-delete:

```
class_name_from_key  bl_version_lesser  bl_version_greater  parse_json_string
getattr_rec__by_names  ref_input_field_property  load_image
has_extension  has_image_extension  get_fname_with_name
get_declaration_modality_key  is_shader_node_group
extract_mod_stack_ng_name_list  get_slot_material_named_closest
is_tagged_material_name_f  maybe_get_slot_material_by_tagged_mat_name
pattern_ui_input_order_sorting_metric
```

Note: `has_extension` calls `get_extension` which **is not defined anywhere** — a latent `NameError`; deleting the trio removes it. `maybe_load_image` is live — keep it. `extract_legacy_asset_tag_data` is reachable via the DEV-gated `ExtractMigrationTagData` operator — keep it (DEV tooling).

- [ ] **Step 5: Verify**

Run: `python3 -m py_compile __init__.py` — success.
Run: `grep -rn "<each deleted name>" tests/` — if `tests/test_assembly_helpers.py` greps for any deleted symbol, update that test accordingly.
Run the smoke test — all green.
Sanity: `wc -l __init__.py` — expect roughly 1,500–2,000 lines fewer than before this task.

- [ ] **Step 6: Commit**

```bash
git add __init__.py tests/
git commit -m "refactor: purge unreachable legacy extgen/execd pipeline, dead operators, animation stubs, dead helpers"
```

---

### Task 8: Purge commented-out code blocks

`__init__.py` carries ~1,450 lines of commented-out code in blocks of 20+ lines (33 blocks; largest around former lines 2179–2300, 3730–3838, four ~77-line blocks between 5762–6250, 13978–14088). These are old versions of functions that exist in live form; git history preserves them. Policy: **commented-out code is deleted; explanatory prose comments stay.**

**Files:**
- Modify: `__init__.py`

- [ ] **Step 1: Locate candidate blocks**

Run:
```bash
awk '/^[[:space:]]*#/{c++; if(c==20) print NR-19; next} {c=0}' __init__.py
```
Each printed number is the start of a ≥20-line comment run. For each block decide: is it **code** (contains `def `, assignments, `bpy.`, brackets/indentation of Python) → delete; is it **prose** (docs, rationale, TODO context) → keep. Mixed blocks: delete the code lines, keep prose lines that still make sense.

- [ ] **Step 2: Delete, in several passes, re-running the awk command until no code blocks remain**

Also sweep smaller commented-out code remnants adjacent to functions touched in Tasks 1–7 (e.g. the commented `set_geonode_mod_input__at_prop_update` variant above the live one, commented `FPATHS['material_input_data']`, commented property declarations inside `HRDC_ObjAttch_Geometry_InptPrps`).

- [ ] **Step 3: Verify after each pass**

Run: `python3 -m py_compile __init__.py` — success (catches an accidental deletion of live code immediately).
After the final pass, run the smoke test — all green.
Sanity: `grep -c "^\s*#" __init__.py` — expect the comment-line count to drop from ~3,900 to well under 1,500.

- [ ] **Step 4: Commit**

```bash
git add __init__.py
git commit -m "chore: delete commented-out code blocks (~1,400 lines); git history is the archive"
```

---

### Task 9: Minor correctness and hygiene fixes

**Files:**
- Modify: `__init__.py`, `tests/test_assembly_helpers.py`

- [ ] **Step 1: Fix the misplaced guard in `reduce_input_data`**

Current code (note `if old_key in d['data']...` uses the **loop-leaked** `d` — it tests only the *last* input's data):

```python
    for new_key, old_key in data_branch_key_mapping.items():
        if old_key in d['data'].keys():
            data[new_key] = most_common(
                [d['data'][old_key] for d in filter(
                    lambda d: old_key in d['data'].keys(),
                    inputs_data)])
```

Replace with (guard against *any* input carrying the key, not just the last):

```python
    for new_key, old_key in data_branch_key_mapping.items():
        vals = [d['data'][old_key] for d in inputs_data
                if old_key in d['data'].keys()]
        if vals:
            data[new_key] = most_common(vals)
```

- [ ] **Step 2: Fix the user-facing typo**

Find: `'Fill the this recipient to enable additional functionality.'`
Replace with: `'Fill this recipient to enable additional functionality.'`

- [ ] **Step 3: Remove the dangling `FPATHS` entry**

Delete `FPATHS['input_field_data'] = FPATHS['data_root'] / 'ui_control_inputs.json'` — the file `data/ui_control_inputs.json` does not exist and the only consumer is a commented-out `json.load` (which Task 8 removed). Verify first: `grep -n "input_field_data'\]" __init__.py` → only the assignment remains.

- [ ] **Step 4: Remove the DEV REPL block referencing another machine**

Delete the `if DEV:` block that loads `/home/feral/.config/blender/4.0/scripts/addons/calculusrex_repl/__init__.py` (plus `dev_aux_registration`/`dev_aux_unregistration` and their call sites in `register()`/`unregister()`); it is a hardcoded path from a different developer's Linux box and can never work here. Keep the `DEV` flag itself and the `DevPanel` gating.

- [ ] **Step 5: Trim unused test scaffolding**

In `tests/test_assembly_helpers.py`, delete the `FakeObject` / `_install_bpy_stub` scaffolding (~lines 14–67) if — verify first — nothing in the file uses it.

- [ ] **Step 6: Verify and commit**

Run: `python3 -m py_compile __init__.py` — success.
Run: `python3 tests/test_assembly_helpers.py` (it is a plain-python source-grep test) — passes.
Run the smoke test — all green.

```bash
git add __init__.py tests/test_assembly_helpers.py
git commit -m "fix: reduce_input_data guard, UI typo, dangling FPATHS entry, dead DEV repl block, test scaffolding"
```

---

### Task 10: Final verification + release build

**Files:** none modified (verification only, plus optional `dist/` output)

- [ ] **Step 1: Full smoke test**

Run: `"$BLENDER" --background --python tests/run_assembly_blender_smoke.py`
Expected: exit 0, `All assembly smoke checks passed.`, including the two new checks from Tasks 1 and 3.

- [ ] **Step 2: Helper test**

Run: `python3 tests/test_assembly_helpers.py`
Expected: passes.

- [ ] **Step 3: Build the release zip and inspect**

Run: `python3 build_release.py`
Expected: build succeeds; `unzip -l dist/liquifeel-v*.zip` shows **no** `synthetic_properties.py`, `foundational.py`, `filepaths.py`, `constants.py`, `node_socket_data__.json`, or `*obsolete*` icons.

- [ ] **Step 4: Manual spot-check in Blender (GUI, if available)**

Open Blender, enable the addon from the fresh zip, fill a test bottle, switch Opening Type Irregular → Straight (no console traceback; Lip Threshold visibly resets), disable+re-enable the addon (no preview-leak warnings, icons still render).

- [ ] **Step 5: Commit any stragglers, then done**

```bash
git status   # expect clean
```

---

## Explicitly out of scope (follow-ups, need product/user decisions)

1. **Splitting `__init__.py` into modules** (`props.py`, `ops.py`, `ui.py`, `core.py`, `diagnostics.py`, `data_tables.py`). Recommended **after** this purge lands (~12k lines remaining). The 5,300-line `INPUT_FIELD_DATA__PRESERVING_ORDER` literal alone is a third of the file and could go back to JSON in `data/`.
2. **Fate of the F3-only shading operators** (`ShadeActiveObjectViaFill` family, `Make*MaterialSingleUser`) — flagged in Task 7 Step 2; delete only with user sign-off.
3. **Fate of the assembly role operators** (cork/label/extra assign) — no UI references, kept alive by the smoke test; either resurface in UI or delete together with their test sections.
4. **`bl_info` says `"blender": (4, 1, 0)`** while the build tag is `blender52-port-r27` — bump the declared minimum to what is actually tested (user decision).
5. Consistent icon access in `draw_condensation_ui` / high-level material+render controls (use the `layout_operator_with_preview`-style guard instead of raw `icon_value=` indexing).
6. `_separate_objects_last_sig` pruning for deleted/renamed objects; `undo_push` decorator-factory simplification; raising the separate-liquid poll interval when idle.
7. Headless CI gate: run the smoke test automatically before `build_release.py`.

---

## Appendix: audit findings → task map

| Audit finding | Severity | Task |
|---|---|---|
| Opening Type "Straight" writes to removed property | Critical | 1 |
| pip-install Pillow at import | Critical | 2 |
| Island count on every panel redraw | Important (perf) | 3 |
| Duplicate defs shadowing (`hrdc_pattern_texture_updt`, `set_geonode_mod_input`) | Important | 4 |
| 4 dead sibling modules shipped in release | Important | 5 |
| Stale data files (`node_socket_data__.json`, obsolete icons) | Important | 5 |
| Preview collections never released; per-class register prints | Important | 6 |
| Dead extgen/execd pipeline (~30 fns), dead operators, dead animation trio, latent `NameError` in `has_extension` | Important | 7 |
| ~1,450 lines commented-out code | Important | 8 |
| `reduce_input_data` loop-variable leak | Important | 9 |
| Typo, dangling FPATHS entry, `/home/feral` DEV block, test scaffolding | Minor | 9 |
| File split, F3 operators, assembly operators, bl_info min version, icon-access consistency, misc | — | Follow-ups |
