'''One GUI app, one driver: a cross-process lock around KingDraw.

KingDraw is a single-instance application. A second launch does not create a
second window, it forwards the file to the instance that already exists -- so
two of our own calls started at the same time hand their files to the same
window and then both wait for a document that never appears. Measured: two
parallel `kd export` runs failed together after 122 s each, having produced
nothing, while the same two calls one after the other take 16 s each and both
succeed.

So the GUI work is serialised with a named Win32 mutex. A mutex rather than a
lock file because the kernel releases it when the holder dies: a crashed call
does not wedge every later one until somebody deletes a stale file by hand.
The wait is bounded and it says what it is waiting for -- the point is to turn
an opaque 122 s double failure into either a success or one sentence.
'''
import contextlib
import ctypes
import os
import sys
import threading
import time

__all__ = ['AppBusy', 'app_session', 'KINGDRAW', 'CHEMDRAW']

KINGDRAW = 'kingdraw'
CHEMDRAW = 'chemdraw'

# A single run takes ~16 s. Eight of them is a generous queue, and a caller
# that has waited that long is better off with a sentence than with a ninth
# attempt, so this is the default and it is overridable.
DEFAULT_TIMEOUT = 150.0

_ERROR_ALREADY_EXISTS = 183
_WAIT_OBJECT_0 = 0x00000000
_WAIT_ABANDONED = 0x00000080
_WAIT_TIMEOUT = 0x00000102
_SYNCHRONIZE = 0x00100000


class AppBusy(RuntimeError):
    '''Raised when the app stayed busy for the whole budget.'''

    def __init__(self, name, waited, holders=None):
        self.name = name
        self.waited = waited
        self.holders = holders or []
        RuntimeError.__init__(self, self.hint())

    def hint(self):
        return ('%s is being driven by another chem-draw-tool call; waited %.1f s '
                'and gave up. Run one GUI command at a time, or raise '
                'CHEMTOOL_APP_LOCK_TIMEOUT.' % (self.name, self.waited))


_state = {}
_state_lock = threading.Lock()


def _mutex_name(name):
    r'''Local\ (not Global\) so separate Windows sessions do not block each
    other. Written as a raw string because "\ " is exactly the invalid escape
    sequence tools/preflight.py refuses to ship.'''
    return 'Local\\chem-draw-tool.' + name


def _timeout(explicit=None):
    if explicit is not None:
        return float(explicit)
    raw = os.environ.get('CHEMTOOL_APP_LOCK_TIMEOUT')
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
    return DEFAULT_TIMEOUT


if sys.platform == 'win32':
    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)


    def _acquire_windows(name, deadline):
        handle = _kernel32.CreateMutexW(None, False, _mutex_name(name))
        if not handle:
            raise OSError(ctypes.get_last_error(), 'CreateMutexW failed')
        started = time.monotonic()
        while True:
            remaining = deadline - time.monotonic()
            wait_ms = 0 if remaining <= 0 else min(int(remaining * 1000) + 1, 250)
            status = _kernel32.WaitForSingleObject(handle, wait_ms)
            if status in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
                # WAIT_ABANDONED is not an error here: the previous holder died
                # without releasing, and we now own it.
                return handle, time.monotonic() - started
            if status != _WAIT_TIMEOUT:
                _kernel32.CloseHandle(handle)
                raise OSError(ctypes.get_last_error(),
                              'WaitForSingleObject returned 0x%x' % status)
            if time.monotonic() >= deadline:
                _kernel32.CloseHandle(handle)
                raise AppBusy(name, time.monotonic() - started)


    def _release_windows(handle):
        try:
            _kernel32.ReleaseMutex(handle)
        finally:
            _kernel32.CloseHandle(handle)

else:  # POSIX: an advisory file lock, same contract.
    import fcntl


    def _lock_path(name):
        return os.path.join(os.environ.get('TMPDIR', '/tmp'),
                            'chem-draw-tool.%s.lock' % name)


    def _acquire_posix(name, deadline):
        path = _lock_path(name)
        handle = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        started = time.monotonic()
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return handle, time.monotonic() - started
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(handle)
                    raise AppBusy(name, time.monotonic() - started)
                time.sleep(0.2)


    def _release_posix(handle):
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            os.close(handle)


class Hold:
    '''A held mutex. Use `with hold:` or call `hold.release()` in a finally.'''

    def __init__(self, name=KINGDRAW, timeout=None):
        self.name = name
        self.waited = 0.0
        self._released = False
        key = (name, threading.get_ident())
        with _state_lock:
            depth = _state.get(key, 0)
        if depth:
            # Same thread already holds it: kd export drives the app through
            # kd open, so the inner call must not wait for the outer one.
            with _state_lock:
                _state[key] = depth + 1
            self._nested = True
            self._handle = None
            return
        self._nested = False
        deadline = time.monotonic() + _timeout(timeout)
        if sys.platform == 'win32':
            self._handle, self.waited = _acquire_windows(name, deadline)
        else:
            self._handle, self.waited = _acquire_posix(name, deadline)
        with _state_lock:
            _state[key] = 1

    def release(self):
        if self._released:
            return
        self._released = True
        key = (self.name, threading.get_ident())
        with _state_lock:
            depth = _state.get(key, 1) - 1
            if depth > 0:
                _state[key] = depth
            else:
                _state.pop(key, None)
        if self._nested or self._handle is None:
            return
        if sys.platform == 'win32':
            _release_windows(self._handle)
        else:
            _release_posix(self._handle)

    def __enter__(self):
        return self.waited

    def __exit__(self, *_exc):
        self.release()
        return False


def hold(name=KINGDRAW, timeout=None):
    '''Acquire the lock and hand back a Hold; raises AppBusy on timeout.'''
    return Hold(name, timeout)


@contextlib.contextmanager
def app_session(name=KINGDRAW, timeout=None):
    '''Hold the app exclusively; re-entrant inside one thread.

    Nesting matters because kd export drives the app through kd open: both
    want the lock and the inner one must not wait for the outer one.
    '''
    key = (name, threading.get_ident())
    with _state_lock:
        depth = _state.get(key, 0)
    if depth:
        with _state_lock:
            _state[key] = depth + 1
        try:
            yield 0.0
        finally:
            with _state_lock:
                _state[key] -= 1
                if not _state[key]:
                    del _state[key]
        return
    budget = _timeout(timeout)
    deadline = time.monotonic() + budget
    if sys.platform == 'win32':
        handle, waited = _acquire_windows(name, deadline)
    else:
        handle, waited = _acquire_posix(name, deadline)
    with _state_lock:
        _state[key] = 1
    try:
        yield waited
    finally:
        with _state_lock:
            _state.pop(key, None)
        if sys.platform == 'win32':
            _release_windows(handle)
        else:
            _release_posix(handle)