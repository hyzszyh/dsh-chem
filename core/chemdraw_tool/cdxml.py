'''Minimal CDXML writer.

RDKit's Python bindings expose a CDXML reader in C++ only, so we build the
document ourselves: 2D coordinates from RDKit, then a page/fragment tree of
atoms and bonds that ChemDraw accepts.

Format notes (verified against ChemDraw 26): a CDXML page holds fragment nodes;
each atom is n with Element = atomic number and p = 'x y' in points; each bond
is b with B and E holding the two atom ids and Order holding the bond order.

CDXML does not name bonds the way the rest of chemistry tooling does. Writing
B as the bond order with p0/p1 atom references is the intuitive guess and it
fails silently: ChemDraw inserts zero atoms and raises nothing. This docstring
used to describe that wrong shape while the code below did it right, which is
the worst combination - anyone copying the prose reproduced the bug.
'''

from __future__ import annotations

from typing import Optional

BOND_LENGTH = 14.4  # ChemDraw default, in points
MARGIN = 30.0


def _esc(text: str) -> str:
    return (str(text).replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').replace('"', '&quot;'))


def build_cdxml(mol, name: str = 'molecule', scale: float = BOND_LENGTH) -> str:
    '''Render an RDKit molecule (needs 2D coords) as a CDXML string.'''
    from rdkit.Chem import AllChem

    if mol is None:
        raise ValueError('mol is None')
    if mol.GetNumConformers() == 0 or not mol.GetConformer().Is3D():
        AllChem.Compute2DCoords(mol)
    conf = mol.GetConformer()
    n = mol.GetNumAtoms()

    xs = [conf.GetAtomPosition(i).x for i in range(n)]
    ys = [conf.GetAtomPosition(i).y for i in range(n)]
    minx, maxx = min(xs), max(xs)
    miny, maxy = min(ys), max(ys)

    atoms = []
    for i in range(n):
        atom = mol.GetAtomWithIdx(i)
        x = (xs[i] - minx) * scale + MARGIN
        y = (maxy - ys[i]) * scale + MARGIN
        attrs = ['id="%d"' % (i + 1), 'p="%.2f %.2f"' % (x, y), 'Element="%d"' % atom.GetAtomicNum()]
        charge = atom.GetFormalCharge()
        if charge:
            attrs.append('Charge="%d"' % charge)
        isotope = atom.GetIsotope()
        if isotope:
            attrs.append('Isotope="%d"' % isotope)
        atoms.append('      <n ' + ' '.join(attrs) + '/>')

    # CDXML names bonds differently from everything else in chemistry tooling:
    # B and E hold the two atom ids, and Order holds the bond order. Writing
    # B as a bond order with p0/p1 atom references (the intuitive guess) makes
    # ChemDraw insert zero atoms with no error at all, which is how the first
    # version of this file failed. Aromatic bonds must also be kekulised first:
    # Order="1.5" alone is silently downgraded to a single bond.
    from rdkit import Chem
    kekule = Chem.Mol(mol)
    try:
        Chem.Kekulize(kekule, clearAromaticFlags=True)
    except Exception:
        kekule = mol

    bonds = []
    for k, bond in enumerate(kekule.GetBonds()):
        order = int(round(bond.GetBondTypeAsDouble()))
        attrs = [
            'id="%d"' % (n + k + 1),
            'B="%d"' % (bond.GetBeginAtomIdx() + 1),
            'E="%d"' % (bond.GetEndAtomIdx() + 1),
            'Order="%d"' % order,
        ]
        bonds.append('      <b ' + ' '.join(attrs) + '/>')

    width = (maxx - minx) * scale + 2 * MARGIN
    height = (maxy - miny) * scale + 2 * MARGIN

    head = [
        '<?xml version="1.0" encoding="UTF-8" ?>',
        '<CDXML CreationProgram="chem-draw-tool" Name="%s">' % _esc(name),
        '  <colortable>',
        '    <color r="1" g="1" b="1"/>',
        '  </colortable>',
        '  <fonttable>',
        '    <font id="3" charset="iso-8859-1" name="Arial"/>',
        '  </fonttable>',
        '  <page id="1" BoundingBox="0 0 %.2f %.2f" Width="%.2f" Height="%.2f"' % (width, height, width, height),
        '        BondLength="%.2f" LabelFont="3" LabelSize="10">' % BOND_LENGTH,
        '    <fragment id="2">',
    ]
    tail = ['    </fragment>', '  </page>', '</CDXML>', '']
    return '\n'.join(head + atoms + bonds + tail)


def write_cdxml(mol, path: str, name: Optional[str] = None) -> str:
    '''Write a CDXML file and return the path.'''
    import os
    text = build_cdxml(mol, name or os.path.basename(path))
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text)
    return path