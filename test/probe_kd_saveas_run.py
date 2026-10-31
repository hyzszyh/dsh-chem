'''Probe 6: drive 另存为 end to end and report every step.

Sequence: 菜单(M) -> 文件(F) -> 另存为(A) -> 浏览 -> file name edit (auto_id 1001)
-> 保存(S) (auto_id 1). Every step is UIA, no coordinate clicks.
'''
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))
from chemdraw_tool.adapters import kd_open  # noqa: E402

OUT = os.path.join(HERE, 'out')
TARGET = os.path.join(OUT, 'kd_probe_saved.king')


def attach(pid):
    from pywinauto import Application
    return Application(backend='uia').connect(process=pid)


def find(pid, auto_id=None, name=None, types=(), tries=6, pause=0.4):
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
        time.sleep(pause)
    return None


def step(el, label, how='invoke'):
    if el is None:
        print('%-28s MISSING' % label)
        return False
    try:
        getattr(el, how)()
        print('%-28s %s() ok' % (label, how))
        return True
    except Exception as exc:
        print('%-28s %s() %s: %s' % (label, how, type(exc).__name__, exc))
        return False


def main():
    if os.path.isfile(TARGET):
        os.remove(TARGET)
    pid = int(sys.argv[1])
    root = find(pid, auto_id='mRootMenu')
    if root is not None and find(pid, auto_id='mFileItem') is None:
        step(root, '菜单(M)', 'expand')
        time.sleep(0.8)
    fileitem = find(pid, auto_id='mFileItem')
    if not step(fileitem, '文件(F)', 'expand'):
        return 1
    time.sleep(0.8)
    if not step(find(pid, auto_id='mSaveAs'), '另存为(A)...', 'invoke'):
        return 1
    time.sleep(1.6)
    browse = find(pid, auto_id='btnOpenSaveFileDialog')
    if not step(browse, '浏览', 'invoke'):
        return 1
    time.sleep(2.0)
    edit = find(pid, auto_id='1001')
    print('file name edit:', bool(edit), repr(getattr(edit, 'window_text', lambda: '')()))
    if edit is None:
        return 1
    try:
        edit.set_edit_text(TARGET)
        print('set name -> %r' % TARGET)
    except Exception as exc:
        print('set_edit_text failed: %s: %s' % (type(exc).__name__, exc))
        try:
            edit.value_pattern.set_value(TARGET) if hasattr(edit, 'value_pattern') else None
            print('value_pattern fallback ok')
        except Exception as exc2:
            print('value_pattern failed:', exc2)
            return 1
    time.sleep(0.3)
    save_btn = find(pid, auto_id='1', name='保存(S)', types=('Button',))
    if not step(save_btn, '保存(S)', 'invoke'):
        return 1
    for i in range(12):
        time.sleep(0.5)
        if os.path.isfile(TARGET):
            print('target appeared after %.1fs, bytes=%d' % (0.5 * (i + 1), os.path.getsize(TARGET)))
            break
    else:
        print('target did NOT appear within 6s')
    app = attach(pid)
    for win in app.windows():
        try:
            title = win.window_text()
            texts = [el.element_info.name for el in win.descendants()
                     if el.element_info.control_type in ('Text', 'Button') and el.element_info.name]
        except Exception:
            continue
        print('window %r still has %d named texts; save-panel texts: %r' % (
            title, len(texts), [t for t in texts if '另存' in t or '保存' in t or '.king' in t][:6]))
    print('exists=%r size=%r' % (os.path.isfile(TARGET),
                                 os.path.getsize(TARGET) if os.path.isfile(TARGET) else None))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
