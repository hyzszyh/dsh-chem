'''Probe 12: can we write a .king (plain-text Ctab) that supKingToJson reads back?

Format learned from D:/tool/KingDraw/Cyclohexane.king:
  Begin Header / KingDraw V2.2 / 20180420 / End Header
  Begin Device ... End Device
  Begin SysConfig ... End SysConfig
  Begin Ctab
  Begin Atom
  <i> <elem> <x> <y> #ff000000 HCount=<n>
  End Atom
  Begin Bond
  <i> <order> <a1> <a2> 0 #ff000000
  End Bond
  End Ctab
  END
'''
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))
from chemdraw_tool.adapters import kd_native  # noqa: E402

TEMPLATE_DEVICE = ('device=[{"device":"3","version":"1.0.2_beta"}]')
SYS_CONFIG = ('{"DrawingSettings":"{\\"Id_Renamed\\":0,\\"documentType\\":0,'
              '\\"proof\\":false,\\"zoomer\\":false,\\"fixedLength\\":\\"0.78\\",'
              '\\"spacing\\":12,\\"lineWidth\\":\\"0.0312\\",\\"boldWidth\\":\\"0.0936\\",'
              '\\"marginWidth\\":\\"0.0312\\",\\"hashSpacing\\":\\"0.0624\\",'
              '\\"chainsAngle\\":120,\\"atomFontName\\":\\"Arial\\",\\"atomFontStyle\\":1,'
              '\\"atomFontSize\\":10,\\"textFontName\\":\\"Arial\\",\\"textFontStyle\\":1,'
              '\\"textFontSize\\":10,\\"isNormal\\":false}"}')


def parse_molblock(text):
    lines = text.splitlines()
    idx = lines.index('M  END') if 'M  END' in lines else len(lines)
    counts = lines[3]
    n_atoms = int(counts[0:3])
    n_bonds = int(counts[3:6])
    atoms = []
    for line in lines[4:4 + n_atoms]:
        x = float(line[0:10])
        y = float(line[10:20])
        elem = line[31:34].strip()
        atoms.append((elem, x, y))
    bonds = []
    base = 4 + n_atoms
    for line in lines[base:base + n_bonds]:
        a1 = int(line[0:3])
        a2 = int(line[3:6])
        order = int(line[6:9])
        bonds.append((order, a1, a2))
    return atoms, bonds


def write_king(atoms, bonds, hcounts=None):
    out = ['Begin Header', 'KingDraw V2.2', '20180420', 'End Header',
           'Begin Device', TEMPLATE_DEVICE, 'End Device',
           'Begin SysConfig', SYS_CONFIG, 'End SysConfig',
           'Begin Ctab', 'Begin Atom']
    for i, (elem, x, y) in enumerate(atoms, 1):
        extra = ''
        if hcounts and i - 1 < len(hcounts) and hcounts[i - 1] is not None:
            extra = ' HCount=%d' % hcounts[i - 1]
        out.append('%d %s %.4f %.4f #ff000000%s' % (i, elem, x, y, extra))
    out.append('End Atom')
    out.append('Begin Bond')
    for i, (order, a1, a2) in enumerate(bonds, 1):
        out.append('%d %d %d %d 0 #ff000000' % (i, order, a1, a2))
    out.append('End Bond')
    out.append('End Ctab')
    out.append('END')
    return '\n'.join(out) + '\n'


def roundtrip(name, smiles):
    mol = kd_native.smiles_to_mol(smiles)
    if not mol.ok:
        print('%-10s smiles_to_mol failed: %s' % (name, mol.failure.code))
        return False
    atoms, bonds = parse_molblock(mol.data['text'])
    king = write_king(atoms, bonds)
    path = os.path.join(HERE, 'out', 'writer_%s.king' % name)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(king)
    r = kd_native.sup_king_to_json(open(path, 'rb').read())
    if not r.ok:
        print('%-10s supKingToJson failed: %s %s' % (name, r.failure.code, r.failure.detail[:100]))
        return False
    doc = json.loads(r.data['text'])
    data = doc.get('data') or {}
    nodes = data.get('nodes') or []
    bonds_back = data.get('bonds') or []
    types = [n.get('type') for n in nodes]
    want = [a[0] for a in atoms]
    ok = (len(nodes) == len(atoms) and len(bonds_back) == len(bonds) and types == want)
    print('%-10s atoms=%-2d nodes=%-2d bonds=%-2d/%-2d types=%r want=%r %s' % (
        name, len(atoms), len(nodes), len(bonds), len(bonds_back), types, want,
        'OK' if ok else 'MISMATCH'))
    if bonds_back and len(bonds_back) != len(bonds):
        print('    bonds back:', json.dumps(bonds_back[:3], ensure_ascii=False)[:200])
    if nodes and nodes[0].get('type') != want[0]:
        print('    node0:', json.dumps(nodes[0], ensure_ascii=False)[:200])
    return ok


def main():
    cases = [('benzene', 'c1ccccc1'), ('phenol', 'c1ccccc1O'),
             ('aspirin', 'CC(=O)Oc1ccccc1C(=O)O'), ('ethanol', 'CCO')]
    results = [roundtrip(n, s) for n, s in cases]
    print('passed %d/%d' % (sum(1 for r in results if r), len(results)))
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
