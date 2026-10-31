#!/usr/bin/env python
"""Install dsh-chem as a self-contained DSH plugin folder.

Why this exists: the plugin used to be wired with link:<checkout>/dsh-plugin, which
means deleting the source workspace breaks the installed plugin. A DSH plugin is
supposed to be one folder under <DSH_HOME>/plugins/<name>/ holding everything it
needs, so this script copies the JavaScript half AND the Python engine next to it.

Layout produced:
    <DSH_HOME>/plugins/dsh-chem/
        package.json  cordis.patch.yml  README.md  PATCH.md  install.json
        lib/            index.js engine.js sidebar-bridge.js client.js config.js bridge.js
        engine/bin/     chem.py
        engine/core/    chem/*.py chemdraw_tool/**
        data ->         %LOCALAPPDATA%/dsh-chem   (junction, see PATCH.md)

Usage:
    python tools/install_plugin.py            # install (idempotent)
    python tools/install_plugin.py --check    # compare installed copy with source
    python tools/install_plugin.py --remove   # delete the installed folder
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN_NAME = 'dsh-chem'
SKIP_DIRS = {'__pycache__', '.pytest_cache', 'data'}   # 'data' is the runtime junction, not content
SKIP_SUFFIX = {'.pyc', '.pyo'}


def dsh_home() -> Path:
    override = os.environ.get('DSH_HOME')
    if override:
        return Path(override)
    return Path.home() / '.dsh'


def local_app_data() -> Path:
    base = os.environ.get('LOCALAPPDATA')
    return Path(base) if base else Path.home() / 'AppData' / 'Local'


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def copy_tree(source: Path, target: Path) -> int:
    """Copy source into target, skipping caches. Returns the file count."""
    count = 0
    for root, dirs, files in os.walk(source):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith('.egg-info')]
        relative = Path(root).relative_to(source)
        (target / relative).mkdir(parents=True, exist_ok=True)
        for name in files:
            if Path(name).suffix in SKIP_SUFFIX:
                continue
            shutil.copy2(Path(root) / name, target / relative / name)
            count += 1
    return count


def plan():
    """(source, target-relative) pairs -- the whole self-contained plugin."""
    plugin = REPO / 'dsh-plugin'
    pairs = [
        (plugin / 'package.json', Path('package.json')),
        (plugin / 'cordis.patch.yml', Path('cordis.patch.yml')),
        (plugin / 'README.md', Path('README.md')),
        (REPO / 'bin' / 'chem.py', Path('engine') / 'bin' / 'chem.py'),
    ]
    # Only the modules index.js actually reaches: the old v1/v2 bridge.js and
    # config.js are unreachable from the 15-tool surface and carry a hardcoded
    # author checkout path, which has no business travelling with an install.
    for name in ('index.js', 'engine.js', 'sidebar-bridge.js', 'client.js'):
        pairs.append((plugin / 'lib' / name, Path('lib') / name))
    missing = [str(src) for src, _ in pairs if not src.is_file()]
    if missing:
        raise SystemExit('missing source files: ' + ', '.join(missing))
    return pairs


def tree_files(root: Path):
    out = []
    for base, dirs, files in os.walk(root):
        # Never descend into the runtime junction: it points at the venv (574 MB).
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.endswith('.egg-info')
                   and not os.path.islink(os.path.join(base, d))]
        out.extend(Path(base) / name for name in files if Path(name).suffix not in SKIP_SUFFIX)
    return out


def git_commit() -> str:
    try:
        out = subprocess.run(['git', '-C', str(REPO), 'rev-parse', '--short', 'HEAD'],
                             capture_output=True, text=True)
        return out.stdout.strip() or 'unknown'
    except Exception:
        return 'unknown'


def write_patch_note(target: Path, files: int, digest: str) -> None:
    note = """# PATCH.md -- 本机改动记录

- 来源: {repo} @ {commit} (D 盘工作区, 源码正身)
- 安装方式: python tools/install_plugin.py (复制, 不是 link)
- 安装文件: {files} 个, 聚合 sha256 {digest}
- 为什么复制: 插件要遵守「一个插件 = 一个自包含文件夹」; 用 link 接 D 盘的话,
  工作区一清空插件就死。现在引擎 (engine/bin, engine/core) 也搬进来了。

## 与源码的差异

- engine/ 是 bin/chem.py + core/ 的副本; engine.js 两种布局都能解析
  (<plugin>/engine/bin/chem.py 优先, 找不到才回源码仓库布局), 所以这份副本和源码
  是同一个文件, 没有改写。
- 未复制 runtime/py32/ (28 MB 的 32 位桥, 属于 KingDraw 通道; 15 个工具不用它)。
- data 是指向 %LOCALAPPDATA%/dsh-chem 的 junction: venv (574 MB)、库、模型都是
  机器级运行时, 不属于某个工作区, 放这里才能重装插件不重装依赖。

## 重新同步

源码改动后:

    python tools/install_plugin.py --check    # 看差在哪
    python tools/install_plugin.py            # 覆盖安装

不要在 {target} 里直接改代码: 下次同步会被覆盖。改源码, 再同步。
""".format(repo=REPO, commit=git_commit(), files=files, digest=digest, target=target)
    (target / 'PATCH.md').write_text(note, encoding='utf-8')


def make_data_junction(target: Path) -> str:
    link = target / 'data'
    real = local_app_data() / 'dsh-chem'
    if link.exists() or link.is_symlink():
        return 'exists'
    if not real.is_dir():
        return 'source-missing'
    # Junctions (unlike symlinks) need no privilege on Windows.
    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(real)],
                            capture_output=True, text=True)
    return 'created' if result.returncode == 0 else 'failed: ' + (result.stderr or result.stdout).strip()[:120]


OLD_NAME = 'dsh-chem-draw-tool'


def profile_link(target: Path) -> str:
    """Point <DSH_HOME>/profiles/desktop/node_modules at the install.

    The host resolves bundles out of the profile's node_modules, not out of
    plugins/. A folder that is healthy there is still invisible when this entry is
    missing, and the plugin manager shows 'cannot resolve profile bundle' - which is
    what happened when the dependency was renamed but the old link stayed behind.
    """
    profile = dsh_home() / 'profiles' / 'desktop'
    if not (profile / 'package.json').is_file():
        return 'no-profile'
    modules = profile / 'node_modules'
    modules.mkdir(parents=True, exist_ok=True)

    stale = modules / OLD_NAME
    if stale.is_symlink() or stale.exists():
        subprocess.run(['cmd', '/c', 'rmdir', str(stale)], capture_output=True, text=True)
        if stale.is_symlink() or stale.exists():
            stale.unlink()

    link = modules / PLUGIN_NAME
    if link.exists() or link.is_symlink():
        try:
            if link.resolve() == target.resolve():
                return 'ok'
        except OSError:
            pass
        subprocess.run(['cmd', '/c', 'rmdir', str(link)], capture_output=True, text=True)
        if link.is_symlink() or link.exists():
            link.unlink()

    result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(target)],
                            capture_output=True, text=True)
    return 'created' if result.returncode == 0 else 'failed: ' + (result.stderr or result.stdout).strip()[:120]


def install(target: Path) -> int:
    pairs = plan()
    target.mkdir(parents=True, exist_ok=True)
    for source, relative in pairs:
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    copy_tree(REPO / 'core', target / 'engine' / 'core')

    # The plugin carries a 2 KB stub of @deepseek-ai/dsh-tools so it can be loaded
    # outside the host (tests, probes). Ship it with the plugin or the folder is not
    # loadable on its own.
    modules = REPO / 'dsh-plugin' / 'node_modules'
    if modules.is_dir():
        copy_tree(modules, target / 'node_modules')

    files = tree_files(target)
    digest = hashlib.sha256()
    manifest = {}
    for path in sorted(files):
        relative = path.relative_to(target).as_posix()
        value = sha256_file(path)
        manifest[relative] = value
        digest.update(relative.encode('utf-8'))
        digest.update(value.encode('utf-8'))

    write_patch_note(target, len(files), digest.hexdigest())
    junction = make_data_junction(target)
    link = profile_link(target)

    record = {
        'plugin': PLUGIN_NAME,
        'source': str(REPO),
        'commit': git_commit(),
        'files': len(files),
        'aggregateSha256': digest.hexdigest(),
        'junction': junction,
        'profileLink': link,
        'installedAt': __import__('datetime').datetime.now().isoformat(timespec='seconds'),
        'manifest': manifest,
    }
    (target / 'install.json').write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps({'ok': True, 'target': str(target), 'files': len(files),
                      'pythonFiles': len(list((target / 'engine').rglob('*.py'))),
                      'junction': junction, 'profileLink': link,
                      'aggregateSha256': digest.hexdigest()[:16]},
                     ensure_ascii=False))
    return 0


def check(target: Path) -> int:
    source_pairs = plan()
    problems = []
    for source, relative in source_pairs:
        destination = target / relative
        if not destination.is_file():
            problems.append('missing: ' + relative.as_posix())
        elif sha256_file(source) != sha256_file(destination):
            problems.append('differs: ' + relative.as_posix())
    source_core = sorted(p.relative_to(REPO / 'core').as_posix() for p in tree_files(REPO / 'core'))
    engine_core = target / 'engine' / 'core'
    target_core = sorted(p.relative_to(engine_core).as_posix() for p in tree_files(engine_core)) if engine_core.is_dir() else []
    for item in source_core:
        if item not in target_core:
            problems.append('core missing in install: ' + item)
    for item in target_core:
        if item not in source_core:
            problems.append('core extra in install: ' + item)
    for item in source_core:
        source = REPO / 'core' / item
        copy = engine_core / item
        if copy.is_file() and sha256_file(source) != sha256_file(copy):
            problems.append('core differs: ' + item)
    link = dsh_home() / 'profiles' / 'desktop' / 'node_modules' / PLUGIN_NAME
    if (dsh_home() / 'profiles' / 'desktop' / 'package.json').is_file():
        try:
            if not link.exists() or link.resolve() != target.resolve():
                problems.append('profile node_modules/' + PLUGIN_NAME + ' does not point at this install')
        except OSError:
            problems.append('profile node_modules/' + PLUGIN_NAME + ' cannot be resolved')
    print(json.dumps({'ok': not problems, 'target': str(target), 'problems': problems[:8]},
                     ensure_ascii=False))
    return 0 if not problems else 1


def remove(target: Path) -> int:
    if not target.exists():
        print(json.dumps({'ok': True, 'removed': False, 'target': str(target)}))
        return 0
    junction = target / 'data'
    if junction.exists():
        subprocess.run(['cmd', '/c', 'rmdir', str(junction)], capture_output=True, text=True)
    shutil.rmtree(target)
    print(json.dumps({'ok': True, 'removed': True, 'target': str(target)}))
    return 0


def profile_package() -> Path:
    return dsh_home() / 'profiles' / 'desktop' / 'package.json'


def wire_profile(target: Path) -> dict:
    """Add the dependency and the bundle entry, so a fresh DSH actually loads it.

    The node_modules junction alone is not enough: the host also needs
    dependencies.dsh-chem (for resolution) and dsh.profile.bundles 里的名字
    (for loading). Both edits are idempotent, and the first run keeps a
    package.json.dsh-chem-backup copy next to the original.
    """
    path = profile_package()
    if not path.is_file():
        return {'ok': False, 'reason': 'no-profile',
                'hint': '先启动一次 DSH，让它生成 profiles/desktop/package.json，再跑这个脚本'}

    raw = path.read_text(encoding='utf-8')
    data = json.loads(raw)
    want = 'link:' + str(target).replace('\\', '/')
    changed = []
    dependencies = data.setdefault('dependencies', {})
    if dependencies.get(PLUGIN_NAME) != want:
        dependencies[PLUGIN_NAME] = want
        changed.append('dependencies.' + PLUGIN_NAME)
    profile = data.setdefault('dsh', {}).setdefault('profile', {})
    bundles = profile.setdefault('bundles', [])
    if PLUGIN_NAME not in bundles:
        bundles.append(PLUGIN_NAME)
        changed.append('dsh.profile.bundles')

    backup = None
    if changed:
        # Only keep a backup when something is actually rewritten: an untouched
        # run should not leave a stray file inside profiles/desktop.
        backup_path = path.with_name(path.name + '.dsh-chem-backup')
        if not backup_path.exists():
            backup_path.write_text(raw, encoding='utf-8')
        backup = str(backup_path)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'ok': True, 'package': str(path), 'changed': changed, 'backup': backup,
            'restart': '重开 DSH 才会加载新 bundle'}


def unwire_profile() -> dict:
    """Undo wire_profile: drop the dependency and the bundle entry."""
    path = profile_package()
    if not path.is_file():
        return {'ok': False, 'reason': 'no-profile'}
    data = json.loads(path.read_text(encoding='utf-8'))
    changed = []
    dependencies = data.get('dependencies') or {}
    if PLUGIN_NAME in dependencies:
        dependencies.pop(PLUGIN_NAME)
        changed.append('dependencies.' + PLUGIN_NAME)
    bundles = (data.get('dsh', {}).get('profile', {}) or {}).get('bundles') or []
    if PLUGIN_NAME in bundles:
        bundles.remove(PLUGIN_NAME)
        changed.append('dsh.profile.bundles')
    if changed:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'ok': True, 'package': str(path), 'changed': changed}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='install dsh-chem into a DSH plugins folder')
    parser.add_argument('--target', default=None, help='default <DSH_HOME>/plugins/dsh-chem')
    parser.add_argument('--check', action='store_true', help='compare only')
    parser.add_argument('--remove', action='store_true', help='delete the installed copy')
    parser.add_argument('--no-wire', action='store_true', help='skip the profile package.json edit')
    parser.add_argument('--unwire', action='store_true', help='only remove the profile entries')
    args = parser.parse_args(argv)
    target = Path(args.target) if args.target else dsh_home() / 'plugins' / PLUGIN_NAME
    if args.unwire:
        print(json.dumps(unwire_profile(), ensure_ascii=False))
        return 0
    if args.remove:
        code = remove(target)
        print(json.dumps(unwire_profile(), ensure_ascii=False))
        return code
    if args.check:
        return check(target)
    code = install(target)
    if not args.no_wire:
        print(json.dumps(wire_profile(target), ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
