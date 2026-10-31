'''Probe 5: click 浏览 (btnOpenSaveFileDialog) and describe the native save dialog.'''
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))
OUT = os.path.join(HERE, 'out')


def attach(pid):
    from pywinauto import Application
    return Application(backend='uia').connect(process=pid)


def find(pid, auto_id=None, name=None, types=(), tries=3):
    for _ in range(tries):
        app = attach(pid)
        for win in app.windows():
            try:
                for el in win.descendants():
                    i = el.element_info
                    if auto_id and i.automation_id == auto_id:
                        return el
                    if name and (i.name or '') == name and (not types or i.control_type in types):
                        return el
            except Exception:
                continue
        time.sleep(0.4)
    return None


def describe(pid, tag):
    app = attach(pid)
    report = []
    for win in app.windows():
        try:
            i = win.element_info
            entry = {'title': win.window_text(), 'class': i.class_name,
                     'auto_id': i.automation_id, 'controls': []}
            for el in win.descendants():
                c = el.element_info
                entry['controls'].append({'type': c.control_type, 'name': c.name,
                                          'auto_id': c.automation_id, 'class': c.class_name})
        except Exception as exc:
            entry = {'title': '<error>', 'class': str(exc), 'controls': []}
        report.append(entry)
    with open(os.path.join(OUT, 'kd_uia_%s.json' % tag), 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    for entry in report:
        print('[%s] window %r class=%r auto_id=%r controls=%d' % (
            tag, entry['title'][:46], entry['class'], entry['auto_id'], len(entry['controls'])))
        for c in entry['controls']:
            if c['type'] in ('Edit', 'ComboBox', 'Button', 'ToolBar', 'TreeItem'):
                print('     %-9s %-34r auto_id=%-18r class=%r' % (
                    c['type'], (c['name'] or '')[:34], c['auto_id'], (c['class'] or '')[:18]))
    return report


def main():
    pid = int(sys.argv[1])
    browse = find(pid, auto_id='btnOpenSaveFileDialog')
    print('browse button:', bool(browse))
    if browse is None:
        return 1
    for how in ('invoke', 'click_input'):
        try:
            getattr(browse, how)()
            print('%s() ok on 浏览' % how)
            break
        except Exception as exc:
            print('%s() failed: %s' % (how, exc))
    time.sleep(2.0)
    describe(pid, 'filedialog')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
