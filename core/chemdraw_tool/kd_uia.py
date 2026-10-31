'''Read KingDraw's UI Automation tree: the direct evidence that a document opened.

Measured on this machine (test/probe_kd_uia.py):

* pywinauto 0.6.9 + comtypes live in the 64-bit Python 3.11; the bundled 32-bit
  runtime has neither, so this module only runs in a 64-bit process and kd_open
  bridges to it when it is invoked from the 32-bit one.
* Connecting costs ~0 ms and walking the whole window ~0.45 s / ~300 elements.
* The document is visible as a TabItem named 'KingDraw.WpfForm.KDLayoutDocument'
  whose subtree carries the file name as Text ('uia_probe_doc.mol') and the bare
  stem ('uia_probe_doc'); a Button with automation_id 'DocumentCloseButton' sits
  next to it.
* That name is an exact string, so "the document opened" becomes a comparison
  instead of a pixel guess. The pixels stay useful only as chrome evidence:
  PrintWindow renders 94% white / black client area because KingDraw draws on a
  WPF/D3D surface that never reaches GDI.

Stdin is not used; argv[1] is the pid. Output is one JSON object on stdout so the
32-bit caller can parse it without importing anything.
'''

from __future__ import annotations

import collections
import json
import sys
import time

DOC_TAB_MARKER = 'KDLayoutDocument'
DOC_CLOSE_AUTO_ID = 'DocumentCloseButton'


def _import_pywinauto():
    try:
        from pywinauto import Application
        return Application
    except Exception:
        return None


def available() -> bool:
    '''True when this interpreter can read UIA at all.'''
    return _import_pywinauto() is not None


def collect(pid: int, timeout: float = 10.0, max_elements: int = 5000) -> dict:
    '''Return the UIA picture of one KingDraw process.

    Keys: ok, window_title, documents (one entry per KDLayoutDocument tab with the
    text it carries), tabs, controls (control-type census), count, walk_s, error.
    '''
    Application = _import_pywinauto()
    if Application is None:
        return {'ok': False, 'error': 'pywinauto unavailable in this interpreter',
                'code': 'E08'}
    started = time.monotonic()
    app = Application(backend='uia').connect(process=pid, timeout=timeout)
    connect_s = time.monotonic() - started
    window = app.top_window()
    try:
        window.wait('exists ready', timeout=timeout)
    except Exception as exc:
        return {'ok': False, 'code': 'E05',
                'error': 'window never became ready: %s' % exc,
                'connect_s': round(connect_s, 2)}
    walk_started = time.monotonic()
    rows = []
    for element in window.descendants()[:max_elements]:
        try:
            info = element.element_info
            rows.append({
                'type': info.control_type or '',
                'name': info.name or '',
                'auto_id': info.automation_id or '',
                'class': info.class_name or '',
            })
        except Exception:
            continue
    walk_s = time.monotonic() - walk_started
    census = collections.Counter(r['type'] for r in rows)
    tabs = [r for r in rows if r['type'] == 'TabItem']
    documents = []
    for tab in tabs:
        blob = (tab['name'] + ' ' + tab['auto_id'] + ' ' + tab['class']).lower()
        is_doc = DOC_TAB_MARKER.lower() in blob or 'document' in blob
        if not is_doc:
            continue
        texts = []

        def walk(element, depth=0):
            if depth > 6 or len(texts) > 40:
                return
            try:
                children = element.children()
            except Exception:
                return
            for child in children:
                try:
                    info = child.element_info
                except Exception:
                    continue
                name = info.name or ''
                if name and info.control_type in ('Text', 'Edit', 'Document'):
                    texts.append({'type': info.control_type, 'name': name,
                                  'auto_id': info.automation_id or ''})
                walk(child, depth + 1)

        try:
            for element in window.descendants(control_type='TabItem'):
                if (element.element_info.name or '') == tab['name'] and \
                        DOC_TAB_MARKER.lower() in (tab['name'] + tab['class']).lower():
                    walk(element)
                    break
        except Exception:
            pass
        if not texts:
            # Flat fallback: any Text whose content names a chemistry file.
            for row in rows:
                if row['type'] != 'Text':
                    continue
                low = row['name'].lower()
                if low.endswith(('.mol', '.king', '.cdx', '.cdxml', '.sdf')):
                    texts.append({'type': 'Text', 'name': row['name'],
                                  'auto_id': row['auto_id']})
        documents.append({'tab_name': tab['name'], 'auto_id': tab['auto_id'],
                          'texts': texts})
    return {
        'ok': True,
        'pid': pid,
        'window_title': window.window_text(),
        'documents': documents,
        'document_count': len(documents),
        'tabs': [{'name': t['name'], 'auto_id': t['auto_id']} for t in tabs],
        'controls': dict(census.most_common(15)),
        'count': len(rows),
        'connect_s': round(connect_s, 2),
        'walk_s': round(walk_s, 2),
        'source': 'pywinauto',
    }


def main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    if not argv:
        sys.stdout.write(json.dumps({'ok': False, 'error': 'usage: kd_uia.py <pid>',
                                     'code': 'E99'}))
        return 2
    try:
        pid = int(argv[0])
    except ValueError:
        sys.stdout.write(json.dumps({'ok': False, 'code': 'E99',
                                     'error': 'pid is not an integer: %r' % argv[0]}))
        return 2
    try:
        payload = collect(pid)
    except Exception as exc:
        payload = {'ok': False, 'code': 'E99',
                   'error': '%s: %s' % (type(exc).__name__, exc)}
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    return 0 if payload.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
