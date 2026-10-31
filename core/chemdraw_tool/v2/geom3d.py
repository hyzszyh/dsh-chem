"""3D conformers without the vendor menu (FR-O5, task D5).

ChemDraw has 3D Clean Up and Add 3D Property in its menu, but the menu cannot be
driven reliably yet (see ARCHIVE.md and requirements §12). RDKit embeds and
optimises a conformer deterministically, which is what a student actually needs
before handing a structure to Gaussian or ORCA.
"""


def embed(smiles: str, optimize: bool = True, seed: int = 0xf00d,
          max_iters: int = 500) -> dict:
    '''A 3D mol block plus the facts about how it was produced.'''
    from rdkit import Chem, RDLogger
    from rdkit.Chem import AllChem
    RDLogger.DisableLog('rdApp.*')

    mol = Chem.MolFromSmiles(smiles or '')
    if mol is None:
        raise ValueError('could not parse the structure')
    mol = Chem.AddHs(mol)
    params = AllChem.ETKDGv3()
    params.randomSeed = int(seed)
    params.useSmallRingTorsions = True
    code = AllChem.EmbedMolecule(mol, params)
    if code != 0:
        params.useRandomCoords = True
        code = AllChem.EmbedMolecule(mol, params)
    if code != 0:
        raise RuntimeError('RDKit could not embed a 3D conformer')
    energy = None
    converged = None
    if optimize:
        try:
            props = AllChem.MMFFGetMoleculeProperties(mol)
            field = AllChem.MMFFGetMoleculeForceField(mol, props)
            converged = field.Minimize(maxIts=max_iters) == 0
            energy = round(field.CalcEnergy(), 3)
        except Exception:
            converged = AllChem.UFFOptimizeMolecule(mol) == 0
            energy = None
    return {'mol': mol, 'energy_kcal': energy, 'converged': converged,
            'atoms_with_h': mol.GetNumAtoms(),
            'method': 'ETKDGv3 + MMFF94' if optimize else 'ETKDGv3'}


def to_molblock(mol) -> str:
    from rdkit import Chem
    return Chem.MolToMolBlock(mol)


def to_xyz(mol) -> str:
    '''XYZ for Gaussian/ORCA; RDKit writes it without a format flag.'''
    from rdkit.Chem import rdMolTransforms  # noqa: F401
    lines = ['%d' % mol.GetNumAtoms(), '']
    conf = mol.GetConformer()
    for atom in mol.GetAtoms():
        point = conf.GetAtomPosition(atom.GetIdx())
        lines.append('%-3s %10.6f %10.6f %10.6f'
                     % (atom.GetSymbol(), point.x, point.y, point.z))
    return '\n'.join(lines) + '\n'