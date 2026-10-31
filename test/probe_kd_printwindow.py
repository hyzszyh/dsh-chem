'''Does PrintWindow need the window in the foreground? Measure both orders.'''
from __future__ import annotations
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'core'))
from chemdraw_tool.adapters import kd_native as kd, kd_open as op

mol = os.path.join(os.environ['TEMP'], 'kd_pw_probe.mol')
open(mol, 'w', encoding='utf-8', newline='').write(kd.smiles_to_mol('CC(=O)Oc1ccccc1C(=O)O').data['text'])
r = op.open_file(mol, timeout=20)
print('open', r.ok, 'pid', r.data.get('pid'), 'rect', r.data['window']['hwnd'])
hwnd = r.data['window']['hwnd']

def shot(label, bring):
    if bring:
        op._user32.ShowWindow(hwnd, op.SW_RESTORE)
        got = bool(op._user32.SetForegroundWindow(hwnd))
        time.sleep(0.5)
        print('  SetForegroundWindow ->', got)
    bgra, info = op._grab(hwnd, 100, 100, 'printwindow')  # size unused for this test
    print('  %-22s info=%r' % (label, info))

w = r.data['window']
rect = op._window_rect(hwnd)
print('rect', rect)
print('A) PrintWindow without touching foreground:')
bgra, info = op._grab(hwnd, rect['width'], rect['height'], 'printwindow')
print('   ', info, 'blank=', op._looks_blank(bgra))
print('B) after SW_RESTORE + SetForegroundWindow:')
op._user32.ShowWindow(hwnd, op.SW_RESTORE)
fg = bool(op._user32.SetForegroundWindow(hwnd))
time.sleep(0.6)
bgra, info = op._grab(hwnd, rect['width'], rect['height'], 'printwindow')
print('   fg=', fg, info, 'blank=', op._looks_blank(bgra))
for i in range(6):
    time.sleep(0.4)
    bgra, info = op._grab(hwnd, rect['width'], rect['height'], 'printwindow')
    print('   retry %d fg=%s %r blank=%s' % (i, fg, info, op._looks_blank(bgra)))
    if not op._looks_blank(bgra):
        png = op.png_from_bgra(rect['width'], rect['height'], bgra)
        out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', 'probe_printwindow.png')
        open(out, 'wb').write(png)
        print('   wrote', out, len(png), 'bytes')
        break
print('close:', op.close_app(r.data['pid'], 12.0).to_dict()['data'])
print('left:', op.list_pids())
