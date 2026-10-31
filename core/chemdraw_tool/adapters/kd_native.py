'''KingDraw native adapter: the 12 exports of GRDKitDll.dll behind one Result envelope.

Everything here was measured on this machine, not copied from a header file:

* The export table was parsed out of the PE (test/probe_kd_exports.py). It holds
  17 names: 4 boost singleton_module symbols that belong to the vendor's runtime,
  and the 12 the doctor already knows; 'supKingToJson' and 'kingCleanUp' exist
  only in stdcall-decorated spelling (_supKingToJson@4, _kingCleanUp@24), so the
  binder tries the plain name and then the decorated one.
* Argument counts were read from each function's epilogue (test/probe_kd_ret.py):
  x86 stdcall returns with 'ret N'. The three decorated exports (ret 4 / ret 24 /
  ret 24) are the self-check for that technique. Results:
      ret  4 -> one char*          (supKingToJson, molToSmiles, smilesToMol,
                                    getMolFormula, getFormula, mol2dTo3d,
                                    smiles2dTo3d)
      ret  8 -> two char*          (structMatch, substructMatch -> int)
      ret 20 -> char*, double, double              (smilesToMolBA)
      ret 24 -> char*, double, double, int         (cleanUp, kingCleanUp)
  The 20- and 24-byte shapes are verified by calling them, not by guesswork:
  smilesToMolBA('c1ccccc1O', 200, 200) answers with a V3000 molblock laid out in a
  200x200 box (so slots 2 and 3 are the doubles), and cleanUp answers with a
  re-laid molblock, kingCleanUp with KingDraw's own JSON. The last slot of the
  24-byte pair is a pointer, not an int: passing 0 raises an access violation
  inside the vendor code while a writable buffer is accepted, so this adapter
  always supplies a scratch buffer there instead of NULL.

The DLL is x86, so this module is only functional under a 32-bit interpreter.
A 64-bit interpreter must not crash inside ctypes: every entry point returns a
Failure with code E04 instead.
'''

from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time
from typing import Any, Callable, Optional

from ..models import (
    ERROR_TEXT, ErrorCode, EVIDENCE_INFERRED, EVIDENCE_MEASURED, Failure, Result,
    bitness_hint,
)

CHANNEL = 'kingdraw'
DLL_NAME = 'GRDKitDll.dll'
HOME_ENV = 'KINGDRAW_HOME'
DEFAULT_HOMES = [
    r'D:\tool\KingDraw',
    r'C:\Program Files\KingDraw',
    r'C:\Program Files (x86)\KingDraw',
]

# Bindings discovered by the probes. 'names' lists the spellings to try, in
# order; the decorated stdcall spelling is the one that actually exists for
# supKingToJson and kingCleanUp.
_SPECS: dict[str, dict[str, Any]] = {
    'supKingToJson': {
        'names': ['supKingToJson', '_supKingToJson@4'],
        'args': [ctypes.c_char_p], 'ret': ctypes.c_char_p, 'ret_bytes': 4,
        'input': '.king bytes', 'output': 'king JSON',
    },
    'kingCleanUp': {
        'names': ['kingCleanUp', '_kingCleanUp@24'],
        'args': [ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_void_p],
        'ret': ctypes.c_char_p, 'ret_bytes': 24,
        'input': 'structure bytes', 'output': 'king JSON',
    },
    'cleanUp': {
        'names': ['cleanUp'],
        'args': [ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_void_p],
        'ret': ctypes.c_char_p, 'ret_bytes': 24,
        'input': 'molblock', 'output': 'molblock (re-laid out)',
    },
    'molToSmiles': {
        'names': ['molToSmiles'],
        'args': [ctypes.c_char_p], 'ret': ctypes.c_char_p, 'ret_bytes': 4,
        'input': 'molblock', 'output': 'SMILES',
    },
    'smilesToMol': {
        'names': ['smilesToMol'],
        'args': [ctypes.c_char_p], 'ret': ctypes.c_char_p, 'ret_bytes': 4,
        'input': 'SMILES', 'output': 'molblock (V2000)',
    },
    'smilesToMolBA': {
        'names': ['smilesToMolBA'],
        'args': [ctypes.c_char_p, ctypes.c_double, ctypes.c_double],
        'ret': ctypes.c_char_p, 'ret_bytes': 20,
        'input': 'SMILES + width + height', 'output': 'molblock (V3000)',
    },
    'substructMatch': {
        'names': ['substructMatch'],
        'args': [ctypes.c_char_p, ctypes.c_char_p], 'ret': ctypes.c_int,
        'ret_bytes': 8, 'input': 'two structures', 'output': 'int 0/1',
    },
    'structMatch': {
        'names': ['structMatch'],
        'args': [ctypes.c_char_p, ctypes.c_char_p], 'ret': ctypes.c_int,
        'ret_bytes': 8, 'input': 'two structures', 'output': 'int 0/1',
    },
    'getMolFormula': {
        'names': ['getMolFormula'],
        'args': [ctypes.c_char_p], 'ret': ctypes.c_char_p, 'ret_bytes': 4,
        'input': 'molblock', 'output': 'formula',
    },
    'getFormula': {
        'names': ['getFormula'],
        'args': [ctypes.c_char_p], 'ret': ctypes.c_char_p, 'ret_bytes': 4,
        'input': 'SMILES', 'output': 'formula',
    },
    'mol2dTo3d': {
        'names': ['mol2dTo3d'],
        'args': [ctypes.c_char_p], 'ret': ctypes.c_char_p, 'ret_bytes': 4,
        'input': 'molblock', 'output': '3D molblock',
    },
    'smiles2dTo3d': {
        'names': ['smiles2dTo3d'],
        'args': [ctypes.c_char_p], 'ret': ctypes.c_char_p, 'ret_bytes': 4,
        'input': 'SMILES', 'output': '3D molblock',
    },
}

BINDINGS = _SPECS  # public alias: the doctor borrows this ABI table
exports = list(_SPECS)
EXPORTS = exports


class MuteNative:
    '''Silence what the vendor library prints while a call runs.

    The DLL prints with C printf on fd 1 ('new rdkit', 'atomkey C_3') and RDKit
    prints parse errors on fd 2 ('[00:34:31] SMILES Parse Error: ...'). Both
    would corrupt a CLI that emits JSON, so both descriptors are redirected.
    '''

    def __init__(self, also_stderr: bool = True):
        self.also_stderr = also_stderr
        self._saved: list = []
        self._null = None

    def __enter__(self):
        self._saved = []
        try:
            self._null = os.open(os.devnull, os.O_WRONLY)
            targets = [1] + ([2] if self.also_stderr else [])
            for fd in targets:
                saved = os.dup(fd)
                os.dup2(self._null, fd)
                self._saved.append((fd, saved))
        except Exception:
            self._saved = []
        return self

    def __exit__(self, *exc):
        for fd, saved in self._saved:
            try:
                os.dup2(saved, fd)
                os.close(saved)
            except Exception:
                pass
        if self._null is not None:
            try:
                os.close(self._null)
            except Exception:
                pass
        self._saved = []
        return False


def is_64bit() -> bool:
    return sys.maxsize > 2 ** 32


def find_home(explicit: Optional[str] = None) -> Optional[str]:
    '''Folder that holds GRDKitDll.dll: explicit, env, registry, then defaults.'''
    # A folder the caller named (argument or HOME_ENV) is honoured or refused --
    # never silently replaced by a default install.
    for named in (explicit, os.environ.get(HOME_ENV)):
        if named:
            if os.path.isfile(os.path.join(named, DLL_NAME)):
                return os.path.abspath(named)
            return None
    candidates = []
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r'kingfile\shell\open\command')
        cmd = winreg.QueryValueEx(key, '')[0]
        first = cmd.split('"')[1] if '"' in cmd else cmd.split()[0]
        candidates.append(os.path.dirname(first))
    except Exception:
        pass
    candidates.extend(DEFAULT_HOMES)
    for c in candidates:
        try:
            if c and os.path.isfile(os.path.join(c, DLL_NAME)):
                return os.path.abspath(c)
        except Exception:
            continue
    return None


def _failure(code: str, stage: str, detail: str = '', message: str = '',
             hint: str = '') -> Failure:
    d_msg, d_hint = ERROR_TEXT.get(code, ('', ''))
    return Failure(
        code=code, message=message or d_msg, hint=hint or d_hint,
        detail=detail, channel=CHANNEL, stage=stage,
    )


def _encode(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode('utf-8')
    return bytes(value)


class KingDrawNative:
    '''Lazy handle on GRDKitDll.dll plus one Result-returning method per export.'''

    def __init__(self, home: Optional[str] = None, auto_load: bool = True):
        self.home = home
        self._dll: Any = None
        self._bound: dict[str, Any] = {}
        self._load_failure: Optional[Failure] = None
        self._lock = threading.RLock()
        self._load_attempted = False
        if auto_load:
            self.load()

    # -- lifecycle ---------------------------------------------------------
    def load(self) -> Result:
        '''Load the library once; repeated calls reuse the first verdict.'''
        with self._lock:
            if self._load_attempted:
                return self._verdict()
            self._load_attempted = True
            started = time.time()
            if is_64bit():
                self._load_failure = _failure(
                    ErrorCode.KD_BITNESS, 'bitness',
                    detail='sys.maxsize=%d, pointer width %d bits'
                           % (sys.maxsize, ctypes.sizeof(ctypes.c_void_p) * 8),
                    hint=bitness_hint(),
                )
                return self._verdict(started)
            home = find_home(self.home)
            if not home:
                self._load_failure = _failure(
                    ErrorCode.KD_NOT_FOUND, 'locate',
                    detail='searched: %s' % ', '.join(DEFAULT_HOMES),
                )
                return self._verdict(started)
            self.home = home
            old_cwd = os.getcwd()
            try:
                try:
                    os.add_dll_directory(home)
                except Exception:
                    pass
                os.chdir(home)
                with MuteNative():
                    self._dll = ctypes.WinDLL(os.path.join(home, DLL_NAME))
            except OSError as exc:
                self._load_failure = _failure(
                    ErrorCode.KD_NOT_FOUND, 'load',
                    detail='%s: %s' % (type(exc).__name__, exc),
                )
                self._dll = None
            except Exception as exc:
                self._load_failure = _failure(
                    ErrorCode.UNKNOWN, 'load',
                    detail='%s: %s' % (type(exc).__name__, exc),
                )
                self._dll = None
            finally:
                try:
                    os.chdir(old_cwd)
                except Exception:
                    pass

            if self._dll is not None:
                missing = []
                for name, spec in _SPECS.items():
                    fn = None
                    for spelling in spec['names']:
                        try:
                            fn = getattr(self._dll, spelling)
                            break
                        except Exception:
                            fn = None
                    if fn is None:
                        missing.append(name)
                        continue
                    fn.argtypes = spec['args']
                    fn.restype = spec['ret']
                    self._bound[name] = fn
                if missing:
                    self._load_failure = _failure(
                        ErrorCode.NOT_INSTALLED, 'bind',
                        detail='missing exports: ' + ', '.join(missing),
                    )
                    self._dll = None
                    self._bound = {}
            return self._verdict(started)

    def _verdict(self, started: Optional[float] = None) -> Result:
        ok = self._load_failure is None and bool(self._bound)
        return Result(
            ok=ok,
            data={
                'home': self.home,
                'exports_bound': sorted(self._bound),
                'exports_expected': EXPORTS,
                'pointer_bits': ctypes.sizeof(ctypes.c_void_p) * 8,
            },
            failure=self._load_failure,
            channel=CHANNEL,
            evidence=EVIDENCE_MEASURED,
            elapsed_ms=int((time.time() - started) * 1000) if started else 0,
        )

    @property
    def ready(self) -> bool:
        return self._load_failure is None and bool(self._bound)

    def capability_spec(self) -> list:
        '''Static description of the 12 exports, for docs and the CLI matrix.'''
        return [
            {
                'export': name,
                'arg_bytes': spec['ret_bytes'],
                'input': spec['input'],
                'output': spec['output'],
                'bound': name in self._bound,
            }
            for name, spec in _SPECS.items()
        ]

    # -- call plumbing -----------------------------------------------------
    def _call(self, export: str, stage: str, args: list,
              decode: Callable[[Any], Any] = None) -> Result:
        started = time.time()
        if not self._load_attempted:
            self.load()
        if not self.ready:
            res = self._verdict(started)
            res.data = None
            return res
        fn = self._bound.get(export)
        if fn is None:
            return Result(
                ok=False, failure=_failure(ErrorCode.NOT_INSTALLED, stage,
                                           detail='export not bound: ' + export),
                channel=CHANNEL, elapsed_ms=0,
            )
        try:
            with self._lock:
                with MuteNative():
                    raw = fn(*args)
        except OSError as exc:
            return Result(
                ok=False,
                failure=_failure(ErrorCode.PARSE_FAILED, stage,
                                 detail='%s: %s' % (type(exc).__name__, exc),
                                 message='KingDraw rejected the input for %s' % export),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
            )
        except Exception as exc:
            return Result(
                ok=False,
                failure=_failure(ErrorCode.UNKNOWN, stage,
                                 detail='%s: %s' % (type(exc).__name__, exc)),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
            )
        elapsed = int((time.time() - started) * 1000)
        if decode is not None:
            try:
                data = decode(raw)
            except Exception as exc:
                return Result(
                    ok=False,
                    failure=_failure(ErrorCode.PARSE_FAILED, stage,
                                     detail='%s: %s' % (type(exc).__name__, exc)),
                    channel=CHANNEL, elapsed_ms=elapsed,
                )
            empty = (isinstance(data, dict)
                     and 'text' in data and not data['text'].strip())
            if empty:
                res = Result(ok=False, data=data, channel=CHANNEL,
                             evidence=EVIDENCE_MEASURED, elapsed_ms=elapsed)
                res.failure = _failure(
                    ErrorCode.PARSE_FAILED, stage,
                    message='%s returned nothing' % export,
                    hint='The input was probably not a structure KingDraw understands',
                )
                res.warnings.append('%s returned empty output' % export)
                return res
            return Result(ok=True, data=data, channel=CHANNEL,
                          evidence=EVIDENCE_MEASURED, elapsed_ms=elapsed)
        text = ''
        if raw is not None:
            text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw)
        res = Result(ok=bool(text.strip()), data=text, channel=CHANNEL,
                     evidence=EVIDENCE_MEASURED, elapsed_ms=elapsed)
        if not text.strip():
            res.failure = _failure(
                ErrorCode.PARSE_FAILED, stage,
                message='%s returned nothing' % export,
                hint='The input was probably not a structure KingDraw understands',
            )
            res.warnings.append('%s returned empty output' % export)
        return res

    @staticmethod
    def _text_decode(raw) -> dict:
        text = raw.decode('utf-8', 'replace') if isinstance(raw, bytes) else str(raw)
        return {'text': text, 'chars': len(text)}

    # -- the 12 exports ----------------------------------------------------
    def sup_king_to_json(self, king_bytes: Any) -> Result:
        '''(.king bytes) -> KingDraw JSON document.'''
        return self._call('supKingToJson', 'sup_king_to_json',
                          [_encode(king_bytes)], self._text_decode)

    def king_clean_up(self, structure: Any, width: float = 200.0,
                      height: float = 200.0, scratch: Any = None) -> Result:
        '''(structure, width, height, scratch) -> KingDraw JSON document.

        The fourth slot must be a writable pointer; NULL killed the vendor code
        when measured, so a scratch buffer is supplied by default. Which input
        shape actually yields populated nodes is still open: every input tried
        so far (raw .king bytes, V2000 molblock) came back as a valid JSON
        document with empty node lists, so the result carries a warning instead
        of pretending success. sup_king_to_json is the verified .king reader.
        '''
        buf = scratch if scratch is not None else ctypes.create_string_buffer(65536)
        res = self._call('kingCleanUp', 'king_clean_up',
                         [_encode(structure), float(width), float(height),
                          ctypes.cast(buf, ctypes.c_void_p)],
                         self._text_decode)
        if res.ok and '"nodes":[]' in (res.data or {}).get('text', ''):
            res.warnings.append(
                'kingCleanUp returned a document with no nodes for this input; '
                'its expected payload shape is not established yet')
            res.evidence = EVIDENCE_INFERRED
        return res

    def clean_up(self, molblock: Any, width: float = 200.0,
                 height: float = 200.0, scratch: Any = None) -> Result:
        '''(molblock, width, height, scratch) -> re-laid-out molblock.

        Same fourth-slot caveat as king_clean_up: a pointer is required.
        '''
        buf = scratch if scratch is not None else ctypes.create_string_buffer(65536)
        return self._call('cleanUp', 'clean_up',
                          [_encode(molblock), float(width), float(height),
                           ctypes.cast(buf, ctypes.c_void_p)],
                          self._text_decode)

    def mol_to_smiles(self, molblock: Any) -> Result:
        return self._call('molToSmiles', 'mol_to_smiles', [_encode(molblock)],
                          self._text_decode)

    def smiles_to_mol(self, smiles: Any) -> Result:
        return self._call('smilesToMol', 'smiles_to_mol', [_encode(smiles)],
                          self._text_decode)

    def smiles_to_mol_ba(self, smiles: Any, width: float = 200.0,
                         height: float = 200.0) -> Result:
        '''SMILES -> V3000 molblock with coordinates inside width x height.'''
        return self._call('smilesToMolBA', 'smiles_to_mol_ba',
                          [_encode(smiles), float(width), float(height)],
                          self._text_decode)

    def substruct_match(self, left: Any, right: Any) -> Result:
        return self._call('substructMatch', 'substruct_match',
                          [_encode(left), _encode(right)], bool)

    def struct_match(self, left: Any, right: Any) -> Result:
        return self._call('structMatch', 'struct_match',
                          [_encode(left), _encode(right)], bool)

    def get_mol_formula(self, molblock: Any) -> Result:
        return self._call('getMolFormula', 'get_mol_formula', [_encode(molblock)],
                          self._text_decode)

    def get_formula(self, smiles: Any) -> Result:
        return self._call('getFormula', 'get_formula', [_encode(smiles)],
                          self._text_decode)

    def mol2d_to_3d(self, molblock: Any) -> Result:
        return self._call('mol2dTo3d', 'mol2d_to_3d', [_encode(molblock)],
                          self._text_decode)

    def smiles2d_to_3d(self, smiles: Any) -> Result:
        return self._call('smiles2dTo3d', 'smiles2d_to_3d', [_encode(smiles)],
                          self._text_decode)


_shared: Optional[KingDrawNative] = None
_shared_lock = threading.Lock()


def engine(home: Optional[str] = None) -> KingDrawNative:
    '''Process-wide engine, so the DLL is loaded once per process.'''
    global _shared
    with _shared_lock:
        if _shared is None or (home and home != _shared.home):
            _shared = KingDrawNative(home)
        return _shared


def load(home: Optional[str] = None) -> Result:
    return engine(home).load()


# Thin module-level wrappers: same Result envelope, shared engine.
def sup_king_to_json(king_bytes, home: Optional[str] = None) -> Result:
    return engine(home).sup_king_to_json(king_bytes)


def king_clean_up(structure, width=200.0, height=200.0, scratch=None, home=None) -> Result:
    return engine(home).king_clean_up(structure, width, height, scratch)


def clean_up(molblock, width=200.0, height=200.0, scratch=None, home=None) -> Result:
    return engine(home).clean_up(molblock, width, height, scratch)


def mol_to_smiles(molblock, home: Optional[str] = None) -> Result:
    return engine(home).mol_to_smiles(molblock)


def smiles_to_mol(smiles, home: Optional[str] = None) -> Result:
    return engine(home).smiles_to_mol(smiles)


def smiles_to_mol_ba(smiles, width=200.0, height=200.0, home=None) -> Result:
    return engine(home).smiles_to_mol_ba(smiles, width, height)


def substruct_match(left, right, home: Optional[str] = None) -> Result:
    return engine(home).substruct_match(left, right)


def struct_match(left, right, home: Optional[str] = None) -> Result:
    return engine(home).struct_match(left, right)


def get_mol_formula(molblock, home: Optional[str] = None) -> Result:
    return engine(home).get_mol_formula(molblock)


def get_formula(smiles, home: Optional[str] = None) -> Result:
    return engine(home).get_formula(smiles)


def mol2d_to_3d(molblock, home: Optional[str] = None) -> Result:
    return engine(home).mol2d_to_3d(molblock)


def smiles2d_to_3d(smiles, home: Optional[str] = None) -> Result:
    return engine(home).smiles2d_to_3d(smiles)


__all__ = [
    'CHANNEL', 'EXPORTS', 'KingDrawNative', 'MuteNative', 'engine', 'find_home',
    'is_64bit', 'load', 'capability_spec',
    'sup_king_to_json', 'king_clean_up', 'clean_up', 'mol_to_smiles',
    'smiles_to_mol', 'smiles_to_mol_ba', 'substruct_match', 'struct_match',
    'get_mol_formula', 'get_formula', 'mol2d_to_3d', 'smiles2d_to_3d',
]


def capability_spec() -> list:
    '''Signature table without loading the DLL (safe on a 64-bit interpreter).'''
    return [
        {'export': name, 'arg_bytes': spec['ret_bytes'], 'input': spec['input'],
         'output': spec['output']}
        for name, spec in _SPECS.items()
    ]
