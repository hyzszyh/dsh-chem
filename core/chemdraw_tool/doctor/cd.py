'''ChemDraw channel doctor: what can this machine actually do over COM.'''

from __future__ import annotations

import os
import sys
import time
from typing import Any

from ..models import (
    DoctorReport, Failure, Capability, ErrorCode, ERROR_TEXT,
    EVIDENCE_MEASURED,
)

PROGIDS = [
    'ChemDraw_x64.Application',
    'ChemDraw.Application',
    'chemdraw',
]


def _failure(exc: BaseException, stage: str, code: str = ErrorCode.CD_NOT_RUNNING) -> Failure:
    msg, hint = ERROR_TEXT.get(code, ERROR_TEXT[ErrorCode.UNKNOWN])
    return Failure(
        code=code,
        message=msg,
        hint=hint,
        detail=type(exc).__name__ + ': ' + str(exc),
        channel='chemdraw',
        stage=stage,
    )


def _running_pids():
    '''Best-effort list of ChemDraw process ids, without extra dependencies.

    Returns None - never [] - when the process list cannot be read. The
    difference decides whether a user's unsaved document survives: an empty
    list means "nothing was running, so an instance that turns up afterwards is
    ours to close", while None means "unknown, close nothing".
    '''
    try:
        import csv
        import subprocess
        out = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq ChemDraw.exe', '/FO', 'CSV', '/NH'],
            capture_output=True, text=True, timeout=15,
        ).stdout
        pids = []
        # tasklist quotes every field and thousands-separates the memory column,
        # so split(',') mangles the row. The old code also stripped only single
        # quotes, leaving a leading double quote on the image name - which made
        # this function return [] on every machine, silently, forever.
        for row in csv.reader(out.splitlines()):
            if len(row) >= 2 and row[0].strip().lower().startswith('chemdraw'):
                pids.append(row[1].strip())
        return pids
    except Exception:
        return None


def inspect(start_if_needed: bool = True, quit_if_started: bool = True) -> DoctorReport:
    '''Probe the ChemDraw COM channel.

    Never quits a ChemDraw instance that was already running: a user may have
    unsaved work in it. Only instances this function started are shut down.
    '''
    report = DoctorReport(channel='chemdraw', available=False, evidence=EVIDENCE_MEASURED)
    t0 = time.time()

    if sys.maxsize <= 2 ** 32:
        report.failures.append(Failure(
            code=ErrorCode.NOT_INSTALLED,
            message='This interpreter is 32-bit; ChemDraw automation needs 64-bit',
            hint='Run with the 64-bit interpreter (system Python 3.11)',
            channel='chemdraw', stage='bitness',
        ))
        return report

    try:
        import pythoncom  # noqa: F401
        import win32com.client as win32
    except Exception as exc:
        report.failures.append(Failure(
            code=ErrorCode.NOT_INSTALLED,
            message='pywin32 is not installed for this interpreter',
            hint='pip install pywin32',
            detail=str(exc), channel='chemdraw', stage='import',
        ))
        return report

    pids_before = _running_pids()
    report.details['instances_before'] = pids_before

    app = None
    attached = False
    progid_used = ''
    try:
        for progid in PROGIDS:
            try:
                app = win32.GetActiveObject(progid)
                attached = True
                progid_used = progid
                break
            except Exception:
                continue
        if app is None and start_if_needed:
            for progid in PROGIDS:
                try:
                    app = win32.Dispatch(progid)
                    progid_used = progid
                    break
                except Exception:
                    continue
    except Exception as exc:
        report.failures.append(_failure(exc, 'connect'))

    if app is None:
        if not report.failures:
            report.failures.append(Failure(
                code=ErrorCode.CD_NOT_RUNNING,
                message='No ChemDraw COM object could be created',
                hint='Open ChemDraw by hand once, dismiss any dialog, retry',
                channel='chemdraw', stage='connect',
            ))
        report.details['elapsed_ms'] = int((time.time() - t0) * 1000)
        return report

    report.details['progid'] = progid_used
    report.details['attached'] = attached

    try:
        report.version = str(getattr(app, 'Name', '') or '')
    except Exception as exc:
        report.details['name_error'] = str(exc)
    for attr in ('FullName', 'Version', 'Build'):
        try:
            val = getattr(app, attr, '')
            if val:
                report.details[attr.lower()] = str(val)
        except Exception:
            pass

    try:
        docs = app.Documents
        report.details['documents_open'] = int(docs.Count)
        names = []
        for i in range(docs.Count):
            try:
                names.append(str(docs.Item(i + 1).Name))
            except Exception:
                pass
        report.details['document_names'] = names
    except Exception as exc:
        report.details['documents_error'] = str(exc)

    report.available = True
    report.capabilities = [
        Capability('draw', 'chemdraw', 'com-object', True, EVIDENCE_MEASURED),
        Capability('read', 'chemdraw', 'com-object', True, EVIDENCE_MEASURED),
        Capability('export', 'chemdraw', 'com-saveas', True, EVIDENCE_MEASURED),
        Capability('layout', 'chemdraw', 'com-object', True, EVIDENCE_MEASURED),
        Capability('check', 'chemdraw', 'com-object+rdkit', True, 'B'),
    ]

    # pids_before is None when the process list could not be read; treat that as
    # "unknown" rather than "none running". Quitting an instance we did not
    # start costs the user their unsaved work, so this comparison fails closed:
    # only a definitely-empty list allows the Quit below.
    started_by_us = (not attached) and pids_before == []
    if started_by_us and quit_if_started:
        try:
            app.Quit()
        except Exception:
            pass

    report.details['elapsed_ms'] = int((time.time() - t0) * 1000)
    report.details['started_by_us'] = started_by_us
    return report