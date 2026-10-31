'''Presentation probe: how the CLI actually looks in a terminal.

Not a unit test -- it runs real commands at fixed COLUMNS values, measures every
output line by *display width* (CJK and fullwidth characters count two columns),
and reports the lines a terminal would wrap, plus the table rows whose columns
do not line up.

    python test/presentation_probe.py            # human report
    python test/presentation_probe.py --json     # machine record

The point is that "looks fine" is not measurable by eye: a CJK character is one
character but two columns, and Python's %-Ns pads by characters.
'''

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CLI = os.path.join(ROOT, 'bin', 'cli.py')
PY64 = sys.executable
PY32 = os.path.join(ROOT, 'runtime', 'py32', 'python.exe')
PY = PY32 if os.path.exists(PY32) else 'python'   # kingdraw needs 32-bit


def char_width(ch: str) -> int:
    '''Columns one character occupies: 2 for CJK/fullwidth, 0 for combining.'''
    if unicodedata.combining(ch):
        return 0
    if unicodedata.category(ch) in ('Mn', 'Me', 'Cf', 'Cc'):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


def display_width(text: str) -> int:
    return sum(char_width(ch) for ch in text)


# Commands that a first-time user is told to run, kept as small as possible so
# the probe stays fast; each one is a real invocation, not a mock.
# kind says who the reader is: 'human' output must fit the terminal, 'json' is
# machine output the terminal is allowed to wrap (it must stay parseable),
# 'error' means JSON on stdout plus a human memo on stderr.
CASES = [
    ('doctor kd (table)', 'human', [PY, CLI, 'doctor', 'kd'], {}),
    ('doctor cd (table)', 'human', [PY64, CLI, 'doctor', 'cd'], {}),
    ('crosscheck (table)', 'human', [PY64, CLI, 'crosscheck',
                                     'CC(=O)Oc1ccccc1C(=O)O'], {}),
    ('crosscheck two smiles', 'human', [PY64, CLI, 'crosscheck', 'c1ccccc1O',
                                        '--compare-to', 'Oc1ccccc1'], {}),
    ('failure: bad smiles', 'error', [PY64, CLI, 'cd', 'draw', 'C1CC('], {}),
    ('failure: no page to export', 'error', [PY64, CLI, 'cd', 'export',
                                             'D:/tmp/probe.png'], {}),
    ('failure: missing molfile', 'error', [PY32, CLI, 'kd', 'smiles',
                                           'D:/tmp/does-not-exist.mol'], {}),
    ('kingdraw formula (json)', 'json', [PY32, CLI, 'kd', 'formula',
                                         '--smiles', 'c1ccccc1O'], {}),
    ('identity (json)', 'json', [PY64, CLI, 'identity',
                                 'CC(=O)Oc1ccccc1C(=O)O'], {}),
    ('help', 'human', [PY64, CLI, '--help'], {}),
]

WIDTHS = [40, 60, 80, 120]


def run_case(cmd, columns: int, env_extra=None):
    env = dict(os.environ)
    env['COLUMNS'] = str(columns)
    env['PYTHONIOENCODING'] = 'utf-8'
    if env_extra:
        env.update(env_extra)
    try:
        proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=180,
                              env=env)
    except Exception as exc:
        return {'cmd': cmd, 'columns': columns, 'error': '%s: %s'
                % (type(exc).__name__, exc), 'lines': [], 'rc': None}
    text = proc.stdout.decode('utf-8', 'replace')
    err = proc.stderr.decode('utf-8', 'replace')
    return {'cmd': cmd, 'columns': columns, 'rc': proc.returncode,
            'stdout': text, 'stderr': err,
            'lines': text.splitlines()}


def overwide(lines, columns):
    return [(i + 1, display_width(line), line)
            for i, line in enumerate(lines) if display_width(line) > columns]


def column_drift(lines):
    '''Rows of a whitespace table whose columns stop lining up.

    A table row is "drifting" when an earlier row in the same block put a token
    at a column that this row cannot reach, which is exactly what happens when a
    %-Ns cell contains a CJK character (len 1, width 2) or a value longer than
    the field.
    '''
    findings = []
    block = []
    for index, line in enumerate(lines, 1):
        # JSON blocks are not tables: quoting and punctuation make token columns
        # meaningless, so only plain whitespace tables are inspected.
        if not line.strip() or '"' in line or '{' in line or '}' in line:
            block = []
            continue
        block.append((index, line))
        if len(block) < 3:
            continue
        # token start columns of the last three lines, ignoring single-token lines
        starts = []
        for _, text in block[-3:]:
            starts.append([m.start() for m in re.finditer(r'\S+', text)])
        if len({len(s) for s in starts}) != 1:
            continue
        for column in range(len(starts[0])):
            here = [s[column] for s in starts]
            if len(set(here)) != 1:
                findings.append({'line': block[-1][0], 'text': block[-1][1],
                                 'expected_columns': here})
                break
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='measure CLI output width')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--columns', default=None,
                        help='only run this width (default: 40,60,80,120)')
    args = parser.parse_args(argv)
    widths = [int(args.columns)] if args.columns else WIDTHS

    # Commands that start ChemDraw cost a few seconds each, so they are probed at
    # the two widths that matter (a narrow terminal and a normal one).
    slow = ('doctor cd', 'crosscheck', 'failure')

    record = []
    for name, kind, cmd, extra in CASES:
        wanted = [w for w in widths if not (name.startswith(slow) and w not in (40, 80))]
        for columns in wanted:
            got = run_case(cmd, columns, extra)
            got['name'] = name
            got['kind'] = kind
            got['overwide'] = overwide(got.get('lines') or [], columns)
            got['drift'] = column_drift(got.get('lines') or [])
            # A human block must fit; our own stderr memo must too. Vendor noise
            # (rdkit parse complaints) is not ours to lay out, so only lines
            # carrying the tool's prefix are measured.
            memo = (got.get('stderr') or '') if kind == 'error' else ''
            memo_lines = [line for line in memo.splitlines()
                          if line.startswith('chem-draw-tool:')
                          or line.startswith('  ')]
            got['memo_overwide'] = overwide(memo_lines, columns)
            record.append(got)

    if args.json:
        slim = [{k: v for k, v in r.items() if k not in ('cmd',)} for r in record]
        print(json.dumps(slim, ensure_ascii=False, indent=1))
    else:
        human_problems = 0
        json_wide = 0
        for got in record:
            kind = got.get('kind')
            over = got['overwide']
            memo_over = got.get('memo_overwide') or []
            if kind == 'human':
                human_problems += len(over) + len(got['drift'])
            elif kind == 'error':
                human_problems += len(got['drift']) + len(memo_over)
            else:
                json_wide += len(over)
            print('%-28s COLUMNS=%-3d rc=%s  kind=%-5s overwide=%d drift=%d memo=%d'
                  % (got['name'], got['columns'], got.get('rc'), kind,
                     len(over), len(got['drift']), len(memo_over)))
            for line_no, width, text in over[:4]:
                print('    wide line %-3d %-3d %s' % (line_no, width, text[:88]))
            for item in got['drift'][:3]:
                print('    drift line %-3d %s' % (item['line'], item['text'][:80]))
            for line_no, width, text in memo_over[:3]:
                print('    memo wide %-3d %-3d %s' % (line_no, width, text[:80]))
        print('')
        print('human-surface problems: %d   (json lines wider than the terminal: %d,'
              ' machine output, reported for information)' % (human_problems, json_wide))
    return 0


if __name__ == '__main__':
    sys.exit(main())
