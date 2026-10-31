from pathlib import Path
import os
import win32com.client.dynamic as dyn

ROOT = str(Path(__file__).resolve().parent.parent)
out = os.path.join(ROOT, 'test', 'out')
os.makedirs(out, exist_ok=True)

app = dyn.Dispatch('ChemDraw_x64.Application')
docs = app.Documents

def funcs(obj, label):
    try:
        ti = obj._oleobj_.GetTypeInfo()
        a = ti.GetTypeAttr()
    except Exception as e:
        print(label, 'no typeinfo', e); return []
    res = []
    for i in range(a.cFuncs):
        try:
            fd = ti.GetFuncDesc(i)
            names = ti.GetNames(fd.memid)
            if names: res.append((names[0], list(names[1:])))
        except Exception:
            pass
    print('===', label, len(res))
    for n, args in res:
        print('   %-24s (%s)' % (n, ', '.join(args)))
    return res

funcs(docs, 'Documents collection')

print('=== ExportDataTypes ===')
try:
    ed = app.ExportDataTypes
    print('count', ed.Count)
    for i in range(min(ed.Count, 25)):
        try:
            print('  ', i, ed.Item(i + 1))
        except Exception as e:
            print('  item err', e)
except Exception as e:
    print('ExportDataTypes ERR', str(e)[:120])

print('=== ImportDataTypes ===')
try:
    idt = app.ImportDataTypes
    print('count', idt.Count)
    for i in range(min(idt.Count, 25)):
        try:
            print('  ', i, idt.Item(i + 1))
        except Exception as e:
            print('  item err', e)
except Exception as e:
    print('ImportDataTypes ERR', str(e)[:120])
app.Quit()