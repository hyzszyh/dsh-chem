'''Backend architecture assertions: resource lifecycle, sharing, envelopes.

    python test/test_architecture_backend.py

Every case here exists because of a finding in docs/architecture-audit.md, and
each one is a regression guard for the fix made there:

  1-2  the KingDraw export bridge left its scratch directory behind on every call
       (measured: 25 691 leftover kd_export_bridge_* folders in %TEMP%)
  3-4  the ChemDraw staging directory leaked when SaveAs raised
  5-7  the paste route clobbered the user's clipboard and never put it back
  8    the MCP stdio guard must restore sys.stdout and the dup'ed fd
  9    identity returns a flat payload, not a Result envelope - pinned on purpose
  10   the MCP loop is single-threaded, so tool calls are serialised

No ChemDraw and no KingDraw are started: everything is mocked at the seam.
'''
from __future__ import annotations

import ast
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORE = os.path.join(ROOT, 'core')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from chemdraw_tool.adapters import cd_com  # noqa: E402
from chemdraw_tool.adapters import kd_export  # noqa: E402
from chemdraw_tool import identity  # noqa: E402
from chemdraw_tool import mcp_server  # noqa: E402
from chemdraw_tool.models import Result  # noqa: E402


def _stage_dirs():
    root = tempfile.gettempdir()
    try:
        return {n for n in os.listdir(root) if n.startswith('cdstage_')}
    except OSError:
        return set()


def _bridge_dirs():
    root = tempfile.gettempdir()
    try:
        return {n for n in os.listdir(root) if n.startswith('kd_export_bridge_')}
    except OSError:
        return set()


class FakeProc:
    def __init__(self, result_file, payload):
        self.returncode = 0
        self._result_file = result_file
        self._payload = payload
        if payload is not None:
            with open(result_file, 'w', encoding='utf-8') as handle:
                handle.write(json.dumps(payload))

    def poll(self):
        return 0


def _popen_factory(payload):
    state = {'result_file': None}

    def fake_popen(cmd, stdout=None, stderr=None):
        # cmd[6] is the value after --result-file
        index = cmd.index('--result-file')
        state['result_file'] = cmd[index + 1]
        return FakeProc(cmd[index + 1], payload)

    return fake_popen, state


class ExportBridgeScratch(unittest.TestCase):
    '''kd_export._export_via_bridge must not leave scratch folders behind.'''

    def _run(self, payload):
        before = _bridge_dirs()
        fake_popen, _state = _popen_factory(payload)
        self.assertTrue(os.path.isfile(os.path.join(ROOT, 'bin', 'kd_export.py')),
                        'the bridge helper script is missing; this test needs it')
        with mock.patch.object(kd_export, 'find_python64', return_value='C:/fake/python.exe'), \
                mock.patch.object(kd_export.subprocess, 'Popen', side_effect=fake_popen):
            res = kd_export._export_via_bridge(
                'in.mol', 'out.png', 30.0, False, True, True, None, True)
        leftovers = _bridge_dirs() - before
        return res, leftovers

    def test_01_scratch_dir_removed_on_success(self):
        res, leftovers = self._run({'ok': True, 'data': {'path': 'out.png'}})
        self.assertTrue(res.ok, res.failure)
        self.assertEqual(leftovers, set(), 'bridge scratch directory leaked')

    def test_02_scratch_dir_removed_when_the_helper_says_nothing(self):
        res, leftovers = self._run(None)
        self.assertFalse(res.ok)
        self.assertEqual(leftovers, set(), 'bridge scratch directory leaked on the '
                                           'failure path as well')


class ExportBridgeStartFailure(unittest.TestCase):
    def test_12_scratch_dir_removed_when_the_helper_will_not_start(self):
        before = _bridge_dirs()
        with mock.patch.object(kd_export, 'find_python64', return_value='C:/fake/python.exe'), \
                mock.patch.object(kd_export.subprocess, 'Popen',
                                  side_effect=OSError('no such interpreter')):
            res = kd_export._export_via_bridge(
                'in.mol', 'out.png', 30.0, False, True, True, None, True)
        self.assertFalse(res.ok)
        self.assertEqual(_bridge_dirs() - before, set(),
                         'an open helper.log handle blocked the scratch cleanup')


class FakeDoc:
    def __init__(self):
        self.pasted = 0

    def SaveAs(self, *a, **k):
        raise RuntimeError('SaveAs exploded')

    def Paste(self):
        self.pasted += 1


class StagedExport(unittest.TestCase):
    '''A SaveAs exception must not leave the ASCII staging directory behind.'''

    def _channel(self):
        ch = cd_com.ChemDrawChannel()
        ch._app = object()
        ch._doc = FakeDoc()
        ch.document = lambda: Result(ok=True, data={}, channel=cd_com.CHANNEL)
        ch._counts = lambda: {'atoms': 3, 'bonds': 2}
        ch.find_export_type = lambda fmt: Result(
            ok=True, data=[{'index': 7, 'extension': '.png', 'mime': 'image/png'}],
            channel=cd_com.CHANNEL)
        ch._export_format_object = lambda index: object()
        ch.content_bounds = lambda: Result(
            ok=True,
            data={'width_pt': 60.0, 'height_pt': 40.0, 'left': 10.0, 'top': 10.0,
                  'right': 70.0, 'bottom': 50.0},
            channel=cd_com.CHANNEL)
        return ch

    def test_03_staging_dir_removed_when_saveas_raises(self):
        before = _stage_dirs()
        target = os.path.join(tempfile.gettempdir(), '中文导出测试.png')
        res = self._channel().export(target, 'png')
        self.assertFalse(res.ok)
        self.assertIn('SaveAs', str(res.failure.message))
        self.assertEqual(_stage_dirs() - before, set(),
                         'a cdstage_* directory survived the failed SaveAs')


class FakeClipboard:
    CF_TEXT = 1
    CF_UNICODETEXT = 13

    def __init__(self, text=None, fail_write=False):
        self._text = text
        self.fail_write = fail_write
        self.written = []

    def OpenClipboard(self):
        return True

    def CloseClipboard(self):
        return True

    def EmptyClipboard(self):
        self._text = None

    def GetClipboardData(self, fmt):
        if self._text is None:
            raise RuntimeError('no data')
        return self._text if fmt == self.CF_UNICODETEXT else self._text.encode('utf-8')

    def SetClipboardText(self, text):
        if self.fail_write:
            raise RuntimeError('clipboard is locked')
        self.written.append(text)
        self._text = text


class ClipboardRestore(unittest.TestCase):
    '''The paste route must read the user's text first and put it back.'''

    def test_04_reads_text_in_either_format(self):
        self.assertEqual(cd_com.ChemDrawChannel._clipboard_text(FakeClipboard('hello')), 'hello')

        class BytesOnly(FakeClipboard):
            def GetClipboardData(self, fmt):
                if fmt == self.CF_UNICODETEXT:
                    raise RuntimeError('no unicode')
                return 'plain'.encode('utf-8')

        self.assertEqual(cd_com.ChemDrawChannel._clipboard_text(BytesOnly('x')), 'plain')
        self.assertIsNone(cd_com.ChemDrawChannel._clipboard_text(FakeClipboard(None)))

    def test_05_restore_puts_the_text_back(self):
        board = FakeClipboard(None)
        self.assertTrue(cd_com.ChemDrawChannel._restore_clipboard(board, 'user text'))
        self.assertEqual(board.written, ['user text'])

    def test_06_restore_reports_failure_instead_of_raising(self):
        board = FakeClipboard('x', fail_write=True)
        self.assertFalse(cd_com.ChemDrawChannel._restore_clipboard(board, 'user text'))
        self.assertFalse(cd_com.ChemDrawChannel._restore_clipboard(board, None))

    def test_07_paste_result_says_whether_the_clipboard_came_back(self):
        ch = cd_com.ChemDrawChannel()
        ch._app = object()
        ch._doc = FakeDoc()
        ch.document = lambda: Result(ok=True, data={}, channel=cd_com.CHANNEL)
        counts = iter([{'atoms': 0, 'bonds': 0}, {'atoms': 13, 'bonds': 13}])
        ch._counts = lambda: next(counts)
        board = FakeClipboard('what the user had copied')

        class BoardModule(FakeClipboard):
            pass

        board_module = BoardModule('what the user had copied')
        with mock.patch.dict(sys.modules, {'win32clipboard': board_module}), \
                mock.patch.object(cd_com.time, 'sleep', return_value=None):
            res = ch.insert_via_paste('CC(=O)Oc1ccccc1C(=O)O')
        self.assertTrue(res.ok, res.failure)
        self.assertTrue(res.data['clipboard_restored'])
        self.assertEqual(res.warnings, [])
        self.assertEqual(board_module.written, ['CC(=O)Oc1ccccc1C(=O)O',
                                                'what the user had copied'])


class StdioGuard(unittest.TestCase):
    def test_08_guard_restores_stdout_and_fd(self):
        original = sys.stdout
        with mcp_server._StdoutGuard():
            self.assertIsNot(sys.stdout, original)
            sys.stdout.write('this goes to the sink')
        self.assertIs(sys.stdout, original)
        sys.stdout.write('')
        self.assertEqual(sys.stdout.fileno(), 1)


class Envelopes(unittest.TestCase):
    def test_09_identity_is_flat_on_purpose(self):
        payload = identity.identify('c1ccccc1O')
        self.assertTrue(payload['ok'])
        self.assertNotIn('failure', payload)
        # Documented deviation: identity is a flat dict, not a Result envelope
        # (no data / channel / degraded / warnings). Pinned so that changing it
        # is a deliberate decision rather than an accident.
        for key in ('data', 'channel', 'degraded', 'warnings'):
            self.assertNotIn(key, payload)

    def test_10_result_envelope_has_the_documented_keys(self):
        self.assertEqual(
            set(Result(ok=True).to_dict()),
            {'ok', 'data', 'failure', 'channel', 'degraded', 'degrade_reason',
             'evidence', 'elapsed_ms', 'warnings', 'evidence_note'})


class SerialLoop(unittest.TestCase):
    '''One resident server, one request at a time: no re-entrancy to protect.'''

    def test_11_requests_are_processed_in_order_not_concurrently(self):
        order = []

        def fake_handle(request):
            order.append(('start', request['id']))
            order.append(('end', request['id']))
            return {'jsonrpc': '2.0', 'id': request['id'], 'result': {}}

        lines = ''.join(json.dumps({'id': i, 'method': 'ping'}) + '\n'
                        for i in (1, 2, 3))
        out = io.StringIO()
        with mock.patch.object(mcp_server, 'handle', side_effect=fake_handle), \
                mock.patch.object(sys, 'stdin', io.StringIO(lines)), \
                mock.patch.object(sys, 'stdout', out):
            mcp_server._serve_loop()
        self.assertEqual(order, [('start', 1), ('end', 1), ('start', 2), ('end', 2),
                                 ('start', 3), ('end', 3)])


class Lifecycle(unittest.TestCase):
    '''What has to happen when a run is cut short instead of finishing.'''

    def test_13_an_interrupted_run_still_closes_the_channel(self):
        '''Ctrl-C must still Quit the ChemDraw instance this run started.

        Measured alternative, on this machine: a hard kill (TerminateProcess,
        no Python handler, no finally) leaves exactly one ChemDraw.exe behind.
        Nothing breaks -- the next command attaches to it and answers in
        0.3 s -- but the window stays until someone closes it. Ctrl-C is the
        case a human actually produces, and it does go through this finally,
        so what matters is the shape: the dispatch sits inside try, and the
        close sits in finally rather than on the happy path where any
        exception would skip it and leak the instance.
        '''
        path = os.path.join(CORE, 'chemdraw_tool', 'cli.py')
        with open(path, encoding='utf-8') as handle:
            tree = ast.parse(handle.read(), path)

        def calls(node, name):
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                func = child.func
                if isinstance(func, ast.Name) and func.id == name:
                    return True
                if isinstance(func, ast.Attribute) and func.attr == name:
                    return True
            return False

        guards = [node for node in ast.walk(tree)
                  if isinstance(node, ast.Try) and calls(node, '_cd_dispatch')]
        self.assertEqual(len(guards), 1,
                         'the cd dispatch must sit in exactly one try block')
        self.assertTrue(any(calls(statement, 'close')
                            for statement in guards[0].finalbody),
                        'an interrupted run would leave ChemDraw.exe running: '
                        'ch.close() is not in the finally around the dispatch')


class ArgumentValidation(unittest.TestCase):
    '''A usage error must cost no COM call and no vendor install.

    Both checks below used to live inside _cd_dispatch, which only runs once a
    ChemDraw instance answers: on a machine without ChemDraw, `cd modify` with
    no edit flag answered E01 'cannot reach ChemDraw' and never mentioned that
    the command had not been told what to change. The fix moved them to
    _cd_validate_args, and this test pins the ORDER in source, because the
    order is the whole fix and it cannot be observed on a machine where
    ChemDraw happens to be installed.
    '''

    def test_15_the_transient_table_is_readable_on_the_failure_path(self):
        '''The hint table is only touched when a suite fails, so nothing else
        exercises it. A malformed row has to fail here, not at 3am.'''
        import importlib.util
        path = os.path.join(ROOT, 'test', 'run_all.py')
        spec = importlib.util.spec_from_file_location('chem_run_all', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertTrue(module.TRANSIENT, 'the table should not be empty')
        for entry in module.TRANSIENT:
            self.assertEqual(len(entry), 2, 'each row is (signature, hint): %r' % (entry,))
            signature, hint = entry
            self.assertTrue(signature and hint, 'neither part may be empty')
            self.assertEqual(module.transient_hint('x ' + signature + ' y'), hint)
        self.assertIsNone(module.transient_hint('a green log mentions none of these'))

    def test_14_argument_checks_run_before_the_channel_opens(self):
        path = os.path.join(CORE, 'chemdraw_tool', 'cli.py')
        with open(path, encoding='utf-8') as handle:
            tree = ast.parse(handle.read(), path)

        function = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'cmd_cd':
                function = node
        self.assertIsNotNone(function, 'cmd_cd disappeared')

        order = []
        for node in ast.walk(function):
            if isinstance(node, ast.Call):
                name = getattr(node.func, 'id', None) or getattr(node.func, 'attr', None)
                if name in ('_cd_validate_args', '_open_cd_channel'):
                    order.append((node.lineno, name))
        order.sort()
        names = [name for _, name in order]
        self.assertEqual(names, ['_cd_validate_args', '_open_cd_channel'],
                         'the validator must run first, before the COM server '
                         'is touched; observed order: %r' % (names,))


if __name__ == '__main__':
    unittest.main(verbosity=2)
