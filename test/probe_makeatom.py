from pathlib import Path
import os
import win32com.client.dynamic as dyn

ROOT = str(Path(__file__).resolve().parent.parent)
out = os.path.join(ROOT, 'test', 'out')
app = dyn.Dispatch('ChemDraw_x64.Application')

print('=== IChemDrawDataType attrs ===')
o = app.ExportDataTypes.Item(1)
try:
    ti = o._oleobj_.GetTypeInfo()
    a = ti.GetTypeAttr()
    for i in range(a.cFuncs):
        fd = ti.GetFuncDesc(i)
        names = ti.GetNames(fd.memid)
        print('   ', names)
except Exception as e:
    print('typeinfo ERR', e)

print('=== try reading props directly ===')
for attr in ('String', 'Name', 'Type', 'ID', 'Value', 'Description', 'Extension'):
    try:
        print('  ', attr, '=', repr(getattr(o, attr)))
    except Exception as e:
        print('  ', attr, 'ERR', str(e)[:60])

print('=== MakeAtom / MakeBond ===')
doc = app.Documents.Add()
print('atoms before', doc.Atoms.Count)
try:
    doc.MakeAtom()
    print('MakeAtom ok, atoms', doc.Atoms.Count)
except Exception as e:
    print('MakeAtom ERR', str(e)[:150])
try:
    doc.MakeAtom()
    print('MakeAtom2 ok, atoms', doc.Atoms.Count)
    a1 = doc.Atoms.Item(1); a2 = doc.Atoms.Item(2)
    print('positions', a1.Position.x if hasattr(a1,'Position') else '?', a2.Position.x if hasattr(a2,'Position') else '?')
except Exception as e:
    print('atom props ERR', str(e)[:150])
try:
    doc.MakeBond(doc.Atoms.Item(1), doc.Atoms.Item(2))
    print('MakeBond ok, bonds', doc.Bonds.Count)
except Exception as e:
    print('MakeBond ERR', str(e)[:150])

print('=== SaveAs png no format ===')
try:
    p = os.path.join(out, 'makeatom.png')
    doc.SaveAs(p)
    print('png size', os.path.getsize(p) if os.path.exists(p) else 'missing')
except Exception as e:
    print('SaveAs png ERR', str(e)[:200])

try:
    doc.Close(False)
except Exception:
    pass
app.Quit()