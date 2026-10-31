'''Adapter tests for the KingDraw native channel.

Run with the 32-bit runtime, because GRDKitDll.dll is x86:

    runtime/py32/python.exe test/test_kd_adapter.py

The file is also pytest-compatible (test_* functions, plain asserts), but has a
__main__ runner so it needs no third-party dependency inside runtime/py32.

Every assertion below is a measured fact about this installation; the bitness
guard test fakes a 64-bit interpreter instead of needing one.
'''

from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))

from chemdraw_tool.adapters import kd_native  # noqa: E402
from chemdraw_tool.models import ErrorCode, Result  # noqa: E402

SAMPLE_KING = os.path.join(kd_native.find_home() or r'D:\tool\KingDraw', 'Cyclohexane.king')
PHENOL = 'c1ccccc1O'
ASPIRIN = 'CC(=O)Oc1ccccc1C(=O)O'


def _ok(res: Result) -> Result:
    assert isinstance(res, Result), 'expected a Result, got %r' % (res,)
    assert res.ok, 'call failed: %s' % (json.dumps(res.to_dict(), ensure_ascii=False),)
    assert res.channel == 'kingdraw', 'channel tag lost: %r' % (res.channel,)
    return res


def test_bitness_guard():
    '''A 64-bit interpreter must get E04, never a ctypes crash.'''
    real = sys.maxsize
    fake = kd_native.KingDrawNative(auto_load=False)
    try:
        sys.maxsize = 2 ** 62
        res = fake.load()
    finally:
        sys.maxsize = real
    assert not res.ok, 'load() must fail on a fake 64-bit interpreter'
    assert res.failure.code == ErrorCode.KD_BITNESS, res.failure.code
    assert fake._dll is None, 'no library may be loaded on the 64-bit path'
    res2 = fake.smiles_to_mol(PHENOL)
    assert not res2.ok and res2.failure.code == ErrorCode.KD_BITNESS


def test_load_reports_all_twelve_exports():
    res = _ok(kd_native.load())
    bound = res.data['exports_bound']
    assert len(bound) == 12, 'bound %d exports: %r' % (len(bound), bound)
    assert len(kd_native.EXPORTS) == 12
    assert res.data['pointer_bits'] == 32, res.data['pointer_bits']
    spec = {(c['export']): c for c in kd_native.capability_spec()}
    assert spec['smilesToMolBA']['arg_bytes'] == 20
    assert spec['cleanUp']['arg_bytes'] == 24
    assert spec['supKingToJson']['arg_bytes'] == 4


def test_smiles_to_mol_returns_molfile():
    res = _ok(kd_native.smiles_to_mol(PHENOL))
    text = res.data['text']
    assert 'RDKit' in text, text[:80]
    assert text.rstrip().endswith('M  END'), text[-40:]
    assert res.data['chars'] > 300, res.data['chars']
    assert res.evidence == 'A'


def test_smiles_mol_smiles_roundtrip():
    mol = _ok(kd_native.smiles_to_mol(PHENOL)).data['text']
    back = _ok(kd_native.mol_to_smiles(mol)).data['text']
    assert back == 'Oc1ccccc1', back
    mol2 = _ok(kd_native.smiles_to_mol(back)).data['text']
    back2 = _ok(kd_native.mol_to_smiles(mol2)).data['text']
    assert back2 == back, 'roundtrip is not stable: %r -> %r' % (back, back2)


def test_get_formula_from_smiles():
    res = _ok(kd_native.get_formula(ASPIRIN))
    assert res.data['text'] == 'C9H8O4', res.data['text']


def test_get_mol_formula_from_molblock():
    mol = _ok(kd_native.smiles_to_mol(ASPIRIN)).data['text']
    res = _ok(kd_native.get_mol_formula(mol))
    assert res.data['text'] == 'C9H8O4', res.data['text']


def test_sup_king_to_json_reads_a_king_sample():
    assert os.path.isfile(SAMPLE_KING), 'sample missing: ' + SAMPLE_KING
    raw = open(SAMPLE_KING, 'rb').read()
    res = _ok(kd_native.sup_king_to_json(raw))
    doc = json.loads(res.data['text'])
    assert doc.get('success') is True, doc
    assert doc.get('code') == 100, doc.get('code')
    data = doc.get('data') or {}
    assert data.get('nodes'), 'king document has no nodes: %r' % (list(data),)
    assert res.data['chars'] > 1000, res.data['chars']


def test_struct_and_substruct_match():
    same = _ok(kd_native.struct_match(PHENOL, 'Oc1ccccc1'))
    assert same.data is True, same.data
    diff = _ok(kd_native.struct_match(PHENOL, 'c1ccccc1'))
    assert diff.data is False, diff.data
    sub_same = _ok(kd_native.substruct_match(PHENOL, PHENOL))
    assert sub_same.data is True


def test_three_d_generators():
    smi3d = _ok(kd_native.smiles2d_to_3d('CCO'))
    assert '3D' in smi3d.data['text'], smi3d.data['text'][:80]
    mol = _ok(kd_native.smiles_to_mol('CCO')).data['text']
    mol3d = _ok(kd_native.mol2d_to_3d(mol))
    assert '3D' in mol3d.data['text'], mol3d.data['text'][:80]


def test_smiles_to_mol_ba_lays_out_v3000():
    res = _ok(kd_native.smiles_to_mol_ba(PHENOL, 200.0, 200.0))
    text = res.data['text']
    assert 'V3000' in text, text[:80]
    assert 'M  V30 COUNTS 7 7' in text, text[:200]


def test_clean_up_relays_out_a_molblock():
    mol = _ok(kd_native.smiles_to_mol(PHENOL)).data['text']
    res = _ok(kd_native.clean_up(mol, 300.0, 300.0))
    text = res.data['text']
    assert 'M  V30' in text or 'V2000' in text, text[:120]
    assert text.rstrip().endswith('END'), text[-40:]


def test_king_clean_up_answers_json():
    raw = open(SAMPLE_KING, 'rb').read()
    res = _ok(kd_native.king_clean_up(raw))
    doc = json.loads(res.data['text'])
    assert 'success' in doc, doc
    assert doc.get('success') is True, doc
    # Slots 2-3 are the doubles: a wider canvas must not break the call.
    res2 = _ok(kd_native.king_clean_up(raw, 800.0, 600.0))
    assert json.loads(res2.data['text']).get('success') is True


def test_parse_failure_is_a_result_not_an_exception():
    res = kd_native.smiles_to_mol('this-is-not-a-smiles')
    assert isinstance(res, Result)
    assert not res.ok, res.to_dict()
    assert res.failure is not None and res.failure.code in (
        ErrorCode.PARSE_FAILED, ErrorCode.UNKNOWN), res.failure.code


def test_native_stdout_is_muted():
    '''The DLL prints debug lines on fd 1; a CLI writing JSON must not see them.'''
    saved = os.dup(1)
    tmp = os.path.join(HERE, 'out', '_stdout_probe.txt')
    os.makedirs(os.path.dirname(tmp), exist_ok=True)
    try:
        fh = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.dup2(fh, 1)
        try:
            kd_native.smiles_to_mol(PHENOL)
            os.write(1, b'CALLER-MARKER\n')
        finally:
            os.dup2(saved, 1)
            os.close(saved)
            os.close(fh)
    finally:
        if os.path.exists(tmp):
            payload = open(tmp, 'rb').read()
            os.remove(tmp)
        else:  # pragma: no cover
            payload = b''
    assert b'CALLER-MARKER' in payload, 'the test lost its own output: ' + repr(payload)
    assert b'new rdkit' not in payload, 'DLL chatter leaked to stdout: ' + repr(payload[:200])
    assert b'atomkey' not in payload, 'DLL chatter leaked to stdout: ' + repr(payload[:200])


def test_no_window_hint_names_the_leftover_process():
    '''A process we never attached to is the confusing case, so name it.

    Measured: one leftover KingDraw process turned a `kd export` into two
    full timeouts (123 s each) and then made four suites fail with three
    different symptoms. The old hint -- 'Leave it running or close it by
    hand; this tool does not kill processes' -- said nothing about a process
    the tool had not attached to, which is exactly the state that produced it.
    '''
    from chemdraw_tool.adapters import kd_open
    hint = kd_open._no_window_hint([], [4242], 90.0)
    assert '4242' in hint, hint
    assert 'taskkill' in hint, hint
    assert 'single-instance' in hint, hint


def test_no_window_hint_offers_the_timeout_knob():
    '''With no process anywhere, the only useful advice is the timeout flag.

    It exists on kd open / kd save / kd export (defaults 20 / 30 / 90) and
    nothing in the failure told the reader so -- a 90 s stall with no escape
    hatch named.
    '''
    from chemdraw_tool.adapters import kd_open
    hint = kd_open._no_window_hint([], [], 90.0)
    assert '--timeout' in hint, hint
    assert '90' in hint, hint


def test_no_window_hint_names_the_instance_we_attached_to():
    from chemdraw_tool.adapters import kd_open
    hint = kd_open._no_window_hint([777], [777], 20.0)
    assert '777' in hint, hint
    assert 'taskkill' not in hint, hint


def main() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith('test_') and callable(fn)]
    if kd_native.is_64bit():
        print('FAIL: run this suite with the 32-bit runtime '
              '(runtime/py32/python.exe); every call would answer E04 here')
        return 2
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
    raise SystemExit(main())
