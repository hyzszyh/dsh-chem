from pathlib import Path
'''Can a WPF window be photographed at all on this machine?

ImageGrab returns the desktop pixels, which is why a background KingDraw came
back as the browser that covered it. Bringing it to the top returns white: WPF
draws through DirectComposition, so the content never lands on a GDI surface
that BitBlt can read. PrintWindow with PW_RENDERFULLCONTENT asks DWM to hand
back the composed frame instead, which is the documented way through.

This probe reports the colour spread of each attempt so 'blank' is measured,
not assumed.'''
import ctypes
import os
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'core'))
from PIL import Image
from chemdraw_tool import ui_capture

PW_RENDERFULLCONTENT = 0x00000002


def spread(path):
    im = Image.open(path).convert('RGB')
    colors = im.getcolors(maxcolors=1 << 24)
    distinct = len(colors) if colors else -1
    white = 0.0
    if colors:
        total = im.width * im.height
        white = round(sum(c for c, px in colors if px == (255, 255, 255)) * 100.0 / total, 2)
    return distinct, white


def print_window(hwnd, out_path, flag):
    import win32gui
    import win32ui
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)
    ok = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), flag)
    bitmap.SaveBitmapFile(save_dc, out_path)
    win32gui.DeleteObject(bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    return ok, width, height


win = ui_capture.find_window('KingDraw', exact_only=True)
if not win:
    print('KingDraw is not running; nothing to photograph')
    raise SystemExit(1)
hwnd = win['hwnd']
print('window: pid=%s hwnd=%s rect=%s' % (win['pid'], hwnd, win['rect']))
ui_capture.flash_to_front(hwnd)

outdir = str(Path(__file__).resolve().parent.parent / 'test' / 'out')
for flag, label in ((0, 'plain'), (PW_RENDERFULLCONTENT, 'renderfull')):
    path = os.path.join(outdir, 'kd_pw_%s.png' % label)
    try:
        ok, w, h = print_window(hwnd, path, flag)
        distinct, white = spread(path)
        print('  PrintWindow(%s): ret=%s %dx%d bytes=%d colors=%d white%%=%s'
              % (label, ok, w, h, os.path.getsize(path), distinct, white))
    except Exception as exc:
        print('  PrintWindow(%s) failed: %s: %s' % (label, type(exc).__name__, exc))
ui_capture.release_topmost(hwnd)