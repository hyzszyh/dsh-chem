'''Three engines, one molecule: rdkit, KingDraw and ChemDraw agree.

This is the end-to-end proof that the two channels are independent and that
each one really re-derives the structure: every case below draws in a real
ChemDraw COM instance and crosses into runtime/py32/python.exe for the x86
KingDraw DLL. InChIKeys are the unit of truth on purpose - ChemDraw rewrites
what it reads back, so comparing SMILES text would fail on aspirin and
caffeine even though both round-trip perfectly.
'''

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = os.path.join(ROOT, 'core')
BIN = os.path.join(ROOT, 'bin')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

from chemdraw_tool import crosscheck as xc  # noqa: E402

PY = sys.executable

# name: (input SMILES, the InChIKey all three engines must produce)
MOLECULES = {
    'phenol': ('c1ccccc1O', 'ISWSIDIOOBJBQZ-UHFFFAOYSA-N'),
    'aspirin': ('CC(=O)Oc1ccccc1C(=O)O', 'BSYNRYMUTXBXSQ-UHFFFAOYSA-N'),
    'caffeine': ('Cn1c(=O)c2c(ncn2C)n(C)c1=O', 'RYYVLZVUVIJVGH-UHFFFAOYSA-N'),
}
ENGINES = ('rdkit', 'kingdraw', 'chemdraw')


def _env() -> dict:
    env = dict(os.environ)
    env['PYTHONPATH'] = CORE
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def kill_chemdraw() -> None:
    subprocess.run('taskkill /F /IM ChemDraw.exe', shell=True,
                   capture_output=True, text=True)


def chemdraw_pids() -> list:
    out = subprocess.run('tasklist /FI "IMAGENAME eq ChemDraw.exe"', shell=True,
                         capture_output=True, text=True, errors='replace').stdout
    return [line for line in out.splitlines() if 'ChemDraw.exe' in line]


def run_cli(*args, timeout=300):
    # The default output is the human summary; this suite parses JSON.
    argv = list(args) if '--json' in args else list(args) + ['--json']
    return subprocess.run([PY, os.path.join(BIN, 'cli.py')] + argv,
                          capture_output=True, text=True, encoding='utf-8',
                          errors='replace', env=_env(), timeout=timeout)


def _parse_json(text: str) -> dict:
    '''The emitted envelope is pretty-printed, so parse the whole stream.'''
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        for line in reversed(stripped.splitlines()):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        raise


class CrosscheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.maxsize <= 2 ** 32:
            raise unittest.SkipTest('ChemDraw COM needs a 64-bit interpreter')
        kill_chemdraw()
        cls._cache = {}

    @classmethod
    def tearDownClass(cls):
        xc.shutdown()
        kill_chemdraw()

    @classmethod
    def single(cls, smiles: str):
        '''One crosscheck per SMILES; several tests read the same pipeline run.'''
        if smiles not in cls._cache:
            cls._cache[smiles] = xc.crosscheck(smiles)
        return cls._cache[smiles]

    # -- the headline promise ---------------------------------------------
    def test_01_three_engines_agree_on_every_molecule(self):
        for name, (smiles, expected) in MOLECULES.items():
            with self.subTest(molecule=name):
                res = self.single(smiles)
                self.assertTrue(res.ok, res.to_dict())
                data = res.data
                self.assertFalse(res.degraded,
                                 'an engine dropped out: %s' % res.degrade_reason)
                self.assertTrue(data['agree'], json.dumps(data['mismatch']))
                self.assertEqual(data['basis'], xc.BASIS_INCHIKEY)
                self.assertEqual(sorted(data['compared']), ['chemdraw', 'kingdraw'])
                self.assertEqual(data['reference']['inchikey'], expected)
                for engine in ENGINES:
                    record = data['engines'][engine]
                    self.assertTrue(record['ok'],
                                    '%s failed: %s' % (engine, record['detail']))
                    self.assertEqual(record['inchikey'], expected,
                                     '%s derived a different molecule' % engine)
                    self.assertEqual(record['basis'], xc.BASIS_INCHIKEY)

    def test_02_chemdraw_rewrites_smiles_but_keeps_the_molecule(self):
        '''Why the comparison is by InChIKey and never by SMILES text.'''
        rewritten = 0
        for name in ('aspirin', 'caffeine'):
            smiles = MOLECULES[name][0]
            record = self.single(smiles).data['engines']['chemdraw']
            if record['smiles'] != smiles:
                rewritten += 1
            self.assertEqual(record['inchikey'], MOLECULES[name][1])
        self.assertGreaterEqual(rewritten, 1,
                                'ChemDraw used to reorder these; if it no longer '
                                'does, the InChIKey comparison is still right')
        aspirin = self.single(MOLECULES['aspirin'][0]).data['engines']['chemdraw']
        self.assertNotEqual(aspirin['smiles'], MOLECULES['aspirin'][0])
        self.assertEqual(aspirin['smiles'], 'CC(Oc1c(C(O)=O)cccc1)=O')

    def test_03_same_molecule_two_spellings(self):
        res = xc.compare('c1ccccc1O', 'Oc1ccccc1')
        self.assertTrue(res.ok, res.to_dict())
        self.assertTrue(res.data['agree'])
        self.assertEqual(res.data['basis'], xc.BASIS_INCHIKEY)
        self.assertTrue(res.data['corroborated'])
        self.assertEqual(res.data['mismatch'], [])

    def test_04_different_molecules_disagree(self):
        res = xc.compare('c1ccccc1O', 'CC(=O)O')
        self.assertTrue(res.ok, 'the check ran; the answer is no')
        self.assertFalse(res.data['agree'])
        self.assertEqual(len(res.data['mismatch']), 2)
        self.assertEqual(res.data['a']['reference']['inchikey'],
                         MOLECULES['phenol'][1])
        self.assertNotEqual(res.data['a']['reference']['inchikey'],
                            res.data['b']['reference']['inchikey'])

    def test_05_rdkit_alone_still_answers(self):
        '''A laptop with neither vendor app is a supported state.'''
        res = xc.crosscheck('c1ccccc1O', engines=('rdkit',))
        self.assertTrue(res.ok)
        self.assertTrue(res.degraded)
        self.assertIn('single engine', res.degrade_reason)
        self.assertTrue(res.data['agree'])
        self.assertEqual(res.data['compared'], [])
        self.assertTrue(any('only rdkit' in w for w in res.warnings))

    def test_06_unparseable_smiles_fails_loudly(self):
        res = xc.crosscheck('not-a-smiles')
        self.assertFalse(res.ok)
        self.assertEqual(res.failure.code, 'E06')
        self.assertEqual(res.failure.stage, 'crosscheck')

    def test_07_leaving_out_the_reference_is_refused(self):
        res = xc.crosscheck('c1ccccc1O', engines=('kingdraw',))
        self.assertFalse(res.ok)
        self.assertIn('reference', res.failure.message)

    # -- the shipped surfaces ---------------------------------------------
    def test_08_cli_reports_agreement_in_both_formats(self):
        done = run_cli('crosscheck', 'c1ccccc1O', '--json')
        self.assertEqual(done.returncode, 0, done.stderr[-500:])
        payload = _parse_json(done.stdout)
        self.assertTrue(payload['ok'])
        self.assertTrue(payload['data']['agree'])
        human = run_cli('crosscheck', 'c1ccccc1O')
        self.assertEqual(human.returncode, 0, human.stderr[-500:])
        self.assertIn('agree', human.stdout)
        self.assertIn(MOLECULES['phenol'][1], human.stdout)
        for engine in ('rdkit', 'kingdraw', 'chemdraw'):
            self.assertIn(engine, human.stdout)

    def test_09_cli_exit_code_marks_a_disagreement(self):
        done = run_cli('crosscheck', 'c1ccccc1O', '--compare-to', 'CC(=O)O', '--json')
        self.assertEqual(done.returncode, 2, done.stdout[-400:] + done.stderr[-200:])
        self.assertFalse(_parse_json(done.stdout)['data']['agree'])

    def test_10_mcp_exposes_the_same_check(self):
        proc = subprocess.Popen([PY, '-m', 'chemdraw_tool.mcp_server'],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=ROOT, env=_env(),
                                text=True, encoding='utf-8', errors='replace')
        try:
            def send(payload):
                proc.stdin.write(json.dumps(payload) + '\n')
                proc.stdin.flush()
                return json.loads(proc.stdout.readline())

            hello = send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                          'params': {'protocolVersion': '2024-11-05',
                                     'capabilities': {},
                                     'clientInfo': {'name': 'test', 'version': '0'}}})
            self.assertEqual(hello['result']['serverInfo']['name'], 'chem-draw-tool')
            proc.stdin.write(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}) + '\n')
            proc.stdin.flush()
            listed = send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list', 'params': {}})
            names = [tool['name'] for tool in listed['result']['tools']]
            self.assertIn('chem_crosscheck', names)
            self.assertIn('kingdraw_smiles_to_mol', names)
            self.assertIn('chemdraw_draw', names)
            called = send({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
                           'params': {'name': 'chem_crosscheck',
                                      'arguments': {'smiles': 'c1ccccc1O'}}})
            self.assertFalse(called['result'].get('isError'), called['result'])
            body = json.loads(called['result']['content'][0]['text'])
            self.assertTrue(body['ok'], body)
            self.assertTrue(body['data']['agree'])
            self.assertEqual(body['data']['engines']['kingdraw']['inchikey'],
                             MOLECULES['phenol'][1])
        finally:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
            for stream in (proc.stdout, proc.stderr):
                try:
                    stream.close()
                except Exception:
                    pass

    def test_11_nothing_is_left_running(self):
        xc.shutdown()
        # Quit is asynchronous: the COM server tears down after the call
        # returns, so give the process a moment to disappear.
        for _ in range(20):
            if not chemdraw_pids():
                break
            time.sleep(0.5)
        self.assertEqual(chemdraw_pids(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
