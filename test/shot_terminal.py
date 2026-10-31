'''Screenshot a real console window running a command.

    python test/shot_terminal.py <label> <command...>

Why a real window instead of piping stdout: wrapping, font metrics and the
actual window width decide whether a table lines up. Captured text cannot show
a column that visually collides, so the evidence has to be pixels.

Output goes to test/out/shots/<label>.png and the window is closed afterwards.
'''
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'core'))

import win32con  # noqa: E402
import win32gui  # noqa: E402

from chemdraw_tool import ui_capture  # noqa: E402

OUT_DIR = os.path.join(ROOT, 'test', 'out', 'shots')


def console_windows():
    found = []

    def visit(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        if win32gui.GetClassName(hwnd) != 'ConsoleWindowClass':
            return True
        found.append((hwnd, win32gui.GetWindowText(hwnd)))
        return True

    win32gui.EnumWindows(visit, None)
    return found


def main(argv):
    if len(argv) < 3:
        print('usage: shot_terminal.py <label> <command...>')
        return 2
    label = argv[1]
    command = ' '.join(argv[2:])
    os.makedirs(OUT_DIR, exist_ok=True)

    before = {h for h, _ in console_windows()}
    # A new console window, kept open so it can be photographed.
    subprocess.Popen(
        ['cmd.exe', '/c', 'start', '', 'cmd.exe', '/k',
         'cd /d "%s" && %s' % (ROOT, command)],
        shell=False, close_fds=True,
    )

    hwnd = None
    deadline = time.time() + 20
    while time.time() < deadline:
        for handle, title in console_windows():
            if handle not in before:
                hwnd = handle
                break
        if hwnd:
            break
        time.sleep(0.3)
    if not hwnd:
        print('no console window appeared')
        return 1

    # A fixed, moderately narrow window: 800 px is roughly 90 columns in the
    # default console font, which is narrow enough for long paths to bite.
    win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, 60, 60, 800, 520,
                          win32con.SWP_SHOWWINDOW)
    time.sleep(float(os.environ.get('SHOT_SETTLE', '9')))

    out = os.path.join(OUT_DIR, label + '.png')
    res = ui_capture.capture(hwnd, out, settle=0.4, raise_to_front=True)
    print('capture ok=%s -> %s' % (res.ok, out))
    if res.ok:
        data = res.data or {}
        print('  size=%s bytes=%s method=%s' % (data.get('size'), data.get('bytes'), data.get('method')))

    # Close the window we opened (never touch anything we did not start).
    try:
        win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        time.sleep(1.0)
        if win32gui.IsWindow(hwnd):
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    except Exception as exc:
        print('close failed: %s' % exc)
    return 0 if res.ok else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))