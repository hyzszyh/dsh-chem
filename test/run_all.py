'''One command that runs every check in this repository.

    python test/run_all.py                 # everything this machine can do
    python test/run_all.py --list          # what exists, and what it needs
    python test/run_all.py --only presentation,contract_sync
    python test/run_all.py --skip chemdraw # skip the vendor-specific suites
    python test/run_all.py --force         # run even if the probe says no

Why this file exists: the suite needs two interpreters (the KingDraw DLL is
x86, the ChemDraw typelib is x64), two vendor applications and node. Which file
needs which lived only in the heads of whoever had run them, so "did you run
the tests?" had no reproducible answer -- and a check nobody can re-run is not
a check. This is that answer.

A suite whose prerequisites are missing is reported as SKIP with the reason,
never as PASS: pretending a vendor check ran is the failure mode this whole
repository is built to avoid.
'''
from __future__ import annotations

import argparse
import os
import shutil
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY32 = os.path.join(ROOT, 'runtime', 'py32', 'python.exe')

# name, interpreter, engine requirements, timeout in seconds
SUITES = [
    ('test_applock', 'py64', (), 180),
    ('test_architecture_backend', 'py64', (), 180),
    ('test_com_timeout', 'py64', (), 180),
    ('test_contract_sync', 'py64', (), 240),
    ('test_examples', 'py64', (), 900),
    ('test_install_script', 'py64', (), 180),
    ('test_mcp_wire', 'py64', (), 240),
    ('test_presentation', 'py64', (), 180),
    ('test_plugin_client_render', 'node', (), 120),
    ('test_plugin_render', 'node', (), 180),
    ('test_plugin_tools', 'node', (), 300),
    ('test_mcp_tasks', 'py64', (), 300),
    ('test_v2_surface', 'py64', (), 240),
    ('test_cd_adapter', 'py64', ('chemdraw',), 900),
    ('test_cd_cli_mcp', 'py64', ('chemdraw',), 900),
    ('test_crosscheck', 'py64', ('chemdraw', 'kingdraw'), 900),
    ('test_structure_fidelity', 'py64', ('chemdraw', 'kingdraw'), 600),
    ('test_kd_adapter', 'py32', ('kingdraw',), 300),
    ('test_kd_export', 'py32', ('kingdraw',), 420),
    ('test_kd_open', 'py32', ('kingdraw',), 180),
    ('test_kd_save', 'py32', ('kingdraw',), 300),
    ('test_misuse', 'py32', ('kingdraw',), 600),
]


def _bits(exe):
    try:
        out = subprocess.run([exe, '-c', 'import struct;print(struct.calcsize("P"))'],
                             capture_output=True, text=True, timeout=60).stdout.strip()
        return int(out[-1])
    except Exception:
        return None


def find_py64():
    if struct.calcsize('P') == 8:
        return sys.executable
    for candidate in (shutil.which('python'), shutil.which('python3'), shutil.which('py')):
        if candidate and _bits(candidate) == 8:
            return candidate
    return None


def probe(engine):
    '''Is this engine plausibly installed? Cheap enough to run always.'''
    if engine == 'chemdraw':
        try:
            import winreg
        except ImportError:
            return False, 'not on Windows'
        for progid in ('ChemDraw_x64.Application', 'ChemDraw.Application'):
            try:
                winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, progid))
                return True, progid
            except OSError:
                continue
        return False, 'no ChemDraw ProgID in the registry'
    if engine == 'kingdraw':
        if not os.path.isfile(PY32):
            return False, 'runtime/py32/python.exe is missing (scripts/fetch_runtime.py)'
        homes = [os.environ.get('KINGDRAW_HOME'), 'D:/tool/KingDraw',
                 os.path.join(ROOT, 'tool', 'KingDraw')]
        for home in homes:
            if home and os.path.isfile(os.path.join(home, 'GRDKitDll.dll')):
                return True, home
        return False, 'GRDKitDll.dll not found under KINGDRAW_HOME'
    return True, ''


def discover():
    found = set()
    for entry in sorted(os.listdir(HERE)):
        if entry.startswith('test_') and entry.endswith(('.py', '.mjs')):
            found.add(os.path.splitext(entry)[0])
    declared = {row[0] for row in SUITES}
    missing = sorted(found - declared)
    phantom = sorted(declared - found)
    if missing or phantom:
        print('the suite table is out of date:')
        for name in missing:
            print('  %s exists but is not listed here' % name)
        for name in phantom:
            print('  %s is listed here but does not exist' % name)
        raise SystemExit(2)


# Signatures this machine produces on a bad day, seen once each. They are not
# excused -- the suite still fails -- but naming them stops a reader from
# hunting a bug in the code that just ran a vendor application.
#
# Measured: one sweep in four had test_misuse hang 126 s (about the 120 s COM
# deadline) and fail two checks; the same group re-run 4/4 passed, and the
# next full sweep was 17/17. A retry flag here would have hidden that.
TRANSIENT = (
    ('E10', 'COM_STALLED -- a ChemDraw call hit the deadline; re-run once first'),
    ('COM_STALLED', 'a ChemDraw call hit the deadline; re-run once first'),
    ('Documents.Add() failed',
     'two processes shared one ChemDraw instance; re-run once first'),
    ('never confirmed it opened',
     'a leftover KingDraw holds the single-instance lock -- clear it with '
     '"taskkill /F /IM KingDraw.WpfForm.exe" and re-run; the suites after this '
     'one fail for the same reason, not because of their own code'),
)

# This table is only read on the failure path, so a malformed entry stays
# invisible until something actually goes red -- exactly when the reader
# needs the hint. Measured: a four-string entry sat here through three green
# sweeps and turned the first red one into a ValueError instead of a hint.
for _entry in TRANSIENT:
    if len(_entry) != 2 or not all(isinstance(part, str) for part in _entry):
        raise SystemExit('TRANSIENT entry %r must be (signature, hint)'
                         % (_entry[0] if _entry else '',))


def transient_hint(blob):
    for signature, hint in TRANSIENT:
        if signature in (blob or ''):
            return hint
    return None


def excerpt(blob, lines=6):
    '''The part of a failing suite's output that says why.

    The last three lines of these suites are a tally -- '12 passed, 0 skipped,
    2 failed' -- which says how much broke and never what. Prefer the lines
    that carry a verdict. (First version printed the tail, and a real failure
    reached me as a bare count with no reason at all.)
    '''
    kept = [line.rstrip() for line in (blob or '').splitlines() if line.strip()]
    verdicts = [index for index, line in enumerate(kept)
                if line.lstrip().startswith(('FAIL', 'ERROR', 'Traceback',
                                              'assert', 'AssertionError'))]
    if verdicts:
        first = verdicts[0]
        body = kept[first:first + lines]
        if kept[-1] not in body:
            body.append(kept[-1])
    else:
        body = kept[-lines:]
    return '\n'.join('      ' + line[:160] for line in body)


def run_suite(name, interpreter, requirements, timeout, args):
    if interpreter == 'node':
        exe = shutil.which('node')
        if not exe:
            return 'SKIP', 'node is not on PATH', 0.0
        argv = [exe, os.path.join(HERE, name + '.mjs')]
    else:
        exe = find_py64() if interpreter == 'py64' else PY32
        if not exe or not os.path.isfile(exe):
            return 'SKIP', 'the %s interpreter is not available' % interpreter, 0.0
        argv = [exe, os.path.join(HERE, name + '.py')]
    if not args.force:
        for engine in requirements:
            ok, why = probe(engine)
            if not ok:
                return 'SKIP', '%s: %s' % (engine, why), 0.0
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    started = time.time()
    try:
        proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', env=env,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return 'FAIL', 'timed out after %ds' % timeout, time.time() - started
    elapsed = time.time() - started
    blob = (proc.stdout or '') + (proc.stderr or '')
    if proc.returncode == 0:
        return 'PASS', '', elapsed
    reason = excerpt(blob)
    hint = transient_hint(blob)
    if hint:
        reason += '\n      ^ ' + hint
    return 'FAIL', reason, elapsed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--only', help='comma-separated suite names')
    parser.add_argument('--skip', help='comma-separated engines to skip')
    parser.add_argument('--force', action='store_true',
                        help='run even when the engine probe says it is missing')
    parser.add_argument('--list', action='store_true', help='print the table and stop')
    args = parser.parse_args(argv)
    discover()

    if args.list:
        for name, interpreter, needs, timeout in SUITES:
            print('%-28s %-5s %-24s %ds' % (name, interpreter,
                                            ','.join(needs) or '-', timeout))
        return 0

    # Accept both spellings: 'presentation' and 'test_presentation' name the
    # same suite, because nobody should have to remember a file prefix to ask
    # for one check.
    def suite_name(part):
        part = part.strip()
        return part if part.startswith('test_') else 'test_' + part

    only = set(suite_name(part) for part in (args.only or '').split(',') if part.strip())
    skipping = set(part.strip() for part in (args.skip or '').split(',') if part.strip())
    selected = [row for row in SUITES if not only or row[0] in only]
    if only:
        unknown = only - {row[0] for row in SUITES}
        if unknown:
            print('unknown suite(s): ' + ', '.join(sorted(unknown)))
            return 2

    print('running %d suite(s) from %s' % (len(selected), ROOT))
    print('')
    counts = {'PASS': 0, 'FAIL': 0, 'SKIP': 0}
    failures = []
    started_all = time.time()
    for name, interpreter, needs, timeout in selected:
        wanted = [engine for engine in needs if engine not in skipping]
        if len(wanted) != len(needs):
            counts['SKIP'] += 1
            print('SKIP  %-28s asked to skip %s' % (name, ','.join(sorted(skipping))))
            continue
        state, detail, elapsed = run_suite(name, interpreter, needs, timeout, args)
        counts[state] += 1
        print('%-5s %-28s %5.1fs%s' % (state, name, elapsed,
                                        ('  ' + detail.splitlines()[0].strip())
                                        if detail and state == 'SKIP' else ''))
        if state == 'FAIL':
            print(detail)
            failures.append(name)
    total = time.time() - started_all
    print('')
    print('%d passed, %d failed, %d skipped in %.1fs'
          % (counts['PASS'], counts['FAIL'], counts['SKIP'], total))
    if failures:
        print('failed: ' + ', '.join(failures))
        return 1
    if counts['SKIP'] and not counts['PASS']:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())