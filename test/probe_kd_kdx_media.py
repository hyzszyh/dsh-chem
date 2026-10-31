'''Probe: save a molecule as .kdx through UIA, then look at the preview images inside.

Answers two questions at once: does the UIA save-as recipe still work end to end,
and what exactly is in media/ of the ZIP KingDraw writes.
'''
import os
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))
from chemdraw_tool.adapters import kd_open  # noqa: E402

OUT = os.path.join(HERE, 'out')


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


def name_edit(pid):
    return pick(pid, lambda i, e: i.control_type == 'Edit' and i.class_name == 'Edit'
                and (i.name or '').startswith('文件名'))


def save_button(pid):
    return pick(pid, lambda i, e: i.control_type == 'Button' and i.automation_id == '1'
                and '保存' in (i.name or ''))


def save_as_kdx(pid, target_no_ext):
    if by_id(pid, 'mFileItem') is None:
        root = by_id(pid, 'mRootMenu')
        if root is None:
            print('no root menu'); return False
        root.expand(); time.sleep(0.8)
    item = by_id(pid, 'mFileItem')
    if item is None:
        print('no file menu'); return False
    try:
        item.expand()
    except Exception:
        pass
    time.sleep(0.8)
    sa = by_id(pid, 'mSaveAs')
    if sa is None:
        print('no mSaveAs'); return False
    sa.invoke(); time.sleep(1.6)
    browse = by_id(pid, 'btnOpenSaveFileDialog')
    if browse is None:
        print('no browse button'); return False
    browse.invoke(); time.sleep(2.2)
    edit = name_edit(pid)
    if edit is None:
        print('no file name edit'); return False
    edit.set_edit_text(target_no_ext)
    time.sleep(0.3)
    btn = save_button(pid)
    if btn is None:
        print('no save button'); return False
    btn.invoke()
    return True


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(OUT, 'kdx_probe_src.mol')
    base = os.path.join(OUT, 'kdx_probe_save')
    kdx = base + '.kdx'
    for path in (kdx,):
        if os.path.isfile(path):
            os.remove(path)
    for pid in kd_open.list_pids():
        kd_open.close_app(pid, 10.0)
    res = kd_open.open_file(src, timeout=25)
    print('open ok=%r pid=%r' % (res.ok, (res.data or {}).get('pid')))
    if not res.ok:
        print(res.failure.to_dict()); return 1
    pid = res.data['pid']
    if not save_as_kdx(pid, base):
        return 1
    for i in range(30):
        time.sleep(0.5)
        if os.path.isfile(kdx):
            print('kdx appeared after %.1fs bytes=%d' % (0.5 * (i + 1), os.path.getsize(kdx)))
            break
    else:
        print('kdx did NOT appear within 15s')
        return 1
    with zipfile.ZipFile(kdx) as zf:
        names = zf.namelist()
        print('zip entries: %d' % len(names))
        for info in zf.infolist():
            print('   %-40s %8d bytes  %s' % (info.filename, info.file_size,
                                              'DIR' if info.is_dir() else ''))
        media = [n for n in names if n.lower().startswith('media/')]
        print('media entries:', media)
    print('close:', kd_open.close_app(pid, 12.0).to_dict()['data'])
    print('left:', kd_open.list_pids())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
