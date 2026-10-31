from pathlib import Path
import json, subprocess, sys
data = open(r'D:/tool/KingDraw/Cyclohexane.king', 'rb').read()
req = json.dumps({'op': 'sup_king_to_json', 'args': {'king_bytes': list(data)}})
p = subprocess.run([str(Path(__file__).resolve().parent.parent / 'runtime' / 'py32' / 'python.exe'),
                    str(Path(__file__).resolve().parent.parent / 'bin' / 'kd_worker.py')],
                   input=req, capture_output=True, text=True, encoding='utf-8')
out = p.stdout.strip()
print('len', len(out))
obj = json.loads(out)
print('ok', obj.get('ok'))
d = obj.get('data')
print('type', type(d).__name__)
if isinstance(d, dict):
    print('keys', list(d)[:8])
    inner = d.get('data') or {}
    print('inner keys', list(inner)[:8] if isinstance(inner, dict) else type(inner).__name__)
    if isinstance(inner, dict) and 'nodes' in inner:
        print('nodes', len(inner['nodes']), 'first', inner['nodes'][0])