'''Render captured CLI output the way a terminal would lay it out.

    python test/render_terminal.py <label> <columns> -- <command...>

Why not just read the text: the complaints we are chasing are visual. A table
formatted with '%-8s' pads by CHARACTER COUNT, while a CJK character occupies
TWO terminal cells. The text looks fine in a file and the columns collide on
screen. Only glyph metrics show that, so the output is laid out with the real
Consolas advance width and photographed.

This is a faithful reconstruction, not a screenshot of a real window: this
session has no visible console to photograph (measured: no ConsoleWindowClass
and no Windows Terminal among visible windows). Glyph metrics are the same ones
the console uses for a monospaced cell, so column collisions found here are
real; anything about the window chrome is not.
'''
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'test', 'out', 'shots')
FONT = 'C:/Windows/Fonts/consola.ttf'
CJK = 'C:/Windows/Fonts/msyh.ttc'
SIZE = 15


def cells(line):
    '''Terminal cells a line occupies: wide characters count as two.'''
    total = 0
    for ch in line:
        total += 2 if unicodedata_east_asian(ch) else 1
    return total


def unicodedata_east_asian(ch):
    import unicodedata
    return unicodedata.east_asian_width(ch) in ('W', 'F')


def wrap(line, columns):
    '''Split on cell width, the way a terminal wraps.'''
    if cells(line) <= columns:
        return [line]
    out, cur, used = [], [], 0
    for ch in line:
        w = 2 if unicodedata_east_asian(ch) else 1
        if used + w > columns:
            out.append(''.join(cur))
            cur, used = [ch], w
        else:
            cur.append(ch)
            used += w
    out.append(''.join(cur))
    return out


def main(argv):
    label = argv[1]
    columns = int(argv[2])
    sep = argv.index('--')
    command = argv[sep + 1:]
    os.makedirs(OUT, exist_ok=True)

    # A .py path is not executable on Windows; run it through this interpreter.
    if command and command[0].endswith('.py'):
        command = [sys.executable] + command
    proc = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=180,
                          env={**os.environ, 'PYTHONIOENCODING': 'utf-8',
                               'COLUMNS': str(columns)})
    text = (proc.stdout or '') + (proc.stderr or '')
    lines = []
    for raw in text.splitlines():
        lines.extend(wrap(raw, columns))

    mono = ImageFont.truetype(FONT, SIZE)
    cell = mono.getlength('M')
    line_h = int(SIZE * 1.35)
    pad = 12
    width = int(cell * columns) + pad * 2
    height = line_h * max(len(lines), 2) + pad * 2
    img = Image.new('RGB', (width, height), (12, 12, 12))
    draw = ImageDraw.Draw(img)

    wide = ImageFont.truetype(CJK, SIZE)
    y = pad
    for line in lines:
        x = pad
        for ch in line:
            if unicodedata_east_asian(ch):
                draw.text((x, y), ch, font=wide, fill=(222, 222, 222))
                x += cell * 2
            else:
                draw.text((x, y), ch, font=mono, fill=(222, 222, 222))
                x += cell
        y += line_h

    path = os.path.join(OUT, '%s_%dcol.png' % (label, columns))
    img.save(path)
    over = [i + 1 for i, l in enumerate(lines) if cells(l) > columns]
    print('wrote %s (%dx%d), rc=%d, %d lines, %d over-wide'
          % (os.path.relpath(path, ROOT), width, height, proc.returncode,
             len(lines), len(over)))
    if over:
        print('  over-wide after wrapping (should be 0): ' + str(over[:10]))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))