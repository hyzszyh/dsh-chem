"""Structure input helpers shared by every tool.

Only two jobs: turn whatever the caller gave us into an RDKit Mol, and turn a
Mol back into the strings callers compare (SMILES / InChIKey). Keeping this in
one place is what makes "same input, same answer" true across tools.
"""

from __future__ import annotations


class MolError(Exception):
    """Input that cannot be turned into a molecule, with a caller-facing code."""

    def __init__(self, code, message, hint=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint


def _chem():
    from rdkit import Chem
    return Chem


def parse_struct(text, *, sanitize=True):
    """SMILES, molblock, or InChI -> Mol. Never returns None silently."""
    Chem = _chem()
    raw = (text or "").strip()
    if not raw:
        raise MolError("empty-input", "没有给结构", "传 smiles / molblock / InChI")
    mol = None
    if raw.startswith("InChI="):
        mol = Chem.MolFromInchi(raw)
    elif "\n" in raw and ("V2000" in raw or "V3000" in raw):
        mol = Chem.MolFromMolBlock(raw, sanitize=sanitize, removeHs=False)
    else:
        mol = Chem.MolFromSmiles(raw, sanitize=sanitize)
    if mol is None:
        raise MolError("bad-structure", "这个输入解析不出结构：" + raw[:60],
                       "检查 SMILES 的括号/环闭合，或改用 molblock")
    return mol


def canonical(mol):
    return _chem().MolToSmiles(mol)


def inchikey(mol):
    Chem = _chem()
    key = Chem.MolToInchiKey(mol)
    return key or None


def formula(mol):
    from rdkit.Chem import rdMolDescriptors
    return rdMolDescriptors.CalcMolFormula(mol)


def fragments(mol):
    """Disconnected pieces, biggest first -- salts and mixtures show up here."""
    Chem = _chem()
    pieces = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=True)
    return sorted(pieces, key=lambda m: m.GetNumHeavyAtoms(), reverse=True)