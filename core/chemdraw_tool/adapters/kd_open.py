'''KingDraw open channel: hand a structure to the desktop app and prove it opened.

The native adapter can compute (SMILES / molblock / 3D) but a user who wants to
edit the structure needs it on screen. This module is the "show me" half of the
channel, and everything in it was measured against KingDraw.WpfForm.exe on this
machine (test/probe_kd_open.py, test/probe_kd_open_timeline.py):

* Launching 'KingDraw.WpfForm.exe <path>' works for .mol and .king inputs.
* The main window appears about 1.5 s after launch, and its title is the bare
  app name 'KingDraw' -- the file name does **not** show up in it, for either
  input type. So the title assertion accepts the file name *or* the app name,
  and the payload records which one actually matched instead of pretending the
  stronger one was seen.
* When an instance is already running, a second launch does not create a second
  process: it exits with code 0 within ~1 s and the existing instance keeps the
  single window. That forwarding exit code is the only observable hand-over
  signal, so reusing marks the result degraded, and the reuse path waits up to
  2 s for that exit instead of reporting "still running" the moment a window is
  found.
* No same-stem .king sidecar is produced by merely opening a .mol file on this
  build (probed for 12 s). The sidecar check is therefore implemented as extra
  corroboration: it upgrades evidence when it fires, and its absence is reported
  as an observation, never as a failure.
* WM_CLOSE is honoured in about a second, but it is posted, not synchronous: the
  close path waits with a deadline, reports what it saw, and never terminates the
  process behind the user's back.

Document-level proof comes from UI Automation, not from pixels: uia_documents()
returns the 'KingDraw.WpfForm.KDLayoutDocument' tab and the file-name Text it
carries, an exact string that can be asserted. Pixels are auxiliary only --
KingDraw paints on a WPF/D3D surface that never reaches GDI (measured: PrintWindow
with PW_RENDERFULLCONTENT answers ~94% white, without it a black client area), so
capture_window() is kept to show the window has chrome, and its payload says
proves_render=False rather than pretending. The bundled 32-bit runtime has no
pywinauto, comtypes, Pillow, pywin32 or pyautogui (all checked), so UIA is
bridged to a 64-bit interpreter through bin/kd_uia.py, and the capture is done
with ctypes + zlib.

Nothing here loads GRDKitDll.dll, so the module itself runs under either
interpreter; only the molfile helper the tests use needs the 32-bit runtime.
'''

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import zlib
from typing import Any, Optional

from ..models import (
    ERROR_TEXT, ErrorCode, EVIDENCE_INFERRED, EVIDENCE_MEASURED, Failure, Result,
)
from .kd_native import find_home

CHANNEL = 'kingdraw'
APP_NAME = 'KingDraw.WpfForm.exe'
HOME_ENV = 'KINGDRAW_HOME'

WM_CLOSE = 0x0010
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
SW_RESTORE = 9
PW_RENDERFULLCONTENT = 0x00000002

IS_WINDOWS = os.name == 'nt'

_user32 = None  # bound on first use by _bind_windows_apis()
_kernel32 = None
_gdi32 = None
_WNDENUMPROC = None
_APIS_BOUND = False


def _bind_windows_apis() -> None:
    '''Open user32/gdi32/kernel32 and declare their prototypes, once.

    Importing this module must not touch ctypes.WinDLL or
    ctypes.WINFUNCTYPE: a non-Windows checkout has to get a readable
    OSError from the call, not an AttributeError from the import.
    '''
    global _user32, _kernel32, _gdi32, _WNDENUMPROC, _APIS_BOUND
    if _APIS_BOUND:
        return
    if not IS_WINDOWS or not hasattr(ctypes, 'WinDLL'):
        raise OSError('the Windows API is unavailable here (os.name=%r, '
                      'ctypes.WinDLL=%r)' % (os.name, hasattr(ctypes, 'WinDLL')))
    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, ctypes.c_ssize_t)
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, ctypes.c_ssize_t]
    _user32.EnumWindows.restype = wt.BOOL
    _user32.IsWindowVisible.argtypes = [wt.HWND]
    _user32.IsWindowVisible.restype = wt.BOOL
    _user32.IsWindow.argtypes = [wt.HWND]
    _user32.IsWindow.restype = wt.BOOL
    _user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wt.DWORD
    _user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    _user32.PostMessageW.restype = wt.BOOL
    _user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    _user32.GetWindowRect.restype = wt.BOOL
    _user32.GetWindowDC.argtypes = [wt.HWND]
    _user32.GetWindowDC.restype = wt.HDC
    _user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    _user32.ReleaseDC.restype = ctypes.c_int
    _user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wt.BOOL
    _user32.SetForegroundWindow.argtypes = [wt.HWND]
    _user32.SetForegroundWindow.restype = wt.BOOL
    _user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
    _user32.PrintWindow.restype = wt.BOOL
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wt.HWND
    _user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    _user32.AttachThreadInput.restype = wt.BOOL
    _user32.BringWindowToTop.argtypes = [wt.HWND]
    _user32.BringWindowToTop.restype = wt.BOOL
    _kernel32.GetCurrentThreadId.argtypes = []
    _kernel32.GetCurrentThreadId.restype = wt.DWORD
    _gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
    _gdi32.CreateCompatibleDC.restype = wt.HDC
    _gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
    _gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    _gdi32.SelectObject.restype = wt.HGDIOBJ
    _gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                              ctypes.c_int, wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
    _gdi32.BitBlt.restype = wt.BOOL
    _gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
                                 ctypes.c_void_p, wt.UINT]
    _gdi32.GetDIBits.restype = ctypes.c_int
    _gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
    _gdi32.DeleteObject.restype = wt.BOOL
    _gdi32.DeleteDC.argtypes = [wt.HDC]
    _gdi32.DeleteDC.restype = wt.BOOL
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    _kernel32.CloseHandle.argtypes = [wt.HANDLE]
    _kernel32.CloseHandle.restype = wt.BOOL
    _kernel32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _kernel32.Process32FirstW.restype = wt.BOOL
    _kernel32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    _kernel32.Process32NextW.restype = wt.BOOL
    _APIS_BOUND = True


def _wndenumproc():
    _bind_windows_apis()
    return _WNDENUMPROC


class _LazyDll:
    '''A WinDLL handle that binds the API set on first attribute use.'''

    def __init__(self, attr: str) -> None:
        self._attr = attr

    def __getattr__(self, item):
        _bind_windows_apis()
        return getattr(globals()[self._attr], item)


_user32 = _LazyDll('_user32')
_kernel32 = _LazyDll('_kernel32')
_gdi32 = _LazyDll('_gdi32')


class PROCESSENTRY32W(ctypes.Structure):
    '''PROCESSENTRY32W with pointer-sized fields, so it is correct on both bitnesses.'''

    _fields_ = [
        ('dwSize', wt.DWORD),
        ('cntUsage', wt.DWORD),
        ('th32ProcessID', wt.DWORD),
        ('th32DefaultHeapID', ctypes.c_size_t),
        ('th32ModuleID', wt.DWORD),
        ('cntThreads', wt.DWORD),
        ('th32ParentProcessID', wt.DWORD),
        ('pcPriClassBase', ctypes.c_long),
        ('dwFlags', wt.DWORD),
        ('szExeFile', ctypes.c_wchar * 260),
    ]


# The process-enumeration prototypes are declared in _bind_windows_apis() too:
# nothing here may touch ctypes at import time.


def _failure(code: str, stage: str, detail: str = '', message: str = '',
             hint: str = '') -> Failure:
    d_msg, d_hint = ERROR_TEXT.get(code, ('', ''))
    return Failure(code=code, message=message or d_msg, hint=hint or d_hint,
                   detail=detail, channel=CHANNEL, stage=stage)


def platform_failure(stage: str = 'platform', exc: Optional[BaseException] = None) -> Result:
    '''The structured answer for "this channel needs Windows".

    Nothing in this module may raise AttributeError at import on a Linux host;
    the call reports E08 with a readable hint instead (portability review).
    '''
    detail = str(exc) if exc else 'os.name=%r' % (os.name,)
    return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_INFERRED,
                  data={'platform': os.name},
                  failure=_failure(ErrorCode.NOT_INSTALLED, stage, detail=detail,
                                   message='The KingDraw channel needs Windows',
                                   hint='KingDraw.WpfForm.exe is a Windows desktop '
                                        'application; run this on Windows.'))


# -- process and window inspection -----------------------------------------
def list_pids(name: str = APP_NAME) -> list:
    '''PIDs of every process whose image name is *name* (case-insensitive).'''
    try:
        _bind_windows_apis()
    except OSError:
        return []
    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return []
    out = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == name.lower():
                out.append(int(entry.th32ProcessID))
            ok = _kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _kernel32.CloseHandle(snap)
    return out


def iter_windows(pid: Optional[int] = None, visible_only: bool = True) -> list:
    """Every top-level window, optionally only those owned by *pid*.

    Returns an empty list when the Windows API is unavailable (see
    platform_failure(): the channel reports E08 instead of a traceback).
    Returns top-level windows as dicts: hwnd, pid, title, class, visible.
    """
    try:
        _bind_windows_apis()
    except OSError:
        return []
    rows: list = []

    def _cb(hwnd, _lparam):
        if visible_only and not _user32.IsWindowVisible(hwnd):
            return True
        owner = wt.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        hwnd_pid = int(owner.value)
        if pid is not None and hwnd_pid != pid:
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        title_buf = ctypes.create_unicode_buffer(length + 2)
        _user32.GetWindowTextW(hwnd, title_buf, length + 1)
        class_buf = ctypes.create_unicode_buffer(256)
        _user32.GetClassNameW(hwnd, class_buf, 255)
        rows.append({
            'hwnd': int(hwnd),
            'hwnd_hex': hex(hwnd),
            'pid': hwnd_pid,
            'title': title_buf.value,
            'class': class_buf.value,
            'visible': bool(_user32.IsWindowVisible(hwnd)),
        })
        return True

    callback = _wndenumproc()(_cb)
    _user32.EnumWindows(callback, 0)
    return rows


def main_window(pid: int) -> Optional[dict]:
    '''The visible, titled top-level window of a pid, biggest first.

    Biggest, not "title contains KingDraw", because the splash screen carries the
    same app title: a test that picked the first titled window screenshotted the
    "loading components" splash (706x452) instead of the document window
    (1451x866) and looked like proof while showing nothing of the document.
    '''
    titled = [w for w in iter_windows(pid) if w['title'].strip()]
    if not titled:
        return None
    for w in titled:
        rect = _window_rect(w['hwnd'], attempts=1)
        w['area'] = (rect['width'] * rect['height']) if rect else 0
        w['rect'] = rect
    titled.sort(key=lambda w: w['area'], reverse=True)
    return titled[0]


def app_home_changes(home: str, since: float, limit: int = 8) -> list:
    '''Files directly in the app home touched at or after *since* (evidence only).'''
    found = []
    try:
        with os.scandir(home) as it:
            for entry in it:
                try:
                    if not entry.is_file():
                        continue
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if mtime >= since:
                    found.append({'name': entry.name,
                                  'mtime': round(mtime, 3),
                                  'bytes': entry.stat().st_size})
    except OSError:
        return []
    found.sort(key=lambda r: r['mtime'], reverse=True)
    return found[:limit]


def _terminate_windowless(pid: int, wait: float = 2.0) -> bool:
    '''Kill a KingDraw process that has no window at all.

    close_app only posts WM_CLOSE, which needs a window to answer, so the
    windowless leftover that turns into a 123 s timeout survives it. Such a
    process cannot be showing anything to anyone, so terminating it cannot
    destroy visible work -- and it does hold the single-instance lock that
    sends the next launch to an invisible window.
    '''
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x0001, False, int(pid))  # PROCESS_TERMINATE
    if not handle:
        return False
    try:
        if not kernel32.TerminateProcess(handle, 1):
            return False
    finally:
        kernel32.CloseHandle(handle)
    deadline = time.monotonic() + max(0.0, float(wait))
    while time.monotonic() < deadline:
        if pid not in list_pids():
            return True
        time.sleep(0.1)
    return pid not in list_pids()


def close_app(pid: int, timeout: float = 10.0, repost_every: float = 1.5) -> Result:
    '''Ask a KingDraw instance to close with WM_CLOSE; wait, bounded, for the pid to go.

    The message is re-posted every *repost_every* seconds: a WM_CLOSE delivered
    while the app is still loading a document is swallowed (measured -- the same
    pid refused to close 10 s after a fresh open, then closed in 1 s when the
    message was posted again later). A close the app keeps ignoring is reported
    with its pid so a human can decide; TerminateProcess is never called.
    '''
    try:
        _bind_windows_apis()
    except OSError as exc:
        return platform_failure('close', exc)
    started = time.monotonic()
    if pid not in list_pids():
        return Result(ok=True, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      data={'pid': pid, 'closed': True, 'already_gone': True,
                            'waited_s': 0.0})
    deadline = started + max(0.5, float(timeout))
    posts = 0
    last_post = 0.0
    window_seen = False
    while time.monotonic() < deadline:
        if pid not in list_pids():
            return Result(
                ok=True, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                data={'pid': pid, 'closed': True, 'posts': posts,
                      'waited_s': round(time.monotonic() - started, 2)},
            )
        windows = iter_windows(pid)
        window_seen = window_seen or bool(windows)
        if windows and (time.monotonic() - last_post) >= repost_every:
            sent = 0
            for window in windows:
                if _user32.PostMessageW(window['hwnd'], WM_CLOSE, 0, 0):
                    sent += 1
            posts += 1 if sent else 0
            last_post = time.monotonic()
        time.sleep(0.2)
    detail = 'pid %d still alive %.1fs after %d WM_CLOSE post(s); window seen: %s' % (
        pid, time.monotonic() - started, posts, window_seen)
    return Result(
        ok=False, channel=CHANNEL, evidence=EVIDENCE_INFERRED,
        data={'pid': pid, 'closed': False, 'posts': posts,
              'window_seen': window_seen,
              'waited_s': round(time.monotonic() - started, 2)},
        failure=_failure(ErrorCode.KD_CLI_DID_NOT_OPEN, 'close', detail=detail,
                         message='KingDraw did not close when asked',
                         hint='It probably shows a save-changes prompt; answer it '
                              'by hand. The process was left running on purpose '
                              '(pid %d).' % pid),
    )


# -- open ------------------------------------------------------------------
def _title_match(title: str, stem: str) -> Optional[str]:
    if not title:
        return None
    low = title.lower()
    if stem and stem.lower() in low:
        return 'filename'
    if 'kingdraw' in low:
        return 'app'
    return None


MAX_OPEN_PATH = 250
STAGED_PREFIX = 'kd_open_stage_'


def _stage_long_input(path: str):
    '''Copy an over-long input somewhere KingDraw can reach. Returns (path, dir).

    KingDraw hands the path straight to Win32, which stops at 260 characters
    without an error that reaches us: measured with a 298-character .mol the
    window opened and no document tab ever appeared, while the same file at 62
    characters reported uia:document-tab. This is the trick the export path
    already uses for SaveAs, which also ignores paths it cannot express.
    '''
    root = tempfile.mkdtemp(prefix=STAGED_PREFIX)
    target = os.path.join(root, os.path.basename(path))
    shutil.copyfile(path, target)
    return target, root


def _sweep_staged(older_than: float = 300.0) -> list:
    '''Remove staged copies left by earlier runs.

    A staged copy must outlive its call: while KingDraw holds the document, a
    Save in the app writes back to it. Past the budget below, whatever is still
    there belongs to a run that is over.
    '''
    removed = []
    now = time.time()
    try:
        names = os.listdir(tempfile.gettempdir())
    except OSError:
        return removed
    for name in names:
        if not name.startswith(STAGED_PREFIX):
            continue
        path = os.path.join(tempfile.gettempdir(), name)
        try:
            if not os.path.isdir(path) or now - os.path.getmtime(path) < older_than:
                continue
        except OSError:
            continue
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.isdir(path):
            removed.append(path)
    return removed


def _open_file_locked(path: str, timeout: float = 20.0, reuse: bool = True,
                      home: Optional[str] = None, close_exe_wait: bool = True,
                      uia: bool = True, uia_timeout: float = 15.0) -> Result:
    '''Open *path* in KingDraw and verify it, with every wait bounded.

    Reuses an already running instance (the second launch forwards the file and
    exits 0); otherwise starts KingDraw.WpfForm.exe with the path.

    Verification has two tiers. The window tier is a title assertion on the pid's
    biggest visible window (never "the process is alive"). The document tier is
    UIAutomation: the KDLayoutDocument tab carries the file name as an exact
    string, which is what actually proves the document opened -- a screenshot
    cannot, because KingDraw paints on a WPF/D3D surface that GDI cannot read. A
    same-stem .king sidecar and files touched in the app home are recorded as
    extra corroboration.
    '''
    started = time.monotonic()
    started_wall = time.time()
    stage = 'locate'
    if not path:
        return Result(ok=False, channel=CHANNEL, failure=_failure(
            ErrorCode.PARSE_FAILED, stage, detail='empty path'),
            evidence=EVIDENCE_MEASURED)
    full = os.path.abspath(path)
    requested = full
    staged_dir = None
    if os.path.isfile(full) and len(full) > MAX_OPEN_PATH:
        _sweep_staged()
        try:
            full, staged_dir = _stage_long_input(full)
        except OSError as exc:
            return Result(
                ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                failure=_failure(
                    ErrorCode.PARSE_FAILED, stage,
                    detail='%s: %s' % (type(exc).__name__, exc),
                    message='Could not stage the over-long path',
                    hint='Move the file under a shorter directory: KingDraw '
                         'cannot open paths past %d characters.' % MAX_OPEN_PATH))
    if not os.path.isfile(full):
        return Result(
            ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
            failure=_failure(ErrorCode.PARSE_FAILED, stage,
                             detail='not a file: ' + full,
                             message='Input structure file does not exist',
                             hint='Write the molfile first, e.g. '
                                  'python bin/cli.py kd mol "c1ccccc1O" --out x.mol'),
        )
    home_dir = find_home(home)
    if not home_dir:
        return Result(
            ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
            data={'home': None},
            failure=_failure(ErrorCode.KD_NOT_FOUND, stage,
                             detail='no GRDKitDll.dll under the default homes'),
        )
    exe = os.path.join(home_dir, APP_NAME)
    if not os.path.isfile(exe):
        return Result(
            ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
            data={'home': home_dir, 'app': exe},
            failure=_failure(ErrorCode.NOT_INSTALLED, 'app',
                             detail='missing ' + exe),
        )

    stage = 'launch'
    stem = os.path.splitext(os.path.basename(full))[0]
    sidecar = os.path.splitext(full)[0] + '.king'
    sidecar_before = os.path.getmtime(sidecar) if os.path.isfile(sidecar) else None
    # A process with no window at all can never be the one that shows the
    # file, but it owns the single-instance lock, so the launch we are about
    # to make hands the file to a window nobody can see. Measured: one such
    # leftover burned the whole deadline and then failed with E05 while the
    # file was perfectly good, and only a by-hand taskkill cleared it. A
    # process with no window has nothing to lose, so clear it here -- before
    # the launch, not as a retry after a full timeout.
    stale: list = []
    for pid in list_pids():
        if iter_windows(pid, visible_only=False):
            continue
        closed = close_app(pid, 8.0)
        posted = bool((closed.data or {}).get('closed'))
        killed = False if posted else _terminate_windowless(pid)
        stale.append({'pid': pid, 'closed': posted, 'terminated': killed})
    existing = list_pids()
    proc = None
    spawn_error = ''
    try:
        proc = subprocess.Popen([exe, full], cwd=home_dir, close_fds=True)
    except OSError as exc:
        spawn_error = '%s: %s' % (type(exc).__name__, exc)
    if proc is None:
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      data={'home': home_dir, 'app': exe, 'path': full},
                      failure=_failure(ErrorCode.UNKNOWN, stage, detail=spawn_error,
                                       message='Could not start KingDraw'))

    stage = 'verify'
    deadline = started + max(0.0, float(timeout))
    window = None
    matched = None
    forwarder = None
    observed: list = []
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            forwarder = {'pid': proc.pid, 'exited': True,
                         'returncode': proc.returncode}
        current = list_pids()
        for pid in current:
            candidate = main_window(pid)  # biggest window first (not the splash)
            if not candidate:
                continue
            hit = _title_match(candidate['title'], stem)
            entry = {'pid': pid, 'title': candidate['title'], 'hwnd': candidate['hwnd'],
                     'area': candidate.get('area')}
            if entry not in observed:
                observed.append(entry)
            if hit:
                window, matched = candidate, hit
                break
        if window:
            # Give the document a moment to load before the sidecar check.
            sidecar_ready = _wait_sidecar(sidecar, sidecar_before,
                                          min(2.0, max(0.0, deadline - time.monotonic())))
            # Reuse case only: the launcher exits 0 once it has handed the file
            # to the instance that already existed. Wait briefly for that exit,
            # otherwise the hand-over signal is missed and looks like a hang.
            if existing and proc.poll() is None:
                settle = min(deadline, time.monotonic() + 2.0)
                while proc.poll() is None and time.monotonic() < settle:
                    time.sleep(0.05)
            break
        time.sleep(0.2)
    else:
        sidecar_ready = None

    # Document-level proof, when asked for and when a window was found. This is a
    # separate, bounded step: UIA costs ~1.4 s through the 64-bit bridge, and its
    # failure must never turn a verified window into a failure.
    uia_summary: Optional[dict] = None
    if window and uia:
        probe = uia_documents(window['pid'], timeout=uia_timeout)
        probes = 1
        if probe.ok:
            names = document_names(probe.data)
            # One look is not enough when the window already showed another
            # document: measured while opening a second file into a window
            # that carried a tab already, the first probe reported the old
            # tab and the verdict became 'no proof' for a file that had
            # loaded a moment later. Ask again while a document is present
            # but the requested one is not, inside a small budget.
            want = stem.lower()
            deadline = time.monotonic() + min(uia_timeout, 4.0)
            while (probes < 3 and probe.data.get('documents')
                   and not [n for n in names if want in n.lower()]
                   and time.monotonic() < deadline):
                time.sleep(0.5)
                again = uia_documents(window['pid'], timeout=uia_timeout)
                probes += 1
                if not again.ok:
                    break
                probe = again
                names = document_names(probe.data)
            uia_summary = {
                'ok': True,
                'probes': probes,
                'documents': probe.data.get('documents'),
                'names': names,
                'tabs': [t.get('name') for t in probe.data.get('tabs') or []],
                'matched': [n for n in names if stem.lower() in n.lower()],
                'count': probe.data.get('count'),
                'walk_s': probe.data.get('walk_s'),
                'source': probe.data.get('source'),
                'bridged_by': probe.data.get('bridged_by'),
                'elapsed_ms': probe.elapsed_ms,
            }
        else:
            uia_summary = {'ok': False, 'code': probe.failure.code,
                           'detail': probe.failure.detail[:240],
                           'hint': probe.failure.hint}

    # The launcher may have exited during the settle wait, not at the top of a
    # poll iteration, so its final state is read once more here instead of being
    # inferred from "we never saw it exit".
    final_rc = proc.poll()
    forwarder = {'pid': proc.pid, 'exited': final_rc is not None,
                 'returncode': final_rc}

    data: dict = {
        'path': requested,
        # When the requested path was too long for KingDraw, the app was
        # handed a short copy instead. Both locations travel so a caller can
        # tell which file the app is actually holding.
        'staged_from': requested if staged_dir else None,
        'opened_path': full if staged_dir else None,
        'home': home_dir,
        'app': exe,
        'spawned_pid': proc.pid,
        'pids_before': existing,
        'pids_after': list_pids(),
        'forwarder': forwarder,
        'reused': bool(existing) or bool(forwarder.get('exited')),
        'reuse_requested': bool(reuse),
        # reuse=False cannot be honoured: KingDraw has one window per user
        # session and forwards every launch to it. The flag used to be recorded
        # and then ignored, which made the CLI help a promise the code did not
        # keep; now the envelope says whether it was honoured.
        'reuse_honored': bool(reuse) or not bool(existing),
        'window': window,
        'window_area': (window or {}).get('area'),
        'title_matched': matched,
        'observed_windows': observed,
        'sidecar_path': sidecar,
        'sidecar_before_mtime': sidecar_before,
        'sidecar_touched': sidecar_ready,
        'home_changes': app_home_changes(home_dir, started_wall),
        'uia': uia_summary,
        'waited_s': round(time.monotonic() - started, 2),
        'close_with': 'close_app(pid) -> WM_CLOSE',
        'stale_instances_cleared': stale,
    }

    if window:
        verified: list = []
        if matched == 'app':
            verified.append('window-title:app-name')
        if matched == 'filename':
            verified.append('window-title:file-name')
        if sidecar_ready:
            verified.append('sidecar:.king touched')
        if data['home_changes']:
            verified.append('app-home:files touched')
        document_confirmed = False
        if uia_summary and uia_summary.get('ok'):
            if uia_summary.get('matched'):
                verified.append('uia:document-tab')
                document_confirmed = True
            elif uia_summary.get('documents'):
                verified.append('uia:document-tab (name differs from the request)')
            else:
                verified.append('uia:no-document-tab')
        data['document_confirmed'] = document_confirmed
        data['verified_by'] = verified
        data['pid'] = window['pid']
        # A window with a title really was measured, so the envelope is A. Which
        # part of the title matched says how strong the *document* claim is, and
        # that travels in title_matched / verified_by instead of in the grade.
        res = Result(ok=True, data=data, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                     elapsed_ms=int((time.monotonic() - started) * 1000))
        if matched == 'app' and not document_confirmed:
            res.warnings.append(
                'window title is the bare app name; this build does not put the '
                'file name in the title for .mol or .king input (measured)')
        if uia_summary is not None and not uia_summary.get('ok'):
            res.warnings.append(
                'UIA verification unavailable (%s): the window was verified, the '
                'document was not' % uia_summary.get('code'))
        # Two independent reasons can weaken the claim, and both are named
        # rather than the last one overwriting the other. No document tab is
        # not cosmetic: measured on a 298-character path, the window opened
        # and the document did not, and this used to report a clean success.
        reasons = []
        if not document_confirmed:
            seen = list((uia_summary or {}).get('names') or [])
            if seen:
                # Two different things can happen here and they read very
                # differently: no tab at all, or a tab that names another
                # document. Measured while forwarding a second file into a
                # running window, the app opened it and the tab kept the
                # first name, so the second case must not be reported as
                # the first.
                reasons.append('the window reports document %r, not %r '
                               '(uia:document-tab, name differs), so the '
                               'document you asked for is not confirmed; '
                               'close that window (chemdraw-tool kd close) '
                               'and open again'
                               % (seen[0], os.path.basename(full)))
            else:
                reasons.append('no document tab could be read '
                               '(uia:no-document-tab), so the file being open '
                               'in the window is not proven')
        if data['reused'] and existing:
            reasons.append('opened in the already running instance (pid %s); '
                           'the only observable hand-over signal is the '
                           'launcher exit code' % (window['pid'],))
        res.degraded = bool(reasons)
        res.degrade_reason = '; '.join(reasons)
        if sidecar_ready is False and not sidecar_before:
            res.warnings.append(
                'no same-stem .king sidecar was created while opening; that is '
                'what this build does for .mol input, not a failure')
        if stale:
            res.warnings.append(
                'a KingDraw process with no window at all was holding the '
                'single-instance lock (pid %s); it was closed before this '
                'launch, otherwise the file would have gone to a window '
                'nobody can see' % ', '.join(str(item['pid']) for item in stale))
        if staged_dir:
            res.warnings.append(
                'the path is %d characters, past the Win32 limit KingDraw can '
                'open (measured: the window appears and no document ever loads), '
                'so the file was copied to %s and opened from there; the copy '
                'stays while the document is open' % (len(requested), full))
        if not reuse and existing:
            res.warnings.append(
                '--no-reuse could not be honoured: KingDraw is a single-instance '
                'application, so the file went to the window that was already '
                'open (pid %s). Nothing of yours was closed and no document of '
                'yours was replaced.' % window['pid'])
        return res

    # no window matched within the deadline
    still_running = list_pids()
    lane = 'pid of the launcher: %d (alive=%s, rc=%r)' % (
        proc.pid, not forwarder.get('exited'), forwarder.get('returncode'))
    hint = _no_window_hint(existing, still_running, timeout)
    if stale:
        hint += ('; %d windowless process(es) were closed before this launch, '
                 'so a leftover is not the reason this time' % len(stale))
    return Result(
        ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED, data=data,
        elapsed_ms=int((time.monotonic() - started) * 1000),
        failure=_failure(
            ErrorCode.KD_CLI_DID_NOT_OPEN, 'verify',
            detail='%s; expected a visible window whose title holds %r or the app '
                   'name within %.1fs; observed: %r; pids now: %r'
                   % (lane, stem, float(timeout), observed, still_running),
            message='KingDraw was launched with the file but never confirmed it opened',
            hint=hint,
        ),
    )


def open_file(path: str, timeout: float = 20.0, reuse: bool = True,
              home: Optional[str] = None, close_exe_wait: bool = True,
              uia: bool = True, uia_timeout: float = 15.0) -> Result:
    '''Open and verify, holding the app lock for the whole exchange.

    Two calls at once used to hand their files to the same single-instance
    window and then both wait for a document that could not appear (measured:
    two parallel kd export runs failed together after 122 s each, having
    produced nothing). The lock makes that a queue instead.
    '''
    from .. import applock
    try:
        held = applock.hold(applock.KINGDRAW,
                            timeout=min(timeout, applock.DEFAULT_TIMEOUT))
    except applock.AppBusy as busy:
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.KD_CLI_DID_NOT_OPEN, 'lock',
                                       detail=busy.hint(),
                                       message='KingDraw is busy with another call',
                                       hint=busy.hint()))
    try:
        return _open_file_locked(path, timeout=timeout, reuse=reuse, home=home,
                                 close_exe_wait=close_exe_wait, uia=uia,
                                 uia_timeout=uia_timeout)
    finally:
        held.release()


def _no_window_hint(existing, still_running, timeout) -> str:
    '''What to do when the deadline passed with no window to attribute.

    Three states used to share one sentence, and the sentence only made sense
    for the first of them:

    - we attached to an instance that was already running and it never showed
      a window -- name the pid;
    - nothing was running when we started, but a process exists now that we
      cannot attribute. That is what a leftover instance from an interrupted
      run looks like, and it also holds the single-instance lock, so the next
      launch hands off to a window nobody can see. Measured: one such process
      turned a kd export into two full timeouts (123 s each) and then made
      four test suites fail with three different symptoms. 'Leave it running
      or close it by hand' told the reader none of that;
    - nothing is running at all -- then the advice is the timeout knob, which
      exists on kd open / kd save / kd export and is where a slow first start
      needs loosening.
    '''
    if existing:
        return ('KingDraw was already running (pid %s) but no window could be '
                'attributed to it; check that instance by hand, or close it and '
                'retry' % ', '.join(str(pid) for pid in existing))
    if still_running:
        return ('a KingDraw process appeared that this tool did not attach to '
                'and cannot attribute (pid %s) -- typically a leftover from an '
                'interrupted run, which also holds the single-instance lock; '
                'clear it with "taskkill /F /IM KingDraw.WpfForm.exe" and '
                'retry' % ', '.join(str(pid) for pid in still_running))
    return ('no KingDraw process is running now; retry with a longer --timeout '
            '(this run waited %gs) or start the app by hand once to check the '
            'install' % float(timeout))


def _wait_sidecar(path: str, before: Optional[float], budget: float) -> Optional[bool]:
    '''True when the sidecar appeared or was refreshed; None when it cannot tell.'''
    deadline = time.monotonic() + max(0.0, budget)
    while True:
        try:
            if os.path.isfile(path):
                mtime = os.path.getmtime(path)
                if before is None or mtime > before:
                    return True
                return False
        except OSError:
            return None
        if time.monotonic() >= deadline:
            return None if before is None else False
        time.sleep(0.15)


# -- screenshot verification ---------------------------------------------
class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wt.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
        ('biPlanes', wt.WORD), ('biBitCount', wt.WORD), ('biCompression', wt.DWORD),
        ('biSizeImage', wt.DWORD), ('biXPelsPerMeter', ctypes.c_long),
        ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wt.DWORD),
        ('biClrImportant', wt.DWORD),
    ]


class _BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', _BITMAPINFOHEADER), ('bmiColors', wt.DWORD * 3)]


def _png_chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack('>I', len(data)) + tag + data
            + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))


def png_from_bgra(width: int, height: int, bgra: bytes) -> bytes:
    '''Encode 32-bit BGRA pixels as PNG using only zlib, so no Pillow is needed.

    The bundled 32-bit runtime ships without Pillow/pywin32 (checked), and the
    channel must not grow a dependency for its own verification.
    '''
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        row = bgra[y * stride:(y + 1) * stride]
        rgb = bytearray(width * 3)
        rgb[0::3] = row[2::4]
        rgb[1::3] = row[1::4]
        rgb[2::3] = row[0::4]
        raw.append(0)
        raw.extend(rgb)
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + _png_chunk(b'IHDR', ihdr)
            + _png_chunk(b'IDAT', zlib.compress(bytes(raw), 6))
            + _png_chunk(b'IEND', b''))


def _window_rect(hwnd: int, attempts: int = 5) -> Optional[dict]:
    '''GetWindowRect with a short retry: it can answer 0 while the window settles.'''
    for _ in range(max(1, attempts)):
        rect = wt.RECT()
        if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            width, height = rect.right - rect.left, rect.bottom - rect.top
            if width > 0 and height > 0:
                return {'left': rect.left, 'top': rect.top, 'right': rect.right,
                        'bottom': rect.bottom, 'width': width, 'height': height}
        time.sleep(0.15)
    return None


def color_variety(bgra: bytes, step: int = 13) -> dict:
    '''Cheap render sanity: how many distinct colours are sampled, and how white.'''
    colors = set()
    white = 0
    total = 0
    for i in range(0, len(bgra) - 4, 4 * step):
        px = bgra[i:i + 3]
        colors.add(bytes(px))
        total += 1
        if px[0] > 240 and px[1] > 240 and px[2] > 240:
            white += 1
    return {'sampled': total, 'distinct': len(colors),
            'white_ratio': round(white / max(1, total), 3)}


def raise_window(hwnd: int, settle: float = 0.4) -> dict:
    '''Bring a window to the front, the way a user click would.

    SetForegroundWindow alone is refused unless the caller already owns the
    foreground, so the input queue is briefly attached to the foreground thread
    first (the standard workaround). The returned dict says whether Windows
    really made it the foreground window, which is what decides whether a screen
    copy of that region can be trusted to belong to this window.
    '''
    try:
        _bind_windows_apis()
    except OSError as exc:
        return {'ok': False, 'raised': False, 'is_foreground': False,
                'error': str(exc), 'platform': os.name}
    front = _user32.GetForegroundWindow()
    front_thread = wt.DWORD()
    if front:
        _user32.GetWindowThreadProcessId(front, ctypes.byref(front_thread))
    this_thread = _kernel32.GetCurrentThreadId()
    attached = False
    set_ok = False
    try:
        if front_thread.value and front_thread.value != this_thread:
            attached = bool(_user32.AttachThreadInput(
                this_thread, front_thread.value, True))
        _user32.ShowWindow(hwnd, SW_RESTORE)
        set_ok = bool(_user32.SetForegroundWindow(hwnd))
        _user32.BringWindowToTop(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(this_thread, front_thread.value, False)
    time.sleep(max(0.0, settle))
    now = _user32.GetForegroundWindow()
    return {'attached': attached, 'set_foreground': set_ok,
            'is_foreground': bool(now) and int(now) == int(hwnd),
            'foreground_hwnd': hex(now) if now else None, 'hwnd': hex(hwnd)}


MAIN_WINDOW_MIN_AREA = 500000  # ~800x625: the document window, not the splash


def wait_for_main_window(pid: int, timeout: float = 8.0,
                         min_area: int = MAIN_WINDOW_MIN_AREA) -> Optional[dict]:
    '''Wait, bounded, for the document window rather than the loading splash.'''
    deadline = time.monotonic() + max(0.0, timeout)
    best = None
    while True:
        window = main_window(pid)
        if window and window.get('area', 0) >= min_area:
            return window
        if window:
            best = window
        if time.monotonic() >= deadline:
            return best
        time.sleep(0.2)


def capture_window(pid: int, out_path: Optional[str] = None,
                   foreground: bool = True, settle: float = 0.4,
                   attempts: int = 20, retry_pause: float = 0.25,
                   wait_main: float = 8.0) -> Result:
    '''Grab the pid's window pixels and (optionally) write them as a PNG.

    This is the "eyes on it" half of the verification, and it is deliberately
    modest about what it proves. PrintWindow renders the window's GDI/WPF chrome,
    so the PNG shows the real KingDraw UI -- toolbar, left palette and the
    document tab carrying the input file name (human-verifiable in
    test/out/kd_open_*.png). The structure canvas itself is a DirectX surface
    that PrintWindow does not include: it comes out white, so a blank canvas in
    the image is normal and is NOT evidence that the molecule failed to load.

    What the numbers are good for: a window whose UI never painted (or a bogus
    handle) yields a handful of colours and a few kilobytes, while a real frame
    is tens of kilobytes with hundreds of colours. That separation is what the
    test asserts; the drawing of the molecule is left to a later UIAutomation
    step, not claimed here.
    '''
    started = time.monotonic()
    window = wait_for_main_window(pid, wait_main) if wait_main else main_window(pid)
    if not window:
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.KD_CLI_DID_NOT_OPEN, 'capture',
                                       detail='pid %d has no visible window' % pid,
                                       message='Nothing to capture: no window for that pid'))
    hwnd = window['hwnd']
    rect = _window_rect(hwnd)
    if not rect:
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.UNKNOWN, 'capture',
                                       detail='GetWindowRect returned 0 for hwnd %s'
                                              % window['hwnd_hex'],
                                       message='Could not measure the window'))
    width, height = rect['width'], rect['height']

    # PrintWindow asks the window to draw itself, so whatever sits in front of it
    # on the desktop cannot leak into the image. That matters: an earlier version
    # of this function used a plain BitBlt from a window DC, which copies *screen*
    # pixels, and it happily captured a browser window that happened to be in
    # front -- identical byte size on every run, and a test that passed while
    # proving nothing.
    # PrintWindow asks the window to draw itself, so windows sitting on top of it
    # cannot leak into the image. Measured caveat: for this WPF app it also
    # returns white frames (ok=True, 866 lines, a single colour) most of the time,
    # so it cannot be the only method. When it does paint (it did in earlier
    # runs: 42 KB, 358 colours) the frame is trustworthy without touching
    # window order.
    history = []
    bgra, info = b'', {'method': 'printwindow', 'ok': False, 'lines': 0, 'distinct': 0}
    for attempt in range(max(1, attempts)):
        bgra, info = _grab(hwnd, width, height, 'printwindow')
        history.append({'try': attempt + 1, 'ok': info.get('ok'),
                        'lines': info.get('lines'), 'distinct': info.get('distinct')})
        if not _looks_blank(bgra):
            break
        if attempt + 1 < attempts:
            time.sleep(retry_pause)
    passed = {'printwindow': dict(info, tries=len(history), history=history[-4:])}
    method = 'printwindow'

    raised: Optional[dict] = None
    if _looks_blank(bgra):
        # Fall back to a screen-region copy -- but only after genuinely raising
        # the window, because otherwise the pixels belong to whatever happens to
        # be in front (that is how an earlier build "proved" a rendering by
        # capturing a browser window). If Windows refuses to raise it, the copy
        # is kept for diagnostics and proves_render stays False.
        if foreground:
            raised = raise_window(hwnd, settle)
        bgra2, info2 = _grab(hwnd, width, height, 'bitblt')
        info2['raised'] = raised
        passed['bitblt'] = info2
        if not _looks_blank(bgra2):
            bgra, method = bgra2, 'bitblt'

    if not bgra:
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.UNKNOWN, 'capture',
                                       detail='no pixels could be read; attempts: %r'
                                              % (passed,),
                                       message='Could not read the window pixels'))

    png = png_from_bgra(width, height, bgra)
    variety = color_variety(bgra)
    blank = _looks_blank(bgra)
    foreground_ok = bool((raised or {}).get('is_foreground'))
    proves = (not blank) and (
        method == 'printwindow' or (method == 'bitblt' and foreground_ok))
    written = None
    if out_path:
        target = os.path.abspath(out_path)
        if blank or not proves:
            # Say it in the file name. A blank frame, or a screen copy taken
            # without a confirmed foreground window, must not be mistaken for
            # evidence of a rendered window when someone opens test/out later.
            stem, ext = os.path.splitext(target)
            target = stem + ('_blank' if blank else '_unproven') + (ext or '.png')
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as fh:
            fh.write(png)
        written = target
    res = Result(
        ok=True, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
        data={'path': written, 'bytes': len(png), 'width': width, 'height': height,
              'rect': rect, 'title': window['title'], 'hwnd': window['hwnd'],
              'window_area': width * height,
              'phase': 'main' if width * height >= MAIN_WINDOW_MIN_AREA else 'small',
              'method': method, 'attempts': passed,
              'blank': blank, 'proves_render': proves,
              'proves_basis': ('printwindow' if method == 'printwindow'
                               else ('bitblt+foreground' if foreground_ok
                                     else 'bitblt without foreground: not proof')),
              'settle_s': round(settle, 2), **variety},
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
    if blank:
        res.warnings.append('window pixels look blank (single colour): the window '
                            'exists but was not shown to have rendered anything')
        res.evidence = EVIDENCE_INFERRED
    if method != 'printwindow':
        if foreground_ok:
            res.warnings.append('PrintWindow returned white frames for this WPF '
                                'window, so the image is a screen copy taken while '
                                'KingDraw was verified to be the foreground window')
        else:
            res.warnings.append('fell back to a screen-region copy but Windows did '
                                'not make KingDraw the foreground window, so the '
                                'image may show other windows and is not proof')
            res.evidence = EVIDENCE_INFERRED
    return res


def _grab(hwnd: int, width: int, height: int, method: str):
    '''Draw the window into a memory bitmap and return (bgra bytes, info).'''
    hdc = _user32.GetWindowDC(hwnd)
    memdc = _gdi32.CreateCompatibleDC(hdc)
    bitmap = _gdi32.CreateCompatibleBitmap(hdc, width, height)
    old = _gdi32.SelectObject(memdc, bitmap)
    info: dict = {'method': method}
    try:
        if method == 'printwindow':
            info['ok'] = bool(_user32.PrintWindow(hwnd, memdc, PW_RENDERFULLCONTENT))
        else:
            info['ok'] = bool(_gdi32.BitBlt(memdc, 0, 0, width, height, hdc, 0, 0,
                                            SRCCOPY | CAPTUREBLT))
        header = _BITMAPINFO()
        header.bmiHeader.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.bmiHeader.biWidth = width
        header.bmiHeader.biHeight = -height
        header.bmiHeader.biPlanes = 1
        header.bmiHeader.biBitCount = 32
        header.bmiHeader.biCompression = 0
        buffer = ctypes.create_string_buffer(width * height * 4)
        info['lines'] = _gdi32.GetDIBits(memdc, bitmap, 0, height, buffer,
                                         ctypes.byref(header), DIB_RGB_COLORS)
        if info['lines'] != height:
            info['distinct'] = 0
            return b'', info
        info['distinct'] = color_variety(buffer.raw)['distinct']
        return buffer.raw, info
    finally:
        _gdi32.SelectObject(memdc, old)
        _gdi32.DeleteObject(bitmap)
        _gdi32.DeleteDC(memdc)
        _user32.ReleaseDC(hwnd, hdc)


def _looks_blank(bgra: bytes, step: int = 13) -> bool:
    '''True when the pixels carry no UI at all: empty, single colour, or all black.'''
    if not bgra:
        return True
    colors = set()
    brightest = 0
    for i in range(0, len(bgra) - 4, 4 * step):
        px = bgra[i:i + 3]
        colors.add(bytes(px))
        brightest = max(brightest, px[0], px[1], px[2])
        if len(colors) > 4 and brightest > 16:
            return False
    return len(colors) <= 2 or brightest <= 16


# -- UIAutomation: the strong "a document is open" signal -------------------
PYTHON64_ENV = 'CHEMTOOL_PYTHON64'
_UIA_CACHE: dict = {'python': None}


def _uia_script() -> str:
    '''bin/kd_uia.py: core/chemdraw_tool/adapters -> project root.'''
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(os.path.dirname(here)))
    return os.path.join(root, 'bin', 'kd_uia.py')


def is_64bit_interpreter() -> bool:
    return sys.maxsize > 2 ** 32


def _python64_candidates() -> list:
    '''Interpreters that may carry pywinauto: env override, self, then common paths.'''
    out = []
    env = os.environ.get(PYTHON64_ENV)
    if env:
        out.append(env)
    # Only add this interpreter when it could plausibly have pywinauto: the
    # bundled 32-bit runtime does not (measured), and using it would just fail.
    if is_64bit_interpreter():
        out.append(sys.executable)
    local = os.environ.get('LOCALAPPDATA') or ''
    if local:
        for ver in ('Python313', 'Python312', 'Python311', 'Python310'):
            out.append(os.path.join(local, 'Programs', 'Python', ver, 'python.exe'))
    out.extend([r'C:\Python311\python.exe', r'C:\Python312\python.exe'])
    seen, unique = set(), []
    for path in out:
        try:
            key = os.path.normcase(os.path.abspath(path))
        except Exception:
            continue
        if key in seen or not os.path.isfile(path):
            continue
        seen.add(key)
        unique.append(path)
    return unique


def uia_documents(pid: int, timeout: float = 15.0,
                  python64: Optional[str] = None) -> Result:
    '''Read the UI Automation tree of a KingDraw window.

    Returns the open documents (the KDLayoutDocument tab and the file-name Text it
    carries) plus a control census. This is the primary proof that a document
    opened: the names are exact strings, unlike a screenshot (KingDraw paints on a
    WPF/D3D surface that never reaches GDI, so PrintWindow answers 94% white or a
    black client area -- measured).

    pywinauto runs in-process when this interpreter has it; otherwise the call is
    bridged to a 64-bit interpreter through bin/kd_uia.py, because the bundled
    32-bit runtime ships neither pywinauto nor comtypes. The open channel itself
    does not need the x86 DLL, so bridging is the normal path there.
    '''
    started = time.monotonic()
    try:
        _bind_windows_apis()
    except OSError as exc:
        return platform_failure('uia', exc)
    stage = 'uia'
    if pid not in list_pids():
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.KD_CLI_DID_NOT_OPEN, stage,
                                       detail='pid %d is not a live KingDraw process' % pid,
                                       message='Nothing to inspect over UIA'))
    if not main_window(pid):
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.KD_CLI_DID_NOT_OPEN, stage,
                                       detail='pid %d has no visible window' % pid))

    from .. import kd_uia  # local import: this module stays ctypes-only
    if kd_uia.available():
        try:
            payload = kd_uia.collect(pid, timeout=timeout)
        except Exception as exc:
            payload = {'ok': False, 'code': ErrorCode.UNKNOWN,
                       'error': type(exc).__name__ + ': ' + str(exc)}
        payload['executed_by'] = sys.executable
    else:
        payload = _uia_via_bridge(pid, timeout, python64)
    elapsed = int((time.monotonic() - started) * 1000)
    if not payload.get('ok'):
        code = payload.get('code') or ErrorCode.UNKNOWN
        if code not in (ErrorCode.KD_CLI_DID_NOT_OPEN, ErrorCode.TIMEOUT,
                        ErrorCode.NOT_INSTALLED):
            code = ErrorCode.UNKNOWN
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      elapsed_ms=elapsed, data={'uia': payload},
                      failure=_failure(code, stage,
                                       detail=str(payload.get('error'))[:300],
                                       message='Could not read the UIA tree',
                                       hint=str(payload.get('hint') or
                                                ('Set %s to a 64-bit interpreter with '
                                                 'pywinauto' % PYTHON64_ENV))))
    return Result(ok=True, data=dict(payload), channel=CHANNEL,
                  evidence=EVIDENCE_MEASURED, elapsed_ms=elapsed)


def _uia_via_bridge(pid: int, timeout: float, python64: Optional[str]) -> dict:
    '''Run the UIA reader in a 64-bit interpreter and parse the JSON it prints.'''
    script = _uia_script()
    if not os.path.isfile(script):
        return {'ok': False, 'code': ErrorCode.NOT_INSTALLED,
                'error': 'UIA reader script missing: ' + script}
    candidates = ([python64] if python64 else []) + (
        [_UIA_CACHE['python']] if _UIA_CACHE.get('python') else []) + _python64_candidates()
    errors = []
    last: dict = {}
    for exe in candidates:
        if not exe or not os.path.isfile(exe):
            continue
        try:
            proc = subprocess.run([exe, script, str(pid)], capture_output=True,
                                  timeout=max(1.0, timeout))
        except subprocess.TimeoutExpired:
            errors.append('%s: timeout after %.1fs' % (exe, timeout))
            continue
        except OSError as exc:
            errors.append('%s: %s' % (exe, exc))
            continue
        out = (proc.stdout or b'').decode('utf-8', 'replace').strip()
        if not out:
            errors.append('%s: rc=%s stderr=%s' % (
                exe, proc.returncode,
                (proc.stderr or b'').decode('utf-8', 'replace')[-160:]))
            continue
        try:
            payload = json.loads(out.splitlines()[-1])
        except Exception:
            errors.append('%s: unparsable output %r' % (exe, out[:120]))
            continue
        if payload.get('ok'):
            _UIA_CACHE['python'] = exe
            payload['bridged_by'] = exe
            payload['source'] = 'pywinauto via ' + os.path.basename(exe)
            return payload
        # A candidate that simply lacks pywinauto must not end the search: try
        # the next interpreter, and keep this answer only as a last resort.
        last = dict(payload)
        last['bridged_by'] = exe
        errors.append('%s: %s' % (exe, payload.get('error')))
        if payload.get('code') != ErrorCode.NOT_INSTALLED:
            return payload
    if last:
        last['attempts'] = errors[:5]
        return last
    return {'ok': False, 'code': ErrorCode.NOT_INSTALLED,
            'error': 'no 64-bit interpreter with pywinauto was found',
            'hint': 'Set %s to one, e.g. the Python311 python.exe' % PYTHON64_ENV,
            'attempts': errors[:5]}


def document_names(uia_payload: dict) -> list:
    '''Flatten a uia_documents payload into the document names it reported.'''
    names = []
    for doc in (uia_payload or {}).get('documents') or []:
        for text in doc.get('texts') or []:
            name = (text or {}).get('name') or ''
            if name and name not in names:
                names.append(name)
    return names


def is_running() -> bool:
    return bool(list_pids())


__all__ = [
    'APP_NAME', 'CHANNEL', 'MAIN_WINDOW_MIN_AREA', 'app_home_changes',
    'capture_window', 'close_app', 'color_variety', 'find_home', 'is_running',
    'document_names', 'is_64bit_interpreter', 'iter_windows', 'list_pids',
    'main_window', 'open_file', 'png_from_bgra', 'raise_window', 'uia_documents',
    'wait_for_main_window',
]
