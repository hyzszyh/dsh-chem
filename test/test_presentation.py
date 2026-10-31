'''Presentation tests: the terminal layout must hold up at any width.

These run without ChemDraw or KingDraw: they call the renderers in
core/chemdraw_tool/cli.py directly with realistic payloads, so the checks are
about layout, not about the machines. Two of them shell out to the CLI for the
things argparse owns (help wrapping) and for the identity summary.

    python test/test_presentation.py          # run all, exit 1 on failure
    pytest test/test_presentation.py
'''

from __future__ import annotations

import io
import os
import subprocess
import sys
import unicodedata
import contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))

from chemdraw_tool import cli  # noqa: E402

CLI = os.path.join(ROOT, 'bin', 'cli.py')

ASPIRIN_KEY = 'BSYNRYMUTXBXSQ-UHFFFAOYSA-N'
PHENOL_KEY = 'ISWSIDIOOBJBQZ-UHFFFAOYSA-N'

DOCTOR_KD = {
    'channel': 'kingdraw',
    'available': True,
    'version': 'GRDKitDll exports=12/12',
    'home': 'D:\\tool\\KingDraw',
    'details': {'exports_found': ['smilesToMol'] * 12, 'exports_expected': 12},
    'capabilities': [
        {'action': 'read', 'route': 'native+file', 'available': True, 'evidence': 'A'},
        {'action': 'draw', 'route': 'file+cli', 'available': True, 'evidence': 'B'},
        {'action': 'layout', 'route': 'file-coords', 'available': False, 'evidence': 'C'},
    ],
    'failures': [],
}

DOCTOR_FAILING = {
    'channel': 'kingdraw',
    'available': False,
    'version': '',
    'home': '',
    'details': {},
    'capabilities': [],
    'failures': [{
        'code': 'E04',
        'message': 'KingDraw core library is x86; this interpreter is x64',
        'hint': 'Run with runtime/py32/python.exe',
        'detail': 'ctypes refused to load GRDKitDll.dll',
        'stage': 'bitness',
        'channel': 'kingdraw',
    }],
}

IDENTITY = {
    'input': 'CC(=O)Oc1ccccc1C(=O)O',
    'canonical_smiles': 'CC(=O)Oc1ccccc1C(=O)O',
    'inchikey': ASPIRIN_KEY,
    'formula': 'C9H8O4',
    'evidence': 'A',
    'note': '',
}

RESULT_FAIL = {
    'ok': False,
    'data': None,
    'channel': 'chemdraw',
    'degraded': False,
    'degrade_reason': '',
    'evidence': 'A',
    'elapsed_ms': 12,
    'warnings': [],
    'evidence_note': 'measured on this machine',
    'failure': {
        'code': 'E06',
        'message': 'The structure could not be parsed',
        'hint': 'Check the SMILES syntax',
        'detail': "RDKit could not parse 'C1CC('",
        'channel': 'chemdraw',
        'stage': 'draw',
    },
}


def width(text: str) -> int:
    '''Columns a line occupies, with ideographs counted as two.'''
    total = 0
    for ch in text:
        if unicodedata.combining(ch) or unicodedata.category(ch) in ('Mn', 'Me', 'Cf'):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
    return total


@contextlib.contextmanager
def columns(width_):
    old = os.environ.get('COLUMNS')
    os.environ['COLUMNS'] = str(width_)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop('COLUMNS', None)
        else:
            os.environ['COLUMNS'] = old


def captured(fn, *args, **kwargs) -> str:
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        fn(*args, **kwargs)
    return buffer.getvalue()


def assert_fits(lines, limit, label=''):
    bad = [(index + 1, width(line), line) for index, line in enumerate(lines)
           if width(line) > limit]
    assert not bad, '%s: %d line(s) wider than %d columns: %r' % (
        label, len(bad), limit, bad[:3])


def columns_of(line: str) -> list:
    '''Start column of each whitespace-separated token.'''
    starts, in_token = [], False
    for index, ch in enumerate(line):
        if ch == ' ':
            in_token = False
        elif not in_token:
            starts.append(width(line[:index]))
            in_token = True
    return starts


# -- the width primitives --------------------------------------------------
def test_display_width_counts_cjk_as_two_columns():
    assert width('abc') == 3
    assert width('中文') == 4
    assert width('a中b') == 4
    assert cli._dwidth('中文') == 4, 'the renderer must use display width'
    # -- is ambiguous-width: one column here, like a terminal does it
    assert cli._dwidth('中文宽度—测试') == 13
    assert cli._dwidth('中文字符宽度') == 12
    assert cli._pad('中', 4) == '中  ', repr(cli._pad('中', 4))
    assert cli._pad('中文', 4) == '中文'


def test_absent_unknown_and_present_are_three_different_strings():
    assert cli._cell(None) == '-'
    assert cli._cell('') == '-'
    assert cli._cell(True) == 'true'
    assert cli._cell(False) == 'false'
    assert cli._cell(0) == '0'
    # version/home: empty means unknown, and home falls back to the real path
    assert cli._base_value({'version': ''}, 'version') == 'unknown'
    assert cli._base_value(
        {'home': '', 'details': {'fullname': 'C:\\x\\ChemDraw.exe'}},
        'home').endswith('ChemDraw.exe')
    assert cli._base_value({'home': '', 'details': {}}, 'home') == 'unknown'


# -- tables: no column drifts, whatever the content ------------------------
def test_doctor_table_columns_line_up_with_a_long_route():
    with columns(120):
        lines = cli._render(dict(DOCTOR_KD, capabilities=DOCTOR_KD['capabilities'] + [
            {'action': 'check', 'route': 'com-object+rdkit', 'available': True,
             'evidence': 'B'}]))
    rows = [line for line in lines if 'com-object+rdkit' in line
            or line.startswith('draw ')
            or line.startswith('layout')]
    starts = [columns_of(line) for line in rows]
    assert len({len(s) for s in starts}) == 1, rows
    for column in range(len(starts[0])):
        assert len({s[column] for s in starts}) == 1, (rows, starts)


def test_doctor_table_never_exceeds_a_narrow_terminal():
    for limit in (32, 40, 60, 80):
        with columns(limit):
            lines = cli._render(DOCTOR_KD)
        assert_fits(lines, limit, 'doctor kd at %d columns' % limit)


def test_cjk_text_in_a_cell_does_not_shift_the_columns():
    payload = dict(DOCTOR_KD)
    payload['capabilities'] = [
        {'action': '绘制', 'route': '原生+文件', 'available': True, 'evidence': 'A'},
        {'action': '导出', 'route': '文件+命令行', 'available': True, 'evidence': 'B'},
    ]
    with columns(80):
        lines = cli._render(payload)
    table = [line for line in lines if '原生' in line or '文件' in line]
    assert table, lines
    starts = [columns_of(line) for line in table]
    assert len({len(s) for s in starts}) == 1, table
    for column in range(len(starts[0])):
        assert len({s[column] for s in starts}) == 1, (table, starts)
    assert_fits(lines, 80, 'cjk doctor table')


# -- identity: the InChIKey must never be broken ---------------------------
def test_identity_summary_fits_40_columns_and_keeps_the_key_intact():
    with columns(40):
        lines = cli._render_identity(IDENTITY)
    assert_fits(lines, 40, 'identity at 40 columns')
    assert any(ASPIRIN_KEY in line for line in lines), lines
    assert any('CC(=O)Oc1ccccc1C(=O)O' in line for line in lines), lines


def test_identity_command_defaults_to_the_summary_and_offers_json():
    env = dict(os.environ, PYTHONIOENCODING='utf-8', COLUMNS='40')
    human = subprocess.run([sys.executable, CLI, 'identity', 'c1ccccc1O'],
                           cwd=ROOT, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', env=env, timeout=120)
    assert human.returncode == 0, human.stderr[-400:]
    assert PHENOL_KEY in human.stdout, human.stdout
    assert '{' not in human.stdout, 'the default must be the summary: ' + human.stdout
    assert_fits(human.stdout.splitlines(), 40, 'identity CLI at 40 columns')

    machine = subprocess.run([sys.executable, CLI, 'identity', 'c1ccccc1O', '--json'],
                             cwd=ROOT, capture_output=True, text=True,
                             encoding='utf-8', errors='replace', env=env, timeout=120)
    assert '"inchikey": "%s"' % PHENOL_KEY in machine.stdout, machine.stdout[:400]


# -- failures --------------------------------------------------------------
def test_failure_block_fits_and_keeps_the_sentence_readable():
    payload = dict(DOCTOR_FAILING)
    for limit in (40, 60, 80):
        with columns(limit):
            lines = cli._render(payload)
        assert_fits(lines, limit, 'failing doctor at %d columns' % limit)
        assert any('E04' in line for line in lines), lines
        assert any('x86' in line for line in lines), lines
    with columns(80):
        lines = cli._render(payload)
    assert any(line.strip().startswith('│ fix') for line in lines), lines


def test_failure_memo_fits_and_names_the_code():
    for limit in (40, 60, 80):
        with columns(limit):
            memo = cli._render_memo(RESULT_FAIL, limit)
        assert memo, 'a failure must produce a memo'
        assert_fits(memo, limit, 'memo at %d columns' % limit)
        text = '\n'.join(memo)
        assert 'E06' in text, memo
        assert 'could not be parsed' in text.replace('\n    ', ' '), memo


def test_degraded_and_preview_products_say_so_on_the_same_screen():
    preview = {'ok': True, 'channel': 'kingdraw', 'evidence': 'A',
               'degraded': True,
               'degrade_reason': 'preview-level raster extracted from a .kdx, not a render',
               'data': {'path': 'x.png', 'bytes': 10}, 'warnings': [
                   'preview-level image: KingDraw renders a JPEG preview inside the .kdx']}
    with columns(80):
        memo = cli._render_memo(preview, 80)
    text = '\n'.join(memo)
    assert 'degraded' in text.lower(), text
    assert 'preview' in text.lower(), text
    assert_fits(memo, 80, 'preview memo')


def test_evidence_below_a_is_announced():
    inferred = {'ok': True, 'channel': 'cli', 'evidence': 'C',
                'evidence_note': 'design inference, not yet verified',
                'data': {'text': 'x'}, 'warnings': []}
    with columns(80):
        memo = cli._render_memo(inferred, 80)
    text = '\n'.join(memo)
    assert 'evidence level C' in text, text


# -- crosscheck ------------------------------------------------------------
def test_crosscheck_columns_share_one_alignment():
    data = {'agree': True, 'basis': 'inchikey',
            'compared': ['kingdraw', 'chemdraw'],
            'reference': {'inchikey': ASPIRIN_KEY,
                          'smiles': 'CC(=O)Oc1ccccc1C(=O)O'},
            'engines': {
                'kingdraw': {'ok': True, 'inchikey': ASPIRIN_KEY,
                             'smiles': 'CC(=O)Oc1ccccc1C(=O)O'},
                'chemdraw': {'ok': True, 'inchikey': ASPIRIN_KEY,
                             'smiles': 'CC(Oc1c(C(O)=O)cccc1)=O'},
            },
            'mismatch': []}
    payload = {'ok': True, 'channel': 'crosscheck', 'data': data,
               'degraded': False, 'warnings': []}

    class Fake:
        def to_dict(self):
            return payload

    with columns(80):
        out = captured(cli._render_crosscheck, Fake())
    lines = out.splitlines()
    assert_fits(lines, 80, 'crosscheck at 80 columns')
    body = [line for line in lines if line.startswith(('rdkit ', 'kingdraw ', 'chemdraw '))]
    starts = [columns_of(line) for line in body]
    for column in range(len(starts[0])):
        assert len({s[column] for s in starts}) == 1, (body, starts)
    assert any(ASPIRIN_KEY in line for line in lines)


def test_crosscheck_stacks_on_a_narrow_terminal_without_splitting_keys():
    data = {'agree': True, 'basis': 'inchikey', 'compared': ['kingdraw'],
            'reference': {'inchikey': ASPIRIN_KEY, 'smiles': 'CC(=O)Oc1ccccc1C(=O)O'},
            'engines': {'kingdraw': {'ok': True, 'inchikey': ASPIRIN_KEY,
                                     'smiles': 'CC(=O)Oc1ccccc1C(=O)O'}},
            'mismatch': []}
    payload = {'ok': True, 'data': data, 'degraded': False, 'warnings': []}

    class Fake:
        def to_dict(self):
            return payload

    with columns(40):
        out = captured(cli._render_crosscheck, Fake())
    lines = out.splitlines()
    assert_fits(lines, 40, 'crosscheck at 40 columns')
    assert any(ASPIRIN_KEY in line for line in lines), 'the key was split'


# -- argparse: help must not break a subcommand name -----------------------
def test_help_does_not_wrap_a_subcommand_list_mid_name():
    env = dict(os.environ, PYTHONIOENCODING='utf-8', COLUMNS='60')
    for args in (['kd', '--help'], ['cd', '--help'], ['--help']):
        proc = subprocess.run([sys.executable, CLI] + args, cwd=ROOT,
                              capture_output=True, text=True, encoding='utf-8',
                              errors='replace', env=env, timeout=120)
        assert proc.returncode == 0, proc.stderr[-300:]
        assert_fits(proc.stdout.splitlines(), 60, 'help %r at 60 columns' % args)
        assert '<command>' in proc.stdout, proc.stdout[:400]


def test_every_leaf_help_fits_forty_columns():
    '''Every subcommand's own --help, at 40 columns -- with one exception.

    The prose must fit. argparse wraps it, but it wraps by character count,
    so a Chinese help string is measured at half its real width: the --json
    line added centrally said '打印完整结果信封（机器可读）' -- 14 characters,
    28 columns -- and the finished row came out 42 wide. English wraps
    correctly; nothing stopped the next Chinese one, hence walking every
    leaf rather than trusting one line to stay English.

    An indivisible option group does not have to fit, and no amount of
    layout fixes it: argparse cannot split '[--kingdraw-home KINGDRAW_HOME]'
    or '--route {smiles,molblock,cdxml,paste,objects}'. Measured at 40
    columns, doctor's usage needs 61 and cd draw's option column 47. Making
    those fit means renaming options, not reflowing text.

    'Indivisible' is defined narrowly on purpose: the line starts with the
    option itself ('--', '[' or '{') AND carries at most one space. An
    option followed by a run of spaces is option + help text, i.e. prose,
    and prose must fit.
    '''

    def indivisible(line):
        stripped = line.strip()
        if not stripped.startswith(('--', '[', '{')):
            return False
        return stripped.count(' ') <= 1

    env = dict(os.environ, PYTHONIOENCODING='utf-8', COLUMNS='40')
    parser = cli.build_parser()
    paths = [' '.join(leaf.prog.split()[1:]) for leaf in cli._leaf_parsers(parser)]
    assert len(paths) >= 20, paths
    prose = []
    for path in paths:
        proc = subprocess.run([sys.executable, CLI] + path.split() + ['--help'],
                              cwd=ROOT, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', env=env,
                              timeout=120)
        assert proc.returncode == 0, '%r -> %s' % (path, proc.stderr[-300:])
        for line in proc.stdout.splitlines():
            if width(line) > 40 and not indivisible(line):
                prose.append((path, width(line), line))
    assert not prose, 'help text wider than the terminal: %r' % (prose[:3],)


def test_no_human_line_is_wider_than_the_terminal_at_40():
    '''The whole human surface, at the width where it used to break.'''
    cases = [('doctor kd', lambda: cli._render(DOCTOR_KD)),
             ('doctor failing', lambda: cli._render(DOCTOR_FAILING)),
             ('identity', lambda: cli._render_identity(IDENTITY))]
    for label, call in cases:
        with columns(40):
            lines = call()
        assert_fits(lines, 40, label)


# Every shape a payload takes, because each one builds its lines differently.
WIDTH_PAYLOADS = {
    'ok': {'ok': True, 'channel': 'chemdraw', 'data': {'nodes': 7, 'bonds': 7},
           'elapsed_ms': 120},
    'text': {'ok': True, 'channel': 'kingdraw', 'data': {'text': 'C6H6O', 'chars': 5}},
    'scalar': {'ok': True, 'channel': 'kingdraw', 'data': True},
    'degraded': {'ok': True, 'channel': 'kingdraw', 'degraded': True,
                 'degrade_reason': 'every structure collection came back empty',
                 'data': {'nodes': 0},
                 'warnings': ['the document opened but nothing was drawn in it']},
    'evidence': {'ok': True, 'channel': 'chemdraw', 'data': {'nodes': 3},
                 'evidence': 'C',
                 'evidence_note': 'design inference, not yet verified'},
    'failure': {'ok': False, 'channel': 'chemdraw',
                'failure': {'code': 'E04', 'channel': 'chemdraw', 'stage': 'connect',
                            'message': 'the 32-bit and 64-bit runtimes cannot share '
                                       'one channel',
                            'hint': 'Re-run with the 64-bit python '
                                    '("python bin/cli.py ...")',
                            'detail': 'sys.maxsize=2147483647'}},
    'path': {'ok': True, 'channel': 'chemdraw',
             'data': {'written': 'C:/Users/someone/AppData/Local/Temp/deep/one/x.mol'}},
    'cjk': {'ok': True, 'channel': 'kingdraw',
            'data': {'note': '结构已写入，共 7 个原子'}},
}

WIDTHS = [32, 40, 50, 60, 72, 80, 100, 120]


def test_argparse_errors_stay_inside_the_terminal_at_every_width():
    '''The parser's own error path used to bypass the width budget entirely.

    Measured before this test existed: at COLUMNS=40 an invalid subcommand
    printed a 172-column line --

        chem-draw-tool kd: error: argument <command>: invalid choice: 'doctor'
        (choose from 'mol', 'smiles', 'formula', 'king', 'match', 'to3d', ...)

    -- while every renderer below it wrapped correctly. The gap was in the
    test set, not the renderer: the other width tests feed cli._render*
    payloads, so nothing ever exercised argparse's own output. Both streams
    are checked here, because this message goes to stderr.
    '''
    cases = [['kd', 'doctor'],
             ['cd', 'nope'],
             ['doctor', 'bogus-channel'],
             ['kd', 'save', 'C:/no/such/file.mol', '--bogus-flag']]
    for width in (32, 40, 60, 80, 120):
        env = dict(os.environ, PYTHONIOENCODING='utf-8', COLUMNS=str(width))
        for args in cases:
            proc = subprocess.run([sys.executable, CLI] + args, capture_output=True,
                                  text=True, encoding='utf-8', errors='replace',
                                  env=env, timeout=120)
            text = (proc.stdout or '') + (proc.stderr or '')
            for line in text.splitlines():
                got = cli._dwidth(line)
                assert got <= width, (
                    ' '.join(args) + ' at %d columns produced a %d-column line: %r'
                    % (width, got, line))
            assert 'error' in text.lower(), (
                'the message disappeared while it was being fitted: %r' % text[:200])


def test_no_rendered_line_ever_exceeds_the_width_it_was_given():
    '''The one promise a width budget makes. Measured before: at 32 columns
    the failure block's detail line came out 35 columns wide, because
    'sys.maxsize=2147483647' cannot be folded and was emitted whole.'''
    over = []
    for name, payload in WIDTH_PAYLOADS.items():
        for width in WIDTHS:
            for index, line in enumerate(cli._render_result(payload, width)):
                got = cli._dwidth(line)
                if got > width:
                    over.append('%s w=%d line %d is %d cols: %r'
                                % (name, width, index, got, line))
    assert not over, 'these lines spilled past the edge:\n  ' + '\n  '.join(over)


def test_a_key_that_does_not_fit_beside_its_label_gets_its_own_line():
    '''A 27-column InChIKey with an 11-column prefix needs 38. At 32 the old
    renderer split it after 21 columns, and a half-printed key is a wrong
    key -- the exact failure this renderer was written to stop.'''
    payload = {'input': 'CCO', 'canonical_smiles': 'CCO',
               'inchikey': 'LFQSCWFLJHTTHZ-UHFFFAOYSA-N', 'formula': 'C2H6O'}
    # _render_identity asks the terminal for its width, so the loop has to
    # set COLUMNS: passing a width argument here would test nothing.
    for width in (32, 40, 100):
        previous = os.environ.get('COLUMNS')
        os.environ['COLUMNS'] = str(width)
        try:
            text = '\n'.join(cli._render_identity(dict(payload)))
        finally:
            if previous is None:
                os.environ.pop('COLUMNS', None)
            else:
                os.environ['COLUMNS'] = previous
        assert 'LFQSCWFLJHTTHZ-UHFFFAOYSA-N' in text, (
            'the key was split at width %d:\n%s' % (width, text))
        if width == 32:
            assert '\n  LFQSCWFLJHTTHZ-UHFFFAOYSA-N' in text, (
                'at 32 the key should own the line below its label:\n' + text)


def test_a_one_value_answer_is_never_dropped():
    '''`kd match` answers with a bare boolean; the summary used to show nothing.

    Measured before the fix: `kd match 'CCO' 'c1ccccc1'` and `kd match 'CCO'
    'CCO'` printed byte-identical output -- 63 bytes each, rc=0 both, no
    difference a reader could see -- and the answer existed only under --json.
    The renderer walked dicts and strings and silently skipped everything else.
    '''
    base = {'ok': True, 'channel': 'kingdraw', 'failure': None,
            'degraded': False, 'evidence': 'A', 'warnings': []}
    yes = '\n'.join(cli._render_result(dict(base, data=True), 100, 'match'))
    no = '\n'.join(cli._render_result(dict(base, data=False), 100, 'match'))
    assert 'match' in yes and 'true' in yes, yes
    assert 'match' in no and 'false' in no, no
    assert yes != no, 'a match and a non-match must not print the same thing'
    # Numbers and the default label have to survive too.
    counted = '\n'.join(cli._render_result(dict(base, data=42), 100))
    assert '42' in counted, counted


def test_merged_json_capture_still_parses():
    '''`--json > out.json 2>&1` has to leave a file a parser can read.

    Merging both streams into one file is what a person types while debugging
    a failure, and it was broken for as long as --json also printed its warning
    memo to stderr: the file began with 'chem-draw-tool: 2 warnings: ...' and
    ended with the envelope. The memo now goes to stderr only while stdout is
    still a terminal, where it has a reader.
    '''
    import json
    proc = subprocess.run([sys.executable, CLI, 'doctor', 'cd', '--json'],
                          cwd=ROOT, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True,
                          encoding='utf-8', errors='replace', timeout=180)
    payload = json.loads(proc.stdout)
    assert 'channel' in payload, payload


def test_a_source_file_where_the_image_goes_is_named():
    '''The positional of `cd figure` is the output; a source file there is a mistake.

    It used to reach 'nothing was drawn ... pass a file instead of a string',
    which asked the reader to do what they had just done, and the source path
    was one SaveAs away from being overwritten. The check runs before the COM
    server opens, so it answers the same way on a machine without ChemDraw.
    '''
    folder = os.path.join(ROOT, 'test', 'out')
    os.makedirs(folder, exist_ok=True)
    source = os.path.join(folder, 'presentation_source.mol')
    with open(source, 'w', encoding='utf-8', newline='') as fh:
        fh.write('phenol\n  chemdraw-tool\n\n  2  1  0  0  0  0  0  0  0  0999 V2000\n')
    proc = subprocess.run([sys.executable, CLI, 'cd', 'figure', source,
                           '--out', os.path.join(folder, 'never_written.png')],
                          cwd=ROOT, capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=180)
    blob = (proc.stdout or '') + (proc.stderr or '')
    assert 'output image, not the input' in blob, blob[-500:]
    assert '--smiles' in blob, blob[-500:]
    assert os.path.isfile(source), 'the source file was consumed by the export'
    assert not os.path.isfile(os.path.join(folder, 'never_written.png'))
    # A path that only looks like a source file has to answer the same way. On
    # a fresh clone the file genuinely is not there, and a rule that demands
    # isfile sent it back to 'pass a file instead of a string'.
    absent = subprocess.run([sys.executable, CLI, 'cd', 'figure',
                             os.path.join(folder, 'typo_nowhere.mol'),
                             '--out', os.path.join(folder, 'never_written.png')],
                            cwd=ROOT, capture_output=True, text=True,
                            encoding='utf-8', errors='replace', timeout=180)
    absent_blob = (absent.stdout or '') + (absent.stderr or '')
    assert 'output image, not the input' in absent_blob, absent_blob[-400:]


def main() -> int:
    tests = [(name, fn) for name, fn in sorted(globals().items())
             if name.startswith('test_') and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print('FAIL %s\n     %s' % (name, str(exc)[:600]))
        except Exception as exc:  # noqa: BLE001 - report, keep going
            failed += 1
            print('ERROR %s: %s: %s' % (name, type(exc).__name__, exc))
        else:
            print('PASS %s' % name)
    print('-' * 60)
    print('%d passed, %d failed, %d total' % (len(tests) - failed, failed, len(tests)))
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
