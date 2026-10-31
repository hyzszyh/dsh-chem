'''The three examples are the first code a reader runs -- so they rot silently.

    python test/test_examples.py

draw_figure.py read data['width_px'], data['height_px'], data['width_mm'] and
data['dpi'] for as long as nobody looked, and all four had moved under it. The
script still exited 0 and still wrote a real 1922x1302 PNG; it just printed

    wrote phenol_acs_single_column.png - None x None px
          None mm at None dpi

No exception, no red test, nothing in any suite -- the only reader who would
notice is a newcomer who does not yet know what those numbers should be.
Examples are documentation that executes, so they get a gate like documentation:
run them and forbid the word None in the output.

ChemDraw and KingDraw are optional here. An example that says it cannot reach
an engine is reported as skipped, not passed: pretending a vendor check ran
would be worse than the bug this file exists to catch.
'''
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
EXAMPLES = os.path.join(ROOT, 'examples')

SKIP_MARKERS = (
    'cannot reach ChemDraw',
    'ChemDraw is not installed',
    'the bundled 32-bit interpreter is missing',
    'KingDraw home',
)

MISSING_ENGINE = re.compile(r'(cannot|not installed|is missing|not found)', re.I)


def _env():
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


def run_example(name, timeout=420):
    '''Run one example; return (rc, stdout+stderr, skip_reason or None).'''
    proc = subprocess.run([sys.executable, os.path.join(EXAMPLES, name)],
                          cwd=ROOT, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', env=_env(),
                          timeout=timeout)
    blob = (proc.stdout or '') + (proc.stderr or '')
    assert 'Traceback (most recent call last)' not in blob, \
        'an example raised instead of explaining:\n' + blob[-800:]
    if proc.returncode != 0:
        tail = '\n'.join(blob.strip().splitlines()[-3:])
        for marker in SKIP_MARKERS:
            if marker in blob:
                return proc.returncode, blob, marker
        if MISSING_ENGINE.search(tail) and ('hint:' in tail or 'not installed' in tail):
            return proc.returncode, blob, tail
    return proc.returncode, blob, None


class Examples(unittest.TestCase):
    def _check(self, name, timeout=420):
        rc, blob, skip = run_example(name, timeout)
        if skip:
            self.skipTest('%s needs an engine this machine lacks: %s'
                          % (name, str(skip).splitlines()[0][:80]))
        self.assertEqual(rc, 0, name + ' failed:\n' + blob[-800:])
        # The whole point: a moved key prints None, and None is never a fact.
        self.assertNotIn('None', blob,
                         name + ' printed None -- a result key moved under it:\n'
                         + blob[-800:])
        return blob

    def test_01_batch_identity_reports_real_identities(self):
        blob = self._check('batch_identity.py', timeout=180)
        self.assertIn('BSYNRYMUTXBXSQ-UHFFFAOYSA-N', blob)
        self.assertIn('C9H8O4', blob)

    def test_02_draw_figure_reports_pixel_and_paper_size(self):
        blob = self._check('draw_figure.py')
        found = re.search(r'(\d+) x (\d+) px, (\d+) dpi, (\w+) mode', blob)
        self.assertIsNotNone(found, 'the figure line lost its facts:\n' + blob[-600:])
        width_px, height_px = int(found.group(1)), int(found.group(2))
        self.assertGreater(width_px, 100)
        self.assertGreater(height_px, 100)
        mm = re.search(r'([\d.]+) mm wide on paper', blob)
        self.assertIsNotNone(mm, blob[-600:])
        self.assertGreater(float(mm.group(1)), 0.0)
        # The example asks for 85 mm at 1200 dpi and this build cannot deliver
        # that pair (measured cap: 1922 px wide). It now reads the ceiling back
        # out of the first answer and re-exports at that dpi, so the file it
        # leaves really is 85 mm -- within rounding, not 40.7 mm.
        self.assertAlmostEqual(float(mm.group(1)), 85.0, delta=1.7,
                               msg='the example left a figure that is not 85 mm '
                                   'wide:\n' + blob[-600:])
        self.assertIn('dpi', blob)

    def test_03_crosscheck_batch_gets_three_engines_to_agree(self):
        blob = self._check('crosscheck_batch.py')
        self.assertIn('agree=True', blob)
        agree = blob.count('agree=True')
        self.assertGreaterEqual(agree, 2, blob[-600:])

    def test_04_no_example_silently_swallows_a_key(self):
        '''Every data.get() key an example reads must be a key some Result has.

        This is the cheap half of the same bug: the run-time check above only
        sees the lines that executed. Here the source is read, so a key used
        on an untaken branch is still caught.
        '''
        import ast
        known = set()
        for sub in ('adapters', '.'):
            folder = os.path.join(ROOT, 'core', 'chemdraw_tool', sub)
            for entry in sorted(os.listdir(folder)):
                if not entry.endswith('.py'):
                    continue
                with open(os.path.join(folder, entry), encoding='utf-8') as handle:
                    try:
                        tree = ast.parse(handle.read())
                    except SyntaxError:
                        continue
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        known.add(node.value)
        used = set()
        for entry in sorted(os.listdir(EXAMPLES)):
            if not entry.endswith('.py'):
                continue
            with open(os.path.join(EXAMPLES, entry), encoding='utf-8') as handle:
                source = handle.read()
            used.update(re.findall(r"\.get\(['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\)", source))
        unknown = sorted(key for key in used if key not in known)
        self.assertEqual(unknown, [],
                         'examples read keys no module ever produces: '
                         + ', '.join(unknown))


if __name__ == '__main__':
    unittest.main(verbosity=2)