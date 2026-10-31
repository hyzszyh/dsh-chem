'''Misuse-injection regression: the mistakes a human actually makes.

Every case asserts the same hard rules, because that is what a user sees:

  * the process exits non-zero and says why (no "ok: true" that did nothing),
  * the answer carries a Failure code and a non-empty message,
  * nothing prints a Python traceback,
  * no ChemDraw or KingDraw process is left running.

The cases are the ten classes from the task: empty input, invalid structure,
non-ASCII paths, missing vendor install, wrong interpreter bitness, huge input,
missing files, conflicting arguments, repeated calls, and interrupt hygiene --
plus the two-entry-point mistake (cd export takes a positional destination while
every kd command takes --out).

Run:  runtime/py32/python.exe test/test_misuse.py
'''
import json
import os
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, 'bin', 'cli.py')
PY32 = os.path.join(ROOT, 'runtime', 'py32', 'python.exe')
PY64 = r'%LOCALAPPDATA%\Programs\Python\Python311\python.exe'
# Under test/out/, not the repository root: this suite writes real .king and
# .png files through Chinese paths, and dropping them next to the source made
# `git status` dirty after every run. The thing being tested is the non-ASCII
# path, not its address.
CN_DIR = os.path.join(ROOT, 'test', 'out', '测试目录')
OUT_DIR = os.path.join(ROOT, 'test', 'out')
SRC_MOL = os.path.join(OUT_DIR, 'kd_save_src_phenol.mol')


def _say(message):
    print('    ' + message)


def run(argv, py='py32', timeout=240):
    '''Run the CLI; retry once when another session's ChemDraw killed our COM ref.

    Measured (captain, 2026-xx): ChemDraw has one COM instance. A process that
    attaches to a foreign instance loses every reference the moment the owner
    calls Quit(), surfacing here as E99 'Documents.Add() failed' with
    'RPC 服务器不可用'. That is contention, not a defect, so retry once.
    '''
    exe = PY32 if py == 'py32' else PY64
    for attempt in (1, 2):
        proc = subprocess.run([exe, CLI] + list(argv), capture_output=True,
                              timeout=timeout, cwd=ROOT)
        out = proc.stdout.decode('utf-8', 'replace')
        err = proc.stderr.decode('utf-8', 'replace')
        collision = attempt == 1 and ('Documents.Add() failed' in out
                                      or 'RPC' in out)
        if collision:
            _say('COM collision (another session quit ChemDraw), retrying once')
            time.sleep(3.0)
            continue
        return proc.returncode, out, err
    return proc.returncode, out, err


def _no_traceback(out, err):
    blob = (out or '') + (err or '')
    assert 'Traceback (most recent call last)' not in blob, \
        'a traceback reached the user:\n' + blob[-600:]


def envelope(argv, py='py32'):
    # The default output is the human summary; a misuse check needs the
    # envelope, so ask for it rather than assuming the default.
    if '--json' not in argv:
        argv = list(argv) + ['--json']
    rc, out, err = run(argv, py)
    _no_traceback(out, err)
    try:
        return rc, json.loads(out), out, err
    except ValueError:
        raise AssertionError(' '.join(argv[:4]) + ': no JSON on stdout (rc=%s)\n'
                             'stdout=%r\nstderr=%r' % (rc, out[:400], err[:300]))


def expect_failure(argv, py, code=None, contains=None):
    '''A misuse must answer: rc!=0, ok=false, a code, a message, no traceback.'''
    rc, payload, out, err = envelope(argv, py)
    failure = payload.get('failure') or {}
    label = ' '.join(a[:40] for a in argv[:4])
    _say('%-46s rc=%s ok=%r code=%r msg=%r' % (
        label, rc, payload.get('ok'), failure.get('code'),
        (failure.get('message') or '')[:60]))
    assert payload.get('ok') is False, '%s: ok was not false' % label
    assert rc != 0, '%s: exit code was 0 for a failure' % label
    assert failure.get('code'), '%s: no failure code' % label
    assert (failure.get('message') or '').strip(), '%s: empty failure message' % label
    if code:
        assert failure.get('code') == code, (
            '%s: code %r != %r' % (label, failure.get('code'), code))
    if contains:
        blob = (failure.get('message') or '') + ' ' + str(failure.get('detail') or '')
        assert contains.lower() in blob.lower(), (
            '%s: %r not in %r' % (label, contains, blob[:200]))
    return payload


# 1. empty input ------------------------------------------------------------
def test_empty_smiles_is_a_failure_not_an_empty_success():
    expect_failure(['identity', '', '--json'], 'py64', code='E06', contains='empty')
    expect_failure(['kd', 'mol', ''], 'py32', code='E06')
    expect_failure(['kd', 'formula', '--smiles', ''], 'py32', code='E06')
    # no argument at all is also a misuse, and used to be a TypeError
    expect_failure(['kd', 'formula'], 'py32', code='E06')
    expect_failure(['kd', 'to3d', '--smiles', ''], 'py32', code='E06')
    expect_failure(['kd', 'layout', '--smiles', ''], 'py32', code='E06')


# 2. invalid structure ------------------------------------------------------
def test_invalid_structure_is_rejected_by_both_channels():
    expect_failure(['identity', 'hello', '--json'], 'py64', code='E06')
    payload = expect_failure(['cd', 'draw', 'not-a-smiles'], 'py64', code='E06',
                             contains='parse')
    assert 'rdkit' in json.dumps(payload).lower(), payload


# 3. non-ASCII paths --------------------------------------------------------
def test_chinese_paths_are_written_not_silently_skipped():
    os.makedirs(CN_DIR, exist_ok=True)
    mol = os.path.join(CN_DIR, '分子.mol')
    king = os.path.join(CN_DIR, '分子.king')
    png = os.path.join(CN_DIR, '画.png')
    for path in (mol, king, png):
        if os.path.isfile(path):
            os.remove(path)
    rc, payload, out, err = envelope(['kd', 'mol', 'c1ccccc1O', '--out', mol], 'py32')
    assert rc == 0 and payload.get('ok'), payload.get('failure')
    assert os.path.isfile(mol) and os.path.getsize(mol) > 100, 'molfile not written'
    rc, payload, out, err = envelope(['kd', 'save', mol, '--out', king], 'py32')
    _say('kd save 测试目录/分子.king -> ok=%r bytes=%r' % (
        payload.get('ok'), (payload.get('data') or {}).get('bytes')))
    assert payload.get('ok'), payload.get('failure')
    assert os.path.isfile(king) and os.path.getsize(king) > 100
    rc, payload, out, err = envelope(['cd', 'draw', 'c1ccccc1O', '--out', png], 'py64')
    exported = (payload.get('data') or {}).get('export') or {}
    _say('cd draw --out 测试目录/画.png -> ok=%r bytes=%r' % (
        payload.get('ok'), (exported.get('data') or {}).get('bytes')))
    assert payload.get('ok'), payload.get('failure')
    assert os.path.isfile(png), 'ChemDraw SaveAs silently skipped a non-ASCII path'
    assert os.path.getsize(png) > 1000, os.path.getsize(png)


# 4. missing vendor install ------------------------------------------------
def test_a_named_kingdraw_folder_is_not_silently_replaced():
    bogus = os.path.join(ROOT, 'no-such-kingdraw-home')
    rc, out, err = run(['doctor', 'kd', '--kingdraw-home', bogus], 'py32')
    _no_traceback(out, err)
    _say('doctor kd --kingdraw-home <bogus> -> rc=%s, warning=%r' % (
        rc, 'no silent fallback' in ' '.join(out.split())))
    assert rc != 0, 'a missing KingDraw install reported success'
    assert 'no silent fallback' in ' '.join(out.split()), out[:300]


def test_32bit_chemdraw_reports_e08_with_a_reason():
    rc, out, err = run(['cd', 'doctor'], 'py32')
    _no_traceback(out, err)
    _say('cd doctor (32-bit) -> rc=%s, mentions 32-bit=%r, E08=%r' % (
        rc, '32-bit' in out, 'E08' in out))
    assert rc != 0, 'cd doctor succeeded under a 32-bit interpreter'
    assert 'E08' in out and '32-bit' in out, out[:300]


# 5. wrong interpreter bitness ---------------------------------------------
def test_64bit_kingdraw_answers_e04_or_bridges():
    rc, payload, out, err = envelope(['kd', 'mol', 'c1ccccc1'], 'py64')
    failure = payload.get('failure') or {}
    _say('kd mol under 64-bit -> ok=%r code=%r msg=%r' % (
        payload.get('ok'), failure.get('code'), (failure.get('message') or '')[:60]))
    if payload.get('ok'):
        assert (payload.get('data') or {}).get('text'), 'bridged but returned nothing'
    else:
        assert failure.get('code') == 'E04', failure
        assert (failure.get('message') or '').strip()


# 6. oversized input -------------------------------------------------------
def test_oversized_input_fails_without_a_traceback():
    '''4000 atoms used to kill the interpreter (exit 3221225725, no output).'''
    payload = expect_failure(['identity', 'C' * 4000, '--json'], 'py64',
                            code='E06', contains='longer than')
    assert payload.get('canonical_smiles') is None
    payload = expect_failure(['cd', 'draw', 'C' * 4000], 'py64', code='E06',
                             contains='longer than')
    assert payload.get('data') is None, 'a refused draw reported data'
    long_name = os.path.join(OUT_DIR, 'a' * 200 + '.mol')
    expect_failure(['kd', 'open', long_name], 'py32', code='E06')


# 7. missing files ---------------------------------------------------------
def test_missing_files_are_named_in_the_failure():
    payload = expect_failure(['kd', 'king', '/nope.king'], 'py32', code='E06')
    assert 'nope.king' in json.dumps(payload), payload
    v = expect_failure(['kd', 'open', '/nope.mol'], 'py32', code='E06')
    assert (v.get('failure') or {}).get('detail'), v
    expect_failure(['kd', 'save', '/nope.mol'], 'py32', code='E06')
    expect_failure(['kd', 'smiles', '/nope.mol'], 'py32', code='E06')


# 8. conflicting arguments -------------------------------------------------
def test_modify_without_an_action_says_so():
    payload = expect_failure(['cd', 'modify'], 'py64', code='E06')
    failure = payload.get('failure') or {}
    _say('cd modify -> %r / hint %r' % (failure.get('message'),
                                        (failure.get('hint') or '')[:60]))
    assert 'action' in (failure.get('message') or '').lower()
    assert '--replace' in (failure.get('hint') or '')


def test_a_destination_can_be_positional_or_flagged():
    '''cd export/figure take a positional path; every kd command takes --out.'''
    pairs = []
    for command, extra in (('export', []), ('figure', ['--dpi', '300'])):
        written = []
        for name, argv in (
                ('pos', ['cd', command, os.path.join(OUT_DIR, 'spell_pos.png'),
                         '--smiles', 'c1ccccc1O'] + extra),
                ('flag', ['cd', command, '--out',
                          os.path.join(OUT_DIR, 'spell_flag.png'),
                          '--smiles', 'c1ccccc1O'] + extra)):
            rc, payload, out, err = envelope(argv, 'py64')
            assert rc == 0 and payload.get('ok'), (command, name, payload.get('failure'))
            path = (payload.get('data') or {}).get('path')
            assert path and os.path.isfile(path), (command, name, path)
            written.append(os.path.getsize(path))
            _say('cd %-6s %-4s -> %r bytes=%s' % (command, name, path, written[-1]))
        pairs.append((command, written))
    for command, written in pairs:
        assert written[0] == written[1], (
            'cd %s: the two spellings produced different files %r' % (command, written))
    expect_failure(['cd', 'export', '--smiles', 'c1ccccc1O'], 'py64', code='E06',
                   contains='destination')


def test_the_format_extension_is_added_on_both_channels():
    stem_cd = os.path.join(OUT_DIR, 'noext_misuse_cd')
    stem_kd = os.path.join(OUT_DIR, 'noext_misuse_kd')
    stem_save = os.path.join(OUT_DIR, 'noext_misuse_save')
    for stem in (stem_cd, stem_kd, stem_save):
        for ext in ('.png', '.king'):
            if os.path.isfile(stem + ext):
                os.remove(stem + ext)
    rc, payload, out, err = envelope(['cd', 'export', stem_cd, '--smiles', 'c1ccccc1O'],
                                     'py64')
    path = (payload.get('data') or {}).get('path') or ''
    _say('cd export without extension -> %r' % path)
    assert rc == 0 and path.endswith('.png') and os.path.isfile(path), path
    rc, payload, out, err = envelope(['kd', 'save', SRC_MOL, '--out', stem_save], 'py32')
    path = (payload.get('data') or {}).get('out') or ''
    _say('kd save without extension -> %r' % path)
    assert rc == 0 and path.endswith('.king') and os.path.isfile(path), path
    rc, payload, out, err = envelope(['kd', 'export', SRC_MOL, '--out', stem_kd], 'py32')
    path = (payload.get('data') or {}).get('out') or ''
    _say('kd export without extension -> %r' % path)
    assert rc == 0 and path.endswith('.png') and os.path.isfile(path), path


# 9. repeated calls --------------------------------------------------------
def test_saving_twice_overwrites_and_can_refuse():
    dest = os.path.join(CN_DIR, '重复.king')
    if not os.path.isfile(SRC_MOL):
        return 'no source molfile: run test_kd_save.py first'
    if os.path.isfile(dest):
        os.remove(dest)
    rc, first, out, err = envelope(['kd', 'save', SRC_MOL, '--out', dest], 'py32')
    rc2, second, out, err = envelope(['kd', 'save', SRC_MOL, '--out', dest], 'py32')
    assert first.get('ok') and second.get('ok'), (first.get('failure'),
                                                  second.get('failure'))
    _say('save twice: first=%r bytes, second=%r bytes (overwrite is the default)' % (
        (first.get('data') or {}).get('bytes'), (second.get('data') or {}).get('bytes')))
    assert (first.get('data') or {}).get('bytes') == (second.get('data') or {}).get('bytes')
    expect_failure(['kd', 'save', SRC_MOL, '--out', dest, '--no-overwrite'], 'py32',
                   code='E06', contains='exists')


# 10. interrupt hygiene ---------------------------------------------------
def test_an_interrupted_command_leaves_no_wedged_process():
    '''SIGTERM in the middle of "kd export" must leave a closable app, not a wedge.'''
    sys.path.insert(0, os.path.join(ROOT, 'core'))
    from chemdraw_tool.adapters import kd_open
    for pid in kd_open.list_pids():
        kd_open.close_app(pid, 10.0)
    baseline = set(kd_open.list_pids())
    if not os.path.isfile(SRC_MOL):
        return 'no source molfile: run test_kd_save.py first'
    proc = subprocess.Popen([PY64, CLI, 'kd', 'export', SRC_MOL,
                             '--out', os.path.join(CN_DIR, '中断.png')],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            cwd=ROOT)
    time.sleep(4.0)
    proc.terminate()
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
    started = set(kd_open.list_pids()) - baseline
    _say('interrupted kd export: cli ended, KingDraw started=%r' % (sorted(started),))
    for pid in started:
        closed = kd_open.close_app(pid, 12.0)
        assert closed.data.get('closed'), 'the app started by the CLI could not be closed'
    assert not (set(kd_open.list_pids()) - baseline), kd_open.list_pids()


def test_doctor_exit_code_follows_its_own_rule():
    '''doctor is a report, and its exit code has to match what it documents.

    Measured: the rule said 'one working channel is enough' while the print
    loop did rc = max(rc, _emit()), so 'doctor' exited 1 on both interpreters
    -- a healthy install reporting failure from whichever side it was run.
    The expected code here is computed from the payload, so this holds on a
    machine with neither channel installed.
    '''
    for label, argv in (('doctor', ['doctor']),
                        ('doctor --strict', ['doctor', '--strict'])):
        rc, payload, out, err = envelope(argv, 'py64')
        rows = payload if isinstance(payload, list) else [payload]
        available = [bool(p.get('available')) for p in rows]
        strict = '--strict' in argv
        expected = (0 if available and all(available) else 1) if strict else (
            0 if any(available) else 1)
        _say('%-16s rc=%s available=%r expected=%s' % (label, rc, available, expected))
        assert rc == expected, (label, rc, expected, available)


def test_close_reports_that_nothing_was_there():
    '''kd close --pid X on a pid that never ran is ok, and says so.

    close_app answers ok for a missing pid (there is nothing to fail at), and
    the command used to print a bare success: measured with --pid 999999, no
    warning at all. --pid 0 was worse: 0 is falsy, so it silently fell back to
    'every window'. Both are pinned here, and both are engine-free.
    '''
    rc, payload, out, err = envelope(['kd', 'close', '--pid', '999999'], 'py64')
    _say('close --pid 999999: rc=%s ok=%r warns=%r' % (
        rc, payload.get('ok'), payload.get('warnings')))
    assert rc == 0 and payload.get('ok') is True, payload
    joined = ' '.join(payload.get('warnings') or [])
    assert '999999' in joined and 'nothing to close' in joined, joined
    rows = (payload.get('data') or {}).get('results') or []
    assert rows and rows[0]['already_gone'] is True, rows

    rc, payload, out, err = envelope(['kd', 'close', '--pid', '0'], 'py64')
    rows = (payload.get('data') or {}).get('results') or []
    _say('close --pid 0: rc=%s targets=%r' % (rc, [r['pid'] for r in rows]))
    assert [r['pid'] for r in rows] == [0], (
        'an explicit --pid 0 must not fall back to every window: %r' % (rows,))


def test_no_vendor_process_is_left_behind():
    sys.path.insert(0, os.path.join(ROOT, 'core'))
    from chemdraw_tool.adapters import kd_open
    left = kd_open.list_pids()
    chem = subprocess.run(['tasklist', '/fi', 'IMAGENAME eq ChemDraw.exe'],
                          capture_output=True, text=True, errors='replace')
    chem_present = 'ChemDraw.exe' in (chem.stdout or '')
    _say('kingdraw pids=%r, chemdraw running=%r' % (left, chem_present))
    assert not left, left
    assert not chem_present, chem.stdout


ORDER = [
    test_empty_smiles_is_a_failure_not_an_empty_success,
    test_invalid_structure_is_rejected_by_both_channels,
    test_chinese_paths_are_written_not_silently_skipped,
    test_a_named_kingdraw_folder_is_not_silently_replaced,
    test_32bit_chemdraw_reports_e08_with_a_reason,
    test_64bit_kingdraw_answers_e04_or_bridges,
    test_oversized_input_fails_without_a_traceback,
    test_missing_files_are_named_in_the_failure,
    test_modify_without_an_action_says_so,
    test_a_destination_can_be_positional_or_flagged,
    test_the_format_extension_is_added_on_both_channels,
    test_saving_twice_overwrites_and_can_refuse,
    test_an_interrupted_command_leaves_no_wedged_process,
    test_close_reports_that_nothing_was_there,
    test_no_vendor_process_is_left_behind,
]
BUDGET_S = 420.0


def main():
    started = time.monotonic()
    passed = failed = skipped = 0
    for func in ORDER:
        t0 = time.monotonic()
        try:
            note = func()
        except AssertionError as exc:
            failed += 1
            print('FAIL %s (%.2fs)' % (func.__name__, time.monotonic() - t0))
            print('    ' + str(exc).strip().replace('\n', '\n    '))
        except Exception:
            failed += 1
            print('ERROR %s (%.2fs)' % (func.__name__, time.monotonic() - t0))
            print('    ' + traceback.format_exc().strip().replace('\n', '\n    '))
        else:
            if isinstance(note, str):
                skipped += 1
                print('SKIP %s (%.2fs) -- %s' % (func.__name__, time.monotonic() - t0, note))
            else:
                passed += 1
                print('PASS %s (%.2fs)' % (func.__name__, time.monotonic() - t0))
        sys.stdout.flush()
    elapsed = time.monotonic() - started
    print('-' * 60)
    print('%d passed, %d skipped, %d failed, %d total in %.1fs (budget %.0fs)'
          % (passed, skipped, failed, passed + skipped + failed, elapsed, BUDGET_S))
    if elapsed > BUDGET_S:
        print('over budget')
        return 1
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
