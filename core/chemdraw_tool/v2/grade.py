"""Grading student structures against an answer (FR-T1).

A teacher does not need a score, they need the sentence that explains the mark.
So this compares identities, then explains the difference in the vocabulary of a
classroom: wrong skeleton, missing stereochemistry, wrong formula, a group that is
there when it should not be.
"""

GROUPS = {
    'carboxylic acid': '[CX3](=O)[OX2H1]',
    'ester': '[CX3](=O)[OX2][#6]',
    'amide': '[CX3](=O)[NX3]',
    'ketone': '[#6][CX3](=O)[#6]',
    'aldehyde': '[CX3H1](=O)[#6]',
    'alcohol': '[OX2H][CX4]',
    'phenol': '[OX2H]c',
    'amine': '[NX3;H2,H1;!$(NC=O)]',
    'nitro': '[N+](=O)[O-]',
    'nitrile': 'C#N',
    'halide': '[F,Cl,Br,I]',
    'aromatic ring': 'c1ccccc1',
}


def _groups(mol) -> dict:
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog('rdApp.*')
    found = {}
    for name, smarts in GROUPS.items():
        pattern = Chem.MolFromSmarts(smarts)
        if pattern is None:
            continue
        count = len(mol.GetSubstructMatches(pattern))
        if count:
            found[name] = count
    return found


def _facts(mol) -> dict:
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors
    return {
        'inchikey': Chem.MolToInchiKey(mol),
        'smiles': Chem.MolToSmiles(mol),
        'formula': rdMolDescriptors.CalcMolFormula(mol),
        'mw': round(Descriptors.MolWt(mol), 3),
        'atoms': mol.GetNumAtoms(),
        'rings': rdMolDescriptors.CalcNumRings(mol),
        'charge': Chem.GetFormalCharge(mol),
        'stereo': len(Chem.FindMolChiralCenters(mol, includeUnassigned=True)),
        'groups': _groups(mol),
    }


def compare(answer, student) -> dict:
    '''Verdict plus the reason a teacher would write next to the mark.'''
    from rdkit import Chem
    left, right = _facts(answer), _facts(student)
    if left['inchikey'] == right['inchikey']:
        return {'verdict': 'correct', 'reason': 'same structure',
                'answer': left, 'student': right, 'differences': []}

    differences = []
    if left['formula'] != right['formula']:
        differences.append('formula %s, answer %s'
                           % (right['formula'], left['formula']))
    if left['charge'] != right['charge']:
        differences.append('net charge %+d, answer %+d'
                           % (right['charge'], left['charge']))
    if left['rings'] != right['rings']:
        differences.append('%d ring(s), answer has %d'
                           % (right['rings'], left['rings']))
    for name in sorted(set(left['groups']) | set(right['groups'])):
        have, want = right['groups'].get(name, 0), left['groups'].get(name, 0)
        if have != want:
            differences.append('%s: %d, answer has %d' % (name, have, want))

    # InChIKey's first block is the skeleton: equal skeleton, different structure
    # almost always means the stereochemistry is wrong, and that is worth saying.
    skeleton_equal = left['inchikey'].split('-')[0] == right['inchikey'].split('-')[0]
    if skeleton_equal and left['stereo'] and right['stereo']:
        verdict = 'stereo'
        reason = 'same skeleton, different stereochemistry'
    elif skeleton_equal:
        verdict = 'stereo'
        reason = 'same skeleton, but the stereocentres do not match'
    elif left['formula'] == right['formula']:
        verdict = 'isomer'
        reason = 'same formula, different connectivity'
    else:
        verdict = 'different'
        reason = 'different structure'
    if not differences:
        differences.append('no formula or functional-group difference found; '
                           'the change is in the skeleton')
    return {'verdict': verdict, 'reason': reason, 'answer': left,
            'student': right, 'differences': differences}


def grade(answer_smiles: str, students, labels=None) -> dict:
    '''One row per student, with a verdict and the reasons behind it.'''
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog('rdApp.*')
    answer = Chem.MolFromSmiles(answer_smiles or '')
    if answer is None:
        raise ValueError('the answer could not be parsed')
    rows = []
    for index, text in enumerate(students):
        label = labels[index] if labels and index < len(labels) else 'student %d' % (index + 1)
        mol = Chem.MolFromSmiles((text or '').strip())
        if mol is None:
            rows.append({'label': label, 'submitted': text, 'verdict': 'unreadable',
                         'reason': 'the structure could not be parsed',
                         'differences': []})
            continue
        row = compare(answer, mol)
        row['label'] = label
        row['submitted'] = text
        rows.append(row)
    counts = {}
    for row in rows:
        counts[row['verdict']] = counts.get(row['verdict'], 0) + 1
    return {'answer': answer_smiles, 'rows': rows, 'counts': counts,
            'marked': sum(counts.get(name, 0) for name in ('correct',))}