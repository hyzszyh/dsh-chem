r'''Adapter tests for the ChemDraw COM channel: SMILES in, PNG out.

Run with the 64-bit interpreter, because ChemDraw automation is x64 only:

    %LOCALAPPDATA%\Programs\Python\Python311\python.exe test/test_cd_adapter.py

The file is pytest-compatible (test_* functions, plain asserts) and also has a
__main__ runner, matching test_kd_adapter.py. It exits non-zero when a test
fails, so the CLI gate can call it directly.

The suite starts by killing stray ChemDraw processes (set CD_TEST_NO_KILL=1 if a
real instance must survive). ChemDraw on this build has several silent no-ops
and the tests pin them down instead of pretending otherwise:

* Document.Close() does nothing: the count keeps its value and the atoms stay.
* SaveAs ignores non-ASCII paths: no file, no exception. The export test writes
  into this project's Chinese path, which is the case a user hits first.
* SaveAs tags every PNG 144 dpi and writes RGBA with a transparent background.
* Width/Height only pad the canvas; the drawing keeps its natural size of
  resolution/36 pixels per point.

Every assertion is a measured fact about ChemDraw 26.1.0.6327 on this machine.
'''

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))

from chemdraw_tool.adapters import cd_com  # noqa: E402
from chemdraw_tool.models import ErrorCode, Result  # noqa: E402

ASPIRIN = 'CC(=O)Oc1ccccc1C(=O)O'
PHENOL = 'c1ccccc1O'
OUT_DIR = os.path.join(HERE, 'out')
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'

_channel = None
_owner = None


def channel() -> cd_com.ChemDrawChannel:
    '''One channel for the whole run: every test reuses its document.'''
    global _channel
    if _channel is None:
        _channel = cd_com.ChemDrawChannel()
        res = _channel.connect()
        assert res.ok, 'connect failed: %s' % json.dumps(res.to_dict(), ensure_ascii=False)
    return _channel


def _ok(res: Result) -> Result:
    assert isinstance(res, Result), 'expected a Result, got %r' % (res,)
    assert res.ok, 'call failed: %s' % json.dumps(res.to_dict(), ensure_ascii=False)
    assert res.channel == 'chemdraw', 'channel tag lost: %r' % (res.channel,)
    return res


def _chemdraw_pids() -> str:
    return subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ChemDraw.exe',
                           '/FO', 'CSV', '/NH'],
                          capture_output=True, text=True, timeout=30).stdout


def _kill_stray_chemdraw() -> None:
    if os.environ.get('CD_TEST_NO_KILL'):
        return
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'ChemDraw.exe'],
                       capture_output=True, timeout=30)
    except Exception:
        pass
    time.sleep(1.0)


def _ink_size(path: str):
    '''Bounding box of the non-transparent pixels and the file's colour mode.'''
    from PIL import Image
    with Image.open(path) as image:
        mode = image.mode
        alpha = image.convert('RGBA').split()[-1]
        box = alpha.getbbox()
        size = image.size
    if not box:
        return {'mode': mode, 'canvas': size, 'ink': None}
    return {'mode': mode, 'canvas': size,
            'ink': (box[2] - box[0], box[3] - box[1])}


def test_00_stray_processes_are_gone():
    '''Hygiene first: a wedged instance from an earlier run must not answer.'''
    _kill_stray_chemdraw()
    out = _chemdraw_pids()
    assert 'ChemDraw.exe' not in out, 'a ChemDraw instance survived taskkill: ' + out[:200]


def test_01_connect_reports_attach_vs_start():
    ch = cd_com.ChemDrawChannel()
    res = _ok(ch.connect())
    for key in ('progid', 'attached', 'started_by_us'):
        assert key in res.data, 'missing %r in %r' % (key, res.data)
    assert isinstance(res.data['attached'], bool)
    assert isinstance(res.data['started_by_us'], bool)
    assert res.data['attached'] != res.data['started_by_us'], res.data
    assert res.data['progid'].lower().startswith('chemdraw'), res.data['progid']
    again = _ok(ch.connect())
    assert again.data.get('reused') is True, 'connect() must be idempotent'
    _ok(ch.close())


def test_02_draw_smiles_inserts_the_whole_molecule():
    ch = channel()
    res = _ok(ch.draw_smiles(ASPIRIN))
    data = res.data
    assert data['route'] == 'smiles', data['route']
    assert data['atoms_after'] == 13, data
    assert data['bonds_after'] == 13, data
    assert data['readback_smiles'], 'ChemDraw read nothing back'
    assert data['roundtrip'] == 'exact', data['roundtrip']


def test_03_every_documented_route_inserts_aspirin():
    '''smiles / molblock / cdxml / paste / objects all reach the page.'''
    ch = channel()
    seen = {}
    for route in cd_com.ROUTES:
        res = ch.draw_smiles(ASPIRIN, route=route)
        assert res.ok, '%s failed: %s' % (route, json.dumps(res.to_dict(), ensure_ascii=False))
        assert res.data['atoms_after'] == 13, (route, res.data)
        assert res.data['bonds_after'] == 13, (route, res.data)
        seen[route] = res.data.get('roundtrip', '')
    # The SMILES/molfile/CDXML routes give ChemDraw real bond orders. The
    # MakeAtom route only places atoms and bonds, so implicit hydrogens are not
    # recorded and the read-back formula differs; that gap is reported rather
    # than hidden, and it is why 'smiles' is the default route.
    for route in ('smiles', 'molblock', 'cdxml', 'paste'):
        assert seen[route] == 'exact', (route, seen)
    assert seen['objects'] in ('exact', 'formula-only', 'differs'), seen
    print('    route roundtrip: %s' % seen)


def test_04_draw_smiles_refuses_unparsable_input():
    res = channel().draw_smiles('not-a-smiles')
    assert isinstance(res, Result)
    assert not res.ok, res.to_dict()
    assert res.failure is not None and res.failure.code == ErrorCode.PARSE_FAILED, res.failure
    assert 'not-a-smiles' in res.failure.detail, res.failure.detail


def test_05_read_current_answers_three_mimes():
    ch = channel()
    _ok(ch.draw_smiles(ASPIRIN))
    smi = _ok(ch.read_current('smiles'))
    assert smi.data['mime'] == 'chemical/x-daylight-smiles', smi.data
    assert smi.data['chars'] >= 9, smi.data
    mol = _ok(ch.read_current('molfile'))
    assert 'V2000' in mol.data['text'], mol.data['text'][:120]
    assert mol.data['text'].rstrip().endswith('M  END'), mol.data['text'][-40:]
    assert mol.data['chars'] > 500, mol.data['chars']
    xml = _ok(ch.read_current('cdxml'))
    assert xml.data['text'].lstrip().startswith('<?xml'), xml.data['text'][:60]
    assert '<page' in xml.data['text'], xml.data['text'][:200]


def test_06_export_png_from_a_chinese_path():
    r'''The acceptance case: aspirin -> PNG larger than 1 KB.

    A Chinese destination is exactly the case where SaveAs silently writes
    nothing, so this test also proves the ASCII staging workaround. The
    directory is named here on purpose: relying on the checkout's own path
    meant the suite only passed when the repo happened to live under a
    Chinese folder -- cloned to C:/src it failed instead of skipping.
    '''
    ch = channel()
    _ok(ch.draw_smiles(ASPIRIN))
    bounds = _ok(ch.content_bounds())
    assert bounds.data['atoms'] == 13, bounds.data
    assert 60 < bounds.data['width_pt'] < 80, bounds.data['width_pt']
    chinese = os.path.join(OUT_DIR, '导出中文路径')
    os.makedirs(chinese, exist_ok=True)
    target = os.path.join(chinese, 'aspirin.png')
    if os.path.exists(target):
        os.remove(target)
    res = _ok(ch.export(target, 'png', 300))
    padded = _ok(ch.export(target.replace('.png', '_padded.png'), 'png', 300,
                           trim=False))
    path = res.data['path']
    size = res.data['bytes']
    assert os.path.isfile(path), path
    assert size == os.path.getsize(path), (size, os.path.getsize(path))
    assert size > 1024, 'PNG is only %d bytes: %r' % (size, res.data)
    with open(path, 'rb') as fh:
        assert fh.read(8) == PNG_MAGIC, 'not a PNG: ' + path
    px = res.data['pixel_size']
    assert px and px[0] > 400 and px[1] > 300, px
    assert res.data['staged'] is True, 'a Chinese path must go through staging'
    assert res.data['format']['extension'].lower() == 'png', res.data['format']
    # Measured traps pinned here: the tag says 144 dpi whatever was requested,
    # and leaving Width/Height at the content size avoids a padded canvas.
    assert res.data['dpi_tag'] == 144, res.data['dpi_tag']
    ink = _ink_size(path)
    assert ink['mode'] == 'RGB', ink
    assert ink['ink'][0] > 400, ink
    # trim=True (the default) crops to the drawing; trim=False keeps the padding.
    assert res.data['trimmed'] is not None, res.data
    assert padded.data['trimmed'] is None, padded.data
    padded_ink = _ink_size(padded.data['path'])
    assert padded_ink['mode'] == 'RGBA', padded_ink
    assert padded_ink['ink'][0] < padded.data['pixel_size'][0], padded.data['pixel_size']
    aspect = ink['ink'][0] / float(ink['ink'][1])
    assert 1.15 < aspect < 1.30, 'the cropped picture must keep the drawing aspect: %.2f' % aspect
    print('    %s: %d bytes, %s px, dpi tag %s, ink %s, format index %d (%s)'
          % (os.path.basename(path), size, px, res.data['dpi_tag'], ink['ink'],
             res.data['format']['index'], res.data['format']['mime']))


def test_07_width_only_pads_the_canvas():
    '''Measured: a wider Width does not enlarge the drawing, only the canvas.'''
    ch = channel()
    _ok(ch.draw_smiles(ASPIRIN))
    bounds = _ok(ch.content_bounds())
    region_w = bounds.data['width_pt'] + 2 * cd_com.DEFAULT_MARGIN_PT
    region_h = bounds.data['height_pt'] + 2 * cd_com.DEFAULT_MARGIN_PT
    narrow = _ok(ch.export(os.path.join(OUT_DIR, 'pad_narrow.png'), 'png', 300,
                           region_w, region_h, trim=False))
    wide = _ok(ch.export(os.path.join(OUT_DIR, 'pad_wide.png'), 'png', 300,
                         region_w * 2, region_h * 2, trim=False))
    assert wide.data['pixel_size'][0] > narrow.data['pixel_size'][0] * 1.3, (
        narrow.data['pixel_size'], wide.data['pixel_size'])
    ink_narrow = _ink_size(narrow.data['path'])['ink']
    ink_wide = _ink_size(wide.data['path'])['ink']
    assert abs(ink_wide[0] - ink_narrow[0]) <= max(2, ink_narrow[0] // 50), (
        'the drawing itself must not grow with Width', ink_narrow, ink_wide)
    print('    canvas %s -> %s, ink %s -> %s'
          % (narrow.data['pixel_size'], wide.data['pixel_size'], ink_narrow, ink_wide))


def test_08_export_figure_is_submittable():
    '''Trim, flatten and tag the dpi, then let artwork.check judge the result.'''
    ch = channel()
    _ok(ch.draw_smiles(ASPIRIN))
    target = os.path.join(OUT_DIR, 'aspirin_figure.png')
    if os.path.exists(target):
        os.remove(target)
    res = _ok(ch.export_figure(target, width_mm=50.0, dpi=1200))
    data = res.data
    assert data['trimmed'] is not None, data
    assert data['bytes'] > 1024, data['bytes']
    figure = data.get('figure') or {}
    assert figure.get('mode') == 'RGB', figure
    assert figure.get('dpi') == 1200, figure
    assert abs(figure.get('width_mm', 0) - 50.0) <= 1.0, figure
    check = data.get('check') or {}
    assert check.get('issues') == [], check
    assert check.get('mode') == 'RGB', check
    # Measured: this build caps the image at about 2637 px, so a wider figure
    # than that at 1200 dpi is impossible; the call must say so instead of
    # silently handing back a smaller picture.
    capped = _ok(ch.export_figure(os.path.join(OUT_DIR, 'aspirin_wide.png'),
                                 width_mm=85.0, dpi=1200))
    assert any('caps the exported image' in w for w in capped.warnings), capped.warnings
    # Round 10 changed the answer here. It used to be a 40.7 mm file tagged
    # 1200 dpi: the same pixels, a smaller picture than the one asked for, and
    # a warning that contradicted itself ('574 dpi is the largest that still
    # fills 85 mm'). The tag now follows what the pixels support, so the width
    # is what was asked and the dpi says what it took.
    wide = capped.data['figure']
    assert abs(wide['width_mm'] - 85.0) <= 1.0, wide
    assert wide['dpi'] < 1200, wide
    assert wide.get('requested_dpi') == 1200, wide
    print('    50 mm figure: %s px, %d bytes, dpi %s, issues %s'
          % (figure.get('width_px'), data['bytes'], figure.get('dpi'),
             check.get('issues')))


def test_09_export_svg_and_ascii_path_needs_no_staging():
    ch = channel()
    _ok(ch.draw_smiles(PHENOL))
    ascii_dir = os.path.join(os.environ.get('TEMP', r'C:\Windows\Temp'), 'cd_adapter_test')
    os.makedirs(ascii_dir, exist_ok=True)
    res = _ok(ch.export(os.path.join(ascii_dir, 'phenol.svg'), 'svg', 300))
    assert res.data['staged'] is False, 'an ASCII path must be written directly'
    body = open(res.data['path'], 'rb').read().decode('utf-8', 'replace')
    assert '<svg' in body, body[:120]
    assert res.data['bytes'] > 1024, res.data['bytes']
    print('    svg: %d bytes, %s' % (res.data['bytes'], res.data['format']['mime']))


def test_10_export_format_is_looked_up_by_extension():
    ch = channel()
    types = _ok(ch.export_types())
    exts = {row['extension'].lower() for row in types.data}
    assert 'png' in exts and 'svg' in exts, sorted(exts)
    assert len(types.data) >= 40, 'only %d export types' % len(types.data)
    # Measured: this installation has no PDF export type at all.
    assert 'pdf' not in exts, 'PDF appeared; re-measure before trusting it'
    picked = _ok(ch.find_export_type('png'))
    assert len(picked.data) >= 1
    for row in picked.data:
        assert row['extension'].lower() == 'png' and row['valid'] is True, row
    bad = ch.find_export_type('nosuchext')
    assert not bad.ok and bad.failure.code == ErrorCode.NOT_INSTALLED, bad.to_dict()


def test_11_documents_open_is_a_silent_no_op():
    r'''Documents.Open() neither opens nor raises; the failure must be explicit.'''
    ch = channel()
    path = os.path.join(OUT_DIR, 'two_atoms.xml')
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write('<CDXML><page><fragment><n id="3" p="100 100"/>'
                 '<n id="4" p="114.4 100"/><b id="5" B="3" E="4" Order="1"/>'
                 '</fragment></page></CDXML>')
    before = int(ch._app.Documents.Count)
    res = ch.insert_cdxml_via_file(path)
    assert not res.ok, 'Documents.Open() must not be reported as success'
    assert res.failure.code == ErrorCode.PARSE_FAILED, res.failure.code
    assert 'silent no-op' in res.failure.detail, res.failure.detail
    assert int(ch._app.Documents.Count) == before, res.data


def test_12_empty_page_export_is_a_refusal():
    ch = channel()
    _ok(ch.document())
    assert ch._clear_document(ch._doc), 'the page could not be cleared'
    res = ch.export(os.path.join(OUT_DIR, 'empty.png'))
    assert not res.ok, res.to_dict()
    assert res.failure.stage == 'export', res.failure.stage


def test_13_capabilities_name_the_measured_routes():
    rows = {row.route: row for row in cd_com.ChemDrawChannel().capabilities()}
    assert rows['objects-data-smiles'].available is True
    assert rows['objects-data-smiles'].channel == 'chemdraw'
    assert rows['documents-open'].available is False, rows['documents-open']
    assert rows['document-close'].available is False, rows['document-close']
    for row in rows.values():
        assert row.evidence == 'A', row.to_dict()


def test_14_closing_an_attached_instance_never_quits_it():
    '''A user's ChemDraw window must survive; only our own instance is quit.'''
    global _channel, _owner
    if _channel is not None:
        _ok(_channel.close())
        _channel = None
    _owner = cd_com.ChemDrawChannel()
    owner_res = _ok(_owner.connect())
    assert owner_res.data['attached'] is False, owner_res.data
    assert _owner.started_by_us is True, 'nothing was running, so this one is ours'

    guest = cd_com.ChemDrawChannel()
    guest_res = _ok(guest.connect())
    assert guest_res.data['attached'] is True, guest_res.data
    assert guest.started_by_us is False, guest_res.data
    _ok(guest.draw_smiles(PHENOL))
    before = int(_owner._app.Documents.Count)
    closed = _ok(guest.close())
    assert closed.data['quit'] is False, closed.data
    # The guest only clears its own page (Document.Close() does nothing here),
    # so the owner's instance must still answer and still add documents.
    _owner._doc = None
    _ok(_owner.document())
    after = int(_owner._app.Documents.Count)
    assert after >= 1, 'the owner cannot add documents any more (%d -> %d)' % (before, after)


def test_15_close_quits_the_instance_it_started():
    global _owner
    assert _owner is not None, 'test_14 must run first'
    res = _ok(_owner.close())
    assert res.data['quit'] is True, res.data
    _owner = None
    time.sleep(2.0)
    out = _chemdraw_pids()
    assert 'ChemDraw.exe' not in out, 'Quit did not close the instance: ' + out[:200]


def test_16_a_failed_trim_is_never_silent():
    r'''A requested trim that did not happen must name its cause.

    Two different faults used to collapse into the same None: Pillow missing,
    or a PNG that cannot be read back. The caller saw trimmed=null next to a
    file that was still RGBA, padded and tagged 144 dpi - which reads as
    success and is not. Both halves are pinned here.
    '''
    assert cd_com.pillow_error() is None, cd_com.pillow_error()
    info, error = cd_com._trim_png(os.path.join(HERE, 'test_cd_adapter.py'), None)
    assert info is None and error, 'a non-PNG must not come back as success'
    assert 'trim failed' in error, error
    assert 'Pillow' not in error, 'this failure is not a missing dependency'
    tag, tag_error = cd_com._dpi_tag(os.path.join(HERE, 'test_cd_adapter.py'))
    assert tag is None and tag_error, 'a non-PNG has no readable dpi tag'
    assert 'could not read' in tag_error, tag_error

    ch = channel()
    path = os.path.join(OUT_DIR, 'trim_contract.png')
    _ok(ch.draw_smiles(ASPIRIN))
    res = _ok(ch.export(path))
    assert res.data['trim_error'] is None, res.data['trim_error']
    assert res.data['trimmed'] and res.data['trimmed']['mode'] == 'RGB'
    assert res.data['dpi_tag_error'] is None, res.data['dpi_tag_error']


def test_17_a_second_caller_does_not_draw_into_the_first_ones_page():
    '''Two callers, one ChemDraw: the second must start on an empty page.

    The channel inserts through Documents.Add(), never through ActiveDocument,
    and this test is what keeps it that way: with a page of 13 atoms already
    open in the same application, the next drawer reports atoms_before == 0.
    That number is the whole protection for somebody who has their own drawing
    open -- if a refactor ever switched to ActiveDocument, this fails.
    '''
    first = channel()
    _ok(first.draw_smiles(ASPIRIN))
    assert first._counts()['atoms'] == 13, first._counts()
    second = cd_com.ChemDrawChannel()
    try:
        _ok(second.connect())
        drawn = _ok(second.draw_smiles(PHENOL))
        assert drawn.data['atoms_before'] == 0, (
            'the second caller landed in a page that already had %d atoms'
            % drawn.data['atoms_before'])
        assert drawn.data['atoms_after'] == 7, drawn.data  # phenol: 6 C + 1 O
        assert drawn.data.get('roundtrip') == 'exact', drawn.data
        # The first page is still there, atoms and all: the second caller
        # closed its own document, not ours.
        assert first._counts()['atoms'] == 13, (
            'the first page lost atoms when the second caller closed: %r'
            % (first._counts(),))
    finally:
        second.close()


def test_18_a_structural_export_asks_for_no_dpi_tag():
    '''A mol/cdxml/svg export has no dpi tag, and must not pretend to look for one.

    Measured: cd export --format mol came back ok with the warning 'the dpi tag
    could not be read: ... UnidentifiedImageError', which reads like the export
    failed. Only a raster file can carry a tag; anything else answers null with
    no warning at all.
    '''
    ch = channel()
    _ok(ch.draw_smiles(ASPIRIN))
    for fmt, suffix in (('mol', '.mol'), ('cdxml', '.cdxml'), ('svg', '.svg')):
        path = os.path.join(OUT_DIR, 'structural_export' + suffix)
        if os.path.exists(path):
            os.remove(path)
        res = _ok(ch.export(path, fmt=fmt))
        data = res.data
        assert os.path.isfile(path), 'no %s file at %s' % (fmt, path)
        assert data['bytes'] > 32, data
        assert data['dpi_tag'] is None, (fmt, data['dpi_tag'])
        assert data['dpi_tag_error'] is None, (fmt, data['dpi_tag_error'])
        joined = ' '.join(res.warnings or [])
        assert 'dpi tag could not be read' not in joined, (fmt, joined)
        print('    %-5s %d bytes, no dpi probe' % (fmt, data['bytes']))


def main() -> int:
    tests = [(name, fn) for name, fn in list(globals().items())
             if name.startswith('test_') and callable(fn)]
    passed = 0
    failed = []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed.append((name, str(exc)))
            print('FAIL %s: %s' % (name, exc))
        except Exception as exc:  # pragma: no cover
            failed.append((name, type(exc).__name__ + ': ' + str(exc)))
            print('ERROR %s: %s: %s' % (name, type(exc).__name__, exc))
        else:
            passed += 1
            print('PASS %s' % name)
    print('-' * 60)
    print('%d passed, %d failed, %d total' % (passed, len(failed), len(tests)))
    return 0 if not failed else 1


if __name__ == '__main__':
    code = main()
    for leftover in (_channel, _owner):
        if leftover is not None:
            try:
                leftover.close()
            except Exception:
                pass
    raise SystemExit(code)
