"""A ChemDraw instance that stays up between calls (requirements §15).

Calling Quit after every task is what made the window flash on and off. The app
is started once, kept invisible, and only detached from; a later call attaches to
the running instance with GetActiveObject.
"""

import contextlib
import json
import os
import tempfile
import time


def state_dir() -> str:
    root = os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()
    path = os.path.join(root, 'chem-draw-tool', 'v2')
    os.makedirs(path, exist_ok=True)
    return path


def state_path() -> str:
    return os.path.join(state_dir(), 'session.json')


def load() -> dict:
    try:
        with open(state_path(), 'r', encoding='utf-8') as handle:
            return json.load(handle)
    except Exception:
        return {}


def save(state: dict) -> None:
    path = state_path()
    temp = path + '.tmp'
    with open(temp, 'w', encoding='utf-8') as handle:
        json.dump(state, handle, ensure_ascii=False, indent=2)
    os.replace(temp, path)


class SessionError(RuntimeError):
    def __init__(self, result):
        self.result = result
        failure = getattr(result, 'failure', None)
        message = getattr(failure, 'message', '') or 'could not reach ChemDraw'
        super().__init__(message)


@contextlib.contextmanager
def open_session(visible: bool = False, timeout: int = 90):
    '''Hold the ChemDraw lock, attach or start, hide it, yield, then detach.'''
    from .. import applock
    from ..adapters import cd_com

    channel = cd_com.channel(visible=visible)
    with applock.hold(applock.CHEMDRAW, timeout=timeout):
        connected = channel.connect()
        if not connected.ok:
            raise SessionError(connected)
        hidden = False
        if channel.started_by_us and not visible:
            try:
                channel._app.Visible = False
                hidden = True
            except Exception:
                pass
        state = load()
        state.update({
            'pid': os.getpid(),
            'started_at': state.get('started_at') or _now(),
            'last_seen': _now(),
            'attached': bool(getattr(channel, 'attached', False)),
            'progid': getattr(channel, 'progid_used', ''),
        })
        if hidden:
            state['hidden'] = True
        save(state)
        try:
            yield channel
        finally:
            state = load()
            state['last_seen'] = _now()
            state['documents_open'] = _doc_count(channel)
            save(state)
            # Drop the COM reference only: quitting is what made windows flash.
            channel._doc = None
            channel._app = None


def _now() -> str:
    return time.strftime('%Y-%m-%dT%H:%M:%S')


def _doc_count(channel) -> int:
    app = getattr(channel, '_app', None)
    if app is None:
        return 0
    try:
        return int(app.Documents.Count)
    except Exception:
        return 0


def describe() -> dict:
    '''Everything chem_status needs, without starting or touching anything.'''
    from .. import applock

    info = {'state': load(), 'state_path': state_path()}
    for name in ('chemdraw', 'kingdraw'):
        info['lock_' + name] = _lock_state(applock, name)
    return info


def _lock_state(applock, name: str) -> str:
    '''free | held (probed by trying to take it for zero seconds).'''
    try:
        with applock.hold(name, timeout=0):
            return 'free'
    except Exception:
        return 'held'