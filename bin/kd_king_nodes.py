'''Print what GRDKitDll reads back from a .king, as one JSON line (32-bit only).'''
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))

from chemdraw_tool.adapters import kd_native  # noqa: E402


def main(argv):
    if len(argv) < 2:
        print(json.dumps({'ok': False, 'error': 'usage: kd_king_nodes.py <file.king>'}))
        return 2
    path = argv[1]
    try:
        with open(path, 'rb') as fh:
            blob = fh.read()
    except OSError as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}))
        return 1
    res = kd_native.sup_king_to_json(blob)
    if not res.ok:
        print(json.dumps({'ok': False, 'error': res.failure.code,
                          'detail': res.failure.detail[:300],
                          'bytes': len(blob)}))
        return 1
    try:
        doc = json.loads(res.data['text'])
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': 'unparsable json: %s' % exc}))
        return 1
    data = doc.get('data') or {}
    print(json.dumps({
        'ok': True, 'bytes': len(blob), 'success': doc.get('success'),
        'code': doc.get('code'), 'type': data.get('type'),
        'nodes': data.get('nodes') or [], 'bonds': data.get('bonds') or [],
        'texts': data.get('texts') or [], 'shapes': data.get('shapes') or [],
        'json_chars': len(res.data.get('text') or ''),
    }, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
