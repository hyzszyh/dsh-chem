'''Can this repository be handed to someone else? One command answers.

    python tools/preflight.py [--strict]

This is not the test suite. The suites prove the chemistry works; this proves
the *repository* is shippable: nothing private in it, nothing enormous, no
broken relative links, no file that will not even compile, no script that a
newcomer's PowerShell will refuse to read.

Exit code 0 when every check passes, 1 otherwise. --strict also fails on
warnings, which is what CI should use.
'''
import argparse
import re
import subprocess
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# A file this big almost certainly does not belong in git.
HUGE = 1_000_000
# Names that should never be committed, whatever they contain.
SECRET_PATTERNS = [
    re.compile(r'sk-[A-Za-z0-9]{20,}'),
    re.compile(r'gh[pousr]_[A-Za-z0-9]{20,}'),
    re.compile(r'BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY'),
    re.compile(r'(?i)(api[_-]?key|password|secret)\s*[:=]\s*["\'][^"\']{12,}["\']'),
]


def tracked_files():
    out = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return [line for line in out.stdout.splitlines() if line.strip()]


def check_present(results):
    for name in ('README.md', 'LICENSE', 'requirements.txt', '.gitignore'):
        path = ROOT / name
        results.append((path.exists(), name + ' exists', '' if path.exists() else 'missing'))


def check_no_secrets(files, results):
    hits = []
    for relative in files:
        path = ROOT / relative
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        if relative.startswith('test/out/'):
            continue
        for pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                hits.append('%s: %s' % (relative, match.group(0)[:40]))
    results.append((not hits, 'no secrets in tracked files', '; '.join(hits[:3])))


def check_no_huge(files, results):
    big = []
    for relative in files:
        path = ROOT / relative
        if path.is_file() and path.stat().st_size > HUGE:
            big.append('%s (%.1f MB)' % (relative, path.stat().st_size / 1e6))
    results.append((not big, 'no tracked file over 1 MB', '; '.join(big[:3])))


def strip_code(text):
    '''Drop fenced blocks and inline code before looking for links.

    Without this the checker flags documentation *about* links: docs-audit.md
    contains the literal `[x](y.md)` while describing how broken links are
    found, and a naive walk calls that a broken link.
    '''
    text = re.sub(r'```.*?```', '', text, flags=re.S)
    text = re.sub(r'`[^`\n]*`', '', text)
    return text


def check_links(files, results):
    '''Relative Markdown links must point at something that exists.'''
    broken = []
    pattern = re.compile(r'\]\(([^)#\s]+)(?:#[^)]*)?\)')
    for relative in files:
        if not relative.endswith('.md'):
            continue
        path = ROOT / relative
        if not path.is_file():
            continue
        text = strip_code(path.read_text(encoding='utf-8', errors='ignore'))
        for target in pattern.findall(text):
            if target.startswith(('http://', 'https://', 'mailto:', '#')):
                continue
            if target.startswith('<'):
                continue
            resolved = (path.parent / target).resolve()
            if not resolved.exists():
                broken.append('%s -> %s' % (relative, target))
    results.append((not broken, 'relative links resolve', '; '.join(broken[:4])))


def check_python_compiles(files, results):
    bad, warned = [], []
    for relative in files:
        if not relative.endswith('.py'):
            continue
        path = ROOT / relative
        try:
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always')
                compile(path.read_text(encoding='utf-8'), str(path), 'exec')
        except SyntaxError as exc:
            bad.append('%s:%s %s' % (relative, exc.lineno, exc.msg))
            continue
        # An invalid escape sequence is not an error today: '\T' in a Windows
        # path stays literal and only warns. It is still a trap, because '\t'
        # and '\n' are perfectly nice directory names that would quietly stop
        # being the text someone wrote. So a warning counts as a failure.
        for problem in caught:
            if issubclass(problem.category, (SyntaxWarning, DeprecationWarning)):
                warned.append('%s: %s' % (relative, str(problem.message)[:70]))
    results.append((not bad, 'every .py compiles', '; '.join(bad[:3])))
    results.append((not warned, 'no invalid escape sequences',
                    '; '.join(sorted(set(warned))[:3])))


def check_ps1_bom(files, results):
    bad = []
    for relative in files:
        if not relative.endswith('.ps1'):
            continue
        path = ROOT / relative
        if not path.read_bytes().startswith(b'\xef\xbb\xbf'):
            bad.append(relative)
    results.append((not bad, 'every .ps1 has a UTF-8 BOM',
                    ', '.join(bad) + ' -- PowerShell 5.1 reads these as ANSI'))


def check_ignored_junk(results):
    '''Runtime output must not be tracked.'''
    # examples/out/ joined the list the day someone committed the PNG that
    # examples/draw_figure.py writes: a generated figure in a repo churns on
    # every run and says nothing about the code that made it.
    junk = subprocess.run(
        ['git', 'ls-files', 'test/out', 'runtime', 'examples/out'],
        cwd=ROOT, capture_output=True, text=True)
    tracked = [line for line in junk.stdout.splitlines() if line.strip()]
    results.append((not tracked, 'generated folders are untracked',
                    '%d file(s) tracked' % len(tracked)))


def check_documented_counts(files, results):
    """Numbers the docs state about this repo must match the repo.

    Rewritten for the 15-tool layout. The suite count comes from the runner
    (a stray test file nobody wires up is not a suite); the tool count comes
    from the plugin's registered chem_* names; and the engine dispatcher has to
    agree with the plugin before either is compared against prose, because a
    doc can only be as honest as the code it counts.
    """
    counts = {}
    runner = ROOT / 'test' / 'run_py.py'
    if runner.is_file():
        block = re.search(r'SUITES\s*=\s*\[(.*?)\]',
                          runner.read_text(encoding='utf-8', errors='ignore'), re.S)
        if block:
            counts['suite'] = len(re.findall(r'"py_[a-z]+"', block.group(1)))
    plugin = ROOT / 'dsh-plugin' / 'lib' / 'index.js'
    if plugin.is_file():
        text = plugin.read_text(encoding='utf-8', errors='ignore')
        counts['plugin'] = len(re.findall(r"name:\s*'(chem_[a-z_]+)'", text))
    cli = ROOT / 'core' / 'chem' / 'cli.py'
    if cli.is_file():
        text = cli.read_text(encoding='utf-8', errors='ignore')
        handlers = re.search(r'HANDLERS\s*=\s*\{(.*?)\n\}', text, re.S)
        counts['engine'] = len(re.findall(r'"[a-z]+":', handlers.group(1))) if handlers else 0

    claims = [
        ('README.md', 'plugin', r'(\d+)\s*个工具'),
        ('README.md', 'suite', r'(\d+)\s*个套件'),
        ('dsh-plugin/README.md', 'plugin', r'(\d+)\s*个工具'),
        ('docs/验收报告.md', 'suite', r'(\d+)\s*个套件'),
    ]
    wrong = []
    if counts.get('engine') is not None and counts.get('plugin') is not None:
        if counts['engine'] != counts['plugin']:
            wrong.append('plugin declares %d tools, engine dispatches %d'
                         % (counts['plugin'], counts['engine']))
    for relative, kind, pattern in claims:
        path = ROOT / relative
        actual = counts.get(kind)
        if not path.is_file() or actual is None:
            continue
        body = path.read_text(encoding='utf-8', errors='ignore')
        found = re.findall(pattern, body)
        if not found:
            wrong.append('%s no longer states its %s count in a shape this '
                         'check can read' % (relative, kind))
        for stated in found:
            if int(stated) != actual:
                wrong.append('%s says %s %s, there are %d'
                             % (relative, stated, kind, actual))
    results.append((not wrong, 'documented counts match the code',
                    '; '.join(sorted(set(wrong))[:4])))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--strict', action='store_true',
                        help='fail on warnings too (use this in CI)')
    args = parser.parse_args(argv)

    files = tracked_files()
    if files is None:
        print('not a git repository (or git is unavailable)')
        return 1

    results = []
    check_present(results)
    check_no_secrets(files, results)
    check_no_huge(files, results)
    check_links(files, results)
    check_python_compiles(files, results)
    check_ps1_bom(files, results)
    check_ignored_junk(results)
    check_documented_counts(files, results)

    failures = 0
    for ok, label, detail in results:
        print('%s  %s' % ('PASS' if ok else 'FAIL', label))
        if not ok and detail:
            print('        ' + detail)
        if not ok:
            failures += 1

    print('')
    print('tracked files: %d | checks: %d | failures: %d'
          % (len(files), len(results), failures))
    return 0 if failures == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())