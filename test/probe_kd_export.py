'''Probe 11: what does 文件 -> 导出 offer?'''
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))


def attach(pid):
    from pywinauto import Application
    return Application(backend='uia').connect(process=pid)


def dump(pid, tag):
    rows = []
    app = attach(pid)
    for win in app.windows():
        try:
            for el in win.descendants():
                i = el.element_info
                rows.append((i.control_type, i.name, i.automation_id))
        except Exception:
            continue
    print('[%s] %d elements' % (tag, len(rows)))
    for ct, name, auto in rows:
        if name and ct in ('Text', 'Button', 'MenuItem', 'ComboBox', 'TabItem', 'ListItem'):
            print('   %-9s %-40r %r' % (ct, name[:40], auto))
    return rows


def pick(pid, auto_id, tries=8):
    for _ in range(tries):
        app = attach(pid)
        for win in app.windows():
            try:
                for el in win.descendants():
                    if el.element_info.automation_id == auto_id:
                        return el
            except Exception:
                continue
        time.sleep(0.4)
    return None


def main():
    pid = int(sys.argv[1])
    if pick(pid, 'mFileItem', 2) is None:
        root = pick(pid, 'mRootMenu')
        if root is None:
            print('no menu'); return 1
        root.expand(); time.sleep(0.8)
    item = pick(pid, 'mFileItem')
    if item is not None:
        try:
            item.expand()
        except Exception:
            pass
        time.sleep(0.8)
    exp = pick(pid, 'mExport')
    print('mExport:', exp is not None)
    if exp is None:
        return 1
    exp.invoke()
    time.sleep(1.8)
    dump(pid, 'after-export')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
