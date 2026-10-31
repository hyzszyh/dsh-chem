'''Command line entry point: python bin/cli.py <command> ...'''

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import unicodedata

from . import identity
from .doctor import cd as cd_doctor, kd as kd_doctor
from .models import ErrorCode, EVIDENCE_MEASURED, Failure, Result, as_envelope


# -- presentation ----------------------------------------------------------
# Three things make a column layout lie: characters that occupy two columns
# (CJK, fullwidth forms), values whose length is not ours to choose (paths,
# SMILES, vendor error text) and terminals of unknown width. Python's %-Ns pads
# by len(), which counts an ideograph as one column, so every later column moves
# left by one per such character. Everything below measures display width, and
# every table falls back to a stacked layout when the aligned one would not fit
# the terminal.

LABEL_WIDTH = 9          # 'canonical' / 'available' are the longest labels
MEMO_PREFIX = 'chem-draw-tool:'
CLIP = 400               # display columns kept from a failure detail


def _char_width(ch: str) -> int:
    if unicodedata.combining(ch) or unicodedata.category(ch) in ('Mn', 'Me', 'Cf'):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


def _dwidth(text) -> int:
    '''Display columns, not characters: an ideograph occupies two.'''
    return sum(_char_width(ch) for ch in str(text))


def _pad(text, width: int) -> str:
    text = str(text)
    return text + ' ' * max(0, width - _dwidth(text))


def _term_width(floor: int = 32, ceiling: int = 200) -> int:
    raw = os.environ.get('COLUMNS', '')
    try:
        width = (int(raw) if raw.strip()
                 else shutil.get_terminal_size((80, 24)).columns)
    except (TypeError, ValueError):
        width = 80
    return max(floor, min(int(width), ceiling))


def _cell(value) -> str:
    '''One spelling for every empty or boolean cell: - / true / false.

    Before this, the tables printed '-', 'n/a' and 'None for the same idea
    depending on which branch built the row, which reads as a missing cell.
    '''
    if value is None or value == '':
        return '-'
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def _clip(text, limit: int = CLIP) -> str:
    '''Cut by display columns on a word boundary, and say that it was cut.'''
    text = ' '.join(str(text).split())
    if _dwidth(text) <= limit:
        return text
    kept, width = [], 0
    for word in text.split():
        if width + _dwidth(word) + (1 if kept else 0) > limit - 1:
            break
        kept.append(word)
        width += _dwidth(word) + (1 if len(kept) > 1 else 0)
    return (' '.join(kept) if kept else text[:limit]) + ' …'


def _shorten_path(path, budget: int) -> str:
    '''Middle-elide a path so it fits; the untruncated path stays in --json.'''
    path = str(path)
    budget = max(8, budget)
    if _dwidth(path) <= budget:
        return path
    head = path[:6]
    keep = budget - _dwidth(head) - 1
    return head + '…' + (path[-keep:] if keep > 3 else '')


def _split_display(text, budget: int):
    '''Cut after at most `budget` display columns; the head is never empty.'''
    budget = max(1, budget)
    seen = 0
    for index, char in enumerate(text):
        step = _dwidth(char)
        if index and seen + step > budget:
            return text[:index], text[index:]
        seen += step
    return text, ''


def _wrap(text, width: int, first: str = '', rest: str = '') -> list:
    '''Wrap prose to the terminal width, never splitting a word.

    A single word wider than the line is normally a Windows path; that one is
    shortened instead of folded, because a path cut mid-segment is noise while
    a shortened one still says where the file went.
    '''
    words = str(text).split()
    if not words:
        return [first.rstrip()] if first.strip() else []
    # Shorten a path word here if it cannot fit on any line, wherever it
    # lands. Only shortening the first word (as this did) left
    # 'Run with C:\Users\...\python.exe' folded mid-segment as soon as the
    # path was not first on the line -- the exact thing this docstring says
    # must not happen. Measured at 40 columns: AppData\L / ocal\Programs\...
    tightest = width - min(_dwidth(first), _dwidth(rest))
    for index, word in enumerate(words):
        if (os.sep in word or '/' in word) and _dwidth(word) > tightest:
            words[index] = _shorten_path(word, width - _dwidth(rest))
    lines, prefix, current = [], first, ''
    for word in words:
        if (not current and _dwidth(prefix) + _dwidth(word) > width
                and (os.sep in word or '/' in word)):
            word = _shorten_path(word, width - _dwidth(prefix))
        probe = (current + ' ' + word) if current else word
        if current and _dwidth(prefix) + _dwidth(probe) > width:
            lines.append((prefix + current).rstrip())
            prefix, current = rest, word
        else:
            current = probe
        # Last resort, measured at 32 columns: 'sys.maxsize=2147483647' is 20
        # columns wide and the '│ detail : ' prefix is 13, so the pair cannot
        # fit. Emitting it whole spilled past the edge -- the one thing a
        # width budget promises not to do. Split it and keep the continuation
        # under the same indent, so nothing is lost and nothing overflows.
        budget = width - _dwidth(prefix)
        while _dwidth(current) > budget:
            head, current = _split_display(current, budget)
            lines.append((prefix + head).rstrip())
            prefix = rest
            budget = width - _dwidth(prefix)
    lines.append((prefix + current).rstrip())
    return lines


def _labelled(label, value, width: int, label_width: int = LABEL_WIDTH,
              indent: str = '') -> list:
    '''label: value, wrapped under the value column.

    A path is never wrapped: 'C:\\Program Files\\...' split at its space is a
    broken path that a user pastes into a shell. It is shortened instead, and
    the full value stays in --json.
    '''
    prefix = indent + _pad(label, label_width) + ': '
    text = _cell(value)
    room = width - _dwidth(prefix)

    def stacked():
        lines = [indent + label + ':']
        lines.extend(_wrap(text, width, first=indent + '  ', rest=indent + '  '))
        return lines

    if os.sep in text or '/' in text:
        # A path is shortened, never folded; it stays on one line beside its
        # label as long as there is any room left beside it.
        return [prefix + _shorten_path(text, room)] if room >= 8 else stacked()
    # An InChIKey is 27 columns and must stay whole: a key split over two
    # lines is a key someone copies wrong, which is the reason this renderer
    # exists at all. 'inchikey : ' is 11 columns, so at 32 there are 21 left
    # -- one column short of the key. Give it the next line instead.
    if room < _dwidth(text) and ' ' not in text and _dwidth(text) < width:
        return stacked()
    return _wrap(text, width, first=prefix, rest=' ' * _dwidth(prefix))


def _table(header, rows, width: int, gap: str = '  '):
    '''An aligned table measured in display columns; None if it cannot fit.'''
    rows = [list(row) for row in rows]
    if not rows:
        return []
    widths = []
    for index, title in enumerate(header):
        cells = [_dwidth(_cell(row[index])) for row in rows]
        widths.append(max([_dwidth(title or '')] + cells))
    if sum(widths) + _dwidth(gap) * (len(widths) - 1) > width:
        return None

    def row(cells):
        return gap.join(_pad(_cell(cell), size)
                        for cell, size in zip(cells, widths)).rstrip()

    lines = [row([title or '' for title in header]),
             gap.join('-' * size for size in widths)]
    lines.extend(row(cells) for cells in rows)
    return lines


_SHORT_LABEL = {'inchikey': 'key', 'smiles / detail': 'smiles',
                'evidence': 'evid'}


def _stacked(header, rows, width: int, indent: str = '  ') -> list:
    '''One record per block, one field per line: what a narrow terminal gets.

    Labels are shortened ('inchikey' -> 'key') and the label column is sized to
    the longest of them, so an InChIKey (27 columns) still fits a 40-column
    terminal on one line instead of being broken in two.
    '''
    labels = [_SHORT_LABEL.get(title, title) for title in header[1:]]
    label_width = max([len(label) for label in labels] or [1])
    lines = []
    for cells in rows:
        cells = list(cells)
        lines.append((indent + _cell(cells[0])).rstrip())
        for label, value in zip(labels, cells[1:]):
            lines.extend(_labelled(label, value, width, label_width,
                                   indent + '  '))
        lines.append('')
    return lines[:-1] if lines else lines


def _render_failure(failure: dict, width: int, indent: str = '') -> list:
    '''[code] message, then fix / detail / stage under a guide bar.

    The bar separates the failure itself from the advice under it: with plain
    indentation those lines read as more of the same sentence.
    '''
    failure = failure or {}
    head = '[%s] %s' % (failure.get('code') or 'E99',
                       failure.get('message') or 'the call failed')
    lines = _wrap(head, width, first=indent, rest=indent + '  ')
    bar = indent + '  │ '
    label_width = 7
    for label, key in (('fix', 'hint'), ('detail', 'detail'), ('stage', 'stage')):
        value = failure.get(key)
        if not value:
            continue
        prefix = bar + _pad(label, label_width) + ': '
        rest = ' ' * (_dwidth(bar) + label_width + 2)
        if width - _dwidth(prefix) < 20:
            # A 13-column prefix leaves 19 at 32 columns, and a value column
            # that thin cannot hold an InChIKey or a version string. Put the
            # label above its value instead of squeezing both onto one line.
            lines.extend(_wrap(_clip(value), width, first=bar + label + ':',
                               rest=bar + '  '))
            continue
        lines.extend(_wrap(_clip(value), width, first=prefix, rest=rest))
    return lines


def _render_memo(payload: dict, width: int) -> list:
    '''A short human note for stderr.

    stdout stays the machine record (JSON, unchanged, so scripts and the MCP
    layer keep parsing it); the things a person must not miss -- a failure, a
    degraded product, an evidence level below A, a preview-level picture -- also
    get a sentence on stderr so they are on the same screen instead of twelve
    lines down the envelope.
    '''
    if not isinstance(payload, dict):
        return []
    lines = []
    failure = payload.get('failure') or {}
    if payload.get('ok') is False or failure:
        head = ('%s FAILED [%s] %s' % (MEMO_PREFIX,
                                       failure.get('code') or 'E99',
                                       failure.get('message') or 'the call failed'))
        lines.extend(_wrap(head, width, rest='    '))
        if failure.get('hint'):
            lines.extend(_labelled('fix', _clip(failure['hint']), width, 6, '  '))
        if failure.get('detail'):
            lines.extend(_labelled('detail', _clip(failure['detail']), width, 6,
                                   '  '))
    if payload.get('degraded'):
        head = MEMO_PREFIX + ' NOTICE: degraded result'
        reason = payload.get('degrade_reason')
        if reason:
            head += ' — ' + str(reason)
        lines.extend(_wrap(head, width, rest='    '))
    evidence = payload.get('evidence')
    if evidence and evidence != 'A':
        note = payload.get('evidence_note') or ''
        head = '%s evidence level %s%s' % (MEMO_PREFIX, evidence,
                                          (' — ' + str(note)) if note else '')
        lines.extend(_wrap(head, width, rest='    '))
    warnings = payload.get('warnings') or []
    if warnings:
        head = '%s %d warning%s: %s' % (MEMO_PREFIX, len(warnings),
                                        '' if len(warnings) == 1 else 's',
                                        _clip(warnings[0], 200))
        lines.extend(_wrap(head, width, rest='    '))
        if len(warnings) > 1:
            lines.extend(_wrap('%s (all %d are in the JSON above)'
                               % (MEMO_PREFIX, len(warnings)), width, rest='    '))
    return lines


def _emit(payload, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for line in _render(payload):
            print(line)
    return 0 if payload.get('available', payload.get('ok', False)) else 1


def _base_value(payload: dict, key: str) -> str:
    '''Three states must be readable at a glance: absent / unknown / a value.

    'version' comes back empty on this ChemDraw build (Application.Name is an
    empty string) and the doctor never fills 'home', while the executable lives
    in details.fullname. Printing '-' for both read as "not installed", so an
    empty field now says 'unknown' and 'home' points at the real path.
    '''
    value = payload.get(key)
    if key == 'home':
        if value:
            return _cell(value)
        fullname = (payload.get('details') or {}).get('fullname')
        return fullname or 'unknown'
    if key == 'version' and not value:
        return 'unknown'
    return _cell(value)


def _render(payload: dict) -> list:
    '''The human form of a doctor report.'''
    width = _term_width()
    lines = []
    for label, key in (('channel', 'channel'), ('available', 'available'),
                       ('version', 'version'), ('home', 'home')):
        lines.extend(_labelled(label, _base_value(payload, key), width))
    caps = payload.get('capabilities') or []
    if caps:
        header = ['action', 'route', 'ok', 'evidence']
        rows = [[_cell(c.get('action')), _cell(c.get('route')),
                 _cell(c.get('available')), _cell(c.get('evidence'))]
                for c in caps]
        lines.append('')
        table = _table(header, rows, width)
        lines.extend(table if table is not None else _stacked(header, rows, width))
    fails = payload.get('failures') or []
    if fails:
        lines.append('')
        for failure in fails:
            lines.extend(_render_failure(failure, width))
    return lines


def _render_identity(payload: dict) -> list:
    '''The human form of an identity answer: one short line per field.

    Before this, "identity" printed the whole JSON envelope, so a 40-column
    terminal cut the InChIKey and the canonical SMILES in half: a copied
    "BSYNRYMUTXBXSQ-UHFFFAOYSA" is a wrong key with no sign that it was cut.
    '''
    width = _term_width()
    lines = []
    for label, key in (('input', 'input'), ('canonical', 'canonical_smiles'),
                       ('inchikey', 'inchikey'), ('formula', 'formula')):
        lines.extend(_labelled(label, payload.get(key), width))
    note = payload.get('note')
    evidence = payload.get('evidence')
    if note:
        lines.extend(_labelled('note', note, width))
    if evidence and evidence != 'A':
        lines.extend(_labelled('evidence', '%s (not a measured identity)'
                               % evidence, width))
    return lines


def _doctor_body(payloads):
    '''The --json shape: one channel is one object, several are an array.

    Measured: 'doctor --json' printed one document per channel back to back,
    so json.loads() answered 'Extra data' and no script could read it. Keeping
    the single-channel case an object means the existing 'doctor cd --json'
    consumers, including this repo's own tests, did not have to change.
    '''
    return payloads[0] if len(payloads) == 1 else payloads


def _doctor_status(payloads, strict: bool = False):
    '''0 when at least one requested channel can be used on this machine.

    Measured on this installation: 'doctor' exited 1 under both interpreters --
    the 64-bit one cannot reach KingDraw, the 32-bit one cannot reach ChemDraw,
    and taking the worst of the two made a healthy install report failure from
    both sides. Asking about one channel still answers about that one.

    That fix stopped short of the print loop, which did rc = max(rc, _emit()):
    measured again, 'doctor' still exited 1 on both interpreters while the
    payload said one channel was available. The rule now lives in one place,
    and --strict is the opposite request for scripts: every channel or nothing.
    '''
    available = [bool(p.get('available', p.get('ok', False))) for p in payloads]
    if strict:
        return 0 if available and all(available) else 1
    return 0 if any(available) else 1


def cmd_doctor(args) -> int:
    payloads = []
    if args.channel in ('cd', 'all'):
        payloads.append(cd_doctor.inspect(
            start_if_needed=not args.no_start,
            quit_if_started=not args.keep_open,
        ).to_dict())
    if args.channel in ('kd', 'all'):
        payloads.append(kd_doctor.inspect(kingdraw_home=args.kingdraw_home).to_dict())
    if args.channel in ('kd', 'all') and getattr(args, 'kingdraw_home', None):
        # A named folder that cannot be used is reported, not quietly replaced by
        # the default install: "I pointed it at X and it used Y" is a quiet wrong
        # answer, and the misuse pass exists for exactly that.
        for p in payloads:
            if p.get('channel') == 'kingdraw' and not p.get('home'):
                for line in _wrap('--kingdraw-home %r does not contain '
                                  'GRDKitDll.dll; the channel is unavailable '
                                  '(no silent fallback)' % args.kingdraw_home,
                                  _term_width(), first='warning  : ',
                                  rest='           '):
                    print(line)
    rc = _doctor_status(payloads, strict=getattr(args, 'strict', False))
    if args.json:
        # Each channel object is enveloped on its own, so 'doctor --json' has
        # the same shape as everything else: one object for one channel, an
        # array of objects for several. ok mirrors available, because the
        # report never carried an ok of its own.
        bodies = [as_envelope(p, channel=p.get('channel') or 'cli',
                                    ok=bool(p.get('available')))
                  for p in payloads]
        print(json.dumps(_doctor_body(bodies), indent=2, ensure_ascii=False))
        return rc
    for index, p in enumerate(payloads):
        # 'doctor all' prints one block per channel; without a gap the tail of the
        # first table runs straight into the next 'channel :' line and reads as
        # one more row of that table.
        if index:
            print('')
        _emit(p, False)
    return rc


def cmd_identity(args) -> int:
    started = time.perf_counter()
    payload = identity.identify(args.smiles)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    if getattr(args, 'json_output', False):
        print(json.dumps(as_envelope(payload, channel='rdkit',
                                           elapsed_ms=elapsed_ms),
                         indent=2, ensure_ascii=False))
    else:
        for line in _render_identity(payload):
            print(line)
    return 0 if payload.get('canonical_smiles') else 1


class _InputError(Exception):
    '''A path or string the command needs but cannot read.

    Raised by the readers, caught in cmd_kd, so every kd subcommand answers with
    the same shaped Failure. Before this, "kd formula" with no arguments reached
    the user as TypeError: expected str ... not NoneType, and "kd king /nope.king"
    as FileNotFoundError -- both tracebacks (misuse pass, t18).
    '''

    def __init__(self, detail: str, message: str, hint: str = '') -> None:
        super().__init__(detail)
        self.detail = detail
        self.message = message
        self.hint = hint

    def result(self) -> Result:
        # 'C' means 'design inference, not yet verified', and it carried that
        # sentence into the envelope of a plain path error -- measured:
        # `kd formula --mol /nope.mol` answered evidence C with the note 'design
        # inference, not yet verified', which is a claim about a design nobody
        # inferred. The path really was checked here, so 'A' is the honest level.
        return Result(ok=False, channel='cli', evidence=EVIDENCE_MEASURED,
                      failure=Failure(code=ErrorCode.PARSE_FAILED,
                                      message=self.message,
                                      hint=self.hint or 'Pass an existing file',
                                      detail=self.detail, channel='cli',
                                      stage='input'))


def _read_text(path: str) -> str:
    if not path:
        raise _InputError('no molfile path was given',
                          'A molfile path is required',
                          'Give --mol <file.mol>, or --smiles <SMILES>')
    if not os.path.isfile(path):
        raise _InputError('not a file: %s' % path, 'Input file does not exist',
                          'Check the path; on Windows a leading / is rewritten to '
                          'the git-bash root')
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        return fh.read()


def _read_bytes(path: str) -> bytes:
    if not path:
        raise _InputError('no file path was given', 'A file path is required')
    if not os.path.isfile(path):
        raise _InputError('not a file: %s' % path, 'Input file does not exist',
                          'Check the path; on Windows a leading / is rewritten to '
                          'the git-bash root')
    with open(path, 'rb') as fh:
        return fh.read()


def _render_result(payload: dict, width: int = 100,
                   scalar_label: str = 'data') -> list:
    '''The human form of a result envelope.

    Deliberately the same shape as doctor's report -- `key : value`, aligned,
    one fact per line -- so a reader who learned one command has learned them
    all. Values are cut only at the terminal width; anything machine-readable
    stays whole in the --json form, which is what a script should use.
    '''
    lines = []
    if not payload.get('ok'):
        # Same renderer identity and crosscheck already use: a guide bar under
        # the message, then fix / detail / stage, all hanging-indented. My
        # first version printed the raw message and let the terminal fold it --
        # at 40 columns that split 'automation' into 'auto' + 'mation' with the
        # tail back at column 0, reading as a second sentence.
        lines.extend(_render_failure(payload.get('failure'), width))
        for warning in payload.get('warnings') or []:
            lines.extend(_wrap('! ' + str(warning), width, first='  ',
                               rest='    '))
        return lines

    items = [('ok', 'true')]
    if payload.get('channel'):
        items.append(('channel', payload['channel']))
    if payload.get('degraded'):
        items.append(('degraded', payload.get('degrade_reason') or 'true'))
    evidence = payload.get('evidence')
    if evidence and evidence != 'A':
        note = payload.get('evidence_note')
        items.append(('evidence', str(evidence) + ((' — ' + str(note)) if note else '')))
    data = payload.get('data')
    body = None
    # Adapters wrap a text answer as {'text': ..., 'chars': ...} so the
    # envelope stays uniform. For a reader, that text IS the answer and the
    # character count is bookkeeping -- showing 'text : C6H6O' and
    # 'chars : 5' buries a one-word result in two lines of scaffolding.
    if isinstance(data, dict) and isinstance(data.get('text'), str):
        body = data['text']
        data = {key: value for key, value in data.items()
                if key not in ('text', 'chars')}
    if isinstance(data, dict):
        for key, value in data.items():
            if value is None or value == '' or isinstance(value, (dict, list)):
                continue
            items.append((key, value))
    elif isinstance(data, str):
        body = data
    elif isinstance(data, (bool, int, float)):
        # A one-value answer. `kd match` returns True or False and nothing
        # else, and rendering only dict/str dropped it: a match and a
        # non-match printed byte-identical output (measured: 63 bytes each,
        # rc=0 both) with the answer visible only under --json.
        items.append((scalar_label, 'true' if data is True else
                      'false' if data is False else data))
    room = max(len(str(key)) for key, _ in items)
    for key, value in items:
        lines.extend(_labelled(str(key), value, width, room))
    if body:
        lines.append('')
        for raw_line in body.splitlines():
            if ' ' in raw_line:
                lines.extend(_wrap(raw_line, width))
            else:
                # One unbreakable token (a SMILES, an InChIKey). Folding it
                # here would hand back something that no longer parses; the
                # terminal may wrap it, and --json carries the whole value.
                lines.append(raw_line)
    for warning in payload.get('warnings') or []:
        lines.extend(_wrap('! ' + str(warning), width, first='  ', rest='    '))
    lines.append('')
    lines.append('--json 输出完整信封')
    return lines


SOURCE_SUFFIXES = ('.mol', '.sdf', '.cdx', '.cdxml', '.smi', '.smiles',
                   '.king', '.rxn', '.mrv')


def _looks_like_a_source_file(path) -> bool:
    '''True when `path` names a chemistry file, whether or not it exists yet.

    Used to turn a confusing 'nothing was drawn ... pass a file instead of a
    string' into the real mistake: on `cd figure` the positional argument is
    the output image, so a source path there would otherwise be silently
    overwritten by the export.

    Existence is deliberately not required. `cd figure` writes PNG only, so a
    name ending in .mol was never an output; requiring isfile would send a
    mistyped path straight back to that same sentence, which tells a reader
    who did pass a path to pass a path. Measured on a fresh clone, where the
    file is absent: the old rule let exactly that happen.
    '''
    if not path or not isinstance(path, str):
        return False
    return path.lower().endswith(SOURCE_SUFFIXES)


def _stdout_is_a_terminal() -> bool:
    '''False whenever stdout is redirected, piped or captured.

    Only --json consults this: the human summary goes to stdout and has no
    second channel, while the machine form must stay parseable even when the
    caller merges stderr into it.
    '''
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def _emit_result(res, out: str = None, as_json: bool = False,
                 scalar_label: str = 'data') -> int:
    '''Print a Result; when --out is given and the data is text, write it there.

    Two audiences, two shapes: a person at a terminal gets an aligned summary,
    a program gets the whole envelope with --json. Flipping the default to the
    summary is only safe because every leaf command now accepts --json -- the
    DSH plugin and the MCP bridge parse stdout as JSON, so a command that could
    not be asked for JSON would break them the day its look changed. That is
    exactly what happened when identity grew a summary: chem_identity went from
    working to E99 'the CLI did not return a JSON result'.
    '''
    import os as _os
    payload = res.to_dict() if hasattr(res, 'to_dict') else dict(res)
    data = payload.get('data')
    # Adapters wrap text as {'text': ..., 'chars': ...} so the envelope stays
    # uniform; --out has to look through that before deciding it cannot write.
    if isinstance(data, dict) and isinstance(data.get('text'), str):
        data = data['text']
    if payload.get('ok') and out and isinstance(data, (str, bytes)):
        if isinstance(data, bytes):
            with open(out, 'wb') as fh:
                fh.write(data)
        else:
            with open(out, 'w', encoding='utf-8', newline='') as fh:
                fh.write(data)
        payload['data'] = {'written': _os.path.abspath(out), 'bytes': len(data)}
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        # The memo is for a person watching the terminal, so it only goes to
        # stderr while stdout is still a terminal. When it is not -- a script
        # capturing output, the plugin, a test -- the envelope already carries
        # every warning, and `--json > out.json 2>&1` (the natural shell
        # spelling, and what a user debugging a failure will type) has to
        # leave a file that parses. Measured before this rule: that file began
        # with 'chem-draw-tool: 2 warnings: ...' and no JSON parser in the
        # world would read it.
        if _stdout_is_a_terminal():
            memo = _render_memo(payload, _term_width())
            if memo:
                sys.stderr.write('\n'.join(memo) + '\n')
                sys.stderr.flush()
    else:
        # The human form already says all of it; printing the memo too would
        # say everything twice (measured: the same E04 block, one after the
        # other). One channel, not two.
        for line in _render_result(payload, _term_width(), scalar_label):
            print(line)
    return 0 if payload.get('ok') else 1


def cmd_kd(args) -> int:
    '''KingDraw native channel. Needs the bundled 32-bit interpreter.

    Input problems (missing path, empty string, unreadable file) come back as a
    Result failure through _InputError: a misuse gets an answer, never a
    traceback.
    '''
    from .adapters import kd_native as kd
    try:
        return _kd_run(args, kd)
    except _InputError as exc:
        return _emit_result(exc.result(), getattr(args, 'out', None),
                            _wants_json(args))


def _king_structure_counts(res):
    '''How many objects each the .king parse found, or None when unreadable.

    sup_king_to_json answers with the worker's raw JSON wrapped as
    {'text': ..., 'chars': ...}, so the structure is one json.loads away.
    '''
    data = getattr(res, 'data', None)
    text = data.get('text') if isinstance(data, dict) else data
    if not isinstance(text, str):
        return None
    try:
        payload = json.loads(text)
    except Exception:
        return None
    body = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(body, dict):
        return None
    return {key: len(body.get(key) or [])
            for key in ('nodes', 'bonds', 'texts', 'sups', 'shapes')}


def _kd_run(args, kd) -> int:
    action = args.kd_cmd
    # What to call a bare scalar in the human summary; only `kd match` has one.
    scalar_label = 'data'
    if action == 'mol':
        source = getattr(args, 'smiles_flag', None) or args.smiles
        if source is None:
            raise _InputError('no SMILES was given',
                              'A SMILES string is required',
                              "Pass it positionally (kd mol 'CCO') or as --smiles 'CCO'")
        res = kd.smiles_to_mol(source)
    elif action == 'smiles':
        res = kd.mol_to_smiles(_read_text(getattr(args, 'mol_flag', None) or args.mol))
    elif action == 'formula':
        # "" is a value, not an absence: an empty --smiles must be judged by the
        # engine (E06), not silently swapped for a molfile read that then crashes.
        res = (kd.get_formula(args.smiles) if args.smiles is not None
               else kd.get_mol_formula(_read_text(args.mol)))
    elif action == 'king':
        res = kd.sup_king_to_json(_read_bytes(args.path))
        # The worker answers success for any bytes it can open -- measured:
        # requirements.txt came back ok:true with nodes/bonds/texts/sups/shapes
        # all empty, and the same was true of an empty file and a plain molfile.
        # An empty structure is a fact worth saying out loud, not a result.
        counts = _king_structure_counts(res)
        if counts is not None and not any(counts.values()):
            res.degraded = True
            res.degrade_reason = ('the file opened but holds no structure: '
                                  'nodes=0 bonds=0 texts=0')
            res.warnings.append(
                'this file parsed as .king but contains no structure; if you '
                'expected atoms here, the file is not a KingDraw drawing')
    elif action == 'match':
        res = (kd.substruct_match(args.a, args.b) if args.substructure
               else kd.struct_match(args.a, args.b))
        # The whole answer is one boolean, so the summary has to call it
        # something. Without this the line read 'data : false'.
        scalar_label = 'match'
    elif action == 'to3d':
        res = (kd.smiles2d_to_3d(args.smiles) if args.smiles is not None
               else kd.mol2d_to_3d(_read_text(args.mol)))
    elif action == 'layout':
        res = (kd.smiles_to_mol_ba(args.smiles, args.width, args.height)
               if args.smiles is not None else
               kd.clean_up(_read_text(args.mol), args.width, args.height))
    elif action == 'save':
        from .adapters import kd_save
        res = kd_save.save_as_king(args.path, args.out, timeout=args.timeout,
                                   overwrite=not getattr(args, 'no_overwrite', False))
    elif action == 'export':
        from .adapters import kd_export
        res = kd_export.export_image(
            args.path, args.out, timeout=args.timeout, keep_kdx=args.keep_kdx,
            min_side=args.min_side, close_app=not args.keep_open)
    elif action == 'open':
        from .adapters import kd_open
        res = kd_open.open_file(args.path, timeout=args.timeout,
                                reuse=not args.no_reuse,
                                uia=not getattr(args, 'no_uia', False))
        if res.ok and getattr(args, 'screenshot', None):
            shot = kd_open.capture_window(res.data['pid'], args.screenshot)
            res.data['screenshot'] = shot.data if shot.ok else None
            if not shot.ok:
                res.warnings.append(shot.failure.message)
            else:
                res.warnings.extend(shot.warnings)
                if not shot.data.get('proves_render'):
                    res.degraded = True
                    res.degrade_reason = ('the screenshot is not a proof of render '
                                          '(%s)' % shot.data.get('method'))
        # Keeping the document on screen is the point of the command, so that is
        # the default; --close is for scripts and tests. Close only what this
        # invocation started, never an instance the user already had open.
        if getattr(args, 'close', False) and not getattr(args, 'keep_open', False):
            pid = (res.data or {}).get('pid')
            ours = pid and pid not in ((res.data or {}).get('pids_before') or [])
            if res.ok and ours:
                closed = kd_open.close_app(pid, args.timeout)
                res.data['closed'] = closed.data
                if not closed.ok:
                    res.warnings.append(closed.failure.message)
                    res.data['close_failure'] = closed.failure.to_dict()
    elif action == 'close':
        # There was no way to close KingDraw from this tool, which made the
        # honest answer to a forwarded-open ('the window still shows another
        # document') impossible to act on. Closing is what makes the next open
        # start from a clean window.
        from .adapters import kd_open
        # `if args.pid` treated --pid 0 as 'no pid given' and quietly closed
        # every window instead. An explicit 0 is nonsense, but it is the
        # caller's nonsense and must not turn into a different action.
        targets = [args.pid] if args.pid is not None else kd_open.list_pids()
        results = []
        gone = []
        for target in targets:
            closed = kd_open.close_app(target, args.timeout)
            body = closed.data or {}
            # close_app answers ok for a pid that was never running (there is
            # nothing to fail at), which read as 'I closed it'. Measured with
            # --pid 999999: plain ok, no warning, no such process anywhere.
            if body.get('already_gone'):
                gone.append(target)
            results.append({'pid': target,
                            'closed': bool(body.get('closed')),
                            'already_gone': bool(body.get('already_gone')),
                            'data': body,
                            'failure': None if closed.ok else closed.failure.to_dict()})
        still = [item['pid'] for item in results if not item['closed']]
        if still:
            res = Result(
                ok=False, channel=kd.CHANNEL, evidence=EVIDENCE_MEASURED,
                data={'targets': targets, 'results': results,
                      'still_running': still},
                failure=Failure(
                    code=ErrorCode.KD_CLI_DID_NOT_OPEN, stage='close',
                    detail='pid still running: %s' % ', '.join(str(p) for p in still),
                    message='%d KingDraw window(s) did not close' % len(still),
                    hint='A window with unsaved work answers WM_CLOSE with its '
                         'own dialog and stays open until that is answered: '
                         'finish it in the app, then close again.'))
        else:
            res = Result(ok=True, channel=kd.CHANNEL,
                         evidence=EVIDENCE_MEASURED,
                         data={'targets': targets, 'results': results,
                               'still_running': []})
            if not targets:
                res.warnings.append('no KingDraw window was running')
            for target in gone:
                res.warnings.append(
                    'no process with pid %d was running: there was nothing '
                    'to close' % target)
    else:
        print(json.dumps({'ok': False, 'failure': {'code': 'E99',
                          'message': 'unknown kd action: ' + str(action)}}, indent=2))
        return 2
    return _emit_result(res, getattr(args, 'out', None), _wants_json(args),
                        scalar_label)



# -- ChemDraw channel ------------------------------------------------------
# Code E04 is the shared "wrong interpreter bitness" code (models.ErrorCode
# .KD_BITNESS spells it for the KingDraw direction); ChemDraw needs it the
# other way round, so the message and hint are overridden instead of reused.
CODE_BITNESS = 'E04'


def _bitness_result():
    '''A Failure, not a crash, when this interpreter cannot talk to ChemDraw.'''
    from .models import Failure, Result
    return Result(
        ok=False, channel='chemdraw',
        failure=Failure(
            code=CODE_BITNESS, channel='chemdraw', stage='bitness',
            message='ChemDraw automation needs the 64-bit interpreter; '
                    'this one is 32-bit',
            # This hint used to name the author's interpreter by absolute
            # path, which is wrong on every other machine and unreadable as
            # a suggestion. Say what has to be true instead of where it lives.
            hint='Re-run with the 64-bit python ("python bin/cli.py ..."), '
                 'not the bundled runtime/py32/python.exe',
            detail='sys.maxsize=%d' % sys.maxsize,
        ))


def _open_cd_channel():
    '''Build a ChemDraw channel, or hand back the Result that says why not.'''
    from .adapters import cd_com
    if sys.maxsize <= 2 ** 32:
        return None, _bitness_result()
    ch = cd_com.ChemDrawChannel(visible=True)
    res = ch.connect()
    if not res.ok:
        return None, res
    _attach_active_document(ch)
    return ch, res


def _attach_active_document(ch) -> bool:
    '''Borrow the document the user is looking at, if there is one.

    The adapter always creates a fresh document, which is right for drawing but
    wrong for "export what is on screen". A one-shot CLI process has no earlier
    document of its own, so the active one is adopted before anything is drawn.
    '''
    if getattr(ch, '_doc', None) is not None:
        return True
    try:
        doc = ch._app.ActiveDocument
    except Exception:
        return False
    if doc is None:
        return False
    ch._doc = doc
    return True


def _cd_validate_args(args):
    '''Argument mistakes that need no COM server to report themselves.

    Both checks used to sit in _cd_dispatch, which only runs after a ChemDraw
    instance answers. On a machine without ChemDraw the answer was E01 'cannot
    reach ChemDraw' and the real mistake -- the command was never told what to
    change, or the source file was passed where the image goes -- was never
    mentioned. A usage error should cost no COM call and no vendor install.
    '''
    from .models import ErrorCode, Failure, Result
    action = getattr(args, 'cd_cmd', None)
    if action == 'modify':
        if not (getattr(args, 'replace', None) or args.clear
                or args.delete_atom is not None or args.delete_object is not None):
            return Result(
                ok=False, channel='chemdraw',
                failure=Failure(
                    code=ErrorCode.PARSE_FAILED,
                    message='cd modify needs an edit action',
                    hint='Pass --replace SMILES, --clear, --delete-atom N or '
                         '--delete-object N',
                    detail='none of --replace/--clear/--delete-atom/--delete-object '
                           'was given',
                    channel='chemdraw', stage='modify'))
    if action == 'figure' and not getattr(args, 'smiles', None):
        dest = getattr(args, 'out', None)
        if _looks_like_a_source_file(dest):
            return Result(
                ok=False, channel='chemdraw',
                failure=Failure(
                    code=ErrorCode.PARSE_FAILED, channel='chemdraw', stage='figure',
                    message='the positional argument is the output image, not the input',
                    detail='%r ends with a chemistry suffix, so it was taken as '
                           'the destination; cd figure writes PNG and reads the '
                           'structure from --smiles' % dest,
                    hint="cd figure --smiles 'c1ccccc1O' out.png --width-mm 85 --dpi 574"))
    return None


def cmd_cd(args) -> int:
    '''ChemDraw channel. Needs the 64-bit interpreter (COM server is x64).'''
    action = args.cd_cmd
    if action == 'doctor':
        report = cd_doctor.inspect(start_if_needed=not args.no_start,
                                   quit_if_started=not args.keep_open)
        return _emit(report.to_dict(), args.json)

    invalid = _cd_validate_args(args)
    if invalid is not None:
        return _emit_result(invalid, as_json=_wants_json(args))
    ch, opened = _open_cd_channel()
    if ch is None:
        return _emit_result(opened, as_json=_wants_json(args))
    try:
        res = _cd_dispatch(ch, args, action)
    finally:
        if not getattr(args, 'keep_open', False):
            try:
                ch.close()
            except Exception:
                pass
    return _emit_result(res, as_json=_wants_json(args))


def _cd_dispatch(ch, args, action):
    from .models import ErrorCode, Failure, Result
    from .adapters import cd_com

    if action == 'capabilities':
        rows = [c.to_dict() for c in cd_com.ChemDrawChannel().capabilities()]
        return Result(ok=True, channel='chemdraw', data=rows)

    if action == 'modify':
        # exception: it states the whole content, so a fresh page is fine.
        if not _attach_active_document(ch) and not getattr(args, 'replace', None):
            return Result(
                ok=False, channel='chemdraw',
                failure=Failure(
                    code=ErrorCode.CD_NOT_RUNNING,
                    message='There is no document open to edit',
                    hint='Draw one first (cd draw), or pass --replace SMILES to set the content'))
        res = ch.modify(
            replace=getattr(args, 'replace', None),
            clear=getattr(args, 'clear', False),
            delete_atom=getattr(args, 'delete_atom', None),
            delete_object=getattr(args, 'delete_object', None),
        )
        if res.ok and getattr(args, 'out', None):
            exported = ch.export(args.out, args.format, args.resolution)
            res.warnings.extend(exported.warnings)
            res.data['export'] = exported.to_dict() if hasattr(exported, 'to_dict') else exported
            if exported.ok:
                # The same keys `cd export` and `kd export` report, so one
                # script reads data.path for every command that wrote a file.
                # Before this, `cd draw --out` left the path only inside the
                # nested export envelope (measured: top-level path was null
                # while the PNG was on disk).
                res.data['path'] = exported.data.get('path')
                res.data['bytes'] = exported.data.get('bytes')
                res.data['format'] = exported.data.get('format')
            if not exported.ok:
                res.ok = False
                res.failure = exported.failure
        return res

    if action == 'draw':
        res = ch.draw_smiles(args.smiles, route=args.route)
        if res.ok and getattr(args, 'out', None):
            exported = ch.export(args.out, args.format, args.resolution)
            res.warnings.extend(exported.warnings)
            res.data['export'] = exported.to_dict() if hasattr(exported, 'to_dict') else exported
            if exported.ok:
                # The same keys `cd export` and `kd export` report, so one
                # script reads data.path for every command that wrote a file.
                # Before this, `cd draw --out` left the path only inside the
                # nested export envelope (measured: top-level path was null
                # while the PNG was on disk).
                res.data['path'] = exported.data.get('path')
                res.data['bytes'] = exported.data.get('bytes')
                res.data['format'] = exported.data.get('format')
            if not exported.ok:
                res.ok = False
                res.failure = exported.failure
            else:
                res.data['png_bytes'] = exported.data['bytes']
        return res

    def _dest() -> tuple:
        '''(destination, failure): the positional form or --out, never neither.'''
        dest = getattr(args, 'out', None) or getattr(args, 'out_flag', None)
        if dest:
            return dest, None
        return None, Result(
            ok=False, channel='chemdraw',
            failure=Failure(code=ErrorCode.PARSE_FAILED,
                            message='cd %s needs a destination file' % action,
                            hint='Give it positionally (cd %s out.png) or as --out '
                                 'out.png' % action,
                            detail='neither the positional out nor --out was given',
                            channel='chemdraw', stage=action))

    if action == 'export':
        dest, missing = _dest()
        if missing is not None:
            return missing
        if args.smiles:
            drawn = ch.draw_smiles(args.smiles)
            if not drawn.ok:
                return drawn
        res = ch.export(dest, args.format, args.resolution,
                        args.width_pt, args.height_pt)
        if not res.ok and not args.smiles and res.failure is not None:
            # Two sentences glued together read as one run-on hint ("Call
            # draw_smiles first On the command line ..."), so join them with a
            # full stop instead of a space.
            extra = ('On the command line there is no earlier document of your '
                     'own: pass --smiles to draw before exporting.')
            hint = (res.failure.hint or '').strip()
            if hint and hint[-1] not in '.!?':
                hint += '.'
            res.failure.hint = (hint + ' ' + extra).strip()
        return res

    if action == 'figure':
        dest, missing = _dest()
        if missing is not None:
            return missing
        if args.smiles:
            drawn = ch.draw_smiles(args.smiles)
            if not drawn.ok:
                return drawn
        return ch.export_figure(dest, width_mm=args.width_mm, dpi=args.dpi,
                                fmt=args.format)

    if action == 'read':
        if args.smiles:
            drawn = ch.draw_smiles(args.smiles)
            if not drawn.ok:
                return drawn
        return ch.read_current(args.format)

    return Result(ok=False, channel='chemdraw', failure=Failure(
        code='E99', channel='chemdraw', stage='dispatch',
        message='unknown cd action: ' + str(action)))



def cmd_crosscheck(args) -> int:
    """Two independent vendor engines verify the same molecule.

    Exit codes: 0 the engines agree, 2 they disagree, 1 the check itself failed.
    """
    from . import crosscheck as xc
    try:
        if args.compare_to:
            res = xc.compare(args.smiles, args.compare_to, args.kingdraw_home)
        else:
            res = xc.crosscheck(args.smiles, args.kingdraw_home)
    finally:
        # One-shot CLI: release the ChemDraw instance this run started.
        try:
            xc.shutdown()
        except Exception:
            pass
    payload = res.to_dict()
    if args.json:
        _emit_result(res, as_json=True)
        if not payload.get('ok'):
            return 1
        # A disagreement is an answer, not a crash: keep it visible in the
        # exit code so a shell can gate on it without parsing JSON.
        return 0 if (payload.get('data') or {}).get('agree') else 2
    return _render_crosscheck(res)


def _render_crosscheck(res) -> int:
    '''The human form of a cross-engine verdict.

    One table, or -- when the terminal is too narrow for it -- one block per
    engine. Before this the reference row and the engine rows came from two
    different format strings ('  %s      : %-28s %s' versus
    '  %-8s: %-7s %-28s %s'), so their colons never shared a column unless the
    engine name happened to be exactly eight characters long.
    '''
    width = _term_width()
    payload = res.to_dict() if hasattr(res, 'to_dict') else dict(res)
    data = payload.get('data') or {}
    if not payload.get('ok'):
        for line in _render_failure(payload.get('failure') or {}, width):
            print(line)
        return 1

    agree = _cell(data.get('agree'))
    basis = _cell(data.get('basis'))
    lines = []
    if 'a' in data and 'b' in data:
        lines.extend(_wrap('%s  (basis: %s)' % (agree, basis), width,
                           first='agree    : ', rest='           '))
        rows = []
        for side in ('a', 'b'):
            info = data.get(side) or {}
            ref = info.get('reference') or {}
            rows.append([side, _cell(ref.get('inchikey')), _cell(ref.get('smiles'))])
        header = ['side', 'inchikey', 'smiles']
    else:
        compared = ', '.join(data.get('compared') or []) or 'reference only'
        lines.extend(_wrap('%s  (basis: %s, compared: %s)'
                           % (agree, basis, compared), width,
                           first='agree    : ', rest='           '))
        rows = []
        reference = data.get('reference') or {}
        rows.append(['rdkit', 'reference', _cell(reference.get('inchikey')),
                     _cell(reference.get('smiles'))])
        for name, record in (data.get('engines') or {}).items():
            if name == 'rdkit':
                continue
            mismatched = any(m.get('engine') == name
                             for m in (data.get('mismatch') or []))
            verdict = ('n/a' if not record.get('ok')
                       else 'differs' if mismatched else 'agree')
            extra = record.get('smiles') or record.get('detail') or ''
            rows.append([name, verdict, _cell(record.get('inchikey')),
                         _cell(extra)])
        header = ['engine', 'verdict', 'inchikey', 'smiles / detail']

    if rows:
        lines.append('')
        table = _table(header, rows, width)
        lines.extend(table if table is not None else _stacked(header, rows, width))
    for mismatch in data.get('mismatch') or []:
        lines.extend(_wrap('mismatch: %s' % mismatch, width, rest='        '))
    if payload.get('degraded'):
        reason = (payload.get('degrade_reason') or '').strip()
        lines.extend(_wrap('degraded: %s' % (reason or 'no reason recorded'),
                           width, rest='          '))
    for warning in payload.get('warnings') or []:
        lines.extend(_wrap('warning : %s' % warning, width, rest='          '))
    for line in lines:
        print(line)
    return 0 if data.get('agree') else 2


def _wants_json(args) -> bool:
    '''Did the caller ask for the machine-readable form?

    identity names its flag differently (it gained --json before the rest of
    the commands did), so both destinations are honoured rather than renaming
    a flag users may already have in a script.
    '''
    return bool(getattr(args, 'json', False) or getattr(args, 'json_output', False))


def _leaf_parsers(parser):
    '''Every parser that has no subcommands of its own.'''
    children = [action for action in parser._actions
                if isinstance(action, argparse._SubParsersAction)]
    if not children:
        yield parser
        return
    for action in children:
        for child in action.choices.values():
            yield from _leaf_parsers(child)


def _add_json_flag(parser) -> None:
    '''Give every leaf command a --json switch, in one place.

    Added centrally on purpose. A command without it silently becomes
    unusable to anything that parses its stdout as JSON -- the DSH plugin,
    the MCP bridge, a user's shell script -- and its output shape turns into
    a contract nobody declared. Doing it here means a new subcommand gets the
    flag by default instead of by whoever remembers.
    (Touches argparse's private _SubParsersAction; that name has been stable
    since 3.2, and this is the only place that reaches into it.)
    '''
    for leaf in _leaf_parsers(parser):
        taken = set()
        for action in leaf._actions:
            taken.update(action.option_strings)
        if '--json' in taken:
            continue
        # English, like every other help string here -- and not only for
        # consistency: argparse wraps help by character count, so a Chinese
        # line is measured at half its real width and runs past the terminal
        # edge. Measured at 40 columns: '打印完整结果信封（机器可读）' is 14
        # characters but 28 columns, and the --json row came out 42 wide.
        leaf.add_argument('--json', action='store_true',
                          help='print the full result envelope as JSON')


class _WidthFormatter(argparse.HelpFormatter):
    '''argparse measures characters, so it wraps CJK text and paths too late.

    It does honour get_terminal_size(), which is why help text mostly fitted,
    but a subparser's usage line could still run past COLUMNS (measured: 64
    columns at COLUMNS=60). Passing our own width makes one number govern both
    usage and the tables below it.
    '''

    def __init__(self, prog, **kwargs):
        kwargs.setdefault('width', _term_width(floor=20))
        argparse.HelpFormatter.__init__(self, prog, **kwargs)


class _WidthParser(argparse.ArgumentParser):
    '''A parser whose errors stay inside the terminal, like everything else.

    argparse prints 'prog: error: <message>' as a single unwrapped line. At
    COLUMNS=40 an invalid subcommand produced this (measured, 172 columns):

        chem-draw-tool kd: error: argument <command>: invalid choice: 'doctor'
        (choose from 'mol', 'smiles', 'formula', 'king', 'match', 'to3d', ...)

    That is the exact overflow the rest of this module exists to prevent, so
    the message goes through _wrap() instead: word boundaries, the same width
    budget, and the subcommand list lands on its own indented lines.
    '''

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('formatter_class', _WidthFormatter)
        argparse.ArgumentParser.__init__(self, *args, **kwargs)

    def print_usage(self, file=None):
        '''Usage through the same wrapper as everything else.

        argparse's hanging indent is 25 columns (measured: the usage line of
        `chem-draw-tool kd` starts its arguments under column 26), so at
        COLUMNS=32 its own layout is infeasible: it emitted a 34-column line
        while claiming a 32-column budget. Fitting the text afterwards is the
        only way to keep the promise at every width.
        '''
        target = file or sys.stderr
        width = _term_width(floor=20)
        text = self.format_usage().rstrip('\n')
        # Keep the 'usage: ' hang on continuation lines: folding ' <command>'
        # to column 0 read as a broken layout (measured at 32 columns).
        hang = ' ' * _dwidth('usage: ')
        for line in _wrap(text, width, first='', rest=hang):
            target.write(line + '\n')

    def error(self, message):
        width = _term_width(floor=20)
        self.print_usage(sys.stderr)
        prefix = '%s: error: ' % self.prog
        # Measured at COLUMNS=40: keeping the message beside a 23-column
        # prefix leaves 17 columns, and two words do not fit in 17 -- the
        # output became one word per line. When the prefix would eat more
        # than half the line, it gets its own line and the message is
        # indented two columns instead.
        if width - _dwidth(prefix) < width // 2:
            sys.stderr.write(prefix.rstrip() + '\n')
            first, rest = '  ', '  '
        else:
            first, rest = prefix, ' ' * _dwidth(prefix)
        for line in _wrap(message, width, first=first, rest=rest):
            sys.stderr.write(line + '\n')
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    p = _WidthParser(prog='chem-draw-tool', description='ChemDraw / KingDraw bridge')
    sub = p.add_subparsers(dest='cmd', metavar='<command>', parser_class=_WidthParser)
    d = sub.add_parser(
        'doctor', help='probe a channel')
    d.add_argument('--strict', action='store_true',
                   help='exit non-zero unless every requested channel is '
                        'available (default: one working channel is enough, '
                        'because the two need different bitness and usually '
                        'one interpreter can only reach one of them)')
    d.add_argument('channel', nargs='?', default='all', choices=['cd', 'kd', 'all'])
    d.add_argument('--json', action='store_true')
    d.add_argument('--kingdraw-home', default=None)
    d.add_argument('--no-start', action='store_true', help='do not launch ChemDraw')
    d.add_argument('--keep-open', action='store_true', help='keep ChemDraw running')
    d.set_defaults(func=cmd_doctor)
    i = sub.add_parser('identity', help='normalise a SMILES string')
    i.add_argument('smiles')
    i.add_argument('--json', dest='json_output', action='store_true',
                   help='print the JSON record instead of the summary')
    i.set_defaults(func=cmd_identity)

    k = sub.add_parser('kd', help='KingDraw native channel (needs the 32-bit runtime)')
    ksub = k.add_subparsers(dest='kd_cmd', metavar='<command>',
                            parser_class=_WidthParser)

    p_mol = ksub.add_parser('mol', help='SMILES -> RDKit 2D molfile')
    p_mol.add_argument('smiles', nargs='?', help='the SMILES (positional)')
    # kd formula / kd to3d / kd layout all take --smiles, so a reader who
    # learned one command guesses the flag here. Measured: typing
    # `kd mol --smiles CCO` answered 'unrecognized arguments: --smiles' three
    # times in a row while writing the fidelity tests. Accept both spellings.
    p_mol.add_argument('--smiles', dest='smiles_flag', metavar='SMILES',
                       help='same value as the positional')
    p_mol.add_argument('--out')
    p_mol.set_defaults(func=cmd_kd)

    p_smi = ksub.add_parser('smiles', help='molfile -> SMILES')
    p_smi.add_argument('mol', nargs='?', help='the molfile (positional)')
    p_smi.add_argument('--mol', dest='mol_flag', metavar='FILE',
                       help='same value as the positional')
    p_smi.set_defaults(func=cmd_kd)

    p_for = ksub.add_parser('formula', help='molecular formula')
    p_for.add_argument('--smiles')
    p_for.add_argument('--mol')
    p_for.set_defaults(func=cmd_kd)

    p_king = ksub.add_parser('king', help='read a .king file as JSON')
    p_king.add_argument('path')
    p_king.add_argument('--out')
    p_king.set_defaults(func=cmd_kd)

    p_match = ksub.add_parser('match', help='compare two structures')
    p_match.add_argument('a')
    p_match.add_argument('b')
    p_match.add_argument('--substructure', action='store_true')
    p_match.set_defaults(func=cmd_kd)

    p_3d = ksub.add_parser('to3d', help='flat structure -> 3D molblock')
    p_3d.add_argument('--smiles')
    p_3d.add_argument('--mol')
    p_3d.add_argument('--out')
    p_3d.set_defaults(func=cmd_kd)

    p_lay = ksub.add_parser('layout', help='re-lay a structure inside a W x H box')
    p_lay.add_argument('--smiles')
    p_lay.add_argument('--mol')
    p_lay.add_argument('--width', type=float, default=200.0)
    p_lay.add_argument('--height', type=float, default=200.0)
    p_lay.add_argument('--out')
    p_lay.set_defaults(func=cmd_kd)

    p_open = ksub.add_parser(
        'open', help='open a structure in KingDraw and verify the window really appeared')
    p_open.add_argument('path', help='molfile or .king to open')
    p_open.add_argument('--timeout', type=float, default=20.0,
                        help='seconds to wait for the window (default 20)')
    p_open.add_argument('--no-uia', action='store_true',
                        help='skip the UIAutomation document check (window title only)')
    p_open.add_argument('--no-reuse', action='store_true',
                        help='ask for a fresh KingDraw instance; it cannot be '
                             'granted (single-instance app) and the result says '
                             'reuse_honored: false plus a warning')
    p_open.add_argument('--keep-open', action='store_true',
                        help='leave KingDraw open (this is the default)')
    p_open.add_argument('--screenshot', default=None,
                        help='save a PNG of the window (proves it really rendered)')
    p_open.add_argument('--close', action='store_true',
                        help='close the instance we started after verifying it (WM_CLOSE)')
    p_open.set_defaults(func=cmd_kd)

    p_save = ksub.add_parser(
        'save', help='write a structure as a KingDraw .king and read it back')
    p_save.add_argument('path', help='molfile to convert (or an existing .king to check)')
    p_save.add_argument('--out', default=None,
                        help='output .king path (default: next to the input)')
    p_save.add_argument('--timeout', type=float, default=30.0,
                        help='seconds for the round-trip verification (default 30)')
    p_save.add_argument('--no-overwrite', action='store_true',
                        help='refuse to replace an existing output instead of '
                             'overwriting it (default: overwrite)')
    p_save.set_defaults(func=cmd_kd)

    p_export = ksub.add_parser(
        'export', help='render the structure to an image via the .kdx preview '
                       '(preview-level, not publication artwork)')
    p_export.add_argument('path', help='molfile or .king to render')
    p_export.add_argument('--out', default=None,
                          help='output image (.png default; .jpg/.webp/.bmp/.tif)')
    p_export.add_argument('--timeout', type=float, default=90.0,
                          help='seconds for the whole open+save+extract cycle (90)')
    p_export.add_argument('--min-side', type=int, default=300,
                          help='upscale small previews so the short side reaches this '
                               '(0 = keep the rendered size)')
    p_export.add_argument('--keep-kdx', action='store_true',
                          help='keep the temporary .kdx archive for inspection')
    p_export.add_argument('--keep-open', action='store_true',
                          help='leave the KingDraw instance open after exporting')
    p_export.set_defaults(func=cmd_kd)

    p_close = ksub.add_parser(
        'close', help='close KingDraw windows, so the next open starts from a '
                      'clean window')
    p_close.add_argument('--pid', type=int, default=None,
                         help='close only this process (default: every KingDraw '
                              'window this tool can see)')
    p_close.add_argument('--timeout', type=float, default=12.0,
                         help='seconds to wait for each window to go (default 12)')
    p_close.set_defaults(func=cmd_kd)

    p_cross = sub.add_parser('crosscheck',
                             help='verify one molecule with two vendor engines')
    p_cross.add_argument('smiles', help='SMILES to verify')
    p_cross.add_argument('--compare-to', metavar='SMILES', default=None,
                         help='also decide whether these two are the same molecule')
    p_cross.add_argument('--kingdraw-home', default=None,
                         help='folder that holds GRDKitDll.dll')
    p_cross.add_argument('--json', action='store_true',
                         help='print the full Result envelope instead of a table')
    p_cross.set_defaults(func=cmd_crosscheck)

    # ChemDraw channel: the same shapes as kd, on the 64-bit interpreter.
    cd = sub.add_parser('cd', help='ChemDraw channel (needs the 64-bit runtime)')
    cdsub = cd.add_subparsers(dest='cd_cmd', metavar='<command>',
                              parser_class=_WidthParser)

    p_cddoc = cdsub.add_parser('doctor', help='probe the ChemDraw COM channel')
    p_cddoc.add_argument('--json', action='store_true')
    p_cddoc.add_argument('--no-start', action='store_true', help='do not launch ChemDraw')
    p_cddoc.add_argument('--keep-open', action='store_true', help='keep ChemDraw running')
    p_cddoc.set_defaults(func=cmd_cd)

    p_cddraw = cdsub.add_parser('draw', help='insert a SMILES on a ChemDraw page')
    p_cddraw.add_argument('smiles')
    p_cddraw.add_argument('--route', default='smiles',
                          choices=['smiles', 'molblock', 'cdxml', 'paste', 'objects'],
                          help='insertion route (default smiles)')
    p_cddraw.add_argument('--out', help='also export the drawing to this file')
    p_cddraw.add_argument('--format', default='png', help='png / svg / emf ...')
    p_cddraw.add_argument('--resolution', type=int, default=300)
    p_cddraw.add_argument('--keep-open', action='store_true')
    p_cddraw.set_defaults(func=cmd_cd)

    p_cdexp = cdsub.add_parser('export', help='export the current page as a picture')
    # Both spellings work: the kd half of the tool takes --out everywhere, so a
    # user who learned that reaches for "cd export --out x.png" and used to get
    # only argparse's "unrecognized arguments". The positional form stays the
    # documented one.
    p_cdexp.add_argument('out', nargs='?',
                         help='destination file; the format extension is added')
    p_cdexp.add_argument('--out', dest='out_flag', metavar='FILE',
                         help='same destination, --out spelling')
    p_cdexp.add_argument('--smiles', help='draw this first (a CLI process has no earlier page)')
    p_cdexp.add_argument('--format', default='png', help='png / svg / emf / tif ...')
    p_cdexp.add_argument('--resolution', type=int, default=300,
                         help='pixels per inch; the PNG is then cropped to '
                              'the ink with 2 pt of paper around it')
    p_cdexp.add_argument('--width-pt', type=float, default=None,
                         help='region width in points (default: the drawing plus a margin)')
    p_cdexp.add_argument('--height-pt', type=float, default=None)
    p_cdexp.add_argument('--keep-open', action='store_true')
    p_cdexp.set_defaults(func=cmd_cd)

    p_cdfig = cdsub.add_parser('figure', help='export a journal-ready, trimmed RGB figure')
    p_cdfig.add_argument('out', nargs='?',
                         help='destination file; the format extension is added')
    p_cdfig.add_argument('--out', dest='out_flag', metavar='FILE',
                         help='same destination, --out spelling')
    p_cdfig.add_argument('--smiles')
    p_cdfig.add_argument('--width-mm', type=float, default=85.0,
                         help='physical width (default 85 mm, single column)')
    p_cdfig.add_argument('--dpi', type=int, default=1200)
    p_cdfig.add_argument('--format', default='png')
    p_cdfig.add_argument('--keep-open', action='store_true')
    p_cdfig.set_defaults(func=cmd_cd)

    p_cdread = cdsub.add_parser('read', help='read the current page back')
    p_cdread.add_argument('--smiles', help='draw this first, then read it back')
    p_cdread.add_argument('--format', default='smiles',
                          choices=['smiles', 'molfile', 'cdxml'])
    p_cdread.add_argument('--out', help='write the text here instead of only printing JSON')
    p_cdread.add_argument('--keep-open', action='store_true')
    p_cdread.set_defaults(func=cmd_cd)

    p_cdmod = cdsub.add_parser('modify', help='edit what is already on the page')
    p_cdmod.add_argument('--replace', metavar='SMILES',
                         help='empty the page and draw this instead')
    p_cdmod.add_argument('--clear', action='store_true', help='just empty the page')
    p_cdmod.add_argument('--delete-atom', type=int, metavar='N',
                         help='delete atom N (1-based)')
    p_cdmod.add_argument('--delete-object', type=int, metavar='N',
                         help='delete graphic/picture N')
    p_cdmod.add_argument('--out', help='export the page after editing')
    p_cdmod.add_argument('--format', default='png')
    p_cdmod.add_argument('--resolution', type=int, default=300)
    p_cdmod.add_argument('--keep-open', action='store_true')
    p_cdmod.set_defaults(func=cmd_cd)

    p_cdcap = cdsub.add_parser('capabilities', help='what this ChemDraw build can do')
    p_cdcap.add_argument('--keep-open', action='store_true')
    p_cdcap.set_defaults(func=cmd_cd)

    _add_json_flag(p)
    return p



def _sub_parser(parser, name):
    '''The subparser registered under `name`, or None.'''
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices.get(name)
    return None


def _owner_parser(parser, args):
    '''The deepest parser that saw this command line, for blame messages.

    argparse reports an unrecognised argument against whichever parser called
    parse_args -- always the top one -- so `identity CCO extra` printed the
    five-command table and named <command>, which is not the command that was
    mistyped. The subparser that owns the leaf knows the right usage line.
    '''
    current = parser
    for key in ('cmd', 'kd_cmd', 'cd_cmd'):
        name = getattr(args, key, None)
        if not name:
            continue
        current = _sub_parser(current, name)
        if current is None:
            return None
    return current


def main(argv=None) -> int:
    parser = build_parser()
    args, leftover = parser.parse_known_args(argv)
    if not getattr(args, 'func', None):
        command = getattr(args, 'cmd', None)
        channel = _sub_parser(parser, command) if command else None
        if command in ('kd', 'cd') and channel is not None:
            # `chem-draw-tool kd` is an unfinished command, not a request for
            # the five-command table: not one of kd's actions appears in that
            # table, so it answered a question nobody asked.
            channel.print_help()
            return 2
        parser.print_help()
        return 2
    if leftover:
        owner = _owner_parser(parser, args) or parser
        owner.error('unrecognized arguments: %s' % ' '.join(leftover))
    return args.func(args)


if __name__ == '__main__':
    raise SystemExit(main())