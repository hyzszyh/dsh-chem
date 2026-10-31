"""Readability maths for a drawn page (requirements FR-D11, FR-D12).

The generator scales a whole drawing to the requested width, so a big molecule
comes back with bonds a few pixels long: technically an image, practically
unreadable. Measuring the median bond length in pixels lets us say so, and lets
us widen the canvas until it stops being true.
"""

import math
import re

MIN_BOND_PX = 8.0
MAX_WIDTH_MM = 420.0

_ATOM = re.compile(r'<n\s+([^>]*)/>')
_BOND = re.compile(r'<b\s+([^>]*)/>')
_ATTR = re.compile(r'(\w+)="([^"]*)"')


def parse_cdxml(text: str) -> dict:
    '''Atom coordinates and bond pairs out of a ChemDraw CDXML page.'''
    atoms, bonds = {}, []
    for chunk in _ATOM.findall(text or ''):
        attrs = dict(_ATTR.findall(chunk))
        ident = attrs.get('id')
        point = attrs.get('p')
        if not ident or not point:
            continue
        parts = point.split()
        if len(parts) < 2:
            continue
        try:
            atoms[ident] = (float(parts[0]), float(parts[1]))
        except ValueError:
            continue
    for chunk in _BOND.findall(text or ''):
        attrs = dict(_ATTR.findall(chunk))
        begin, end = attrs.get('B'), attrs.get('E')
        if begin in atoms and end in atoms:
            bonds.append((begin, end))
    return {'atoms': atoms, 'bonds': bonds}


def bond_lengths(geometry: dict) -> list:
    '''Every bond length in points (1 pt = 1/72 inch).'''
    atoms = geometry.get('atoms') or {}
    out = []
    for begin, end in geometry.get('bonds') or []:
        if begin not in atoms or end not in atoms:
            continue
        ax, ay = atoms[begin]
        bx, by = atoms[end]
        out.append(math.hypot(ax - bx, ay - by))
    return out


def median(values: list) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def measure(geometry: dict, width_mm: float, dpi: int) -> dict:
    '''Bond length in pixels for the figure as it would be exported.'''
    lengths = bond_lengths(geometry)
    if not lengths:
        return {'bonds': 0, 'median_px': 0.0, 'min_px': 0.0, 'readable': False,
                'reason': 'no bonds on the page'}
    atoms = geometry.get('atoms') or {}
    xs = [p[0] for p in atoms.values()]
    ys = [p[1] for p in atoms.values()]
    span_pt = max(max(xs) - min(xs), 1.0)
    # The page is scaled so its content spans width_mm; bond length follows.
    scale = (width_mm * 72.0 / 25.4) / span_pt
    median_pt = median(lengths) * scale
    min_pt = min(lengths) * scale
    return {
        'bonds': len(lengths),
        'median_px': round(median_pt / 72.0 * dpi, 2),
        'min_px': round(min_pt / 72.0 * dpi, 2),
        'readable': (median_pt / 72.0 * dpi) >= MIN_BOND_PX,
        'reason': '',
    }


def suggest_width(geometry: dict, width_mm: float, dpi: int,
                  min_px: float = MIN_BOND_PX) -> float:
    '''The narrowest width at which the median bond is min_px long.'''
    stats = measure(geometry, width_mm, dpi)
    if stats.get('median_px', 0.0) <= 0:
        return width_mm
    factor = min_px / stats['median_px']
    if factor <= 1.0:
        return width_mm
    wanted = math.ceil(width_mm * factor / 5.0) * 5.0
    return min(wanted, MAX_WIDTH_MM)


def tier(atom_count: int) -> dict:
    '''Which size class this structure falls in, with its budget (FR-D11).'''
    if atom_count < 100:
        return {'name': 'small', 'atoms': atom_count, 'expect_s': 3}
    if atom_count < 300:
        return {'name': 'medium', 'atoms': atom_count, 'expect_s': 8}
    if atom_count < 800:
        return {'name': 'large', 'atoms': atom_count, 'expect_s': 20}
    return {'name': 'natural-product', 'atoms': atom_count, 'expect_s': 60}