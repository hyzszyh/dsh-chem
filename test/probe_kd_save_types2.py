'''Probe 9: enumerate the save-type choices of the KingDraw save dialog.'''
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


def by_id(pid, auto_id):
    return pick(pid, lambda i, e: i.automation_id == auto_id)


def main():
    pid = int(sys.argv[1])
    if by_id(pid, 'mFileItem') is None:
        root = by_id(pid, 'mRootMenu')
        if root is None:
            print('no root menu'); return 1
        root.expand(); time.sleep(0.8)
    if by_id(pid, 'btnOpenSaveFileDialog') is None:
        item = by_id(pid, 'mFileItem')
        if item is not None:
            try:
                item.expand()
            except Exception as exc:
                print('file expand:', exc)
            time.sleep(0.8)
        sa = by_id(pid, 'mSaveAs')
        print('mSaveAs:', sa is not None)
        if sa is not None:
            sa.invoke(); time.sleep(1.6)
        br = by_id(pid, 'btnOpenSaveFileDialog')
        print('browse:', br is not None)
        if br is not None:
            br.invoke(); time.sleep(2.2)
    combo = pick(pid, lambda i, e: i.control_type == 'ComboBox'
                 and ('保存类型' in (i.name or '') or i.automation_id == 'FileTypeControlHost'))
    print('save-type combo:', combo is not None)
    if combo is not None:
        print('   name=%r auto_id=%r' % (combo.element_info.name, combo.element_info.automation_id))
        for label, fn in (('texts', combo.texts), ('item_texts', combo.item_texts),
                          ('selected_text', combo.selected_text)):
            try:
                print('   %s -> %r' % (label, fn()))
            except Exception as exc:
                print('   %s -> %s' % (label, type(exc).__name__))
        try:
            combo.expand()
            time.sleep(1.0)
            kids = [(x.element_info.control_type, x.element_info.name)
                    for x in combo.descendants()]
            print('   expanded children:', kids[:12])
        except Exception as exc:
            print('   expand -> %s: %s' % (type(exc).__name__, exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
