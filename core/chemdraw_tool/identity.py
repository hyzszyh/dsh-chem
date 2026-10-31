'''Molecule identity helpers: canonical SMILES, InChIKey, molecular formula.

Identity is the handshake between channels. Two engines may disagree about
layout, fonts or coordinates, but they must agree about what the molecule is.
'''

from __future__ import annotations

from typing import Optional

from .limits import (MAX_ATOMS_CANONICAL, MAX_SMILES_CHARS, too_large_payload,
                     too_many_atoms)
from .models import ErrorCode

_rdkit_error: Optional[str] = None


def _rdkit():
    '''Import rdkit lazily so the package still imports without it.'''
    global _rdkit_error
    try:
        from rdkit import Chem
        from rdkit import RDLogger
        from rdkit.Chem import rdMolDescriptors
        # rdkit prints parse failures to stderr. On the MCP transport that is
        # noise beside protocol messages, and the failure is already reported
        # structurally in the payload's note field.
        RDLogger.DisableLog('rdApp.*')
        return Chem, rdMolDescriptors
    except Exception as exc:  # pragma: no cover - depends on environment
        _rdkit_error = str(exc)
        return None, None


def rdkit_available() -> bool:
    chem, _ = _rdkit()
    return chem is not None


def rdkit_error() -> Optional[str]:
    _rdkit()
    return _rdkit_error


def mol_from_smiles(smiles: str):
    '''Parse a SMILES string into an RDKit molecule, or None.'''
    chem, _ = _rdkit()
    if chem is None:
        return None
    return chem.MolFromSmiles(smiles)


def canonical_smiles(smiles: str) -> Optional[str]:
    '''Return the canonical SMILES for any accepted SMILES spelling.'''
    mol = mol_from_smiles(smiles)
    if mol is None:
        return None
    chem, _ = _rdkit()
    return chem.MolToSmiles(mol)


def inchikey(smiles: str) -> Optional[str]:
    '''Standard InChIKey, the cross-engine identity used by the tool.'''
    mol = mol_from_smiles(smiles)
    if mol is None:
        return None
    chem, _ = _rdkit()
    try:
        return chem.MolToInchiKey(mol)
    except Exception:
        return None


def formula(smiles: str) -> Optional[str]:
    '''Molecular formula in Hill order, e.g. C9H8O4.'''
    mol = mol_from_smiles(smiles)
    if mol is None:
        return None
    _, desc = _rdkit()
    return desc.CalcMolFormula(mol)


def identify(smiles: str) -> dict:
    '''Full identity payload for a SMILES string.

    Carries an 'ok' key because MCP tools/call decides isError from it; without
    it every successful lookup was reported to the agent as a failure.

    Evidence is A when rdkit answered, C when we had to fall back to the raw
    string (no normalisation possible).
    '''
    if smiles is None or not str(smiles).strip():
        # An empty string is not a molecule. Returning ok=true with every field
        # empty (what this used to do) is the "succeeded at doing nothing" answer
        # the misuse pass fails on.
        return {
            'ok': False,
            'failure': {
                'code': ErrorCode.PARSE_FAILED,
                'channel': 'rdkit',
                'stage': 'input',
                'message': 'empty SMILES',
                'hint': 'Pass a SMILES string, e.g. c1ccccc1O',
                'detail': repr(smiles),
            },
            'input': smiles,
            'canonical_smiles': None,
            'inchikey': None,
            'formula': None,
            'evidence': 'A',
            'note': 'empty input: nothing to identify',
        }
    if len(smiles) > MAX_SMILES_CHARS:
        # Refuse before rdkit sees it: a long enough chain overflows the stack
        # inside the parser itself, where nothing can be caught.
        failure = too_large_payload('a SMILES string')
        failure['detail'] = ('%d characters, limit %d'
                             % (len(smiles), MAX_SMILES_CHARS))
        failure['message'] = ('SMILES is longer than %d characters' % MAX_SMILES_CHARS)
        return {
            'ok': False,
            'failure': failure,
            'input': smiles[:120] + '...',
            'canonical_smiles': None,
            'inchikey': None,
            'formula': None,
            'evidence': 'A',
            'note': failure['message'],
        }
    probe = mol_from_smiles(smiles)
    if too_many_atoms(probe):
        # Measured: 3000 atoms abort the interpreter (STATUS_STACK_OVERFLOW,
        # exit 3221225725, empty stdout and stderr). Refuse before the canonical
        # writer walks the graph.
        failure = too_large_payload('canonical SMILES')
        failure['detail'] = ('%d atoms, limit %d'
                             % (probe.GetNumAtoms(), MAX_ATOMS_CANONICAL))
        return {
            'ok': False,
            'failure': failure,
            'input': smiles[:120] + ('...' if len(smiles) > 120 else ''),
            'canonical_smiles': None,
            'inchikey': None,
            'formula': None,
            'evidence': 'A',
            'note': failure['message'],
        }
    canon = canonical_smiles(smiles)
    if canon is None:
        missing_rdkit = not rdkit_available()
        return {
            'ok': False,
            # The flat fields stay where they were so existing callers keep
            # working; 'failure' is what makes the error machine-readable.
            # Without it an agent could see ok=false and nothing else, which is
            # the difference between "retry with different input" and "install
            # a package".
            'failure': {
                'code': (ErrorCode.NOT_INSTALLED if missing_rdkit
                         else ErrorCode.PARSE_FAILED),
                'channel': 'rdkit',
                'stage': 'install' if missing_rdkit else 'parse',
                'message': ('rdkit is not installed' if missing_rdkit
                            else 'rdkit could not parse this SMILES'),
                'hint': ('pip install rdkit' if missing_rdkit
                         else 'Check the SMILES syntax'),
                'detail': (str(rdkit_error()) if missing_rdkit else smiles),
            },
            'input': smiles,
            'canonical_smiles': None,
            'inchikey': None,
            'formula': None,
            'evidence': 'C',
            'note': ('rdkit is not installed: ' + str(rdkit_error())
                     if missing_rdkit
                     else 'rdkit could not parse this SMILES'),
        }
    return {
        'ok': True,
        'input': smiles,
        'canonical_smiles': canon,
        'inchikey': inchikey(smiles),
        'formula': formula(smiles),
        'evidence': 'A',
        # None, not '': the note is where a caveat goes, and 'no caveat' is
        # an absence a script can test for. See models._or_none.
        'note': None,
    }


def same_molecule(a: str, b: str) -> dict:
    '''Compare two structures by InChIKey, falling back to canonical SMILES.'''
    ia = identify(a)
    ib = identify(b)
    ka, kb = ia.get('inchikey'), ib.get('inchikey')
    if ka and kb:
        verdict = ka == kb
        basis = 'inchikey'
    else:
        verdict = ia.get('canonical_smiles') == ib.get('canonical_smiles')
        basis = 'canonical_smiles'
    return {
        'same': verdict,
        'basis': basis,
        'left': ia,
        'right': ib,
    }