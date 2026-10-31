import os, glob
import win32com.client
import win32com.client.gencache as gc

app = win32com.client.gencache.EnsureDispatch('ChemDraw_x64.Application')
gen = gc.GetGeneratePath()
files = sorted(glob.glob(os.path.join(gen, '**', '*.py'), recursive=True))
print('modules', len(files))
want = ('MakeAtom', 'MakeBond', 'Open', 'Paste', 'MakeCaption', 'Import', 'Export')
for f in files:
    try:
        text = open(f, encoding='latin-1').read()
    except Exception:
        continue
    hits = [ln.strip() for ln in text.splitlines() if ln.strip().startswith('def ') and any(w in ln for w in want)]
    if not hits:
        continue
    print('FILE', os.path.basename(f), '(', len(hits), 'hits )')
    for h in hits[:25]:
        print('   ', h[:170])
app.Quit()