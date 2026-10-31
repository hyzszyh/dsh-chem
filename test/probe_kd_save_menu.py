'''Probe 2: expand KingDraw's root menu over UIA and look for a save command.

Writes every element of every window the process owns to test/out/kd_uia_menu.json
and prints the save-ish rows. No clicks at coordinates, no blind typing.
'''
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))
from chemdraw_tool.adapters import kd_open  # noqa: E402

OUT = os.path.join(HERE, 'out')
HINTS = ('save', '保存', '另存', 'store', 'export', '导出')


def rows_of(ctrl, limit=900):
    out = []
    for el in ctrl.descendants():
        info = el.element_info
        try:
            out.append({'type': info.control_type, 'name': info.name,
                        'auto_id': info.automation_id, 'class': info.class_name})
        except Exception as exc:
            out.append({'error': str(exc)})
        if len(out) >= limit:
            break
    return out


def attach(pid):
    from pywinauto import Application
    return Application(backend='uia').connect(process=pid)


def walk_all(pid, tag):
    app = attach(pid)
    windows = app.windows()
    print('[%s] windows=%d' % (tag, len(windows)))
    dump = {}
    for win in windows:
        try:
            title = win.window_text()
            rows = rows_of(win)
        except Exception as exc:
            print('  window error: %s' % exc)
            continue
        dump[title or '<untitled>'] = rows
        print('  window %r elements=%d' % (title, len(rows)))
    path = os.path.join(OUT, 'kd_uia_%s.json' % tag)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(dump, fh, ensure_ascii=False, indent=1)
    print('  dump -> %s' % path)
    hits = 0
    for title, rows in dump.items():
        for row in rows:
            name = (row.get('name') or '')
            if any(h in name.lower() for h in HINTS):
                print('  HIT [%s] %-14s %r auto_id=%r' % (
                    title[:18], row.get('type'), name[:30], row.get('auto_id')))
                hits += 1
    print('  save-ish hits=%d' % hits)
    return dump


def main():
    pid = int(sys.argv[1])
    print('pid=%d alive=%r' % (pid, pid in kd_open.list_pids()))
    walk_all(pid, 'before')
    app = attach(pid)
    win = app.top_window()
    menu = None
    for el in win.descendants():
        info = el.element_info
        if info.automation_id == 'mRootMenu':
            menu = el
            break
    if menu is None:
        print('mRootMenu NOT FOUND')
        return 1
    print('menu found: name=%r type=%r' % (menu.element_info.name,
                                           menu.element_info.control_type))
    print('patterns:', [p for p in ('invoke', 'expand_collapse', 'selection_item',
                                    'legacy') if menu.is_enabled() and getattr(menu, 'iface_' , None) is not None][:6])
    for how in ('invoke', 'expand', 'click_input'):
        try:
            getattr(menu, how)()
            print('  %s(): ok' % how)
        except Exception as exc:
            print('  %s(): %s: %s' % (how, type(exc).__name__, exc))
            continue
        time.sleep(0.8)
        walk_all(pid, 'after_' + how)
        break
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
