'''One command proves the KingDraw channel can produce a picture.

The picture is the preview raster KingDraw embeds in the .kdx it saves: measured
108x120 for phenol, 147x141 for aspirin, 270x233 for cholesterol, JPEG. It is a
PREVIEW -- small, JPEG-compressed, not typeset -- so the adapter reports
source size and upscales for screen use, and every Result carries the
"not publication artwork" warning. Submission figures come from ChemDraw.

What is asserted here, per run: the file exists, Pillow opens it, both sides are
over 200 px, it is not blank (>50 colours, dominant colour under 99%), the
provenance fields name the media entry, and no KingDraw process is left behind.

Run:  <64-bit python with pywinauto+Pillow> test/test_kd_export.py
'''
import os
import shutil
import sys
import tempfile
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))

from chemdraw_tool.adapters import kd_export, kd_native, kd_open  # noqa: E402

OUT = os.path.join(HERE, 'out')
STATE = {}
CASES = [('phenol', 'c1ccccc1O'), ('cholesterol',
                                   'CC(C)CCCC(C)C1CCC2C1(CCC3C2CC=C4C3(CCC(C4)O)C)C')]


def _say(message):
    print('    ' + message)


def _src(smiles, name):
    '''Build the molfile with whichever interpreter can talk to the DLL.'''
    mol = kd_native.smiles_to_mol(smiles)
    if not mol.ok and mol.failure.code == 'E04':
        # 64-bit interpreter: ask the bundled 32-bit runtime for the molfile.
        sys.path.insert(0, os.path.join(ROOT, 'core'))
        from chemdraw_tool.adapters import kd_save
        exe = kd_save.find_python32()
        assert exe, 'no 32-bit interpreter for GRDKitDll.dll'
        import subprocess
        code = ('import sys; sys.path.insert(0, %r);'
                'from chemdraw_tool.adapters import kd_native;'
                'r = kd_native.smiles_to_mol(%r);'
                'assert r.ok, r.failure;'
                'sys.stdout.write(r.data["text"])'
                % (os.path.join(ROOT, 'core'), smiles))
        proc = subprocess.run([exe, '-c', code], capture_output=True, timeout=120)
        assert proc.returncode == 0, proc.stderr.decode('utf-8', 'replace')[-400:]
        text = proc.stdout.decode('utf-8')
    else:
        assert mol.ok, mol.failure and mol.failure.to_dict()
        text = mol.data['text']
    path = os.path.join(OUT, 'kd_export_src_%s.mol' % name)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(text)
    return path


def _margins(path):
    '''Paper on the left, top, right and bottom of the ink, in pixels.'''
    from PIL import Image, ImageChops
    with Image.open(path) as img:
        flat = img.convert('RGB')
    background = flat.getpixel((0, 0))
    diff = ImageChops.difference(flat, Image.new('RGB', flat.size, background))
    box = diff.convert('L').point(lambda v: 255 if v > 24 else 0).getbbox()
    if not box:
        return (0, 0, 0, 0)
    width, height = flat.size
    return (box[0], box[1], width - box[2], height - box[3])


def _check(name, smiles, expect_min_side):
    started = time.monotonic()
    src = _src(smiles, name)
    dest = os.path.join(OUT, 'kd_export_%s.png' % name)
    if os.path.isfile(dest):
        os.remove(dest)
    res = kd_export.export_image(src, dest, timeout=90)
    took = time.monotonic() - started
    if not res.ok:
        raise AssertionError('export(%s) failed: %r' % (name, res.failure.to_dict()))
    data = res.data
    STATE.setdefault('results', {})[name] = res
    _say('%-11s %.1fs -> %dx%d, %d bytes, %d colours, src %s %r, upscaled=%r x%.2f'
         % (name, took, data['width'], data['height'], data['bytes'],
            data['colours'], data['source_name'], data['source_size'],
            data['upscaled'], data['scale']))
    assert os.path.isfile(dest), 'no image was written'
    assert data['out'] == dest, (data['out'], dest)
    # Pillow is optional here on purpose: it is not installed in the 32-bit
    # runtime that owns the KingDraw DLL, so a cross-check that requires it
    # would fail on exactly the interpreter users run. Fall back to the magic
    # bytes, which still prove the file is a real image.
    try:
        from PIL import Image
    except ImportError:
        Image = None
    if Image is not None:
        with Image.open(dest) as img:
            img.load()
            assert img.size == (data['width'], data['height']), (img.size, data)
            assert img.format in ('PNG', 'JPEG', 'WEBP', 'BMP', 'TIFF'), img.format
        # KingDraw puts the structure wherever it likes on its own canvas --
        # measured: caffeine came back flush against the left edge, i.e. cut.
        # The exporter crops to the ink and pastes it onto a fresh canvas, so
        # every side must come back with the same paper.
        with Image.open(dest) as img:
            counts = img.convert('RGB').getcolors(maxcolors=1 << 20) or []
        # KingDraw colours heteroatoms; a .king written in plain black renders
        # as a grey picture of the same molecule. Every molecule here has an
        # oxygen or a nitrogen, so some coloured pixels must exist.
        coloured = sum(n for n, c in counts if max(c) - min(c) > 60)
        _say('%d coloured pixels' % coloured)
        assert coloured > 20, 'no coloured atom pixels: %d' % coloured
        margins = _margins(dest)
        _say('margins L/T/R/B = %d/%d/%d/%d' % margins)
        assert min(margins) >= 4, margins
        assert max(margins) - min(margins) <= 2, margins
    else:
        with open(dest, 'rb') as handle:
            magic = handle.read(8)
        assert magic.startswith(b'\x89PNG\r\n\x1a\n'), magic
    assert data['width'] > 200 and data['height'] > 200, (data['width'], data['height'])
    assert min(data['width'], data['height']) >= expect_min_side, (
        data['width'], data['height'], expect_min_side)
    assert data['colours'] > 50, 'the image is nearly flat: %d colours' % data['colours']
    assert data['dominant'] < 0.99, 'the image is blank: %.2f%% one colour' % (
        data['dominant'] * 100)
    assert data['source_name'].startswith('media/'), data['source_name']
    assert data['bytes'] > 2000, data['bytes']
    joined = ' '.join(res.warnings)
    assert 'preview' in joined.lower(), res.warnings
    assert res.degraded and 'preview' in (res.degrade_reason or ''), res.degrade_reason
    return data


def test_phenol_comes_out_as_a_picture():
    data = _check('phenol', 'c1ccccc1O', 300)
    assert data['source_name'] == 'media/p_jpg.jpg', data['source_name']
    assert data['upscaled'] is True, 'a 108x120 preview has to be upscaled'
    assert len(data['media']) >= 2, data['media']


def test_a_bigger_molecule_comes_out_as_a_picture():
    data = _check('cholesterol',
                  'CC(C)CCCC(C)C1CCC2C1(CCC3C2CC=C4C3(CCC(C4)O)C)C', 200)
    _say('media entries in this .kdx: %r' % (
        [(m['name'], m['width'], m['height'], m['colours']) for m in data['media']],))
    assert data['source_size'][0] >= 200, data['source_size']


def test_a_file_without_media_or_structure_fails_distinctly():
    junk = os.path.join(OUT, 'kd_export_junk.txt')
    with open(junk, 'w', encoding='utf-8') as fh:
        fh.write('not a structure\n')
    res = kd_export.export_image(junk, os.path.join(OUT, 'kd_export_junk.png'))
    _say('junk -> ok=%r code=%r msg=%r' % (
        res.ok, res.failure and res.failure.code, res.failure and res.failure.message))
    assert not res.ok and res.failure.code == 'E06', res.failure and res.failure.code
    # An archive with no media must be reported as "no usable preview", not E99.
    import zipfile
    empty = os.path.join(OUT, 'kd_export_empty.kdx')
    with zipfile.ZipFile(empty, 'w') as zf:
        zf.writestr('protocol', '{}')
    rows = kd_export.media_entries(empty)
    assert rows == [], rows
    assert kd_export.pick_media(rows) is None


def test_no_kingdraw_process_is_left_behind():
    left = kd_open.list_pids()
    _say('pids left: %r' % (left,))
    assert not left, left


def test_a_killed_run_s_debris_is_swept_by_the_next_one():
    '''Windows termination cannot run finally, so the next run clears up.

    Measured with the interrupt test: SIGTERM four seconds into `kd export`
    leaves one empty kd_export_* folder in %TEMP%, and there is no hook that
    could have deleted it -- a terminated process runs no finally block. Even
    a run of the whole suite left exactly one behind, from exactly that test.
    So the next export sweeps: old folders go, anything recent (a live run, a
    --keep-kdx archive) stays.
    '''
    root = tempfile.gettempdir()
    stale = os.path.join(root, 'kd_export_stale_probe')
    fresh = os.path.join(root, 'kd_export_fresh_probe')
    for path in (stale, fresh):
        shutil.rmtree(path, ignore_errors=True)
        os.makedirs(path)
    old = time.time() - 3 * 3600
    os.utime(stale, (old, old))
    try:
        removed = kd_export._sweep_stale_temp()
        _say('swept %r' % ([os.path.basename(p) for p in removed],))
        assert not os.path.isdir(stale), 'the stale folder survived the sweep'
        assert os.path.normpath(stale) in [os.path.normpath(p) for p in removed], removed
        assert os.path.isdir(fresh), 'the sweep deleted a folder it did not own'
        # --keep-kdx leaves an archive on purpose; it is evidence, not debris.
        archive = os.path.join(root, 'kd_export_kept_probe')
        shutil.rmtree(archive, ignore_errors=True)
        os.makedirs(archive)
        with open(os.path.join(archive, 'kept.kdx'), 'wb') as fh:
            fh.write(b'PK\x03\x04kept')
        os.utime(archive, (old, old))
        try:
            again = kd_export._sweep_stale_temp()
            assert os.path.isdir(archive), 'the sweep ate a --keep-kdx archive'
            assert os.path.normpath(archive) not in [os.path.normpath(p)
                                                     for p in again], again
        finally:
            shutil.rmtree(archive, ignore_errors=True)
    finally:
        shutil.rmtree(fresh, ignore_errors=True)
        shutil.rmtree(stale, ignore_errors=True)


ORDER = [
    test_phenol_comes_out_as_a_picture,
    test_a_bigger_molecule_comes_out_as_a_picture,
    test_a_killed_run_s_debris_is_swept_by_the_next_one,
    test_a_file_without_media_or_structure_fails_distinctly,
    test_no_kingdraw_process_is_left_behind,
]
BUDGET_S = 300.0


def main():
    started = time.monotonic()
    passed = failed = skipped = 0
    for func in ORDER:
        t0 = time.monotonic()
        try:
            note = func()
        except AssertionError as exc:
            failed += 1
            print('FAIL %s (%.2fs)' % (func.__name__, time.monotonic() - t0))
            print('    ' + str(exc).strip().replace('\n', '\n    '))
        except Exception:
            failed += 1
            print('ERROR %s (%.2fs)' % (func.__name__, time.monotonic() - t0))
            print('    ' + traceback.format_exc().strip().replace('\n', '\n    '))
        else:
            if isinstance(note, str):
                skipped += 1
                print('SKIP %s (%.2fs)' % (func.__name__, time.monotonic() - t0))
            else:
                passed += 1
                print('PASS %s (%.2fs)' % (func.__name__, time.monotonic() - t0))
        sys.stdout.flush()
    elapsed = time.monotonic() - started
    print('-' * 60)
    print('%d passed, %d skipped, %d failed, %d total in %.1fs (budget %.0fs)'
          % (passed, skipped, failed, passed + skipped + failed, elapsed, BUDGET_S))
    if elapsed > BUDGET_S:
        print('over budget')
        return 1
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
