from pathlib import Path
import os
import win32com.client.dynamic as dyn

ROOT = str(Path(__file__).resolve().parent.parent)
out = os.path.join(ROOT, 'test', 'out')
app = dyn.Dispatch('ChemDraw_x64.Application')

ed = app.ExportDataTypes
idt = app.ImportDataTypes

def describe(coll, label):
    print('===', label, 'count', coll.Count)
    names = []
    for i in range(coll.Count):
        o = coll.Item(i + 1)
        picked = None
        for attr in ('Name', 'name', 'String', 'ID', 'id', 'Description', 'description'):
            try:
                v = getattr(o, attr)
                if v is None:
                    continue
                picked = (attr, v)
                break
            except Exception:
                continue
        names.append((i + 1, picked))
        print('  [%2d] %s' % (i + 1, picked))
    return names

exp = describe(ed, 'ExportDataTypes')
imp = describe(idt, 'ImportDataTypes')
app.Quit()