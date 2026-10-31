'''Shared data models for chem-draw-tool.

Every channel (ChemDraw / KingDraw / rdkit) returns the same shapes, so callers do
not need to know which engine answered. Evidence levels travel with the payload:
a value measured on a real installation is tagged differently from one that is
only documented upstream.
'''

from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

Channel = str
Evidence = str

EVIDENCE_MEASURED = 'A'
EVIDENCE_SOURCE = 'B'
EVIDENCE_INFERRED = 'C'

PYTHON32_ENV = 'CHEMTOOL_PYTHON32'

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))


def bundled_python32(root: str = '') -> str:
    '''Where this checkout keeps the fetched 32-bit interpreter.'''
    base = os.path.abspath(root) if root else REPO_ROOT
    return os.path.join(base, 'runtime', 'py32', 'python.exe')


def unusable_python32_env() -> str:
    '''Why %s was not used, or '' when it is unset or points at a file.

    find_python32() skips an entry that is not a file and moves on, which is
    the right behaviour -- but when it then finds nothing, the reader needs
    to know their setting was the problem, not the machine.
    '''
    value = os.environ.get(PYTHON32_ENV, '')
    if not value:
        return ''
    if not os.path.isfile(value):
        return ('%s is set to %s, which is not a file' % (PYTHON32_ENV, value))
    return ''


def bitness_hint(root: str = '') -> str:
    '''What to do when this interpreter is 64-bit and KingDraw needs 32-bit.

    A clone has no runtime/ directory: install.ps1 fetches it and it is not
    committed. Measured on a fresh clone, 'run runtime/py32/python.exe' was
    the very first thing the tool printed and it named a file that was not
    there -- the reader is told to run something they do not have.
    '''
    if os.path.isfile(bundled_python32(root)):
        return 'Run with the bundled 32-bit runtime: runtime/py32/python.exe'
    base = os.path.abspath(root) if root else REPO_ROOT
    broken = unusable_python32_env()
    if os.path.isfile(os.path.join(base, 'install.ps1')):
        hint = ('This checkout has no 32-bit runtime yet: run install.ps1 (or '
                'python scripts/fetch_runtime.py) to fetch it, or set %s to any '
                '32-bit python.exe' % PYTHON32_ENV)
        return hint + ('; note: ' + broken if broken else '')
    # An installed layout (pip install .) has no install.ps1 to run, so
    # naming it would send the reader after a file that is not there -- the
    # same mistake as naming runtime/py32/python.exe in a fresh clone,
    # which is what this function was written for.
    hint = ('This build has no 32-bit runtime: set %s to a 32-bit python.exe '
            '(KingDraw ships an x86 DLL, so a 64-bit interpreter cannot load '
            'it)' % PYTHON32_ENV)
    broken = unusable_python32_env()
    if broken:
        hint += '; note: ' + broken
    return hint


EVIDENCE_NOTE = {
    'A': 'measured on this machine',
    'B': 'upstream source or documentation, not executed here',
    'C': 'design inference, not yet verified',
}


class ErrorCode:
    '''Stable error identifiers. Documentation and the CLI both key off these.'''

    CD_NOT_RUNNING = 'E01'
    CD_LICENSE = 'E02'
    KD_NOT_FOUND = 'E03'
    KD_BITNESS = 'E04'
    KD_CLI_DID_NOT_OPEN = 'E05'
    PARSE_FAILED = 'E06'
    IDENTITY_MISMATCH = 'E07'
    NOT_INSTALLED = 'E08'
    TIMEOUT = 'E09'
    # The ChemDraw connection stopped answering mid-call: usually a modal dialog.
    # Distinct from TIMEOUT (a subprocess budget) because the recovery path is
    # different: nothing is killed, the channel is marked wedged and probed later.
    COM_STALLED = 'E10'
    UNKNOWN = 'E99'


ERROR_TEXT = {
    ErrorCode.CD_NOT_RUNNING: (
        'ChemDraw is not reachable over COM: not running, or blocked by an activation dialog',
        'Open ChemDraw once by hand, dismiss any activation dialog, then run the cd doctor again',
    ),
    ErrorCode.CD_LICENSE: (
        'ChemDraw reports a licensing problem',
        'Check activation inside ChemDraw; without it COM cannot create documents',
    ),
    ErrorCode.KD_NOT_FOUND: (
        'KingDraw installation could not be located',
        'Pass --kingdraw-home pointing at the folder that holds GRDKitDll.dll',
    ),
    ErrorCode.KD_BITNESS: (
        'KingDraw core library is x86 but this interpreter is x64',
        bitness_hint(),
    ),
    ErrorCode.KD_CLI_DID_NOT_OPEN: (
        'KingDraw was launched with the file but never confirmed it opened',
        'The file is still on disk; open it by hand or raise --open-timeout',
    ),
    ErrorCode.PARSE_FAILED: (
        'The structure could not be parsed',
        'Check the SMILES or molfile syntax, or pass a file instead of a string',
    ),
    ErrorCode.IDENTITY_MISMATCH: (
        'The two channels disagree about this molecule',
        'Compare the raw payloads in the result; one side parsed the input differently',
    ),
    ErrorCode.NOT_INSTALLED: (
        'A required component is missing',
        'Run the doctor subcommand for that channel to see what to install',
    ),
    ErrorCode.TIMEOUT: (
        'The operation exceeded its time budget',
        'Retry; if it repeats, the external process is probably wedged',
    ),
    ErrorCode.COM_STALLED: (
        'ChemDraw stopped answering: it is probably showing a dialog',
        'Look at the ChemDraw window and dismiss the dialog (activation, save-as, '
        'export progress), then retry; the server probes the channel again by '
        'itself, and KingDraw keeps working meanwhile',
    ),
    ErrorCode.UNKNOWN: (
        'Unexpected failure',
        'See the detail field for the raw exception',
    ),
}


def _or_none(value):
    '''An empty string here means "we do not know", which JSON spells null.

    Measured: doctor --json said '"version": ""' while the human form said
    'version : unknown', and every healthy envelope carried
    '"degrade_reason": ""'. A script reading '' cannot tell "not known" from
    "known to be empty", so the machine form was disagreeing with the human
    one about a fact both were reporting.
    '''
    return None if value == '' else value


@dataclass
class Failure:
    code: str
    message: str
    hint: str = ''
    detail: str = ''
    channel: Optional[Channel] = None
    stage: str = ''

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        for key in ('hint', 'detail', 'stage'):
            out[key] = _or_none(out.get(key))
        return out


@dataclass
class Result:
    '''Uniform envelope for every call.

    degraded is never silent: if a call asked for one engine and got another,
    that fact and its reason travel with the payload.
    '''

    ok: bool
    data: Any = None
    failure: Optional[Failure] = None
    channel: Optional[Channel] = None
    degraded: bool = False
    degrade_reason: str = ''
    evidence: Evidence = EVIDENCE_MEASURED
    elapsed_ms: int = 0
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out['degrade_reason'] = _or_none(self.degrade_reason)
        out['evidence_note'] = EVIDENCE_NOTE.get(self.evidence, '')
        return out


ENVELOPE_KEYS = ('ok', 'failure', 'evidence')


def as_envelope(body, channel='cli', ok=None, elapsed_ms=0):
    '''Give a flat payload the uniform envelope without taking its fields away.

    Measured on this build: 18 of the 20 leaf commands answered
    {ok, channel, data, failure, degraded, elapsed_ms, warnings}, while
    `identity` and `doctor` answered a flat object with no `data` -- and so did
    the MCP tool chem_identity, which calls the adapter directly instead of
    going through the CLI. The rule every other surface teaches is 'read
    payload[data]', so the two commands and the one tool a newcomer meets first
    were exactly the ones where it raised KeyError. The audit notes had carried
    that as 'cognitive load'; it was a defect with a name.

    The flat keys stay where they were, so nothing that already reads
    payload['inchikey'] or payload['available'] breaks; the envelope keys are
    added around them. `ok` is passed in where the flat payload carries none
    (doctor says `available` instead, and defaulting to True would report a
    missing install as success).
    '''
    data = {key: value for key, value in body.items() if key not in ENVELOPE_KEYS}
    envelope = Result(
        ok=bool(body.get('ok', True) if ok is None else ok),
        channel=body.get('channel', channel),
        data=data,
        evidence=body.get('evidence', EVIDENCE_MEASURED),
        elapsed_ms=elapsed_ms,
        warnings=list(body.get('warnings') or []),
    ).to_dict()
    envelope.update(body)
    return envelope


@dataclass
class Capability:
    '''One row of the capability matrix: an action, on a channel, via a route.'''

    action: str
    channel: Channel
    route: str
    available: bool
    evidence: Evidence
    note: str = ''

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out['note'] = _or_none(self.note)
        return out


@dataclass
class DoctorReport:
    channel: Channel
    available: bool
    version: str = ''
    home: str = ''
    details: dict = field(default_factory=dict)
    capabilities: list = field(default_factory=list)
    failures: list = field(default_factory=list)
    evidence: Evidence = EVIDENCE_MEASURED

    def to_dict(self) -> dict[str, Any]:
        return {
            'channel': self.channel,
            'available': self.available,
            'version': _or_none(self.version),
            'home': _or_none(self.home),
            'details': self.details,
            'capabilities': [c.to_dict() for c in self.capabilities],
            'failures': [f.to_dict() for f in self.failures],
            'evidence': self.evidence,
            'evidence_note': EVIDENCE_NOTE.get(self.evidence, ''),
        }