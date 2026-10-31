"""Question variants from a scaffold (FR-T2).

A scaffold with a dummy atom plus a list of substituents is exactly how a teacher
describes 'same skeleton, different group'. Replacement happens in RDKit so every
variant is a real, valid molecule rather than a drawing trick.
"""


def expand(scaffold: str, substituents, labels=None) -> dict:
    '''Replace the dummy atom with each substituent; report what happened.'''
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog('rdApp.*')
    base = Chem.MolFromSmiles(scaffold or '')
    if base is None:
        raise ValueError('the scaffold could not be parsed')
    query = Chem.MolFromSmiles('[*]')
    variants, failed = [], []
    for index, sub in enumerate(substituents):
        label = labels[index] if labels and index < len(labels) else str(sub)
        mol = Chem.MolFromSmiles(sub or '')
        if mol is None:
            failed.append({'label': label, 'smiles': sub,
                           'reason': 'the substituent could not be parsed'})
            continue
        try:
            products = Chem.ReplaceSubstructs(base, query, mol,
                                              replacementConnectionPoint=0)
        except Exception as exc:
            failed.append({'label': label, 'smiles': sub,
                           'reason': str(exc)[:80]})
            continue
        product = Chem.RemoveHs(products[0]) if products else None
        if product is None:
            failed.append({'label': label, 'smiles': sub,
                           'reason': 'replacement produced nothing'})
            continue
        from rdkit.Chem import rdMolDescriptors
        canon = Chem.MolToSmiles(product)
        variants.append({'label': label, 'substituent': sub, 'smiles': canon,
                         'formula': rdMolDescriptors.CalcMolFormula(product),
                         'inchikey': Chem.MolToInchiKey(product)})
    seen, unique = set(), []
    for row in variants:
        if row['inchikey'] in seen:
            row['duplicate_of'] = row['inchikey']
            continue
        seen.add(row['inchikey'])
        unique.append(row)
    return {'scaffold': scaffold, 'variants': unique,
            'duplicates': len(variants) - len(unique), 'failed': failed}