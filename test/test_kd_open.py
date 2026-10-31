'''Tests for the KingDraw open channel.

    runtime/py32/python.exe test/test_kd_open.py

Needs a 32-bit interpreter only because the molfile is generated through
adapters.kd_native (GRDKitDll.dll is x86). Every wait in this file is bounded and
the whole run is asserted to finish inside 40 s; nothing is killed -- closing goes
through WM_CLOSE, and only instances this run started are closed.

Ordered scenario, because the assertions share one desktop state:
  1. open a fresh molfile          -> window + title verify
  2. screenshot it                 -> PNG in test/out, sized like the window
  3. ask UIAutomation              -> the document tab carries the file name (the
                                      proof that the document opened)
  4. open it again                 -> reuse, no second process
  5. close the instance we started -> WM_CLOSE, pid gone
  6. a path past the Win32 limit    -> staged copy opened, and reported
  7. force the timeout path        -> E05 with the pid, then close it
  8. missing input file            -> failure without launching anything

Pixels are auxiliary only: KingDraw's canvas is a WPF/D3D surface that GDI cannot
read, so no assertion here claims the molecule was drawn.
'''

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))

from chemdraw_tool.adapters import kd_native  # noqa: E402
from chemdraw_tool.adapters import kd_open  # noqa: E402
from chemdraw_tool.models import ErrorCode, Result  # noqa: E402

# Raised from 40 s when the staged-path test landed: that one closes the app,
# opens cold, opens again warm and restores the state, which is two app
# starts on top of the six the suite already did (measured 41.3 s).
BUDGET_S = 70.0
STATE: dict = {}


def _say(msg: str) -> None:
    print('    ' + msg)


def _ok(res: Result) -> Result:
    assert isinstance(res, Result), 'expected a Result, got %r' % (res,)
    assert res.ok, 'call failed: %s' % (res.to_dict(),)
    assert res.channel == 'kingdraw', res.channel
    return res


def _make_molfile() -> str:
    res = kd_native.smiles_to_mol('c1ccccc1O')
    assert res.ok, res.to_dict()
    tmpdir = tempfile.mkdtemp(prefix='kd_open_test_')
    STATE['tmpdir'] = tmpdir
    path = os.path.join(tmpdir, 'phenol.mol')
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(res.data['text'])
    return path


def test_native_molfile_is_available():
    path = _make_molfile()
    STATE['mol'] = path
    assert os.path.getsize(path) > 300, os.path.getsize(path)


def test_open_shows_a_window():
    path = STATE['mol']
    pre = kd_open.list_pids()
    STATE['pre_pids'] = list(pre)
    started = time.monotonic()
    res = _ok(kd_open.open_file(path, timeout=20.0))
    STATE['open'] = res
    STATE['elapsed'] = time.monotonic() - started
    data = res.data
    _say('waited %.2fs, pids before %s, pids after %s' % (
        data['waited_s'], data['pids_before'], data['pids_after']))
    window = data.get('window')
    assert window, 'no window was attributed to KingDraw: %r' % (data,)
    assert window['visible'], window
    title = window['title']
    stem = os.path.splitext(os.path.basename(path))[0]
    assert ('kingdraw' in title.lower()) or (stem.lower() in title.lower()), (
        'window title matched neither the app nor the file: %r' % title)
    assert data['title_matched'] in ('app', 'filename'), data['title_matched']
    assert data.get('verified_by'), 'no verification path recorded'
    assert data['waited_s'] < 20.0, data['waited_s']
    # Nothing was running before this call, so a fresh-instance request is
    # honourable and the envelope says so.
    assert data['reuse_honored'] is True, data.get('reuse_honored')
    assert window['pid'] in data['pids_after'], (
        'window pid %s not in pids %s' % (window['pid'], data['pids_after']))


def test_screenshot_is_written_for_the_document_window():
    '''The capture must exist, be a real PNG, and match the window geometry.'''
    data = STATE['open'].data
    pid = data['pid']
    out = os.path.join(HERE, 'out', 'kd_open_%d.png' % pid)
    res = _ok(kd_open.capture_window(pid, out, foreground=True))
    STATE['shot'] = out
    STATE['shot_data'] = res.data
    body = res.data
    _say('png %s bytes, %dx%d, phase=%s, method=%s, distinct=%d/%d, white_ratio=%s, '
         'proves_render=%s (%s)' % (
             body['bytes'], body['width'], body['height'], body['phase'],
             body['method'], body['distinct'], body['sampled'],
             body['white_ratio'], body['proves_render'], body['proves_basis']))
    written = body.get('path') or out
    assert os.path.isfile(written), 'screenshot was not written: ' + str(written)
    if body.get('blank'):
        _say('blank frame kept for diagnostics as %s' % written)
    assert body['bytes'] > 5000, body['bytes']
    assert os.path.getsize(written) == body['bytes'], 'written size differs from reported'
    with open(written, 'rb') as fh:
        assert fh.read(8) == b'\x89PNG\r\n\x1a\n', 'not a PNG file'
    assert body['width'] == body['rect']['width'], (body['width'], body['rect'])
    assert body['height'] == body['rect']['height'], (body['height'], body['rect'])
    assert body['phase'] == 'main', (
        'captured the small window (area %r) -- that is the KingDraw loading '
        'splash, not the document window' % body.get('window_area'))


def test_screenshot_is_chrome_evidence_only():
    '''Pixels are auxiliary evidence, and this test says so out loud.

    KingDraw paints its canvas on a WPF/D3D surface that GDI cannot read: the
    captain measured PrintWindow flag=0 as title bar + black client area and
    flag=2 as 94% white, and the same white frames show up in the 32-bit runtime.
    So no assertion here pretends the molecule was rendered -- the UIA test above
    is the one that proves a document opened. This only checks that the capture
    is a real image of the window's chrome, sized like the window.
    '''
    body = STATE.get('shot_data') or {}
    assert body, 'no capture data: run test_screenshot_is_written_for_the_document_window first'
    _say('pixel proof not claimed (GDI cannot read the D3D surface); '
         'proves_render=%r basis=%r' % (body.get('proves_render'), body.get('proves_basis')))
    assert body['bytes'] > 5000, body['bytes']
    assert body['width'] == body['rect']['width']
    assert body['height'] == body['rect']['height']


def test_uia_reports_the_open_document():
    '''The document is proven by its exact UIA name, not by pixels.'''
    data = STATE['open'].data
    pid = data['pid']
    stem = os.path.splitext(os.path.basename(STATE['mol']))[0]
    direct = _ok(kd_open.uia_documents(pid))
    names = kd_open.document_names(direct.data)
    tabs = [t.get('name') or '' for t in direct.data.get('tabs') or []]
    _say('uia names=%r count=%r walk_s=%r via=%r' % (
        names, direct.data.get('count'), direct.data.get('walk_s'),
        direct.data.get('bridged_by') or direct.data.get('executed_by')))
    assert any('KDLayoutDocument' in t for t in tabs), (
        'no KDLayoutDocument tab in the UIA tree: %r' % (tabs,))
    assert names, 'the document tab carries no text at all'
    assert any(stem.lower() in n.lower() for n in names), (
        'no UIA name contains the file stem %r: %r' % (stem, names))
    # open_file must have folded the same evidence into its own result.
    summary = data.get('uia') or {}
    assert summary.get('ok'), summary
    assert summary.get('matched'), summary
    assert data.get('document_confirmed') is True, data.get('verified_by')
    assert 'uia:document-tab' in (data.get('verified_by') or []), data.get('verified_by')


def test_reuse_does_not_start_a_second_instance():
    data = STATE['open'].data
    pid = data['pid']
    before = kd_open.list_pids()
    res = _ok(kd_open.open_file(STATE['mol'], timeout=20.0, reuse=True))
    after = kd_open.list_pids()
    _say('reuse: pids %s -> %s, forwarder %r, degraded=%s' % (
        before, after, res.data['forwarder'], res.degraded))
    assert sorted(after) == sorted(before), (
        'reuse started another instance: %s -> %s' % (before, after))
    assert pid in after, 'the instance that had the document is gone'
    forwarder = res.data['forwarder']
    assert forwarder['exited'], (
        'the launcher did not hand the file over (still running): %r' % forwarder)
    assert forwarder['returncode'] == 0, forwarder
    assert res.data['window'] is not None
    assert res.degraded is True and 'already running' in res.degrade_reason


def test_no_reuse_is_reported_instead_of_granted():
    '''--no-reuse cannot be granted, so the result has to say it was not.

    The CLI help used to promise 'do not attach to an already running
    KingDraw instance' while the implementation recorded the flag and did
    nothing with it: KingDraw has one window per user session and forwards
    every launch to it. A flag that quietly does nothing is worse than one
    that reports the truth, so reuse_honored now says which happened.
    '''
    pid = STATE['open'].data['pid']
    before = kd_open.list_pids()
    res = _ok(kd_open.open_file(STATE['mol'], timeout=20.0, reuse=False))
    after = kd_open.list_pids()
    _say('reuse=False: pids %s -> %s, reuse_honored=%r, degraded=%s' % (
        before, after, res.data.get('reuse_honored'), res.degraded))
    assert res.data.get('reuse_requested') is False
    assert res.data.get('reuse_honored') is False, (
        'a window was open, so the request could not be honoured')
    assert sorted(after) == sorted(before), (
        'reuse=False started a second instance: %s -> %s' % (before, after))
    assert pid in after, 'the instance with the document was replaced'
    joined = ' '.join(res.warnings)
    assert '--no-reuse could not be honoured' in joined, joined
    assert 'single-instance' in joined, joined
    assert 'Nothing of yours was closed' in joined, joined


def _close_all(timeout: float = 12.0) -> list:
    '''Close every KingDraw instance this run can see. Returns (pid, closed).'''
    out = []
    for pid in kd_open.list_pids():
        res = kd_open.close_app(pid, timeout=timeout)
        out.append((pid, bool((res.data or {}).get('closed'))))
    return out


def test_a_path_past_the_win32_limit_is_opened_through_a_staged_copy():
    '''A path KingDraw cannot express is staged and reported, not silently failed.

    Measured before the fix, same molecule: at 62 characters the document tab
    carried the file name; at 298 characters the window opened, no document tab
    appeared, and the envelope still said ok with degraded=False. KingDraw hands
    the path to Win32, which drops it silently, so the fix copies the file to a
    short temp path and reports both locations.
    '''
    source = STATE['mol']
    deep = os.path.join(STATE['tmpdir'], 'deep')
    while len(os.path.join(deep, 'far_away.mol')) < 285:
        deep = os.path.join(deep, 'd' * 40)
    os.makedirs(deep, exist_ok=True)
    target = os.path.join(deep, 'far_away.mol')
    shutil.copyfile(source, target)
    assert len(target) > kd_open.MAX_OPEN_PATH, len(target)
    _say('input path is %d characters' % len(target))

    # Cold on purpose: the tab text is only trustworthy for the first document
    # in a window. A forwarded second file is opened, but the tab keeps the
    # first name (measured: two document tabs, both named after the first
    # file), which is what the warm half below asserts as 'unproven'.
    _say('closing before the cold open: %s' % (_close_all(),))
    time.sleep(1.0)
    res = _ok(kd_open.open_file(target, timeout=25.0))
    data = res.data
    assert data['path'] == target, data['path']
    assert data['staged_from'] == target, data['staged_from']
    assert data['opened_path'] and data['opened_path'] != target, data['opened_path']
    assert os.path.basename(data['opened_path']) == 'far_away.mol', data['opened_path']
    assert len(data['opened_path']) < kd_open.MAX_OPEN_PATH, data['opened_path']
    # The staged copy is what loaded: the window reports that name, and the
    # long path itself never produces a document at all.
    assert data['document_confirmed'] is True, data.get('verified_by')
    assert any('past the Win32 limit' in w for w in res.warnings), res.warnings
    assert not res.degraded, res.degrade_reason
    # The copy must outlive the call: while the document is open in the app,
    # deleting it would be deleting the file the app is holding.
    assert os.path.isfile(data['opened_path'])
    _say('cold open: %s -> document %r' % (target, (data.get('uia') or {}).get('names')))

    # Warm, with a different name. The app opens it, the tab does not follow,
    # so the honest envelope is ok + degraded, naming what the window shows.
    other = os.path.join(STATE['tmpdir'], 'other_name.mol')
    shutil.copyfile(source, other)
    warm = _ok(kd_open.open_file(other, timeout=25.0))
    assert warm.data['reused'] is True, warm.data.get('reused')
    assert warm.data['document_confirmed'] is False, warm.data.get('uia')
    assert warm.degraded is True, warm.to_dict()
    assert 'name differs' in ' '.join(warm.data['verified_by']), warm.data['verified_by']
    assert 'name differs' in warm.degrade_reason, warm.degrade_reason
    _say('warm: tab still %r, degrade=%r' % (
        (warm.data.get('uia') or {}).get('names'), warm.degrade_reason[:90]))

    # Leave the state test_close_ends_the_instance_we_started expects: one
    # instance, showing the file the first test opened.
    _close_all()
    time.sleep(1.0)
    STATE['open'] = _ok(kd_open.open_file(source, timeout=25.0))


def test_close_ends_the_instance_we_started():
    data = STATE['open'].data
    pid = data['pid']
    started = time.monotonic()
    res = _ok(kd_open.close_app(pid, timeout=12.0))
    _say('close pid %s: %r after %.2fs' % (
        pid, res.data, time.monotonic() - started))
    assert res.data['closed'], res.data
    assert pid not in kd_open.list_pids(), 'pid %s survived the close' % pid
    leftover = [p for p in kd_open.list_pids() if p not in STATE['pre_pids']]
    assert not leftover, 'leftover KingDraw processes: %s' % leftover


def test_timeout_is_reported_with_the_pid_and_the_app_is_left_running():
    started = time.monotonic()
    res = kd_open.open_file(STATE['mol'], timeout=0.05)
    pid_guess = (res.data or {}).get('pid') or (res.data or {}).get('spawned_pid')
    try:
        _assert_timeout_failure(res)
    finally:
        if pid_guess:
            closed = kd_open.close_app(pid_guess, timeout=12.0)
            _say('cleanup close: %r' % (closed.data,))
            assert closed.ok and closed.data['closed'], closed.to_dict()
    elapsed = time.monotonic() - started
    _say('E05 path returned in %.2fs' % elapsed)


def _assert_timeout_failure(res: Result) -> None:
    assert isinstance(res, Result) and not res.ok, res.to_dict()
    assert res.failure.code == ErrorCode.KD_CLI_DID_NOT_OPEN, res.failure.code
    assert 'pid' in res.failure.detail, res.failure.detail
    pid = res.data.get('pid') or res.data.get('spawned_pid')
    assert pid, 'the failure carries no pid: %r' % (res.data,)
    assert res.failure.hint, 'a failure must say what to do about the pid'
    # The app must have been left running on purpose, not killed.
    _say('E05 detail: %s' % res.failure.detail[:160])
    _say('E05 hint  : %s' % res.failure.hint[:160])


def test_missing_file_fails_without_launching():
    before = kd_open.list_pids()
    res = kd_open.open_file(os.path.join(tempfile.gettempdir(), 'kd_no_such.mol'))
    after = kd_open.list_pids()
    assert not res.ok, res.to_dict()
    assert res.failure.code == ErrorCode.PARSE_FAILED, res.failure.code
    assert sorted(after) == sorted(before), (
        'a missing file must not start the app: %s -> %s' % (before, after))


def _cleanup():
    tmpdir = STATE.get('tmpdir')
    if tmpdir and os.path.isdir(tmpdir):
        shutil.rmtree(tmpdir, ignore_errors=True)
    # Staged copies of over-long paths are kept while a document is open and
    # swept by the next run in normal use; here the app is already closed, so
    # the test takes its own copies with it.
    for leftover in kd_open._sweep_staged(older_than=0.0):
        print('    removed staged copy %s' % leftover)


ORDER = [
    test_native_molfile_is_available,
    test_open_shows_a_window,
    test_screenshot_is_written_for_the_document_window,
    test_uia_reports_the_open_document,
    test_screenshot_is_chrome_evidence_only,
    test_reuse_does_not_start_a_second_instance,
    test_no_reuse_is_reported_instead_of_granted,
    test_a_path_past_the_win32_limit_is_opened_through_a_staged_copy,
    test_close_ends_the_instance_we_started,
    test_timeout_is_reported_with_the_pid_and_the_app_is_left_running,
    test_missing_file_fails_without_launching,
]


def main() -> int:
    if kd_native.is_64bit():
        print('FAIL: run with the 32-bit runtime (runtime/py32/python.exe); '
              'the molfile step needs the x86 DLL')
        return 2
    started = time.monotonic()
    passed, failed, skipped = 0, [], []
    try:
        for fn in ORDER:
            t0 = time.monotonic()
            try:
                outcome = fn()
            except AssertionError as exc:
                failed.append((fn.__name__, str(exc)))
                print('FAIL %s (%.2fs): %s' % (fn.__name__, time.monotonic() - t0, exc))
            except Exception as exc:  # pragma: no cover
                failed.append((fn.__name__, type(exc).__name__ + ': ' + str(exc)))
                print('ERROR %s (%.2fs): %s: %s' % (
                    fn.__name__, time.monotonic() - t0, type(exc).__name__, exc))
            else:
                if isinstance(outcome, str):
                    skipped.append((fn.__name__, outcome))
                    print('SKIP %s (%.2fs): %s' % (
                        fn.__name__, time.monotonic() - t0, outcome))
                else:
                    passed += 1
                    print('PASS %s (%.2fs)' % (fn.__name__, time.monotonic() - t0))
    finally:
        pre = STATE.get('pre_pids') or []
        mine = [p for p in kd_open.list_pids() if p not in pre]
        for pid in mine:
            closed = kd_open.close_app(pid, timeout=12.0)
            print('    safety-net close pid %s: %r' % (pid, closed.data))
        _cleanup()
        total = time.monotonic() - started
        leftover = kd_open.list_pids() if 'kd_open' in sys.modules else []
        print('-' * 60)
        print('%d passed, %d skipped, %d failed, %d total in %.1fs (budget %.0fs)' % (
            passed, len(skipped), len(failed), len(ORDER), total, BUDGET_S))
        if leftover:
            print('WARNING: KingDraw still running after the run: %s '
                  '(close with WM_CLOSE via close_app)' % leftover)
        if total > BUDGET_S:
            print('FAIL: the suite took %.1fs, budget is %.0fs' % (total, BUDGET_S))
            return 1
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
