'''A wedged ChemDraw must not freeze the MCP server.

    python test/test_com_timeout.py

Reproduces the t20 finding P1-1 and proves the fix from com_broker.py:

  * test_01 is the "before" picture: the loop is serial, so one call without a
    deadline makes ping wait for it.
  * test_02 is the "after" picture: the slow call returns E10 while ping is
    answered during the same window.
  * test_03/04: wedged is sticky and fast, and KingDraw keeps working - the two
    channels are independent, which is the whole reason the broker only guards
    the ChemDraw side.

No ChemDraw and no KingDraw are started. Other team members may be driving a
real ChemDraw at the same time, so every test here uses a fake channel and
monkeypatches the seam instead of trying to wedge the real one.
'''
from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORE = os.path.join(ROOT, 'core')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from chemdraw_tool import com_broker  # noqa: E402
from chemdraw_tool import mcp_server  # noqa: E402
from chemdraw_tool.models import ERROR_TEXT, ErrorCode, Result  # noqa: E402


class SlowChannel:
    """connect() answers, the drawing call parks. This is the modal-dialog shape."""

    def __init__(self, delay=3.0):
        self.delay = delay
        self.threads = []
        self.calls = []

    def connect(self):
        self.threads.append(threading.current_thread().name)
        return Result(ok=True, data={'reused': True}, channel='chemdraw')

    def draw_smiles(self, smiles, route=None):
        self.calls.append('draw_smiles')
        time.sleep(self.delay)
        return Result(ok=True, data={'atoms_after': 1, 'bonds_after': 0},
                      channel='chemdraw')

    def _doc_count(self):
        return 1

    def close(self):
        return Result(ok=True, data={'quit': True}, channel='chemdraw')


class HealthyChannel(SlowChannel):
    def __init__(self, delay=0.0):
        super().__init__(delay)


def _tool_call(name, args=None):
    return {'jsonrpc': '2.0', 'id': name + '-1', 'method': 'tools/call',
            'params': {'name': name, 'arguments': args or {}}}


def _serve(requests, stdout=None):
    """Run the real stdio loop over a canned request list; return parsed replies."""
    out = stdout or io.StringIO()
    payload = ''.join(json.dumps(r) + '\n' for r in requests)
    with mock.patch.object(sys, 'stdin', io.StringIO(payload)), \
            mock.patch.object(sys, 'stdout', out):
        mcp_server._serve_loop()
    return [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]


def _payload(response):
    return json.loads(response['result']['content'][0]['text'])


class Base(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {
            'CHEMTOOL_COM_TIMEOUT': '0.4',
            'CHEMTOOL_COM_PROBE_TIMEOUT': '0.4',
            'CHEMTOOL_COM_RETRY_AFTER': '60',
        })
        self.env.start()
        com_broker.reset(lambda: SlowChannel())

    def tearDown(self):
        self.env.stop()
        com_broker.shutdown(deadline=0.1)


class BeforeTheFix(Base):
    def test_01_one_slow_call_makes_ping_wait(self):
        """The pre-fix picture, kept as a reproduction of the finding."""
        marks = []
        real_handle = mcp_server.handle

        def handle(request):
            if request.get('method') == 'tools/call' and \
                    request['params']['name'] == 'chemdraw_draw':
                channel = SlowChannel(delay=1.2)
                marks.append(('slow-start', time.monotonic()))
                channel.draw_smiles('CCO')          # no deadline anywhere
                marks.append(('slow-end', time.monotonic()))
                return {'jsonrpc': '2.0', 'id': request['id'],
                        'result': {'content': [{'type': 'text', 'text': '{"ok": true}'}],
                                   'isError': False}}
            reply = real_handle(request)
            marks.append(('ping', time.monotonic()))
            return reply

        started = time.monotonic()
        with mock.patch.object(mcp_server, 'handle', side_effect=handle):
            replies = _serve([_tool_call('chemdraw_draw', {'smiles': 'CCO'}),
                              {'jsonrpc': '2.0', 'id': 7, 'method': 'ping'}])
        slow_end = dict(marks)['slow-end']
        ping_at = dict(marks)['ping']
        self.assertGreater(ping_at - started, 1.0,
                           'ping should have had to wait for the slow call')
        self.assertGreaterEqual(ping_at, slow_end)
        self.assertEqual(len(replies), 2)


class AfterTheFix(Base):
    def test_02_slow_call_returns_e10_while_ping_answers(self):
        started = time.monotonic()
        replies = _serve([_tool_call('chemdraw_draw', {'smiles': 'CCO'}),
                          {'jsonrpc': '2.0', 'id': 7, 'method': 'ping'}])
        elapsed = time.monotonic() - started
        self.assertEqual(len(replies), 2, replies)
        first = _payload(replies[0])
        self.assertFalse(first['ok'])
        self.assertEqual(first['failure']['code'], ErrorCode.COM_STALLED)
        self.assertTrue(replies[0]['result']['isError'])
        # ping is served while the fake call is still parked; the fake sleeps 3 s
        self.assertIn('result', replies[1])
        self.assertEqual(replies[1]['result'], {})
        self.assertLess(elapsed, 2.0,
                        'ping waited for the slow call: %.2fs' % elapsed)

    def test_03_second_call_after_wedge_fails_fast(self):
        first = _payload(mcp_server.handle(_tool_call('chemdraw_draw', {'smiles': 'CCO'})))
        self.assertEqual(first['failure']['code'], ErrorCode.COM_STALLED)

        started = time.monotonic()
        second = _payload(mcp_server.handle(_tool_call('chemdraw_draw', {'smiles': 'CCO'})))
        fast = time.monotonic() - started
        self.assertEqual(second['failure']['code'], ErrorCode.COM_STALLED)
        self.assertLess(fast, 0.3, 'the second call sat through the deadline again')
        self.assertIn('wedged', second['failure']['detail'])

    def test_04_kingdraw_keeps_working_while_the_com_channel_is_wedged(self):
        _payload(mcp_server.handle(_tool_call('chemdraw_draw', {'smiles': 'CCO'})))
        self.assertTrue(com_broker.broker().wedged)

        workers = {'inmol_ok': {'ok': True, 'channel': 'kingdraw', 'data': {'text': 'C2H6O'}}}
        started = time.monotonic()
        with mock.patch.object(mcp_server, 'call_worker',
                               side_effect=lambda op, args, timeout=40: workers['inmol_ok']):
            reply = mcp_server.handle(_tool_call('kingdraw_formula', {'smiles': 'CCO'}))
        elapsed = time.monotonic() - started
        payload = _payload(reply)
        self.assertTrue(payload['ok'], payload)
        self.assertFalse(reply['result']['isError'])
        self.assertLess(elapsed, 0.3, 'the KingDraw channel is not behind the COM broker')

    def test_05_com_objects_are_created_on_the_broker_thread(self):
        channel = SlowChannel(delay=0.0)
        com_broker.reset(lambda: channel)
        com_broker.channel_proxy().connect()
        self.assertEqual(channel.threads, ['chemdraw-com'])
        self.assertNotEqual(channel.threads[0], threading.current_thread().name)

    def test_06_probe_unwedges_after_the_cooldown(self):
        com_broker.reset(lambda: SlowChannel(delay=5.0))
        with mock.patch.dict(os.environ, {'CHEMTOOL_COM_TIMEOUT': '0.3'}):
            first = _payload(mcp_server.handle(_tool_call('chemdraw_draw', {'smiles': 'CCO'})))
        self.assertEqual(first['failure']['code'], ErrorCode.COM_STALLED)

        # A fresh generation answers immediately; the cooldown has to elapse first.
        com_broker._BROKER._factory = lambda: HealthyChannel()  # type: ignore[attr-defined]
        with mock.patch.dict(os.environ, {'CHEMTOOL_COM_RETRY_AFTER': '0.05',
                                          'CHEMTOOL_COM_TIMEOUT': '2.0'}):
            time.sleep(0.08)
            reply = mcp_server.handle(_tool_call('chemdraw_draw', {'smiles': 'CCO'}))
        payload = _payload(reply)
        self.assertTrue(payload['ok'], payload)
        self.assertFalse(com_broker.broker().wedged)

    def test_07_failure_envelope_shape_and_hint(self):
        payload = _payload(mcp_server.handle(_tool_call('chemdraw_draw', {'smiles': 'CCO'})))
        self.assertFalse(payload['ok'])
        failure = payload['failure']
        self.assertEqual(failure['code'], ErrorCode.COM_STALLED)
        self.assertEqual(failure['channel'], 'chemdraw')
        self.assertEqual(failure['stage'], com_broker.STAGE)
        self.assertIn('dialog', failure['hint'].lower())
        self.assertIn('ChemDraw window', failure['hint'])
        for key in ('ok', 'data', 'failure', 'channel', 'degraded', 'degrade_reason',
                    'evidence', 'elapsed_ms', 'warnings', 'evidence_note'):
            self.assertIn(key, payload, 'the Result envelope must not change shape')

    def test_08_shutdown_returns_even_when_the_worker_is_parked(self):
        com_broker.reset(lambda: SlowChannel(delay=5.0))
        with mock.patch.dict(os.environ, {'CHEMTOOL_COM_TIMEOUT': '0.2'}):
            mcp_server.handle(_tool_call('chemdraw_draw', {'smiles': 'CCO'}))
        started = time.monotonic()
        com_broker.shutdown(deadline=0.3)
        self.assertLess(time.monotonic() - started, 1.5)


class Contract(unittest.TestCase):
    def test_09_error_code_is_registered(self):
        self.assertEqual(ErrorCode.COM_STALLED, 'E10')
        message, hint = ERROR_TEXT[ErrorCode.COM_STALLED]
        self.assertIn('dialog', message.lower())
        self.assertTrue(hint)

    def test_10_the_sixteen_tools_are_untouched(self):
        # The tool list is a contract: every addition is meant to break this
        # until it is updated on purpose (kingdraw_close added it to 16).
        names = [tool['name'] for tool in mcp_server.TOOLS]
        self.assertEqual(len(names), 16, names)
        self.assertEqual(names, [
            'chem_identity', 'kingdraw_smiles_to_mol', 'kingdraw_mol_to_smiles',
            'kingdraw_formula', 'kingdraw_read_king', 'kingdraw_match',
            'kingdraw_to3d', 'kingdraw_export', 'kingdraw_close', 'chemdraw_draw',
            'chemdraw_modify', 'chemdraw_export', 'chemdraw_figure',
            'chemdraw_read', 'chem_crosscheck', 'chemdraw_capabilities'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
