from pathlib import Path
import sys, os, time
ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, os.path.join(ROOT, 'core'))
import win32com.client as win32

cdxml = os.path.join(ROOT, 'test', 'out', 'aspirin.cdxml')
outdir = os.path.join(ROOT, 'test', 'out')

app = win32.Dispatch('ChemDraw_x64.Application')
print('app', app.Name)
print('docs before', app.Documents.Count)

ret = app.Documents.Open(cdxml)
print('Open returned', type(ret).__name__, repr(ret)[:80])
time.sleep(0.6)
print('docs after', app.Documents.Count)

doc = None
try:
    doc = app.ActiveDocument
    print('ActiveDocument', doc.Name)
except Exception as e:
    print('ActiveDocument ERR', e)
if doc is None and app.Documents.Count > 0:
    doc = app.Documents.Item(1)
    print('Item(1)', doc.Name)

if doc is None:
    print('NO_DOC')
    app.Quit()
    raise SystemExit(1)

for attr in ('Objects', 'Atoms', 'Bonds'):
    try:
        print(attr, 'Count=', getattr(doc, attr).Count)
    except Exception as e:
        print(attr, 'ERR', str(e)[:80])

for ext in ('png', 'svg', 'tif'):
    p = os.path.join(outdir, 'aspirin.' + ext)
    try:
        doc.SaveAs(p)
        size = os.path.getsize(p) if os.path.exists(p) else 0
        print('SaveAs', ext, 'size', size)
    except Exception as e:
        print('SaveAs', ext, 'ERR', str(e)[:120])

try:
    doc.Close(False)
except Exception as e:
    print('close err', str(e)[:80])
app.Quit()
print('done')
