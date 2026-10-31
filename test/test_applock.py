'''The cross-process app lock, tested from two processes.

    python test/test_applock.py

Why this file exists: two `kd export` runs started at the same time used to
hand their files to the same single-instance KingDraw window and both time out
(measured: 122 s each, nothing produced, 44 temp folders left behind). The fix
is a named mutex around the GUI work, so what has to be proven is exactly the
thing a single-process test cannot show: a second process really waits, the
wait is bounded, a dead holder does not wedge the next call, and nesting inside
one thread - kd export drives the app through kd open - does not deadlock.
'''
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORE = os.path.join(ROOT, 'core')
OUT = os.path.join(HERE, 'out')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from chemdraw_tool import applock  # noqa: E402

PREAMBLE = (
    'import sys, time, os\n'
    'sys.path.insert(0, %r)\n' % CORE
)


def spawn(code, env=None):
    environ = dict(os.environ)
    environ.pop('CHEMTOOL_APP_LOCK_TIMEOUT', None)
    if env:
        environ.update(env)
    return subprocess.Popen([sys.executable, '-c', PREAMBLE + code],
                            env=environ, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True,
                            encoding='utf-8', errors='replace')


def wait_for(path, timeout=20.0):
    '''The child writes this file once it owns the lock.'''
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if os.path.exists(path):
            return True
        time.sleep(0.02)
    return False


class Lock(unittest.TestCase):

    def setUp(self):
        os.makedirs(OUT, exist_ok=True)
        self.marker = os.path.join(OUT, 'lock_marker_%s' % self._testMethodName)
        if os.path.exists(self.marker):
            os.remove(self.marker)

    def tearDown(self):
        if os.path.exists(self.marker):
            os.remove(self.marker)

    def test_1_a_second_process_really_waits(self):
        '''The lock is exclusive across processes, not just across threads.'''
        child = spawn(
            'from chemdraw_tool import applock\n'
            'hold = applock.hold("probe-serial", timeout=30)\n'
            'open(%r, "w").close()\n' % self.marker +
            'time.sleep(1.5)\n'
            'hold.release()\n')
        try:
            self.assertTrue(wait_for(self.marker), 'the child never took the lock')
            started = time.monotonic()
            hold = applock.hold('probe-serial', timeout=30)
            elapsed = time.monotonic() - started
            hold.release()
            self.assertGreaterEqual(elapsed, 1.0,
                                    'the second process did not wait: %.2fs' % elapsed)
        finally:
            child.communicate(timeout=30)

    def test_2_the_wait_is_bounded_and_says_what_it_is_waiting_for(self):
        child = spawn(
            'from chemdraw_tool import applock\n'
            'hold = applock.hold("probe-bounded", timeout=30)\n'
            'open(%r, "w").close()\n' % self.marker +
            'time.sleep(6.0)\n'
            'hold.release()\n')
        try:
            self.assertTrue(wait_for(self.marker), 'the child never took the lock')
            started = time.monotonic()
            with self.assertRaises(applock.AppBusy) as caught:
                applock.hold('probe-bounded', timeout=0.5)
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 3.0, 'gave up after %.2fs, not ~0.5s' % elapsed)
            text = caught.exception.hint()
            self.assertIn('CHEMTOOL_APP_LOCK_TIMEOUT', text)
            self.assertIn('another chem-draw-tool call', text)
        finally:
            child.kill()
            child.communicate(timeout=30)

    def test_3_nesting_inside_one_thread_does_not_deadlock(self):
        '''kd export holds the lock and then calls kd open, which wants it too.'''
        with applock.app_session('probe-nested', timeout=5):
            started = time.monotonic()
            with applock.app_session('probe-nested', timeout=5):
                with applock.app_session('probe-nested', timeout=5):
                    pass
            self.assertLess(time.monotonic() - started, 1.0)

    def test_4_a_holder_that_dies_does_not_wedge_the_next_call(self):
        '''A mutex, not a lock file: the kernel drops it when the holder dies.'''
        child = spawn(
            'from chemdraw_tool import applock\n'
            'hold = applock.hold("probe-abandoned", timeout=30)\n'
            'open(%r, "w").close()\n' % self.marker +
            'time.sleep(30)\n')
        try:
            self.assertTrue(wait_for(self.marker), 'the child never took the lock')
            child.kill()
            child.communicate(timeout=30)
            started = time.monotonic()
            hold = applock.hold('probe-abandoned', timeout=10)
            elapsed = time.monotonic() - started
            hold.release()
            self.assertLess(elapsed, 3.0,
                            'the abandoned lock was not picked up: %.2fs' % elapsed)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=30)

    def test_5_the_budget_can_be_set_from_the_environment(self):
        child = spawn(
            'from chemdraw_tool import applock\n'
            'hold = applock.hold("probe-env", timeout=30)\n'
            'open(%r, "w").close()\n' % self.marker +
            'time.sleep(6.0)\n'
            'hold.release()\n')
        os.environ['CHEMTOOL_APP_LOCK_TIMEOUT'] = '0.4'
        try:
            self.assertTrue(wait_for(self.marker), 'the child never took the lock')
            started = time.monotonic()
            with self.assertRaises(applock.AppBusy):
                applock.hold('probe-env')
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 3.0, 'the env budget was ignored (%.2fs)' % elapsed)
        finally:
            os.environ.pop('CHEMTOOL_APP_LOCK_TIMEOUT', None)
            child.kill()
            child.communicate(timeout=30)
        # A garbled environment value must not crash a call that only wanted
        # to drive an app; fall back to the documented default instead.
        os.environ['CHEMTOOL_APP_LOCK_TIMEOUT'] = 'abc'
        try:
            self.assertEqual(applock._timeout(), applock.DEFAULT_TIMEOUT)
        finally:
            os.environ.pop('CHEMTOOL_APP_LOCK_TIMEOUT', None)


if __name__ == '__main__':
    unittest.main(verbosity=2)