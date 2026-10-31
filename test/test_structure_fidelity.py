'''Both channels must hand a structure back unchanged -- compared by InChIKey.

    python test/test_structure_fidelity.py

Why this exists: identity, doctor, layouts and figures are all downstream of one
claim -- that a SMILES put into ChemDraw or KingDraw comes back as the same
molecule. Nothing tested that claim end to end. A channel can render a picture
that looks right and still drop a stereocentre, a charge or an isotope, and no
layout test would notice: the drawing is still a drawing.

Measured 2026-10-29, this installation: 12/12 on both channels, including the
two alanines (S vs R), the E/Z pair, an anion, a cation, a deuterium label, a
four-stereocentre sugar and single-atom water. ChemDraw reorders the SMILES it
reads back, so the comparison is the InChIKey, never the string.
'''
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))

from rdkit import Chem, RDLogger  # noqa: E402
from rdkit.Chem import inchi  # noqa: E402

RDLogger.DisableLog('rdApp.*')

PY32 = os.path.join(ROOT, 'runtime', 'py32', 'python.exe')
CLI = os.path.join(ROOT, 'bin', 'cli.py')

# Every one of these is here for a reason; a plain alkane would prove nothing.
MOLECULES = [
    ('ethanol',           'CCO'),
    ('L-alanine',         'C[C@@H](N)C(=O)O'),      # tetrahedral stereo, S
    ('D-alanine',         'C[C@H](N)C(=O)O'),       # the other enantiomer
    ('(E)-2-butene',      'C/C=C/C'),               # double-bond geometry
    ('(Z)-2-butene',      'C/C=C\\C'),              # and its opposite
    ('acetate anion',     'CC(=O)[O-]'),            # formal charge, minus
    ('trimethylammonium', 'C[N+](C)(C)C'),          # formal charge, plus
    ('deuteromethanol',   '[2H]OC'),                # isotope layer
    ('caffeine',          'Cn1c(=O)c2c(ncn2C)n(C)c1=O'),  # fused heteroaromatic
    ('aspirin',           'CC(=O)Oc1ccccc1C(=O)O'),
    ('glucose',           'OC[C@H]1O[C@@H](O)[C@H](O)[C@@H](O)[C@@H]1O'),
    ('water',             'O'),                     # single heavy atom
]


def key_of(smiles):
    '''The InChIKey of a SMILES, or None when RDKit cannot read it.'''
    molecule = Chem.MolFromSmiles(smiles or '')
    if molecule is None:
        return None
    return inchi.MolToInchiKey(molecule)


def _text_of(payload):
    '''The answer text of an envelope, whichever way the adapter wrapped it.'''
    data = payload.get('data')
    if isinstance(data, dict):
        data = data.get('text')
    lines = str(data or '').strip().splitlines()
    return lines[-1] if lines else ''


class KingDrawFidelity(unittest.TestCase):
    '''SMILES -> molfile -> SMILES, through the 32-bit native DLL.'''

    def test_every_molecule_survives_the_round_trip(self):
        if not os.path.isfile(PY32):
            self.skipTest('the bundled 32-bit runtime is missing')
        wrong, checked = [], 0
        for name, smiles in MOLECULES:
            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, 'x.mol')
                made = subprocess.run(
                    [PY32, CLI, 'kd', 'mol', smiles, '--out', path, '--json'],
                    cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=120)
                back = subprocess.run(
                    [PY32, CLI, 'kd', 'smiles', path, '--json'],
                    cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                    errors='replace', timeout=120)
            if made.returncode != 0 or back.returncode != 0:
                wrong.append('%s: a call failed (kd mol rc=%d, kd smiles rc=%d)'
                             % (name, made.returncode, back.returncode))
                continue
            got = key_of(_text_of(json.loads(back.stdout)))
            checked += 1
            if got != key_of(smiles):
                wrong.append('%s: expected %s, got %s' % (name, key_of(smiles), got))
        # A loop that compared nothing would also produce an empty failure
        # list, so the count has to be asserted or the test can pass vacuously.
        self.assertEqual(checked, len(MOLECULES), 'not every molecule was compared')
        self.assertFalse(wrong, 'the KingDraw channel changed these structures:\n  '
                         + '\n  '.join(wrong))


    def test_both_spellings_of_the_input_produce_the_same_file(self):
        '''kd mol / kd smiles take the input positionally, but kd formula,
        kd to3d and kd layout take --smiles / --mol. Measured: guessing the
        flag form cost three failed attempts while this file was written.'''
        if not os.path.isfile(PY32):
            self.skipTest('the bundled 32-bit runtime is missing')
        with tempfile.TemporaryDirectory() as folder:
            flat = os.path.join(folder, 'flat.mol')
            flagged = os.path.join(folder, 'flagged.mol')
            for arguments in ([PY32, CLI, 'kd', 'mol', 'CCO', '--out', flat],
                              [PY32, CLI, 'kd', 'mol', '--smiles', 'CCO',
                               '--out', flagged]):
                done = subprocess.run(arguments, cwd=ROOT, capture_output=True,
                                      text=True, encoding='utf-8',
                                      errors='replace', timeout=120)
                self.assertEqual(done.returncode, 0, done.stderr[-300:])
            with open(flat, 'rb') as handle:
                first = handle.read()
            with open(flagged, 'rb') as handle:
                second = handle.read()
        self.assertEqual(first, second, 'the two spellings must reach the same molfile')


class ChemDrawFidelity(unittest.TestCase):
    '''SMILES -> drawn document -> SMILES, through COM.'''

    def test_every_molecule_survives_draw_and_read(self):
        from chemdraw_tool.adapters.cd_com import ChemDrawChannel
        channel = ChemDrawChannel()
        opened = channel.connect()
        if not opened.ok:
            self.skipTest('ChemDraw is not reachable: %s' % opened.failure.message)
        wrong, checked = [], 0
        try:
            for name, smiles in MOLECULES:
                drawn = channel.draw_smiles(smiles)
                if not drawn.ok:
                    wrong.append('%s: draw failed (%s)' % (name, drawn.failure.message))
                    continue
                read = channel.read_current('smiles')
                if not read.ok:
                    wrong.append('%s: read failed (%s)' % (name, read.failure.message))
                    continue
                got = key_of(_text_of(read.to_dict() if hasattr(read, 'to_dict') else read.data))
                checked += 1
                if got != key_of(smiles):
                    wrong.append('%s: expected %s, got %s' % (name, key_of(smiles), got))
        finally:
            channel.close()
        self.assertEqual(checked, len(MOLECULES), 'not every molecule was compared')
        self.assertFalse(wrong, 'the ChemDraw channel changed these structures:\n  '
                         + '\n  '.join(wrong))


if __name__ == '__main__':
    unittest.main(verbosity=2)