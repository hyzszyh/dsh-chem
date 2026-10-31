from pathlib import Path
import os, sys
import win32com.client.dynamic as dyn

app = dyn.Dispatch('ChemDraw_x64.Application')
doc = app.Documents.Add()
print('doc', doc.name if hasattr(doc, 'name') else doc.Name)

def dump(obj, label):
    ti = obj._oleobj_.GetTypeInfo()
    attr = ti.GetTypeAttr()
    out = []
    for i in range(attr.cFuncs):
        try:
            fd = ti.GetFuncDesc(i)
            names = ti.GetNames(fd.memid)
            if names:
                out.append((names[0], list(names[1:])))
        except Exception:
            continue
    print('===', label, len(out), 'funcs')
    for name, args in out:
        print('   %-30s (%s)' % (name, ', '.join(args)))
    return out

funcs = dump(doc, 'Document')
appfuncs = dump(app, 'Application')

path = str(Path(__file__).resolve().parent.parent / 'docs' / 'com_item_document.txt')
with open(path, 'w', encoding='utf-8') as fh:
    for name, args in funcs:
        fh.write('%-30s (%s)\n' % (name, ', '.join(args)))
    fh.write('\n\n=== Application ===\n')
    for name, args in appfuncs:
        fh.write('%-30s (%s)\n' % (name, ', '.join(args)))
print('written', path)
doc.Close(False)
app.Quit()