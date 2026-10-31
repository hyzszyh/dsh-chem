'''Probe 3: expand 菜单(M) -> 文件(F) over UIA and list the file submenu.

No coordinates are clicked. Prints every MenuItem seen after each expansion so the
save command can be located by name/automation id.
'''
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))
from chemdraw_tool.adapters import kd_open  # noqa: E402

OUT = os.path.join(HERE, 'out')


def snap(pid):
    from pywinauto import Application
    app = Application(backend='uia').connect(process=pid)
    rows = []
    for win in app.windows():
        try:
            for el in win.descendants():
                info = el.element_info
                rows.append({'type': info.control_type, 'name': info.name,
                             'auto_id': info.automation_id, 'class': info.class_name,
                             'win': win.window_text()})
        except Exception:
            continue
    return rows


def find(pid, auto_id=None, name=None, tries=3):
    from pywinauto import Application
    for attempt in range(tries):
        app = Application(backend='uia').connect(process=pid)
        for win in app.windows():
            try:
                for el in win.descendants():
                    info = el.element_info
                    if auto_id and info.automation_id == auto_id:
                        return el
                    if name and (info.name or '') == name and info.control_type == 'MenuItem':
                        return el
            except Exception:
                continue
        time.sleep(0.4)
    return None


def show(rows, tag):
    items = [r for r in rows if r['type'] in ('MenuItem', 'Button')
             and (r['name'] or r['auto_id'])]
    print('[%s] %d rows, %d named menu/button rows' % (tag, len(rows), len(items)))
    for r in items:
        print('   %-9s %-26r auto_id=%-20r' % (r['type'], (r['name'] or '')[:26], r['auto_id']))
    path = os.path.join(OUT, 'kd_uia_%s.json' % tag)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(rows, fh, ensure_ascii=False, indent=1)


def main():
    pid = int(sys.argv[1])
    fileitem = find(pid, auto_id='mFileItem')
    if fileitem is None:
        root = find(pid, auto_id='mRootMenu')
        print('root menu:', bool(root))
        if root is None:
            return 1
        root.expand()
        time.sleep(0.9)
        fileitem = find(pid, auto_id='mFileItem')
    print('file item:', bool(fileitem))
    if fileitem is None:
        return 1
    show(snap(pid), 'menu_open')
    for how in ('expand', 'click_input'):
        try:
            getattr(fileitem, how)()
            print('%s() ok on 文件(F)' % how)
        except Exception as exc:
            print('%s() failed: %s' % (how, exc))
            continue
        break
    time.sleep(0.9)
    show(snap(pid), 'file_open')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
