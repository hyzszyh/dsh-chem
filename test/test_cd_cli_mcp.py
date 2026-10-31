r'''End-to-end tests for the ChemDraw channel across CLI and MCP.

Run with the 64-bit interpreter (ChemDraw's COM server is x64):

    %LOCALAPPDATA%\Programs\Python\Python311\python.exe test/test_cd_cli_mcp.py

One command covers both surfaces:

* the 'cd' CLI subcommands (draw, export, figure, read, capabilities, doctor),
  each invoked as a real subprocess and checked for an ok Result plus a real
  artifact on disk;
* an MCP stdio session driven with initialize / tools/list / tools/call, where
  every stdout line must parse as JSON (the transport is line-delimited JSON,
  so one stray print from ChemDraw or rdkit would corrupt it);
* the 32-bit guard: runtime/py32/python.exe must answer E04, not crash;
* process hygiene: no ChemDraw.exe is left behind when the run ends.

Set CD_TEST_NO_KILL=1 to keep an existing ChemDraw session alive across the run.
'''

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = sys.executable
PY32 = os.path.join(ROOT, 'runtime', 'py32', 'python.exe')
CLI = os.path.join(ROOT, 'bin', 'cli.py')
OUT_DIR = os.path.join(HERE, 'out')
ASPIRIN = 'CC(=O)Oc1ccccc1C(=O)O'
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'
CD_TOOLS = ('chemdraw_draw', 'chemdraw_export', 'chemdraw_figure',
            'chemdraw_read', 'chemdraw_capabilities')


def _env() -> dict:
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'
    core = os.path.join(ROOT, 'core')
    env['PYTHONPATH'] = core + (os.pathsep + env['PYTHONPATH']
                                if env.get('PYTHONPATH') else '')
    return env


def _is_64bit() -> bool:
    return sys.maxsize > 2 ** 32


def _chemdraw_pids() -> str:
    return subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ChemDraw.exe',
                           '/FO', 'CSV', '/NH'],
                          capture_output=True, text=True, timeout=30).stdout


def _wait_for_no_chemdraw(timeout: float = 20.0) -> None:
    '''Quit returns before the COM server is gone, so wait instead of racing.

    Each CLI run quits the instance it started, but the process lingers for a
    moment. A doctor probe that lands in that window attaches to a dying
    instance and reports started_by_us=False, which is a timing artefact of the
    suite, not a fact about the channel.
    '''
    deadline = time.time() + timeout
    while _chemdraw_pids() and time.time() < deadline:
        time.sleep(0.5)


def _kill_stray() -> None:
    if os.environ.get('CD_TEST_NO_KILL'):
        return
    try:
        subprocess.run(['taskkill', '/F', '/IM', 'ChemDraw.exe'],
                       capture_output=True, timeout=30)
    except Exception:
        pass
    time.sleep(1.0)


def _parse_json(text: str) -> dict:
    '''First JSON object in the output; CLI chatter before it is tolerated.'''
    start = text.find('{')
    assert start >= 0, 'no JSON in the CLI output: ' + text[:400]
    return json.loads(text[start:])


def _want_json(args):
    '''Ask for the envelope explicitly.

    The CLI's default output is written for a person at a terminal; this
    suite reads stdout as JSON, so it has to say which shape it wants
    instead of depending on the default staying JSON-shaped forever.
    '''
    return list(args) if '--json' in args else list(args) + ['--json']


def run_cli(*args, timeout: int = 240):
    proc = subprocess.run([PY, CLI] + _want_json(args), cwd=ROOT, env=_env(),
                          capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout)
    return proc.returncode, _parse_json(proc.stdout or '{}'), proc


def _ok_cli(*args):
    rc, payload, proc = run_cli(*args)
    assert payload.get('ok') is True, 'cd %s failed: %s' % (
        ' '.join(args), json.dumps(payload, ensure_ascii=False)[:900])
    assert rc == 0, 'exit code %d for cd %s (stderr: %s)' % (
        rc, ' '.join(args), (proc.stderr or '')[-400:])
    assert payload.get('channel') == 'chemdraw', payload.get('channel')
    return payload


def mcp_session(messages: list, timeout: int = 300):
    '''Speak JSON-RPC to the server over stdin and return parsed responses.

    Relative imports mean the server must be started as a module, not as a
    script path; PYTHONPATH carries <root>/core.
    '''
    payload = ''.join(json.dumps(m) + '\n' for m in messages)
    proc = subprocess.run([PY, '-m', 'chemdraw_tool.mcp_server'],
                          cwd=ROOT, env=_env(), input=payload,
                          capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout)
    responses = []
    for index, line in enumerate((proc.stdout or '').splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            responses.append(json.loads(line))
        except Exception as exc:
            raise AssertionError(
                'stdout line %d is not JSON (%s): %r' % (index, exc, line[:200]))
    return responses, proc


def _tool_body(response: dict) -> dict:
    result = response.get('result') or {}
    assert 'content' in result, 'no content in response: %r' % (response,)
    return json.loads(result['content'][0]['text'])


def test_00_no_stray_chemdraw_before_start():
    _kill_stray()
    out = _chemdraw_pids()
    assert 'ChemDraw.exe' not in out, 'stray instance survived: ' + out[:200]


def test_01_cli_draw_writes_a_png():
    os.makedirs(OUT_DIR, exist_ok=True)
    target = os.path.join(OUT_DIR, 'cli_draw.png')
    if os.path.exists(target):
        os.remove(target)
    payload = _ok_cli('cd', 'draw', ASPIRIN, '--out', target, '--resolution', '300')
    data = payload['data']
    assert data['atoms_after'] == 13 and data['bonds_after'] == 13, data
    assert data['route'] == 'smiles', data['route']
    assert data['readback_smiles'], data
    assert os.path.isfile(target), 'no PNG at ' + target
    size = os.path.getsize(target)
    assert size > 1024, 'PNG is only %d bytes' % size
    # The envelope has to name the file it wrote, at the same keys cd export
    # and kd export use: measured with top-level path null while the PNG sat
    # on disk, the only place to look was inside the nested export envelope.
    nested = data['export']['data']
    assert data['path'] == nested['path'] == target, (data.get('path'), nested) 
    assert data['bytes'] == nested['bytes'] == size, (data.get('bytes'), size)
    assert data['format'] == nested['format'], (data.get('format'), nested['format'])
    with open(target, 'rb') as fh:
        assert fh.read(8) == PNG_MAGIC
    print('    draw -> %d atoms, %s (%d bytes)'
          % (data['atoms_after'], os.path.basename(target), size))


def test_02_cli_export_reports_file_facts():
    # Written into a Chinese-named directory on purpose: the staging this
    # asserts must not depend on where the checkout itself lives.
    chinese = os.path.join(OUT_DIR, '导出中文路径')
    os.makedirs(chinese, exist_ok=True)
    target = os.path.join(chinese, 'cli_export.png')
    payload = _ok_cli('cd', 'export', target, '--smiles', ASPIRIN,
                      '--resolution', '300')
    data = payload['data']
    assert data['bytes'] > 1024, data['bytes']
    assert os.path.getsize(data['path']) == data['bytes']
    assert data['format']['extension'].lower() == 'png', data['format']
    assert data['pixel_size'] and data['pixel_size'][0] > 400, data['pixel_size']
    # Measured: this build tags every PNG 144 dpi and writes it RGBA.
    assert data['dpi_tag'] == 144, data['dpi_tag']
    assert data['staged'] is True, 'a Chinese path must go through ASCII staging'
    # The trim keeps a margin. Measured before it kept none: the acetate
    # export was 260x242 with ink on all four borders, so the terminal C-C
    # bond sat on the last column and read as a bond that had been cut off.
    from PIL import Image
    with Image.open(data['path']) as image:
        grey = image.convert('L')
        box = grey.point(lambda value: 0 if value > 245 else 255).getbbox()
        assert box, 'the export has no ink at all'
        margins = (box[0], box[1], grey.width - box[2], grey.height - box[3])
    assert min(margins) >= 8, (
        'the drawing sits %s px from the edges; a figure needs paper around it'
        % (margins,))
    assert data.get('trimmed', {}).get('pad_px'), data.get('trimmed')
    svg = _ok_cli('cd', 'export', os.path.join(OUT_DIR, 'cli_export.svg'),
                  '--smiles', ASPIRIN, '--format', 'svg')
    assert svg['data']['format']['extension'].lower() == 'svg', svg['data']['format']
    assert svg['data']['bytes'] > 512, svg['data']['bytes']
    print('    export -> %s %s, svg %d bytes'
          % (data['pixel_size'], data['format']['mime'], svg['data']['bytes']))


def test_03_cli_figure_is_journal_ready():
    target = os.path.join(OUT_DIR, 'cli_figure.png')
    payload = _ok_cli('cd', 'figure', target, '--smiles', ASPIRIN,
                      '--width-mm', '50', '--dpi', '1200')
    data = payload['data']
    figure = data.get('figure') or {}
    check = data.get('check') or {}
    assert figure.get('mode') == 'RGB', figure
    assert figure.get('dpi') == 1200, figure
    assert abs(figure.get('width_mm', 0) - 50.0) <= 1.0, figure
    assert check.get('issues') == [], check
    assert data['bytes'] > 1024, data['bytes']
    print('    figure -> %s px, %.1f mm, dpi %s, issues %s'
          % (figure.get('width_px'), figure.get('width_mm'), figure.get('dpi'),
             check.get('issues')))


def test_04_cli_read_answers_both_formats():
    smiles = _ok_cli('cd', 'read', '--smiles', ASPIRIN, '--format', 'smiles')
    assert smiles['data']['mime'] == 'chemical/x-daylight-smiles'
    assert smiles['data']['chars'] >= 9, smiles['data']
    mol = _ok_cli('cd', 'read', '--smiles', ASPIRIN, '--format', 'molfile')
    assert 'V2000' in mol['data']['text'], mol['data']['text'][:120]
    assert mol['data']['chars'] > 500, mol['data']['chars']
    print('    read -> %r / %d molblock chars'
          % (smiles['data']['text'], mol['data']['chars']))


def test_05_cli_capabilities_and_doctor():
    caps = _ok_cli('cd', 'capabilities')
    routes = {row['route'] for row in caps['data']}
    assert 'objects-data-smiles' in routes, sorted(routes)
    assert 'documents-open' in routes, sorted(routes)
    assert len(caps['data']) >= 8, len(caps['data'])
    opened = [r for r in caps['data'] if r['route'] == 'documents-open'][0]
    assert opened['available'] is False, opened
    # Started and quit by the doctor itself: this is the same probe the
    # top-level 'doctor cd' runs, reached through the channel subcommand.
    _wait_for_no_chemdraw()
    rc, doctor, proc = run_cli('cd', 'doctor', '--json')
    assert doctor.get('channel') == 'chemdraw', doctor
    assert 'capabilities' in doctor and 'details' in doctor, sorted(doctor)
    assert doctor.get('available') is True, doctor.get('failures')
    assert doctor['details'].get('started_by_us') is True, doctor['details']
    assert any(c['route'] == 'com-saveas' for c in doctor['capabilities']), (
        doctor['capabilities'])
    print('    capabilities -> %d rows, doctor available=%s (quit its own instance)'
          % (len(caps['data']), doctor.get('available')))


def test_06_mcp_lists_the_chemdraw_tools():
    responses, proc = mcp_session([
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
    ])
    assert len(responses) == 2, 'expected 2 responses, got %r' % (responses,)
    init = responses[0]['result']
    assert init['protocolVersion'], init
    assert init['serverInfo']['name'] == 'chem-draw-tool', init['serverInfo']
    names = [t['name'] for t in responses[1]['result']['tools']]
    for tool in CD_TOOLS:
        assert tool in names, 'missing %s in %r' % (tool, names)
    for tool in ('kingdraw_smiles_to_mol', 'chem_identity'):
        assert tool in names, 'the KingDraw surface must stay intact: %r' % (names,)
    print('    mcp tools -> %d total, chemdraw: %d'
          % (len(names), sum(1 for n in names if n.startswith('chemdraw_'))))


def test_07_mcp_tools_call_round_trip():
    export_path = os.path.join(OUT_DIR, 'mcp_export.png')
    figure_path = os.path.join(OUT_DIR, 'mcp_figure.png')
    messages = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
         'params': {'name': 'chemdraw_draw', 'arguments': {'smiles': ASPIRIN}}},
        {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call',
         'params': {'name': 'chemdraw_export',
                    'arguments': {'path': export_path, 'format': 'png',
                                  'resolution': 300}}},
        {'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call',
         'params': {'name': 'chemdraw_figure',
                    'arguments': {'path': figure_path, 'width_mm': 50,
                                  'dpi': 1200}}},
        {'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call',
         'params': {'name': 'chemdraw_read', 'arguments': {'format': 'smiles'}}},
        {'jsonrpc': '2.0', 'id': 7, 'method': 'tools/call',
         'params': {'name': 'chemdraw_capabilities', 'arguments': {}}},
    ]
    responses, proc = mcp_session(messages)
    assert len(responses) == len(messages), (
        'expected %d responses, got %d' % (len(messages), len(responses)))
    by_id = {r.get('id'): r for r in responses}

    draw = by_id[3]['result']
    assert draw['isError'] is False, draw
    body = _tool_body(by_id[3])
    assert body['ok'] is True, body
    for key in ('atoms', 'bonds', 'doc', 'route'):
        assert key in body['data'], 'chemdraw_draw must report %r: %r' % (key, body['data'])
    assert body['data']['atoms'] == 13 and body['data']['bonds'] == 13, body['data']
    assert body['data']['route'] == 'smiles', body['data']

    exported = by_id[4]['result']
    assert exported['isError'] is False, exported
    body = _tool_body(by_id[4])
    assert body['data']['exists'] is True, body['data']
    assert body['data']['bytes'] > 1024, body['data']
    assert os.path.isfile(export_path)

    figure = by_id[5]['result']
    assert figure['isError'] is False, figure
    body = _tool_body(by_id[5])
    assert (body['data'].get('figure') or {}).get('mode') == 'RGB', body['data']
    assert (body['data'].get('check') or {}).get('issues') == [], body['data']

    read = by_id[6]['result']
    assert read['isError'] is False, read
    body = _tool_body(by_id[6])
    assert body['data']['chars'] >= 9, body['data']

    caps = by_id[7]['result']
    assert caps['isError'] is False, caps
    body = _tool_body(by_id[7])
    assert len(body['data']) >= 8, body['data']
    figure_body = _tool_body(by_id[5])
    print('    mcp call -> draw 13/13 atoms, export %d bytes, figure %s px'
          % (os.path.getsize(export_path),
             (figure_body['data'].get('figure') or {}).get('width_px')))


def test_08_mcp_stdout_stays_protocol_only():
    '''Every line of a busy session must parse; nothing may leak from COM.'''
    responses, proc = mcp_session([
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call',
         'params': {'name': 'chemdraw_draw',
                    'arguments': {'smiles': 'c1ccccc1O', 'route': 'cdxml'}}},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
         'params': {'name': 'chemdraw_read', 'arguments': {'format': 'cdxml'}}},
    ])
    assert len(responses) == 3, responses
    for response in responses:
        assert response.get('jsonrpc') == '2.0', response
    cdxml = _tool_body(responses[2])
    assert cdxml['data']['text'].lstrip().startswith('<?xml'), cdxml['data']['text'][:80]
    assert (proc.stdout or '').count('\n') == 3, 'unexpected extra stdout lines'


def test_09_py32_answers_e04_instead_of_crashing():
    '''The 32-bit runtime must refuse politely: ChemDraw COM is x64 only.'''
    if not os.path.isfile(PY32):
        print('    skipped: %s is not present' % PY32)
        return
    proc = subprocess.run([PY32, CLI, 'cd', 'capabilities', '--json'],
                          cwd=ROOT, env=_env(),
                          capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=120)
    payload = _parse_json(proc.stdout or '{}')
    assert payload.get('ok') is False, payload
    assert proc.returncode == 1, proc.returncode
    failure = payload.get('failure') or {}
    assert failure.get('code') == 'E04', failure
    assert '64-bit' in failure.get('message', ''), failure
    assert 'Traceback' not in (proc.stderr or ''), proc.stderr[-500:]
    print('    py32 -> %s: %s' % (failure.get('code'), failure.get('message')[:60]))


def test_10_no_chemdraw_left_behind():
    '''Every command quieted its own instance; the run must leave nothing.'''
    time.sleep(1.0)
    out = _chemdraw_pids()
    assert 'ChemDraw.exe' not in out, 'a ChemDraw instance was left running: ' + out[:300]


def main() -> int:
    if not _is_64bit():
        print('FAIL: run this suite with the 64-bit interpreter; every '
              'ChemDraw call would answer E04 here')
        return 2
    tests = [(name, fn) for name, fn in list(globals().items())
             if name.startswith('test_') and callable(fn)]
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
