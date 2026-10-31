"""Reaction stoichiometry without a dialog box (FR-V3).

ChemDraw has Analyze Stoichiometry, but a table computed here is reproducible,
diffable and testable — and it works on machines with no licence at all.
"""


def _species(text: str) -> list:
    '''Split 'A.B' into the individual components, ignoring empties.'''
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog('rdApp.*')
    out = []
    for chunk in (text or '').split('.'):
        if not chunk.strip():
            continue
        mol = Chem.MolFromSmiles(chunk.strip())
        if mol is not None:
            out.append(mol)
    return out


def table(reaction: str, scale_mmol: float = 1.0,
          yield_percent: float = None) -> dict:
    '''Equivalents, mmol and mass for every species in 'reactants>>products'.'''
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors

    if '>>' not in (reaction or ''):
        raise ValueError("a reaction needs the form 'reactants>>products'")
    left, right = reaction.split('>>', 1)
    rows = []
    for role, side in (('reactant', left), ('product', right)):
        for index, mol in enumerate(_species(side), 1):
            mw = Descriptors.MolWt(mol)
            # Reactants: 1.0 equiv at the stated scale. Products: theoretical
            # mass assuming a 1:1 conversion from the limiting reagent, which is
            # stated in the note rather than silently believed.
            equivalent = 1.0 if role == 'reactant' else None
            mmol = scale_mmol
            mass = mmol * mw
            rows.append({
                'role': role,
                'order': index,
                'smiles': Chem.MolToSmiles(mol),
                'formula': rdMolDescriptors.CalcMolFormula(mol),
                'mw': round(mw, 3),
                'equiv': equivalent,
                'mmol': round(mmol, 3) if mmol is not None else None,
                'mass_mg': round(mass, 2) if mass is not None else None,
            })
    if yield_percent is not None:
        for row in rows:
            if row['role'] == 'product' and row['mass_mg'] is not None:
                row['mass_at_yield_mg'] = round(
                    row['mass_mg'] * float(yield_percent) / 100.0, 2)
    return {'reaction': reaction, 'scale_mmol': scale_mmol,
            'yield_percent': yield_percent, 'rows': rows,
            'note': ('reactant masses are 1.0 equiv at the stated scale; product '
                     'masses are theoretical at 1:1 conversion, not a yield claim')}