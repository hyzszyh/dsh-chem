'''Window capture: let the agent look at what the software actually drew.

ChemDraw can be asked for a PNG directly (SaveAs with a Format object), but
KingDraw cannot, and for both engines a screenshot is the only way to confirm
that what the user sees matches what the API claims. This module is deliberately
engine-agnostic: find a window by title, bring it forward, grab its rectangle.

Nothing here clicks anything. Guessing coordinates is how automation destroys
someone's unsaved work; the callers that do interact (kd_open) post window
messages to a window handle they found themselves.'''

from __future__ import annotations

import os
import time
from typing import Optional

from .models import ErrorCode, Failure, Result


def _windows() -> list:
    import win32gui
    import win32process
    found = []

    def visit(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return True
            title = win32gui.GetWindowText(hwnd)
            if not title.strip():
                return True
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            found.append({
                'hwnd': hwnd,
                'pid': pid,
                'title': title,
                'class': win32gui.GetClassName(hwnd),
                'rect': win32gui.GetWindowRect(hwnd),
            })
        except Exception:
            pass
        return True

    win32gui.EnumWindows(visit, None)
    return found


def find_window(title_part: str, pid: Optional[int] = None,
                exact_only: bool = False) -> Optional[dict]:
    '''Best visible window matching title_part (case-insensitive).

    An exact title match wins over a substring match on purpose: browser windows
    routinely carry the application name in a tab title ('... — KingDraw ...'),
    and grabbing one of those produces a screenshot of the wrong program while
    looking perfectly successful.
    '''
    needle = title_part.strip().lower()
    candidates = []
    for win in _windows():
        if pid is not None and win['pid'] != pid:
            continue
        if needle in win['title'].lower():
            candidates.append(win)
    for win in candidates:
        if win['title'].strip().lower() == needle:
            return win
    if exact_only:
        return None
    return candidates[0] if candidates else None


def bring_to_front(hwnd: int) -> bool:
    '''Restore and focus a window. Returns False instead of raising.'''
    import win32con
    import win32gui
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        time.sleep(0.15)
        return True
    except Exception:
        return False


def flash_to_front(hwnd: int, hold: float = 0.3) -> bool:
    '''Raise a window above everything just long enough to photograph it.

    ImageGrab reads pixels off the screen, so a window sitting behind the
    user's browser is photographed as that browser. SetForegroundWindow is
    refused for background processes since Windows 8, but SetWindowPos with
    HWND_TOPMOST is not, so this borrows the top of the z-order briefly.
    '''
    import win32con
    import win32gui
    try:
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW)
        time.sleep(hold)
        return True
    except Exception:
        return False


def release_topmost(hwnd: int) -> None:
    import win32con
    import win32gui
    try:
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE)
    except Exception:
        pass


def capture(hwnd: int, out_path: str, settle: float = 0.2,
            raise_to_front: bool = True) -> Result:
    '''Grab one window's rectangle into a PNG. Returns the file facts.'''
    import win32gui
    from PIL import ImageGrab

    try:
        rect = win32gui.GetWindowRect(hwnd)
    except Exception as exc:
        return Result(ok=False, channel='ui', failure=Failure(
            code=ErrorCode.UNKNOWN,
            message='window handle is gone',
            detail=type(exc).__name__ + ': ' + str(exc), stage='capture'))
    left, top, right, bottom = rect
    if right - left < 8 or bottom - top < 8:
        return Result(ok=False, channel='ui', failure=Failure(
            code=ErrorCode.UNKNOWN,
            message='window is minimised or has no area',
            detail=str(rect), stage='capture'))
    raised = flash_to_front(hwnd) if raise_to_front else False
    try:
        if settle:
            time.sleep(settle)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        image = ImageGrab.grab(bbox=rect, all_screens=True)
        image.save(out_path)
    except Exception as exc:
        if raised:
            release_topmost(hwnd)
        return Result(ok=False, channel='ui', failure=Failure(
            code=ErrorCode.UNKNOWN,
            message='screenshot failed',
            detail=type(exc).__name__ + ': ' + str(exc), stage='capture'))
    if raised:
        release_topmost(hwnd)
    size = os.path.getsize(out_path)
    return Result(ok=True, channel='ui', data={
        'path': os.path.abspath(out_path),
        'bytes': size,
        'width': image.width,
        'height': image.height,
        'rect': list(rect),
    })


def capture_by_title(title_part: str, out_path: str,
                     pid: Optional[int] = None,
                     foreground: bool = True,
                     exact_only: bool = False) -> Result:
    '''Find a window by title, optionally focus it, then capture it.

    Pass exact_only when a browser tab could carry the same word in its title,
    which is exactly what happens when someone reads about KingDraw while the
    application is closed: the screenshot succeeds and shows the wrong window.
    '''
    win = find_window(title_part, pid=pid, exact_only=exact_only)
    if win is None:
        return Result(ok=False, channel='ui', failure=Failure(
            code=ErrorCode.NOT_INSTALLED,
            message='no visible window matching %r' % title_part,
            hint='Start the application first, or pass a substring that appears in its title bar',
            stage='locate'))
    if foreground:
        bring_to_front(win['hwnd'])
    result = capture(win['hwnd'], out_path)
    if result.ok:
        result.data['pid'] = win['pid']
        result.data['title'] = win['title']
    return result


def list_windows(needle: str = '') -> Result:
    '''Every visible titled window, optionally filtered. For hung detection.'''
    low = needle.lower()
    rows = [w for w in _windows() if low in (w['title'] + ' ' + w['class']).lower()]
    return Result(ok=True, channel='ui', data={'count': len(rows), 'windows': rows})