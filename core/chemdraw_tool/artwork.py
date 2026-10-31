'''Journal artwork: turn whatever the engine exports into something submittable.

The measured facts this module is built on (see docs/journal-artwork.md):

* ChemDraw's SaveAs writes PNG with a dpi tag of 144 no matter what resolution
  was requested, and the pixels come out as RGBA. Publishers reject both.
* SaveAs cannot produce PDF on this installation at all, so a vector submission
  has to be EPS or SVG.
* Width and resolution only scale pixel count; they never change the physical
  size. A 10034 px file is 849 mm wide at 300 dpi. So the target pixel width is
  chosen first and the SaveAs arguments are solved backwards from it.

Nothing here talks to ChemDraw; it repairs files that already exist.'''

from __future__ import annotations

import os
from typing import Optional

from .models import ErrorCode, Failure, Result

# Publisher profiles, in the units each one states them. dpi values are the
# hard requirements; widths are converted to points so they can be compared
# with what ChemDraw reports (1 in = 72 pt).
JOURNALS = {
    'acs': {
        'label': 'ACS (JACS author guidelines)',
        'line_art_dpi': 1200,
        'gray_dpi': 600,
        'color_dpi': 300,
        'single_col_pt': 240.0,
        'max_depth_pt': 660.0,
        'min_font_pt': 4.5,
        'min_line_pt': 0.5,
        'formats': ['tif', 'eps'],
    },
    'rsc': {
        'label': 'Royal Society of Chemistry',
        'line_art_dpi': 600,
        'gray_dpi': 600,
        'color_dpi': 600,
        'single_col_pt': None,   # not obtained: the site returned 403
        'max_depth_pt': None,
        'min_font_pt': None,
        'min_line_pt': None,
        'formats': ['tif', 'eps', 'pdf'],
    },
    'wiley': {
        'label': 'Wiley (updated 1 Sep 2016)',
        'line_art_dpi': 600,
        'gray_dpi': 300,
        'color_dpi': 300,
        'single_col_pt': round(80.0 * 72 / 25.4, 1),
        'max_depth_pt': round(180.0 * 72 / 25.4, 1),
        'min_font_pt': None,
        'min_line_pt': None,
        'formats': ['tif', 'eps'],
    },
    'elsevier': {
        'label': 'Elsevier',
        'line_art_dpi': 1000,
        'gray_dpi': 500,
        'color_dpi': 300,
        'single_col_pt': round(90.0 * 72 / 25.4, 1),
        'max_depth_pt': round(190.0 * 72 / 25.4, 1),
        'min_font_pt': 6.0,
        'min_line_pt': None,
        'formats': ['tif', 'jpeg', 'eps', 'pdf'],
    },
}


def _open(path):
    from PIL import Image
    return Image.open(path)


def _new_rgb(size):
    from PIL import Image
    return Image.new('RGB', size, (255, 255, 255))


def check(path, journal=None, min_dpi=300, target_width_pt=None):
    '''Report what would fail at submission time, in plain language.'''
    if not os.path.isfile(path):
        return Result(ok=False, channel='artwork', failure=Failure(
            code=ErrorCode.NOT_INSTALLED, message='file not found: ' + path,
            stage='check'))
    profile = JOURNALS.get((journal or '').lower())
    try:
        image = _open(path)
    except Exception as exc:
        return Result(ok=False, channel='artwork', failure=Failure(
            code=ErrorCode.PARSE_FAILED, message='cannot read image',
            detail=type(exc).__name__ + ': ' + str(exc), stage='check'))

    dpi = image.info.get('dpi') or (None, None)
    dpi_x = round(float(dpi[0])) if dpi and dpi[0] else None
    issues = []
    warnings = []

    if dpi_x is None:
        issues.append('no dpi metadata; publishers read the dpi tag, not the pixel count')
    elif dpi_x < min_dpi:
        issues.append('dpi %d is below the %d required' % (dpi_x, min_dpi))
    if image.mode not in ('RGB', 'L'):
        issues.append('colour mode %s will be rejected or silently flattened; convert to RGB' % image.mode)

    width_pt = image.width * 72.0 / dpi_x if dpi_x else None
    if target_width_pt and width_pt:
        delta = abs(width_pt - target_width_pt) / target_width_pt
        if delta > 0.05:
            warnings.append('width is %.1f pt (%.1f mm), target %.1f pt; at %d dpi that is %.0f px' % (
                width_pt, width_pt * 25.4 / 72, target_width_pt, dpi_x,
                target_width_pt * dpi_x / 72))

    if profile:
        hard = profile.get('line_art_dpi') or min_dpi
        if dpi_x and dpi_x < hard:
            issues.append('%s wants %d dpi for line art' % (profile['label'], hard))
        ext = os.path.splitext(path)[1].lower().lstrip('.')
        if profile.get('formats') and ext not in profile['formats']:
            warnings.append('%s accepts %s; .%s may need converting' % (
                profile['label'], '/'.join(profile['formats']), ext))

    return Result(ok=not issues, channel='artwork', data={
        'path': os.path.abspath(path),
        'format': image.format,
        'mode': image.mode,
        'width_px': image.width,
        'height_px': image.height,
        'dpi': dpi_x,
        'width_pt': round(width_pt, 1) if width_pt else None,
        'width_mm': round(width_pt * 25.4 / 72, 1) if width_pt else None,
        'journal': profile['label'] if profile else None,
        'issues': issues,
        'warnings': warnings,
    }, warnings=warnings + issues)


def normalize(src, dst, dpi=300, max_width_mm=None):
    '''Rewrite dpi, flatten to RGB, optionally rescale to a physical width.'''
    if not os.path.isfile(src):
        return Result(ok=False, channel='artwork', failure=Failure(
            code=ErrorCode.NOT_INSTALLED, message='file not found: ' + src,
            stage='normalize'))
    try:
        image = _open(src)
        original = (image.mode, image.width, image.height,
                    (image.info.get('dpi') or (None,))[0])
        if image.mode in ('RGBA', 'LA', 'P'):
            canvas = _open(src).convert('RGBA')
            flat = _new_rgb(canvas.size)
            flat.paste(canvas, mask=canvas.split()[-1])
            image = flat
        elif image.mode == 'L':
            image = image.convert('RGB')
        if max_width_mm:
            target_px = int(round(max_width_mm / 25.4 * dpi))
            if target_px < image.width:
                height = int(round(image.height * target_px / image.width))
                image = image.resize((target_px, height))
        os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
        image.save(dst, dpi=(dpi, dpi))
    except Exception as exc:
        return Result(ok=False, channel='artwork', failure=Failure(
            code=ErrorCode.UNKNOWN, message='normalize failed',
            detail=type(exc).__name__ + ': ' + str(exc), stage='normalize'))
    return Result(ok=True, channel='artwork', data={
        'src': os.path.abspath(src),
        'dst': os.path.abspath(dst),
        'bytes': os.path.getsize(dst),
        'mode': image.mode,
        'width_px': image.width,
        'height_px': image.height,
        'dpi': dpi,
        'width_mm': round(image.width / dpi * 25.4, 1),
        'before': {'mode': original[0], 'width_px': original[1],
                   'height_px': original[2], 'dpi': original[3]},
    })


# No export on this build exceeds this size, whatever resolution is asked for
# (1500 dpi and 2183 dpi both came back 2637 x 2191). figures at high dpi on
# wide content are therefore unreachable in a single SaveAs.
MAX_EXPORT_PX = (2637, 2191)


def pad_margin(path, ratio=0.06, dpi=300, min_px=10):
    '''Re-lay the ink on a white canvas of the same size, so it has margins.

    ChemDraw writes a crop that is flush with the outermost bond, which reads
    as 'no margins' next to other figures. Shrinking the ink inside its own
    canvas adds the margin without changing the physical width: same pixels,
    same dpi, so the mm value stays true. Returns the factor every length
    measured before the export must be multiplied by, or None when nothing
    was done.'''
    if not os.path.isfile(path):
        return None
    try:
        from PIL import Image, ImageChops
        image = _open(path).convert('RGB')
        white = Image.new('RGB', image.size, (255, 255, 255))
        bbox = ImageChops.difference(image, white).getbbox()
    except Exception:
        return None
    if not bbox:
        return {'scale': 1.0, 'margin_px': 0, 'width_px': image.width,
                'height_px': image.height}
    ink = image.crop(bbox)
    margin = max(int(min_px), int(round(max(image.size) * float(ratio))))
    room_w = max(1, image.width - 2 * margin)
    room_h = max(1, image.height - 2 * margin)
    scale = min(room_w / float(ink.width), room_h / float(ink.height), 1.0)
    if scale >= 0.999:
        return {'scale': 1.0, 'margin_px': margin, 'width_px': image.width,
                'height_px': image.height}
    size = (max(1, int(round(ink.width * scale))),
            max(1, int(round(ink.height * scale))))
    scaled = ink.resize(size, Image.LANCZOS)
    canvas = Image.new('RGB', image.size, (255, 255, 255))
    canvas.paste(scaled, ((image.width - size[0]) // 2,
                          (image.height - size[1]) // 2))
    try:
        canvas.save(path, dpi=(dpi, dpi))
    except Exception:
        return None
    return {'scale': round(scale, 4), 'margin_px': margin,
            'width_px': image.width, 'height_px': image.height,
            'ink_px': [size[0], size[1]]}

def resolution_for(target_px_width, content_width_pt):
    '''Resolution that draws content_width_pt of structure target_px_width wide.

    This is the direction that works, and the opposite one does not. Width and
    Height in SaveAs only add canvas margin: the same 66.2 pt molecule came
    back 550 px wide whether Width was 78.2, 234.7 or 309, because the drawing
    is laid out at resolution/36 px per point and everything else is blank
    paper. Solving for Width therefore pads the page and leaves the molecule
    exactly as small as before - it looks like it scaled the figure only if
    you measure the file instead of the ink.'''
    if content_width_pt <= 0:
        raise ValueError('content_width_pt must be positive')
    return max(72, int(round(target_px_width * 36.0 / content_width_pt)))


def canvas_pt(content_width_pt, content_height_pt, margin_pt=10.0):
    '''Canvas that just holds the drawing plus a margin, in points.'''
    return (content_width_pt + 2 * margin_pt, content_height_pt + 2 * margin_pt)