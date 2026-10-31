'''Probe 13: molblock (V2000/V3000) -> .king text -> supKingToJson round trip.'''
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))
from chemdraw_tool.adapters import kd_native  # noqa: E402

DEVICE = 'device=[{"device":"3","version":"1.0.2_beta"}]'
SYS_CONFIG = ('{"DrawingSettings":"{\\"Id_Renamed\\":0,\\"documentType\\":0,'
              '\\"proof\\":false,\\"zoomer\\":false,\\"fixedLength\\":\\"0.78\\",'
              '\\"spacing\\":12,\\"lineWidth\\":\\"0.0312\\",\\"boldWidth\\":\\"0.0936\\",'
              '\\"marginWidth\\":\\"0.0312\\",\\"hashSpacing\\":\\"0.0624\\",'
              '\\"chainsAngle\\":120,\\"atomFontName\\":\\"Arial\\",\\"atomFontStyle\\":1,'
              '\\"atomFontSize\\":10,\\"textFontName\\":\\"Arial\\",\\"textFontStyle\\":1,'
              '\\"textFontSize\\":10,\\"isNormal\\":false}"}')


def parse_molblock(text):
    '''Atoms [(elem, x, y)], bonds [(order, a1, a2)] from V2000 or V3000.'''
    lines = [ln.rstrip('\r') for ln in text.splitlines()]
    atoms, bonds = [], []
    if any('V3000' in ln for ln in lines[:6]):
        in_atoms = in_bonds = False
        for line in lines:
            s = line.strip()
            if not s.startswith('M  V30'):
                continue
            body = s[6:].strip()
            if body.startswith('BEGIN ATOM'):
                in_atoms, in_bonds = True, False
                continue
            if body.startswith('END ATOM'):
                in_atoms = False
                continue
            if body.startswith('BEGIN BOND'):
                in_atoms, in_bonds = False, True
                continue
            if body.startswith('END BOND'):
                in_bonds = False
                continue
            parts = body.split()
            if in_atoms and len(parts) >= 5:
                atoms.append((parts[1], float(parts[2]), float(parts[3])))
            elif in_bonds and len(parts) >= 4:
                bonds.append((int(parts[1]), int(parts[2]), int(parts[3])))
        return atoms, bonds
    counts = lines[3]
    n_atoms, n_bonds = int(counts[0:3]), int(counts[3:6])
    for line in lines[4:4 + n_atoms]:
        atoms.append((line[31:34].strip(), float(line[0:10]), float(line[10:20])))
    for line in lines[4 + n_atoms:4 + n_atoms + n_bonds]:
        bonds.append((int(line[6:9]), int(line[0:3]), int(line[3:6])))
    return atoms, bonds


def write_king(atoms, bonds):
    out = ['Begin Header', 'KingDraw V2.2', '20180420', 'End Header',
           'Begin Device', DEVICE, 'End Device',
           'Begin SysConfig', SYS_CONFIG, 'End SysConfig',
           'Begin Ctab', 'Begin Atom']
    for i, (elem, x, y) in enumerate(atoms, 1):
        out.append('%d %s %.4f %.4f #ff000000' % (i, elem, x, y))
    out.append('End Atom')
    out.append('Begin Bond')
    for i, (order, a1, a2) in enumerate(bonds, 1):
        out.append('%d %d %d %d 0 #ff000000' % (i, order, a1, a2))
    out.append('End Bond')
    out.append('End Ctab')
    out.append('END')
    return '\n'.join(out) + '\n'


def roundtrip(name, smiles, expect_atoms):
    mol = kd_native.smiles_to_mol(smiles)
    if not mol.ok:
        print('%-9s smiles_to_mol failed %s' % (name, mol.failure.code))
        return False
    atoms, bonds = parse_molblock(mol.data['text'])
    path = os.path.join(HERE, 'out', 'writer_%s.king' % name)
    with open(path, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(write_king(atoms, bonds))
    r = kd_native.sup_king_to_json(open(path, 'rb').read())
    if not r.ok or not atoms:
        print('%-9s FAIL atoms=%d ok=%r %s' % (name, len(atoms), r.ok,
                                               r.failure.detail[:80] if r.failure else ''))
        return False
    data = (json.loads(r.data['text']).get('data') or {})
    nodes, bonds_back = data.get('nodes') or [], data.get('bonds') or []
    types = [n.get('type') for n in nodes]
    want = [a[0] for a in atoms]
    ok = len(nodes) == expect_atoms and len(nodes) == len(atoms) and types == want \
        and len(bonds_back) == len(bonds)
    print('%-9s atoms=%-2d nodes=%-2d bonds=%-2d/%-2d types=%r %s' % (
        name, len(atoms), len(nodes), len(bonds), len(bonds_back), types,
        'OK' if ok else 'MISMATCH'))
    if not ok:
        print('   want:', want, '| node0:', json.dumps(nodes[0], ensure_ascii=False)[:140] if nodes else None)
    return ok


def main():
    cases = [('benzene', 'c1ccccc1', 6), ('phenol', 'c1ccccc1O', 7),
             ('aspirin', 'CC(=O)Oc1ccccc1C(=O)O', 13), ('ethanol', 'CCO', 3)]
    results = [roundtrip(*c) for c in cases]
    print('passed %d/%d' % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
