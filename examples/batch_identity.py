'''Turn a list of SMILES into identities, with nothing installed but rdkit.

    python examples/batch_identity.py

This is the floor of the project: it runs on a machine with no ChemDraw, no
KingDraw and no Windows-specific pieces. Everything else is an add-on, so this
is also the quickest way to tell whether a broken environment is the Python
side or the application side.
'''
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'core'))

from chemdraw_tool.identity import identify  # noqa: E402

MOLECULES = [
    ('phenol', 'c1ccccc1O'),
    ('aspirin', 'CC(=O)Oc1ccccc1C(=O)O'),
    ('caffeine', 'Cn1cnc2c1c(=O)n(C)c(=O)n2C'),
]


def main() -> int:
    failures = 0
    for name, smiles in MOLECULES:
        result = identify(smiles)
        if not result.get('ok'):
            failures += 1
            print('%-9s FAILED  %s' % (name, result.get('note', 'unknown')))
            continue
        print('%-9s %s' % (name, result['inchikey']))
        print('%-9s formula=%s  canonical=%s' % ('', result['formula'], result['canonical_smiles']))
    if failures:
        print('\n%d of %d failed; rdkit is probably absent.' % (failures, len(MOLECULES)))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())