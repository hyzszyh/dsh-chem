'''Exploratory probe: does KingDraw.WpfForm.exe accept a molfile argument, and how
does one tell from the outside that it really opened?

Prints, per second: matching PIDs, their visible window titles, and whether a
same-stem .king sidecar appeared next to the input. Closes only the instance it
started, with WM_CLOSE.

Usage: python test/probe_kd_open.py [--keep] [--timeout 15]
'''
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import tempfile
import time

HOME = os.environ.get('KINGDRAW_HOME', r'D:\tool\KingDraw')
EXE = os.path.join(HOME, 'KingDraw.WpfForm.exe')
EXE_NAME = 'KingDraw.WpfForm.exe'

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

TH32CS_SNAPPROCESS = 0x00000002
WM_CLOSE = 0x0010
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ('dwSize', wt.DWORD), ('cntUsage', wt.DWORD),
        ('th32ProcessID', wt.DWORD), ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
        ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD),
        ('th32ParentProcessID', wt.DWORD), ('pcPriClassBase', ctypes.c_long),
        ('dwFlags', wt.DWORD), ('szExeFile', ctypes.c_wchar * 260),
    ]


def pids_for(name: str) -> list:
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    out = []
    if snap == -1:
        return out
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    try:
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == name.lower():
                out.append(int(entry.th32ProcessID))
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return out


def windows() -> list:
    '''Visible top-level windows: [(pid, title)].'''
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            pid = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            title = buf.value
            if title:
                found.append((int(pid.value), title))
        return True

    user32.EnumWindows(cb, 0)
    return found


def close_pid(pid: int) -> int:
    sent = 0

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lparam):
        nonlocal sent
        owner = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if int(owner.value) == pid and user32.IsWindowVisible(hwnd):
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            sent += 1
        return True

    user32.EnumWindows(cb, 0)
    return sent


def make_molfile() -> str:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'core'))
    from chemdraw_tool.adapters import kd_native as kd
    res = kd.smiles_to_mol('c1ccccc1O')
    assert res.ok, res.to_dict()
    path = os.path.join(tempfile.gettempdir(), 'kd_open_probe_phenol.mol')
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(res.data['text'])
    return path


def main(argv: list) -> int:
    timeout = 15.0
    keep = '--keep' in argv
    if '--timeout' in argv:
        timeout = float(argv[argv.index('--timeout') + 1])
    print('exe exists:', os.path.isfile(EXE))
    before_pids = pids_for(EXE_NAME)
    print('pids before:', before_pids)
    print('windows before:', [w for w in windows() if w[0] in before_pids])
    mol = make_molfile()
    print('input molfile:', mol, os.path.getsize(mol), 'bytes')
    stem = os.path.splitext(mol)[0]
    sidecar = stem + '.king'
    print('sidecar exists before:', os.path.exists(sidecar))

    started = time.monotonic()
    proc = subprocess.Popen([EXE, mol], cwd=HOME, close_fds=True)
    print('spawned pid:', proc.pid)
    seen = []
    while time.monotonic() - started < timeout:
        time.sleep(1.0)
        pids = pids_for(EXE_NAME)
        wins = [w for w in windows() if w[0] in pids]
        line = '%.1fs pids=%s wins=%r sidecar=%s spawned_alive=%s' % (
            time.monotonic() - started, pids, wins,
            os.path.exists(sidecar), proc.poll() is None)
        print(line)
        seen.append((pids, wins))
        if proc.poll() is not None:
            print('spawned process exited with', proc.returncode, '(single-instance forwarding?)')
            break
        if any('phenol' in t.lower() or 'kingdraw' in t.lower() for _p, t in wins):
            print('hit: window title matched')
            break
    pids_now = pids_for(EXE_NAME)
    print('final pids:', pids_now)
    print('final windows:', [w for w in windows() if w[0] in pids_now])
    if keep:
        print('--keep: leaving processes alone')
        return 0
    mine = proc.pid if proc.poll() is None else None
    if mine:
        print('WM_CLOSE to spawned pid', mine, '->', close_pid(mine))
    else:
        new = [p for p in pids_now if p not in before_pids]
        print('spawned process already gone; new pids since start:', new,
              '-> not touching them')
    time.sleep(2.0)
    print('pids after close:', pids_for(EXE_NAME))
    print('windows after close:', [w for w in windows() if w[0] in pids_for(EXE_NAME)])
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
