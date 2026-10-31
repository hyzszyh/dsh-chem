"""Identity, properties and file conversion, all through RDKit.

These verbs run without any vendor software, which is what makes them usable in
CI and on machines with no ChemDraw licence (NFR-5, NFR-8).
"""

import csv
import os

COLUMNS = ['label', 'smiles', 'formula', 'mw', 'exact_mass', 'logp', 'tpsa',
           'hbd', 'hba', 'rotatable', 'rings', 'charge', 'stereo_centers',
           'inchikey', 'inchi']


def describe(mol, label: str = '') -> dict:
    '''Everything a supplementary-information table needs (FR-O3).'''
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors

    return {
        'label': label,
        'smiles': Chem.MolToSmiles(mol),
        'formula': rdMolDescriptors.CalcMolFormula(mol),
        'mw': round(Descriptors.MolWt(mol), 3),
        'exact_mass': round(Descriptors.ExactMolWt(mol), 5),
        'logp': round(Descriptors.MolLogP(mol), 3),
        'tpsa': round(Descriptors.TPSA(mol), 2),
        'hbd': rdMolDescriptors.CalcNumHBD(mol),
        'hba': rdMolDescriptors.CalcNumHBA(mol),
        'rotatable': rdMolDescriptors.CalcNumRotatableBonds(mol),
        'rings': rdMolDescriptors.CalcNumRings(mol),
        'charge': Chem.GetFormalCharge(mol),
        'stereo_centers': len(Chem.FindMolChiralCenters(
            mol, includeUnassigned=True)),
        'inchikey': Chem.MolToInchiKey(mol),
        'inchi': Chem.MolToInchi(mol),
    }


def to_csv(rows, path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, 'w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def to_markdown(rows) -> str:
    '''A table that pastes into a report without reformatting.'''
    head = ['#', 'formula', 'MW', 'exact mass', 'logP', 'TPSA', 'HBD', 'HBA',
            'InChIKey']
    lines = ['| ' + ' | '.join(head) + ' |',
             '|' + '|'.join(['---'] * len(head)) + '|']
    for index, row in enumerate(rows, 1):
        cells = [str(index), row['formula'], '%.3f' % row['mw'],
                 '%.5f' % row['exact_mass'], '%.2f' % row['logp'],
                 '%.2f' % row['tpsa'], str(row['hbd']), str(row['hba']),
                 row['inchikey']]
        lines.append('| ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


def to_sdf(mols, path: str, labels=None) -> str:
    from rdkit import Chem
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    writer = Chem.SDWriter(path)
    try:
        for index, mol in enumerate(mols):
            if labels and index < len(labels):
                mol.SetProp('_Name', str(labels[index]))
            writer.write(mol)
    finally:
        writer.close()
    return path


def to_molblock(mol) -> str:
    from rdkit import Chem
    return Chem.MolToMolBlock(mol)


def to_smiles(mol) -> str:
    from rdkit import Chem
    return Chem.MolToSmiles(mol)