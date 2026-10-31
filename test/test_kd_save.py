'''One command proves the KingDraw save channel: .king out, then read back in.

What "verified" means here, and why:

* KingDraw 26's 另存为 dialog only offers 'KDX 文件(*.kdx)' and appends .kdx to
  whatever name is typed (measured), and a .kdx is a ZIP that GRDKitDll.dll reads
  back as an empty document -- so the app cannot produce a .king.
* .king is plain text with a Ctab block (measured from Cyclohexane.king), so the
  adapter writes that text itself and then hands the bytes to supKingToJson in the
  32-bit runtime. Node count, bond count and the element list must match the
  parsed molfile; a merely non-empty file is not acceptance.
* Finally the app opens the produced .king and UI Automation reports the document
  name, which shows it is a real KingDraw document and not just DLL-readable text.

Run:  runtime/py32/python.exe test/test_kd_save.py
'''
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))

from chemdraw_tool.adapters import kd_native, kd_open, kd_save  # noqa: E402

OUT = os.path.join(HERE, 'out')
STATE = {}
CASES = [('benzene', 'c1ccccc1', 6), ('phenol', 'c1ccccc1O', 7),
         ('aspirin', 'CC(=O)Oc1ccccc1C(=O)O', 13)]


def _say(message):
    print('    ' + message)


def _ok(res, what):
    assert res.ok, '%s failed: %r' % (what, getattr(res, 'failure', None)
                                      and res.failure.to_dict())
    return res


def _src(smiles, name):
    mol = _ok(kd_native.smiles_to_mol(smiles), 'smiles_to_mol(%s)' % name)
    path = os.path.join(OUT, 'kd_save_src_%s.mol' % name)
    with open(path, 'w', encoding='utf-8', newline='') as fh:
        fh.write(mol.data['text'])
    return path


def test_a_molfile_becomes_a_king_document():
    os.makedirs(OUT, exist_ok=True)
    src = _src('c1ccccc1O', 'phenol')
    dest = os.path.join(OUT, 'kd_save_phenol.king')
    if os.path.isfile(dest):
        os.remove(dest)
    started = time.monotonic()
    res = _ok(kd_save.save_as_king(src, dest), 'save_as_king')
    STATE['res'] = res
    STATE['dest'] = res.data['out']
    body = res.data
    _say('%.2fs -> %s (%d bytes), atoms=%r bonds=%r verified_by=%r' % (
        time.monotonic() - started, os.path.basename(body['out']), body['bytes'],
        body['atoms'], body['bonds'], body['verified_by']))
    assert os.path.isfile(body['out']), 'no file was written'
    assert body['bytes'] > 300, 'the .king is suspiciously small: %d' % body['bytes']
    with open(body['out'], 'rb') as fh:
        head = fh.read(64)
    assert head.startswith(b'Begin Header'), 'not KingDraw text: %r' % head[:16]
    assert b'Begin Ctab' in open(body['out'], 'rb').read(), 'no Ctab block'
    assert body['source'] == 'molfile', body['source']
    assert body['method'] == 'king-writer', body['method']


def test_a_heteroatom_names_itself_in_the_written_file():
    '''KingDraw draws the letter of an atom from Label=, not from the element
    column. Measured in round 11: a .king written without it renders as bare
    vertices -- an exported glucose came back as a plain cyclohexane ring and
    caffeine as a bare purine skeleton, while the same structure exported from
    a molfile was correct. The reference file this format was copied from is
    Cyclohexane.king, all carbon, which is why the attribute was missed.
    '''
    src = _src('OC[C@H]1O[C@@H](O)[C@H](O)[C@@H](O)[C@@H]1O', 'glucose')
    dest = os.path.join(OUT, 'kd_save_glucose.king')
    if os.path.isfile(dest):
        os.remove(dest)
    res = _ok(kd_save.save_as_king(src, dest), 'save_as_king')
    with open(res.data['out'], encoding='utf-8', errors='replace') as handle:
        text = handle.read()
    oxygens = [line for line in text.splitlines()
               if line[:1].isdigit() and ' O ' in line and '#' in line]
    carbons = [line for line in text.splitlines()
               if line[:1].isdigit() and ' C ' in line and '#' in line]
    assert len(oxygens) == 6, 'glucose has six oxygens, the file has %d' % len(oxygens)
    # A pyranose has five hydroxyls and one ring oxygen. Measured: the label
    # IS the drawn text ('Label=OH' renders OH, 'Label=O' renders O) and
    # 'HCount=1' beside it changes nothing, so the hydrogen has to be spelled
    # into the label.
    hydroxyls = [line for line in oxygens if 'Label=OH' in line]
    rings = [line for line in oxygens if line.rstrip().endswith('Label=O')]
    assert len(hydroxyls) == 5, 'expected five hydroxyls: %r' % (hydroxyls,)
    assert len(rings) == 1, 'the ring oxygen carries no hydrogen: %r' % (rings,)
    assert not any('Label=' in line for line in carbons), carbons[:2]
    # The colour rides on the atom too, and it is what makes the .king look
    # like the same picture the app draws from a molfile (red O, blue N).
    assert all('#ffff0000' in line for line in oxygens), oxygens[:2]
    assert all('#ff000000' in line for line in carbons), carbons[:2]
    _say('%d HO/OH and %d bare O, %d carbons stay bare'
         % (len(hydroxyls), len(rings), len(carbons)))


def test_stereo_is_reported_as_not_carried():
    '''The .king dialect cannot hold a wedge, so saving a chiral file says so.

    A flattened structure still looks like a perfectly normal drawing, which is
    exactly why silence is the wrong answer: the reader has no way to tell the
    stereocentre was dropped.
    '''
    chiral = ('\n  Mrv1810\n\n  6  5  0  0  0  0            999 V2000\n'
              '    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n'
              '    1.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n'
              '    2.0000    0.7000    0.0000 N   0  0  0  0  0  0  0  0  0  0  0  0\n'
              '    2.0000   -0.7000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n'
              '    3.0000   -0.7000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0\n'
              '    2.0000   -1.4000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0\n'
              '  2  1  1  6\n  2  3  1  0\n  2  4  1  0\n  4  5  2  0\n  4  6  1  0\n'
              'M  END\n')
    flat = chiral.replace('  2  1  1  6', '  2  1  1  0')
    assert kd_save.stereo_bonds(chiral) == 1, kd_save.stereo_bonds(chiral)
    assert kd_save.stereo_bonds(flat) == 0, kd_save.stereo_bonds(flat)
    src = os.path.join(OUT, 'kd_save_stereo.mol')
    with open(src, 'w', encoding='utf-8', newline='') as fh:
        fh.write(chiral)
    dest = os.path.join(OUT, 'kd_save_stereo.king')
    res = _ok(kd_save.save_as_king(src, dest), 'save_as_king(chiral)')
    assert res.degraded, 'a flattened wedge must be reported as degraded'
    assert 'stereo bond' in (res.degrade_reason or ''), res.degrade_reason
    assert res.data['stereo_bonds_not_carried'] == 1, res.data
    assert any('opens flat' in text for text in res.warnings), res.warnings
    _say('1 wedge flattened and reported: %r' % res.degrade_reason[:60])


def test_the_round_trip_matches_the_structure():
    data = STATE['res'].data
    reader = data['reader']
    assert reader['ok'], reader
    assert data['atoms'] == 7, data['atoms']
    assert data['elements'] == ['C', 'C', 'C', 'C', 'C', 'C', 'O'], data['elements']
    assert reader['code'] == 100, reader['code']
    assert reader['type'] == 5, reader['type']
    _say('supKingToJson: success=%r code=%r nodes=%d bonds=%d' % (
        reader['success'], reader['code'], len(reader['nodes']), len(reader['bonds'])))


def test_every_structure_round_trips_with_matching_atom_counts():
    for name, smiles, atoms in CASES:
        src = _src(smiles, name)
        dest = os.path.join(OUT, 'kd_save_%s.king' % name)
        res = _ok(kd_save.save_as_king(src, dest), 'save_as_king(%s)' % name)
        got = res.data
        assert got['atoms'] == atoms, (name, got['atoms'], atoms)
        assert len(got['elements']) == atoms, (name, got['elements'])
        assert got['bonds'] >= atoms - 1, (name, got['bonds'])
        _say('%-8s atoms=%-2d nodes=%-2d bonds=%-2d elements=%r' % (
            name, atoms, got['atoms'], got['bonds'], got['elements']))


def test_kingdraw_opens_the_file_we_wrote():
    dest = STATE['dest']
    pre = kd_open.list_pids()
    STATE['pre_pids'] = list(pre)
    res = _ok(kd_open.open_file(dest, timeout=25), 'open_file(.king)')
    pid = res.data['pid']
    STATE['pid'] = pid
    # open_file checks UIA the moment a window exists; a .king document can still
    # be loading then, so poll the document tab for a few seconds before judging.
    stem = os.path.splitext(os.path.basename(dest))[0]
    docs: list = []
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        probe = kd_open.uia_documents(pid)
        docs = kd_open.document_names(probe.data) if probe.ok else []
        if any(stem.lower() in (n or '').lower() for n in docs):
            break
        time.sleep(0.8)
    _say('opened pid=%r, UIA names=%r (open_file said verified_by=%r)' % (
        pid, docs, res.data.get('verified_by')))
    assert docs, 'the app never reported a document tab for the .king'
    assert any(stem.lower() in (n or '').lower() for n in docs), (
        'the app did not report our document name: %r (stem %r)' % (docs, stem))


def test_the_vendor_app_only_saves_kdx():
    '''The measured reason this adapter writes .king itself instead of driving UI.'''
    kdx = os.path.join(OUT, 'kd_probe_saved.king.kdx')
    if not os.path.isfile(kdx):
        return 'no .kdx sample from the UI save run; nothing to compare'
    with open(kdx, 'rb') as fh:
        head = fh.read(8)
    assert head[:2] == b'PK', 'the .kdx is not a ZIP container: %r' % head
    report = kd_save.verify_king(kdx)
    _say('.kdx is %r (ZIP); GRDKitDll reads back nodes=%r from it' % (
        head[:2].decode('latin1'), report.get('nodes')))
    assert not report.get('text_format'), report
    assert not report.get('ok'), 'a .kdx must not pass the .king check'


def test_bad_input_fails_with_a_structured_failure():
    junk = os.path.join(OUT, 'kd_save_junk.txt')
    with open(junk, 'w', encoding='utf-8') as fh:
        fh.write('this is not a structure\n')
    res = kd_save.save_as_king(junk, os.path.join(OUT, 'kd_save_junk.king'))
    _say('junk -> ok=%r code=%r msg=%r' % (
        res.ok, res.failure and res.failure.code, res.failure and res.failure.message))
    assert not res.ok, 'a text file must not be accepted as a structure'
    assert res.failure.code in ('E06', 'E05'), res.failure.code
    missing = kd_save.save_as_king(os.path.join(OUT, 'nope.mol'))
    assert not missing.ok and missing.failure.code == 'E06', missing.failure.code


def test_a_windowless_leftover_is_cleared_before_launch():
    '''A process with no window cannot show the file, but it does hold the lock.'''
    # Measured: a leftover KingDraw with no window swallowed the launch, so the
    # file went to a window nobody could see, the deadline expired and the call
    # failed with E05 while the file was fine. A stand-in process with no window
    # plays the leftover here: the adapter should clear it before launching.
    import subprocess
    import sys
    dummy = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(180)'])
    real = kd_open.list_pids

    def with_dummy():
        extra = [dummy.pid] if dummy.poll() is None else []
        return real() + extra

    kd_open.list_pids = with_dummy
    try:
        res = kd_open.open_file(STATE['dest'], timeout=25)
    finally:
        kd_open.list_pids = real
        if dummy.poll() is None:
            dummy.kill()
    _ok(res, 'open_file(.king) with a windowless leftover')
    cleared = res.data.get('stale_instances_cleared') or []
    assert any(item['pid'] == dummy.pid for item in cleared), cleared
    # close_app posts WM_CLOSE, which a windowless process never answers, so the
    # guard has to terminate it -- that is what makes this recoverable at all.
    assert any(item.get('terminated') for item in cleared), cleared
    assert dummy.poll() is not None, 'the leftover is still running'
    assert any('no window at all' in text for text in res.warnings), res.warnings
    _say('cleared %r, opened in pid %r' % (cleared, res.data.get('pid')))


def test_no_kingdraw_process_is_left_behind():
    pid = STATE.get('pid')
    if pid:
        closed = kd_open.close_app(pid, 12.0)
        _say('close %r -> %r' % (pid, closed.data))
    left = kd_open.list_pids()
    for other in left:
        if other not in (STATE.get('pre_pids') or []):
            kd_open.close_app(other, 8.0)
    left = kd_open.list_pids()
    _say('pids left: %r' % (left,))
    assert not [p for p in left if p not in (STATE.get('pre_pids') or [])], left


BUDGET_S = 90.0


def test_a_formal_charge_is_spelled_into_the_label():
    '''Charges ride in the drawn text, because the file's own attributes are ignored.'''
    # Measured on acetate: 'Charge=-1' beside the label renders nothing at all,
    # while 'Label=O-' draws the minus. The charge also feeds the hydrogen
    # count -- an O- has one bond and no hydrogen, a neutral hydroxyl has one --
    # so both facts have to be read out of the molfile.
    acetate = ('\n  Mrv1810\n\n  4  3  0  0  0  0            999 V2000\n'
               '    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n'
               '    1.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0\n'
               '    1.0000    1.0000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0\n'
               '    2.0000   -1.0000    0.0000 O   0  0  0  0  0  0  0  0  0  0  0  0\n'
               '  1  2  1  0\n  2  3  2  0\n  2  4  1  0\n'
               'M  CHG  1   4  -1\nM  END\n')
    atoms, bonds = kd_save.parse_molblock(acetate)
    assert atoms[3] == ('O', 2.0, -1.0, -1), atoms[3]
    lines = kd_save.king_text(atoms, bonds).splitlines()
    labels = [line for line in lines if ' Label=' in line]
    assert 'Label=O-' in labels[1], labels
    assert labels[0].split('Label=')[1].strip() == 'O', labels[0]
    _say('acetate: carbonyl stays O, the anion reads O-')


def test_an_isotope_or_a_radical_is_named_as_lost():
    '''The .king format draws neither, and silence about it is the bug.

    Measured: a molfile from [13CH3]C carries MASS=13, one from [CH3] carries
    RAD=2, and the .king written from either holds a bare 'C' -- no label, no
    dot -- while the result said ok with no warning at all. A charge is the
    opposite case: it survives inside the atom label (Label=O-), so it must
    not be reported as lost.
    '''
    heavy = (
        '\n  Mrv1810\n\n  2  1  0  0  0  0            999 V3000\n'
        'M  V30 BEGIN CTAB\nM  V30 COUNTS 2 1 0 0 0\nM  V30 BEGIN ATOM\n'
        'M  V30 1 C 0 0 0 0 MASS=13\nM  V30 2 C 0.6755 0.39 0 0\n'
        'M  V30 END ATOM\nM  V30 BEGIN BOND\nM  V30 1 1 1 2\n'
        'M  V30 END BOND\nM  V30 END CTAB\nM  END\n')
    assert kd_save.unrepresentable_atoms(heavy) == {'isotopes': 1, 'radicals': 0}
    radical = ('\n  Mrv1810\n\n  1  0  0  0  0  0            999 V3000\n'
               'M  V30 BEGIN CTAB\nM  V30 COUNTS 1 0 0 0 0\nM  V30 BEGIN ATOM\n'
               'M  V30 1 C 0 0 0 0 RAD=2 VAL=3\nM  V30 END ATOM\nM  V30 END CTAB\n'
               'M  END\n')
    assert kd_save.unrepresentable_atoms(radical) == {'isotopes': 0, 'radicals': 1}
    plain = ('\n  Mrv1810\n\n  1  0  0  0  0  0            999 V3000\n'
             'M  V30 BEGIN CTAB\nM  V30 COUNTS 1 0 0 0 0\nM  V30 BEGIN ATOM\n'
             'M  V30 1 N 0 0 0 0 CHG=1\nM  V30 END ATOM\nM  V30 END CTAB\nM  END\n')
    assert kd_save.unrepresentable_atoms(plain) == {'isotopes': 0, 'radicals': 0}, (
        'a charge is carried in the label, so it is not lost')

    for name, smiles, field in (('iso', '[13CH3]C', 'isotopes_not_carried'),
                                ('rad', '[CH3]', 'radicals_not_carried')):
        src = _src(smiles, 'kd_save_%s' % name)
        dest = os.path.join(OUT, 'kd_save_%s.king' % name)
        res = _ok(kd_save.save_as_king(src, dest), 'save %s' % name)
        assert res.data[field] == 1, res.data
        assert res.degraded is True, res.degrade_reason
        assert 'cannot draw' in (res.degrade_reason or ''), res.degrade_reason
        assert any('cannot draw' in w for w in res.warnings), res.warnings
        body = open(dest, encoding='utf-8', errors='replace').read()
        assert 'MASS' not in body and 'RAD' not in body, body[:200]
        _say('%s: %r, and the file really has no %s' % (name, field, name))


ORDER = [
    test_a_formal_charge_is_spelled_into_the_label,
    test_a_molfile_becomes_a_king_document,
    test_stereo_is_reported_as_not_carried,
    test_an_isotope_or_a_radical_is_named_as_lost,
    test_the_round_trip_matches_the_structure,
    test_every_structure_round_trips_with_matching_atom_counts,
    test_kingdraw_opens_the_file_we_wrote,
    test_a_windowless_leftover_is_cleared_before_launch,
    test_the_vendor_app_only_saves_kdx,
    test_bad_input_fails_with_a_structured_failure,
    test_no_kingdraw_process_is_left_behind,
]
BUDGET_S = 90.0


def main():
    started = time.monotonic()
    passed = failed = skipped = 0
    for func in ORDER:
        name = func.__name__
        t0 = time.monotonic()
        try:
            note = func()
        except AssertionError as exc:
            failed += 1
            print('FAIL %s (%.2fs)' % (name, time.monotonic() - t0))
            print('    ' + str(exc).strip().replace('\n', '\n    '))
        except Exception:
            failed += 1
            print('ERROR %s (%.2fs)' % (name, time.monotonic() - t0))
            print('    ' + traceback.format_exc().strip().replace('\n', '\n    '))
        else:
            if isinstance(note, str):
                skipped += 1
                print('SKIP %s (%.2fs)' % (name, time.monotonic() - t0))
            else:
                passed += 1
                print('PASS %s (%.2fs)' % (name, time.monotonic() - t0))
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
