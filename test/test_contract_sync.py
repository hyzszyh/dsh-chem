'''Contract reconciliation as a test: MCP tools / DSH plugin tools / CLI subcommands.

    python test/test_contract_sync.py

The same capability is declared in three places, and the declarations drifted once
already (the plugin table forgot chem_crosscheck while mcp_server.TOOLS held 14
tools, not the 12 the docs claimed). This file turns the reconciliation in
tools/contract_sync.py into a gate: any new drift fails here instead of being
found by a human reading three files.

Truth source: the Python side - core/chemdraw_tool/cli.py (argparse) and
core/chemdraw_tool/mcp_server.py (TOOLS). The DSH plugin is a thin shell, so it is
allowed to expose a subset and to rename parameters to camelCase; what it may not
do is call a CLI subcommand or flag that does not exist, require a CLI flag it
never passes, or declare a parameter it never forwards.

The last two tests prove the gate has teeth: they feed it a deliberately broken
surface and, once, a mutated copy of the tree in a temp directory.
'''
from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORE = os.path.join(ROOT, 'core')
TOOLS = os.path.join(ROOT, 'tools')
for path in (CORE, TOOLS):
    if path not in sys.path:
        sys.path.insert(0, path)

import contract_sync as cs  # noqa: E402

NODE = shutil.which('node')


def capture_report(data, findings, mcp, plugin, cli, plugin_paths) -> str:
    buffer = io.StringIO()
    cs.report(findings, mcp, plugin, cli, plugin_paths, stream=buffer)
    return buffer.getvalue()


class Surfaces(unittest.TestCase):
    '''The three declarations can be read at all, and agree today.'''

    @classmethod
    def setUpClass(cls):
        cls.cli = cs.cli_surface()
        cls.mcp = cs.mcp_surface()
        cls.plugin = cs.plugin_surface() if NODE else None

    def test_01_cli_parser_is_introspectable(self):
        self.assertGreaterEqual(len(self.cli), 20, sorted(self.cli))
        for path in ('doctor', 'identity', 'crosscheck', 'cd draw', 'cd export',
                     'cd figure', 'cd read', 'cd modify', 'kd mol', 'kd smiles',
                     'kd formula', 'kd king', 'kd save', 'kd export'):
            self.assertIn(path, self.cli)

    def test_01b_json_is_one_document_and_says_unknown_as_null(self):
        '''Two promises the --json form makes to a script.

        Measured before: 'doctor --json' printed one document per channel back
        to back, so json.loads() answered 'Extra data'; and doctor said
        '"version": ""' while the human form said 'version : unknown', so the
        two views of one envelope disagreed about the same fact.
        '''
        import json
        from chemdraw_tool import cli

        # The framing rule, without paying for a COM round trip.
        one = {'channel': 'chemdraw', 'available': True}
        two = [one, {'channel': 'kingdraw', 'available': False}]
        self.assertIs(cli._doctor_body([one]), one)
        self.assertEqual(cli._doctor_body(two), two)
        self.assertEqual(cli._doctor_status([{'available': False}]), 1)
        self.assertEqual(cli._doctor_status([{'available': True},
                                            {'available': False}]), 0)
        self.assertEqual(cli._doctor_status([]), 1)

        # And a real command: its stdout has to be exactly one JSON value.
        done = subprocess.run([sys.executable, os.path.join(ROOT, 'bin', 'cli.py'),
                               'identity', 'CCO', '--json'], capture_output=True,
                              text=True, encoding='utf-8', errors='replace',
                              timeout=180)
        payload = json.loads(done.stdout)
        self.assertEqual(payload.get('inchikey'), 'LFQSCWFLJHTTHZ-UHFFFAOYSA-N')
        self.assertIsNone(payload.get('note'),
                          "a missing note is null, not ''")

    def test_02_mcp_tool_names_are_unique_and_well_formed(self):
        names = [tool['name'] for tool in self.mcp]
        self.assertEqual(len(names), len(set(names)), 'duplicate MCP tool name')
        for name in names:
            self.assertRegex(name, r'^[a-z][a-z0-9_]+$')

    def test_03_every_mcp_tool_declares_a_real_cli_path(self):
        for name, (path, params) in sorted(cs.MCP_TO_CLI.items()):
            self.assertIn(path, self.cli, '%s -> %s' % (name, path))
            entry = self.cli[path]
            for param, target in sorted(params.items()):
                if target.startswith('--'):
                    self.assertIn(target, entry['flags'], '%s.%s' % (name, param))
                else:
                    index = int(target.split(':')[1])
                    self.assertLess(index, len(entry['positionals']),
                                    '%s.%s' % (name, param))

    def test_04_mcp_mapping_covers_tools_exactly(self):
        missing = sorted({t['name'] for t in self.mcp} - set(cs.MCP_TO_CLI))
        stale = sorted(set(cs.MCP_TO_CLI) - {t['name'] for t in self.mcp})
        self.assertEqual(missing, [], 'MCP tool with no declared CLI path')
        self.assertEqual(stale, [], 'declared CLI path for a tool that is gone')

    @unittest.skipUnless(NODE, 'node is not on PATH; the plugin is an ES module')
    def test_05_plugin_tools_are_discovered(self):
        names = [tool['name'] for tool in self.plugin]
        self.assertGreaterEqual(len(names), 10, names)
        self.assertEqual(len(names), len(set(names)), 'duplicate plugin tool name')
        for tool in self.plugin:
            self.assertEqual(tool['problems'], [], tool['name'])

    @unittest.skipUnless(NODE, 'node is not on PATH; the plugin is an ES module')
    def test_06_no_contract_drift(self):
        data = {'cli': self.cli, 'v2': cs.v2_surface(), 'mcp': self.mcp,
                'plugin': self.plugin}
        findings, mcp, plugin, cli, plugin_paths = cs.compare(data, cs.MCP_TO_CLI)
        text = capture_report(data, findings, mcp, plugin, cli, plugin_paths)
        self.assertEqual(findings, [], 'contract drift:\n' + text)

    @unittest.skipUnless(NODE, 'node is not on PATH; the plugin is an ES module')
    def test_07_report_names_the_truth_source(self):
        data = {'cli': self.cli, 'v2': cs.v2_surface(), 'mcp': self.mcp,
                'plugin': self.plugin}
        findings, mcp, plugin, cli, plugin_paths = cs.compare(data, cs.MCP_TO_CLI)
        text = capture_report(data, findings, mcp, plugin, cli, plugin_paths)
        self.assertIn('truth source', text)
        self.assertIn('cli.py', text)
        print()
        print(text)


class Hint(unittest.TestCase):
    '''The bitness hint must name something the reader actually has.'''

    def test_14_a_checkout_without_the_runtime_says_how_to_get_it(self):
        # Measured on a fresh clone: the first KingDraw command answered
        # 'Run with the bundled 32-bit runtime: runtime/py32/python.exe', but
        # a clone has no runtime/ at all -- install.ps1 fetches it and it is
        # not committed. The reader was told to run a file they do not have.
        from chemdraw_tool import models
        with tempfile.TemporaryDirectory() as clone:
            open(os.path.join(clone, 'install.ps1'), 'w').close()
            hint = models.bitness_hint(clone)
            self.assertIn('install.ps1', hint)
            self.assertIn(models.PYTHON32_ENV, hint)
            self.assertNotIn('runtime/py32/python.exe', hint)
        # An installed layout (pip install .) has no install.ps1 either, so
        # the same hint cannot name it -- measured with a --target install,
        # which printed 'run install.ps1' for a file that was not shipped.
        with tempfile.TemporaryDirectory() as installed:
            hint = models.bitness_hint(installed)
            self.assertNotIn('install.ps1', hint)
            self.assertNotIn('runtime/py32/python.exe', hint)
            self.assertIn(models.PYTHON32_ENV, hint)
            self.assertIn('x86 DLL', hint)
        with tempfile.TemporaryDirectory() as full:
            os.makedirs(os.path.join(full, 'runtime', 'py32'))
            open(os.path.join(full, 'runtime', 'py32', 'python.exe'), 'wb').close()
            hint = models.bitness_hint(full)
            self.assertIn('runtime/py32/python.exe', hint)
            self.assertNotIn('install.ps1', hint)
    def test_15_an_unusable_env_variable_is_named(self):
        '''A wrong CHEMTOOL_PYTHON32 has to be named, not silently skipped.

        find_python32() drops an entry that is not a file and falls through to
        the bundled runtime, which is right when something else works. When
        nothing does, the reader has to learn their setting was the problem.
        '''
        from chemdraw_tool import models
        with tempfile.TemporaryDirectory() as empty:
            os.environ[models.PYTHON32_ENV] = os.path.join(empty, 'typo.exe')
            try:
                hint = models.bitness_hint(empty)
            finally:
                del os.environ[models.PYTHON32_ENV]
            self.assertIn(models.PYTHON32_ENV, hint)
            self.assertIn('is set to', hint)
            self.assertIn('not a file', hint)
        with tempfile.TemporaryDirectory() as real:
            real_exe = os.path.join(real, 'python32.exe')
            open(real_exe, 'wb').close()
            os.environ[models.PYTHON32_ENV] = real_exe
            try:
                hint = models.bitness_hint(real)
            finally:
                del os.environ[models.PYTHON32_ENV]
            self.assertNotIn('not a file', hint)


class Teeth(unittest.TestCase):
    '''The gate fails when it should: synthetic surfaces, then a mutated copy.'''

    @classmethod
    def setUpClass(cls):
        cls.cli = cs.cli_surface()

    def _plugin_tool(self, name, params, argv):
        return {'name': name, 'params': {k: {'type': 'string', 'required': False}
                                         for k in params},
                'calls': [{'channel': 'cd', 'argv': argv}], 'problems': []}

    def test_08_a_flag_the_cli_does_not_have_is_caught(self):
        plugin = [self._plugin_tool('chemdraw_read', ['format'],
                                    ['cd', 'read', '--nonsense', 'x'])]
        findings, *_ = cs.compare({'cli': self.cli, 'mcp': [], 'plugin': plugin},
                                  {})
        self.assertEqual([f['kind'] for f in findings], ['flag'])
        self.assertIn('--nonsense', findings[0]['detail'])

    def test_09_a_subcommand_that_does_not_exist_is_caught(self):
        plugin = [self._plugin_tool('chemdraw_ghost', [],
                                    ['cd', 'ghost', 'x'])]
        findings, *_ = cs.compare({'cli': self.cli, 'mcp': [], 'plugin': plugin},
                                  {})
        self.assertTrue(any(f['kind'] == 'path' for f in findings), findings)

    def test_10_a_required_cli_flag_the_plugin_never_passes_is_caught(self):
        cli = {k: {'flags': dict(v['flags']), 'positionals': list(v['positionals'])}
               for k, v in self.cli.items()}
        cli['identity']['flags']['--out'] = {'dest': 'out', 'required': True,
                                             'takes_value': True}
        plugin = [self._plugin_tool('chem_identity', ['smiles'],
                                    ['identity', '__SENT_smiles__'])]
        findings, *_ = cs.compare({'cli': cli, 'mcp': [], 'plugin': plugin}, {})
        self.assertTrue(any(f['kind'] == 'required' for f in findings), findings)

    def test_11_a_parameter_that_goes_nowhere_is_caught(self):
        plugin = [self._plugin_tool('chemdraw_read', ['bogusParam'],
                                    ['cd', 'read'])]
        findings, *_ = cs.compare({'cli': self.cli, 'mcp': [], 'plugin': plugin},
                                  {})
        self.assertTrue(any(f['kind'] == 'param' for f in findings), findings)

    @unittest.skipUnless(NODE, 'node is not on PATH; the plugin is an ES module')
    def test_12_a_mutated_copy_of_the_tree_fails_the_gate(self):
        '''Copy enough of the tree to run, rename one CLI flag, expect exit 1.'''
        tmp = tempfile.mkdtemp(prefix='cdt-contract-')
        try:
            for name in ('core', 'bin', 'dsh-plugin', 'tools'):
                shutil.copytree(os.path.join(ROOT, name), os.path.join(tmp, name),
                                ignore=shutil.ignore_patterns('__pycache__'))
            target = os.path.join(tmp, 'core', 'chemdraw_tool', 'cli.py')
            with open(target, 'r', encoding='utf-8') as handle:
                source = handle.read()
            self.assertIn("'--compare-to'", source)
            with open(target, 'w', encoding='utf-8', newline='') as handle:
                handle.write(source.replace("'--compare-to'", "'--compare'"))

            env = dict(os.environ)
            env['PYTHONIOENCODING'] = 'utf-8'
            proc = subprocess.run([sys.executable, os.path.join(tmp, 'tools', 'contract_sync.py')],
                                  cwd=tmp, capture_output=True, text=True,
                                  encoding='utf-8', errors='replace', env=env, timeout=180)
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            drift = re.sub(r'\s+', ' ', proc.stdout)
            self.assertIn('--compare-to', drift)
            self.assertIn('DRIFT', drift)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    def test_13_every_leaf_command_can_be_asked_for_json(self):
        '''The plugin appends --json to every call it makes.

        That is only safe while every leaf command accepts the flag. A new
        subcommand that forgot it would make the plugin's calls fail inside
        argparse, and the user would meet an E99 that reads like a broken
        CLI rather than a missing flag. cli.build_parser() adds the flag
        centrally for exactly this reason; this test keeps that wiring alive.
        '''
        leaves = sorted(path for path, info in self.cli.items()
                        if not info['children'])
        self.assertGreaterEqual(len(leaves), 18, leaves)
        missing = [path for path in leaves
                   if '--json' not in self.cli[path]['flags']]
        self.assertEqual(missing, [],
                         'leaf commands the plugin cannot ask for JSON: '
                         + ', '.join(missing))


class Envelope(unittest.TestCase):
    '''Every leaf command answers with the same envelope.

    Measured on this build: 18 of the 20 leaf commands answered
    {ok, channel, data, failure, degraded, elapsed_ms, warnings}, while
    `identity` and `doctor` answered a flat object with no `data` at all --
    the first two commands a newcomer runs. A caller that had learned the
    rule from any other command read payload['data'] and met KeyError.
    The fix added the envelope keys and kept the flat ones, so this test
    asserts both halves: the envelope is there, and nothing moved.
    '''

    @staticmethod
    def run_cli(argv):
        # ROOT is a str here, not a Path: `ROOT / 'bin'` raised TypeError inside
        # the first run of this test, which read like a CLI failure.
        proc = subprocess.run([sys.executable, os.path.join(ROOT, 'bin', 'cli.py')] + argv,
                              capture_output=True, text=True, encoding='utf-8',
                              cwd=ROOT)
        return json.loads(proc.stdout), proc.returncode

    def test_16_identity_answers_with_the_same_envelope(self):
        payload, rc = self.run_cli(['identity', 'CCO', '--json'])
        self.assertEqual(rc, 0)
        for key in ('ok', 'channel', 'data', 'degraded', 'elapsed_ms',
                    'warnings', 'evidence', 'evidence_note', 'failure',
                    'degrade_reason'):
            self.assertIn(key, payload)
        self.assertTrue(payload['ok'])
        # the flat keys the old shape taught callers to read are untouched
        self.assertEqual(payload['inchikey'], 'LFQSCWFLJHTTHZ-UHFFFAOYSA-N')
        self.assertEqual(payload['data']['inchikey'], payload['inchikey'])
        self.assertEqual(payload['channel'], 'rdkit')

    def test_17_a_bad_smiles_keeps_the_flat_keys_and_turns_ok_false(self):
        payload, rc = self.run_cli(['identity', 'not-a-molecule', '--json'])
        self.assertEqual(rc, 1)
        self.assertFalse(payload['ok'])
        self.assertIn('data', payload)
        self.assertIsNotNone(payload['failure'])
        self.assertIn('input', payload)

    def test_18_doctor_envelopes_each_channel(self):
        payload, rc = self.run_cli(['doctor', 'kd', '--json'])
        self.assertIn('data', payload)
        self.assertEqual(payload['ok'], bool(payload['available']))
        self.assertEqual(payload['data']['available'], payload['available'])
        # several channels stay an array (a single --json document either way)
        both, _ = self.run_cli(['doctor', 'all', '--no-start', '--json'])
        self.assertIsInstance(both, list)
        self.assertEqual([item['channel'] for item in both],
                         ['chemdraw', 'kingdraw'])
        for item in both:
            self.assertIn('data', item)
            self.assertEqual(item['ok'], bool(item['available']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
