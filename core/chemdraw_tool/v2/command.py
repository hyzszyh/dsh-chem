"""Drive ChemDraw menu commands through UI Automation (FR-S3, §5).

Measured on ChemDraw 25: COM cannot fire a menu item (Execute raises), and
PostMessage(WM_COMMAND) kills the process. What does work is expanding the real
menu bar through UI Automation and clicking the item, then comparing the exported
page before and after. A command that left the page byte-identical is reported as
not applied, never as success.

Two measured traps: ChemDraw drops the automation proxy after some operations
(re-get it by ProgID), and an untitled page disappears when the client detaches,
so a command must run against a page drawn in the same session.
"""

import hashlib
import os
import tempfile
import time

PROGID = 'ChemDraw_x64.Application'
SETTLE = 0.7


def _hwnd(app) -> int:
    window = app.MainWindow
    return int(window) if not hasattr(window, 'HWND') else int(window.HWND)


def _reattach(channel) -> object:
    '''ChemDraw drops the automation proxy; rebind it and the active page.'''
    import win32com.client as win32
    app = win32.GetActiveObject(PROGID)
    channel._app = app
    try:
        channel._doc = app.ActiveDocument
    except Exception:
        pass
    return app


def _window_handle(channel):
    '''(app, hwnd) with one re-attach if the proxy went stale. Measured: it does.'''
    last = None
    for _attempt in range(3):
        try:
            app = channel._app
            if app is None:
                raise RuntimeError('no proxy')
            return app, _hwnd(app)
        except Exception as exc:
            last = exc
            try:
                _reattach(channel)
            except Exception as inner:
                last = inner
    raise RuntimeError('no window: %s' % str(last)[:100])


def _shot(channel, folder: str, tag: str) -> str:
    '''Hash of the exported page — the change detector that survived every probe.'''
    path = os.path.join(folder, tag + '.png')
    if os.path.exists(path):
        os.remove(path)
    _, _, document = channel._doc, None, None
    result = channel.export(path, fmt='png', resolution=150)
    if not result.ok or not os.path.exists(path):
        return ''
    with open(path, 'rb') as handle:
        return hashlib.sha256(handle.read()).hexdigest()[:16]


def _menu_items(window) -> dict:
    found = {}
    for item in window.descendants(control_type='MenuItem'):
        text = (item.window_text() or '').strip()
        if text and text not in found:
            found[text] = item
    return found


def run_in(channel, command: str, menu: str = '', settle: float = SETTLE,
           folder: str = '') -> dict:
    '''Click one command on a live channel; caller owns the lock and the page.'''
    started = time.time()
    warnings = []
    folder = folder or tempfile.mkdtemp(prefix='cdcmd-')
    from pywinauto import Application
    from pywinauto.keyboard import send_keys

    def done(ok, stage, message='', extra=None):
        row = {'ok': ok, 'command': command, 'menu': menu or '?',
               'stage': stage, 'message': message,
               'warnings': list(warnings),
               'elapsed_ms': int((time.time() - started) * 1000)}
        row.update(extra or {})
        return row

    try:
        _, hwnd = _window_handle(channel)
    except Exception as exc:
        return done(False, 'window', str(exc)[:120])
    before = _shot(channel, folder, 'before-command')
    if not before:
        warnings.append('could not export the page before the command')
    try:
        _, hwnd = _window_handle(channel)
    except Exception:
        pass
    gui = Application(backend='uia').connect(handle=hwnd)
    window = gui.window(handle=hwnd)
    menus = _menu_items(window)
    target_menu = menus.get(menu) if menu else None
    if target_menu is None and not menu:
        for label in sorted(menus):
            candidate = menus[label]
            try:
                candidate.expand()
                time.sleep(settle * 0.5)
                if any(command.lower() in (i.window_text() or '').lower()
                       for i in window.descendants(control_type='MenuItem')):
                    target_menu = candidate
                    break
            except Exception:
                continue
            send_keys('{ESC}')
    if target_menu is None:
        return done(False, 'menu',
                    'menu %r not found; saw %s' % (menu, ', '.join(sorted(menus))))
    try:
        target_menu.expand()
    except Exception as exc:
        return done(False, 'expand', str(exc)[:120])
    time.sleep(settle)
    item = None
    candidates = list(window.descendants(control_type='MenuItem'))
    for candidate in candidates:
        if (candidate.window_text() or '').strip() == command:
            item = candidate
            break
    if item is None:
        for candidate in candidates:
            if command.lower() in (candidate.window_text() or '').lower():
                item = candidate
                break
    if item is None:
        send_keys('{ESC}')
        return done(False, 'item', 'command %r is not on that menu' % command)
    item.click_input()
    time.sleep(settle * 1.8)
    send_keys('{ESC}')
    time.sleep(0.4)
    try:
        _reattach(channel)
    except Exception:
        pass
    after = _shot(channel, folder, 'after-command')
    if not after:
        warnings.append('could not export the page after the command')
    changed = bool(before) and bool(after) and before != after
    return done(changed, 'applied' if changed else 'no-change',
                '' if changed else 'the page is byte-identical; not applied',
                {'changed': changed, 'before': before, 'after': after})


def run(command: str, menu: str = '', settle: float = SETTLE) -> dict:
    '''Open a session, click the command on a fresh page, report the outcome.'''
    from .. import applock
    from ..adapters import cd_com
    channel = cd_com.channel(visible=True)
    with applock.hold(applock.CHEMDRAW, timeout=150):
        attached = channel.connect()
        if not attached.ok:
            return {'ok': False, 'command': command, 'stage': 'connect',
                    'message': str(getattr(attached.failure, 'message', ''))[:120],
                    'elapsed_ms': 0}
        return run_in(channel, command, menu=menu, settle=settle)