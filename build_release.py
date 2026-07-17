#!/usr/bin/env python3
"""Build a distributable Blender-addon release zip for LiquiFeel.

Produces `dist/liquifeel-v<major>.<minor>.zip` whose single top-level folder is
`liquifeel/` (so Blender's "Install from Disk" registers it directly). The zip
bundles everything the addon needs at runtime -- including the large master
`.blend` asset that is deliberately NOT tracked in git (it exceeds GitHub's
100MB limit). Dev-only files (tests, docs, git, bytecode, backups) are excluded.

Usage:
    python3 build_release.py            # build dist/liquifeel-vX.Y.zip
    python3 build_release.py --out DIR  # write the zip into DIR instead of dist/
"""
from __future__ import annotations

import argparse
import ast
import fnmatch
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
ADDON_FOLDER = 'liquifeel'  # top-level folder inside the zip / Blender module name

# Paths are matched against the addon-root-relative POSIX path of each file, or
# any of its parent directory names. Anything matching is left out of the zip.
EXCLUDE_DIRS = {'.git', '__pycache__', 'tests', 'docs', 'dist', '.vscode',
                '.idea', 'scratchpad'}
EXCLUDE_GLOBS = [
    '*.pyc', '*.pyo', '*.pyd',
    '.gitignore', '.gitattributes', '.DS_Store',
    '*.blend1', '*.blend2', '*_bak_*', '*.bak_*',
    'build_release.py',
]
# Runtime assets that git does not track but the release MUST contain.
REQUIRED_UNTRACKED = ['data/blendfs/LiquidFeel_MASTER.blend']


def read_version() -> str:
    """Extract bl_info['version'] from __init__.py without importing bpy."""
    src = (REPO / '__init__.py').read_text(encoding='utf-8')
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'bl_info'
                for t in node.targets):
            bl_info = ast.literal_eval(node.value)
            return '.'.join(str(v) for v in bl_info.get('version', (0, 0)))
    raise SystemExit('ERROR: could not find bl_info["version"] in __init__.py')


def is_excluded(rel: Path) -> bool:
    if any(part in EXCLUDE_DIRS for part in rel.parts):
        return True
    name = rel.name
    return any(fnmatch.fnmatch(name, pat) for pat in EXCLUDE_GLOBS)


def iter_release_files() -> list[Path]:
    files = []
    for path in REPO.rglob('*'):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO)
        if is_excluded(rel):
            continue
        files.append(rel)
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description='Build the LiquiFeel release zip.')
    ap.add_argument('--out', default=str(REPO / 'dist'),
                    help='output directory (default: ./dist)')
    args = ap.parse_args()

    version = read_version()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f'{ADDON_FOLDER}-v{version}.zip'

    files = iter_release_files()

    # Fail loudly if a required runtime asset is missing on disk.
    missing = [p for p in REQUIRED_UNTRACKED if not (REPO / p).is_file()]
    if missing:
        print('ERROR: required runtime asset(s) missing on disk:', file=sys.stderr)
        for p in missing:
            print(f'  - {p}', file=sys.stderr)
        return 1
    have = {str(p.as_posix()) for p in files}
    for req in REQUIRED_UNTRACKED:
        if req not in have:  # excluded/untracked -> add explicitly
            files.append(Path(req))

    total = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel in sorted(set(files)):
            src = REPO / rel
            arcname = f'{ADDON_FOLDER}/{rel.as_posix()}'
            zf.write(src, arcname)
            total += src.stat().st_size

    size_mb = zip_path.stat().st_size / 1048576
    print(f'Built {zip_path}')
    print(f'  addon folder : {ADDON_FOLDER}/')
    print(f'  files        : {len(set(files))}')
    print(f'  uncompressed : {total / 1048576:.1f} MB')
    print(f'  zip size     : {size_mb:.1f} MB')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
