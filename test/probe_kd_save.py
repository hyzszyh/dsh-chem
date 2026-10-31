'''Probe: does KingDraw expose Save As through UI Automation?

Dumps every element of the pistream window with control_type / name / auto_id
into test/out/kd_uia_dump.json, and prints the rows that look like a save command.
'''
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'core'))
from chemdraw_tool.adapters import kd_open, kd_native  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
MOL = os.path.join(OUT, 'kd_save_probe.mol')
HINTS = ('save', '保存', '另存', '导出', 'export', 'king')


def dump(pid, path):
    from pywinauto import Application
    app = Application(backend='uia').connect(process=pid)
    win = app.top_window()
    rows = []
    t0 = time.monotonic()
    for el in win.descendants():
        info = el.element_info
        try:
            row = {'type': info.control_type, 'name': info.name,
                   'auto_id': info.automation_id, 'class': info.class_name}
        except Exception as exc:
            row = {'error': str(exc)}
        rows.append(row)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)
    return rows, time.monotonic() - t0


def main():
    os.makedirs(OUT, exist_ok=True)
    if len(sys.argv) > 1:
        MOL_IN = os.path.abspath(sys.argv[1])
    else:
        MOL_IN = MOL
        mol = kd_native.smiles_to_mol('c1ccccc1O')  # needs the 32-bit runtime
        assert mol.ok, mol.failure
        with open(MOL, 'w', encoding='utf-8', newline='') as fh:
            fh.write(mol.data['text'])
    for pid in kd_open.list_pids():
        kd_open.close_app(pid, 8.0)
    res = kd_open.open_file(MOL_IN, timeout=25)
    print('open ok=%r pid=%r' % (res.ok, (res.data or {}).get('pid')))
    if not res.ok:
        print(res.failure.to_dict())
        return 1
    pid = res.data['pid']
    rows, walked = dump(pid, os.path.join(OUT, 'kd_uia_dump.json'))
    print('elements=%d walk=%.2fs' % (len(rows), walked))
    kinds = {}
    for row in rows:
        kinds[row.get('type')] = kinds.get(row.get('type'), 0) + 1
    print('types:', json.dumps(kinds, ensure_ascii=False, sort_keys=True))
    print('--- menu-ish rows ---')
    for row in rows:
        name = (row.get('name') or '')
        if any(h in name.lower() for h in HINTS) or row.get('type') in ('MenuItem', 'MenuBar'):
            print('%-12s name=%-28r auto_id=%r class=%r' % (
                row.get('type'), name[:28], row.get('auto_id'), (row.get('class') or '')[:20]))
    print('--- tab items ---')
    for row in rows:
        if row.get('type') in ('TabItem', 'Tab'):
            print('%-12s name=%r auto_id=%r' % (row.get('type'), row.get('name'), row.get('auto_id')))
    print('close:', kd_open.close_app(pid, 12.0).to_dict()['data'])
    print('left:', kd_open.list_pids())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
