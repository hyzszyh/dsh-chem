'''One dedicated apartment-threaded worker for every ChemDraw COM call.

Why this exists
---------------
The MCP server is a resident process: it holds one COM connection and serves
requests one at a time (measured in test_architecture_backend test_11). Without a
deadline, one ChemDraw modal dialog - an activation prompt, a save-as box, a
progress window during a big export - parks the call forever. The server then
stops answering everything, ping included, and the only way out is killing the
process, which throws away whatever the user had drawn.

What this does
--------------
* Every COM call runs on one worker thread that called CoInitialize() itself, so
  the COM apartment belongs to that thread. Nothing touches the ChemDraw objects
  from the main thread: cross-apartment calls fail with RPC errors, which is why
  a plain ThreadPoolExecutor is the wrong tool here.
* The caller waits with a deadline. When it expires the channel is marked
  "wedged" and the caller gets a structured failure (ErrorCode.COM_STALLED)
  instead of silence.
* While wedged, later calls fail fast with the same failure - they do not sit
  through the deadline again. KingDraw traffic never goes through this file, so
  the other channel keeps working (that is the whole point of two channels).
* Recovery needs no restart: once CHEMTOOL_COM_RETRY_AFTER seconds have passed,
  the next request starts a fresh worker generation and probes it with connect()
  under a short deadline. If the probe answers, the channel is unwedged and the
  request is served normally.

A worker stuck inside a wedged COM call cannot be cancelled (COM has no safe
cancellation). It is left parked as a daemon thread and is reclaimed when the
dialog is dismissed or the process exits.

Environment
-----------
    CHEMTOOL_COM_TIMEOUT        per-call deadline in seconds    (default 120)
    CHEMTOOL_COM_PROBE_TIMEOUT  deadline for the recovery probe (default 5)
    CHEMTOOL_COM_RETRY_AFTER    cooldown before a probe         (default 30)
'''
from __future__ import annotations

import os
import queue
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout

from .models import ERROR_TEXT, ErrorCode, Failure, Result

CHANNEL = 'chemdraw'
STAGE = 'com-timeout'


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def timeout_s() -> float:
    """Per-call deadline. Read on every call so tests and operators can tune it."""
    return _env_float('CHEMTOOL_COM_TIMEOUT', 120.0)


class _TimeoutSentinel:
    def __repr__(self):
        return '<com timeout>'


TIMED_OUT = _TimeoutSentinel()


class _Job:
    __slots__ = ('name', 'args', 'kwargs', 'future')

    def __init__(self, name, args, kwargs):
        self.name = name
        self.args = args
        self.kwargs = kwargs
        self.future = Future()


class ComBroker:
    """Serialises COM calls onto one apartment thread and bounds each of them."""

    def __init__(self, factory):
        self._factory = factory
        self._queue = queue.Queue()
        self._thread = None
        self._target = None
        self._lock = threading.RLock()
        self._wedged = False
        self._wedged_at = 0.0
        self._wedged_call = ''
        self._parked = []

    # -- worker ------------------------------------------------------------
    def _start_worker(self):
        self._queue = queue.Queue()
        thread = threading.Thread(target=self._run, name='chemdraw-com', daemon=True)
        thread.start()
        self._thread = thread

    def _ensure_worker(self):
        if self._thread is None or not self._thread.is_alive():
            self._start_worker()

    def _run(self):
        # The apartment belongs to this thread: everything COM is created and
        # used here and nowhere else.
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception:
            pass
        try:
            self._target = self._factory()
        except Exception:
            self._target = None
        while True:
            job = self._queue.get()
            if job is None:
                return
            if self._target is None:
                try:
                    self._target = self._factory()
                except Exception:
                    self._target = None
            if self._target is None:
                job.future.set_exception(
                    RuntimeError('the ChemDraw channel could not be created'))
                continue
            try:
                method = getattr(self._target, job.name)
                job.future.set_result(method(*job.args, **job.kwargs))
            except BaseException as exc:  # never let the worker die silently
                if not job.future.done():
                    job.future.set_exception(exc)

    def _replace_worker(self):
        """Park the stuck thread and start a fresh generation."""
        with self._lock:
            if self._thread is not None:
                self._parked.append(self._thread)
            self._thread = None
            self._target = None
            self._start_worker()

    def _submit(self, name, args, kwargs, deadline):
        self._ensure_worker()
        job = _Job(name, args, kwargs)
        self._queue.put(job)
        try:
            return job.future.result(timeout=deadline)
        except FutureTimeout:
            return TIMED_OUT

    # -- failure -----------------------------------------------------------
    def _failure(self, name, detail, since=None):
        message, default_hint = ERROR_TEXT.get(
            ErrorCode.COM_STALLED, ('ChemDraw did not answer in time', ''))
        hint = ('Look at the ChemDraw window: a dialog (activation, save-as, '
                'export progress) is probably waiting for a click. Dismiss it and '
                'retry; the server probes the channel again by itself after '
                '%g s, or immediately after a restart.'
                % _env_float('CHEMTOOL_COM_RETRY_AFTER', 30.0))
        if since is not None:
            detail = '%s; wedged %.0f s since %r' % (
                detail, max(0.0, time.monotonic() - since), self._wedged_call)
        return Result(ok=False, channel=CHANNEL, failure=Failure(
            code=ErrorCode.COM_STALLED, channel=CHANNEL, stage=STAGE,
            message=message, hint=hint or default_hint, detail=detail))

    def _wedge(self, name, detail):
        with self._lock:
            self._wedged = True
            self._wedged_at = time.monotonic()
            self._wedged_call = name
        return self._failure(name, detail)

    # -- public ------------------------------------------------------------
    @property
    def wedged(self) -> bool:
        return self._wedged

    def clear_wedge(self):
        """Forget the wedged state (a doctor run or a test may want a clean sheet)."""
        with self._lock:
            self._wedged = False
            self._wedged_at = 0.0
            self._wedged_call = ''

    def call(self, name, args=(), kwargs=None):
        kwargs = kwargs or {}
        gate = self._wedged_gate(name)
        if gate is not None:
            return gate
        deadline = timeout_s()
        outcome = self._submit(name, args, kwargs, deadline)
        if outcome is TIMED_OUT:
            return self._wedge(name, 'no answer within %g s' % deadline)
        if isinstance(outcome, BaseException):
            return Result(ok=False, channel=CHANNEL, failure=Failure(
                code=ErrorCode.UNKNOWN, channel=CHANNEL, stage='com',
                message='the ChemDraw call raised',
                detail='%s: %s' % (type(outcome).__name__, outcome)))
        return outcome

    def _wedged_gate(self, name):
        """Fast-fail while wedged; probe once per cooldown to see if it recovered."""
        if not self._wedged:
            return None
        since = self._wedged_at
        cooldown = _env_float('CHEMTOOL_COM_RETRY_AFTER', 30.0)
        if time.monotonic() - since < cooldown:
            return self._failure(name, 'the channel is marked wedged; not retried yet',
                                 since=since)
        probe_deadline = _env_float('CHEMTOOL_COM_PROBE_TIMEOUT', 5.0)
        self._replace_worker()
        outcome = self._submit('connect', (), {}, probe_deadline)
        recovered = (outcome is not TIMED_OUT and isinstance(outcome, Result)
                     and outcome.ok)
        if not recovered:
            with self._lock:
                self._wedged_at = time.monotonic()
            return self._failure(
                name, 'the recovery probe did not answer within %g s' % probe_deadline,
                since=since)
        with self._lock:
            self._wedged = False
            self._wedged_at = 0.0
            self._wedged_call = ''
        return None

    def shutdown(self, deadline: float = 10.0):
        """Ask the worker to quit ChemDraw, then stop the thread. Never raises."""
        result = None
        try:
            outcome = self._submit('close', (), {}, deadline)
            if outcome is not TIMED_OUT and not isinstance(outcome, BaseException):
                result = outcome
        except Exception:
            result = None
        try:
            self._queue.put(None)
        except Exception:
            pass
        return result


class ChannelProxy:
    """Looks like a ChemDrawChannel; every call goes through the broker."""

    def __init__(self, broker: ComBroker):
        self._broker = broker

    def __getattr__(self, name):
        if name.startswith('__'):
            raise AttributeError(name)

        def forward(*args, **kwargs):
            return self._broker.call(name, args, kwargs)

        return forward

    @property
    def wedged(self) -> bool:
        return self._broker.wedged


_BROKER = None
_LOCK = threading.Lock()


def broker(factory=None) -> ComBroker:
    """Process-wide broker. The first caller supplies the channel factory."""
    global _BROKER
    with _LOCK:
        if _BROKER is None:
            if factory is None:
                raise RuntimeError('the first broker() call must supply a channel factory')
            _BROKER = ComBroker(factory)
        return _BROKER


def channel_proxy(factory=None) -> ChannelProxy:
    return ChannelProxy(broker(factory))


def reset(factory=None) -> ComBroker:
    """Drop the broker (a stuck worker stays parked) and start over."""
    global _BROKER
    with _LOCK:
        old, _BROKER = _BROKER, None
    if old is not None:
        try:
            old.shutdown(deadline=0.2)
        except Exception:
            pass
    return broker(factory)


def shutdown(deadline: float = 10.0):
    global _BROKER
    with _LOCK:
        current, _BROKER = _BROKER, None
    if current is not None:
        return current.shutdown(deadline=deadline)
    return None


__all__ = ['CHANNEL', 'STAGE', 'ChannelProxy', 'ComBroker', 'TIMED_OUT', 'broker',
           'channel_proxy', 'reset', 'shutdown', 'timeout_s']
