r'''M1 acceptance gate: both channels, five criteria, one command.

    %LOCALAPPDATA%\Programs\Python\Python311\python.exe test/acceptance_m1.py

Run it with the 64-bit interpreter. The KingDraw library is x86, so the KingDraw
leg is executed in a child process of the bundled 32-bit runtime
(runtime/py32/python.exe) and its measurements come back as JSON; rdkit only
lives in the 64-bit interpreter, so every InChIKey and every formula comparison
is computed on the parent side. That way both channels are measured for real
instead of one being faked.

The five criteria, in the order they are checked:

  1. identity      the same molecule gives the same InChIKey on both channels
  2. kd roundtrip  KingDraw: SMILES -> molfile -> SMILES agrees, and getFormula
                   equals rdkit's formula
  3. cd draw       ChemDraw: at least one atom and one bond after draw_smiles,
                   and an exported PNG that exists and is larger than 1 KB
  4. bad input     an illegal SMILES returns a structured Failure carrying an
                   ErrorCode on both channels, with nothing raised
  5. hygiene       no ChemDraw.exe is left behind at the end

Nothing here patches production code: the module only imports the adapters and
compares what they return. test/out/acceptance_m1.json holds the raw record the
docs table was written from.
'''

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CORE = os.path.join(ROOT, 'core')
if CORE not in sys.path:
    sys.path.insert(0, CORE)

OUT_DIR = os.path.join(HERE, 'out', 'acceptance_m1')
KD_JSON_MARKER = 'M1_KD_JSON:'

# The three molecules named by the acceptance contract.
MOLECULES = [
    ('phenol', 'c1ccccc1O'),
    ('aspirin', 'CC(=O)Oc1ccccc1C(=O)O'),
    ('caffeine', 'CN1C=NC2=C1C(=O)N(C(=O)N2C)C'),
]

# Inputs that no engine should accept. Kept deliberately short: rdkit and
# KingDraw must both refuse them without raising.
BAD_SMILES = ['C1CC(', 'not_a_smiles']

PY32_RELATIVE = os.path.join('runtime', 'py32', 'python.exe')


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def py32() -> str:
    '''The bundled 32-bit interpreter, or sys.executable when already 32-bit.'''
    if sys.maxsize < 2 ** 62:
        return sys.executable
    candidate = os.path.join(ROOT, PY32_RELATIVE)
    return candidate if os.path.exists(candidate) else ''


def chemdraw_pids() -> tuple:
    '''(pids, raw tasklist lines) for ChemDraw.exe, without raising.'''
    try:
        proc = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq ChemDraw.exe', '/NH'],
            capture_output=True, timeout=60)
    except Exception as exc:  # pragma: no cover - tasklist is always there
        return None, ['tasklist failed: %s: %s' % (type(exc).__name__, exc)]
    text = proc.stdout.decode('utf-8', 'replace')
    lines = [line.strip() for line in text.splitlines()
             if 'ChemDraw.exe' in line]
    pids = []
    for line in lines:
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids, lines


def _failure_payload(result) -> dict:
    if result is None:
        return {}
    payload = {'ok': bool(getattr(result, 'ok', False))}
    failure = getattr(result, 'failure', None)
    if failure is not None:
        payload['code'] = failure.code
        payload['message'] = failure.message
        payload['stage'] = failure.stage
        payload['detail'] = failure.detail
    return payload


# --------------------------------------------------------------------------
# KingDraw leg -- runs inside the 32-bit interpreter
# --------------------------------------------------------------------------
def kingdraw_leg() -> dict:
    from chemdraw_tool.adapters import kd_native
    from chemdraw_tool.models import ErrorCode

    record = {'ok': False, 'molecules': {}, 'bad': {}, 'warnings': []}
    load = kd_native.load()
    record['load'] = {
        'ok': load.ok,
        'failure': load.failure.to_dict() if load.failure else None,
        'exports_bound': sorted((load.data or {}).get('exports_bound') or []),
        'pointer_bits': (load.data or {}).get('pointer_bits'),
        'home': (load.data or {}).get('home'),
    }
    if not load.ok:
        return record
    engine = kd_native.engine()

    for name, smiles in MOLECULES:
        rec = {}
        to_mol = engine.smiles_to_mol(smiles)
        rec['smiles_to_mol'] = _failure_payload(to_mol)
        if to_mol.ok:
            molblock = to_mol.data['text']
            rec['molblock_chars'] = len(molblock)
            rec['molblock_version'] = ('V3000' if 'V3000' in molblock
                                       else 'V2000' if 'V2000' in molblock
                                       else 'unknown')
            back = engine.mol_to_smiles(molblock)
            rec['mol_to_smiles'] = _failure_payload(back)
            rec['smiles_back'] = (back.data or {}).get('text') if back.ok else None
            formula_smiles = engine.get_formula(smiles)
            rec['get_formula'] = {
                'ok': formula_smiles.ok,
                'text': ((formula_smiles.data or {}).get('text')
                         if formula_smiles.ok else None),
                'code': (formula_smiles.failure.code
                         if formula_smiles.failure else None),
            }
            formula_mol = engine.get_mol_formula(molblock)
            rec['get_mol_formula'] = {
                'ok': formula_mol.ok,
                'text': ((formula_mol.data or {}).get('text')
                         if formula_mol.ok else None),
                'code': (formula_mol.failure.code if formula_mol.failure else None),
            }
            rec['channel'] = to_mol.channel
        record['molecules'][name] = rec

    for bad in BAD_SMILES:
        raised = None
        try:
            res = engine.smiles_to_mol(bad)
        except BaseException as exc:  # a raised exception is the failure we test for
            raised = '%s: %s' % (type(exc).__name__, exc)
            res = None
        record['bad'][bad] = {
            'raised': raised,
            'result': _failure_payload(res),
            'known_codes': [ErrorCode.PARSE_FAILED, ErrorCode.UNKNOWN],
        }
    record['ok'] = True
    return record


# --------------------------------------------------------------------------
# ChemDraw leg -- runs here, in the 64-bit interpreter
# --------------------------------------------------------------------------
def chemdraw_leg() -> dict:
    from chemdraw_tool.adapters import cd_com
    from chemdraw_tool.models import ErrorCode

    os.makedirs(OUT_DIR, exist_ok=True)
    record = {'ok': False, 'molecules': {}, 'bad': {}, 'warnings': []}
    channel = cd_com.ChemDrawChannel()
    connect = channel.connect()
    record['connect'] = {
        'ok': connect.ok,
        'failure': connect.failure.to_dict() if connect.failure else None,
        'data': connect.data,
    }
    if not connect.ok:
        record['close'] = None
        return record
    record['warnings'].extend(connect.warnings or [])

    for name, smiles in MOLECULES:
        rec = {}
        drawn = channel.draw_smiles(smiles)
        rec['draw'] = _failure_payload(drawn)
        data = drawn.data if isinstance(drawn.data, dict) else {}
        rec['route'] = data.get('route')
        rec['atoms'] = data.get('atoms_after')
        rec['bonds'] = data.get('bonds_after')
        rec['readback_smiles'] = data.get('readback_smiles')
        rec['roundtrip'] = data.get('roundtrip')
        rec['warnings'] = list(drawn.warnings or [])
        if drawn.ok:
            png = os.path.join(OUT_DIR, 'cd_%s.png' % name)
            exported = channel.export(png, fmt='png')
            rec['export'] = _failure_payload(exported)
            if exported.ok:
                info = exported.data
                rec['export'].update({
                    'path': info.get('path'),
                    'bytes': info.get('bytes'),
                    'exists': os.path.exists(info.get('path') or ''),
                    'pixel_size': info.get('pixel_size'),
                    'trimmed': info.get('trimmed'),
                    'staged': info.get('staged'),
                })
                rec['warnings'].extend(exported.warnings or [])
        else:
            rec['export'] = {'ok': False, 'skipped': 'draw failed'}
        record['molecules'][name] = rec

    # Failure path: the channel must answer, not throw.
    for bad in BAD_SMILES:
        raised = None
        try:
            res = channel.draw_smiles(bad)
        except BaseException as exc:
            raised = '%s: %s' % (type(exc).__name__, exc)
            res = None
        record['bad'][bad] = {
            'raised': raised,
            'result': _failure_payload(res),
            'known_codes': [ErrorCode.PARSE_FAILED, ErrorCode.UNKNOWN],
        }

    # The two inputs above never reach ChemDraw: rdkit refuses them first, which
    # proves the envelope but not the channel's own guard. An empty SMILES does
    # parse in rdkit while inserting no atoms, so Objects.Data inserts nothing
    # and the guarded insert has to answer with a Failure of its own.
    raised = None
    try:
        native_res = channel.draw_smiles('')
    except BaseException as exc:
        raised = '%s: %s' % (type(exc).__name__, exc)
        native_res = None
    record['native_reject'] = {
        'input': '<empty smiles>',
        'raised': raised,
        'result': _failure_payload(native_res),
        'detail': (native_res.failure.detail
                   if native_res is not None and native_res.failure else ''),
        'known_codes': [ErrorCode.PARSE_FAILED, ErrorCode.UNKNOWN],
    }

    closed = channel.close()
    record['close'] = {
        'ok': closed.ok,
        'data': closed.data,
        'warnings': list(closed.warnings or []),
        'failure': closed.failure.to_dict() if closed.failure else None,
    }
    record['warnings'].extend(closed.warnings or [])
    record['ok'] = True
    return record


def run_kingdraw_in_child() -> dict:
    '''Execute the KingDraw leg in the 32-bit interpreter and read its JSON.'''
    exe = py32()
    if not exe or not os.path.exists(exe):
        return {'ok': False,
                'error': 'no 32-bit interpreter: expected %s'
                         % os.path.join(ROOT, PY32_RELATIVE)}
    started = time.time()
    try:
        proc = subprocess.run(
            [exe, os.path.abspath(__file__), '--leg', 'kingdraw'],
            capture_output=True, timeout=300,
            env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    except Exception as exc:
        return {'ok': False, 'error': 'child failed to run: %s: %s'
                % (type(exc).__name__, exc)}
    elapsed = round(time.time() - started, 2)
    stdout = proc.stdout.decode('utf-8', 'replace')
    stderr = proc.stderr.decode('utf-8', 'replace')
    payload = None
    for line in stdout.splitlines():
        if line.startswith(KD_JSON_MARKER):
            payload = json.loads(line[len(KD_JSON_MARKER):])
    if payload is None:
        return {'ok': False,
                'error': 'child printed no JSON (exit %d)' % proc.returncode,
                'stdout_tail': stdout[-2000:], 'stderr_tail': stderr[-2000:]}
    payload['interpreter'] = exe
    payload['child_exit'] = proc.returncode
    payload['child_seconds'] = elapsed
    payload['stderr_tail'] = stderr[-1000:]
    return payload


# --------------------------------------------------------------------------
# criteria
# --------------------------------------------------------------------------
def check_identity(kd: dict, cd: dict) -> dict:
    from chemdraw_tool import identity

    rows = []
    passed = True
    for name, smiles in MOLECULES:
        ref = identity.inchikey(smiles)
        kd_smiles = ((kd.get('molecules') or {}).get(name) or {}).get('smiles_back')
        cd_smiles = ((cd.get('molecules') or {}).get(name) or {}).get('readback_smiles')
        kd_key = identity.inchikey(kd_smiles) if kd_smiles else None
        cd_key = identity.inchikey(cd_smiles) if cd_smiles else None
        same = bool(ref and kd_key and cd_key and ref == kd_key == cd_key)
        rows.append({'molecule': name, 'input_smiles': smiles,
                     'rdkit_inchikey': ref, 'kingdraw_inchikey': kd_key,
                     'kingdraw_smiles': kd_smiles,
                     'chemdraw_inchikey': cd_key, 'chemdraw_smiles': cd_smiles,
                     'same': same})
        passed = passed and same
    return {'id': 1, 'name': 'InChIKey agreement across channels',
            'passed': passed, 'rows': rows}


def check_kd_roundtrip(kd: dict) -> dict:
    from chemdraw_tool import identity

    rows = []
    passed = True
    for name, smiles in MOLECULES:
        rec = (kd.get('molecules') or {}).get(name) or {}
        back = rec.get('smiles_back')
        want_canonical = identity.canonical_smiles(smiles)
        got_canonical = identity.canonical_smiles(back) if back else None
        rdkit_formula = identity.formula(smiles)
        kd_formula = (rec.get('get_formula') or {}).get('text')
        kd_mol_formula = (rec.get('get_mol_formula') or {}).get('text')
        roundtrip = bool(want_canonical and got_canonical
                         and want_canonical == got_canonical)
        formula_ok = bool(rdkit_formula and kd_formula
                          and kd_formula == rdkit_formula)
        mol_formula_ok = bool(rdkit_formula and kd_mol_formula
                              and kd_mol_formula == rdkit_formula)
        rows.append({
            'molecule': name,
            'input_smiles': smiles,
            'kingdraw_smiles_back': back,
            'canonical_in': want_canonical,
            'canonical_back': got_canonical,
            'roundtrip_exact': roundtrip,
            'rdkit_formula': rdkit_formula,
            'kingdraw_get_formula': kd_formula,
            'kingdraw_get_mol_formula': kd_mol_formula,
            'formula_same': formula_ok,
            'mol_formula_same': mol_formula_ok,
            'molblock_chars': rec.get('molblock_chars'),
        })
        passed = passed and roundtrip and formula_ok and mol_formula_ok
    return {'id': 2, 'name': 'KingDraw SMILES->molfile->SMILES and formula',
            'passed': passed, 'rows': rows}


def check_cd_draw(cd: dict) -> dict:
    rows = []
    passed = True
    for name, smiles in MOLECULES:
        rec = (cd.get('molecules') or {}).get(name) or {}
        atoms = rec.get('atoms')
        bonds = rec.get('bonds')
        export = rec.get('export') or {}
        size = export.get('bytes')
        path = export.get('path')
        exists = bool(path and os.path.exists(path))
        drawn = bool(isinstance(atoms, int) and atoms > 0
                     and isinstance(bonds, int) and bonds > 0)
        exported = bool(export.get('ok') and exists and isinstance(size, int)
                        and size > 1024)
        rows.append({'molecule': name, 'input_smiles': smiles,
                     'atoms': atoms, 'bonds': bonds,
                     'route': rec.get('route'),
                     'readback_smiles': rec.get('readback_smiles'),
                     'png': path, 'png_exists': exists, 'png_bytes': size,
                     'png_pixels': export.get('pixel_size'),
                     'drawn': drawn, 'exported': exported})
        passed = passed and drawn and exported
    return {'id': 3, 'name': 'ChemDraw draw_smiles then PNG export',
            'passed': passed, 'rows': rows}


def check_bad_input(kd: dict, cd: dict) -> dict:
    from chemdraw_tool.models import ErrorCode

    known = {ErrorCode.PARSE_FAILED, ErrorCode.UNKNOWN,
             ErrorCode.KD_NOT_FOUND, ErrorCode.KD_BITNESS,
             ErrorCode.NOT_INSTALLED}
    rows = []
    passed = True
    for bad in BAD_SMILES:
        kd_rec = (kd.get('bad') or {}).get(bad) or {}
        cd_rec = (cd.get('bad') or {}).get(bad) or {}
        kd_res = kd_rec.get('result') or {}
        cd_res = cd_rec.get('result') or {}
        kd_ok = (not kd_rec.get('raised') and kd_res.get('ok') is False
                 and kd_res.get('code') in known)
        cd_ok = (not cd_rec.get('raised') and cd_res.get('ok') is False
                 and cd_res.get('code') in known)
        rows.append({'input': bad,
                     'kingdraw_raised': kd_rec.get('raised'),
                     'kingdraw_code': kd_res.get('code'),
                     'kingdraw_message': kd_res.get('message'),
                     'chemdraw_raised': cd_rec.get('raised'),
                     'chemdraw_code': cd_res.get('code'),
                     'chemdraw_message': cd_res.get('message'),
                     'kingdraw_structured': kd_ok,
                     'chemdraw_structured': cd_ok})
        passed = passed and kd_ok and cd_ok

    # Extra, ChemDraw only: the channel's own insert guard, reached through an
    # input rdkit accepts. Not required by the contract, reported because the
    # two illegal inputs above are stopped before any COM call.
    native = (cd or {}).get('native_reject') or {}
    if native:
        native_res = native.get('result') or {}
        native_ok = (not native.get('raised')
                     and native_res.get('ok') is False
                     and native_res.get('code') in known)
        rows.append({'input': native.get('input', '<empty smiles>'),
                     'scope': 'chemdraw insert guard only',
                     'kingdraw_raised': None, 'kingdraw_code': None,
                     'kingdraw_message': 'not applicable to this probe',
                     'chemdraw_raised': native.get('raised'),
                     'chemdraw_code': native_res.get('code'),
                     'chemdraw_message': native_res.get('message'),
                     'chemdraw_detail': native.get('detail'),
                     'kingdraw_structured': None,
                     'chemdraw_structured': native_ok})
        passed = passed and native_ok
    return {'id': 4, 'name': 'illegal SMILES -> structured Failure, no raise',
            'passed': passed, 'rows': rows}


def check_hygiene(baseline_pids, baseline_lines, closed: dict) -> dict:
    pids, lines = chemdraw_pids()
    residual = [p for p in (pids or []) if p not in (baseline_pids or [])]
    # Give ChemDraw a moment to finish shutting down after Quit().
    waited = 0.0
    while residual and waited < 20.0:
        time.sleep(1.0)
        waited += 1.0
        pids, lines = chemdraw_pids()
        residual = [p for p in (pids or []) if p not in (baseline_pids or [])]
    return {'id': 5, 'name': 'no ChemDraw.exe left behind',
            'passed': not residual,
            'baseline_pids': baseline_pids, 'baseline_lines': baseline_lines,
            'final_pids': pids, 'final_lines': lines,
            'residual_pids': residual,
            'quit_issued': (closed or {}).get('data', {}).get('quit'),
            'waited_seconds': waited}


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------
def render(results: list) -> str:
    out = []
    out.append('=' * 78)
    out.append('M1 acceptance: ChemDraw + KingDraw, five criteria')
    out.append('=' * 78)
    for item in results:
        status = 'PASS' if item['passed'] else 'FAIL'
        out.append('')
        out.append('[%d/5] %-46s %s' % (item['id'], item['name'], status))
        if item['id'] == 1:
            for row in item['rows']:
                out.append('      %-8s ref=%s' % (row['molecule'],
                                                  row['rdkit_inchikey']))
                out.append('      %-8s kd =%s   (smiles %s)'
                           % ('', row['kingdraw_inchikey'],
                              row['kingdraw_smiles']))
                out.append('      %-8s cd =%s   (smiles %s)'
                           % ('', row['chemdraw_inchikey'],
                              row['chemdraw_smiles']))
        elif item['id'] == 2:
            for row in item['rows']:
                out.append('      %-8s back=%-28s canonical_match=%s'
                           % (row['molecule'], row['kingdraw_smiles_back'],
                              row['roundtrip_exact']))
                out.append('      %-8s formula rdkit=%s kingdraw getFormula=%s '
                           'getMolFormula=%s'
                           % ('', row['rdkit_formula'],
                              row['kingdraw_get_formula'],
                              row['kingdraw_get_mol_formula']))
                out.append('      %-8s molblock=%s chars'
                           % ('', row['molblock_chars']))
        elif item['id'] == 3:
            for row in item['rows']:
                out.append('      %-8s atoms=%s bonds=%s route=%s readback=%s'
                           % (row['molecule'], row['atoms'], row['bonds'],
                              row['route'], row['readback_smiles']))
                out.append('      %-8s png=%s exists=%s bytes=%s px=%s'
                           % ('', row['png'], row['png_exists'],
                              row['png_bytes'], row['png_pixels']))
        elif item['id'] == 4:
            for row in item['rows']:
                out.append('      input=%r  kingdraw: raised=%s code=%s msg=%s'
                           % (row['input'], row['kingdraw_raised'],
                              row['kingdraw_code'], row['kingdraw_message']))
                out.append('      input=%r  chemdraw: raised=%s code=%s msg=%s'
                           % (row['input'], row['chemdraw_raised'],
                              row['chemdraw_code'], row['chemdraw_message']))
        elif item['id'] == 5:
            out.append('      baseline pids=%s final pids=%s residual=%s '
                       'quit=%s' % (item['baseline_pids'], item['final_pids'],
                                    item['residual_pids'],
                                    item['quit_issued']))
            for line in item['final_lines']:
                out.append('      tasklist: ' + line)
    out.append('')
    passed = sum(1 for item in results if item['passed'])
    out.append('-' * 78)
    out.append('%d/%d criteria passed' % (passed, len(results)))
    out.append('-' * 78)
    return '\n'.join(out)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description='M1 acceptance gate for both channels')
    parser.add_argument('--leg', choices=['kingdraw'],
                        help='internal: run one channel leg and print JSON')
    parser.add_argument('--json', action='store_true',
                        help='also print the raw record as JSON')
    args = parser.parse_args(argv)

    if args.leg == 'kingdraw':
        try:
            payload = kingdraw_leg()
        except BaseException:
            payload = {'ok': False, 'error': traceback.format_exc()}
        sys.stdout.write('\n' + KD_JSON_MARKER
                         + json.dumps(payload, ensure_ascii=True) + '\n')
        sys.stdout.flush()
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    baseline_pids, baseline_lines = chemdraw_pids()
    started = time.time()

    kd = run_kingdraw_in_child()
    try:
        cd = chemdraw_leg()
    except BaseException:
        cd = {'ok': False, 'molecules': {}, 'bad': {},
              'error': traceback.format_exc()}
    closed = cd.get('close') if isinstance(cd, dict) else None
    hygiene = check_hygiene(baseline_pids, baseline_lines, closed or {})

    results = [
        check_identity(kd, cd),
        check_kd_roundtrip(kd),
        check_cd_draw(cd),
        check_bad_input(kd, cd),
        hygiene,
    ]

    report = render(results)
    print(report)
    record = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'seconds': round(time.time() - started, 1),
        'interpreter': sys.executable,
        'results': results,
        'kingdraw_leg': kd,
        'chemdraw_leg': {k: v for k, v in cd.items() if k != 'close'} if isinstance(cd, dict) else cd,
        'chemdraw_close': closed,
    }
    out_json = os.path.join(OUT_DIR, 'acceptance_m1.json')
    with open(out_json, 'w', encoding='utf-8') as handle:
        json.dump(record, handle, ensure_ascii=False, indent=1)
    print('raw record: ' + out_json)
    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=1))
    return 0 if all(item['passed'] for item in results) else 1


if __name__ == '__main__':
    sys.exit(main())
