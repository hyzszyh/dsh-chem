from pathlib import Path
import sys, os, time
ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, os.path.join(ROOT, 'core'))
import win32com.client as win32

outdir = os.path.join(ROOT, 'test', 'out')
os.makedirs(outdir, exist_ok=True)
ref = os.path.join(outdir, 'reference.cdxml')

app = win32.Dispatch('ChemDraw_x64.Application')
print('app', app.Name)

doc = app.Documents.Add()
print('new doc', doc.Name)
try:
    doc.SaveAs(ref)
    print('saveas reference', os.path.getsize(ref))
except Exception as e:
    print('saveas ERR', str(e)[:150])
doc.Close(False)
print('closed, docs=', app.Documents.Count)

print('--- now reopen the reference file ---')
ret = app.Documents.Open(ref)
print('Open ret', ret)
time.sleep(1.0)
print('docs now', app.Documents.Count)
try:
    d2 = app.ActiveDocument
    print('active', d2.Name, 'objects', d2.Objects.Count)
    d2.Close(False)
except Exception as e:
    print('active ERR', str(e)[:100])

print('--- try our generated cdxml ---')
ours = os.path.join(outdir, 'aspirin.cdxml')
ret2 = app.Documents.Open(ours)
time.sleep(1.0)
print('Open ret2', ret2, 'docs', app.Documents.Count)
try:
    d3 = app.ActiveDocument
    print('active2', d3.Name, 'objects', d3.Objects.Count, 'atoms', d3.Atoms.Count)
    d3.Close(False)
except Exception as e:
    print('active2 ERR', str(e)[:100])

app.Quit()
print('done')
