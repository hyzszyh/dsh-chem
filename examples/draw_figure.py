'''Draw a molecule in ChemDraw and export a journal-sized figure.

    python examples/draw_figure.py

Needs the 64-bit interpreter, pywin32, Pillow and an installed ChemDraw. It
opens or attaches to ChemDraw, draws the structure, then writes a trimmed RGB
PNG at a physical width, and reports what it measured.

The interesting part is the failure behaviour: every step returns a Result
with a structured failure instead of raising, so a broken install prints why
rather than a traceback.
'''
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'core'))

from chemdraw_tool.adapters.cd_com import ChemDrawChannel  # noqa: E402

OUT = ROOT / 'examples' / 'out'

# ACS single column, and their floor for line art.
WIDTH_MM = 85.0
DPI = 1200


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / 'phenol_acs_single_column.png'

    channel = ChemDrawChannel()
    opened = channel.connect()
    if not opened.ok:
        print('cannot reach ChemDraw:', opened.failure.message)
        print('hint:', opened.failure.hint)
        return 1

    try:
        drawn = channel.draw_smiles('c1ccccc1O')
        if not drawn.ok:
            print('draw failed:', drawn.failure.message)
            return 1
        print('drew %s atoms / %s bonds, read back %s'
              % (drawn.data.get('atoms_after'), drawn.data.get('bonds_after'),
                 drawn.data.get('readback_smiles')))

        # 85 mm is the ACS single-column width; 1200 dpi is their line-art floor.
        # Both are worth asking for, and this build cannot give them together:
        # the export tops out near 1922 px wide, so 85 mm at 1200 dpi would be
        # 4016 px. Asking anyway is deliberate -- the answer names the width it
        # reached and the dpi it had to use (measured on phenol: 85.0 mm at
        # 574 dpi), and the width is the one that was asked for.
        figure = channel.export_figure(str(target), width_mm=WIDTH_MM, dpi=DPI)
        if not figure.ok:
            print('export failed:', figure.failure.message)
            print('hint:', figure.failure.hint)
            return 1
        art = (figure.data or {}).get('figure') or {}
        fit = int(art.get('dpi_fit') or 0)
        got_mm = float(art.get('width_mm') or 0)
        if fit and got_mm and got_mm < WIDTH_MM * 0.98:
            print('%d dpi at %g mm is beyond this build: it capped the export '
                  'at %s px, giving %.1f mm.'
                  % (DPI, WIDTH_MM, art.get('width_px'), got_mm))
            print('re-exporting at %d dpi, the largest that still fills %g mm'
                  % (fit, WIDTH_MM))
            figure = channel.export_figure(str(target), width_mm=WIDTH_MM, dpi=fit)
            if not figure.ok:
                print('export failed:', figure.failure.message)
                return 1
        # export_figure keeps the raw export under data and the measured
        # artwork under data['figure'] / data['check']. Reading the top level
        # (data['width_px'] and friends) is what printed 'None x None px'
        # here for as long as nobody looked.
        art = (figure.data or {}).get('figure') or {}
        check = (figure.data or {}).get('check') or {}
        print('wrote %s - %s x %s px, %s dpi, %s mode'
              % (target.name, art.get('width_px'), art.get('height_px'),
                 art.get('dpi'), art.get('mode')))
        print('      %.1f mm wide on paper (asked for %g at %s dpi), %s bytes'
              % (float(art.get('width_mm') or 0), WIDTH_MM, DPI, art.get('bytes')))
        issues = check.get('issues') or []
        print('      artwork check: %d issue%s%s'
              % (len(issues), '' if len(issues) == 1 else 's',
                 (' - ' + '; '.join(issues)) if issues else ''))
        for warning in figure.warnings:
            print('  warning:', warning)
    finally:
        channel.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())