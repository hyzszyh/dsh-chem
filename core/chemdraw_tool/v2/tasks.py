"""The M1 task surface: status, draw, close.

One call per task, a preview image on every drawing, and an identity the caller
can check without opening the software. See docs/v2/requirements.md §3.
"""

import json
import os
import re
import time

from .. import artwork
from ..models import ErrorCode
from . import checks
from . import figure as figure_mod
from . import geom3d
from . import geometry
from . import grade as grade_mod
from . import ocr as ocr_mod
from . import props
from . import reaction as reaction_mod
from . import resolve
from . import route as routes
from . import stoich as stoich_mod
from . import variants as variants_mod
from . import session

SMILES_CHARS = re.compile(r'^[A-Za-z0-9@+\-\[\]()=#$%./\\:]+$')
STRUCTURE_HINT = re.compile(r'[A-Z0-9\[\]=#$%]')

WIDTH_BY_TIER = {'small': 85.0, 'medium': 140.0, 'large': 200.0,
                 'natural-product': 320.0}


def envelope(ok, data=None, failure=None, elapsed_ms=0, warnings=None,
             degraded=False, degrade_reason='', channel='v2',
             evidence='measured', evidence_note=''):
    return {
        'ok': bool(ok),
        'channel': channel,
        'data': data,
        'failure': failure,
        'degraded': bool(degraded),
        'degrade_reason': degrade_reason,
        'evidence': evidence,
        'evidence_note': evidence_note,
        'elapsed_ms': int(elapsed_ms),
        'warnings': list(warnings or []),
    }


def failure(code, stage, message, hint='', detail=''):
    return {'code': code, 'stage': stage, 'message': message,
            'hint': hint, 'detail': detail}


def artifacts_dir(sub='draw') -> str:
    path = os.path.join(session.state_dir(), 'artifacts', sub)
    os.makedirs(path, exist_ok=True)
    return path


def _slug(text: str, limit: int = 40) -> str:
    keep = [c if (c.isalnum() or c in '-_') else '-' for c in text]
    return ''.join(keep)[:limit].strip('-') or 'structure'


def _identity(mol) -> dict:
    from rdkit import Chem
    from rdkit.Chem import Descriptors, rdMolDescriptors

    smiles = Chem.MolToSmiles(mol)
    return {
        'smiles': smiles,
        'formula': rdMolDescriptors.CalcMolFormula(mol),
        'mw': round(Descriptors.MolWt(mol), 3),
        'atoms': mol.GetNumAtoms(),
        'bonds': mol.GetNumBonds(),
        'inchikey': Chem.MolToInchiKey(mol),
        'inchi': Chem.MolToInchi(mol),
        'stereo_centers': len(Chem.FindMolChiralCenters(
            mol, includeUnassigned=True)),
    }


def _read_source(source: str):
    '''(kind, mol) for a SMILES / InChI / molblock; None when unreadable.'''
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog('rdApp.*')
    raw = source or ''
    text = raw.strip()
    if not text:
        return None, None
    # A path is as natural an argument as a SMILES: students hand in files.
    # Resolving it here keeps every verb (draw, check, analyze, convert) able
    # to take one without each of them growing its own file branch.
    if '\n' not in text and len(text) < 260 and os.path.isfile(text):
        try:
            with open(text, encoding='utf-8', errors='replace') as handle:
                return _read_source(handle.read())
        except OSError:
            pass
    if text.startswith('InChI='):
        return 'inchi', Chem.MolFromInchi(text)
    if 'M  END' in text or 'V2000' in text or 'V3000' in text:
        return 'molblock', _read_molblock(raw, text)
    # A word like 'aspirin' also matches the SMILES character class, and RDKit
    # happily reads it as a chain of aromatic atoms. Real SMILES always carry an
    # upper-case element, a ring digit or a bond symbol; names do not.
    if SMILES_CHARS.match(text) and STRUCTURE_HINT.search(text):
        return 'smiles', Chem.MolFromSmiles(text)
    return 'unknown', None


def _read_molblock(raw: str, text: str):
    '''Parse a molblock whose title line may have been stripped away.

    The sanitised read comes first. When it fails the block is read again
    without sanitisation: a pentavalent carbon cannot be sanitised, and that
    is precisely the structure a student needs to be told about. The fallback
    keeps the broken atoms so checks.inspect can name them; without it the
    answer was 'E06 parse failed', which tells nobody what is wrong.
    '''
    from rdkit import Chem
    for candidate in (text, '\n' + text, raw):
        block = Chem.MolFromMolBlock(candidate, sanitize=True, removeHs=False)
        if block is not None:
            return block
    for candidate in (text, '\n' + text, raw):
        block = Chem.MolFromMolBlock(candidate, sanitize=False, removeHs=False)
        if block is not None:
            try:
                block.UpdatePropertyCache(strict=False)
            except Exception:
                pass
            return block
    return None


def status() -> dict:
    started = time.perf_counter()
    have = routes.available()
    picked = {task: routes.pick(task, have) for task in routes.TASKS}
    info = session.describe()
    data = {
        'routes': {name: {'available': have.get(name, False),
                          'bits': routes.ROUTES[name]['bits'],
                          'driver': routes.ROUTES[name]['driver'],
                          'needs_license': routes.ROUTES[name]['needs_license']}
                   for name in routes.ROUTES},
        'picked': picked,
        'session': info,
        'artifacts_dir': artifacts_dir(),
        'ocr_engines': ocr_mod.engine_reports(),
    }
    ok = any(have.values())
    fail = None
    if not ok:
        fail = failure(ErrorCode.NOT_INSTALLED, 'status',
                       'neither ChemDraw nor KingDraw answers on this machine',
                       hint='install one of them, or run in a container with RDKit only')
    return envelope(ok, data, fail, (time.perf_counter() - started) * 1000)


# 留白比例：画布长边的 6%。三原子分子和六十原子的天然产物都够用。
INK_MARGIN = 0.06


def draw(source: str, width_mm: float = None, dpi: int = 300,
         out_dir: str = None, visible: bool = False,
         name: str = '', allow_widen: bool = True) -> dict:
    '''Parse a structure, draw it, verify it, and return a readable preview.'''
    started = time.perf_counter()
    warnings = []
    kind, mol = _read_source(source)
    if mol is None:
        hint = ('name/CAS input lands in M4; give SMILES, InChI or a molblock'
                if kind == 'unknown' else 'fix the %s and retry' % kind)
        return envelope(False, None, failure(
            ErrorCode.PARSE_FAILED, 'parse',
            'could not read %r as a structure' % (source or '')[:60], hint=hint),
            (time.perf_counter() - started) * 1000)
    ident = _identity(mol)
    tier = geometry.tier(ident['atoms'])
    wanted_width = float(width_mm or WIDTH_BY_TIER.get(tier['name'], 85.0))
    route = routes.pick('draw')
    if not route:
        return envelope(False, None, failure(
            ErrorCode.NOT_INSTALLED, 'route', 'no drawing route is available',
            hint='install ChemDraw or KingDraw'),
            (time.perf_counter() - started) * 1000)
    target_dir = out_dir or artifacts_dir()
    os.makedirs(target_dir, exist_ok=True)
    stem = _slug(name or ident['inchikey'] or 'structure')
    png = os.path.join(target_dir, '%s-%s.png' % (stem, int(time.time())))
    try:
        with session.open_session(visible=visible) as channel:
            drawn = channel.draw_smiles(ident['smiles'])
            if not drawn.ok:
                return envelope(False, {'identity': ident},
                                _as_dict(getattr(drawn, 'failure', None)),
                                (time.perf_counter() - started) * 1000)
            page = channel.read_current('cdxml')
            text = (page.data or {}).get('text', '') if page.ok else ''
            shape = geometry.parse_cdxml(text)
            stats = geometry.measure(shape, wanted_width, dpi)
            suggested = geometry.suggest_width(shape, wanted_width, dpi)
            if not stats.get('readable') and allow_widen:
                wider = suggested
                if wider > wanted_width:
                    warnings.append(
                        'median bond was %.1f px at %g mm; widened to %g mm'
                        % (stats.get('median_px', 0), wanted_width, wider))
                    wanted_width = wider
                    stats = geometry.measure(shape, wanted_width, dpi)
            exported = channel.export_figure(png, width_mm=wanted_width,
                                             dpi=dpi)
            if not exported.ok:
                return envelope(False, {'identity': ident},
                                _as_dict(getattr(exported, 'failure', None)),
                                (time.perf_counter() - started) * 1000)
            # ChemDraw 导出的是一张紧贴笔迹的裁切图，最外侧的键就是画布边界。
            # 放在稿子里看着像「没有留白」，所以导出后把墨迹在原画布中央缩进一点：
            # 像素数与 dpi 都不变，物理宽度还是原来那个数，只是周围多一圈白边。
            padding = artwork.pad_margin(png, ratio=INK_MARGIN, dpi=dpi)
            if padding and padding.get('scale', 1.0) < 0.999:
                stats = dict(stats or {})
                if stats.get('median_px'):
                    stats['median_px'] = stats['median_px'] * padding['scale']
                    stats['min_px'] = (stats.get('min_px') or 0) * padding['scale']
                    stats['readable'] = stats['median_px'] >= geometry.MIN_BOND_PX
            doc_atoms = channel._doc.Atoms.Count
            doc_bonds = channel._doc.Bonds.Count
    except session.SessionError as exc:
        return envelope(False, None, _as_dict(exc.result.failure),
                        (time.perf_counter() - started) * 1000)
    except Exception as exc:
        return envelope(False, None, failure(ErrorCode.UNKNOWN, 'draw',
                                             '%s: %s' % (type(exc).__name__, exc)),
                        (time.perf_counter() - started) * 1000)
    matches = (doc_atoms == ident['atoms'] and doc_bonds == ident['bonds'])
    if not matches:
        warnings.append('page has %d atoms/%d bonds, input had %d/%d'
                        % (doc_atoms, doc_bonds, ident['atoms'],
                           ident['bonds']))
    preview = {
        'path': png,
        'bytes': os.path.getsize(png) if os.path.exists(png) else 0,
        'width_mm': wanted_width,
        'dpi': dpi,
        'median_bond_px': stats.get('median_px'),
        'readable': stats.get('readable'),
        'suggested_width_mm': round(suggested, 1),
        'padding': padding if isinstance(locals().get('padding'), dict) else None,
    }
    data = {'route': route, 'identity': ident, 'tier': tier,
            'preview': preview, 'page': {'atoms': doc_atoms,
                                        'bonds': doc_bonds},
            'verified': bool(matches),
            'artifacts': [png]}
    return envelope(True, data, None, (time.perf_counter() - started) * 1000,
                    warnings)


def close(quit_app: bool = False) -> dict:
    '''Close the page we drew on; the application stays up unless quit_app.'''
    started = time.perf_counter()
    closed, left, failure_row = 0, 0, None
    try:
        with session.open_session(visible=False) as channel:
            doc = getattr(channel, '_doc', None)
            try:
                if doc is not None:
                    doc.Close(0)
                    closed = 1
            except Exception as exc:
                failure_row = failure(ErrorCode.COM_STALLED, 'close',
                                      'Close failed: %s' % str(exc)[:80])
            left = int(channel._app.Documents.Count)
            if quit_app:
                channel._app.Quit()
    except session.SessionError as exc:
        return envelope(False, None, _as_dict(exc.result.failure),
                        (time.perf_counter() - started) * 1000)
    except Exception as exc:
        return envelope(False, None, failure(ErrorCode.UNKNOWN, 'close',
                                             '%s: %s' % (type(exc).__name__, exc)),
                        (time.perf_counter() - started) * 1000)
    data = {'closed_documents': closed, 'documents_left': left,
            'application_quit': bool(quit_app)}
    return envelope(True, data, failure_row,
                    (time.perf_counter() - started) * 1000)


def figure_export(source: str, preset: str = 'cn-1col', out_dir: str = None,
                  name: str = '', visible: bool = False) -> dict:
    '''Export at a journal preset width, and say so when it cannot be read.'''
    started = time.perf_counter()
    try:
        row = figure_mod.preset(preset)
    except KeyError as exc:
        return envelope(False, None, failure(
            ErrorCode.PARSE_FAILED, 'figure', 'unknown preset',
            hint=str(exc)), (time.perf_counter() - started) * 1000)
    result = draw(source, width_mm=row['width_mm'], dpi=row['dpi'],
                  out_dir=out_dir, visible=visible, name=name,
                  allow_widen=False)
    if not result.get('ok'):
        return result
    preview = result['data']['preview']
    suggested = preview.get('suggested_width_mm') or row['width_mm']
    result['data']['preset'] = row
    result['data']['figure'] = figure_mod.resolve(
        row, {'readable': preview.get('readable'),
              'median_px': preview.get('median_bond_px')}, suggested)
    if not preview.get('readable'):
        result['warnings'].append(
            'not readable at %g mm: %.1f px per bond'
            % (row['width_mm'], preview.get('median_bond_px') or 0))
    result['elapsed_ms'] = int((time.perf_counter() - started) * 1000)
    return result


def batch(sources, width_mm: float = None, dpi: int = 300,
          out_dir: str = None, visible: bool = False, sheet: bool = True,
          columns: int = 3) -> dict:
    '''Draw N structures, keep the ones that worked, and glue a contact sheet.'''
    started = time.perf_counter()
    items, failures = [], []
    for index, source in enumerate(sources, 1):
        result = draw(source, width_mm=width_mm, dpi=dpi, out_dir=out_dir,
                      visible=visible, name='%02d' % index)
        if result.get('ok'):
            items.append({'index': index, 'source': (source or '')[:80],
                          'png': result['data']['preview']['path'],
                          'identity': result['data']['identity'],
                          'preview': result['data']['preview']})
        else:
            failures.append({'index': index, 'source': (source or '')[:80],
                             'failure': result.get('failure')})
    sheet_path = ''
    if sheet and items:
        sheet_path = _contact_sheet(
            [{'png': row['png'], 'label': '#%02d' % row['index'],
              'bond_px': (row.get('preview') or {}).get('median_bond_px')}
             for row in items],
            out_dir or artifacts_dir('batch'), columns)
    data = {'requested': len(sources), 'drawn': len(items),
            'failed': failures, 'items': items,
            'contact_sheet': sheet_path}
    ok = bool(items) and not failures
    fail = None if ok else failure(
        ErrorCode.PARSE_FAILED if not items else ErrorCode.UNKNOWN, 'batch',
        '%d of %d could not be drawn' % (len(failures), len(sources)),
        hint='see data.failed for the per-item reason')
    return envelope(bool(items), data, fail,
                    (time.perf_counter() - started) * 1000)


def _contact_sheet(items, out_dir: str, columns: int = 3) -> str:
    '''Tile labelled drawings at a common bond length, not a common canvas.'''
    from PIL import Image, ImageDraw, ImageFont
    os.makedirs(out_dir, exist_ok=True)
    cell_w, cell_h, pad, band, inset = 560, 440, 24, 52, 20
    target_bond_px = 105.0
    columns = max(1, int(columns))
    rows = max(1, (len(items) + columns - 1) // columns)
    sheet = Image.new('RGB', (pad + columns * (cell_w + pad),
                              pad + rows * (cell_h + band + pad)), 'white')
    draw_ctx = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 24)
    except Exception:
        font = ImageFont.load_default()
    box_w, box_h = cell_w - 2 * inset, cell_h - 2 * inset
    for index, item in enumerate(items):
        column, row = index % columns, index // columns
        x = pad + column * (cell_w + pad)
        y = pad + row * (cell_h + band + pad)
        try:
            with Image.open(item['png']) as page:
                page = page.convert('RGB')
                bond = float(item.get('bond_px') or 0)
                scale = (target_bond_px / bond) if bond > 0 else 1.0
                width = max(1, int(page.width * scale))
                height = max(1, int(page.height * scale))
                if width > box_w or height > box_h:
                    fit = min(box_w / width, box_h / height)
                    width, height = int(width * fit), int(height * fit)
                page = page.resize((width, height), Image.LANCZOS)
                sheet.paste(page, (x + (cell_w - width) // 2,
                                  y + (cell_h - height) // 2))
        except Exception:
            pass
        label = item.get('label', '')
        text_w = draw_ctx.textlength(label, font=font)
        draw_ctx.text((x + (cell_w - text_w) / 2, y + cell_h + 8), label,
                      fill='black', font=font)
    out = os.path.join(out_dir, 'contact-sheet-%d.png' % int(time.time()))
    sheet.save(out, 'PNG')
    return out


def convert(source: str, to: str = 'sdf', out_dir: str = None,
            label: str = '') -> dict:
    '''Write the structure in another format; no vendor software involved.'''
    started = time.perf_counter()
    kind, mol = _read_source(source)
    if mol is None:
        return envelope(False, None, failure(
            ErrorCode.PARSE_FAILED, 'convert', 'could not read the structure',
            hint='give SMILES, InChI or a molblock'),
            (time.perf_counter() - started) * 1000)
    target = (to or 'sdf').strip().lower().lstrip('.')
    folder = out_dir or artifacts_dir('convert')
    os.makedirs(folder, exist_ok=True)
    from rdkit import Chem
    base = (mol.GetProp('_Name').strip()
            if mol.HasProp('_Name') and mol.GetProp('_Name').strip()
            else Chem.MolToSmiles(mol))
    stem = _slug(label or base)
    path = os.path.join(folder, '%s-%d.%s' % (stem, int(time.time()),
                                               'smi' if target == 'smiles'
                                               else target))
    try:
        if target in ('sdf', 'sd'):
            props.to_sdf([mol], path, [label or stem])
        elif target in ('mol', 'molblock'):
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(props.to_molblock(mol))
        elif target in ('smiles', 'smi'):
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(props.to_smiles(mol) + '\n')
        elif target == 'inchi':
            from rdkit import Chem
            with open(path, 'w', encoding='utf-8') as handle:
                handle.write(Chem.MolToInchi(mol) + '\n')
        elif target == 'csv':
            props.to_csv([props.describe(mol, label or stem)], path)
        else:
            return envelope(False, None, failure(
                ErrorCode.NOT_INSTALLED, 'convert',
                'unsupported target %r' % target,
                hint='sdf, mol, smiles, inchi, csv'),
                (time.perf_counter() - started) * 1000)
    except Exception as exc:
        return envelope(False, None, failure(
            ErrorCode.UNKNOWN, 'convert',
            '%s: %s' % (type(exc).__name__, exc)),
            (time.perf_counter() - started) * 1000)
    data = {'from': kind, 'to': target, 'path': path,
            'bytes': os.path.getsize(path) if os.path.exists(path) else 0,
            'identity': _identity(mol)}
    return envelope(True, data, None, (time.perf_counter() - started) * 1000)


def analyze(sources, out_dir: str = None, labels=None) -> dict:
    '''Property table for one or more structures (FR-O3).'''
    started = time.perf_counter()
    rows, failures = [], []
    for index, source in enumerate(sources):
        kind, mol = _read_source(source)
        if mol is None:
            failures.append({'index': index + 1,
                             'source': (source or '')[:80], 'kind': kind})
            continue
        label = labels[index] if labels and index < len(labels) else ''
        rows.append(props.describe(mol, label))
    folder = out_dir or artifacts_dir('analyze')
    csv_path = ''
    if rows:
        os.makedirs(folder, exist_ok=True)
        csv_path = os.path.join(folder, 'properties-%d.csv' % int(time.time()))
        props.to_csv(rows, csv_path)
    data = {'rows': rows, 'failed': failures, 'csv': csv_path,
            'markdown': props.to_markdown(rows) if rows else ''}
    ok = bool(rows) and not failures
    return envelope(bool(rows), data, None,
                    (time.perf_counter() - started) * 1000)

def check(source: str, with_layout: bool = False,
          visible: bool = False) -> dict:
    '''Valence, stereo, fragments — and atom clashes when a page is drawn.'''
    started = time.perf_counter()
    kind, mol = _read_source(source)
    if mol is None:
        return envelope(False, None, failure(
            ErrorCode.PARSE_FAILED, 'check', 'could not read the structure',
            hint='give SMILES, InChI or a molblock'),
            (time.perf_counter() - started) * 1000)
    report = checks.inspect(mol)
    data = {'identity': _identity(mol), 'issues': report['issues'],
            'summary': report['summary'], 'layout': None}
    warnings = []
    if with_layout:
        drawn = draw(source, visible=visible, name='check')
        if drawn.get('ok'):
            data['layout'] = {'preview': drawn['data']['preview'],
                              'page': drawn['data']['page']}
        else:
            warnings.append('asked to check the layout but the drawing failed')
    return envelope(report['ok'], data, None,
                    (time.perf_counter() - started) * 1000, warnings)


def stoich(reaction: str, scale_mmol: float = 1.0,
           yield_percent: float = None) -> dict:
    '''Equivalents, mmol and mass for a reaction written as A.B>>C.'''
    started = time.perf_counter()
    try:
        table = stoich_mod.table(reaction, scale_mmol, yield_percent)
    except Exception as exc:
        return envelope(False, None, failure(
            ErrorCode.PARSE_FAILED, 'stoich', str(exc)[:160],
            hint="write it as 'CC(=O)O.OCC>>CC(=O)OCC.O'"),
            (time.perf_counter() - started) * 1000)
    return envelope(True, table, None,
                    (time.perf_counter() - started) * 1000)


def _bond_points(centres) -> float:
    '''Median nearest-neighbour distance between atom centres, in points.

    A bond length is the distance between two bonded atoms, and every non-
    terminal atom has a neighbour at that distance. Taking the nearest
    neighbour of each atom and the median recovers it without the bond list.
    '''
    values = []
    for index, first in enumerate(centres):
        best = None
        for other, second in enumerate(centres):
            if other == index:
                continue
            gap = ((first['x'] - second['x']) ** 2 +
                   (first['y'] - second['y']) ** 2) ** 0.5
            if best is None or gap < best:
                best = gap
        if best:
            values.append(best)
    if not values:
        return 0.0
    values.sort()
    return values[len(values) // 2]


def _composite_caption(path: str, text: str) -> bool:
    '''Put a caption band above the scheme, in the exported PNG.

    ChemDraw cannot place the text where it belongs on this build (measured:
    CDXML text ignores its coordinate, and a labelled atom renders only in a
    payload that then loses its arrow). Compositing keeps the chemistry drawing
    vendor-native and the caption deterministic -- and the envelope says which
    one drew what.
    '''
    if not text or not os.path.exists(path):
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return False
    try:
        with Image.open(path) as source:
            image = source.convert('RGB')
        width, height = image.size
        size = max(16, int(round(width / 42.0)))
        band = int(size * 1.9)
        font = None
        for candidate in ('arial.ttf', 'DejaVuSans.ttf', 'segoeui.ttf'):
            try:
                font = ImageFont.truetype(candidate, size)
                break
            except Exception:
                continue
        canvas = Image.new('RGB', (width, height + band), 'white')
        canvas.paste(image, (0, band))
        draw = ImageDraw.Draw(canvas)
        if font is None:
            draw.text((width // 2, band // 2), text, fill='black',
                      anchor='mm')
        else:
            draw.text((width // 2, band // 2), text, fill='black', font=font,
                      anchor='mm')
        canvas.save(path, format='PNG')
        return True
    except Exception:
        return False


def reaction_scheme(reaction: str, conditions: str = '', width_mm: float = None,
                    dpi: int = 300, out_dir: str = None, visible: bool = False,
                    name: str = '', allow_widen: bool = True) -> dict:
    '''Reactants + arrow + products on one page, laid out by ChemDraw from RXN.

    The vendor renderer owns the layout: hand-placed CDXML graphics measured
    unreliable (accepted and drawn on a simple page, dropped on this one), and
    an RXN block carries the atom map numbers into the drawing, so the picture
    and the file agree.
    '''
    started = time.perf_counter()
    warnings = []
    try:
        reactants, products = reaction_mod.split(reaction)
    except ValueError as exc:
        return envelope(False, None, failure(
            ErrorCode.PARSE_FAILED, 'parse', str(exc),
            hint='write the reaction as A.B>>C.D'),
            (time.perf_counter() - started) * 1000)
    try:
        r_mols, p_mols, rows = reaction_mod.map_atoms(reactants, products)
    except ValueError as exc:
        return envelope(False, None, failure(
            ErrorCode.PARSE_FAILED, 'map', str(exc)),
            (time.perf_counter() - started) * 1000)
    kinds = {}
    for row in rows:
        kinds[row['match']] = kinds.get(row['match'], 0) + 1
    block = reaction_mod.rxn_block(r_mols, p_mols, rows)
    mapped = reaction_mod.mapped_smiles(r_mols, p_mols, rows)
    exact = kinds.get('exact', 0)
    if exact < len(rows):
        warnings.append('%d of %d product atoms have no exact match in the reactants'
                        % (len(rows) - exact, len(rows)))
    route = routes.pick('draw')
    if not route:
        return envelope(False, None, failure(
            ErrorCode.NOT_INSTALLED, 'route', 'no drawing route is available',
            hint='install ChemDraw'),
            (time.perf_counter() - started) * 1000)
    target_dir = out_dir or artifacts_dir('reaction')
    os.makedirs(target_dir, exist_ok=True)
    stem = _slug(name or 'reaction')
    png = os.path.join(target_dir, '%s-%d.png' % (stem, int(time.time())))
    wanted_width = float(width_mm or 170.0)
    text_ok = None
    atoms = bonds = 0
    annotations = 0
    try:
        with session.open_session(visible=visible) as channel:
            inserted = channel.insert_rxn(block)
            if not inserted.ok:
                return envelope(False, {'mapping': rows},
                                _as_dict(getattr(inserted, 'failure', None)),
                                (time.perf_counter() - started) * 1000)
            # The conditions are composited onto the exported figure further down.
            # Two vendor routes were measured and both fail: a CDXML <t p> insert
            # ignores its position, and a labelled pseudo atom renders text only
            # when it shares one payload with the structures -- and then the arrow
            # graphic is dropped. One payload cannot carry both, and a second
            # payload lands at the content centre regardless of its coordinates.
            centres = channel.atom_centres()
            bond_pt = _bond_points((centres.data or {}).get('centres') or [])
            box = channel.content_bounds()
            span_pt = float((box.data or {}).get('width_pt') or 0.0) if box.ok else 0.0
            exported = channel.export_figure(png, width_mm=wanted_width, dpi=dpi)
            if not exported.ok:
                return envelope(False, {'mapping': rows},
                                _as_dict(getattr(exported, 'failure', None)),
                                (time.perf_counter() - started) * 1000)
            atoms = int(channel._doc.Atoms.Count)
            bonds = int(channel._doc.Bonds.Count)
    except session.SessionError as exc:
        return envelope(False, None, _as_dict(exc.result.failure),
                        (time.perf_counter() - started) * 1000)
    except Exception as exc:
        return envelope(False, None, failure(
            ErrorCode.UNKNOWN, 'reaction',
            '%s: %s' % (type(exc).__name__, exc)),
            (time.perf_counter() - started) * 1000)
    if conditions:
        text_ok = _composite_caption(png, conditions)
        if text_ok:
            warnings.append('conditions are composited onto the figure by this tool')
        else:
            warnings.append('the conditions caption could not be composited')
    width_px = 0
    try:
        from PIL import Image
        with Image.open(png) as image:
            width_px = int(image.size[0])
    except Exception:
        pass
    px_per_pt = (width_px / span_pt) if (width_px and span_pt) else 0.0
    bond_px = bond_pt * px_per_pt
    readable = bond_px >= 8.0
    suggested = wanted_width
    if not readable and bond_px and allow_widen:
        suggested = min(round(wanted_width * (8.0 / bond_px), 1), 420.0)
        if suggested > wanted_width:
            warnings.append('median bond was %.1f px at %g mm; widened to %g mm'
                            % (bond_px, wanted_width, suggested))
    data = {
        'reactants': reactants,
        'products': products,
        'mapped_smiles': mapped,
        'conditions': conditions,
        'mapping': rows,
        'mapping_counts': kinds,
        'rxn_lines': len(block.splitlines()),
        'page': {'atoms': max(atoms - annotations, 0), 'bonds': bonds,
                 'annotations': annotations},
        'preview': {
            'path': png,
            'bytes': os.path.getsize(png) if os.path.exists(png) else 0,
            'width_mm': wanted_width,
            'dpi': dpi,
            'median_bond_px': round(bond_px, 2),
            'readable': readable,
            'suggested_width_mm': suggested,
            'geometry': 'measured from the page atom centres',
        },
        'conditions_placed': text_ok,
    }
    return envelope(True, data, None, (time.perf_counter() - started) * 1000,
                    warnings)


def three_d(source: str, optimize: bool = True, out_dir: str = None,
            label: str = '') -> dict:
    '''Embed a 3D conformer and write .mol + .xyz next to each other.'''
    started = time.perf_counter()
    kind, mol = _read_source(source)
    if mol is None:
        return envelope(False, None, failure(
            ErrorCode.PARSE_FAILED, '3d', 'could not read the structure',
            hint='give SMILES, InChI or a molblock'),
            (time.perf_counter() - started) * 1000)
    try:
        built = geom3d.embed(props.to_smiles(mol), optimize=optimize)
    except Exception as exc:
        return envelope(False, None, failure(
            ErrorCode.UNKNOWN, '3d', str(exc)[:160]),
            (time.perf_counter() - started) * 1000)
    folder = out_dir or artifacts_dir('3d')
    os.makedirs(folder, exist_ok=True)
    stem = _slug(label or _identity(mol)['inchikey'])
    stamp = int(time.time())
    mol_path = os.path.join(folder, '%s-%d.mol' % (stem, stamp))
    xyz_path = os.path.join(folder, '%s-%d.xyz' % (stem, stamp))
    with open(mol_path, 'w', encoding='utf-8') as handle:
        handle.write(geom3d.to_molblock(built['mol']))
    with open(xyz_path, 'w', encoding='utf-8') as handle:
        handle.write(geom3d.to_xyz(built['mol']))
    data = {'method': built['method'], 'energy_kcal': built['energy_kcal'],
            'converged': built['converged'],
            'atoms_with_h': built['atoms_with_h'],
            'mol': mol_path, 'xyz': xyz_path,
            'identity': _identity(mol),
            'artifacts': [mol_path, xyz_path]}
    warnings = ([] if built['converged'] else
                ['the force field did not fully converge; treat the geometry as a start'])
    return envelope(True, data, None,
                    (time.perf_counter() - started) * 1000, warnings)

def resolve_name(query: str, allow_network: bool = True) -> dict:
    '''Name, trivial name or CAS number to a verified structure (FR-I1).'''
    started = time.perf_counter()
    row = resolve.resolve(query, allow_network=allow_network)
    if not row.get('ok'):
        return envelope(False, {'query': query, 'tried': row.get('tried')},
                        failure(ErrorCode.PARSE_FAILED, 'resolve',
                                row.get('reason') or 'not found',
                                hint='give SMILES or InChI instead'),
                        (time.perf_counter() - started) * 1000)
    kind, mol = _read_source(row['smiles'])
    if mol is None:
        return envelope(False, {'query': query, 'smiles': row['smiles']},
                        failure(ErrorCode.PARSE_FAILED, 'resolve',
                                'the resolved SMILES did not parse'),
                        (time.perf_counter() - started) * 1000)
    data = {'query': query, 'smiles': row['smiles'],
            'source': row['source'], 'tried': row.get('tried'),
            'identity': _identity(mol)}
    degraded = row['source'] != 'local-names'
    return envelope(True, data, None,
                    (time.perf_counter() - started) * 1000,
                    degraded=degraded,
                    degrade_reason='' if not degraded else
                                   'answered by %s, not the offline dictionary'
                                   % row['source'])


def ocr_probe() -> dict:
    '''Which readers exist on this machine, and what each one is missing.'''
    started = time.perf_counter()
    reports = ocr_mod.engine_reports()
    ready = [name for name, row in reports.items() if row.get('available')]
    warnings = []
    if not ready:
        warnings.append('no reader can run here: install one of the engines below')
    return envelope(True, {'engines': reports, 'ready': ready}, None,
                    (time.perf_counter() - started) * 1000, warnings)


def ocr(image_path: str, llm_hint: str = '', engines=None) -> dict:
    '''Picture to structure with several readers and an RDKit arbiter (FR-I2).'''
    started = time.perf_counter()
    if not os.path.exists(image_path):
        return envelope(False, None, failure(
            ErrorCode.NOT_INSTALLED, 'ocr', 'no such image: %s' % image_path),
            (time.perf_counter() - started) * 1000)
    try:
        result = ocr_mod.read_image(image_path, llm_hint=llm_hint,
                                    engines=engines,
                                    out_dir=artifacts_dir('ocr'))
    except Exception as exc:
        return envelope(False, None, failure(
            ErrorCode.UNKNOWN, 'ocr', '%s: %s' % (type(exc).__name__, exc)),
            (time.perf_counter() - started) * 1000)
    best = result.get('best')
    warnings = list(result.get('notes') or [])
    if not best:
        return envelope(False, result, failure(
            ErrorCode.PARSE_FAILED, 'ocr',
            'no reader produced a structure RDKit accepts',
            hint='pass the SMILES you read yourself as llm_hint'),
            (time.perf_counter() - started) * 1000, warnings)
    data = {'best': best, 'candidates': result['candidates'],
            'rejected': result['rejected'],
            'needs_confirmation': result['needs_confirmation'],
            'prepared_image': result.get('prepared_image'),
            'engines': result.get('engines'),
            'engine_ms': result.get('engine_ms'),
            'proposals': result.get('proposals'),
            'readers': result.get('readers'),
            'differing': result.get('differing')}
    # Reading is only half the evidence: redraw what was read, with the same
    # pipeline that drew the original. A picture next to the input shows a wrong
    # substituent faster than any confidence number.
    redrawn = {}
    try:
        rerun = draw(best['smiles'], dpi=300, out_dir=artifacts_dir('ocr-redraw'))
        if rerun.get('ok'):
            redrawn = dict((rerun.get('data') or {}).get('preview') or {})
    except Exception as exc:
        warnings.append('could not redraw the answer: %s' % str(exc)[:80])
    if redrawn:
        data['redrawn'] = redrawn
        data['compare'] = {'original': image_path, 'redrawn': redrawn.get('path')}
    if result['needs_confirmation']:
        warnings.append('only one reader agrees; ask the user to confirm')
    differing = result.get('differing') or []
    if differing:
        warnings.append('reads differently: %s' % ', '.join(
            '%s (%s)' % (row['source'], row['smiles']) for row in differing))
    return envelope(True, data, None,
                    (time.perf_counter() - started) * 1000, warnings)

def grade(answer: str, students, labels=None) -> dict:
    '''Mark a class against one answer structure (FR-T1).'''
    started = time.perf_counter()
    try:
        report = grade_mod.grade(answer, students, labels)
    except Exception as exc:
        return envelope(False, None, failure(
            ErrorCode.PARSE_FAILED, 'grade', str(exc)[:160],
            hint='the answer must be SMILES, InChI or a molblock'),
            (time.perf_counter() - started) * 1000)
    data = report
    warnings = []
    unreadable = report['counts'].get('unreadable', 0)
    if unreadable:
        warnings.append('%d submission(s) could not be parsed' % unreadable)
    return envelope(True, data, None,
                    (time.perf_counter() - started) * 1000, warnings)


def variants(scaffold: str, substituents, labels=None) -> dict:
    '''One scaffold, N questions: replace the dummy atom (FR-T2).'''
    started = time.perf_counter()
    try:
        report = variants_mod.expand(scaffold, substituents, labels)
    except Exception as exc:
        return envelope(False, None, failure(
            ErrorCode.PARSE_FAILED, 'variants', str(exc)[:160],
            hint='the scaffold needs one [*] attachment point'),
            (time.perf_counter() - started) * 1000)
    warnings = []
    if report['duplicates']:
        warnings.append('%d variant(s) duplicated another' % report['duplicates'])
    for row in report['failed']:
        warnings.append('%s: %s' % (row['label'], row['reason']))
    ok = bool(report['variants'])
    return envelope(ok, report, None if ok else failure(
        ErrorCode.PARSE_FAILED, 'variants', 'no variant could be built'),
        (time.perf_counter() - started) * 1000, warnings)

def _as_dict(obj) -> dict:
    '''A failure object as the flat dict the envelope uses.'''
    if obj is None:
        return failure(ErrorCode.UNKNOWN, 'unknown', 'no detail')
    if isinstance(obj, dict):
        return obj
    return {'code': getattr(obj, 'code', ErrorCode.UNKNOWN),
            'stage': getattr(obj, 'stage', ''),
            'message': getattr(obj, 'message', str(obj)),
            'hint': getattr(obj, 'hint', ''),
            'detail': getattr(obj, 'detail', '')}