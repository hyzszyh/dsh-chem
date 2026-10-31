"""chem_props: numbers, computed not recalled.

Every field here is an RDKit descriptor with a fixed definition. The tool
reports which backend and which RDKit version produced them, so a value that
disagrees with a textbook can be traced instead of argued about.
"""

from __future__ import annotations

from . import mol as molmod

# name -> (callable, unit/notes). Kept explicit so `fields=` can select subsets
# and so the output order is stable across runs (dicts preserve insertion).
def _compute(m):
    from rdkit import Chem
    from rdkit.Chem import Crippen, Descriptors, QED, rdMolDescriptors

    rings = rdMolDescriptors.CalcNumRings(m)
    aromatic = rdMolDescriptors.CalcNumAromaticRings(m)
    return {
        "formula": molmod.formula(m),
        "canonical_smiles": molmod.canonical(m),
        "inchikey": molmod.inchikey(m),
        "mw": round(Descriptors.MolWt(m), 4),
        "exact_mass": round(Descriptors.ExactMolWt(m), 6),
        "logp": round(Crippen.MolLogP(m), 4),
        "tpsa": round(rdMolDescriptors.CalcTPSA(m), 4),
        "hbd": rdMolDescriptors.CalcNumHBD(m),
        "hba": rdMolDescriptors.CalcNumHBA(m),
        "rotatable_bonds": rdMolDescriptors.CalcNumRotatableBonds(m),
        "rings": rings,
        "aromatic_rings": aromatic,
        "aliphatic_rings": rings - aromatic,
        "heavy_atoms": m.GetNumHeavyAtoms(),
        "formal_charge": Chem.GetFormalCharge(m),
        "num_fragments": len(Chem.GetMolFrags(m)),
        "fraction_csp3": round(rdMolDescriptors.CalcFractionCSP3(m), 4),
        "qed": round(QED.qed(m), 4),
        "complexity": round(Descriptors.BertzCT(m), 2),
        "num_stereocenters": len(Chem.FindMolChiralCenters(m, includeUnassigned=True, useLegacyImplementation=False)),
    }


def handle(payload):
    smiles = payload.get("smiles") or payload.get("structure") or ""
    try:
        m = molmod.parse_struct(smiles)
    except molmod.MolError as exc:
        return {"ok": False, "failure": {"code": exc.code, "message": exc.message, "hint": exc.hint}}

    values = _compute(m)
    wanted = [f.strip() for f in str(payload.get("fields") or "").split(",") if f.strip()]
    if wanted:
        unknown = [f for f in wanted if f not in values]
        if unknown:
            return {"ok": False, "failure": {
                "code": "unknown-field",
                "message": "没有这些字段：" + ", ".join(unknown),
                "hint": "可用字段：" + ", ".join(values.keys()),
            }}
        values = {k: values[k] for k in wanted}

    import rdkit
    return {
        "ok": True,
        "channel": "rdkit",
        "data": values,
        "evidence": {"rdkit": rdkit.__version__, "definition": "RDKit descriptors (Crippen logP, TPSA, QED)"},
    }