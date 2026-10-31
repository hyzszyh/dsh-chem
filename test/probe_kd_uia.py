'''Probe: what does UIAutomation actually show for a KingDraw window?

Runs under the 64-bit interpreter (pywinauto lives there; the bundled 32-bit
runtime has neither pywinauto nor comtypes -- measured). Opens a document through
kd_open and dumps the UIA descendants that matter: every TabItem, every name that
carries the file stem, and a control-type census. Closes only its own instance.

Usage: python test/probe_kd_uia.py [path] [--keep] [--limit N]
'''
from __future__ import annotations

import collections
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))

from chemdraw_tool.adapters import kd_open as op  # noqa: E402

SAMPLE = os.path.join(op.find_home() or r'D:\tool\KingDraw', 'Cyclohexane.king')


def collect(pid: int, limit: int = 4000) -> dict:
    from pywinauto import Application
    started = time.monotonic()
    app = Application(backend='uia').connect(process=pid, timeout=10)
    connect_s = time.monotonic() - started
    win = app.top_window()
    walk_started = time.monotonic()
    rows = []
    try:
        descendants = win.descendants()
    except Exception as exc:
        return {'connect_s': round(connect_s, 2),
                'error': '%s: %s' % (type(exc).__name__, exc)}
    for element in descendants[:limit]:
        try:
            info = element.element_info
            rows.append({'type': info.control_type or '', 'name': info.name or '',
                         'auto_id': info.automation_id or '',
                         'class': info.class_name or ''})
        except Exception:
            continue
    return {'connect_s': round(connect_s, 2),
            'walk_s': round(time.monotonic() - walk_started, 2),
            'count': len(rows), 'window_title': win.window_text(), 'rows': rows}


def main(argv) -> int:
    path = SAMPLE
    limit = 4000
    for i, a in enumerate(argv):
        if a == '--limit':
            limit = int(argv[i + 1])
        elif not a.startswith('--'):
            path = a
    if not os.path.isfile(path):
        print('missing input:', path)
        return 2
    try:
        import pywinauto  # noqa: F401
    except Exception as exc:
        print('pywinauto not importable here:', exc)
        return 3
    stem = os.path.splitext(os.path.basename(path))[0]
    pre = op.list_pids()
    print('pids before:', pre, '| input:', os.path.basename(path), '| stem:', stem)
    res = op.open_file(path, timeout=20)
    print('open ok=', res.ok, 'pid=', res.data.get('pid'), 'reused=', res.data.get('reused'))
    if not res.ok:
        return 1
    pid = res.data['pid']
    time.sleep(1.0)  # let the document tab settle
    out = collect(pid, limit)
    if 'error' in out:
        print('collect error:', out['error'])
        return 1
    census = collections.Counter(r['type'] for r in out['rows'])
    print('connect_s=', out['connect_s'], 'walk_s=', out['walk_s'], 'count=', out['count'])
    print('control types:', dict(census.most_common(12)))
    tabs = [r for r in out['rows'] if r['type'] == 'TabItem']
    print('TabItems (%d):' % len(tabs))
    for r in tabs:
        print('   name=%r auto_id=%r class=%r' % (r['name'][:70], r['auto_id'][:40], r['class'][:40]))
    hits = [r for r in out['rows'] if stem.lower() in r['name'].lower()]
    print('rows containing stem (%d):' % len(hits))
    for r in hits:
        print('   %-12s %r' % (r['type'], r['name'][:80]))
    docish = [r for r in out['rows']
              if 'document' in (r['name'] + r['class'] + r['auto_id']).lower()]
    print('document-ish rows (%d):' % len(docish))
    for r in docish[:10]:
        print('   %-12s name=%r class=%r auto=%r' % (r['type'], r['name'][:50], r['class'][:40], r['auto_id'][:30]))
    if '--keep' not in argv:
        print('close:', op.close_app(pid, 12.0).to_dict()['data'])
    print('left:', op.list_pids())
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
