"""Structure checks that do not need a vendor program (FR-V1).

Everything here is a fact RDKit can prove: valence, charge, disconnected
fragments, unassigned stereo, and — when a drawn page is available — atoms that
sit on top of each other. Anything that cannot be proven is left out rather than
guessed.
"""


def inspect(mol) -> dict:
    '''Problems worth telling a student about, each with a concrete fix.'''
    from rdkit import Chem, RDLogger
    from rdkit.Chem import rdMolDescriptors
    RDLogger.DisableLog('rdApp.*')
    issues = []

    # Explicit valence, computed from the bonds that are actually drawn. This
    # runs before sanitisation on purpose: RDKit refuses to sanitise the very
    # structures worth reporting, so 'atom 2 has 5 bonds' has to come from here.
    try:
        mol.UpdatePropertyCache(strict=False)
    except Exception:
        pass
    caps = {'C': 4, 'N': 3, 'O': 2, 'H': 1, 'F': 1, 'Cl': 1, 'Br': 1, 'I': 1,
            'S': 6, 'P': 5, 'B': 3, 'Si': 4}
    for atom in mol.GetAtoms():
        cap = caps.get(atom.GetSymbol())
        if not cap:
            continue
        used = sum(bond.GetBondTypeAsDouble() for bond in atom.GetBonds())
        used += atom.GetNumExplicitHs()
        if used > cap + 0.01:
            issues.append({
                'code': 'valence', 'severity': 'error',
                'message': 'atom %d (%s) carries %g bond orders, the limit is %d'
                           % (atom.GetIdx() + 1, atom.GetSymbol(), used, cap),
                'fix': 'remove a bond or add a charge; a carbon may have at most four',
            })

    try:
        Chem.SanitizeMol(Chem.Mol(mol))
        sanitized = True
    except Exception as exc:
        sanitized = False
        issues.append({
            'code': 'valence', 'severity': 'error',
            'message': 'RDKit refuses to sanitize this structure: %s' % str(exc)[:120],
            'fix': 'check for a pentavalent carbon, a wrong charge or a bad bond order',
        })

    fragments = len(Chem.GetMolFrags(mol))
    if fragments > 1:
        issues.append({
            'code': 'disconnected', 'severity': 'info',
            'message': '%d disconnected fragments (a salt or a mixture?)' % fragments,
            'fix': 'separate the counter-ion into its own row if it is a salt',
        })

    try:
        centres = Chem.FindMolChiralCenters(mol, includeUnassigned=True)
    except Exception:
        centres = []
    unassigned = [centre for centre, label in centres if label == '?']
    if unassigned:
        issues.append({
            'code': 'stereo-unassigned', 'severity': 'warning',
            'message': '%d stereocentre(s) drawn without a wedge: atom %s'
                       % (len(unassigned), ', '.join(str(i + 1)
                                                  for i in unassigned[:6])),
            'fix': 'add a wedge or hash bond, or say the stereochemistry is unknown',
        })

    charge = Chem.GetFormalCharge(mol)
    if charge:
        issues.append({
            'code': 'charge', 'severity': 'info',
            'message': 'net charge %+d' % charge,
            'fix': 'confirm the counter-ion is drawn',
        })

    radicals = sum(1 for atom in mol.GetAtoms() if atom.GetNumRadicalElectrons())
    if radicals:
        issues.append({
            'code': 'radical', 'severity': 'warning',
            'message': '%d radical centre(s) drawn' % radicals,
            'fix': 'radicals must be deliberate; check the bond orders',
        })

    try:
        formula = rdMolDescriptors.CalcMolFormula(mol)
    except Exception:
        formula = '?'
    summary = {
        'sanitized': sanitized,
        'atoms': mol.GetNumAtoms(),
        'bonds': mol.GetNumBonds(),
        'fragments': fragments,
        'charge': charge,
        'formula': formula,
        'stereocentres': len(centres),
        'errors': sum(1 for row in issues if row['severity'] == 'error'),
        'warnings': sum(1 for row in issues if row['severity'] == 'warning'),
    }
    return {'ok': summary['errors'] == 0, 'issues': issues, 'summary': summary}


def overlaps(geometry: dict, factor: float = 0.6) -> list:
    '''Atom pairs closer than factor x the median bond length.'''
    import math
    from . import geometry as geom
    atoms = geometry.get('atoms') or {}
    lengths = geom.bond_lengths(geometry)
    if len(atoms) < 2 or not lengths:
        return []
    limit = geom.median(lengths) * factor
    points = list(atoms.items())
    clashes = []
    for index, (left_id, left) in enumerate(points):
        for right_id, right in points[index + 1:]:
            distance = math.hypot(left[0] - right[0], left[1] - right[1])
            if distance < limit:
                clashes.append({'a': left_id, 'b': right_id,
                                'distance_pt': round(distance, 2),
                                'limit_pt': round(limit, 2)})
    return clashes