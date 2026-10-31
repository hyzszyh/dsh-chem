r'''ChemDraw COM adapter: SMILES in, PNG out, one Result envelope.

Everything below was measured on ChemDraw 26.1.0.6327 (64-bit) on this machine.
The four findings that shaped the code are listed first because each one is a
trap that fails silently:

1. Structures are inserted through the *parameterised property* Data on the
   document's Objects collection. pywin32 cannot express a property-put with an
   argument, so the adapter reaches for IDispatch directly:

       raw = doc.Objects._oleobj_
       dispid = raw.GetIDsOfNames(0, 'Data')
       raw.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0, mime, payload)

   The payload must be bytes. A str payload is narrowed BSTR -> cp1252, so any
   non-cp1252 character arrives as '?', and the damage is irreversible.
   A wrong mime is *not* an error: the call returns S_OK and inserts nothing
   (or guesses the format from the bytes). Every insertion therefore asserts
   Atoms.Count grew before it is reported as success.

2. doc.SaveAs(Filename, Format, resolution, Width, Height) is a silent no-op
   for paths that contain non-ASCII characters: it returns None, raises
   nothing, and creates no file. Measured with the same document and the same
   format object, only the path differing:

       '%TEMP%\cdprobe\p_ascii.png'                  -> 312645 bytes
       '%TEMP%\cdprobe\中文测试\p_cn.png'              -> no file, no exception
       '<repo>\_probe_out\...'  -> no file, no exception

   This project lives under a Chinese path, so export() stages the file in an
   ASCII temp directory and copies it into place. GetShortPathName does not
   help: 8.3 name generation is disabled on this volume, so the "short" path
   comes back unchanged.

3. What SaveAs writes is proportional to Width/Height, not fitted to content:
   Width x resolution / 36 is the pixel width within about 3% (Width=144,
   resolution=300 -> 1234x934; Width=1200, resolution=300 -> 10034x7534).
   The real pixel size is read back from the PNG header instead of predicted.

4. Documents.Open() is a silent no-op unless a document window already exists:
   it returns None, raises nothing, and Documents.Count does not change. With a
   window open it still does nothing on this build (measured three times). The
   adapter never uses Open; it inserts payloads through Objects.Data.

document.Close(saveChanges, Filename) is also a silent no-op here: the call
returns, Documents.Count keeps its value and the atoms stay in the document.
Only Application.Quit() actually disposes of documents, so the adapter quits
instances it started and never quits an instance it attached to.

Routes, in the order this adapter prefers them (all but the last measured):

    smiles   Objects.Data('chemical/x-daylight-smiles')   7 atoms for phenol
    molblock Objects.Data('chemical/x-mdl-molfile')       keeps aromaticity
    cdxml    Objects.Data('text/xml')                     needs B/E + Order, and
                                                          Kekule bonds: a bare
                                                          Order="1.5" is silently
                                                          downgraded to single
    paste    clipboard CF_TEXT + doc.Paste()              works, 13 atoms for
                                                          aspirin, but goes
                                                          through the user's
                                                          clipboard
    objects  doc.MakeAtom() / doc.MakeBond(a1, a2)        works, one atom and
                                                          one bond per call
    open     app.Documents.Open(path)                     fails silently, see 4
'''

from __future__ import annotations

import os
import shutil
import struct
import tempfile
import time
from typing import Any, Optional

from ..limits import MAX_SMILES_CHARS, too_long
from ..models import (
    ERROR_TEXT, ErrorCode, EVIDENCE_MEASURED, Capability, Failure, Result,
)

CHANNEL = 'chemdraw'
PROGIDS = ('ChemDraw_x64.Application', 'ChemDraw.Application')

SMILES_MIME = 'chemical/x-daylight-smiles'
MOLFILE_MIME = 'chemical/x-mdl-molfile'
CDXML_MIME = 'text/xml'

DEFAULT_RESOLUTION = 300
DEFAULT_MARGIN_PT = 6.0
# Formats that can carry a dpi tag at all. Everything else (mol, cdxml, svg,
# emf) is a text or vector file: Pillow cannot open it, so asking is noise.
RASTER_EXTENSIONS = ('.png', '.tif', '.tiff', '.jpg', '.jpeg', '.bmp')
# 144 x 108 points at 300 dpi lands on 1234 x 934 pixels on this build, which is
# a sane figure-sized canvas. Width/Height are not pixels and not inches.
DEFAULT_SIZE = (144.0, 108.0)

# Measured: every route except 'open' inserts something for phenol.
ROUTES = ('smiles', 'molblock', 'cdxml', 'paste', 'objects')
DEFAULT_ROUTE = 'smiles'

_ASCII_TEMP_CANDIDATES = (
    None,               # tempfile.gettempdir()
    r'C:\Windows\Temp',
    r'C:\Temp',
)


def _failure(code: str, stage: str, detail: str = '', message: str = '',
             hint: str = '') -> Failure:
    d_msg, d_hint = ERROR_TEXT.get(code, ('', ''))
    return Failure(
        code=code, message=message or d_msg, hint=hint or d_hint,
        detail=detail, channel=CHANNEL, stage=stage,
    )


def _is_ascii(text: str) -> bool:
    return all(ord(ch) < 128 for ch in text)


def png_pixel_size(path: str) -> Optional[tuple]:
    '''(width, height) from a PNG header, without pulling in Pillow.'''
    try:
        with open(path, 'rb') as fh:
            head = fh.read(33)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    return struct.unpack('>II', head[16:24])


def pillow_error() -> Optional[str]:
    '''None when Pillow imports, else the reason it does not.

    Trim and dpi tagging both need it, and the two ways they can fail used to
    collapse into the same silent None: Pillow missing entirely, or an image
    that cannot be read back. The caller then saw trimmed=null beside a file
    that was still RGBA, padded and tagged 144 dpi, which looks like success
    and is not. The reason is carried out to the caller instead.
    '''
    try:
        import PIL  # noqa: F401
        return None
    except Exception as exc:
        return 'Pillow is not installed (%s: %s)' % (type(exc).__name__, exc)


def _dpi_tag(path: str):
    '''(dpi, error) for a PNG: the tag it carries, not the one requested.'''
    try:
        from PIL import Image
    except Exception:
        return None, pillow_error() or 'PIL is unavailable'
    try:
        with Image.open(path) as image:
            dpi = image.info.get('dpi') or (None, None)
        return (int(round(float(dpi[0]))) if dpi and dpi[0] else None), None
    except Exception as exc:
        return None, 'could not read %s back: %s: %s' % (
            os.path.basename(path), type(exc).__name__, exc)


def _trim_png(staged: str, in_place: Optional[str], pad_px: int = 0):
    '''(info, error): crop the transparent padding, flatten onto white.

    pad_px keeps that many pixels of paper around the ink. Cropping to the
    alpha bounding box exactly left the drawing flush with the file edge --
    measured on a 260x242 acetate export: ink on all four borders, and the
    C-C bond ending on the last column, which reads as a bond that was cut
    off rather than a methyl. A figure pasted into a manuscript needs paper
    around it, so the crop now leaves a margin (the caller picks its size).

    ChemDraw writes PNG as RGBA with a fully transparent background and black
    ink, tagged 144 dpi whatever resolution was asked for. Cropping the alpha
    bounding box removes the padding that Width/Height added, and flattening
    makes the file readable in tools that ignore alpha.

    error is None on success. Otherwise it names the real cause, because "no
    Pillow" and "this PNG is broken" need different fixes and must never look
    the same to the caller.
    '''
    try:
        from PIL import Image
    except Exception:
        return None, pillow_error() or 'PIL is unavailable'
    try:
        with Image.open(staged) as source:
            image = source.convert('RGBA')
            source_dpi = source.info.get('dpi')
        before = image.size
        box = image.split()[-1].getbbox()
        if box:
            if pad_px > 0:
                left, top, right, bottom = box
                box = (max(0, left - pad_px), max(0, top - pad_px),
                       min(before[0], right + pad_px),
                       min(before[1], bottom + pad_px))
            image = image.crop(box)
        flat = Image.new('RGB', image.size, (255, 255, 255))
        flat.paste(image, mask=image.split()[-1])
        out = in_place or staged
        # Keep the source dpi tag: it is wrong (144 whatever was asked for),
        # but silently dropping it would hide that fact from the caller.
        flat.save(out, format='PNG', dpi=source_dpi if source_dpi else None)
        return {'before_px': list(before), 'after_px': list(flat.size),
                'box': list(box) if box else None, 'pad_px': pad_px,
                'mode': 'RGB'}, None
    except Exception as exc:
        return None, 'trim failed on %s: %s: %s' % (
            os.path.basename(staged), type(exc).__name__, exc)


def _fit_resolution(wanted: int, width_pt: float, height_pt: float,
                    max_canvas_px: int) -> int:
    '''Largest dpi at or below wanted whose canvas stays inside the budget.

    A 315 x 399 pt region at 2183 dpi would be 19000 x 24000 px, which does
    not fit in a normal process, so the resolution steps down until it does.
    '''
    resolution = max(72, int(wanted))
    while (width_pt * resolution / 36.0) * (height_pt * resolution / 36.0) > max_canvas_px:
        resolution = int(resolution * 0.85)
        if resolution <= 72:
            return 72
    return resolution


def _too_long_failure(action: str, smiles: str) -> Failure:
    '''One wording for the size ceiling, so both channels say the same thing.'''
    return _failure(
        ErrorCode.PARSE_FAILED, action,
        detail='%d characters, limit %d' % (len(smiles), MAX_SMILES_CHARS),
        message='SMILES is longer than %d characters' % MAX_SMILES_CHARS,
        hint=('A string this long cannot be laid out here, and canonicalising it '
              'aborts the process with no message. Draw or import a smaller one.'))


def _canonical_smiles(smiles: str) -> Optional[str]:
    # Refuse before rdkit sees it: past ~2000 atoms the canonical writer walks
    # the graph recursively and takes the interpreter down (measured: exit
    # 3221225725, no output).
    if too_long(smiles):
        return None
    try:
        from rdkit import Chem
    except Exception:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:
        return None
    if mol is None:
        return None
    return Chem.MolToSmiles(mol)


def _formula(smiles: str) -> Optional[str]:
    try:
        from rdkit import Chem
        from rdkit.Chem import rdMolDescriptors
    except Exception:
        return None
    try:
        mol = Chem.MolFromSmiles(smiles)
    except Exception:
        return None
    if mol is None:
        return None
    return rdMolDescriptors.CalcMolFormula(mol)


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    if value is None:
        return ''
    return str(value)


class ChemDrawChannel:
    '''One ChemDraw application behind the shared Result envelope.'''

    channel = CHANNEL

    def __init__(self, progid: Optional[str] = None, visible: bool = True,
                 route: str = DEFAULT_ROUTE, keep_document: bool = True):
        self.progid = progid
        self.visible = visible
        self.route = route if route in ROUTES else DEFAULT_ROUTE
        self.keep_document = keep_document
        self._app: Any = None
        self._doc: Any = None
        self.attached = False
        self.started_by_us = False
        self.progid_used = ''
        self.warnings: list = []
        self._cleared: dict = {}

    # -- lifecycle ---------------------------------------------------------
    @property
    def connected(self) -> bool:
        return self._app is not None

    def connect(self) -> Result:
        '''Attach to a running ChemDraw, or start one and remember that we did.

        Dispatch is only a fallback: it spawns a second, invisible instance and
        every later call would land on that one instead of the window the user
        is looking at.
        '''
        started = time.time()
        if self._app is not None:
            return self._verdict(started, {'reused': True})

        try:
            import pythoncom  # noqa: F401
            import win32com.client as win32
        except Exception as exc:
            return Result(
                ok=False,
                failure=_failure(ErrorCode.NOT_INSTALLED, 'import',
                                 detail='%s: %s' % (type(exc).__name__, exc),
                                 message='pywin32 is not installed for this interpreter',
                                 hint='pip install pywin32'),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
            )

        progids = (self.progid,) if self.progid else PROGIDS
        for progid in progids:
            try:
                self._app = win32.GetActiveObject(progid)
                self.attached = True
                self.started_by_us = False
                self.progid_used = progid
                break
            except Exception:
                continue
        if self._app is None:
            for progid in progids:
                try:
                    self._app = win32.Dispatch(progid)
                    self.attached = False
                    self.started_by_us = True
                    self.progid_used = progid
                    break
                except Exception as exc:
                    last = exc
            if self._app is None:
                return Result(
                    ok=False,
                    failure=_failure(
                        ErrorCode.CD_NOT_RUNNING, 'connect',
                        detail='%s: %s' % (type(last).__name__, last)
                               if 'last' in dir() else 'no ProgID answered',
                        message='No ChemDraw COM object could be created',
                        hint='Open ChemDraw by hand once, dismiss any dialog, retry'),
                    channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
                )

        if self.visible:
            try:
                self._app.Visible = True
            except Exception as exc:
                self.warnings.append('Visible could not be set: %s' % exc)

        return self._verdict(started, {
            'attached': self.attached,
            'started_by_us': self.started_by_us,
            'progid': self.progid_used,
            'documents_open': self._doc_count(),
        })

    def _verdict(self, started: float, extra: Optional[dict] = None) -> Result:
        data = {'progid': self.progid_used, 'attached': self.attached,
                'started_by_us': self.started_by_us}
        if extra:
            data.update(extra)
        return Result(ok=self._app is not None, data=data, channel=CHANNEL,
                      evidence=EVIDENCE_MEASURED,
                      elapsed_ms=int((time.time() - started) * 1000),
                      warnings=list(self.warnings))

    def _doc_count(self) -> int:
        try:
            return int(self._app.Documents.Count)
        except Exception:
            return -1

    def close(self) -> Result:
        '''Quit only what we started; a user instance keeps its windows.

        document.Close() is a measured no-op on this build, so a document this
        adapter created inside a *user's* instance cannot be disposed of. The
        content is cleared instead, and the leftover window is reported.
        '''
        started = time.time()
        warnings = []
        if self._app is None:
            return Result(ok=True, data={'quit': False}, channel=CHANNEL,
                          elapsed_ms=0)
        quit_done = False
        if self.started_by_us:
            try:
                self._app.Quit()
                quit_done = True
            except Exception as exc:
                warnings.append('Quit failed: %s: %s' % (type(exc).__name__, exc))
        else:
            if self._doc is not None:
                cleared = self._clear_document(self._doc)
                if not cleared:
                    warnings.append(
                        'document.Close() is a no-op on this build, so the '
                        'untitled document created in the user instance stays '
                        'open (content cleared where possible)')
        self._app = None
        self._doc = None
        res = Result(ok=True, data={'quit': quit_done,
                                    'attached_instance_kept': self.attached},
                     channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                     elapsed_ms=int((time.time() - started) * 1000),
                     warnings=warnings)
        return res

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False

    # -- documents ---------------------------------------------------------
    def document(self) -> Result:
        '''Return the working document, creating one on first use.'''
        started = time.time()
        if self._app is None:
            res = self.connect()
            if not res.ok:
                return res
        if self._doc is not None:
            try:
                _ = self._doc.Atoms.Count
                return Result(ok=True, data={'document': 'reused',
                                             'atoms': int(self._doc.Atoms.Count)},
                              channel=CHANNEL, evidence=EVIDENCE_MEASURED)
            except Exception:
                self._doc = None
        before = self._doc_count()
        try:
            self._doc = self._app.Documents.Add()
        except Exception as exc:
            return Result(
                ok=False,
                failure=_failure(ErrorCode.UNKNOWN, 'add_document',
                                 detail='%s: %s' % (type(exc).__name__, exc),
                                 message='Documents.Add() failed'),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
            )
        after = self._doc_count()
        if after <= before:
            self.warnings.append(
                'Documents.Add() did not raise the document count (%d -> %d)'
                % (before, after))
        return Result(ok=True, data={'document': 'created', 'before': before,
                                     'after': after, 'atoms': int(self._doc.Atoms.Count)},
                      channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      elapsed_ms=int((time.time() - started) * 1000))

    def _counts(self, doc=None) -> dict:
        doc = doc if doc is not None else self._doc
        out = {}
        for name, coll in (('atoms', 'Atoms'), ('bonds', 'Bonds'),
                           ('groups', 'Groups')):
            try:
                out[name] = int(getattr(doc, coll).Count)
            except Exception:
                out[name] = -1
        return out

    def _clear_document(self, doc) -> bool:
        '''Empty the page: atoms first (bonds go with them), then leftovers.

        Deleting the atoms alone is not enough: a previous paste can leave a
        graphic behind (measured: a stray ring survived a page that reported
        0 atoms and still printed into the exported PNG), so the object
        collections are drained as well.
        '''
        try:
            n = int(doc.Atoms.Count)
        except Exception:
            return False
        for idx in range(n, 0, -1):
            try:
                doc.Atoms.Item(idx).Delete()
            except Exception:
                return False
        leftovers = {}
        for attr in ('Graphics', 'Splines', 'Captions', 'Pictures', 'Groups',
                     'AltGroups', 'Brackets', 'Arrows', 'Symbols'):
            try:
                collection = getattr(doc, attr)
            except Exception:
                continue
            for _ in range(200):
                try:
                    if int(collection.Count) <= 0:
                        break
                    collection.Item(1).Delete()
                    leftovers[attr] = leftovers.get(attr, 0) + 1
                except Exception:
                    leftovers[attr] = 'stuck'
                    break
        self._cleared = leftovers
        try:
            return int(doc.Atoms.Count) == 0
        except Exception:
            return False

    # -- insertion ---------------------------------------------------------
    def _raw_put(self, mime: str, payload: bytes) -> Result:
        '''Property-put Objects.Data(mime) = payload through IDispatch.'''
        started = time.time()
        try:
            import pythoncom
        except Exception as exc:  # pragma: no cover - guarded in connect()
            return Result(ok=False, failure=_failure(
                ErrorCode.NOT_INSTALLED, 'insert',
                detail='%s: %s' % (type(exc).__name__, exc)), channel=CHANNEL)
        try:
            raw = self._doc.Objects._oleobj_
            dispid = raw.GetIDsOfNames(0, 'Data')
            raw.Invoke(dispid, 0, pythoncom.DISPATCH_PROPERTYPUT, 0,
                       mime, bytes(payload))
        except Exception as exc:
            return Result(
                ok=False,
                failure=_failure(ErrorCode.PARSE_FAILED, 'insert',
                                 detail='%s: %s' % (type(exc).__name__, exc),
                                 message='ChemDraw rejected the %s payload' % mime),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
            )
        return Result(ok=True, data={'mime': mime, 'payload_bytes': len(payload)},
                      channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      elapsed_ms=int((time.time() - started) * 1000))

    def _guarded_insert(self, mime: str, payload: bytes, route: str) -> Result:
        '''Insert, then prove it landed: a wrong payload inserts nothing.'''
        started = time.time()
        doc = self.document()
        if not doc.ok:
            return doc
        before = self._counts()
        put = self._raw_put(mime, payload)
        if not put.ok:
            return put
        after = self._counts()
        data = {
            'route': route, 'mime': mime, 'payload_bytes': len(payload),
            'atoms_before': before['atoms'], 'atoms_after': after['atoms'],
            'bonds_after': after['bonds'], 'groups_after': after['groups'],
        }
        if after['atoms'] <= before['atoms']:
            return Result(
                ok=False, data=data,
                failure=_failure(
                    ErrorCode.PARSE_FAILED, 'insert',
                    detail='Atoms.Count stayed at %d after Objects.Data(%r); '
                           'the call returned S_OK and inserted nothing'
                           % (after['atoms'], mime),
                    message='ChemDraw accepted the call but inserted no atoms',
                    hint='Check the payload attributes: a CDXML bond needs '
                         'B/E atom ids and Order, and a missing atom id is '
                         'dropped silently'),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
            )
        return Result(ok=True, data=data, channel=CHANNEL,
                      evidence=EVIDENCE_MEASURED,
                      elapsed_ms=int((time.time() - started) * 1000),
                      warnings=list(self.warnings))

    def insert_smiles(self, smiles: str) -> Result:
        '''Preferred route: let ChemDraw parse the SMILES itself.'''
        return self._guarded_insert(SMILES_MIME, smiles.encode('utf-8'), 'smiles')

    def insert_molblock(self, molblock: str) -> Result:
        return self._guarded_insert(MOLFILE_MIME, molblock.encode('utf-8'),
                                    'molblock')

    def insert_rxn(self, block: str) -> Result:
        '''A $RXN block: measured to land 14 atoms, 10 bonds, 4 groups.

        ChemDraw lays the reaction out itself -- reactants, a plus sign, an
        arrow and the products -- which is why the page does not need graphics
        we would have to position by hand.
        '''
        return self._guarded_insert('chemical/x-mdl-rxnfile',
                                    block.encode('utf-8'), 'rxn')

    def insert_text(self, text: str, x: float, y: float,
                    size: float = 9.0) -> Result:
        '''One text object at page points (origin top-left, y down).

        Best effort: the payload is accepted but this build gives no way to
        read a text object back, so the caller must treat success as 'the call
        went through', not as 'the text is on the page'.
        '''
        if not text:
            return Result(ok=False, failure=_failure(
                ErrorCode.PARSE_FAILED, 'text', detail='empty text'),
                channel=CHANNEL)
        escaped = (text.replace('&', '&amp;').replace('<', '&lt;')
                   .replace('>', '&gt;'))
        cdxml = ('<CDXML><page id="1" BoundingBox="0 0 540 719.75" '
                 'BondLength="14.40"><t id="9001" p="%.2f %.2f" '
                 'Justification="Center"><s font="3" size="%g">%s</s></t>'
                 '</page></CDXML>' % (x, y, size, escaped))
        return self._raw_put('text/xml', cdxml.encode('utf-8'))

    def insert_label(self, text: str, x: float, y: float,
                     size: float = 10.0) -> Result:
        '''Real ChemDraw text, placed by atom coordinate.

        Two earlier routes measured useless for placement: a CDXML `<t p>` is
        accepted but its position is ignored (two different y values produced
        byte-identical images), and this object model exposes no AddText. A
        pseudo atom with Element=6 and LabelDisplay=Text does honour `p`, and
        ChemDraw draws the child <t> as text instead of the element symbol.
        It costs one atom on the page, so callers must subtract it.
        '''
        if not text:
            return Result(ok=False, failure=_failure(
                ErrorCode.PARSE_FAILED, 'label', detail='empty text'),
                channel=CHANNEL)
        escaped = (text.replace('&', '&amp;').replace('<', '&lt;')
                   .replace('>', '&gt;'))
        cdxml = ('<CDXML><page id="1" BoundingBox="0 0 540 719.75" '
                 'BondLength="14.40"><fragment id="2">'
                 '<n id="1" p="%.2f %.2f" Element="6" LabelDisplay="Text" '
                 'LabelJustification="Center">'
                 '<t><s font="3" size="%g">%s</s></t></n>'
                 '</fragment></page></CDXML>'
                 % (x, y, size, escaped))
        return self._guarded_insert('text/xml', cdxml.encode('utf-8'),
                                    'label')

    def atom_centres(self) -> Result:
        '''Centres of every atom on the page, in page points.'''
        started = time.time()
        doc = self.document()
        if not doc.ok:
            return doc
        try:
            count = int(self._doc.Atoms.Count)
        except Exception as exc:
            return Result(ok=False, failure=_failure(
                ErrorCode.UNKNOWN, 'centres',
                detail='%s: %s' % (type(exc).__name__, exc)), channel=CHANNEL)
        centres = []
        for index in range(1, count + 1):
            atom = self._doc.Atoms.Item(index)
            centres.append({
                'x': (float(atom.Left) + float(atom.Right)) / 2.0,
                'y': (float(atom.Top) + float(atom.Bottom)) / 2.0,
                'element': int(getattr(atom, 'Element', 0) or 0),
            })
        return Result(ok=True, data={'centres': centres, 'count': len(centres)},
                      channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      elapsed_ms=int((time.time() - started) * 1000))

    def insert_cdxml(self, text: str) -> Result:
        return self._guarded_insert(CDXML_MIME, text.encode('utf-8'), 'cdxml')

    def insert_cdxml_via_file(self, path: str, fmt: Any = None) -> Result:
        '''Documents.Open: measured to do nothing, kept for the record.

        Exact behaviour on this build: Documents.Open(path) returns None,
        raises nothing, and Documents.Count is unchanged, both with and without
        a document window open, with and without a Format argument.
        '''
        started = time.time()
        if self._app is None:
            res = self.connect()
            if not res.ok:
                return res
        before = self._doc_count()
        detail = ''
        try:
            if fmt is None:
                returned = self._app.Documents.Open(path)
            else:
                returned = self._app.Documents.Open(path, '', fmt)
        except Exception as exc:
            detail = '%s: %s' % (type(exc).__name__, exc)
            returned = None
        after = self._doc_count()
        if after > before:
            self._doc = self._app.Documents.Item(after)
            return Result(ok=True, data={'route': 'open', 'before': before,
                                         'after': after,
                                         'atoms': int(self._doc.Atoms.Count)},
                          channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                          elapsed_ms=int((time.time() - started) * 1000))
        return Result(
            ok=False,
            data={'route': 'open', 'before': before, 'after': after,
                  'returned': type(returned).__name__ if returned is not None else 'None'},
            failure=_failure(
                ErrorCode.PARSE_FAILED, 'open',
                detail=(detail + '; ' if detail else '')
                       + 'Documents.Open returned %s and Documents.Count stayed '
                         'at %d (silent no-op)'
                         % ('None' if returned is None else type(returned).__name__, after),
                message='Documents.Open() did nothing',
                hint='Insert the payload through Objects.Data instead; Open is '
                     'a no-op unless ChemDraw already has a document window'),
            channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
        )

    @staticmethod
    def _clipboard_text(clipboard):
        """Whatever text the user has on the clipboard right now, or None."""
        for fmt in (clipboard.CF_UNICODETEXT, clipboard.CF_TEXT):
            try:
                value = clipboard.GetClipboardData(fmt)
            except Exception:
                continue
            if isinstance(value, bytes):
                value = value.decode('utf-8', 'replace')
            if value:
                return str(value)
        return None

    @staticmethod
    def _restore_clipboard(clipboard, saved) -> bool:
        """Put the user's text back. Best effort: some formats cannot be rebuilt."""
        if saved is None:
            return False
        try:
            clipboard.OpenClipboard()
            try:
                clipboard.EmptyClipboard()
                clipboard.SetClipboardText(saved)
            finally:
                clipboard.CloseClipboard()
            return True
        except Exception:
            return False

    def insert_via_paste(self, payload: str) -> Result:
        '''Route 1 from the brief: clipboard CF_TEXT, then doc.Paste().

        Measured: a SMILES string on the clipboard pastes as a structure
        (aspirin -> 13 atoms / 13 bonds). The clipboard has to be overwritten
        to do it; the previous text is read first and put back afterwards, and
        the Result says whether that worked (clipboard_restored). It is still
        not the default route.
        '''
        started = time.time()
        doc = self.document()
        if not doc.ok:
            return doc
        try:
            import win32clipboard
        except Exception as exc:
            return Result(ok=False, failure=_failure(
                ErrorCode.NOT_INSTALLED, 'paste',
                detail='%s: %s' % (type(exc).__name__, exc)), channel=CHANNEL)
        before = self._counts()
        saved_text = None
        try:
            win32clipboard.OpenClipboard()
            try:
                saved_text = self._clipboard_text(win32clipboard)
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(payload)
            finally:
                win32clipboard.CloseClipboard()
        except Exception as exc:
            return Result(
                ok=False,
                failure=_failure(ErrorCode.UNKNOWN, 'paste',
                                 detail='%s: %s' % (type(exc).__name__, exc),
                                 message='the clipboard could not be written'),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
            )
        try:
            self._doc.Paste()
            time.sleep(0.2)
        except Exception as exc:
            return Result(
                ok=False,
                failure=_failure(ErrorCode.PARSE_FAILED, 'paste',
                                 detail='%s: %s' % (type(exc).__name__, exc),
                                 message='doc.Paste() failed'),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
            )
        # Paste() has read the clipboard by now, so hand the user's text back.
        restored = self._restore_clipboard(win32clipboard, saved_text)
        after = self._counts()
        data = {'route': 'paste', 'clipboard_format': 'CF_TEXT',
                'atoms_before': before['atoms'], 'atoms_after': after['atoms'],
                'bonds_after': after['bonds'],
                'clipboard_restored': restored}
        if after['atoms'] <= before['atoms']:
            return Result(ok=False, data=data, failure=_failure(
                ErrorCode.PARSE_FAILED, 'paste',
                detail='Atoms.Count stayed at %d after Paste()' % after['atoms'],
                message='nothing was pasted'), channel=CHANNEL,
                elapsed_ms=int((time.time() - started) * 1000))
        warnings = []
        if not restored:
            warnings.append('the clipboard was overwritten by this call and the '
                            'previous text could not be restored')
        return Result(ok=True, data=data, channel=CHANNEL,
                      evidence=EVIDENCE_MEASURED,
                      elapsed_ms=int((time.time() - started) * 1000),
                      warnings=warnings)

    def insert_via_objects(self, smiles: str) -> Result:
        '''Route 2 from the brief: MakeAtom()/MakeBond() one piece at a time.

        Coordinates come from RDKit 2D, scaled so one bond is BondLength points
        (ChemDraw's default 14.40). Element and charge are set through
        ElementNumber and Charge on each atom.
        '''
        started = time.time()
        doc = self.document()
        if not doc.ok:
            return doc
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem
        except Exception as exc:
            return Result(ok=False, failure=_failure(
                ErrorCode.NOT_INSTALLED, 'objects',
                detail='%s: %s' % (type(exc).__name__, exc),
                message='RDKit is needed to lay out the atoms'), channel=CHANNEL)
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return Result(ok=False, failure=_failure(
                ErrorCode.PARSE_FAILED, 'objects',
                detail='RDKit could not parse %r' % smiles), channel=CHANNEL)
        if mol.GetNumConformers() == 0:
            AllChem.Compute2DCoords(mol)
        conf = mol.GetConformer()
        n = mol.GetNumAtoms()
        scale, margin = 14.4, 60.0
        xs = [conf.GetAtomPosition(i).x for i in range(n)]
        ys = [conf.GetAtomPosition(i).y for i in range(n)]
        minx, maxy = min(xs), max(ys)
        made = []
        errors = []
        try:
            for i in range(n):
                atom = mol.GetAtomWithIdx(i)
                cd_atom = self._doc.MakeAtom()
                x = (xs[i] - minx) * scale + margin
                y = (maxy - ys[i]) * scale + margin
                # Position is a by-value COM point: mutating the returned
                # copy changes nothing until the whole point is assigned back.
                # Measured: a1.Position.X = 100 leaves X at 0; assigning the
                # hand-built point back moves the atom to (100, 120).
                try:
                    point = cd_atom.Position
                    point.X = float(x)
                    point.Y = float(y)
                    cd_atom.Position = point
                except Exception as exc:
                    errors.append('Position: %s: %s' % (type(exc).__name__, exc))
                try:
                    cd_atom.ElementNumber = int(atom.GetAtomicNum())
                except Exception as exc:
                    errors.append('ElementNumber: %s' % exc)
                charge = atom.GetFormalCharge()
                if charge:
                    try:
                        cd_atom.Charge = float(charge)
                    except Exception as exc:
                        errors.append('Charge: %s' % exc)
                made.append(cd_atom)
            for bond in mol.GetBonds():
                self._doc.MakeBond(made[bond.GetBeginAtomIdx()],
                                   made[bond.GetEndAtomIdx()])
        except Exception as exc:
            return Result(
                ok=False,
                failure=_failure(ErrorCode.UNKNOWN, 'objects',
                                 detail='%s: %s' % (type(exc).__name__, exc),
                                 message='MakeAtom/MakeBond failed'),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
            )
        counts = self._counts()
        data = {'route': 'objects', 'expected_atoms': n,
                'atoms_after': counts['atoms'], 'bonds_after': counts['bonds']}
        if errors:
            data['property_errors'] = errors[:6]
        if counts['atoms'] < n:
            return Result(ok=False, data=data, failure=_failure(
                ErrorCode.PARSE_FAILED, 'objects',
                detail='expected %d atoms, Atoms.Count is %d'
                       % (n, counts['atoms']),
                message='MakeAtom() did not create every atom'),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000))
        return Result(ok=True, data=data, channel=CHANNEL,
                      evidence=EVIDENCE_MEASURED,
                      elapsed_ms=int((time.time() - started) * 1000),
                      warnings=list(self.warnings))

    # -- drawing -----------------------------------------------------------
    # -- editing -----------------------------------------------------------
    def modify(self, replace: Optional[str] = None, clear: bool = False,
               delete_atom: Optional[int] = None,
               delete_object: Optional[int] = None) -> Result:
        '''Change what is on the CURRENT page instead of adding another one.

        draw_smiles() always opens a fresh document, which is right when the
        job is "draw this molecule" and wrong when the job is "change the one
        already on screen". This method is the second case: it edits in place.

        Measured quirks it works around:

        - Deleting atoms takes their bonds with them, but a previous paste can
          leave a graphic behind that still prints even when the page reports
          zero atoms, so clearing drains the object collections too.
        - Item() is 1-based and deleting from the front renumbers everything
          after it, so deletions run back to front.
        '''
        started = time.time()
        if not (replace or clear or delete_atom or delete_object):
            return Result(ok=False, failure=_failure(
                ErrorCode.UNKNOWN, 'modify',
                detail='nothing to do',
                message='modify needs at least one of replace / clear / delete-atom / delete-object',
                hint='Pick an action; an empty modify would just be a slow no-op'),
                channel=CHANNEL)

        doc = self.document()
        if not doc.ok:
            return doc

        before = self._counts()
        actions = []

        if delete_atom is not None:
            try:
                total = int(self._doc.Atoms.Count)
            except Exception as exc:
                return Result(ok=False, failure=_failure(
                    ErrorCode.UNKNOWN, 'modify',
                    detail='%s: %s' % (type(exc).__name__, exc),
                    message='cannot read the atom count'), channel=CHANNEL)
            if not (1 <= int(delete_atom) <= total):
                return Result(ok=False, failure=_failure(
                    ErrorCode.UNKNOWN, 'modify',
                    detail='delete-atom %s outside 1..%d' % (delete_atom, total),
                    message='No atom with that number on the page',
                    hint='Atoms are numbered from 1; read the page first to see how many there are'),
                    channel=CHANNEL)
            try:
                self._doc.Atoms.Item(int(delete_atom)).Delete()
                actions.append('deleted atom %d' % delete_atom)
            except Exception as exc:
                return Result(ok=False, failure=_failure(
                    ErrorCode.UNKNOWN, 'modify',
                    detail='%s: %s' % (type(exc).__name__, exc),
                    message='Deleting the atom failed'), channel=CHANNEL)

        if delete_object is not None:
            deleted = False
            for attr in ('Graphics', 'Pictures', 'Captions', 'Splines'):
                try:
                    collection = getattr(self._doc, attr)
                    if int(collection.Count) >= int(delete_object):
                        collection.Item(int(delete_object)).Delete()
                        actions.append('deleted %s %d' % (attr, delete_object))
                        deleted = True
                        break
                except Exception:
                    continue
            if not deleted:
                return Result(ok=False, failure=_failure(
                    ErrorCode.UNKNOWN, 'modify',
                    detail='no object collection had an item %s' % delete_object,
                    message='No object with that number on the page'),
                    channel=CHANNEL)

        if replace or clear:
            if not self._clear_document(self._doc):
                return Result(ok=False, failure=_failure(
                    ErrorCode.UNKNOWN, 'modify',
                    detail='the page still holds atoms after clearing',
                    message='Could not empty the page'),
                    channel=CHANNEL,
                    elapsed_ms=int((time.time() - started) * 1000))
            actions.append('cleared the page')

        if replace:
            if too_long(replace):
                return Result(ok=False, failure=_too_long_failure('modify', replace),
                              channel=CHANNEL,
                              elapsed_ms=int((time.time() - started) * 1000))
            canonical = _canonical_smiles(replace)
            if canonical is None:
                return Result(ok=False, failure=_failure(
                    ErrorCode.PARSE_FAILED, 'modify',
                    detail='RDKit could not parse %r' % replace,
                    message='The replacement structure could not be parsed',
                    hint='Check the SMILES syntax'), channel=CHANNEL)
            inserted = self.insert_smiles(canonical)
            if not inserted.ok:
                return inserted
            actions.append('inserted the replacement')

        after = self._counts()
        return Result(
            ok=True,
            data={'actions': actions, 'before': before, 'after': after,
                  'cleared_leftovers': getattr(self, '_cleared', None)},
            channel=CHANNEL,
            elapsed_ms=int((time.time() - started) * 1000),
        )

    def draw_smiles(self, smiles: str, route: Optional[str] = None) -> Result:
        '''SMILES -> a structure on the page, by the best route available.'''
        started = time.time()
        route = route or self.route
        if route not in ROUTES:
            return Result(ok=False, failure=_failure(
                ErrorCode.PARSE_FAILED, 'draw',
                detail='unknown route %r; known: %s' % (route, ', '.join(ROUTES)),
                message='unknown draw route'), channel=CHANNEL)

        if too_long(smiles):
            return Result(ok=False, failure=_too_long_failure('draw', smiles),
                          channel=CHANNEL,
                          elapsed_ms=int((time.time() - started) * 1000))
        canonical = _canonical_smiles(smiles)
        if canonical is None:
            return Result(
                ok=False,
                failure=_failure(ErrorCode.PARSE_FAILED, 'draw',
                                 detail='RDKit could not parse %r' % smiles[:120],
                                 message='The structure could not be parsed',
                                 hint='Check the SMILES syntax'),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
            )

        # Every drawing gets its own document. Deleting the content of a used
        # document is not reliable here: measured, Graphics.Item(1).Delete()
        # does nothing while the collection grows 1 -> 2 -> 3 across three
        # drawings, and the leftovers stretch the exported frame (ink 550x458
        # for a fresh page versus 2373x3090 after three). Document.Close() is a
        # no-op too, so the untitled windows stay open in a user instance; that
        # is reported by close() instead of being hidden.
        if self._doc is not None:
            self._doc = None
        doc = self.document()
        if not doc.ok:
            return doc

        if route == 'smiles':
            insert = self.insert_smiles(canonical)
        elif route == 'molblock':
            molblock = self._molblock(canonical)
            if molblock is None:
                return Result(ok=False, failure=_failure(
                    ErrorCode.PARSE_FAILED, 'draw',
                    detail='RDKit produced no molblock for %r' % smiles),
                    channel=CHANNEL)
            insert = self.insert_molblock(molblock)
        elif route == 'cdxml':
            insert = self.insert_cdxml(self._cdxml(canonical))
        elif route == 'paste':
            insert = self.insert_via_paste(smiles)
        else:
            insert = self.insert_via_objects(canonical)
        if not insert.ok:
            return insert

        check = self.read_current('smiles')
        readback = (check.data or {}).get('text', '') if check.ok else ''
        insert.data.update({
            'route': route,
            'input_smiles': smiles,
            'canonical_smiles': canonical,
            'readback_smiles': readback,
            'roundtrip': 'exact',
        })
        if readback:
            back = _canonical_smiles(readback)
            if back != canonical:
                same_formula = _formula(readback) == _formula(canonical)
                insert.data['roundtrip'] = ('formula-only' if same_formula
                                            else 'differs')
                insert.warnings.append(
                    'read-back SMILES differs: %r vs %r (%s)'
                    % (back or readback, canonical,
                       'same formula, different depiction'
                       if same_formula else 'formula differs too'))
                if not same_formula:
                    insert.evidence = EVIDENCE_MEASURED
        insert.elapsed_ms = int((time.time() - started) * 1000)
        return insert

    def _molblock(self, smiles: str) -> Optional[str]:
        try:
            from rdkit import Chem
            from rdkit.Chem import AllChem
        except Exception:
            return None
        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            return None
        if mol.GetNumConformers() == 0:
            AllChem.Compute2DCoords(mol)
        return Chem.MolToMolBlock(mol)

    def _cdxml(self, smiles: str) -> str:
        '''Minimal CDXML that this build actually accepts.

        chemdraw_tool.cdxml cannot be reused as-is: it writes the bond order
        into B and the atom ids into p0/p1, while CDXML needs B/E to hold the
        two atom ids and Order to hold the order. This build silently drops
        such a fragment (0 atoms, no error), so the payload is rebuilt here.
        Bonds are written Kekule: a bare Order="1.5" is downgraded to a single
        bond unless a matching <graphic OvalType="Circle"> comes with it.
        '''
        from rdkit import Chem
        from rdkit.Chem import AllChem

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            raise ValueError('RDKit could not parse %r' % smiles)
        if mol.GetNumConformers() == 0:
            AllChem.Compute2DCoords(mol)
        Chem.Kekulize(mol, clearAromaticFlags=True)
        conf = mol.GetConformer()
        n = mol.GetNumAtoms()
        xs = [conf.GetAtomPosition(i).x for i in range(n)]
        ys = [conf.GetAtomPosition(i).y for i in range(n)]
        minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
        scale, margin = 14.4, 30.0
        atoms = []
        for i in range(n):
            atom = mol.GetAtomWithIdx(i)
            x = (xs[i] - minx) * scale + margin
            y = (maxy - ys[i]) * scale + margin
            attrs = ['id="%d"' % (i + 1), 'p="%.2f %.2f"' % (x, y),
                     'Element="%d"' % atom.GetAtomicNum()]
            if atom.GetFormalCharge():
                attrs.append('Charge="%d"' % atom.GetFormalCharge())
            atoms.append('<n ' + ' '.join(attrs) + '/>')
        bonds = []
        for k, bond in enumerate(mol.GetBonds()):
            order = bond.GetBondTypeAsDouble()
            bonds.append('<b id="%d" B="%d" E="%d" Order="%s"/>' % (
                n + k + 1, bond.GetBeginAtomIdx() + 1,
                bond.GetEndAtomIdx() + 1,
                ('%.1f' % order).rstrip('0').rstrip('.')))
        width = (maxx - minx) * scale + 2 * margin
        height = (maxy - miny) * scale + 2 * margin
        return ('<CDXML><page id="1" BoundingBox="0 0 %.2f %.2f" '
                'BondLength="14.40"><fragment id="2">%s%s</fragment></page></CDXML>'
                % (width, height, ''.join(atoms), ''.join(bonds)))

    # -- reading -----------------------------------------------------------
    def read_current(self, kind: str = 'smiles') -> Result:
        '''Read the page back through Objects.GetData.

        Measured: 'chemical/x-daylight-smiles' answers 'Oc1ccccc1' for phenol;
        'chemical/x-mdl-molfile' answers a 735-byte V2000 block; 'text/xml'
        answers the whole page as CDXML.
        '''
        started = time.time()
        mime = {'smiles': SMILES_MIME, 'molfile': MOLFILE_MIME,
                'cdxml': CDXML_MIME}.get(kind, kind)
        doc = self.document()
        if not doc.ok:
            return doc
        try:
            value = self._doc.Objects.GetData(mime)
        except Exception as exc:
            return Result(
                ok=False,
                failure=_failure(ErrorCode.PARSE_FAILED, 'read',
                                 detail='%s: %s' % (type(exc).__name__, exc),
                                 message='GetData(%r) failed' % mime),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
            )
        text = _as_text(value)
        res = Result(ok=bool(text), data={'mime': mime, 'text': text,
                                          'chars': len(text)},
                     channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                     elapsed_ms=int((time.time() - started) * 1000))
        if not text:
            res.failure = _failure(
                ErrorCode.PARSE_FAILED, 'read',
                detail='GetData(%r) returned nothing' % mime,
                message='the drawing is empty')
        return res

    # -- export ------------------------------------------------------------
    def export_types(self) -> Result:
        """What SaveAs will accept, keyed by extension."""
        started = time.time()
        if self._app is None:
            res = self.connect()
            if not res.ok:
                return res
        rows = []
        try:
            collection = self._app.ExportDataTypes
            for i in range(int(collection.Count)):
                item = collection.Item(i + 1)
                rows.append({'index': i + 1, 'mime': _as_text(item.MIME),
                             'extension': _as_text(item.Extension),
                             'valid': bool(item.Valid)})
        except Exception as exc:
            return Result(ok=False, failure=_failure(
                ErrorCode.UNKNOWN, 'export_types',
                detail='%s: %s' % (type(exc).__name__, exc)),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000))
        return Result(ok=True, data=rows, channel=CHANNEL,
                      evidence=EVIDENCE_MEASURED,
                      elapsed_ms=int((time.time() - started) * 1000))

    def find_export_type(self, fmt: str):
        '''Pick an ExportDataType by extension, never by index.

        Measured indices on this build: png = 49 (image/x-png) and 50
        (image/png), svg = 47, emf = 43/44, jpg = 46, tif = 51. They are
        reported, not relied on: indexes drift between installations.
        '''
        want = fmt.lower().lstrip('.')
        types = self.export_types()
        if not types.ok:
            return types
        matches = [row for row in types.data
                   if row['extension'].lower().lstrip('.') == want and row['valid']]
        if not matches:
            return Result(ok=False, failure=_failure(
                ErrorCode.NOT_INSTALLED, 'export_format',
                detail='no valid ExportDataType with extension %r; available: %s'
                       % (want, ', '.join(sorted({r['extension'] for r in types.data}))),
                message='ChemDraw cannot export %s here' % want.upper()))
        self._export_type = (matches[0], matches)
        return Result(ok=True, data=matches, channel=CHANNEL,
                      evidence=EVIDENCE_MEASURED)

    def _stage_dir(self) -> Optional[str]:
        '''An ASCII temp dir: SaveAs silently skips non-ASCII paths.'''
        for base in _ASCII_TEMP_CANDIDATES:
            try:
                candidate = tempfile.gettempdir() if base is None else base
                if not os.path.isdir(candidate) or not _is_ascii(candidate):
                    continue
                return tempfile.mkdtemp(prefix='cdstage_', dir=candidate)
            except Exception:
                continue
        return None

    def content_bounds(self) -> Result:
        """Bounding box of everything drawn, in page points from the origin.

        Measured: the page is 540 x 719.75 pt with the origin at the top-left
        and y growing downwards; a SMILES insert lands near the middle of the
        page (aspirin: x 236.8..303.0, y 333.0..387.4). Nothing in SaveAs takes
        an offset, so this is only useful for choosing Width/Height.
        """
        started = time.time()
        doc = self.document()
        if not doc.ok:
            return doc
        try:
            count = int(self._doc.Atoms.Count)
        except Exception as exc:
            return Result(ok=False, failure=_failure(
                ErrorCode.UNKNOWN, 'bounds',
                detail='%s: %s' % (type(exc).__name__, exc)), channel=CHANNEL)
        if count == 0:
            return Result(ok=False, failure=_failure(
                ErrorCode.PARSE_FAILED, 'bounds',
                detail='Atoms.Count is 0; the page is empty',
                message='nothing was drawn'), channel=CHANNEL)
        left = top = float('inf')
        right = bottom = float('-inf')
        for index in range(1, count + 1):
            atom = self._doc.Atoms.Item(index)
            left = min(left, float(atom.Left))
            right = max(right, float(atom.Right))
            top = min(top, float(atom.Top))
            bottom = max(bottom, float(atom.Bottom))
        return Result(ok=True, data={
            'left': left, 'right': right, 'top': top, 'bottom': bottom,
            'width_pt': right - left, 'height_pt': bottom - top,
            'atoms': count,
            'page': {'width': float(self._doc.Width),
                     'height': float(self._doc.Height)},
        }, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
            elapsed_ms=int((time.time() - started) * 1000))

    def export(self, path: str, fmt: str = 'png',
               resolution: Optional[int] = None,
               width: Optional[float] = None,
               height: Optional[float] = None,
               margin: float = DEFAULT_MARGIN_PT,
               target_px_width: Optional[int] = None,
               trim: bool = True,
               trim_pad_pt: float = 2.0) -> Result:
        '''SaveAs the current page, working around three measured traps.

        1. A non-ASCII destination is a silent no-op, so the file is staged in
           an ASCII temp directory and copied into place.
        2. The drawing is centred at its natural size of resolution / 36 pixels
           per point; Width/Height only add padding, and a region smaller than
           the drawing clips it. Measured ink width at resolution 300 for the
           same 66.2 pt wide aspirin: 550 px with Width 78.2, 550 px with Width
           234.7, 550 px with Width 309, 508 px with Width 66.2 (clipped). The
           defaults therefore follow the drawing's own aspect ratio, and a
           wanted pixel width is solved as resolution = px * 36 / width_pt.
        3. resolution does scale the drawing, so a wanted pixel size is solved
           from it: resolution = target_px_width * 36 / content_width_pt.

        trim=True crops the transparent padding away and flattens the RGBA
        result onto white, which is what a publisher wants to look at.
        '''
        started = time.time()
        doc = self.document()
        if not doc.ok:
            return doc
        if self._counts()['atoms'] <= 0:
            return Result(
                ok=False,
                failure=_failure(ErrorCode.PARSE_FAILED, 'export',
                                 detail='Atoms.Count is 0; nothing to export',
                                 message='the page is empty',
                                 hint='Call draw_smiles first'),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000))
        picked = self.find_export_type(fmt)
        if not picked.ok:
            return picked
        chosen, all_matches = picked.data[0], picked.data
        fmt_obj = self._export_format_object(chosen['index'])
        if fmt_obj is None:
            return Result(ok=False, failure=_failure(
                ErrorCode.UNKNOWN, 'export',
                detail='ExportDataTypes.Item(%d) could not be fetched'
                       % chosen['index']), channel=CHANNEL)

        bounds = self.content_bounds()
        content_w = bounds.data['width_pt'] if bounds.ok else None
        content_h = bounds.data['height_pt'] if bounds.ok else None
        warnings = list(self.warnings)
        solved_res = resolution
        if target_px_width and content_w:
            solved_res = int(round(target_px_width * 36.0 / content_w))
            solved_res = max(72, min(solved_res, 4800))
            warnings.append(
                'resolution solved from %d px / %.1f pt -> %d dpi'
                % (target_px_width, content_w, solved_res))
        resolution = int(solved_res or DEFAULT_RESOLUTION)
        # Measured: the drawing is rendered at its natural size of
        # resolution / 36 pixels per point and Width/Height only add padding;
        # a region smaller than the drawing clips it. Where the drawing sits in
        # the region is not stable across documents (a fresh page centres it,
        # a page that has been drawn on several times anchors it near the page
        # origin), so the default region covers both cases: at least the
        # drawing's own size, and at least its page position plus a margin.
        if width is None:
            width = (max(content_w + 2 * margin, bounds.data['right'] + margin)
                     if content_w else DEFAULT_SIZE[0])
        if height is None:
            height = (max(content_h + 2 * margin, bounds.data['bottom'] + margin)
                      if content_h else DEFAULT_SIZE[1])

        extension = '.' + chosen['extension'].lower().lstrip('.')
        destination = os.path.abspath(path)
        if not destination.lower().endswith(extension):
            destination += extension
        directory = os.path.dirname(destination) or os.getcwd()
        try:
            os.makedirs(directory, exist_ok=True)
        except Exception as exc:
            return Result(ok=False, failure=_failure(
                ErrorCode.UNKNOWN, 'export',
                detail='%s: %s' % (type(exc).__name__, exc),
                message='the output directory could not be created'),
                channel=CHANNEL)

        staged_from = None
        target = destination
        if not _is_ascii(destination):
            stage = self._stage_dir()
            if stage is None:
                return Result(
                    ok=False,
                    failure=_failure(
                        ErrorCode.UNKNOWN, 'export',
                        detail='no ASCII-only temp directory was usable; '
                               'SaveAs cannot write %r' % destination,
                        message='the destination path has non-ASCII characters '
                                'and no staging directory was available',
                        hint='Point --out at an ASCII path, or set TEMP to an '
                             'ASCII directory'),
                    channel=CHANNEL,
                    elapsed_ms=int((time.time() - started) * 1000))
            staged_from = stage
            target = os.path.join(stage, 'page' + extension)

        try:
            self._doc.SaveAs(target, fmt_obj, int(resolution),
                             float(width), float(height))
        except Exception as exc:
            if staged_from:
                # The staging directory was created for this call only; an
                # exception here used to leave an empty cdstage_* folder behind.
                shutil.rmtree(staged_from, ignore_errors=True)
            return Result(
                ok=False,
                failure=_failure(ErrorCode.UNKNOWN, 'export',
                                 detail='%s: %s' % (type(exc).__name__, exc),
                                 message='SaveAs raised'),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000))
        if not os.path.exists(target) or os.path.getsize(target) == 0:
            if staged_from:
                shutil.rmtree(staged_from, ignore_errors=True)
            return Result(
                ok=False,
                failure=_failure(
                    ErrorCode.UNKNOWN, 'export',
                    detail='SaveAs returned without writing %r '
                           '(exists=%s, size=%s); this build silently skips '
                           'paths with non-ASCII characters'
                           % (target, os.path.exists(target),
                              os.path.getsize(target) if os.path.exists(target) else None),
                    message='ChemDraw wrote no file',
                    hint='Retry with an ASCII output path'),
                channel=CHANNEL, elapsed_ms=int((time.time() - started) * 1000),
                data={'format': chosen, 'resolution': resolution,
                      'width': width, 'height': height, 'target': target})

        staged_bytes = os.path.getsize(target)
        # Copy into place before trimming, so a failed trim still leaves the
        # raw export on disk for the caller to fall back to.
        if staged_from is not None:
            try:
                shutil.copyfile(target, destination)
            except Exception as exc:
                return Result(ok=False, failure=_failure(
                    ErrorCode.UNKNOWN, 'export',
                    detail='%s: %s' % (type(exc).__name__, exc),
                    message='the staged file could not be copied into place',
                    hint='The file is still at ' + target), channel=CHANNEL)
            finally:
                shutil.rmtree(staged_from, ignore_errors=True)

        trim_info = None
        trim_error = None
        if trim and extension == '.png':
            # 2 pt of paper at the asked-for resolution: the smallest margin
            # that stops a terminal bond from sitting on the border. At 300 dpi
            # that is 17 px, about 5% of a small structure. export_figure asks
            # for 0: it sizes the region to a requested physical width, so a
            # second margin there makes the paper width drift (measured: an
            # 85 mm figure came back 79.6 mm).
            pad_px = (int(round(float(resolution) / 36.0 * trim_pad_pt))
                      if resolution and trim_pad_pt else 0)
            trim_info, trim_error = _trim_png(destination, destination, pad_px)
        if trim_error:
            # The caller asked for a cropped RGB PNG. Shipping the raw RGBA
            # export instead is not a cosmetic downgrade but a different file:
            # padded, transparent, tagged 144 dpi. Say so instead of returning ok.
            missing = pillow_error() is not None
            return Result(
                ok=False,
                failure=_failure(
                    ErrorCode.NOT_INSTALLED if missing else ErrorCode.UNKNOWN,
                    'trim',
                    message=('trimming needs Pillow, which is not installed'
                             if missing else
                             'the exported PNG could not be trimmed'),
                    detail=trim_error,
                    hint=('pip install pillow' if missing else
                          'The untrimmed export is still at ' + destination)),
                channel=CHANNEL,
                elapsed_ms=int((time.time() - started) * 1000),
                data={'path': destination, 'raw_path': destination,
                      'raw_bytes': staged_bytes, 'trim_error': trim_error,
                      'format': chosen, 'resolution': int(resolution)})

        size = os.path.getsize(destination)
        pixels = png_pixel_size(destination) if extension == '.png' else None
        if staged_from is not None:
            warnings.append(
                'exported through an ASCII staging directory: SaveAs ignores '
                'non-ASCII paths')
        # A dpi tag only exists inside a raster image. Asking for one after a
        # mol/cdxml/svg export produced 'UnidentifiedImageError' warnings that
        # read like a fault in the export itself (measured with --format mol:
        # ok:true next to 'the dpi tag could not be read').
        if extension in RASTER_EXTENSIONS:
            dpi_tag, dpi_error = _dpi_tag(destination)
        else:
            dpi_tag, dpi_error = None, None
        if dpi_error:
            warnings.append('the dpi tag could not be read: ' + dpi_error)
        physical_mm = None
        if pixels and dpi_tag:
            physical_mm = round(pixels[0] / float(dpi_tag) * 25.4, 1)
        return Result(
            ok=size > 0,
            data={
                'path': destination, 'bytes': size, 'format': chosen,
                'formats_matching': all_matches,
                'resolution': int(resolution), 'width': round(float(width), 2),
                'height': round(float(height), 2),
                'pixel_size': pixels, 'staged': staged_from is not None,
                'staged_bytes': staged_bytes,
                'content_pt': ({'width': round(content_w, 2),
                                'height': round(content_h, 2)}
                               if content_w else None),
                'trimmed': trim_info,
                'trim_error': trim_error,
                'dpi_tag': dpi_tag,
                'dpi_tag_error': dpi_error,
                'physical_width_mm': physical_mm,
            },
            channel=CHANNEL, evidence=EVIDENCE_MEASURED,
            elapsed_ms=int((time.time() - started) * 1000), warnings=warnings)

    def export_figure(self, path: str,
                      width_mm: float = 85.0,
                      dpi: int = 1200,
                      margin: float = DEFAULT_MARGIN_PT,
                      fmt: str = 'png',
                      max_canvas_px: int = 40000000) -> Result:
        """Export a figure that is trimmed, RGB and physically width_mm wide.

        Measured limits worth knowing: this build never exports more than about
        2637 x 2191 px (1500 dpi and 2183 dpi both came back at that size), so
        a wide figure at a high dpi is not reachable in one SaveAs; the result
        then reports the physical width actually achieved and warns about it.

        A cheap 72 dpi probe comes first, because the drawing is not always
        centred in the exported region: when it is anchored near the page
        origin, a tight region clips it. The probe costs one small SaveAs and
        tells us which region this document needs; the real export then uses a
        resolution solved from the wanted pixel count.
        """
        started = time.time()
        if fmt != 'png':
            return Result(ok=False, failure=_failure(
                ErrorCode.NOT_INSTALLED, 'export_figure',
                detail='only PNG can be trimmed and re-tagged here; asked for %r' % fmt,
                message='unsupported figure format'), channel=CHANNEL)
        bounds = self.content_bounds()
        if not bounds.ok:
            return bounds
        content_w = bounds.data['width_pt']
        content_h = bounds.data['height_pt']
        target_px = int(round(width_mm / 25.4 * dpi))
        warnings = []
        # Filled in below when the exporter hits its pixel cap: the largest
        # dpi that still fills width_mm, computed from this very export.
        dpi_fit = 0
        achieved_dpi = dpi

        tight_w = content_w + 2 * margin
        tight_h = content_h + 2 * margin
        wanted = int(round(target_px * 36.0 / content_w))
        resolution = _fit_resolution(wanted, tight_w, tight_h, max_canvas_px)
        if resolution < wanted:
            warnings.append('resolution capped at %d dpi to keep the canvas '
                            'under %d megapixels'
                            % (resolution, max_canvas_px // 1000000))

        exported = self.export(path, fmt='png', resolution=resolution,
                              width=tight_w, height=tight_h, trim=True,
                              trim_pad_pt=0.0)
        # Two different reasons can make the ink come back smaller than asked:
        # ChemDraw caps the exported image (measured: 2637 x 2191 px even at
        # 2183 dpi), or the page anchors the drawing away from the region.
        # The canvas size tells them apart.
        expected = content_w * resolution / 36.0
        got = ((exported.data or {}).get('trimmed') or {}).get('after_px', [0])[0]
        canvas_w = ((exported.data or {}).get('pixel_size') or [0])[0]
        cap_hit = bool(canvas_w) and canvas_w < expected * 0.95
        if exported.ok and got and cap_hit:
            # The number a reader needs is not 'it came out 40.7 mm' but 'this
            # width still fits at 574 dpi'. Measured on an 85 mm request:
            # 574 dpi -> 1901 px -> 84.1 mm; 600 dpi -> the 1922 px cap ->
            # 81.4 mm; 1200 dpi -> 40.7 mm. So the cap, not the request, is
            # what decides the answer, and it is content dependent.
            dpi_fit = int(canvas_w * 25.4 / width_mm) if width_mm > 0 else 0
            # Tagging these pixels 1200 dpi makes the figure 40.7 mm wide: the
            # same image, a smaller picture than the one that was asked for.
            # The tool's own example already worked around this by hand (ask,
            # read dpi_fit, export again at 574), so the tag follows what the
            # pixels support and the width stays the one that was requested.
            achieved_dpi = dpi_fit or dpi
            warnings.append(
                'this build caps the exported image at about %d px, so %g mm'
                ' comes out at %d dpi, not %d%s'
                % (canvas_w, width_mm, achieved_dpi, dpi,
                   '' if not dpi_fit else
                   '; %d dpi is the largest that fills %g mm'
                   % (dpi_fit, width_mm)))
        if exported.ok and got and got < expected * 0.9 and not cap_hit:
            wide_w = max(tight_w, bounds.data['right'] + margin)
            wide_h = max(tight_h, bounds.data['bottom'] + margin)
            resolution = _fit_resolution(wanted, wide_w, wide_h, max_canvas_px)
            warnings.append('the drawing is anchored on this page (ink %d px, '
                            'expected about %.0f px), so the wider region '
                            '%.1f x %.1f pt is exported at %d dpi'
                            % (got, expected, wide_w, wide_h, resolution))
            exported = self.export(path, fmt='png', resolution=resolution,
                                   width=wide_w, height=wide_h, trim=True,
                              trim_pad_pt=0.0)
        exported.warnings.extend(warnings)
        if not exported.ok:
            return exported
        try:
            from .. import artwork
        except Exception as exc:
            exported.warnings.append('artwork module unavailable: %s' % exc)
            return exported
        normalized = artwork.normalize(exported.data['path'], exported.data['path'],
                                       dpi=achieved_dpi, max_width_mm=width_mm)
        if not normalized.ok:
            # normalize re-tags the dpi and caps the physical width; without it
            # the file is not submission-shaped, so this is a failure, not a note.
            missing = pillow_error() is not None
            exported.ok = False
            exported.failure = Failure(
                code=(ErrorCode.NOT_INSTALLED if missing else ErrorCode.UNKNOWN),
                channel=CHANNEL, stage='normalize',
                message=('the figure could not be re-tagged, which needs Pillow'
                         if missing else
                         'the figure could not be re-tagged for submission'),
                detail=str(normalized.failure.detail if normalized.failure else ''),
                hint=('pip install pillow' if missing else
                      'The exported file is still at '
                      + str(exported.data.get('path'))))
            return exported
        # Judged against what this export could reach: the requested dpi is a
        # wish, and reporting it as a failure would flag every capped figure.
        checked = artwork.check(exported.data['path'], min_dpi=min(dpi, achieved_dpi))
        exported.data['figure'] = normalized.data
        exported.data['figure']['dpi_fit'] = dpi_fit
        exported.data['figure']['requested_dpi'] = dpi
        exported.data['check'] = checked.data
        exported.ok = bool(checked.ok)
        if not checked.ok:
            exported.failure = Failure(
                code=ErrorCode.UNKNOWN, channel=CHANNEL, stage='artwork_check',
                message='the exported file would be rejected at submission',
                detail='; '.join((checked.data or {}).get('issues', [])),
                hint='See data.check for the artwork module report')
        exported.data['bytes'] = os.path.getsize(exported.data['path'])
        exported.elapsed_ms = int((time.time() - started) * 1000)
        return exported

    def _export_format_object(self, index: int):
        try:
            return self._app.ExportDataTypes.Item(int(index))
        except Exception:
            return None

    # -- report ------------------------------------------------------------
    def capabilities(self) -> list:
        '''What this channel can do, with the evidence level of each row.'''
        return [
            Capability('draw', CHANNEL, 'objects-data-smiles', True,
                       EVIDENCE_MEASURED,
                       'Objects.Data("chemical/x-daylight-smiles")'),
            Capability('draw', CHANNEL, 'objects-data-molblock', True,
                       EVIDENCE_MEASURED,
                       'Objects.Data("chemical/x-mdl-molfile")'),
            Capability('draw', CHANNEL, 'objects-data-cdxml', True,
                       EVIDENCE_MEASURED,
                       'text/xml with B/E + Order and Kekule bonds'),
            Capability('draw', CHANNEL, 'clipboard-paste', True,
                       EVIDENCE_MEASURED, 'CF_TEXT + Document.Paste()'),
            Capability('draw', CHANNEL, 'make-atom-bond', True,
                       EVIDENCE_MEASURED,
                       'MakeAtom/MakeBond with RDKit 2D coordinates'),
            Capability('open', CHANNEL, 'documents-open', False,
                       EVIDENCE_MEASURED,
                       'silent no-op: returns None, Documents.Count unchanged'),
            Capability('read', CHANNEL, 'objects-getdata', True,
                       EVIDENCE_MEASURED, 'smiles / molfile / cdxml'),
            Capability('export', CHANNEL, 'saveas-with-format', True,
                       EVIDENCE_MEASURED,
                       'ASCII paths only; non-ASCII is a silent no-op'),
            Capability('export', CHANNEL, 'export-figure', True,
                       EVIDENCE_MEASURED,
                       'trim + RGB + dpi tag, judged by chemdraw_tool.artwork'),
            Capability('close', CHANNEL, 'document-close', False,
                       EVIDENCE_MEASURED,
                       'Document.Close() is a no-op; only Application.Quit() works'),
        ]


_shared: Optional[ChemDrawChannel] = None


def channel(**kwargs) -> ChemDrawChannel:
    '''Process-wide channel, so repeated calls reuse one COM connection.'''
    global _shared
    if _shared is None:
        _shared = ChemDrawChannel(**kwargs)
    return _shared


def draw_smiles(smiles: str, route: Optional[str] = None) -> Result:
    return channel().draw_smiles(smiles, route)


def export(path: str, fmt: str = 'png', resolution: Optional[int] = None,
           width: Optional[float] = None, height: Optional[float] = None,
           margin: float = DEFAULT_MARGIN_PT,
           target_px_width: Optional[int] = None,
           trim: bool = True, trim_pad_pt: float = 2.0) -> Result:
    return channel().export(path, fmt, resolution, width, height, margin,
                            target_px_width, trim, trim_pad_pt)


def export_figure(path: str, width_mm: float = 85.0, dpi: int = 1200,
                  fmt: str = 'png') -> Result:
    return channel().export_figure(path, width_mm, dpi, fmt=fmt)


def read_current(kind: str = 'smiles') -> Result:
    return channel().read_current(kind)


def close() -> Result:
    global _shared
    if _shared is None:
        return Result(ok=True, data={'quit': False}, channel=CHANNEL)
    res = _shared.close()
    _shared = None
    return res


__all__ = [
    'CHANNEL', 'PROGIDS', 'ROUTES', 'DEFAULT_ROUTE', 'DEFAULT_RESOLUTION',
    'DEFAULT_SIZE', 'DEFAULT_MARGIN_PT', 'ChemDrawChannel', 'channel',
    'draw_smiles', 'export', 'export_figure', 'read_current', 'close',
    'png_pixel_size',
]
