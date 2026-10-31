'''Cross-engine identity: the same molecule through two vendor engines.

Two independent parsers reading one structure agree far more convincingly than
either alone: rdkit is the reference, KingDraw re-derives the molecule through
GRDKitDll.dll, ChemDraw re-derives it through COM, and only the InChIKeys are
compared.

Why InChIKey and not the SMILES text: ChemDraw rewrites what it reads back.
Measured on this machine for aspirin, input 'CC(=O)Oc1ccccc1C(=O)O' comes back
as 'CC(Oc1c(C(O)=O)cccc1)=O' and caffeine comes back as
'Cn(c(=O)c1n(C)cnc1n2C)c2=O' - both the same molecule, neither the same string.
An InChIKey comparison flattens every harmless difference into one verdict.

Process boundary: Crosscheck runs on the 64-bit interpreter because ChemDraw's
COM server is x64, while GRDKitDll.dll is x86. KingDraw calls therefore go
through bin/kd_worker.py in runtime/py32/python.exe, the same bridge the MCP
server uses; nothing here loads a 32-bit DLL into a 64-bit process.

Degradation is explicit, never silent: a missing engine is reported as
available=false with a reason, only-rdkit still answers (a laptop with neither
vendor app installed is a supported state), and the envelope carries
degraded/degrade_reason plus warnings. shutdown() releases the ChemDraw
instance this module started - callers own that decision, because a library
function should not quit an application behind the caller's back.
'''

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Optional

from .models import EVIDENCE_MEASURED, ErrorCode, Failure, Result
from . import identity

CHANNEL = 'crosscheck'
BASIS_INCHIKEY = 'inchikey'
BASIS_CANONICAL = 'canonical-smiles'
BASIS_MIXED = 'mixed:inchikey+canonical-smiles'

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
KD_PY32 = os.path.join(ROOT, 'runtime', 'py32', 'python.exe')
KD_WORKER = os.path.join(ROOT, 'bin', 'kd_worker.py')
KD_TIMEOUT = 60

ENGINES = ('rdkit', 'kingdraw', 'chemdraw')


# -- KingDraw over the 32-bit bridge ---------------------------------------
def _kd_call(op: str, args: dict, timeout: int = KD_TIMEOUT) -> dict:
    '''One KingDraw operation in runtime/py32/python.exe.'''
    if not os.path.isfile(KD_PY32):
        return {'ok': False, 'data': None, 'channel': 'kingdraw',
                'failure': {'code': ErrorCode.KD_BITNESS,
                            'message': 'the bundled 32-bit interpreter is missing',
                            'hint': 'restore runtime/py32/ (scripts/fetch_runtime.py)',
                            'stage': 'bitness'}}
    request = json.dumps({'op': op, 'args': args}, ensure_ascii=False)
    try:
        proc = subprocess.run([KD_PY32, KD_WORKER], input=request,
                              capture_output=True, text=True, encoding='utf-8',
                              errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'data': None, 'channel': 'kingdraw',
                'failure': {'code': ErrorCode.TIMEOUT,
                            'message': 'the KingDraw worker timed out',
                            'stage': 'worker'}}
    except Exception as exc:
        return {'ok': False, 'data': None, 'channel': 'kingdraw',
                'failure': {'code': ErrorCode.UNKNOWN,
                            'message': 'the KingDraw worker could not be started',
                            'detail': '%s: %s' % (type(exc).__name__, exc),
                            'stage': 'worker'}}
    lines = [line for line in (proc.stdout or '').splitlines() if line.strip()]
    for line in reversed(lines):
        try:
            return json.loads(line)
        except Exception:
            continue
    return {'ok': False, 'data': None, 'channel': 'kingdraw',
            'failure': {'code': ErrorCode.UNKNOWN,
                        'message': 'the KingDraw worker answered without JSON',
                        'detail': ((proc.stdout or '') + (proc.stderr or ''))[-400:],
                        'stage': 'worker'}}


# -- one record per engine -------------------------------------------------
def _blank(engine: str) -> dict:
    return {'engine': engine, 'available': False, 'ok': False, 'input': None,
            'smiles': None, 'canonical_smiles': None, 'inchikey': None,
            'formula': None, 'basis': None, 'evidence': None,
            'detail': '', 'artifacts': {}}


def _finish(record: dict) -> dict:
    '''Fill in the derived identity fields for whatever SMILES we ended with.'''
    smiles = record.get('smiles')
    if smiles:
        record['canonical_smiles'] = identity.canonical_smiles(smiles)
        record['inchikey'] = identity.inchikey(smiles)
        record['formula'] = identity.formula(smiles)
    if record['inchikey']:
        record['basis'] = BASIS_INCHIKEY
        record['ok'] = True
        record['evidence'] = EVIDENCE_MEASURED
    elif record.get('canonical_smiles'):
        record['basis'] = BASIS_CANONICAL
        record['ok'] = True
        record['evidence'] = EVIDENCE_MEASURED
        record['detail'] = (record['detail'] + ' ' if record['detail'] else '') + \
            'no InChIKey, compared by canonical SMILES'
    return record


def rdkit_record(smiles: str) -> dict:
    record = _blank('rdkit')
    record['available'] = True
    record['input'] = smiles
    parsed = identity.mol_from_smiles(smiles)
    if parsed is None:
        record['detail'] = ('rdkit is not installed' if not identity.rdkit_available()
                            else 'rdkit could not parse this SMILES')
        return record
    record['smiles'] = identity.canonical_smiles(smiles)
    return _finish(record)


def kingdraw_record(smiles: str, home: Optional[str] = None) -> dict:
    record = _blank('kingdraw')
    record['input'] = smiles
    first = _kd_call('smiles_to_mol', {'smiles': smiles, 'home': home})
    if not first.get('ok'):
        failure = first.get('failure') or {}
        record['detail'] = '%s: %s' % (failure.get('code', '?'),
                                       failure.get('message', 'KingDraw failed'))
        return record
    record['available'] = True
    molblock = (first.get('data') or {}).get('text') or ''
    record['artifacts']['molblock_chars'] = len(molblock)
    back = _kd_call('mol_to_smiles', {'mol': molblock, 'home': home})
    if not back.get('ok'):
        failure = back.get('failure') or {}
        record['detail'] = 'mol_to_smiles failed: %s' % failure.get('message', '')
        return record
    record['smiles'] = (back.get('data') or {}).get('text') or ''
    return _finish(record)


def chemdraw_record(smiles: str) -> dict:
    record = _blank('chemdraw')
    record['input'] = smiles
    import sys
    if sys.maxsize <= 2 ** 32:
        record['detail'] = 'ChemDraw COM is x64; this interpreter is 32-bit'
        return record
    try:
        from .adapters import cd_com
    except Exception as exc:
        record['detail'] = 'the ChemDraw adapter is not importable: %s' % exc
        return record
    channel = cd_com.channel(visible=True)
    connected = channel.connect()
    if not connected.ok:
        record['detail'] = 'ChemDraw is not reachable: %s' % (
            (connected.failure.message if connected.failure else 'connect failed'))
        return record
    record['available'] = True
    drawn = channel.draw_smiles(smiles)
    if not drawn.ok:
        record['detail'] = 'ChemDraw could not draw it: %s' % (
            drawn.failure.message if drawn.failure else 'draw failed')
        return record
    record['artifacts']['atoms'] = drawn.data.get('atoms_after')
    record['artifacts']['bonds'] = drawn.data.get('bonds_after')
    read = channel.read_current('smiles')
    if not read.ok:
        record['detail'] = 'ChemDraw could not read the page back'
        return record
    record['smiles'] = read.data.get('text') or ''
    return _finish(record)


# -- comparison ------------------------------------------------------------
def _compare_records(records: dict, reference: str = 'rdkit'):
    '''Verdict for one molecule across every engine that answered.'''
    ref = records.get(reference) or {}
    ref_key = ref.get('inchikey')
    ref_canon = ref.get('canonical_smiles')
    mismatch = []
    compared = []
    basis = BASIS_INCHIKEY
    for name, record in records.items():
        if name == reference or not record.get('ok'):
            continue
        compared.append(name)

        key = record.get('inchikey')
        if key and ref_key:
            if key != ref_key:
                mismatch.append({'engine': name, 'expected': ref_key, 'got': key,
                                 'smiles': record.get('smiles')})
            continue
        # No InChIKey on at least one side: canonical SMILES is the fallback.
        canon = record.get('canonical_smiles')
        if canon != ref_canon:
            mismatch.append({'engine': name, 'expected': ref_canon, 'got': canon,
                             'smiles': record.get('smiles')})
    unavailable = [name for name, record in records.items()
                   if not record.get('ok')]
    answered = [records[n] for n in compared + [reference]
                if (records.get(n) or {}).get('ok')]
    with_key = [record for record in answered if record.get('inchikey')]
    if answered and len(with_key) == len(answered):
        basis = BASIS_INCHIKEY
    elif not with_key:
        basis = BASIS_CANONICAL
    else:
        basis = BASIS_MIXED
    return {
        'agree': not mismatch,
        'basis': basis,
        'compared': compared,
        'unavailable': unavailable,
        'mismatch': mismatch,
    }


def _collect(smiles: str, use, kingdraw_home: Optional[str] = None) -> dict:
    records = {}
    if 'rdkit' in use:
        records['rdkit'] = rdkit_record(smiles)
    if 'kingdraw' in use:
        records['kingdraw'] = kingdraw_record(smiles, kingdraw_home)
    if 'chemdraw' in use:
        records['chemdraw'] = chemdraw_record(smiles)
    return records


def _degradation(records: dict, requested) -> tuple:
    '''(degraded, reason, warnings) for the engines that did not answer.'''
    degraded = False
    reasons = []
    warnings = []
    for name in requested:
        record = records.get(name) or {}
        if record.get('ok'):
            continue
        degraded = True
        reasons.append('%s unavailable: %s' % (name, record.get('detail') or 'no answer'))
        warnings.append('%s could not be consulted' % name)
    answered = [name for name in requested if (records.get(name) or {}).get('ok')]
    if len(answered) == 1 and answered == ['rdkit']:
        degraded = True
        warnings.append('only rdkit answered: nothing to corroborate against, '
                        'this is a local-only result')
        reasons.append('single engine')
    if records.get('rdkit') and not records['rdkit'].get('ok'):
        degraded = True
        reasons.append('the reference engine (rdkit) could not parse the input')
    return degraded, '; '.join(reasons), warnings


def _result(ok: bool, data: dict, started: float, degraded: bool = False,
            reason: str = '', warnings: Optional[list] = None,
            failure: Optional[Failure] = None) -> Result:
    return Result(ok=ok, data=data, channel=CHANNEL, degraded=degraded,
                  degrade_reason=reason, evidence=EVIDENCE_MEASURED,
                  elapsed_ms=int((time.time() - started) * 1000),
                  warnings=list(warnings or []), failure=failure)


def crosscheck(smiles: str, kingdraw_home: Optional[str] = None,
               engines=ENGINES) -> Result:
    '''Check one molecule: rdkit is the reference, the vendors must agree.

    Returns data {agree, basis, engines:{rdkit,kingdraw,chemdraw}, mismatch,
    compared}. ok means the check ran; agree is the verdict.
    '''
    started = time.time()
    use = tuple(name for name in ENGINES if name in tuple(engines))
    if 'rdkit' not in use:
        return _result(False, None, started, failure=Failure(
            code=ErrorCode.PARSE_FAILED, channel=CHANNEL, stage='crosscheck',
            message='rdkit is the reference engine and cannot be skipped',
            hint='Pass engines including "rdkit"'))
    records = _collect(smiles, use, kingdraw_home)
    verdict = _compare_records(records)
    degraded, reason, warnings = _degradation(records, use)
    reference = records.get('rdkit') or {}
    if not reference.get('ok'):
        return _result(False, {
            'agree': False, 'basis': None, 'input': smiles,
            'engines': records, 'mismatch': [], 'compared': [],
            'reference': None,
        }, started, degraded=True, reason=reason, warnings=warnings,
            failure=Failure(code=ErrorCode.PARSE_FAILED, channel=CHANNEL,
                            stage='crosscheck',
                            message='the structure could not be parsed',
                            hint='Check the SMILES syntax',
                            detail=reference.get('detail', '')))
    data = {
        'agree': verdict['agree'],
        'basis': verdict['basis'],
        'input': smiles,
        'reference': {'engine': 'rdkit', 'smiles': reference.get('smiles'),
                      'inchikey': reference.get('inchikey')},
        'engines': records,
        'compared': verdict['compared'],
        'unavailable': verdict['unavailable'],
        'mismatch': verdict['mismatch'],
    }
    return _result(True, data, started, degraded=degraded, reason=reason,
                   warnings=warnings)


def compare(a: str, b: str, kingdraw_home: Optional[str] = None,
            engines=ENGINES) -> Result:
    '''Are two SMILES the same molecule? Each side is corroborated first.

    This is the case that makes the tool useful for humans: 'c1ccccc1O' and
    'Oc1ccccc1' are the same thing, 'c1ccccc1O' and 'CC(=O)O' are not, and both
    verdicts are backed by two engines each before they are compared.
    '''
    started = time.time()
    left = crosscheck(a, kingdraw_home, engines)
    right = crosscheck(b, kingdraw_home, engines)
    if not left.ok or not right.ok:
        failed = left if not left.ok else right
        return _result(False, {
            'agree': False, 'basis': None,
            'a': left.data, 'b': right.data, 'mismatch': [],
        }, started, degraded=True,
            reason='one side could not be identified',
            warnings=list(left.warnings) + list(right.warnings),
            failure=failed.failure)
    ref_a = (left.data.get('reference') or {})
    ref_b = (right.data.get('reference') or {})
    key_a, key_b = ref_a.get('inchikey'), ref_b.get('inchikey')
    if key_a and key_b:
        basis = BASIS_INCHIKEY
        same = key_a == key_b
    else:
        basis = BASIS_CANONICAL
        same = ref_a.get('smiles') == ref_b.get('smiles')
    mismatch = []
    if not same:
        mismatch.append({'side': 'a', 'inchikey': key_a, 'smiles': ref_a.get('smiles')})
        mismatch.append({'side': 'b', 'inchikey': key_b, 'smiles': ref_b.get('smiles')})
    engines = {}
    for name in tuple(engines):
        engines[name] = {
            'a': (left.data.get('engines') or {}).get(name),
            'b': (right.data.get('engines') or {}).get(name),
        }
    data = {
        'agree': same,
        'basis': basis,
        'a': {'input': a, 'reference': ref_a, 'agree': left.data.get('agree'),
              'basis': left.data.get('basis')},
        'b': {'input': b, 'reference': ref_b, 'agree': right.data.get('agree'),
              'basis': right.data.get('basis')},
        'engines': engines,
        'mismatch': mismatch,
        'corroborated': bool(left.data.get('compared')) and bool(right.data.get('compared')),
    }
    degraded = left.degraded or right.degraded
    reason = '; '.join(filter(None, [left.degrade_reason, right.degrade_reason]))
    return _result(True, data, started, degraded=degraded, reason=reason,
                   warnings=list(left.warnings) + list(right.warnings))


def shutdown() -> Result:
    '''Release the ChemDraw instance this module started (never a user's).'''
    try:
        from .adapters import cd_com
    except Exception as exc:
        return Result(ok=False, channel=CHANNEL, failure=Failure(
            code=ErrorCode.NOT_INSTALLED, channel=CHANNEL, stage='shutdown',
            message='the ChemDraw adapter is not importable', detail=str(exc)))
    return cd_com.close()


__all__ = ['BASIS_INCHIKEY', 'BASIS_CANONICAL', 'BASIS_MIXED', 'CHANNEL',
           'ENGINES', 'crosscheck', 'compare', 'shutdown', 'rdkit_record',
           'kingdraw_record', 'chemdraw_record']
