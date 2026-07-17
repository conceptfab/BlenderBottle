# LiquiFeel Pre-Release Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the release blockers found in the GROK-branch code review — the destructive scale-baking bug on bottle assembly, operators running inside RNA update callbacks, repo hygiene (committed binaries/bytecode/debug artifacts), placeholder URLs, and a set of minor robustness issues — so the branch is shippable.

**Architecture:** All logic changes are in the monolithic addon entry file `__init__.py`. The scale bug is fixed by baking **rotation only** (never scale) and snapshotting/restoring child world matrices around `transform_apply`. The RNA-callback risk is fixed by deferring operator-heavy work to a one-shot `bpy.app.timers` tick, mirroring the existing `schedule_separate_refresh` pattern. Repo hygiene is mechanical git work plus a new `.gitignore`. Behavioral coverage lives in the Blender background smoke test (`tests/run_assembly_blender_smoke.py`), which is the only test vehicle that loads the real addon.

**Tech Stack:** Python 3.11+, Blender 4.1+ Python API (`bpy`), git.

**Prerequisites:** A Blender 4.x binary is required to run the smoke test. Set `BLENDER` to its path, e.g.:
```bash
export BLENDER="/Applications/Blender.app/Contents/MacOS/Blender"
```

---

## File Structure

| File | Responsibility | Change |
|------|----------------|--------|
| `__init__.py` | Addon logic | Modify: `bake_parent_transforms` (117), `make_single_user_and_apply_transforms` (111), `assembly_bottle_pointer_update` (8581), `_unregister_separate_timers` (9189), signature cache (9164/9183), `_assembly_seed_drop_slots_timer` teardown, `AssemblyToggleHideExtras.execute` (~12386) |
| `tests/run_assembly_blender_smoke.py` | End-to-end Blender smoke test | Modify: add scale-0.1 + child-displacement scenario and marker round-trip check |
| `tests/test_assembly_helpers.py` | Pure-python presence checks | Modify: remove the misleading no-op behavioral test, relabel as presence-only |
| `.gitignore` | Ignore build/backup artifacts | Create |
| `data/urls.json` | User-facing button URLs | Modify: real product URLs (values supplied by product owner) |

Priority order: **Task 1 → 3 → 4** are the hard release blockers (bug + hygiene + URLs). **Task 2** is the crash-risk fix. **Task 5** is minor robustness. **Task 6** cleans up the misleading test.

---

## Task 1: Fix destructive scale-baking on bottle assembly

**Symptom (reported):** A bottle model authored at scale 0.1 (parent empty `500_bottle_R21 - skala0.5`) ends up at scale 1.000/1.000/1.000 after being set as the assembly Bottle. Applying scale bakes 0.1 into the mesh and — because `transform_apply` does not compensate child `matrix_parent_inverse` — drags cork/label/liquid off the bottle. The liquid proxy (parented with `matrix_parent_inverse` identity, `scale=(1,1,1)`, at `__init__.py:9068-9072`) inherits the parent scale, so resizing the parent also resizes the liquid.

**Root cause:** `bake_parent_transforms` (`__init__.py:132`) and `make_single_user_and_apply_transforms` (`__init__.py:115`) both call `bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)`. Only **rotation** must be baked (the fill Geometry Nodes read world-space rotation, per the docstring at `__init__.py:120-123`); baking scale is the bug.

**Files:**
- Test: `tests/run_assembly_blender_smoke.py`
- Modify: `__init__.py:111-115` and `__init__.py:117-132`

- [ ] **Step 1: Add the failing smoke-test scenario**

In `tests/run_assembly_blender_smoke.py`, insert this block immediately before the `marker = dict(mod._lqfl_marker_get(bottle))` line (currently line 157), so it runs after the existing `bake_parent` check:

```python
    # --- Regression: scale must be preserved and children must not drift ---
    scaled = mesh_obj('ScaledBottle', (2, 0, 0))
    scaled.scale = (0.1, 0.1, 0.1)
    scap = mesh_obj('ScaledCork', (2, 0, 0.06))
    root = bpy.data.objects.new('SkalaRoot', None)
    bpy.context.collection.objects.link(root)
    mw = scaled.matrix_world.copy()
    scaled.parent = root
    scaled.matrix_world = mw
    root.rotation_euler.z = math.radians(30)
    bpy.context.view_layer.update()

    select_active(scaled)
    if 'FINISHED' not in bpy.ops.liquifeel.assembly_set_bottle():
        fail('Set scaled bottle failed')
    select_active(scap)
    bpy.ops.liquifeel.assembly_assign_cork()

    cork_world_before = scap.matrix_world.translation.copy()
    select_active(scaled)
    if 'FINISHED' not in bpy.ops.liquifeel.bake_parent_transforms():
        fail('bake on scaled bottle failed')
    bpy.context.view_layer.update()

    if abs(scaled.scale.x - 0.1) > 1e-4:
        fail(f'Bottle scale was baked away: scale.x={scaled.scale.x} (expected 0.1)')
    else:
        ok('Bottle scale 0.1 preserved through bake')

    cork_world_after = scap.matrix_world.translation.copy()
    if (cork_world_after - cork_world_before).length > 1e-3:
        fail(f'Cork drifted on bake: {(cork_world_after - cork_world_before).length}')
    else:
        ok('Cork world position preserved through bake')
```

- [ ] **Step 2: Run the smoke test and confirm the new checks FAIL**

Run:
```bash
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py
```
Expected: output contains `FAIL: Bottle scale was baked away: scale.x=1.0 (expected 0.1)` (and likely a cork-drift FAIL), and a non-zero exit code.

- [ ] **Step 3: Fix `bake_parent_transforms`**

Replace `__init__.py:117-132` with:

```python
def bake_parent_transforms(context, obj__):
    """Unparent with Keep Transform, then apply ROTATION ONLY.

    LiquiFeel's fill Geometry Nodes read Self Object / Object Info rotation in
    world space. Nested parents (typical CAD hierarchies) leave that rotation
    on the parent chain, which breaks liquid generation. Baking the world
    rotation into the object fixes it without changing the visible placement.

    Scale is deliberately NOT applied: models are often authored at a non-unit
    scale (e.g. 0.1), the liquid proxy inherits the bottle's scale, and
    transform_apply does not compensate child matrix_parent_inverse — applying
    scale would resize the liquid and drag cork/label off the bottle.
    """
    select_and_set_active(context, obj__, deselect_all=True)
    bpy.ops.object.make_single_user(object=True, obdata=True, material=True)
    if obj__.parent is not None:
        unparent_keep_transform(obj__)
        context.view_layer.update()
    # Snapshot child world matrices: applying rotation to a parent does not fix
    # child matrix_parent_inverse, so children would otherwise drift.
    child_world = {child: child.matrix_world.copy() for child in obj__.children}
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
    for child, mw in child_world.items():
        child.matrix_world = mw
```

Note: `unparent_keep_transform` is defined at `__init__.py:8074`; module-level forward reference is fine because it is resolved at call time.

- [ ] **Step 4: Fix the sibling helper `make_single_user_and_apply_transforms`**

Replace `__init__.py:111-115` with:

```python
def make_single_user_and_apply_transforms(context, obj__):
    select_and_set_active(context, obj__, deselect_all=True)
    bpy.ops.object.make_single_user(object=True, obdata=True, material=True)
    # Rotation only — never bake scale (see bake_parent_transforms docstring).
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=False)
```

- [ ] **Step 5: Run the smoke test and confirm ALL checks PASS**

Run:
```bash
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py
```
Expected: `All assembly smoke checks passed.` and exit code 0, including `OK: Bottle scale 0.1 preserved through bake` and `OK: Cork world position preserved through bake`.

- [ ] **Step 6: Manual verification in Blender UI (reproduces the original report)**

Open the master blend, take a bottle authored at scale 0.1 under a rotated parent, drop it into the **Bottle** field, assign a cork + label. Confirm: bottle Scale stays 0.1 in the N-panel Transform, cork/label stay visually attached, and the liquid proxy is not resized. Record the result in the commit message.

- [ ] **Step 7: Commit**

```bash
git add __init__.py tests/run_assembly_blender_smoke.py
git commit -m "fix: bake rotation only and preserve child transforms on assembly bake

Applying scale in bake_parent_transforms wiped intended object scale (0.1)
and dragged cork/label/liquid off the bottle. Bake rotation only and restore
child world matrices around transform_apply.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: Move operators out of the RNA update callback

**Root cause:** `assembly_bottle_pointer_update` (`__init__.py:8581`) runs `prepare_bottle_world_pose` → `bake_parent_transforms`, which executes `bpy.ops.object.make_single_user` and `bpy.ops.object.transform_apply` from inside a PointerProperty update. Running data-modifying operators from an RNA update is unsupported by Blender and can crash or leave the depsgraph inconsistent. The codebase already avoids this for separate-liquid work by deferring to a timer (`schedule_separate_refresh`); do the same here.

**Files:**
- Modify: `__init__.py` — add a deferred bake scheduler near `schedule_separate_refresh`; rewrite `assembly_bottle_pointer_update` (8581); extend `_unregister_separate_timers` (9189).

- [ ] **Step 1: Add the deferred bake scheduler**

Insert immediately **above** `def assembly_bottle_pointer_update(self, context):` (currently `__init__.py:8581`):

```python
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
```

- [ ] **Step 2: Rewrite the update callback to only schedule**

Replace the body of `assembly_bottle_pointer_update` (`__init__.py:8581-8599`) with:

```python
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
```

- [ ] **Step 3: Tear the timer down on unregister**

In `_unregister_separate_timers` (`__init__.py:9189-9194`), add before `_pending_separate_refresh.clear()`:

```python
    if bpy.app.timers.is_registered(_flush_bottle_bake_timer):
        bpy.app.timers.unregister(_flush_bottle_bake_timer)
    _pending_bottle_bake.clear()
```

- [ ] **Step 4: Run the smoke test**

Run:
```bash
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py
```
Expected: `All assembly smoke checks passed.`, exit 0. (The smoke test calls the operators directly, so this confirms no regression; the timer path is exercised interactively.)

- [ ] **Step 5: Manual verification — reload safety**

In Blender: drop a parented bottle into the Bottle field (confirm no crash, pose bakes on the next tick), then disable + re-enable the addon. Confirm no `bpy.app.timers` warning and no ghost callbacks.

- [ ] **Step 6: Commit**

```bash
git add __init__.py
git commit -m "fix: defer bottle pose bake out of RNA update callback

Running make_single_user/transform_apply from a PointerProperty update can
crash Blender. Schedule the bake on a one-shot timer and tear it down on
unregister.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Repo hygiene — stop shipping binaries, bytecode, and debug artifacts

**Root cause:** No `.gitignore`. Tracked: `__pycache__/*.pyc` (incl. a new cpython-314), 18 `third_party/**/*.pyc`, `data/blendfs/LiquidFeel_MASTER.blend1` (~123 MB backup), and `tests/_draw_debug_out.txt` (26 KB captured stdout). These bloat the release archive by ~250 MB and ship stale bytecode.

**Files:**
- Create: `.gitignore`
- Remove from tracking: all `.pyc`, the `.blend1` backup, the debug capture

- [ ] **Step 1: Create `.gitignore`**

Create `.gitignore` with:

```gitignore
# Python bytecode
__pycache__/
*.py[cod]

# Blender backups / temp
*.blend1
*.blend2
*_bak_*.blend

# OS cruft
.DS_Store

# Dev/debug scratch output
tests/_draw_debug_out.txt
```

- [ ] **Step 2: Untrack the offending files (keep them on disk)**

Run:
```bash
git rm --cached -r __pycache__ third_party/t3dn_bip/__pycache__
git rm --cached "data/blendfs/LiquidFeel_MASTER.blend1"
git rm --cached tests/_draw_debug_out.txt
git rm --cached third_party/.DS_Store .DS_Store 2>/dev/null || true
```

- [ ] **Step 3: Verify nothing unwanted remains tracked**

Run:
```bash
git ls-files | grep -E '\.pyc$|\.blend1$|_draw_debug_out|\.DS_Store' || echo "CLEAN"
```
Expected: `CLEAN`.

- [ ] **Step 4: Decide on the 129 MB master `.blend`**

Confirm with the product owner whether `data/blendfs/LiquidFeel_MASTER.blend` (129 MB) must ship inside the addon package or can be delivered separately / via Git LFS. Record the decision in the commit message. (Do not remove it without confirmation — the addon may load assets from it at runtime; grep first: `grep -n "LiquidFeel_MASTER" __init__.py filepaths.py`.)

- [ ] **Step 5: Commit**

```bash
git add .gitignore
git commit -m "chore: add .gitignore and untrack bytecode, blend backup, debug capture

Removes ~250 MB of redundant binaries/bytecode from the tree. Master .blend
retained pending packaging decision.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Replace placeholder URLs with real product URLs

**Root cause:** `data/urls.json` ships dummy links wired to live UI buttons (`LaunchGuide`/`LaunchGallery`/`LaunchFeedbackForm` at `__init__.py:12749-12766`): `guide: youtube.com`, `gallery: liquifeel.xyz`, `get_pro: .../wiki/Upgrade`, `website: wordpress.com`, `feedback: .../wiki/Feedback`, plus placeholder social links.

**Files:**
- Modify: `data/urls.json`

- [ ] **Step 1: Obtain the real URLs from the product owner**

The correct values are product content, not derivable from code. Collect real, absolute `https://` URLs for every key below before editing.

- [ ] **Step 2: Replace the file contents**

Replace `data/urls.json` with real values (template — fill each `https://REPLACE_ME/...`):

```json
{
    "get_pro": "https://REPLACE_ME/pro",
    "website": "https://REPLACE_ME/",
    "twitter": "https://REPLACE_ME/twitter",
    "youtube": "https://REPLACE_ME/youtube",
    "instagram": "https://REPLACE_ME/instagram",
    "terms_and_conditions": "https://REPLACE_ME/terms",
    "privacy_policy": "https://REPLACE_ME/privacy",
    "feedback": "https://REPLACE_ME/feedback",
    "guide": "https://REPLACE_ME/guide",
    "gallery": "https://REPLACE_ME/gallery"
}
```

- [ ] **Step 3: Validate JSON and confirm no placeholders remain**

Run:
```bash
python3 -c "import json; d=json.load(open('data/urls.json')); assert all(v.startswith('https://') and 'REPLACE_ME' not in v and 'wikipedia' not in v for v in d.values()), d; print('urls OK')"
```
Expected: `urls OK`.

- [ ] **Step 4: Commit**

```bash
git add data/urls.json
git commit -m "fix: point UI buttons at real product URLs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Minor robustness fixes (M1, M2, M3)

**Files:**
- Modify: `__init__.py` — signature cache (`_separate_objects_last_sig`), seed-timer teardown, `AssemblyToggleHideExtras.execute`

- [ ] **Step 1 (M1): Key the separate-liquid signature cache by name, not pointer**

`_separate_objects_last_sig` is keyed by `obj.as_pointer()` (`__init__.py:9164`, `:9183`). Blender reuses freed addresses, so a deleted-then-recreated object can collide with a stale signature and skip a needed rebuild; the dict also never shrinks. Find both the read and write sites:

```bash
grep -n "_separate_objects_last_sig\|as_pointer()" __init__.py
```

At each site, replace the key `obj__.as_pointer()` (and the equivalent on `src`) with `obj__.name` (respectively `src.name`). Then in `_unregister_separate_timers` (`__init__.py:9189`), add:

```python
    _separate_objects_last_sig.clear()
```

- [ ] **Step 2 (M2): Tear down the assembly seed timer on unregister**

`_assembly_seed_drop_slots_timer` (`__init__.py:8516`) is registered at `:8527` but never unregistered. In `_unregister_separate_timers` (`__init__.py:9189`), add:

```python
    if bpy.app.timers.is_registered(_assembly_seed_drop_slots_timer):
        bpy.app.timers.unregister(_assembly_seed_drop_slots_timer)
```

- [ ] **Step 3 (M3): Remove the duplicate hide-apply**

In `AssemblyToggleHideExtras.execute` (~`__init__.py:12386`) the code sets `controls.assembly_hide_extras = new_state` (which fires `assembly_hide_extras_update` → `apply_assembly_hide_state`) and then calls `apply_assembly_hide_state(...)` again on the next line, doing a full-scene hide walk twice. Locate it:

```bash
grep -n "assembly_hide_extras = \|apply_assembly_hide_state" __init__.py
```

In `execute`, keep the assignment (it triggers the update callback) and delete the immediately-following redundant `n = apply_assembly_hide_state(...)` call, sourcing the reported count from the update path or from a single explicit call — not both.

- [ ] **Step 4: Run the smoke test**

Run:
```bash
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py
```
Expected: `All assembly smoke checks passed.`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add __init__.py
git commit -m "fix: name-key separate-liquid cache, tear down seed timer, dedupe hide-apply

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Stop the unit test from giving false confidence

**Root cause:** `tests/test_assembly_helpers.py` cannot import the addon (it pulls in Blender-only deps), so its "tests" only `assertIn` against the raw source text, and `test_parent_keep_transform_contract` asserts values it just set on a fake without calling any addon function. A logic regression that keeps function names intact stays green.

**Files:**
- Modify: `tests/test_assembly_helpers.py`

- [ ] **Step 1: Remove the no-op behavioral test and relabel the class**

In `tests/test_assembly_helpers.py`, delete `test_parent_keep_transform_contract` (lines 109-117) entirely — it exercises no product code. Rename the class docstring / add a module note making explicit these are **API-presence** checks only, and that behavioral coverage lives in `tests/run_assembly_blender_smoke.py`. Replace the class docstring line (the class at line 69) by adding, as the first statement inside `class AssemblyHelperTests(unittest.TestCase):`:

```python
    """API-presence checks only (the addon can't import without Blender).

    Real behavioral coverage of assembly/scale logic lives in
    tests/run_assembly_blender_smoke.py — run that under `blender --background`.
    """
```

- [ ] **Step 2: Add a marker round-trip assertion to the Blender smoke test**

In `tests/run_assembly_blender_smoke.py`, immediately after the existing `Clear-fill strip keeps assembly` block (currently ends at line 167), add:

```python
    # Marker (de)serialization must survive an IDProperty round-trip.
    sample = {'role': 'extra', 'controller': bottle.name,
              'version': list(mod.bl_info['version']), 'nested': {'a': 1}}
    clean = mod._lqfl_sanitize_marker(dict(sample))
    mod._lqfl_marker_set(cork, {'assembly': {'members': {}}, 'version': clean['version']})
    got = mod._lqfl_marker_get(cork)
    if got.get('version') is None:
        fail('Marker round-trip lost version')
    else:
        ok('Marker round-trip preserves data')
```

- [ ] **Step 3: Run both test layers**

Run:
```bash
python3 tests/test_assembly_helpers.py
"$BLENDER" --background --python tests/run_assembly_blender_smoke.py
```
Expected: unit test `OK`; smoke test `All assembly smoke checks passed.`.

- [ ] **Step 4: Commit**

```bash
git add tests/test_assembly_helpers.py tests/run_assembly_blender_smoke.py
git commit -m "test: drop no-op unit test, add marker round-trip to smoke test

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Final verification (before merge)

- [ ] Run the full smoke test on a real Blender 4.1 build: `"$BLENDER" --background --python tests/run_assembly_blender_smoke.py` → `All assembly smoke checks passed.`
- [ ] Run the unit test: `python3 tests/test_assembly_helpers.py` → OK.
- [ ] `git ls-files | grep -E '\.pyc$|\.blend1$|_draw_debug_out'` → empty.
- [ ] `python3 -c "import json,glob; [json.load(open(f)) for f in glob.glob('data/*.json')]"` → no error.
- [ ] Manual: bottle at scale 0.1 under a rotated parent → Set as Bottle + assign cork/label → scale stays 0.1, children stay attached, liquid not resized, no crash, addon disable/re-enable clean.

---

## Notes / deferred (not release-blocking)

- **Deeper unit coverage (I4 follow-up):** truly unit-testing the pure helpers (`_lqfl_sanitize_marker`, `_normalize_assembly_dict`, `key_from_name`) without Blender requires extracting them into a `bpy`-free module and updating call sites. Worth doing later; out of scope for this release pass.
- **`data/node_socket_data__.json`** (double-underscore variant) appears to be a stray duplicate of `node_socket_data.json` — verify and remove if unused (`grep -n "node_socket_data__" __init__.py filepaths.py`).
