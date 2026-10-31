'''Probe 7: drive 另存为 with precise selectors and report the outcome.

The file name Edit is chosen by (control_type == 'Edit', class_name == 'Edit',
name startswith '文件名'), never by auto_id alone: the dialog's address bar also
reports auto_id 1001 and selecting it silently typed into the wrong box.
'''
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))

OUT = os.path.join(HERE, 'out')
TARGET = os.path.join(OUT, 'kd_probe_saved.king')


def attach(pid):
    from pywinauto import Application
    return Application(backend='uia').connect(process=pid)


def all_elements(pid):
    app = attach(pid)
    for win in app.windows():
        try:
            for el in win.descendants():
                yield el
        except Exception:
            continue


def pick(pid, pred, tries=8, pause=0.4):
    for _ in range(tries):
        for el in all_elements(pid):
            try:
                if pred(el.element_info, el):
                    return el
            except Exception:
                continue
        time.sleep(pause)
    return None


def name_edit(pid):
    return pick(pid, lambda i, el: i.control_type == 'Edit' and i.class_name == 'Edit'
                and (i.name or '').startswith('文件名'))


def save_button(pid):
    return pick(pid, lambda i, el: i.control_type == 'Button' and i.automation_id == '1'
                and '保存' in (i.name or ''))


def menu(pid, auto_id):
    return pick(pid, lambda i, el: i.control_type == 'MenuItem' and i.automation_id == auto_id)


def click(el, label, how='invoke'):
    if el is None:
        print('%-16s MISSING' % label)
        return False
    try:
        getattr(el, how)()
        print('%-16s %s() ok' % (label, how))
        return True
    except Exception as exc:
        print('%-16s %s() %s: %s' % (label, how, type(exc).__name__, exc))
        return False


def main():
    if os.path.isfile(TARGET):
        os.remove(TARGET)
    pid = int(sys.argv[1])
    root = menu(pid, 'mRootMenu')
    if root is not None and menu(pid, 'mFileItem') is None:
        click(root, '菜单(M)', 'expand')
        time.sleep(0.8)
    if not click(menu(pid, 'mFileItem'), '文件(F)', 'expand'):
        return 1
    time.sleep(0.8)
    if not click(menu(pid, 'mSaveAs'), '另存为(A)', 'invoke'):
        return 1
    time.sleep(1.6)
    if not click(pick(pid, lambda i, el: i.automation_id == 'btnOpenSaveFileDialog'),
                 '浏览', 'invoke'):
        return 1
    time.sleep(2.2)
    edit = name_edit(pid)
    if edit is None:
        print('name edit not found; dumping Edit candidates')
        for el in all_elements(pid):
            i = el.element_info
            if i.control_type == 'Edit':
                print('   Edit name=%r auto_id=%r class=%r' % (i.name, i.automation_id, i.class_name))
        return 1
    print('name edit: name=%r auto_id=%r class=%r' % (
        edit.element_info.name, edit.element_info.automation_id, edit.element_info.class_name))
    edit.set_edit_text(TARGET)
    time.sleep(0.3)
    print('typed %r; field now %r' % (TARGET, edit.window_text()))
    if not click(save_button(pid), '保存(S)', 'invoke'):
        return 1
    for i in range(20):
        time.sleep(0.5)
        if os.path.isfile(TARGET):
            print('target appeared after %.1fs, bytes=%d' % (0.5 * (i + 1), os.path.getsize(TARGET)))
            break
    else:
        print('target did NOT appear within 10s')
        names = [(el.element_info.control_type, el.element_info.name)
                 for el in all_elements(pid) if el.element_info.name]
        print('dialog texts now:', [n for n in names if '保存' in n[1] or '另存' in n[1] or '.king' in n[1]][:10])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
