import win32gui, win32process

rows = []
def cb(hwnd, _):
    try:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title.strip():
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        cls = win32gui.GetClassName(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        rows.append((hwnd, pid, cls, title, rect))
    except Exception:
        pass
    return True
win32gui.EnumWindows(cb, None)

print('visible windows:', len(rows))
for hwnd, pid, cls, title, rect in rows:
    mark = ''
    low = (title + ' ' + cls).lower()
    if 'king' in low or 'chem' in low:
        mark = '  <== TARGET'
    print('  hwnd=%-9d pid=%-6d %-28s %-42s %s%s' % (hwnd, pid, cls[:28], title[:42], rect, mark))