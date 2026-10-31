'''Ask two vendors the same question and compare the answers.

    python examples/crosscheck_batch.py

Each molecule goes through RDKit (local), KingDraw's DLL (32-bit) and
ChemDraw's COM server (64-bit). The three are compared by InChIKey, never by
SMILES text: ChemDraw rewrites the string it is handed, so a string match would
report false disagreement on molecules that are in fact identical.

Degrades instead of failing - with only RDKit installed it still reports, and
says so.
'''
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'core'))

from chemdraw_tool.crosscheck import crosscheck, shutdown  # noqa: E402

MOLECULES = [
    ('phenol', 'c1ccccc1O'),
    ('aspirin', 'CC(=O)Oc1ccccc1C(=O)O'),
    ('caffeine', 'Cn1cnc2c1c(=O)n(C)c(=O)n2C'),
]


def main() -> int:
    disagreements = 0
    try:
        for name, smiles in MOLECULES:
            result = crosscheck(smiles)
            if not result.ok:
                print('%-9s FAILED  %s' % (name, result.failure.message))
                disagreements += 1
                continue
            data = result.data
            engines = data.get('engines', {})
            print('%-9s agree=%s' % (name, data.get('agree')))
            for engine, info in engines.items():
                print('          %-9s %s' % (engine, info.get('inchikey') or info.get('error') or '-'))
            if result.degraded:
                # A channel that could not run at all is still 'degraded' but
                # has no reason string, and printing the Python None there is
                # how a fresh clone ended up showing '(degraded: None)'.
                reason = (data.get('degrade_reason') or '').strip()
                print('          (degraded: %s)' % (reason or 'a channel did not contribute'))
            if not data.get('agree'):
                disagreements += 1
    finally:
        shutdown()
    return 2 if disagreements else 0


if __name__ == '__main__':
    raise SystemExit(main())