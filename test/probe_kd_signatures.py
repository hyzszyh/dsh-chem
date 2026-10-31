'''Probe the real ctypes signatures of GRDKitDll.dll exports.

Must run on a 32-bit interpreter (the DLL is x86). Each mode is a separate
process so a bad call shape cannot take the whole investigation down: results go
to stderr, one JSON line per attempt, and a crash only loses the current mode.

Usage (from the project root, 32-bit python):
    python test/probe_kd_signatures.py names
    python test/probe_kd_signatures.py simple
    python test/probe_kd_signatures.py match
    python test/probe_kd_signatures.py ba
    python test/probe_kd_signatures.py kingclean
'''
from __future__ import annotations

import ctypes
import json
import os
import sys

HOME = os.environ.get('KINGDRAW_HOME', r'D:\tool\KingDraw')
DLL_PATH = os.path.join(HOME, 'GRDKitDll.dll')

# Names as reported by the PE export table plus the doctor's presumed spellings.
CANDIDATES = [
    'supKingToJson', '_supKingToJson@4',
    'kingCleanUp', '_kingCleanUp@24',
    'cleanUp', 'molToSmiles', 'smilesToMol', 'smilesToMolBA',
    '_smilesToMolBA2@24', 'substructMatch', 'structMatch',
    'getMolFormula', 'getFormula', 'mol2dTo3d', 'smiles2dTo3d',
]


def emit(**kw) -> None:
    sys.stderr.write(json.dumps(kw, ensure_ascii=False) + '\n')
    sys.stderr.flush()


class Mute:
    def __enter__(self):
        self.saved = None
        try:
            self.saved = os.dup(1)
            self.null = os.open(os.devnull, os.O_WRONLY)
            os.dup2(self.null, 1)
        except Exception:
            self.saved = None
        return self

    def __exit__(self, *exc):
        if self.saved is not None:
            try:
                os.dup2(self.saved, 1)
                os.close(self.saved)
                os.close(self.null)
            except Exception:
                pass
        return False


def load(kind='windll'):
    try:
        os.add_dll_directory(HOME)
    except Exception:
        pass
    old = os.getcwd()
    os.chdir(HOME)
    try:
        with Mute():
            cls = ctypes.WinDLL if kind == 'windll' else ctypes.CDLL
            return cls(DLL_PATH)
    finally:
        os.chdir(old)


def as_text(v):
    if v is None:
        return None
    if isinstance(v, bytes):
        return v.decode('utf-8', 'replace')
    return repr(v)


def mode_names():
    for kind in ('windll', 'cdll'):
        try:
            dll = load(kind)
        except Exception as exc:
            emit(load=kind, error=type(exc).__name__ + ': ' + str(exc))
            continue
        for name in CANDIDATES:
            try:
                getattr(dll, name)
                emit(load=kind, name=name, bound=True)
            except Exception as exc:
                emit(load=kind, name=name, bound=False, error=type(exc).__name__)


def bind1(dll, name, restype=None):
    fn = getattr(dll, name)
    fn.argtypes = [ctypes.c_char_p]
    fn.restype = ctypes.c_char_p
    return fn


def mode_simple():
    dll = load('windll')
    probe = os.path.join(HOME, 'Cyclohexane.king')
    for fn_name in ('smilesToMol', 'smiles2dTo3d', 'molToSmiles', 'getFormula',
                    'getMolFormula', 'supKingToJson', '_supKingToJson@4'):
        try:
            fn = bind1(dll, fn_name)
        except Exception as exc:
            emit(fn=fn_name, bound=False, error=type(exc).__name__)
            continue
        try:
            with Mute():
                if fn_name in ('supKingToJson', '_supKingToJson@4'):
                    arg = open(probe, 'rb').read()
                elif fn_name == 'molToSmiles':
                    mol = bind1(dll, 'smilesToMol')(b'c1ccccc1O')
                    arg = mol
                elif fn_name == 'mol2dTo3d':
                    arg = bind1(dll, 'smilesToMol')(b'CCO')
                else:
                    arg = b'CC(=O)Oc1ccccc1C(=O)O' if fn_name in (
                        'getFormula', 'getMolFormula') else b'c1ccccc1O'
                out = fn(arg)
            emit(fn=fn_name, ok=bool(out), bytes=len(out) if out else 0,
                 head=(as_text(out) or '')[:60])
        except Exception as exc:
            emit(fn=fn_name, error=type(exc).__name__ + ': ' + str(exc))


def mode_match():
    dll = load('windll')
    pairs = [('c1ccccc1O', 'c1ccccc1O'), ('c1ccccc1O', 'c1ccccc1'),
             ('c1ccccc1O', 'Oc1ccccc1'), ('CCO', 'c1ccccc1O')]
    for fn_name in ('structMatch', 'substructMatch'):
        try:
            fn = getattr(dll, fn_name)
            fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
            fn.restype = ctypes.c_int
        except Exception as exc:
            emit(fn=fn_name, bound=False, error=type(exc).__name__)
            continue
        for a, b in pairs:
            try:
                with Mute():
                    rc = fn(a.encode(), b.encode())
                emit(fn=fn_name, a=a, b=b, rc=rc)
            except Exception as exc:
                emit(fn=fn_name, a=a, b=b, error=type(exc).__name__ + ': ' + str(exc))


def mode_ba():
    '''smilesToMolBA: unknown arity. Try one shape per invocation (argv[2]).'''
    shape = sys.argv[2] if len(sys.argv) > 2 else '1'
    dll = load('windll')
    fn = getattr(dll, 'smilesToMolBA')
    smiles = b'c1ccccc1O'
    if shape == '1':
        fn.argtypes = [ctypes.c_char_p]
        fn.restype = ctypes.c_char_p
        with Mute():
            out = fn(smiles)
        emit(shape=shape, ok=bool(out), bytes=len(out) if out else 0,
             head=(as_text(out) or '')[:60])
    elif shape == '2':
        fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
        fn.restype = ctypes.c_char_p
        with Mute():
            out = fn(smiles, b'')
        emit(shape=shape, ok=bool(out), bytes=len(out) if out else 0,
             head=(as_text(out) or '')[:60])
    elif shape == '3':
        fn.argtypes = [ctypes.c_char_p, ctypes.c_double, ctypes.c_double]
        fn.restype = ctypes.c_char_p
        with Mute():
            out = fn(smiles, 200.0, 200.0)
        emit(shape=shape, ok=bool(out), bytes=len(out) if out else 0,
             head=(as_text(out) or '')[:60])


def mode_kingclean():
    '''_kingCleanUp@24 / cleanUp: 6 dwords, all-NULL-ish probe (argv[2] = ordinal).'''
    which = sys.argv[2] if len(sys.argv) > 2 else '_kingCleanUp@24'
    dll = load('windll')
    fn = getattr(dll, which)
    fn.argtypes = [ctypes.c_void_p] * 6
    fn.restype = ctypes.c_void_p
    with Mute():
        rc = fn(None, None, None, None, None, None)
    emit(fn=which, rc=rc)


def mode_shapes():
    '''Sweep arity/type shapes for an export with unknown signature.

    argv[2]=symbol, argv[3]=arity, argv[4]=first-arg payload
    (smiles|mol|king|empty). Every pointer slot gets its own 64 KiB writable
    buffer, so a callee that treats a slot as an output buffer can write into it
    instead of faulting. The functions own buffers are dumped afterwards; the
    return value is reported raw (never dereferenced).
    '''
    symbol = sys.argv[2]
    arity = int(sys.argv[3])
    kind = sys.argv[4] if len(sys.argv) > 4 else 'smiles'
    payload_map = {
        'smiles': b'c1ccccc1O',
        'mol': None,
        'king': open(os.path.join(HOME, 'Cyclohexane.king'), 'rb').read(),
        'empty': b'',
    }
    dll = load('windll')
    payload = payload_map[kind]
    if payload is None:
        payload = bind1(dll, 'smilesToMol')(b'c1ccccc1O') or b''
    fn = getattr(dll, symbol)
    fn.argtypes = [ctypes.c_void_p] * arity
    fn.restype = ctypes.c_void_p
    bufs = [ctypes.create_string_buffer(65536) for _ in range(max(0, arity - 1))]
    args = [ctypes.cast(ctypes.c_char_p(payload), ctypes.c_void_p)]
    args.extend(ctypes.cast(b, ctypes.c_void_p) for b in bufs)
    with Mute():
        rc = fn(*args)
    dumped = []
    for i, b in enumerate(bufs):
        raw = b.raw.rstrip(b'\x00')
        if raw:
            dumped.append({'slot': i + 1, 'bytes': len(raw),
                           'head': raw[:50].decode('utf-8', 'replace')})
    emit(symbol=symbol, arity=arity, kind=kind, rc=rc, filled=dumped)


def mode_molinputs():
    '''Feeds molfile output back into the mol-taking exports.'''
    dll = load('windll')
    with Mute():
        mol2d = bind1(dll, 'smilesToMol')(b'CC(=O)Oc1ccccc1C(=O)O')
    for fn_name in ('getMolFormula', 'mol2dTo3d', 'molToSmiles'):
        try:
            fn = bind1(dll, fn_name)
            with Mute():
                out = fn(mol2d)
            emit(fn=fn_name, input='molblock(aspirin)', ok=bool(out),
                 bytes=len(out) if out else 0, head=(as_text(out) or '')[:60])
        except Exception as exc:
            emit(fn=fn_name, error=type(exc).__name__ + ': ' + str(exc))


def mode_clean():
    '''cleanUp / kingCleanUp: ret 24 -> (char*, double, double, char*) probe.

    argv[2]=symbol, argv[3]=payload (smiles|mol|king|out), argv[4]=4th arg
    ('buf' = 64 KiB output buffer, 'null' = NULL).
    '''
    symbol = sys.argv[2]
    kind = sys.argv[3] if len(sys.argv) > 3 else 'smiles'
    fourth = sys.argv[4] if len(sys.argv) > 4 else 'buf'
    dll = load('windll')
    if kind == 'smiles':
        payload = b'c1ccccc1O'
    elif kind == 'mol':
        payload = bind1(dll, 'smilesToMol')(b'c1ccccc1O') or b''
    elif kind == 'king':
        payload = open(os.path.join(HOME, 'Cyclohexane.king'), 'rb').read()
    elif kind == 'json':
        raw = open(os.path.join(HOME, 'Cyclohexane.king'), 'rb').read()
        with Mute():
            payload = bind1(dll, 'supKingToJson')(raw) or b''
    else:
        payload = b''
    fn = getattr(dll, symbol)
    fn.argtypes = [ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_void_p]
    fn.restype = ctypes.c_void_p
    buf = ctypes.create_string_buffer(65536)
    arg4 = ctypes.cast(buf, ctypes.c_void_p) if fourth == 'buf' else None
    with Mute():
        rc = fn(payload, 200.0, 200.0, arg4)
    out = {}
    if rc:
        try:
            out['rc_text'] = ctypes.string_at(rc, 200).split(b'\x00')[0].decode('utf-8', 'replace')
        except Exception as exc:
            out['rc_deref_error'] = type(exc).__name__
    raw = buf.raw.rstrip(b'\x00')
    if raw:
        out['buf'] = raw[:200].decode('utf-8', 'replace')
    emit(symbol=symbol, kind=kind, fourth=fourth, rc=rc, **out)


def mode_ba3():
    '''smilesToMolBA: ret 20 -> (char*, double, double).'''
    dll = load('windll')
    fn = getattr(dll, 'smilesToMolBA')
    fn.argtypes = [ctypes.c_char_p, ctypes.c_double, ctypes.c_double]
    fn.restype = ctypes.c_void_p
    for smiles in (b'c1ccccc1O', b'CCO'):
        with Mute():
            rc = fn(smiles, 200.0, 200.0)
        info = {'smiles': smiles.decode(), 'rc': rc}
        if rc:
            try:
                info['text'] = ctypes.string_at(rc, 300).split(b'\x00')[0].decode('utf-8', 'replace')
            except Exception as exc:
                info['deref_error'] = type(exc).__name__
        emit(**info)


def mode_kc_compare():
    '''Compare supKingToJson with kingCleanUp on the same .king sample.'''
    import json as _json
    dll = load('windll')
    raw = open(os.path.join(HOME, 'Cyclohexane.king'), 'rb').read()
    fn = bind1(dll, 'supKingToJson')
    with Mute():
        base = fn(raw) or b''
    fn2 = getattr(dll, 'kingCleanUp')
    fn2.argtypes = [ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_int]
    fn2.restype = ctypes.c_char_p
    with Mute():
        cleaned = fn2(raw, 200.0, 200.0, 0) or b''
    out = {'king_bytes': len(raw), 'supKingToJson_bytes': len(base),
           'kingCleanUp_bytes': len(cleaned)}
    for label, blob in (('sup', base), ('cln', cleaned)):
        try:
            d = _json.loads(blob.decode('utf-8', 'replace'))
            data = d.get('data') or {}
            out[label] = {'success': d.get('success'), 'nodes': len(data.get('nodes') or []),
                          'bonds': len(data.get('bonds') or [])}
        except Exception as exc:
            out[label] = {'parse_error': type(exc).__name__}
    emit(**out)


MODES = {
    'names': mode_names,
    'kc_compare': mode_kc_compare,
    'clean': mode_clean,
    'ba3': mode_ba3,
    'simple': mode_simple,
    'match': mode_match,
    'ba': mode_ba,
    'kingclean': mode_kingclean,
    'shapes': mode_shapes,
    'molinputs': mode_molinputs,
}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in MODES:
        sys.stderr.write('modes: ' + ', '.join(MODES) + '\n')
        raise SystemExit(2)
    if sys.maxsize > 2 ** 32:
        emit(fatal='need 32-bit interpreter', maxsize=sys.maxsize)
        raise SystemExit(3)
    MODES[sys.argv[1]]()
