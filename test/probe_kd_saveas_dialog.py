'''Probe 4: invoke 另存为(A)... and describe the dialog it opens.

Prints every top-level window of the process with its class and the controls that
matter for a file dialog (Edit / ComboBox / Button with names), then cancels the
dialog through UIA so nothing is written behind the user's back.
'''
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


def find(pid, auto_id=None, name=None, tries=3, types=('MenuItem',)):
    for _ in range(tries):
        app = attach(pid)
        for win in app.windows():
            try:
                for el in win.descendants():
                    info = el.element_info
                    if auto_id and info.automation_id == auto_id:
                        return el
                    if name and (info.name or '') == name and (
                            not types or info.control_type in types):
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
            title = win.window_text()
            info = win.element_info
            entry = {'title': title, 'class': info.class_name,
                     'auto_id': info.automation_id, 'controls': []}
            for el in win.descendants():
                i = el.element_info
                if i.control_type in ('Edit', 'ComboBox', 'Button', 'Text', 'Document',
                                      'TreeItem', 'ListItem'):
                    entry['controls'].append({'type': i.control_type, 'name': i.name,
                                              'auto_id': i.automation_id,
                                              'class': i.class_name})
        except Exception as exc:
            entry = {'title': '<error>', 'class': str(exc), 'controls': []}
        report.append(entry)
    with open(os.path.join(OUT, 'kd_uia_%s.json' % tag), 'w', encoding='utf-8') as fh:
        json.dump(report, fh, ensure_ascii=False, indent=1)
    for entry in report:
        print('[%s] window %r class=%r auto_id=%r controls=%d' % (
            tag, entry['title'][:40], entry['class'], entry['auto_id'],
            len(entry['controls'])))
        for c in entry['controls'][:25]:
            print('     %-10s %-30r auto_id=%-22r' % (
                c['type'], (c['name'] or '')[:30], c['auto_id']))
    return report


def main():
    pid = int(sys.argv[1])
    print('--- before ---')
    describe(pid, 'saveas_before')
    item = find(pid, auto_id='mSaveAs')
    print('mSaveAs found:', bool(item))
    if item is None:
        return 1
    for how in ('invoke', 'click_input'):
        try:
            getattr(item, how)()
            print('%s() ok' % how)
        except Exception as exc:
            print('%s() failed: %s: %s' % (how, type(exc).__name__, exc))
            continue
        break
    time.sleep(1.6)
    print('--- after ---')
    describe(pid, 'saveas_after')
    cancel = find(pid, name='取消', tries=2, types=('Button',)) or find(
        pid, name='Cancel', tries=1, types=('Button',))
    if cancel is not None:
        try:
            cancel.invoke()
            print('cancel invoked')
        except Exception as exc:
            print('cancel failed:', exc)
        time.sleep(0.8)
    else:
        print('no cancel button found; leaving the dialog for inspection')
    describe(pid, 'saveas_cancelled')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
