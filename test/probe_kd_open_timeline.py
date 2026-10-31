'''Timeline probe: .king title, single-instance reuse, and WM_CLOSE latency.

Answers three questions the adapter design depends on:
  1. does the window title carry the file name (needed for the "opened" assert)?
  2. when KingDraw is already running, does a second launch hand the file over to
     the existing instance or start a second one?
  3. how long does a WM_CLOSE that is honoured take to actually free the pid?

Usage: python test/probe_kd_open.py2 ... (bounded: never waits more than 40 s)
'''
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import probe_kd_open as p  # noqa: E402


def state():
    pids = p.pids_for(p.EXE_NAME)
    return pids, [w for w in p.windows() if w[0] in pids]


def wait_title(proc, seconds, label):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(0.5)
        pids, wins = state()
        print('  %-8s %.1fs pids=%s wins=%r alive=%s' % (
            label, time.monotonic(), pids, wins, proc.poll() is None))
        if wins:
            return pids, wins
    return state()


def main() -> int:
    print('start:', state())
    tmp = tempfile.gettempdir()
    king_src = os.path.join(p.HOME, 'Cyclohexane.king')
    king = os.path.join(tmp, 'kd_open_probe_cyclo.king')
    shutil.copyfile(king_src, king)
    mol = p.make_molfile()
    print('samples:', os.path.basename(king), os.path.basename(mol))

    print('[1] launch with .king, watch title')
    t0 = time.monotonic()
    proc = subprocess.Popen([p.EXE, king], cwd=p.HOME, close_fds=True)
    pids1, wins1 = wait_title(proc, 12.0, 'king')
    print('  title after .king:', wins1, 'elapsed %.1fs' % (time.monotonic() - t0))

    print('[2] reuse: launch again with .mol while the instance is up')
    time.sleep(1.0)
    before = state()
    proc2 = subprocess.Popen([p.EXE, mol], cwd=p.HOME, close_fds=True)
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        time.sleep(0.5)
        pids, wins = state()
        print('  reuse   pids=%s wins=%r p2_alive=%s rc=%r' % (
            pids, wins, proc2.poll() is None, proc2.returncode))
        if proc2.poll() is not None:
            break
    print('  before pids=%s after pids=%s' % (before[0], pids))
    print('  second process rc:', proc2.returncode)

    print('[3] close: WM_CLOSE to every pid we started')
    live = [pid for pid in (proc.pid, proc2.pid) if pid in p.pids_for(p.EXE_NAME)]
    for pid in live:
        print('  WM_CLOSE ->', pid, p.close_pid(pid))
    close_t0 = time.monotonic()
    while time.monotonic() - close_t0 < 20.0:
        pids, wins = state()
        if not pids:
            print('  all gone after %.1fs' % (time.monotonic() - close_t0))
            break
        time.sleep(0.5)
    else:
        print('  still alive after 20s:', state())
    print('end:', state())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
