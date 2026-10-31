'''Probe 8: what save types does the KingDraw save dialog offer?'''
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))


def attach(pid):
    from pywinauto import Application
    return Application(backend='uia').connect(process=pid)


def pick(pid, pred, tries=8, pause=0.4):
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
    menu_save_as = pick(pid, lambda i, el: i.automation_id == 'mSaveAs')
    if menu_save_as is not None:
        root = pick(pid, lambda i, el: i.automation_id == 'mRootMenu')
        if pick(pid, lambda i, el: i.automation_id == 'mFileItem') is None:
            root.expand()
            time.sleep(0.8)
        pick(pid, lambda i, el: i.automation_id == 'mFileItem').expand()
        time.sleep(0.8)
        menu_save_as.invoke()
        time.sleep(1.6)
    browse = pick(pid, lambda i, el: i.automation_id == 'btnOpenSaveFileDialog')
    if browse is not None:
        browse.invoke()
        time.sleep(2.0)
    for auto in ('FileTypeControlHost', 'FileNameControlHost'):
        el = pick(pid, lambda i, e, a=auto: i.automation_id == a)
        print('%s: %r' % (auto, el is not None))
        if el is None:
            continue
        info = el.element_info
        print('   name=%r type=%r class=%r' % (info.name, info.control_type, info.class_name))
        try:
            print('   value=%r' % (el.get_value(),))
        except Exception as exc:
            print('   get_value: %s' % type(exc).__name__)
        try:
            el.expand()
            time.sleep(1.0)
            items = [(x.element_info.control_type, x.element_info.name)
                     for x in el.descendants()]
            print('   children:', items[:12])
        except Exception as exc:
            print('   expand: %s: %s' % (type(exc).__name__, exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
