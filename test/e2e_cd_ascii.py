from pathlib import Path
import sys, os, time, shutil
ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, os.path.join(ROOT, 'core'))
import win32com.client as win32

ascii_dir = r'D:\Test'
ascii_cdxml = os.path.join(ascii_dir, 'cdx_ascii_test.cdxml')
shutil.copy(os.path.join(ROOT, 'test', 'out', 'aspirin.cdxml'), ascii_cdxml)
print('copied to', ascii_cdxml)

app = win32.Dispatch('ChemDraw_x64.Application')
print('app', app.Name, 'docs', app.Documents.Count)

print('--- A: open ASCII path ---')
try:
    r1 = app.Documents.Open(ascii_cdxml)
    print('open ascii ret', r1)
except Exception as e:
    print('open ascii ERR', str(e)[:150])
time.sleep(1.2)
print('docs', app.Documents.Count)

def first_doc():
    try:
        return app.Documents.Item(1)
    except Exception:
        return None

d = first_doc()
if d is not None:
    try:
        print('doc1', d.Name, 'objects', d.Objects.Count, 'atoms', d.Atoms.Count, 'bonds', d.Bonds.Count)
    except Exception as e:
        print('doc1 props ERR', str(e)[:100])
    try:
        png = os.path.join(ascii_dir, 'cdx_ascii_test.png')
        d.SaveAs(png)
        print('saveas png size', os.path.getsize(png) if os.path.exists(png) else 0)
    except Exception as e:
        print('saveas png ERR', str(e)[:150])
    try:
        d.Close(False)
    except Exception as e:
        print('close ERR', str(e)[:80])

print('docs after close', app.Documents.Count)

print('--- B: saveas into chinese path ---')
doc = app.Documents.Add()
try:
    doc.SaveAs(os.path.join(ROOT, 'test', 'out', 'cn_path_test.cdxml'))
    print('cn saveas OK')
except Exception as e:
    print('cn saveas ERR', str(e)[:160])
try:
    doc.Close(False)
except Exception:
    pass
app.Quit()
print('done')
