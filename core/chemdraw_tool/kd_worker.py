'''32-bit worker: runs KingDraw native calls on behalf of a 64-bit host.

GRDKitDll.dll is x86, so nothing in this process can be done from the 64-bit
interpreter that owns ChemDraw's COM connection. The host therefore spawns this
module with runtime/py32/python.exe and talks JSON over a pipe:

    stdin  <- {"op": "smiles_to_mol", "args": {"smiles": "c1ccccc1O"}}
    stdout -> {"ok": true, "data": {...}, ...}

One request per process is enough for every current call (all of them finish in
tens of milliseconds), and it keeps the DLL from leaking state between calls.
'''

from __future__ import annotations

import json
import os
import sys


def _unwrap_king_json(res):
    '''The .king reader answers with JSON inside JSON; hand back the object.

    supKingToJson returns {success, code, data:{nodes, bonds, ...}} as a text
    payload. Leaving it stringified forces every caller to double-parse, so it
    is unpacked here, once, where the wire format is already being shaped.
    '''
    if not getattr(res, 'ok', False):
        return res
    data = getattr(res, 'data', None)
    if isinstance(data, dict) and isinstance(data.get('text'), str):
        try:
            res.data = json.loads(data['text'])
        except Exception:
            pass
    return res


def _ops():
    from .adapters import kd_native as kd
    from .adapters import kd_open as ko
    return {
        # The open channel does not touch GRDKitDll.dll (it drives the desktop
        # app through subprocess + user32), but it must still be reachable from
        # the host through this worker so the MCP layer has one path per channel.
        'open_file': lambda a: ko.open_file(
            a['path'], a.get('timeout', 20.0), a.get('reuse', True), a.get('home')),
        'close_app': lambda a: ko.close_app(a['pid'], a.get('timeout', 10.0)),
        'capture_window': lambda a: ko.capture_window(
            a['pid'], a.get('out'), a.get('foreground', True), a.get('settle', 0.4)),
        # UIA is the strong "the document really opened" signal; it needs a
        # 64-bit interpreter with pywinauto, so kd_open bridges out from here.
        'uia_documents': lambda a: ko.uia_documents(
            a['pid'], a.get('timeout', 15.0), a.get('python64')),
        'list_app_pids': lambda a: __import__(
            'chemdraw_tool.models', fromlist=['Result']).Result(
                ok=True, channel='kingdraw', data=ko.list_pids()),
        'load': lambda a: kd.load(a.get('home')),
        'smiles_to_mol': lambda a: kd.smiles_to_mol(a['smiles'], a.get('home')),
        'mol_to_smiles': lambda a: kd.mol_to_smiles(a['mol'], a.get('home')),
        'get_formula': lambda a: kd.get_formula(a['smiles'], a.get('home')),
        'get_mol_formula': lambda a: kd.get_mol_formula(a['mol'], a.get('home')),
        'smiles_to_mol_ba': lambda a: kd.smiles_to_mol_ba(
            a['smiles'], a.get('width', 200.0), a.get('height', 200.0), a.get('home')),
        'clean_up': lambda a: kd.clean_up(
            a['mol'], a.get('width', 200.0), a.get('height', 200.0), None, a.get('home')),
        'struct_match': lambda a: kd.struct_match(a['a'], a['b'], a.get('home')),
        'substruct_match': lambda a: kd.substruct_match(a['a'], a['b'], a.get('home')),
        'smiles2d_to_3d': lambda a: kd.smiles2d_to_3d(a['smiles'], a.get('home')),
        'mol2d_to_3d': lambda a: kd.mol2d_to_3d(a['mol'], a.get('home')),
        # JSON has no bytes type, so callers send a list of ints and it is
        # turned back into bytes here, before the DLL ever sees it.
        'sup_king_to_json': lambda a: _unwrap_king_json(
            kd.sup_king_to_json(bytes(a['king_bytes']), a.get('home'))),
    }


def run(request: dict) -> dict:
    from .models import ErrorCode, Failure, Result

    op = request.get('op')
    table = _ops()
    fn = table.get(op)
    if fn is None:
        return Result(ok=False, channel='kingdraw', failure=Failure(
            code=ErrorCode.UNKNOWN,
            message='unknown worker op: %r' % (op,),
            hint='Known ops: ' + ', '.join(sorted(table)),
        )).to_dict()
    try:
        res = fn(request.get('args') or {})
    except KeyError as exc:
        return Result(ok=False, channel='kingdraw', failure=Failure(
            code=ErrorCode.UNKNOWN,
            message='worker op %s is missing argument %s' % (op, exc),
        )).to_dict()
    except Exception as exc:
        return Result(ok=False, channel='kingdraw', failure=Failure(
            code=ErrorCode.UNKNOWN,
            message='worker op %s crashed' % op,
            detail=type(exc).__name__ + ': ' + str(exc),
        )).to_dict()
    return res.to_dict() if hasattr(res, 'to_dict') else dict(res)


def main() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    raw = sys.stdin.read()
    try:
        request = json.loads(raw) if raw.strip() else {}
    except Exception as exc:
        sys.stdout.write(json.dumps({'ok': False, 'failure': {
            'code': 'E99', 'message': 'worker could not parse its request',
            'detail': str(exc)}}))
        return 2
    payload = run(request)
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    return 0 if payload.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())