"""Reaction schemes: atom mapping, RXN block, and one laid-out CDXML page.

Three pieces, in the order they fail:

1. Mapping is a fact about atoms, so RDKit proves it. Every product atom either
   matches a reactant atom exactly (same element, charge, hydrogen count, degree
   and neighbour elements) or is reported as inferred. Ambiguity is counted, not
   hidden: two quoted atoms with identical signatures are indistinguishable, and
   the caller is told how many were inferred.
2. The RXN block is the interchange format other tools read; atom map numbers
   travel in the molblock columns.
3. The page is CDXML this build accepts: fragments at explicit coordinates, an
   arrow graphic, and a conditions text. Measured: `GraphicType="Arrow"` alone
   draws nothing, `GraphicType="Line" ArrowType="FullHead"` also draws nothing,
   and `<graphic GraphicType="Arrow" ArrowType="FullHead">` draws the arrow.
"""

SCALE = 14.4
MARGIN = 20.0
GAP = 34.0
ARROW = 64.0


def split(reaction_smiles: str):
    '''Split 'A.B>>C.D' into two lists, refusing anything that is not a reaction.'''
    text = (reaction_smiles or '').strip()
    if '>>' not in text:
        raise ValueError('a reaction needs the form A.B>>C.D')
    left, right = text.split('>>', 1)
    reactants = [part.strip() for part in left.split('.') if part.strip()]
    products = [part.strip() for part in right.split('.') if part.strip()]
    if not reactants or not products:
        raise ValueError('both sides need at least one structure')
    if any('>' in part for part in reactants + products):
        raise ValueError('reagents above the arrow are not supported yet')
    return reactants, products


def _signature(atom):
    return (atom.GetSymbol(), atom.GetFormalCharge(), atom.GetTotalNumHs(),
            atom.GetDegree(),
            tuple(sorted(n.GetSymbol() for n in atom.GetNeighbors())),
            atom.GetIsAromatic())


def _loose(atom):
    '''What still has to agree when the exact signature does not.'''
    return (atom.GetSymbol(), atom.GetFormalCharge(),
            tuple(sorted(n.GetSymbol() for n in atom.GetNeighbors())))


def map_atoms(reactants, products):
    '''Assign map numbers: product atoms point at the reactant atom they came from.

    Returns (mols, mapping). `mapping` has one row per product atom: which
    reactant atom it came from, the shared map number, and whether the match was
    exact or inferred. Unmatched product atoms get a fresh number and are marked
    `created` -- a genuine new atom, which a condensation never has.
    '''
    from rdkit import Chem

    r_mols = [Chem.MolFromSmiles(smiles) for smiles in reactants]
    p_mols = [Chem.MolFromSmiles(smiles) for smiles in products]
    if any(mol is None for mol in r_mols + p_mols):
        raise ValueError('at least one structure on the page does not parse')

    # (reactant index, atom index) -> map number, assigned in reading order.
    numbers = {}
    counter = 0
    for index, mol in enumerate(r_mols):
        for atom in mol.GetAtoms():
            counter += 1
            numbers[(index, atom.GetIdx())] = counter

    used = set()
    rows = []
    pending = []
    for p_index, mol in enumerate(p_mols):
        for atom in mol.GetAtoms():
            signature = _signature(atom)
            match = None
            for r_index, r_mol in enumerate(r_mols):
                for r_atom in r_mol.GetAtoms():
                    key = (r_index, r_atom.GetIdx())
                    if key in used or _signature(r_atom) != signature:
                        continue
                    match = key
                    break
                if match:
                    break
            if match:
                used.add(match)
                rows.append({'product': [p_index, atom.GetIdx()],
                             'reactant': list(match),
                             'map': numbers[match], 'element': atom.GetSymbol(),
                             'match': 'exact',
                             'product_index': len(rows)})
            else:
                pending.append((p_index, atom))

    for p_index, atom in pending:
        loose = _loose(atom)
        best = None
        for r_index, r_mol in enumerate(r_mols):
            for r_atom in r_mol.GetAtoms():
                key = (r_index, r_atom.GetIdx())
                if key in used or _loose(r_atom) != loose:
                    continue
                best = key
                break
            if best:
                break
        if best:
            used.add(best)
            rows.append({'product': [p_index, atom.GetIdx()],
                         'reactant': list(best),
                         'map': numbers[best], 'element': atom.GetSymbol(),
                         'match': 'inferred',
                         'product_index': len(rows)})
        else:
            counter += 1
            rows.append({'product': [p_index, atom.GetIdx()],
                         'reactant': None, 'map': counter,
                         'element': atom.GetSymbol(), 'match': 'created',
                         'product_index': len(rows)})
    # Stamp the numbers on the molecules too. Without this the page had no
    # AtomMapNum at all while the RXN block did -- the drawing and the file
    # disagreed about the same reaction.
    for row in rows:
        if not row['map']:
            continue
        p_index, p_atom = row['product']
        if row['reactant']:
            r_index, r_atom = row['reactant']
            r_mols[r_index].GetAtomWithIdx(r_atom).SetAtomMapNum(row['map'])
        p_mols[p_index].GetAtomWithIdx(p_atom).SetAtomMapNum(row['map'])
    return r_mols, p_mols, rows


def mapped_smiles(r_mols, p_mols, rows):
    '''The reaction with :n after every atom, for tools that read maps only here.'''
    from rdkit import Chem

    copies = []
    for mol in list(r_mols) + list(p_mols):
        copy = Chem.RWMol(mol)
        copy = copy.GetMol()
        copy.UpdatePropertyCache(strict=False)
        copies.append(copy)
    for row in rows:
        p_index, atom_index = row['product']
        target = copies[len(r_mols) + p_index].GetAtomWithIdx(atom_index)
        target.SetAtomMapNum(row['map'])
    side = [Chem.MolToSmiles(copies[i], canonical=False)
            for i in range(len(r_mols))]
    other = [Chem.MolToSmiles(copies[len(r_mols) + i], canonical=False)
             for i in range(len(p_mols))]
    return '.'.join(side) + '>>' + '.'.join(other)


def rxn_block(r_mols, p_mols, rows):
    '''A $RXN file: the interchange format, map numbers in the atom columns.'''
    from rdkit import Chem

    copies = []
    for mol in list(r_mols) + list(p_mols):
        copy = Chem.RWMol(mol).GetMol()
        copy.UpdatePropertyCache(strict=False)
        copies.append(copy)
    numbers = {}
    for row in rows:
        numbers[(row['product'][0], row['product'][1])] = row['map']
    for index, mol in enumerate(r_mols):
        for atom in mol.GetAtoms():
            for row in rows:
                if row['reactant'] == [index, atom.GetIdx()]:
                    copies[index].GetAtomWithIdx(atom.GetIdx()).SetAtomMapNum(row['map'])
                    break
    for count, mol in enumerate(copies):
        if count >= len(r_mols):
            offset = count - len(r_mols)
            for row in rows:
                if row['product'][0] == offset:
                    mol.GetAtomWithIdx(row['product'][1]).SetAtomMapNum(row['map'])
    blocks = []
    for mol in copies:
        if mol.GetNumConformers() == 0:
            from rdkit.Chem import AllChem
            AllChem.Compute2DCoords(mol)
        blocks.append(Chem.MolToMolBlock(mol))
    head = '$RXN\n\n  chem-draw-tool\n\n  %d  %d\n' % (len(r_mols), len(p_mols))
    body = ''.join('$MOL\n' + block for block in blocks)
    return head + body


def _fragment(mol, base, x, y, height_centre, with_maps):
    '''One fragment at an explicit position, bonds Kekule, ids from base.'''
    from rdkit import Chem
    from rdkit.Chem import AllChem

    if mol.GetNumConformers() == 0:
        AllChem.Compute2DCoords(mol)
    Chem.Kekulize(mol, clearAromaticFlags=True)
    conf = mol.GetConformer()
    count = mol.GetNumAtoms()
    xs = [conf.GetAtomPosition(i).x for i in range(count)]
    ys = [conf.GetAtomPosition(i).y for i in range(count)]
    minx, miny, maxy = min(xs), min(ys), max(ys)
    centre = (miny + maxy) / 2.0
    atoms = []
    for index in range(count):
        atom = mol.GetAtomWithIdx(index)
        px = (xs[index] - minx) * SCALE + x
        py = (ys[index] - centre) * SCALE + height_centre
        attrs = ['id="%d"' % (base + index), 'p="%.2f %.2f"' % (px, py),
                 'Element="%d"' % atom.GetAtomicNum()]
        if atom.GetFormalCharge():
            attrs.append('Charge="%d"' % atom.GetFormalCharge())
        if with_maps and atom.GetAtomMapNum():
            attrs.append('AtomMapNum="%d"' % atom.GetAtomMapNum())
        atoms.append('<n ' + ' '.join(attrs) + '/>')
    bonds = []
    for order, bond in enumerate(mol.GetBonds()):
        value = ('%.1f' % bond.GetBondTypeAsDouble()).rstrip('0').rstrip('.')
        bonds.append('<b id="%d" B="%d" E="%d" Order="%s"/>' % (
            base + 400 + order, base + bond.GetBeginAtomIdx(),
            base + bond.GetEndAtomIdx(), value))
    width = (max(xs) - minx) * SCALE
    return ''.join(atoms) + ''.join(bonds), width


def page_cdxml(r_mols, p_mols, mapped_products, conditions='', with_maps=True):
    '''Reactants left, arrow with the conditions above it, products right.'''
    height_centre = 90.0
    cursor = MARGIN
    chunks = []
    base = 1
    for mol in r_mols:
        body, width = _fragment(mol, base, cursor, 0.0, height_centre, with_maps)
        chunks.append('<fragment id="%d">%s</fragment>' % (base + 900, body))
        base += 560
        cursor += width + GAP
    arrow_start = cursor
    arrow_end = cursor + ARROW
    chunks.append('<graphic id="%d" BoundingBox="%.2f %.2f %.2f %.2f" '
                  'GraphicType="Arrow" ArrowType="FullHead"/>'
                  % (base + 950, arrow_start, height_centre, arrow_end, height_centre))
    if conditions:
        chunks.append('<t id="%d" p="%.2f %.2f" Justification="Center">'
                      '<s font="3" size="9">%s</s></t>'
                      % (base + 951, (arrow_start + arrow_end) / 2.0,
                         height_centre - 28.0, conditions))
    base += 560
    cursor = arrow_end + GAP
    for mol in p_mols:
        body, width = _fragment(mol, base, cursor, 0.0, height_centre, with_maps)
        chunks.append('<fragment id="%d">%s</fragment>' % (base + 900, body))
        base += 560
        cursor += width + GAP
    page_width = cursor + MARGIN
    page_height = height_centre * 2 + MARGIN
    return ('<CDXML><page id="1" BoundingBox="0 0 %.2f %.2f" BondLength="%.2f">'
            % (page_width, page_height, SCALE) + ''.join(chunks) +
            '</page></CDXML>')