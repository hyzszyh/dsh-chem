'''Probe: capture a KingDraw window to PNG using ctypes GDI + zlib only.

Deliberately avoids PIL/pyautogui so the capture works in the bundled 32-bit
runtime too (and so the channel keeps one dependency-free implementation).
Prints bytes, dimensions, and a colour-variety metric that separates a blank
window from a rendered one.

Usage: python test/probe_kd_capture.py [png out path]
'''
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import tempfile
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'core'))
from chemdraw_tool.adapters import kd_native as kd  # noqa: E402
from chemdraw_tool.adapters import kd_open as op  # noqa: E402

user32 = op._user32
gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
SW_RESTORE = 9
PW_RENDERFULLCONTENT = 0x00000002

gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         ctypes.c_int, wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
gdi32.BitBlt.restype = wt.BOOL
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteObject.restype = wt.BOOL
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.DeleteDC.restype = wt.BOOL
user32.GetWindowDC.argtypes = [wt.HWND]
user32.GetWindowDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.GetWindowRect.restype = wt.BOOL
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.ShowWindow.restype = wt.BOOL
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.SetForegroundWindow.restype = wt.BOOL
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
user32.PrintWindow.restype = wt.BOOL


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ('biSize', wt.DWORD), ('biWidth', ctypes.c_long), ('biHeight', ctypes.c_long),
        ('biPlanes', wt.WORD), ('biBitCount', wt.WORD), ('biCompression', wt.DWORD),
        ('biSizeImage', wt.DWORD), ('biXPelsPerMeter', ctypes.c_long),
        ('biYPelsPerMeter', ctypes.c_long), ('biClrUsed', wt.DWORD),
        ('biClrImportant', wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [('bmiHeader', BITMAPINFOHEADER), ('bmiColors', wt.DWORD * 3)]


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack('>I', len(data)) + tag + data
            + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))


def png_from_bgra(width: int, height: int, bgra: bytes) -> bytes:
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        row = bgra[y * stride:(y + 1) * stride]
        rgb = bytearray(width * 3)
        rgb[0::3] = row[2::4]
        rgb[1::3] = row[1::4]
        rgb[2::3] = row[0::4]
        raw.append(0)
        raw.extend(rgb)
    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n' + _chunk(b'IHDR', ihdr)
            + _chunk(b'IDAT', zlib.compress(bytes(raw), 6)) + _chunk(b'IEND', b''))


def capture(hwnd: int):
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    rect = wt.RECT()
    assert user32.GetWindowRect(hwnd, ctypes.byref(rect)), 'GetWindowRect failed'
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetWindowDC(hwnd)
    memdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    old = gdi32.SelectObject(memdc, bmp)
    ok = gdi32.BitBlt(memdc, 0, 0, w, h, hdc, 0, 0, SRCCOPY | CAPTUREBLT)
    pb = user32.PrintWindow(hwnd, memdc, PW_RENDERFULLCONTENT)
    bi = BITMAPINFO()
    bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bi.bmiHeader.biWidth = w
    bi.bmiHeader.biHeight = -h
    bi.bmiHeader.biPlanes = 1
    bi.bmiHeader.biBitCount = 32
    bi.bmiHeader.biCompression = 0
    buf = ctypes.create_string_buffer(w * h * 4)
    lines = gdi32.GetDIBits(memdc, bmp, 0, h, buf, ctypes.byref(bi), DIB_RGB_COLORS)
    gdi32.SelectObject(memdc, old)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(memdc)
    user32.ReleaseDC(hwnd, hdc)
    return {'w': w, 'h': h, 'bitblt': bool(ok), 'printwindow': bool(pb),
            'dib_lines': lines, 'bgra': buf.raw}


def variety(bgra: bytes, step: int = 13) -> dict:
    colors = set()
    white = 0
    total = 0
    for i in range(0, len(bgra) - 4, 4 * step):
        px = bgra[i:i + 3]
        colors.add(bytes(px))
        total += 1
        if px[0] > 240 and px[1] > 240 and px[2] > 240:
            white += 1
    return {'sampled': total, 'distinct': len(colors),
            'white_ratio': round(white / max(1, total), 3)}


def main(argv) -> int:
    out = argv[0] if argv else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', 'probe_capture.png')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    mol = os.path.join(tempfile.gettempdir(), 'kd_cap.mol')
    res = kd.smiles_to_mol('c1ccccc1O')
    open(mol, 'w', encoding='utf-8', newline='').write(res.data['text'])
    opened = op.open_file(mol, timeout=20)
    print('open ok=', opened.ok, 'pid=', opened.data.get('pid'),
          'title=', (opened.data.get('window') or {}).get('title'))
    if not opened.ok:
        return 1
    hwnd = opened.data['window']['hwnd']
    info = capture(hwnd)
    png = png_from_bgra(info['w'], info['h'], info['bgra'])
    open(out, 'wb').write(png)
    print('png bytes:', len(png), 'dims:', info['w'], 'x', info['h'],
          'bitblt:', info['bitblt'], 'printwindow:', info['printwindow'], 'dib:', info['dib_lines'])
    print('variety:', variety(info['bgra']))
    print('wrote', out)
    print('close:', op.close_app(opened.data['pid'], 12.0).to_dict()['data'])
    print('left:', op.list_pids())
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
