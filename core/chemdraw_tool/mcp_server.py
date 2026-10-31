'''MCP server over stdio: the same capabilities, spoken to agents.

The process runs on the 64-bit interpreter because ChemDraw's COM server lives
there. KingDraw's DLL is x86 and cannot be loaded here, so every KingDraw tool
forwards to runtime/py32/python.exe through kd_worker.py and returns the same
Result envelope. That boundary is deliberate: it is also what keeps a crashing
vendor DLL away from the host process.

Protocol: JSON-RPC 2.0, one message per line, as the MCP stdio transport expects.
Nothing but protocol messages may reach stdout.'''

from __future__ import annotations

import json
import os
import subprocess
import sys

PROTOCOL_VERSION = '2024-11-05'
SERVER_NAME = 'chem-draw-tool'

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
PY32 = os.path.join(ROOT, 'runtime', 'py32', 'python.exe')
WORKER = os.path.join(ROOT, 'bin', 'kd_worker.py')
WORKER_TIMEOUT = 40


def call_worker(op: str, args: dict, timeout: int = WORKER_TIMEOUT) -> dict:
    '''Run one KingDraw operation in the 32-bit interpreter.'''
    if not os.path.isfile(PY32):
        return {'ok': False, 'channel': 'kingdraw', 'data': None,
                'failure': {'code': 'E04',
                            'message': 'the bundled 32-bit interpreter is missing',
                            'hint': 'Restore runtime/py32/ (see scripts/fetch_runtime.py)',
                            'channel': 'kingdraw', 'stage': 'bitness'}}
    payload = json.dumps({'op': op, 'args': args}, ensure_ascii=False)
    try:
        proc = subprocess.run(
            [PY32, WORKER], input=payload, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'channel': 'kingdraw', 'data': None,
                'failure': {'code': 'E09', 'message': 'KingDraw call timed out',
                            'hint': 'Retry; the vendor DLL may be wedged',
                            'channel': 'kingdraw', 'stage': 'worker'}}
    out = (proc.stdout or '').strip()
    if not out:
        return {'ok': False, 'channel': 'kingdraw', 'data': None,
                'failure': {'code': 'E99', 'message': 'the 32-bit worker said nothing',
                            'detail': (proc.stderr or '')[-500:],
                            'channel': 'kingdraw', 'stage': 'worker'}}
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        return {'ok': False, 'channel': 'kingdraw', 'data': None,
                'failure': {'code': 'E99', 'message': 'worker answered with non-JSON',
                            'detail': out[-500:], 'channel': 'kingdraw',
                            'stage': 'worker'}}


def _identity(args: dict) -> dict:
    from . import identity
    from .models import as_envelope
    # Measured: this tool answered a flat object while every other tool
    # answered an envelope, so its result was the one place an agent's
    # payload['data'] habit failed -- see models.as_envelope.
    return as_envelope(identity.identify(args['smiles']), channel='rdkit')


# -- ChemDraw channel ------------------------------------------------------
# Code E04 is the shared "wrong interpreter bitness" code (models.ErrorCode
# .KD_BITNESS spells it for KingDraw); the ChemDraw direction needs the
# message reversed, so it is overridden here.
CODE_BITNESS = 'E04'


class _NullStream:
    '''Swallows anything a tool tries to print while stdout is redirected.'''

    def write(self, _text):
        return 0

    def flush(self):
        pass

    def isatty(self):
        return False


class _StdoutGuard:
    '''Keep vendor noise off the protocol stream.

    The MCP stdio transport is line-delimited JSON on stdout. rdkit prints
    parse complaints on file descriptors behind Python's back, so during a tool
    call fd 1 is pointed at the null device and sys.stdout is swapped for a
    sink; both are restored before the response is written.
    '''

    def __enter__(self):
        self._saved_stdout = sys.stdout
        self._saved_fd = None
        self._null = None
        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            self._saved_fd = os.dup(1)
            self._null = os.open(os.devnull, os.O_WRONLY)
            os.dup2(self._null, 1)
        except Exception:
            self._saved_fd = None
        sys.stdout = _NullStream()
        return self

    def __exit__(self, *exc_info):
        sys.stdout = self._saved_stdout
        try:
            if self._saved_fd is not None:
                os.dup2(self._saved_fd, 1)
                os.close(self._saved_fd)
            if self._null is not None:
                os.close(self._null)
        except Exception:
            pass
        self._saved_fd = None
        self._null = None
        return False


def _bitness_payload() -> dict:
    return {'ok': False, 'channel': 'chemdraw', 'data': None,
            'failure': {'code': CODE_BITNESS, 'channel': 'chemdraw',
                        'stage': 'bitness',
                        'message': 'ChemDraw automation needs the 64-bit '
                                   'interpreter; this one is 32-bit',
                        'hint': 'Start the server with the 64-bit Python '
                                '(Python311\\python.exe)',
                        'detail': 'sys.maxsize=%d' % sys.maxsize}}


def _channel_factory():
    """Build the real ChemDraw channel. Runs on the broker's apartment thread."""
    from .adapters import cd_com
    return cd_com.channel(visible=True)


def _cd_channel():
    """The process-wide ChemDraw channel, reached through the COM broker.

    Every call - connect() included - is handed to one apartment thread with a
    deadline (com_broker). Without that, a modal dialog in ChemDraw parked this
    function forever and the whole server stopped answering, ping included.
    """
    from . import com_broker
    if sys.maxsize <= 2 ** 32:
        return None, _bitness_payload()
    ch = com_broker.channel_proxy(_channel_factory)
    res = ch.connect()
    if not res.ok:
        return None, res.to_dict()
    return ch, None


def _kd_export_image(args: dict) -> dict:
    """KingDraw figure, taken from the preview JPEG inside its own .kdx."""
    from .adapters import kd_export
    res = kd_export.export_image(
        args['input'], args['out'],
        keep_kdx=bool(args.get('keep_kdx')),
        min_side=int(args.get('min_side') or 300),
        timeout=int(args.get('timeout') or 90),
    )
    return res.to_dict()


def _kd_close(args: dict) -> dict:
    """Close KingDraw windows.

    The CLI grew this command first and the agent surfaces did not follow,
    which left every 'close that window and open again' answer unreachable
    from MCP: an agent could see the advice and had no tool to act on it.
    """
    from .adapters import kd_open
    pid = args.get('pid')
    targets = [int(pid)] if pid is not None else kd_open.list_pids()
    timeout = float(args.get('timeout') or 12.0)
    rows = []
    gone = []
    for target in targets:
        closed = kd_open.close_app(target, timeout)
        body = closed.data or {}
        if body.get('already_gone'):
            gone.append(target)
        rows.append({'pid': target, 'closed': bool(body.get('closed')),
                     'already_gone': bool(body.get('already_gone'))})
    still = [row['pid'] for row in rows if not row['closed']]
    payload = {'ok': not still,
               'data': {'targets': targets, 'results': rows,
                        'still_running': still, 'nothing_was_running': gone},
               'channel': 'kingdraw'}
    if still:
        payload['failure'] = {
            'code': 'E05', 'stage': 'close',
            'message': '%d KingDraw window(s) did not close' % len(still),
            'hint': 'a window with unsaved work answers WM_CLOSE with its own '
                    'dialog and stays open until that is answered',
            'detail': 'pid still running: %s' % ', '.join(str(p) for p in still)}
    return payload


def _cd_modify(args: dict) -> dict:
    """Edit the page in place: replace its content, empty it, or delete one
    atom / graphic. Unlike chemdraw_draw, which always starts a fresh page."""
    ch, err = _cd_channel()
    if ch is None:
        return err
    res = ch.modify(
        replace=args.get('replace'),
        clear=bool(args.get('clear')),
        delete_atom=args.get('delete_atom'),
        delete_object=args.get('delete_object'),
    )
    return res.to_dict()


def _cd_draw(args: dict) -> dict:
    ch, err = _cd_channel()
    if ch is None:
        return err
    res = ch.draw_smiles(args['smiles'], route=args.get('route') or None)
    payload = res.to_dict()
    if res.ok:
        data = res.data
        payload['data'] = {
            'atoms': data.get('atoms_after'),
            'bonds': data.get('bonds_after'),
            'route': data.get('route'),
            'doc': {'documents_open': ch._doc_count(),
                    'groups': data.get('groups_after')},
            'readback_smiles': data.get('readback_smiles'),
            'roundtrip': data.get('roundtrip'),
        }
    return payload


def _cd_export(args: dict) -> dict:
    ch, err = _cd_channel()
    if ch is None:
        return err
    if args.get('smiles'):
        drawn = ch.draw_smiles(args['smiles'])
        if not drawn.ok:
            return drawn.to_dict()
    res = ch.export(args['path'], args.get('format') or 'png',
                    args.get('resolution') or 300,
                    args.get('width_pt'), args.get('height_pt'))
    payload = res.to_dict()
    if res.ok:
        data = res.data
        payload['data'] = {
            'path': data['path'],
            'exists': os.path.isfile(data['path']),
            'bytes': data['bytes'],
            'format': data['format']['extension'],
            'mime': data['format']['mime'],
            'resolution': data['resolution'],
            'width_pt': data['width'],
            'height_pt': data['height'],
            'pixel_size': data['pixel_size'],
            'dpi_tag': data.get('dpi_tag'),
            'trimmed': data.get('trimmed'),
            'staged_through_ascii_temp': data.get('staged'),
        }
    return payload


def _cd_figure(args: dict) -> dict:
    ch, err = _cd_channel()
    if ch is None:
        return err
    if args.get('smiles'):
        drawn = ch.draw_smiles(args['smiles'])
        if not drawn.ok:
            return drawn.to_dict()
    res = ch.export_figure(args['path'],
                           width_mm=float(args.get('width_mm') or 85.0),
                           dpi=int(args.get('dpi') or 1200),
                           fmt=args.get('format') or 'png')
    payload = res.to_dict()
    if res.ok:
        data = res.data
        payload['data'] = {
            'path': data['path'],
            'exists': os.path.isfile(data['path']),
            'bytes': data['bytes'],
            'figure': data.get('figure'),
            'check': data.get('check'),
            'trimmed': data.get('trimmed'),
        }
    return payload


def _cd_read(args: dict) -> dict:
    ch, err = _cd_channel()
    if ch is None:
        return err
    if args.get('smiles'):
        drawn = ch.draw_smiles(args['smiles'])
        if not drawn.ok:
            return drawn.to_dict()
    return ch.read_current(args.get('format') or 'smiles').to_dict()


def _cd_capabilities(_args: dict) -> dict:
    ch, err = _cd_channel()
    if ch is None:
        return err
    rows = [row.to_dict() for row in ch.capabilities()]
    return {'ok': True, 'channel': 'chemdraw', 'data': rows,
            'evidence': 'A',
            'evidence_note': 'measured on this machine'}


def _crosscheck_tool(args: dict) -> dict:
    '''Two vendor engines on one molecule; the ChemDraw channel stays open.'''
    from . import crosscheck as xc
    if args.get('compare_to'):
        res = xc.compare(args['smiles'], args['compare_to'], args.get('kingdraw_home'))
    else:
        res = xc.crosscheck(args['smiles'], args.get('kingdraw_home'))
    return res.to_dict()


TOOLS = [
    {
        'name': 'chem_identity',
        'description': 'Normalise a SMILES string: canonical form, InChIKey and molecular formula. Pure rdkit, works on any machine.',
        'inputSchema': {
            'type': 'object',
            'properties': {'smiles': {'type': 'string', 'description': 'SMILES, e.g. c1ccccc1O'}},
            'required': ['smiles'],
        },
        'handler': lambda a: _identity(a),
    },
    {
        'name': 'kingdraw_smiles_to_mol',
        'description': 'Convert SMILES to a 2D molfile using the KingDraw engine that ships with the app.',
        'inputSchema': {
            'type': 'object',
            'properties': {'smiles': {'type': 'string'}},
            'required': ['smiles'],
        },
        'handler': lambda a: call_worker('smiles_to_mol', {'smiles': a['smiles']}),
    },
    {
        'name': 'kingdraw_mol_to_smiles',
        'description': 'Convert a molfile back to SMILES with the KingDraw engine.',
        'inputSchema': {
            'type': 'object',
            'properties': {'mol': {'type': 'string', 'description': 'molblock text (V2000 or V3000)'}},
            'required': ['mol'],
        },
        'handler': lambda a: call_worker('mol_to_smiles', {'mol': a['mol']}),
    },
    {
        'name': 'kingdraw_formula',
        'description': 'Molecular formula for a SMILES or a molblock, computed by the KingDraw engine (RDKit formula, not a naive carbon count).',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'smiles': {'type': 'string'},
                'mol': {'type': 'string'},
            },
        },
        'handler': lambda a: (call_worker('get_formula', {'smiles': a['smiles']})
                             if a.get('smiles') else
                             call_worker('get_mol_formula', {'mol': a['mol']})),
    },
    {
        'name': 'kingdraw_read_king',
        'description': 'Read a .king file (KingDraw native format) and return its structure as JSON: nodes with coordinates, bonds, texts, drawings.',
        'inputSchema': {
            'type': 'object',
            'properties': {'path': {'type': 'string', 'description': 'absolute path to a .king file'}},
            'required': ['path'],
        },
        'handler': lambda a: _read_king(a['path']),
    },
    {
        'name': 'kingdraw_match',
        'description': 'Compare two structures with the KingDraw engine. substructure=true asks whether the second is a substructure pattern hit.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'a': {'type': 'string', 'description': 'SMILES'},
                'b': {'type': 'string', 'description': 'SMILES'},
                'substructure': {'type': 'boolean', 'default': False},
            },
            'required': ['a', 'b'],
        },
        'handler': lambda a: call_worker(
            'substruct_match' if a.get('substructure') else 'struct_match',
            {'a': a['a'], 'b': a['b']}),
    },
    {
        'name': 'kingdraw_to3d',
        'description': 'Turn a flat structure into a 3D molblock (coordinates generated by the KingDraw engine).',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'smiles': {'type': 'string'},
                'mol': {'type': 'string'},
            },
        },
        'handler': lambda a: (call_worker('smiles2d_to_3d', {'smiles': a['smiles']})
                             if a.get('smiles') else
                             call_worker('mol2d_to_3d', {'mol': a['mol']})),
    },
    {
        'name': 'kingdraw_export',
        'description': 'Produce a picture from the KingDraw channel. Its own export needs a login and the WPF canvas cannot be captured, so this drives the app to save a .kdx container and lifts the preview JPEG out of it. This is preview-level output (the source is roughly 100-300 px), not publication artwork - use chemdraw_figure for that.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'input': {'type': 'string', 'description': 'input molfile path'},
                'out': {'type': 'string', 'description': 'output picture path (png or jpg)'},
                'min_side': {'type': 'integer', 'default': 300, 'description': 'upscale so the short side is at least this; 0 disables'},
                'keep_kdx': {'type': 'boolean', 'description': 'keep the intermediate .kdx for inspection'},
                'timeout': {'type': 'integer', 'default': 90},
            },
            'required': ['input', 'out'],
        },
        'handler': _kd_export_image,
    },
    {
        'name': 'kingdraw_close',
        'description': (
            'Close KingDraw windows. This is the way out of a window that already '
            'holds another document: KingDraw opens a forwarded file in a new tab '
            'but keeps the old tab text, so a second open can never be confirmed '
            'until the window is closed. Never kills a process: it posts WM_CLOSE, '
            'so a window with unsaved work answers with its own dialog and stays '
            'open, which is reported.'),
        'inputSchema': {
            'type': 'object',
            'properties': {
                'pid': {'type': 'integer',
                        'description': 'close only this process (default: every KingDraw window this tool can see)'},
                'timeout': {'type': 'number', 'default': 12,
                            'description': 'seconds to wait for each window to go'},
            },
        },
        'handler': _kd_close,
    },
    {
        'name': 'chemdraw_draw',
        'description': 'Draw a SMILES on a ChemDraw page through COM and report what landed: atom and bond counts, the insertion route and the SMILES ChemDraw reads back.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'smiles': {'type': 'string', 'description': 'SMILES, e.g. CC(=O)Oc1ccccc1C(=O)O'},
                'route': {'type': 'string', 'enum': ['smiles', 'molblock', 'cdxml', 'paste', 'objects'],
                          'description': 'insertion route; smiles is the default and keeps aromaticity'},
            },
            'required': ['smiles'],
        },
        'handler': _cd_draw,
    },
    {
        'name': 'chemdraw_modify',
        'description': 'Edit the page that is already open instead of drawing a new one: replace all of its content, empty it, or delete one atom or graphic. Bonds go with their atoms, and clearing also drains leftover graphics that would otherwise still print.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'replace': {'type': 'string', 'description': 'empty the page and draw this SMILES instead'},
                'clear': {'type': 'boolean', 'description': 'empty the page'},
                'delete_atom': {'type': 'integer', 'description': 'delete atom N (1-based)'},
                'delete_object': {'type': 'integer', 'description': 'delete graphic / picture N'},
            },
        },
        'handler': _cd_modify,
    },
    {
        'name': 'chemdraw_export',
        'description': 'Export the ChemDraw page as a picture (png, svg, emf, tif ...). Non-ASCII paths are staged through an ASCII temp directory because SaveAs silently skips them.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string', 'description': 'destination file'},
                'format': {'type': 'string', 'default': 'png', 'description': 'extension to export as'},
                'resolution': {'type': 'integer', 'default': 300},
                'width_pt': {'type': 'number', 'description': 'region width in points'},
                'height_pt': {'type': 'number'},
                'smiles': {'type': 'string', 'description': 'draw this first when the server has no page yet'},
            },
            'required': ['path'],
        },
        'handler': _cd_export,
    },
    {
        'name': 'chemdraw_figure',
        'description': 'Export a journal-ready figure: trimmed, flattened to RGB and tagged with the dpi that makes it the requested physical width, then judged by the artwork module.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'path': {'type': 'string'},
                'width_mm': {'type': 'number', 'default': 85, 'description': 'physical width in mm'},
                'dpi': {'type': 'integer', 'default': 1200},
                'format': {'type': 'string', 'default': 'png'},
                'smiles': {'type': 'string', 'description': 'draw this first when the server has no page yet'},
            },
            'required': ['path'],
        },
        'handler': _cd_figure,
    },
    {
        'name': 'chemdraw_read',
        'description': 'Read the current ChemDraw page back as SMILES, molblock or CDXML.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'format': {'type': 'string', 'enum': ['smiles', 'molfile', 'cdxml'],
                           'default': 'smiles'},
                'smiles': {'type': 'string', 'description': 'draw this first, then read it back'},
            },
        },
        'handler': _cd_read,
    },
    {
        'name': 'chem_crosscheck',
        'description': 'Verify a molecule with two independent vendor engines: rdkit is the reference, KingDraw (32-bit DLL) and ChemDraw (COM) each re-derive the structure, and the three InChIKeys must agree. Pass compare_to to decide whether two SMILES are the same molecule. Works with rdkit alone, marked degraded.',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'smiles': {'type': 'string', 'description': 'SMILES to verify'},
                'compare_to': {'type': 'string',
                               'description': 'second SMILES; the answer is whether these two are the same molecule'},
                'kingdraw_home': {'type': 'string',
                                  'description': 'folder that holds GRDKitDll.dll'},
            },
            'required': ['smiles'],
        },
        'handler': _crosscheck_tool,
    },
    {
        'name': 'chemdraw_capabilities',
        'description': 'What this ChemDraw installation can actually do, route by route, with the evidence level of each row.',
        'inputSchema': {'type': 'object', 'properties': {}},
        'handler': _cd_capabilities,
    },
]


def _read_king(path: str) -> dict:
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
    except OSError as exc:
        return {'ok': False, 'channel': 'kingdraw', 'data': None,
                'failure': {'code': 'E03', 'message': 'cannot read ' + path,
                            'detail': str(exc), 'channel': 'kingdraw', 'stage': 'read'}}
    return call_worker('sup_king_to_json', {'king_bytes': list(data)})


def _tool_specs() -> list:
    return [{k: v for k, v in t.items() if k != 'handler'} for t in TOOLS]


def _missing_argument(name, exc, given: dict) -> dict:
    '''The failure for a call that left out an argument the schema requires.

    Measured before this existed: calling chem_identity with an empty arguments
    object returned {'code': 'E99', 'message': 'tool raised', 'detail':
    't recent call last): ...'} -- a traceback sliced mid-word, no argument
    named, and no sign that the schema already said which one was required.
    '''
    missing = exc.args[0] if exc.args else ''
    required, known = [], {}
    for tool in TOOLS:
        if tool.get('name') == name:
            schema = tool.get('inputSchema') or {}
            required = list(schema.get('required') or [])
            known = schema.get('properties') or {}
            break
    hint = ('required: ' + ', '.join(required)) if required else ''
    unsupported = sorted(set(given) - set(known)) if known else []
    if unsupported:
        hint = (hint + '; unsupported: ' + ', '.join(unsupported)).strip('; ')
    return {'ok': False, 'data': None,
            'failure': {'code': 'E06', 'channel': 'mcp', 'stage': 'arguments',
                        'message': 'missing required argument %r for %s'
                                   % (str(missing), str(name)),
                        'detail': '%s needs %s and got %s'
                                  % (name, ', '.join(required) or 'no arguments',
                                     ', '.join(sorted(given)) or 'nothing'),
                        'hint': hint or 'See tools/list for the schema'}}


def _call_tool(name: str, args: dict) -> dict:
    for tool in TOOLS:
        if tool['name'] == name:
            return tool['handler'](args or {})
    return {'ok': False, 'data': None,
            'failure': {'code': 'E99', 'message': 'unknown tool: ' + str(name)}}


def handle(request: dict):
    method = request.get('method')
    rid = request.get('id')
    if rid is None:
        # JSON-RPC: a request without an id is a notification, and a server
        # must not answer it. Measured before this check: a tools/call without
        # an id came back with "id": null, which a strict client reports as a
        # protocol violation. Parse errors still answer with id null -- those
        # never reach here, they are caught in serve().
        return None
    if method == 'initialize':
        return {'jsonrpc': '2.0', 'id': rid, 'result': {
            'protocolVersion': PROTOCOL_VERSION,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': SERVER_NAME, 'version': '0.1.0'},
        }}
    if method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': rid, 'result': {'tools': _tool_specs()}}
    if method == 'tools/call':
        params = request.get('params') or {}
        try:
            with _StdoutGuard():
                payload = _call_tool(params.get('name'), params.get('arguments') or {})
        except KeyError as exc:
            # An agent that forgets an argument is the common case, and the old
            # answer -- {'message': 'tool raised', 'detail': <a Python traceback
            # sliced mid-word>} -- named neither the argument nor the schema.
            payload = _missing_argument(params.get('name'), exc,
                                        params.get('arguments') or {})
        except Exception as exc:
            payload = {'ok': False, 'data': None,
                       'failure': {'code': 'E99', 'channel': 'mcp',
                                   'stage': 'arguments',
                                   'message': '%s raised %s' % (params.get('name'), type(exc).__name__),
                                   'detail': str(exc) or 'no message',
                                   'hint': 'the envelope is honest but the tool has a bug'}}
        ok = bool(payload.get('ok'))
        return {'jsonrpc': '2.0', 'id': rid, 'result': {
            'content': [{'type': 'text',
                         'text': json.dumps(payload, indent=2, ensure_ascii=False)}],
            'isError': not ok,
        }}
    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': rid, 'result': {}}
    if rid is None:
        return None
    return {'jsonrpc': '2.0', 'id': rid,
            'error': {'code': -32601, 'message': 'method not found: ' + str(method)}}


def serve() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    try:
        _serve_loop()
    finally:
        _shutdown()
    return 0


def _serve_loop() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except Exception:
            sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': None,
                'error': {'code': -32700, 'message': 'parse error'}}) + '\n')
            sys.stdout.flush()
            continue
        response = handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + '\n')
            sys.stdout.flush()


def _shutdown() -> None:
    '''Quit the ChemDraw instance this server started; never the user's.

    Closing stdin ends the session, and a COM connection that keeps an invisible
    ChemDraw.exe alive after that is a leak: the adapter's close() quits only an
    instance it created itself.
    '''
    from . import com_broker
    try:
        # close() has to run on the apartment thread that owns the objects.
        com_broker.shutdown(deadline=10.0)
    except Exception:
        pass


if __name__ == '__main__':
    raise SystemExit(serve())