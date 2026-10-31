from pathlib import Path
'''End-to-end visual check: open a molfile in KingDraw, then look at it.

kd_open runs in the 32-bit worker, which has no PIL and no modern capture
library. The 64-bit host does, so the screenshot is taken here instead: find
every visible window owned by the pid the opener reported, keep the largest
(the splash screen shares the title and appears first), capture it.
'''
import json
import os
import subprocess
import sys
import time

ROOT = str(Path(__file__).resolve().parent.parent)
sys.path.insert(0, os.path.join(ROOT, 'core'))
from chemdraw_tool import ui_capture

PY32 = os.path.join(ROOT, 'runtime', 'py32', 'python.exe')
CLI = os.path.join(ROOT, 'bin', 'cli.py')
MOL = os.path.join(ROOT, 'test', 'out', 'aspirin_kd.mol')

def run(args, timeout=90):
    proc = subprocess.run([PY32, CLI] + args, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout)
    return proc

if not os.path.isfile(MOL):
    print('generating molfile...')
    p = run(['kd', 'mol', 'CC(=O)Oc1ccccc1C(=O)O', '--out', MOL])
    print('  rc', p.returncode, (p.stderr or '')[:200])

print('opening in KingDraw (this takes a few seconds)...')
p = run(['kd', 'open', MOL, '--keep-open', '--timeout', '30'])
print('  rc', p.returncode, (p.stderr or '')[:300])
try:
    opened = json.loads(p.stdout)
except Exception:
    print('  stdout:', p.stdout[:300])
    raise SystemExit(1)
print('  ok:', opened.get('ok'), 'degraded:', opened.get('degraded'))
data = opened.get('data') or {}
pid = data.get('pid')
print('  pid:', pid, 'reused:', data.get('reused'))
if not pid:
    print('  no pid in payload; cannot screenshot')
    raise SystemExit(1)

time.sleep(3.0)
wins = [w for w in ui_capture._windows() if w['pid'] == pid]
print('  windows owned by pid %s: %d' % (pid, len(wins)))
for w in sorted(wins, key=lambda x: -( (x['rect'][2]-x['rect'][0]) * (x['rect'][3]-x['rect'][1]) )):
    area = (w['rect'][2]-w['rect'][0]) * (w['rect'][3]-w['rect'][1])
    print('    %-30s %s area=%d' % (w['title'][:30], w['rect'], area))
if not wins:
    print('  no windows; abort')
    raise SystemExit(1)

biggest = max(wins, key=lambda x: (x['rect'][2]-x['rect'][0]) * (x['rect'][3]-x['rect'][1]))
out = os.path.join(ROOT, 'test', 'out', 'kd_visual_%s.png' % pid)
shot = ui_capture.capture(biggest['hwnd'], out)
print('  capture ok:', shot.ok)
if shot.ok:
    print('  file:', shot.data['path'], shot.data['bytes'], 'bytes', shot.data['width'], 'x', shot.data['height'])
else:
    print('  failure:', shot.failure.to_dict())
