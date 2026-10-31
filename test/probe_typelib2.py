import os, glob
import win32com.client.gencache as gc
gen = gc.GetGeneratePath()
print('genpath', gen)
files = sorted(glob.glob(os.path.join(gen, '**', '*.py'), recursive=True))
for f in files:
    print('---', os.path.relpath(f, gen), os.path.getsize(f))
print('=== search MakeAtom ===')
for f in files:
    text = open(f, encoding='latin-1').read()
    if 'MakeAtom' in text:
        for ln in text.splitlines():
            if 'MakeAtom' in ln or 'MakeBond' in ln:
                print(os.path.basename(f), '|', ln.strip()[:200])