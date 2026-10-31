'''Render a Markdown file the way a reader would see it, and photograph it.

    python test/render_markdown.py README.md --width 900 --out test/out/shots/readme.png

Why: tables and long code lines are only a problem once rendered. A table that
looks fine in source can force a horizontal scrollbar on a laptop; a code block
past ~90 columns does the same. Measuring the source text does not answer that,
the browser does.

Uses the Edge/Chromium already on the machine in headless mode, with a throwaway
profile so it never touches the user's browser session.
'''
import argparse
import os
import subprocess
import sys
import tempfile

import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROWSERS = [
    r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
    r'C:\Program Files\Google\Chrome\Application\chrome.exe',
    r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe',
]

# The page width is pinned in CSS on purpose. --window-size alone does not
# constrain layout in headless mode (measured: at 420 px the body still laid
# out wider and the screenshot simply cropped the right edge, which would have
# "proven" a table overflow that was really a tool bug).
CSS = '''
:root { color-scheme: light; }
html, body { width: %(width)dpx; max-width: %(width)dpx; margin: 0;
             box-sizing: border-box; overflow-x: hidden; }
body { padding: 24px 32px; background: #fff;
       font: 16px/1.55 -apple-system, 'Segoe UI', 'Microsoft YaHei', sans-serif;
       color: #1f2328; }
h1 { font-size: 2em; border-bottom: 1px solid #d1d9e0; padding-bottom: .3em; margin: .67em 0; }
h2 { font-size: 1.5em; border-bottom: 1px solid #d1d9e0; padding-bottom: .3em; margin-top: 1.4em; }
h3 { font-size: 1.25em; margin-top: 1.2em; }
table { border-collapse: collapse; margin: 12px 0; font-size: 15px;
        display: block; overflow-x: auto; max-width: %(width)dpx; }
th, td { border: 1px solid #d1d9e0; padding: 6px 13px; vertical-align: top; }
th { background: #f6f8fa; font-weight: 600; }
tr:nth-child(2n) td { background: #f6f8fa; }
code { background: #eff1f3; padding: .2em .4em; border-radius: 6px;
       font: 85% 'Cascadia Mono', Consolas, monospace; }
pre { background: #f6f8fa; padding: 16px; border-radius: 6px;
      overflow-x: auto; max-width: 100%; }
img { max-width: 100%; height: auto; }
pre code { background: none; padding: 0; font-size: 14px; }
blockquote { margin: 0; padding: 0 1em; color: #59636e; border-left: .25em solid #d1d9e0; }
'''


def edge_ink(path, band=2):
    '''Count non-background pixels hugging each border.

    A page with padding must have nothing in the outer band. Ink there means
    the layout came out wider than the viewport and the screenshot cropped it --
    which is exactly how this tool lied once: it reported a table overflow that
    was really the renderer failing to constrain the body width.
    '''
    from PIL import Image
    image = Image.open(path).convert('L')
    width, height = image.size
    px = image.load()
    tallies = {'left': 0, 'right': 0, 'top': 0, 'bottom': 0}
    for y in range(height):
        for x in range(band):
            if px[x, y] < 240:
                tallies['left'] += 1
            if px[width - 1 - x, y] < 240:
                tallies['right'] += 1
    for x in range(width):
        for y in range(band):
            if px[x, y] < 240:
                tallies['top'] += 1
            if px[x, height - 1 - y] < 240:
                tallies['bottom'] += 1
    return tallies


def find_browser():
    for path in BROWSERS:
        if os.path.exists(path):
            return path
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('source')
    ap.add_argument('--width', type=int, default=900)
    ap.add_argument('--height', type=int, default=1600)
    ap.add_argument('--out', default=None)
    args = ap.parse_args(argv)

    browser = find_browser()
    if not browser:
        print('no Edge/Chrome found; cannot render')
        return 2

    path = os.path.join(ROOT, args.source) if not os.path.isabs(args.source) else args.source
    with open(path, encoding='utf-8') as handle:
        # Footnotes and task lists are part of what GitHub renders; leaving
        # the extensions out makes the screenshot lie about the page.
        body = markdown.markdown(
            handle.read(),
            extensions=['tables', 'fenced_code', 'footnotes', 'sane_lists'],
        )

    # The content box minus the body padding: what is left for the text.
    content_width = max(args.width - 64, 200)
    # Straight replacement: the sheet contains a literal '85%', which
    # %-formatting would try to read as a conversion specifier.
    css = CSS.replace('%(width)d', str(content_width))
    # The page is written to a temp directory, so relative image paths would
    # resolve there and every <img> would fall back to its alt text -- the
    # screenshot would then 'prove' a broken image that is actually fine.
    base = 'file:///' + str(ROOT).replace(os.sep, '/') + '/'
    html = ('<!doctype html><meta charset="utf-8"><base href="' + base + '">'
            '<style>' + css + '</style><body>' + body + '</body>')

    out = args.out or os.path.join('test', 'out', 'shots',
                                   os.path.splitext(os.path.basename(path))[0] + '.png')
    out = os.path.join(ROOT, out) if not os.path.isabs(out) else out
    os.makedirs(os.path.dirname(out), exist_ok=True)

    with tempfile.TemporaryDirectory() as work:
        html_path = os.path.join(work, 'page.html')
        with open(html_path, 'w', encoding='utf-8') as handle:
            handle.write(html)
        profile = os.path.join(work, 'profile')
        cmd = [browser, '--headless=new', '--disable-gpu', '--no-first-run',
               '--no-default-browser-check', '--hide-scrollbars',
               '--force-device-scale-factor=1',
               '--user-data-dir=' + profile,
               '--window-size=%d,%d' % (args.width, args.height),
               '--screenshot=' + out,
               'file:///' + html_path.replace('\\', '/')]
        # Edge writes its diagnostics in the console codepage, not UTF-8;
        # decoding strictly raises even though the screenshot succeeded.
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              errors='replace', timeout=120)

    if not os.path.exists(out):
        print('screenshot failed, rc=%d' % proc.returncode)
        print((proc.stderr or '')[-800:])
        return 1
    size = os.path.getsize(out)
    ink = edge_ink(out)
    print('wrote %s (%d bytes, %dpx wide)' % (os.path.relpath(out, ROOT), size, args.width))
    print('edge ink  L=%d R=%d T=%d B=%d' % (
          ink['left'], ink['right'], ink['top'], ink['bottom']))
    if ink['left'] or ink['right']:
        print('FAIL: content touches the horizontal edge; the page was cropped')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())