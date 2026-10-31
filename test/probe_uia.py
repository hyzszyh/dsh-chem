from pathlib import Path
'''What is actually inside KingDraw's window, according to UIAutomation?

PrintWindow returns the title bar and a black client area: WPF draws through
D3D, so the pixels never reach a GDI surface. The accessibility tree does
survive though, and it answers the question the screenshot was supposed to
answer - is this document open - with text instead of pixels.'''
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'core'))
from pywinauto import Application

PID = int(sys.argv[1]) if len(sys.argv) > 1 else None
if PID is None:
    from chemdraw_tool import ui_capture
    win = ui_capture.find_window('KingDraw', exact_only=True)
    if not win:
        print('KingDraw is not running')
        raise SystemExit(1)
    PID = win['pid']

print('connecting to pid', PID)
app = Application(backend='uia').connect(process=PID, timeout=15)
win = app.top_window()
print('top window:', repr(win.window_text()), 'class:', win.class_name())

seen = []
try:
    for child in win.descendants():
        try:
            ctype = child.element_info.control_type
            text = child.window_text()
        except Exception:
            continue
        if not text and ctype not in ('Document', 'Pane', 'Tab', 'TabItem'):
            continue
        seen.append((ctype, text))
        if len(seen) >= 45:
            break
except Exception as exc:
    print('walk failed:', type(exc).__name__, exc)

print('nodes with text:', len(seen))
for ctype, text in seen:
    print('  %-18s %s' % (ctype, text[:70]))