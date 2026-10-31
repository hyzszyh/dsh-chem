'''Probe: where does the in-process RDKit SMILES parse die?'''
import subprocess
import sys

PY = sys.executable
CODE = ("import sys;from rdkit import Chem;"
        "s='C'*int(sys.argv[1]);m=Chem.MolFromSmiles(s);"
        "print('atoms',m.GetNumAtoms(),'canon',len(Chem.MolToSmiles(m)))")

for n in (2000, 3000, 3300, 3600, 4000, 5000):
    p = subprocess.run([PY, '-c', CODE, str(n)], capture_output=True)
    tail = (p.stdout + p.stderr).decode('utf-8', 'replace').replace('\n', ' ')[:70]
    print('len=%-5d rc=%-12d %s' % (n, p.returncode, tail))
