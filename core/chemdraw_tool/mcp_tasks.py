"""MCP surface for the v2 task tools (14 verbs, one call each).

The atomic v1 server stays as it is; this one speaks the task language instead:
draw, figure, batch, convert, analyze, check, stoich, 3d, resolve, ocr, grade,
variants, status, close. Every call is dispatched to `bin/v2.py` in a child
process, so a vendor crash costs one call rather than the whole server.
"""

import json
import os
import subprocess
import sys

PROTOCOL_VERSION = '2024-11-05'
SERVER_NAME = 'chem-draw-tool-tasks'
# core/chemdraw_tool/mcp_tasks.py -> core -> repository root
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
CLI = os.path.join(ROOT, 'bin', 'v2.py')


def _envelope_failure(message: str, detail: str = '') -> dict:
    return {'ok': False, 'channel': 'mcp', 'data': None,
            'failure': {'code': 'E99', 'stage': 'dispatch', 'message': message,
                        'hint': 'see detail; the CLI is the source of truth',
                        'detail': detail},
            'degraded': False, 'degrade_reason': '', 'evidence': 'measured',
            'evidence_note': '', 'elapsed_ms': 0, 'warnings': []}


def run_cli(argv, timeout: int = 180) -> dict:
    '''Run one task verb in a child process and parse its envelope.'''
    command = [sys.executable, CLI] + [str(item) for item in argv]
    # Without this the child prints in the console codepage and every non-ASCII
    # name (咖啡因) comes back as mojibake.
    environment = os.environ.copy()
    environment['PYTHONIOENCODING'] = 'utf-8'
    environment['PYTHONUTF8'] = '1'
    try:
        completed = subprocess.run(command, capture_output=True, text=True,
                                   encoding='utf-8', errors='replace',
                                   timeout=timeout, cwd=ROOT, env=environment)
    except subprocess.TimeoutExpired:
        return _envelope_failure('the task did not finish within %d s' % timeout)
    except Exception as exc:
        return _envelope_failure('%s: %s' % (type(exc).__name__, exc))
    text = (completed.stdout or '').strip()
    if not text:
        return _envelope_failure('the task produced no output',
                                 (completed.stderr or '')[-400:])
    try:
        return json.loads(text)
    except Exception:
        return _envelope_failure('the task produced non-JSON output',
                                 text[-400:])


def _draw(args) -> dict:
    argv = ['draw', args['source']]
    if args.get('width_mm'):
        argv += ['--width-mm', args['width_mm']]
    if args.get('dpi'):
        argv += ['--dpi', args['dpi']]
    if args.get('name'):
        argv += ['--name', args['name']]
    return run_cli(argv, timeout=300)


def _figure(args) -> dict:
    argv = ['figure', args['source']]
    if args.get('preset'):
        argv += ['--preset', args['preset']]
    return run_cli(argv, timeout=300)


def _batch(args) -> dict:
    argv = ['batch'] + list(args['sources'])
    if args.get('columns'):
        argv += ['--columns', args['columns']]
    if args.get('width_mm'):
        argv += ['--width-mm', args['width_mm']]
    return run_cli(argv, timeout=900)


def _simple(verb, key):
    def handler(args):
        extra = []
        for flag, name in (('--to', 'to'), ('--label', 'llm_hint')):
            pass
        return run_cli([verb, args[key]])
    return handler


def _convert(args) -> dict:
    argv = ['convert', args['source']]
    if args.get('to'):
        argv += ['--to', args['to']]
    return run_cli(argv)


def _analyze(args) -> dict:
    return run_cli(['analyze'] + list(args['sources']))


def _check(args) -> dict:
    argv = ['check', args['source']]
    if args.get('with_layout'):
        argv.append('--with-layout')
    return run_cli(argv, timeout=300)


def _stoich(args) -> dict:
    argv = ['stoich', args['reaction']]
    if args.get('scale_mmol'):
        argv += ['--scale-mmol', args['scale_mmol']]
    if args.get('yield_percent'):
        argv += ['--yield', args['yield_percent']]
    return run_cli(argv)


def _three_d(args) -> dict:
    argv = ['3d', args['source']]
    if args.get('optimize') is False:
        argv.append('--no-optimize')
    if args.get('label'):
        argv += ['--label', args['label']]
    return run_cli(argv, timeout=300)


def _resolve(args) -> dict:
    argv = ['resolve', args['query']]
    if args.get('offline'):
        argv.append('--offline')
    return run_cli(argv)


def _ocr(args) -> dict:
    argv = ['ocr', args['image']]
    if args.get('llm_hint'):
        argv += ['--llm-hint', args['llm_hint']]
    return run_cli(argv, timeout=600)


def _grade(args) -> dict:
    return run_cli(['grade', '--answer', args['answer']] + list(args['submissions']))


def _variants(args) -> dict:
    return run_cli(['variants', args['scaffold']] + list(args['substituents']))


def _reaction(args) -> dict:
    argv = ['reaction', args['reaction']]
    if args.get('conditions'):
        argv += ['--conditions', args['conditions']]
    if args.get('width_mm'):
        argv += ['--width-mm', args['width_mm']]
    return run_cli(argv, timeout=600)


def _status(args) -> dict:
    return run_cli(['status'], timeout=120)


def _close(args) -> dict:
    argv = ['close']
    if args.get('quit'):
        argv.append('--quit')
    return run_cli(argv, timeout=180)


def _structure(description: str, extra=None) -> dict:
    schema = {'type': 'object',
              'properties': {'source': {'type': 'string',
                                        'description': 'SMILES, InChI or a molblock'}},
              'required': ['source']}
    schema['properties'].update(extra or {})
    return {'description': description, 'inputSchema': schema}


TOOLS = [
    {'name': 'chem_status', 'handler': _status,
     'description': 'What is available right now: routes, locks, session, artifacts.',
     'inputSchema': {'type': 'object', 'properties': {}}},
    {'name': 'chem_draw', 'handler': _draw,
     'description': 'Draw one structure and return a preview image plus identity.',
     'inputSchema': {'type': 'object',
                     'properties': {'source': {'type': 'string'},
                                    'width_mm': {'type': 'number'},
                                    'dpi': {'type': 'integer'},
                                    'name': {'type': 'string'}},
                     'required': ['source']}},
    {'name': 'chem_figure', 'handler': _figure,
     'description': 'Export at a journal preset (cn-1col, cn-2col, acs-1col, ...).',
     'inputSchema': {'type': 'object',
                     'properties': {'source': {'type': 'string'},
                                    'preset': {'type': 'string'}},
                     'required': ['source']}},
    {'name': 'chem_batch', 'handler': _batch,
     'description': 'Draw many structures at one bond length and tile a contact sheet.',
     'inputSchema': {'type': 'object',
                     'properties': {'sources': {'type': 'array',
                                                'items': {'type': 'string'}},
                                    'columns': {'type': 'integer'},
                                    'width_mm': {'type': 'number'}},
                     'required': ['sources']}},
    {'name': 'chem_convert', 'handler': _convert,
     'description': 'Write the structure as sdf, mol, smiles, inchi or csv.',
     'inputSchema': {'type': 'object',
                     'properties': {'source': {'type': 'string'},
                                    'to': {'type': 'string'}},
                     'required': ['source']}},
    {'name': 'chem_analyze', 'handler': _analyze,
     'description': 'Property table (formula, MW, logP, TPSA, InChIKey) as CSV + markdown.',
     'inputSchema': {'type': 'object',
                     'properties': {'sources': {'type': 'array',
                                                'items': {'type': 'string'}}},
                     'required': ['sources']}},
    {'name': 'chem_check', 'handler': _check,
     'description': 'Valence, charge, fragments, stereo, atom clashes; each with a fix.',
     'inputSchema': {'type': 'object',
                     'properties': {'source': {'type': 'string'},
                                    'with_layout': {'type': 'boolean'}},
                     'required': ['source']}},
    {'name': 'chem_stoich', 'handler': _stoich,
     'description': "Reaction table for 'A.B>>C': equivalents, mmol, mass.",
     'inputSchema': {'type': 'object',
                     'properties': {'reaction': {'type': 'string'},
                                    'scale_mmol': {'type': 'number'},
                                    'yield_percent': {'type': 'number'}},
                     'required': ['reaction']}},
    {'name': 'chem_reaction', 'handler': _reaction,
     'description': 'Draw a reaction: reactants, arrow, products, atom map numbers.',
     'inputSchema': {'type': 'object',
                     'properties': {'reaction': {'type': 'string'},
                                    'conditions': {'type': 'string'},
                                    'width_mm': {'type': 'number'}},
                     'required': ['reaction']}},
    {'name': 'chem_3d', 'handler': _three_d,
     'description': 'Embed and optimise a 3D conformer; writes .mol and .xyz.',
     'inputSchema': {'type': 'object',
                     'properties': {'source': {'type': 'string'},
                                    'optimize': {'type': 'boolean'},
                                    'label': {'type': 'string'}},
                     'required': ['source']}},
    {'name': 'chem_resolve', 'handler': _resolve,
     'description': 'Name or CAS number to a verified structure (local tables, then PubChem).',
     'inputSchema': {'type': 'object',
                     'properties': {'query': {'type': 'string'},
                                    'offline': {'type': 'boolean'}},
                     'required': ['query']}},
    {'name': 'chem_ocr', 'handler': _ocr,
     'description': 'Read a structure from an image; several readers vote, RDKit arbitrates.',
     'inputSchema': {'type': 'object',
                     'properties': {'image': {'type': 'string'},
                                    'llm_hint': {'type': 'string'}},
                     'required': ['image']}},
    {'name': 'chem_grade', 'handler': _grade,
     'description': 'Mark submissions against one answer; explains each difference.',
     'inputSchema': {'type': 'object',
                     'properties': {'answer': {'type': 'string'},
                                    'submissions': {'type': 'array',
                                                    'items': {'type': 'string'}}},
                     'required': ['answer', 'submissions']}},
    {'name': 'chem_variants', 'handler': _variants,
     'description': 'Replace the [*] on a scaffold with each substituent: question variants.',
     'inputSchema': {'type': 'object',
                     'properties': {'scaffold': {'type': 'string'},
                                    'substituents': {'type': 'array',
                                                     'items': {'type': 'string'}}},
                     'required': ['scaffold', 'substituents']}},
    {'name': 'chem_close', 'handler': _close,
     'description': 'Close the working page; the application stays up unless quit is true.',
     'inputSchema': {'type': 'object',
                     'properties': {'quit': {'type': 'boolean'}}}},
]


def _specs() -> list:
    return [{'name': tool['name'], 'description': tool['description'],
             'inputSchema': tool['inputSchema']} for tool in TOOLS]


def _call(name: str, args: dict) -> dict:
    for tool in TOOLS:
        if tool['name'] == name:
            try:
                return tool['handler'](args or {})
            except KeyError as exc:
                return _envelope_failure('missing argument %s' % exc,
                                         'see the tool inputSchema')
    return _envelope_failure('unknown tool: %s' % name)


def handle(request: dict):
    method = request.get('method')
    rid = request.get('id')
    if rid is None:
        return None
    if method == 'initialize':
        return {'jsonrpc': '2.0', 'id': rid, 'result': {
            'protocolVersion': PROTOCOL_VERSION,
            'capabilities': {'tools': {'listChanged': False}},
            'serverInfo': {'name': SERVER_NAME, 'version': '0.2.0'}}}
    if method == 'tools/list':
        return {'jsonrpc': '2.0', 'id': rid, 'result': {'tools': _specs()}}
    if method == 'tools/call':
        params = request.get('params') or {}
        payload = _call(params.get('name'), params.get('arguments') or {})
        return {'jsonrpc': '2.0', 'id': rid, 'result': {
            'content': [{'type': 'text',
                         'text': json.dumps(payload, indent=2, ensure_ascii=False)}],
            'isError': not bool(payload.get('ok'))}}
    if method == 'ping':
        return {'jsonrpc': '2.0', 'id': rid, 'result': {}}
    return {'jsonrpc': '2.0', 'id': rid,
            'error': {'code': -32601, 'message': 'method not found: ' + str(method)}}


def serve() -> int:
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
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
    return 0