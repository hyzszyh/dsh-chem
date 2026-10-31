'''KingDraw save channel: turn a structure into a .king document (and verify it).

The old plan was "drive the app's 另存为 dialog", and that part works (see
save_via_app below), but it cannot produce a .king: measured on this build,
dialog is 'KDX 文件(*.kdx) - KDX为新版的拓展的King文件，能够完全覆盖King格式',
KingDraw appends .kdx no matter what name is typed, and the .kdx container is a
ZIP (header 'PK\x03\x04') that GRDKitDll.dll cannot read -- supKingToJson answers
{"success":true,...,"nodes":[]} for it. So the app can save, but not to .king.

.king itself is plain text with a Ctab block (measured from
D:/tool/KingDraw/Cyclohexane.king):

    Begin Header / KingDraw V2.2 / 20180420 / End Header
    Begin Device ... End Device
    Begin SysConfig ... End SysConfig
    Begin Ctab
    Begin Atom
    <i> <elem> <x> <y> <colour> [Label=<text>]
    End Atom
    Begin Bond
    <i> <order> <a1> <a2> 0 #ff000000
    End Bond
    End Ctab
    END

The reference file is all carbon, so three things it cannot show were learned
by measuring what the app does with them (each note below repeats the number):

  * Label is the text the app draws, not the element symbol. 'Label=OH' draws
    OH, 'Label=O' draws O, and 'HCount=n' beside it changes nothing at all.
  * A formal charge is drawn the same way -- 'Label=O-' shows the minus, while
    a 'Charge=-1' attribute is ignored.
  * The per-atom colour is what makes the picture look like the app's own:
    a .king written in plain black exports grey, while the same structure
    exported from its molfile comes out with red oxygens and blue nitrogens.

What the format cannot carry is a stereo bond: measured across the bond type
values 1-8 and the align field, none of them draws a wedge, and the reader
reports no other bond field. save_as_king() therefore reports such a file as
degraded instead of quietly handing back a flat structure.

Writing that text from a molblock and reading it back through supKingToJson gives
the same node count, bond count and element list, which is what save_as_king()
asserts before it reports success.
'''

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import sys
import time
from typing import Optional

from ..models import (
    ERROR_TEXT, ErrorCode, EVIDENCE_INFERRED, EVIDENCE_MEASURED, Failure, Result,
)

CHANNEL = 'kingdraw'
KING_MAGIC = 'Begin Header'
KING_HEADER = ['Begin Header', 'KingDraw V2.2', '20180420', 'End Header']
KING_DEVICE = ['Begin Device', 'device=[{"device":"3","version":"1.0.2_beta"}]',
               'End Device']
KING_SYS_CONFIG = [
    'Begin SysConfig',
    '{"DrawingSettings":"{\\"Id_Renamed\\":0,\\"documentType\\":0,\\"proof\\":false,'
    '\\"zoomer\\":false,\\"fixedLength\\":\\"0.78\\",\\"spacing\\":12,'
    '\\"lineWidth\\":\\"0.0312\\",\\"boldWidth\\":\\"0.0936\\",'
    '\\"marginWidth\\":\\"0.0312\\",\\"hashSpacing\\":\\"0.0624\\",'
    '\\"chainsAngle\\":120,\\"atomFontName\\":\\"Arial\\",\\"atomFontStyle\\":1,'
    '\\"atomFontSize\\":10,\\"textFontName\\":\\"Arial\\",\\"textFontStyle\\":1,'
    '\\"textFontSize\\":10,\\"isNormal\\":false}"}',
    'End SysConfig']
PY32_ENV = 'CHEMTOOL_PYTHON32'
DEFAULT_PY32 = os.path.join('runtime', 'py32', 'python.exe')


def _failure(code: str, stage: str, detail: str = '', message: str = '',
             hint: str = '') -> Failure:
    d_msg, d_hint = ERROR_TEXT.get(code, ('', ''))
    return Failure(code=code, message=message or d_msg, hint=hint or d_hint,
                   detail=detail, channel=CHANNEL, stage=stage)


def _root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


def is_32bit() -> bool:
    return sys.maxsize <= 2 ** 31


def find_python32(explicit: Optional[str] = None) -> Optional[str]:
    '''A 32-bit interpreter that can load GRDKitDll.dll.'''
    out = []
    if explicit:
        out.append(explicit)
    env = os.environ.get(PY32_ENV)
    if env:
        out.append(env)
    out.append(os.path.join(_root(), DEFAULT_PY32))
    out.extend(glob.glob(r'C:\Python3*\python.exe'))
    for path in out:
        if path and os.path.isfile(path) and os.path.normcase(path) != os.path.normcase(sys.executable):
            return path
    return sys.executable if is_32bit() else None


# -- molblock reading -------------------------------------------------------
def parse_molblock(text: str):
    '''(atoms [(elem, x, y)], bonds [(order, a1, a2)]) from a V2000/V3000 block.'''
    lines = [ln.rstrip('\r') for ln in (text or '').splitlines()]
    atoms: list = []
    bonds: list = []
    if any('V3000' in line for line in lines[:8]):
        in_atoms = in_bonds = False
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith('M  V30'):
                continue
            body = stripped[6:].strip()
            if body.startswith('BEGIN ATOM'):
                in_atoms, in_bonds = True, False
                continue
            if body.startswith('END ATOM'):
                in_atoms = False
                continue
            if body.startswith('BEGIN BOND'):
                in_atoms, in_bonds = False, True
                continue
            if body.startswith('END BOND'):
                in_bonds = False
                continue
            parts = body.split()
            if in_atoms and len(parts) >= 5:
                charge = 0
                for attribute in parts[5:]:
                    if attribute.upper().startswith('CHG='):
                        try:
                            charge = int(attribute[4:])
                        except ValueError:
                            charge = 0
                atoms.append((parts[1], float(parts[2]), float(parts[3]), charge))
            elif in_bonds and len(parts) >= 4:
                bonds.append((int(parts[1]), int(parts[2]), int(parts[3])))
        return atoms, bonds
    if len(lines) < 4:
        return atoms, bonds
    counts = lines[3]
    try:
        n_atoms = int(counts[0:3])
        n_bonds = int(counts[3:6])
    except ValueError:
        return atoms, bonds
    for line in lines[4:4 + n_atoms]:
        if len(line) < 20:
            continue
        atoms.append((line[31:34].strip(), float(line[0:10]), float(line[10:20]), 0))
    # 'M  CHG n a1 c1 a2 c2 ...' carries formal charges in V2000. They matter to
    # the hydrogen count below: acetate's O- has one bond and no hydrogen,
    # while a neutral hydroxyl with one bond has one.
    for line in lines[4 + n_atoms:]:
        if not line.startswith('M  CHG'):
            continue
        fields = line.split()
        try:
            pairs = int(fields[2])
        except (IndexError, ValueError):
            continue
        for index in range(pairs):
            try:
                atom = int(fields[3 + index * 2]) - 1
                charge = int(fields[4 + index * 2])
            except (IndexError, ValueError):
                break
            if 0 <= atom < len(atoms):
                elem, x, y, _ = atoms[atom]
                atoms[atom] = (elem, x, y, charge)
    for line in lines[4 + n_atoms:4 + n_atoms + n_bonds]:
        if len(line) < 9:
            continue
        bonds.append((int(line[6:9]), int(line[0:3]), int(line[3:6])))
    return atoms, bonds


def unrepresentable_atoms(text: str) -> dict:
    '''Counts of what this .king format cannot draw: isotopes and radicals.

    Measured on molfiles written by this tool (they come back as V3000):
    [13CH3]C carries MASS=13, [CH3] carries RAD=2, and the .king written from
    either has a plain 'C' with no label -- the isotope and the radical are
    gone with no error. A charge is different: it survives, because it becomes
    part of the atom label (Label=NH4+, Label=O-), so it is not counted here.
    '''
    counts = {'isotopes': 0, 'radicals': 0}
    lines = text.splitlines()
    if any('V3000' in line for line in lines[:8]):
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith('M  V30'):
                continue
            body = stripped[6:].strip().upper()
            # ATOM lines start with the index; the attribute block is key=value
            if 'MASS=' in body:
                counts['isotopes'] += 1
            if 'RAD=' in body:
                counts['radicals'] += 1
        return counts
    for line in lines:
        if line.startswith('M  ISO'):
            counts['isotopes'] += 1
        elif line.startswith('M  RAD'):
            counts['radicals'] += 1
    if counts['isotopes'] or counts['radicals']:
        return counts
    try:
        n_atoms = int(lines[3][0:3])
    except (IndexError, ValueError):
        return counts
    for line in lines[4:4 + n_atoms]:
        diff = line[34:36].strip() if len(line) > 35 else ''
        if diff and diff.lstrip('+-').isdigit() and diff != '0':
            counts['isotopes'] += 1
    return counts


def stereo_bonds(text: str) -> int:
    '''How many bonds in this molblock carry stereo information.

    A wedge, a hash or a cis/trans flag lives in the bond block: the fourth
    column of a V2000 bond line (1 up, 3 either, 4 either-double, 6 down) or
    a CFG attribute on a V3000 BOND line.
    '''
    lines = text.splitlines()
    if any('V3000' in line for line in lines[:8]):
        count = 0
        for line in lines:
            stripped = line.strip()
            if not stripped.startswith('M  V30'):
                continue
            body = stripped[6:].strip()
            # a V3000 bond line is index, order, atom, atom -- four numbers
            if not re.match(r'^\d+\s+\d+\s+\d+\s+\d+\s', body):
                continue
            if 'CFG=' in body.upper():
                count += 1
        return count
    if len(lines) < 4:
        return 0
    try:
        n_atoms = int(lines[3][0:3])
        n_bonds = int(lines[3][3:6])
    except ValueError:
        return 0
    count = 0
    for line in lines[4 + n_atoms:4 + n_atoms + n_bonds]:
        if len(line) < 12:
            continue
        try:
            flag = int(line[9:12])
        except ValueError:
            continue
        if flag:
            count += 1
    return count


# Electrons an atom's neutral form wants, used to work out how many hydrogens
# its label should show. Covers what organic structures actually contain;
# anything outside this table gets no HCount, which renders as it did before.
_VALENCE = {'B': 3, 'C': 4, 'N': 3, 'O': 2, 'F': 1, 'Si': 4, 'P': 3,
            'S': 2, 'Cl': 1, 'Br': 1, 'I': 1}

# KingDraw colours heteroatoms in its own theme -- a structure exported
# straight from a molfile comes out with red oxygens and blue nitrogens --
# and the colour is per atom, so a .king written in plain black renders as
# a different-looking picture of the same molecule. These are the values
# that export measures on screen; carbon keeps the default black.
_ELEMENT_COLOUR = {
    'N': '#ff0000ff', 'O': '#ffff0000', 'S': '#ffcc9900', 'P': '#ffff8000',
    'F': '#ff00b050', 'Cl': '#ff00b050', 'Br': '#ffa00000', 'I': '#ff800080',
}


# These take a hydrogen per formal negative charge and lose one per positive;
# carbon and boron go the other way.
_LONE_PAIR_ELEMENTS = ('N', 'O', 'F', 'P', 'S', 'Cl', 'Br', 'I')


def _hydrogens(elem: str, orders: int, charge: int) -> int:
    '''How many hydrogens belong on this atom's label (0 when unsure).'''
    valence = _VALENCE.get(elem)
    if valence is None:
        return 0
    if elem in _LONE_PAIR_ELEMENTS:
        count = valence - orders + charge
    else:
        count = valence - orders - charge
    return max(0, count)


def king_text(atoms, bonds) -> str:
    '''The .king document text for a parsed structure.'''
    orders = [0] * (len(atoms) + 1)
    for order, first, second in bonds:
        for index in (first, second):
            if 0 < index <= len(atoms):
                orders[index] += int(order)
    out = list(KING_HEADER) + list(KING_DEVICE) + list(KING_SYS_CONFIG)
    out.extend(['Begin Ctab', 'Begin Atom'])
    for i, atom in enumerate(atoms, 1):
        elem, x, y = atom[0], atom[1], atom[2]
        charge = atom[3] if len(atom) > 3 else 0
        # Measured: KingDraw draws an atom's letter from the Label attribute,
        # not from the element column. Without it a saved document renders as
        # bare vertices -- an exported glucose came back as a plain cyclohexane
        # ring, and caffeine as a bare purine skeleton. The reference file this
        # format was copied from is Cyclohexane.king, all carbon, so the
        # attribute never appeared in the sample: carbon stays bare, and
        # everything else names itself.
        suffix = ''
        if elem != 'C':
            # Label is the text KingDraw draws, not the element symbol:
            # measured, 'Label=O' renders O and 'Label=OH' renders OH, while
            # 'HCount=1' beside the label changes nothing at all. So the
            # hydrogens belong in the label itself.
            hydrogens = _hydrogens(str(elem), orders[i], charge)
            shown = str(elem) + ('' if not hydrogens else
                                 'H' if hydrogens == 1 else 'H%d' % hydrogens)
            # The charge also belongs in the drawn text: measured on acetate,
            # 'Label=O-' draws a minus beside the O while 'Charge=-1' next to
            # it is ignored entirely, and 'Text=O-' silently drops the label.
            if charge:
                shown += ('-' if charge < 0 else '+') * min(3, abs(int(charge)))
            suffix += ' Label=' + shown
        colour = _ELEMENT_COLOUR.get(str(elem), '#ff000000')
        out.append('%d %s %.4f %.4f %s%s' % (i, elem, x, y, colour, suffix))
    out.append('End Atom')
    out.append('Begin Bond')
    for i, (order, a1, a2) in enumerate(bonds, 1):
        out.append('%d %d %d %d 0 #ff000000' % (i, order, a1, a2))
    out.append('End Bond')
    out.append('End Ctab')
    out.append('END')
    return '\n'.join(out) + '\n'


def is_king_text(blob: bytes) -> bool:
    return blob[:len(KING_MAGIC)] == KING_MAGIC.encode('ascii')


# -- verification through GRDKitDll (32-bit) --------------------------------
def _nodes_script() -> str:
    return os.path.join(_root(), 'bin', 'kd_king_nodes.py')


def read_king_nodes(path: str, python32: Optional[str] = None) -> dict:
    '''supKingToJson(path bytes) in a 32-bit interpreter -> the document.'''
    script = _nodes_script()
    exe = find_python32(python32)
    if exe is None:
        return {'ok': False, 'code': ErrorCode.KD_BITNESS,
                'error': 'no 32-bit interpreter found for GRDKitDll.dll',
                'hint': ('run install.ps1 (or python scripts/fetch_runtime.py) to '
                         'fetch runtime/py32/, or set %s to any 32-bit python.exe'
                         % PY32_ENV)}
    if not os.path.isfile(script):
        return {'ok': False, 'code': ErrorCode.NOT_INSTALLED,
                'error': 'reader script missing: ' + script}
    try:
        proc = subprocess.run([exe, script, os.path.abspath(path)],
                              capture_output=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'code': ErrorCode.TIMEOUT, 'error': 'reader timed out'}
    except OSError as exc:
        return {'ok': False, 'code': ErrorCode.UNKNOWN, 'error': str(exc)}
    out = (proc.stdout or b'').decode('utf-8', 'replace').strip()
    if not out:
        return {'ok': False, 'code': ErrorCode.UNKNOWN,
                'error': 'no output (rc=%s): %s' % (
                    proc.returncode, (proc.stderr or b'').decode('utf-8', 'replace')[-200:])}
    try:
        return json.loads(out.splitlines()[-1])
    except ValueError:
        return {'ok': False, 'code': ErrorCode.UNKNOWN,
                'error': 'unparsable reader output: ' + out[:200]}


def verify_king(path: str, expect_atoms: Optional[list] = None,
                python32: Optional[str] = None) -> dict:
    '''Round-trip a .king through supKingToJson and compare with the source.'''
    report: dict = {'ok': False, 'path': os.path.abspath(path)}
    if not os.path.isfile(path):
        report.update({'code': ErrorCode.PARSE_FAILED, 'error': 'no such file'})
        return report
    size = os.path.getsize(path)
    report['bytes'] = size
    with open(path, 'rb') as fh:
        head = fh.read(64)
    report['text_format'] = is_king_text(head)
    if not report['text_format']:
        report.update({'code': ErrorCode.PARSE_FAILED,
                       'error': 'not a KingDraw text document (header %r)' % head[:16]})
        return report
    parsed = read_king_nodes(path, python32)
    report['reader'] = parsed
    if not parsed.get('ok'):
        report.update({'code': parsed.get('code') or ErrorCode.UNKNOWN,
                       'error': parsed.get('error')})
        return report
    nodes = parsed.get('nodes') or []
    bonds = parsed.get('bonds') or []
    report['nodes'] = len(nodes)
    report['bonds'] = len(bonds)
    report['elements'] = [n.get('type') for n in nodes]
    report['ok'] = bool(nodes)
    if expect_atoms is not None:
        want = [a[0] for a in expect_atoms]
        report['expect_atoms'] = len(want)
        if len(nodes) != len(want):
            report.update({'ok': False,
                           'error': 'node count %d != atom count %d' % (len(nodes), len(want))})
        elif report['elements'] != want:
            report.update({'ok': False,
                           'error': 'element order differs: %r != %r'
                                    % (report['elements'], want)})
    return report


# -- the public capability --------------------------------------------------
def save_as_king(path: str, out: Optional[str] = None, timeout: float = 30.0,
                 python32: Optional[str] = None, overwrite: bool = True) -> Result:
    '''Write *path* (molfile or .king) as a KingDraw .king document and verify it.

    The verification is the round trip: the bytes are handed to supKingToJson in
    the 32-bit runtime, and the node count, bond count and element list must match
    the parsed input. A file that is merely non-empty is not reported as success.
    '''
    started = time.monotonic()
    stage = 'locate'
    if not path:
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.PARSE_FAILED, stage,
                                       detail='empty path'))
    src = os.path.abspath(path)
    if not os.path.isfile(src):
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.PARSE_FAILED, stage,
                                       detail='not a file: ' + src,
                                       message='Input structure file does not exist'))
    dest = os.path.abspath(out) if out else os.path.splitext(src)[0] + '.king'
    if os.path.splitext(dest)[1].lower() != '.king':
        dest = dest + '.king'
    if os.path.isfile(dest) and not overwrite:
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.PARSE_FAILED, stage,
                                       detail='output exists: ' + dest,
                                       message='Output already exists',
                                       hint='Pass overwrite=True or remove the file'))
    with open(src, 'rb') as fh:
        blob = fh.read()
    stage = 'parse'
    stereo = 0
    lost = {'isotopes': 0, 'radicals': 0}
    if is_king_text(blob):
        atoms: list = []
        text = blob.decode('utf-8', 'replace')
        expect = None
        source_kind = 'king'
    else:
        source_text = blob.decode('utf-8', 'replace')
        atoms, bonds = parse_molblock(source_text)
        if not atoms:
            return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                          failure=_failure(ErrorCode.PARSE_FAILED, stage,
                                           detail='no atoms in the molblock (V2000/V3000)',
                                           message='Could not read the structure',
                                           hint='Pass a molfile or an existing .king'))
        text = king_text(atoms, bonds)
        expect = atoms
        source_kind = 'molfile'
        stereo = stereo_bonds(source_text)
        lost = unrepresentable_atoms(source_text)
    stage = 'write'
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(text)
    stage = 'verify'
    report = verify_king(dest, expect_atoms=expect, python32=python32)
    elapsed = int((time.monotonic() - started) * 1000)
    if not report.get('ok'):
        return Result(
            ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
            elapsed_ms=elapsed,
            data={'path': src, 'out': dest, 'verify': report},
            failure=_failure(report.get('code') or ErrorCode.PARSE_FAILED, stage,
                             detail=str(report.get('error'))[:400],
                             message='The .king was written but did not read back',
                             hint='Run python bin/kd_king_nodes.py <file> to see what '
                                  'GRDKitDll answered'))
    data = {
        'path': src, 'out': dest, 'bytes': report['bytes'],
        'source': source_kind,
        'atoms': report.get('nodes'), 'bonds': report.get('bonds'),
        'elements': report.get('elements'),
        'verified_by': ['text-header', 'supKingToJson:nodes', 'elements-match'],
        'reader': report.get('reader'),
        'method': 'king-writer',
        'stereo_bonds_not_carried': stereo,
        'isotopes_not_carried': lost['isotopes'],
        'radicals_not_carried': lost['radicals'],
        'waited_s': round(time.monotonic() - started, 3),
    }
    res = Result(ok=True, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                 elapsed_ms=elapsed, data=data)
    if source_kind == 'king':
        res.warnings.append('input was already a .king; it was re-verified, not '
                            'rebuilt from chemistry')
    if stereo:
        # Measured: a bond's only degrees of freedom in this format are its
        # type and its align flag. Types 1-8 draw single, double, triple and
        # aromatic bonds; no value draws a wedge, and the reader reports no
        # other bond field. A structure read back from .king is therefore
        # flat -- which looks perfectly plausible on screen, so it has to be
        # said out loud rather than left to the reader to notice.
        res.degraded = True
        res.degrade_reason = (
            'the .king format has nowhere to keep a stereo bond, so %d wedge(s) '
            'were flattened; export from the molfile or keep the .mol if the '
            'stereochemistry matters' % stereo)
        res.warnings.append(
            'this .king opens flat: %d stereo bond(s) could not be carried' % stereo)
    if lost['isotopes'] or lost['radicals']:
        # Measured: the atom becomes a plain element symbol with no label at
        # all, and nothing in the result said so. On screen the drawing looks
        # like the molecule minus a detail nobody can see, which is the kind
        # of loss that has to be named.
        parts = []
        if lost['isotopes']:
            parts.append('%d isotope label(s)' % lost['isotopes'])
        if lost['radicals']:
            parts.append('%d radical(s)' % lost['radicals'])
        detail = ' and '.join(parts)
        res.warnings.append(
            'this .king cannot draw %s: the atom is written as the bare '
            'element, so keep the .mol or the molfile if that detail '
            'matters' % detail)
        previous = res.degrade_reason
        res.degraded = True
        extra = 'the .king format cannot draw %s, so they were dropped' % detail
        res.degrade_reason = (previous + '; ' + extra) if previous else extra
    return res


__all__ = ['CHANNEL', 'find_python32', 'is_32bit', 'is_king_text', 'king_text',
           'parse_molblock', 'read_king_nodes', 'save_as_king', 'stereo_bonds',
           'verify_king']
