'''Probe 10: save-type choices, robustly.'''
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))


def attach(pid):
    from pywinauto import Application
    return Application(backend='uia').connect(process=pid)


def pick(pid, pred, tries=10, pause=0.4):
    for _ in range(tries):
        app = attach(pid)
        for win in app.windows():
            try:
                for el in win.descendants():
                    if pred(el.element_info, el):
                        return el
            except Exception:
                continue
        time.sleep(pause)
    return None


def main():
    pid = int(sys.argv[1])
    combo = pick(pid, lambda i, e: i.automation_id == 'FileTypeControlHost')
    print('combo:', combo is not None)
    if combo is None:
        return 1
    for label in ('texts', 'selected_text', 'value'):
        try:
            print('  %s -> %r' % (label, getattr(combo, label)()))
        except Exception as exc:
            print('  %s -> %s' % (label, type(exc).__name__))
    try:
        combo.expand()
        print('  expand ok')
    except Exception as exc:
        print('  expand -> %s: %s' % (type(exc).__name__, exc))
    time.sleep(1.2)
    rows = []
    app = attach(pid)
    for win in app.windows():
        try:
            for el in win.descendants():
                i = el.element_info
                if i.control_type in ('ListItem', 'MenuItem', 'TreeItem'):
                    rows.append((i.control_type, i.name, i.automation_id))
        except Exception:
            continue
    print('  list/menu items now:', rows[:20])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
