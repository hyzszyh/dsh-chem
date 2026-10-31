'''KingDraw channel doctor: native library, file format, CLI hand-off.'''

from __future__ import annotations

import ctypes
import os
import sys
import time
from typing import Any, Optional

from ..models import (  # noqa: F401  (bitness_hint is used below)
    DoctorReport, Failure, Capability, ErrorCode, ERROR_TEXT, EVIDENCE_MEASURED,
    bitness_hint,
)

EXPORTS = [
    'supKingToJson', 'kingCleanUp', 'cleanUp', 'molToSmiles', 'smilesToMol',
    'smilesToMolBA', 'substructMatch', 'structMatch', 'getMolFormula',
    'getFormula', 'mol2dTo3d', 'smiles2dTo3d',
]

DEFAULT_HOMES = [
    r'D:\tool\KingDraw',
    r'C:\Program Files\KingDraw',
    r'C:\Program Files (x86)\KingDraw',
]


class _MuteStdout:
    '''The KingDraw DLL writes debug chatter straight to fd 1. Silence it.

    It uses printf from C, so redirecting the file descriptor is the only
    reliable way to keep our own JSON output clean.
    '''

    def __enter__(self):
        self._saved = None
        try:
            self._saved = os.dup(1)
            self._null = os.open(os.devnull, os.O_WRONLY)
            os.dup2(self._null, 1)
        except Exception:
            self._saved = None
        return self

    def __exit__(self, *exc):
        if self._saved is not None:
            try:
                os.dup2(self._saved, 1)
                os.close(self._saved)
                os.close(self._null)
            except Exception:
                pass
        return False


def find_home(explicit: Optional[str] = None) -> Optional[str]:
    '''Locate the KingDraw folder that contains GRDKitDll.dll.'''
    # A folder the caller named (argument or KINGDRAW_HOME) is honoured or
    # refused -- never silently replaced by a default install.
    for named in (explicit, os.environ.get('KINGDRAW_HOME')):
        if named:
            if os.path.isfile(os.path.join(named, 'GRDKitDll.dll')):
                return os.path.abspath(named)
            return None
    candidates = []
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CLASSES_ROOT, r'kingfile\shell\open\command')
        cmd = winreg.QueryValueEx(key, '')[0]
        first = cmd.split('"')[1] if '"' in cmd else cmd.split()[0]
        candidates.append(os.path.dirname(first))
    except Exception:
        pass
    candidates.extend(DEFAULT_HOMES)
    for c in candidates:
        try:
            if c and os.path.isfile(os.path.join(c, 'GRDKitDll.dll')):
                return os.path.abspath(c)
        except Exception:
            continue
    return None


def _bind(dll, name: str):
    '''Bind one export using the signature table the adapter measured.

    The doctor does not keep its own copy of the ABI. adapters/kd_native.py
    derived these shapes from the PE export table and each function's 'ret N'
    epilogue, so borrowing it here keeps one source of truth: the vendor ships
    two exports (supKingToJson, kingCleanUp) under their stdcall-decorated
    spelling only, and the table knows which names to try in which order.
    '''
    from ..adapters import kd_native

    spec = kd_native.BINDINGS[name]
    fn = None
    attempt = []
    for candidate in spec['names']:
        attempt.append(candidate)
        try:
            fn = getattr(dll, candidate)
            break
        except AttributeError:
            continue
    if fn is None:
        raise AttributeError(
            '%s not found under any spelling (%s)' % (name, ', '.join(attempt)))
    fn.argtypes = spec['args']
    fn.restype = spec['ret']
    return fn


def inspect(kingdraw_home: Optional[str] = None, probe_king: bool = True) -> DoctorReport:
    '''Probe the KingDraw channel. Must run in a 32-bit interpreter.'''
    report = DoctorReport(channel='kingdraw', available=False, evidence=EVIDENCE_MEASURED)
    t0 = time.time()

    if sys.maxsize > 2 ** 32:
        report.failures.append(Failure(
            code=ErrorCode.KD_BITNESS,
            message='KingDraw core library is x86; this interpreter is x64',
            hint=bitness_hint(),
            channel='kingdraw', stage='bitness',
        ))
        return report

    home = find_home(kingdraw_home)
    if not home:
        report.failures.append(Failure(
            code=ErrorCode.KD_NOT_FOUND,
            message='GRDKitDll.dll not found in any known location',
            hint='Pass --kingdraw-home, or set KINGDRAW_HOME',
            channel='kingdraw', stage='locate',
        ))
        return report
    report.home = home
    report.details['home'] = home

    exe = os.path.join(home, 'KingDraw.WpfForm.exe')
    report.details['app_exe'] = exe if os.path.isfile(exe) else None
    report.details['app_present'] = os.path.isfile(exe)

    dll = None
    try:
        try:
            os.add_dll_directory(home)
        except Exception:
            pass
        old = os.getcwd()
        try:
            os.chdir(home)
            with _MuteStdout():
                dll = ctypes.WinDLL(os.path.join(home, 'GRDKitDll.dll'))
        finally:
            os.chdir(old)
    except Exception as exc:
        report.failures.append(Failure(
            code=ErrorCode.KD_NOT_FOUND,
            message='GRDKitDll.dll exists but could not be loaded',
            hint='Check that the 32-bit runtime is used and vendor DLLs are present',
            detail=type(exc).__name__ + ': ' + str(exc),
            channel='kingdraw', stage='load',
        ))
        return report

    found = []
    bound = {}
    bind_errors = {}
    for name in EXPORTS:
        try:
            bound[name] = _bind(dll, name)
            found.append(name)
        except Exception as exc:
            # Never swallow this: a silent empty binding makes the doctor
            # report '0/12 exports' while the DLL is perfectly fine.
            bind_errors[name] = type(exc).__name__ + ': ' + str(exc)
    if bind_errors:
        report.details['bind_errors'] = bind_errors
    report.details['exports_found'] = found
    report.details['exports_expected'] = len(EXPORTS)
    report.details['exports_missing'] = [n for n in EXPORTS if n not in found]

    probes: dict = {}
    old = os.getcwd()
    try:
        os.chdir(home)
        with _MuteStdout():
            if 'smilesToMol' in bound:
                mol = bound['smilesToMol'](b'c1ccccc1O')
                probes['smilesToMol'] = {
                    'ok': bool(mol),
                    'bytes': len(mol) if mol else 0,
                    'head': (mol or b'')[:40].decode('utf-8', 'replace'),
                }
            if 'molToSmiles' in bound and probes.get('smilesToMol', {}).get('ok'):
                mol = bound['smilesToMol'](b'c1ccccc1O')
                smi = bound['molToSmiles'](mol)
                probes['molToSmiles'] = {'ok': bool(smi), 'value': (smi or b'').decode('utf-8', 'replace')}
            if 'getFormula' in bound:
                f = bound['getFormula'](b'CC(=O)Oc1ccccc1C(=O)O')
                probes['getFormula'] = {'ok': bool(f), 'value': (f or b'').decode('utf-8', 'replace')}
            if 'smiles2dTo3d' in bound:
                d3 = bound['smiles2dTo3d'](b'CCO')
                probes['smiles2dTo3d'] = {'ok': bool(d3), 'bytes': len(d3) if d3 else 0}
            if probe_king and 'supKingToJson' in bound:
                sample = None
                for f in os.listdir(home):
                    if f.lower().endswith('.king'):
                        sample = os.path.join(home, f)
                        break
                if sample:
                    raw = open(sample, 'rb').read()
                    js = bound['supKingToJson'](raw)
                    text = (js or b'').decode('utf-8', 'replace')
                    probes['supKingToJson'] = {
                        'ok': bool(text),
                        'sample': os.path.basename(sample),
                        'bytes': len(text),
                        'head': text[:60],
                    }
    finally:
        os.chdir(old)

    report.details['probes'] = probes
    report.available = True
    for action, route, ok, evidence in [
        ('read', 'native+file', bool(probes.get('supKingToJson', {}).get('ok')), EVIDENCE_MEASURED),
        ('draw', 'file+cli', bool(report.details['app_present']), 'B'),
        ('convert', 'native', bool(probes.get('smilesToMol', {}).get('ok')), EVIDENCE_MEASURED),
        ('check', 'native', bool(probes.get('getFormula', {}).get('ok')), EVIDENCE_MEASURED),
        ('three_d', 'native', bool(probes.get('smiles2dTo3d', {}).get('ok')), EVIDENCE_MEASURED),
        ('layout', 'file-coords', False, 'C'),
    ]:
        note = '' if ok else 'not verified on this install'
        report.capabilities.append(Capability(action, 'kingdraw', route, ok, evidence, note))

    report.version = 'GRDKitDll exports=' + str(len(found)) + '/' + str(len(EXPORTS))
    report.details['elapsed_ms'] = int((time.time() - t0) * 1000)
    return report