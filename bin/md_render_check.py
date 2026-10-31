'''Render-time audit for the Markdown in this repo.

Why a script instead of eyeballing: four of the six things that make a page
unreadable on GitHub are mechanical. A table wider than ~100 columns scrolls
sideways on a phone, a code line over ~90 characters gets a scrollbar that
poisons copy-paste, a heading that jumps from # to ### breaks the outline, and
a relative link whose text disagrees with its target misleads a reader who is
copying paths. All of it is countable.

Width is measured the way a renderer lays it out: a CJK / fullwidth character
counts 2 columns, everything else 1, and a table row costs the sum of its
column widths plus 3 columns of cell padding and pipes per column.

Usage:
    python bin/md_render_check.py                 # the whole repo
    python bin/md_render_check.py README.md docs  # just these paths
    python bin/md_render_check.py --json          # machine readable
    python bin/md_render_check.py --min-table 100 --max-code 90

Exit code is 0 when nothing is over its budget, 1 otherwise, so a CI step or
a shell gate can use it directly.
'''

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BT = chr(96)
FENCE = re.compile(r'^\s*' + BT * 3 + r'(.*)$')
HEAD = re.compile(r'^(#{1,6})\s+(\S.*)$')
LINK = re.compile(r'(!?)\[([^\]]*)\]\(([^)\s]+)(?:\s+"[^"]*")?\)')
SEPARATOR = re.compile(r'^:?-{2,}:?$')
SKIP_DIRS = {'.git', 'runtime', '.agent-teams', '__pycache__', 'node_modules'}
SKIP_PREFIX = (os.path.join('test', 'out'),)


def display_width(text: str) -> int:
    '''Columns this text occupies: wide glyphs count 2.'''
    return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1
               for ch in text)


def strip_inline(text: str) -> str:
    '''Width of the rendered text, not of its Markdown source.'''
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = text.replace(BT, '').replace('**', '').replace('__', '')
    return text.strip()


def markdown_files(paths) -> list:
    found = []
    for path in paths:
        full = path if os.path.isabs(path) else os.path.join(ROOT, path)
        if os.path.isfile(full) and full.endswith('.md'):
            found.append(full)
            continue
        for dirpath, dirnames, filenames in os.walk(full):
            rel = os.path.relpath(dirpath, ROOT)
            dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
            if rel.startswith(SKIP_PREFIX):
                continue
            found.extend(os.path.join(dirpath, name) for name in sorted(filenames)
                         if name.endswith('.md'))
    return sorted(set(found))


def split_cells(row: str) -> list:
    # Split on the pipes that really delimit cells: a backslash-escaped pipe
    # (as written inside GFM code spans) belongs to the cell, not the table.
    # Counted naively it turns a 4-column row into 5 cells and every width
    # downstream is wrong.
    body = row.strip()
    if body.startswith('|'):
        body = body[1:]
    if body.endswith('|') and not body.endswith('\\|'):
        body = body[:-1]
    cells, current, index = [], '', 0
    while index < len(body):
        if body[index] == '\\' and index + 1 < len(body) and body[index + 1] == '|':
            current += '|'
            index += 2
            continue
        if body[index] == '|':
            cells.append(current)
            current = ''
            index += 1
            continue
        current += body[index]
        index += 1
    cells.append(current)
    return [cell.strip() for cell in cells]

def table_widths(rows) -> tuple:
    '''(rendered width, column widths, body row count) for one Markdown table.'''
    cells = []
    for row in rows:
        parts = [strip_inline(c) for c in split_cells(row)]
        if all(SEPARATOR.match(part.replace(' ', '')) for part in parts if part):
            continue
        cells.append(parts)
    if not cells:
        return 0, [], 0
    columns = max(len(row) for row in cells)
    widths = [max((display_width(row[i]) if i < len(row) else 0) for row in cells)
              for i in range(columns)]
    return sum(widths) + 3 * columns + 1, widths, len(cells) - 1


def audit_file(path: str, min_table: int, max_code: int) -> dict:
    rel = os.path.relpath(path, ROOT).replace(os.sep, '/')
    with open(path, encoding='utf-8') as handle:
        lines = handle.read().splitlines()
    findings = {'tables': [], 'code': [], 'headings': [], 'links': [], 'images': []}
    infence = False
    fence_lang = ''
    fence_exempt = False
    previous_level = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = FENCE.match(line)
        if fence:
            infence = not infence
            fence_lang = (fence.group(1) or '').strip()
            # A block that quotes real program output cannot be wrapped:
            # folding it would edit the evidence. Marking the fence 'nowrap'
            # records that decision instead of leaving a permanent red line
            # nobody reads.
            fence_exempt = 'nowrap' in fence_lang or 'keep' in fence_lang
            index += 1
            continue
        if infence:
            if not fence_exempt and len(line) > max_code:
                findings['code'].append({'line': index + 1, 'length': len(line),
                                         'lang': fence_lang, 'text': line.strip()})
            index += 1
            continue
        if line.lstrip().startswith('|'):
            start = index
            rows = []
            while index < len(lines) and lines[index].lstrip().startswith('|'):
                rows.append(lines[index])
                index += 1
            width, columns, body = table_widths(rows)
            # A reference table (a catalogue, a matrix) can be legitimately
            # wide. Letting the author record that decision beats leaving a
            # permanent red line that everybody learns to ignore.
            exempt = any('wide-table-ok' in lines[k]
                         for k in range(max(0, start - 2), start))
            if width > min_table and not exempt:
                findings['tables'].append({'line': start + 1, 'width': width,
                                           'columns': columns, 'rows': body,
                                           'header': rows[0].strip()[:120]})
            continue
        heading = HEAD.match(line)
        if heading:
            level = len(heading.group(1))
            if previous_level and level > previous_level + 1:
                findings['headings'].append({'line': index + 1, 'from': previous_level,
                                             'to': level,
                                             'text': heading.group(2)[:70]})
            previous_level = level
        for bang, text, target in LINK.findall(line):
            if target.startswith(('http://', 'https://', 'mailto:', '#')):
                continue
            local = target.split('#')[0]
            if not local:
                continue
            resolved = os.path.normpath(os.path.join(os.path.dirname(path), local))
            entry = {'line': index + 1, 'text': text, 'target': target,
                     'exists': os.path.exists(resolved)}
            if bang == '!':
                # An image that loads is the normal case; only a broken
                # reference is worth reporting.
                if not entry['exists']:
                    findings['images'].append(entry)
            else:
                looks_like_file = text.strip().lower().endswith(
                    ('.md', '.py', '.json', '.png', '.ps1', '.txt'))
                if looks_like_file and os.path.basename(text.strip().lower()) != \
                        os.path.basename(target.lower()):
                    entry['reason'] = 'link text names a different file'
                    findings['links'].append(entry)
        index += 1
    return {'file': rel, 'lines': len(lines), 'findings': findings}


def summarise(report: dict, min_table: int, max_code: int) -> int:
    total = 0
    for entry in report['files']:
        findings = entry['findings']
        if not any(findings.values()):
            continue
        print('### %s' % entry['file'])
        for item in findings['tables']:
            total += 1
            print('  table  line %-4d width %-4d cols %-2d rows %-2d  %s'
                  % (item['line'], item['width'], len(item['columns']),
                     item['rows'], item['header']))
        for item in findings['code']:
            total += 1
            print('  code   line %-4d len %-4d [%s]  %s'
                  % (item['line'], item['length'], item['lang'], item['text'][:96]))
        for item in findings['headings']:
            total += 1
            print('  head   line %-4d h%d -> h%d  %s'
                  % (item['line'], item['from'], item['to'], item['text']))
        for item in findings['links']:
            total += 1
            print('  link   line %-4d %-24s -> %-28s exists=%s %s'
                  % (item['line'], item['text'][:24], item['target'][:28],
                     item['exists'], item.get('reason', '')))
        for item in findings['images']:
            total += 1
            print('  image  line %-4d %-24s -> %-28s exists=%s'
                  % (item['line'], item['text'][:24], item['target'][:28],
                     item['exists']))
        print()
    print('%d finding(s); table budget %d columns, code budget %d characters'
          % (total, min_table, max_code))
    return 0 if total == 0 else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Markdown render audit')
    parser.add_argument('paths', nargs='*', help='files or directories')
    parser.add_argument('--min-table', type=int, default=100,
                        help='flag tables wider than this (default 100)')
    parser.add_argument('--max-code', type=int, default=90,
                        help='flag code lines longer than this (default 90)')
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)

    targets = args.paths or ['.']
    files = markdown_files(targets)
    report = {'root': ROOT, 'files': [audit_file(path, args.min_table,
                                                  args.max_code) for path in files],
              'budgets': {'table': args.min_table, 'code': args.max_code}}
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        flagged = sum(1 for entry in report['files'] if any(entry['findings'].values()))
        return 0 if flagged == 0 else 1
    return summarise(report, args.min_table, args.max_code)


if __name__ == '__main__':
    raise SystemExit(main())