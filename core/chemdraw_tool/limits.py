'''Input ceilings shared by both channels.

These numbers are measured, not guessed. RDKit's canonical SMILES writer walks
the molecule recursively, and on this machine a 3000-atom chain takes the whole
interpreter down with STATUS_STACK_OVERFLOW: exit code 3221225725, empty stdout,
empty stderr, nothing a caller can explain to a user. 2000 atoms still survived,
so the safe ceiling is set below it with margin.

Refusing with E06 costs the caller a big molecule; crashing costs them the
process and any diagnosis at all. The misuse pass (t18) treats an unexplained
exit as a failure, so the ceiling lives here, in one place, and both channels
consult it.
'''

#: Above this atom count canonical SMILES / InChIKey are not attempted.
MAX_ATOMS_CANONICAL = 1000

#: Ceiling for a raw SMILES string. One character carries at most one atom, so a
#: 2000-character string cannot describe more than 2000 atoms -- the point where
#: parse-plus-canonicalise was still measured to survive. Refusing on length costs
#: nothing and stops the parse from being reached at all.
MAX_SMILES_CHARS = 2000


def too_many_atoms(mol) -> bool:
    try:
        return mol.GetNumAtoms() > MAX_ATOMS_CANONICAL
    except Exception:
        return False


def too_long(smiles) -> bool:
    return isinstance(smiles, str) and len(smiles) > MAX_SMILES_CHARS


def too_large_payload(what: str) -> dict:
    '''The failure body both channels use, so the wording cannot drift.'''
    return {
        'code': 'E06',
        'channel': 'rdkit',
        'stage': 'input',
        'message': 'structure too large for %s (limit %d atoms)'
                   % (what, MAX_ATOMS_CANONICAL),
        'hint': ('Identify a smaller fragment, or compare the drawings instead of '
                 'the molecules. The limit exists because canonicalisation of a '
                 'bigger molecule aborts the process with no message.'),
    }
