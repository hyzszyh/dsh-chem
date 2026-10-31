'''Picture output for the KingDraw channel: the preview raster inside a .kdx.

KingDraw 26 has no usable image export of its own -- 导出(E) answers "请登录后使用
导出图片功能！" (measured), and a screenshot cannot see the canvas because it is a
WPF/D3D surface (measured: PrintWindow returns white or black). What it does have
is the save path: 另存为 writes a .kdx, and a .kdx is a ZIP that carries the images
KingDraw rendered for the document.

Measured contents of a .kdx written on this build (phenol / aspirin / cholesterol):

    media/p_jpg.jpg       108x120  348 colours / 147x141 860 / 270x233 353
    media/p_png.png       108x120   10 colours / 147x141  12 / 270x233   8
    media/p_thumbnail.png 300x300    11 colours (a black block with the label)

So "the largest entry" is not the useful one: p_thumbnail.png is bigger in pixels
but visually a placeholder, while p_jpg.jpg is the real drawing and its size grows
with the molecule (108x120 -> 270x233). The picker therefore ranks media entries
by colour richness first and pixel area second, which selects the rendered one.

The result is a PREVIEW, not publication artwork: 108-270 px on a side, JPEG
compressed. export_image() says so in Result.warnings every time, and it reports
the untouched source size next to the delivered one. Submission figures come from
the ChemDraw channel (cd figure / cd export).
'''

from __future__ import annotations

import glob
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from typing import Optional

from ..models import (
    ERROR_TEXT, ErrorCode, EVIDENCE_INFERRED, EVIDENCE_MEASURED, Failure, Result,
)

CHANNEL = 'kingdraw'
PY64_ENV = 'CHEMTOOL_PYTHON64'
PREVIEW_WARNING = ('preview-level image: KingDraw renders a JPEG preview inside the '
                   '.kdx (a few hundred pixels on a side); this is not publication '
                   'artwork -- use the ChemDraw channel (cd figure) for submission '
                   'figures')
MIN_MEDIA_AREA = 16
BLANK_RATIO = 0.99
IMAGE_SUFFIXES = ('.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff')


def _remove_tree(path: str, attempts: int = 10, wait: float = 0.4) -> bool:
    '''Delete a temp folder, retrying while a just-closed app lets go of it.

    `shutil.rmtree(..., ignore_errors=True)` is why 44 `kd_export_*` folders
    had piled up in %TEMP%: KingDraw still holds the .kdx it just wrote, the
    delete fails, and the silence makes it invisible. Retry for ~4 s, then say
    so on stderr instead of pretending the folder is gone.
    '''
    for attempt in range(attempts):
        if not os.path.exists(path):
            return True
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            return True
        time.sleep(wait)
    if os.path.exists(path):
        sys.stderr.write('warning: a temporary folder could not be removed: %s\n'
                         % path)
        return False
    return True


TEMP_PREFIX = 'kd_export_'
STALE_AFTER_S = 5 * 60


def _sweep_stale_temp(older_than: float = STALE_AFTER_S) -> list:
    '''Remove workdirs left by runs that were killed before their finally ran.

    A process does not get to clean up when Windows terminates it. Measured:
    the interrupt test SIGTERMs `kd export` four seconds in, and the process
    exits without running finally, leaving one `kd_export_*` folder behind -- no
    amount of retrying inside that process could have prevented it. So the
    next run clears the debris, age-gated at half an hour so a live run's
    folder (or a --keep-kdx archive somebody is still looking at) is never
    touched.

    Returns the paths that were removed, so the caller can report them.
    '''
    removed = []
    root = tempfile.gettempdir()
    now = time.time()
    try:
        entries = os.listdir(root)
    except OSError:
        return removed
    for name in entries:
        if not name.startswith(TEMP_PREFIX) or name == TEMP_PREFIX:
            continue
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        try:
            if now - os.path.getmtime(path) < older_than:
                continue
            entries = os.listdir(path)
        except OSError:
            continue
        if any(name.endswith('.kdx') for name in entries):
            # --keep-kdx left this one on purpose: it is evidence somebody
            # asked for, not debris.
            continue
        if _remove_tree(path, attempts=3, wait=0.2):
            removed.append(path)
    return removed


def _failure(code: str, stage: str, detail: str = '', message: str = '',
             hint: str = '') -> Failure:
    d_msg, d_hint = ERROR_TEXT.get(code, ('', ''))
    return Failure(code=code, message=message or d_msg, hint=hint or d_hint,
                   detail=detail, channel=CHANNEL, stage=stage)


def _root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.dirname(os.path.dirname(os.path.dirname(here)))


# -- which interpreter can do the UIA + Pillow half -------------------------
def _have_uia() -> bool:
    try:
        import pywinauto  # noqa: F401
        return True
    except Exception:
        return False


def _have_pillow() -> bool:
    try:
        from PIL import Image  # noqa: F401
        return True
    except Exception:
        return False


def find_python64(explicit: Optional[str] = None) -> Optional[str]:
    '''A 64-bit interpreter with pywinauto + Pillow (the bundled py32 has neither).'''
    cands = []
    if explicit:
        cands.append(explicit)
    env = os.environ.get(PY64_ENV)
    if env:
        cands.append(env)
    if sys.maxsize > 2 ** 32:
        cands.append(sys.executable)
    local = os.environ.get('LOCALAPPDATA') or ''
    if local:
        for ver in ('Python313', 'Python312', 'Python311', 'Python310'):
            cands.append(os.path.join(local, 'Programs', 'Python', ver, 'python.exe'))
    cands.extend([r'C:\Python311\python.exe', r'C:\Python312\python.exe'])
    seen = set()
    for path in cands:
        if not path or not os.path.isfile(path):
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen:
            continue
        seen.add(key)
        if _interpreter_has_export_tools(path):
            return path
    return None


_HAS_TOOLS: dict = {}


def _interpreter_has_export_tools(exe: str, timeout: float = 25.0) -> bool:
    '''Does this interpreter have pywinauto and Pillow? Ask it, do not assume.

    The machine this was built on has Python313 next to Python311, and only 311
    carries the packages; picking 313 made the helper re-enter the bridge and
    hang (found the hard way).
    '''
    key = os.path.normcase(exe)
    if key in _HAS_TOOLS:
        return _HAS_TOOLS[key]
    try:
        proc = subprocess.run([exe, '-c', 'import pywinauto, PIL; print(1)'],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=timeout)
        ok = proc.returncode == 0 and b'1' in (proc.stdout or b'')
    except Exception:
        ok = False
    _HAS_TOOLS[key] = ok
    return ok


# -- the UIA recipe (no coordinate clicks anywhere) -------------------------
def _attach(pid: int):
    from pywinauto import Application
    return Application(backend='uia').connect(process=pid)


def _find(pid: int, pred, tries: int = 10, pause: float = 0.4):
    for _ in range(tries):
        app = _attach(pid)
        for win in app.windows():
            try:
                for el in win.descendants():
                    try:
                        if pred(el.element_info, el):
                            return el
                    except Exception:
                        continue
            except Exception:
                continue
        time.sleep(pause)
    return None


def _by_id(pid: int, auto_id: str, tries: int = 10):
    return _find(pid, lambda info, el: info.automation_id == auto_id, tries=tries)


def _file_name_edit(pid: int):
    '''The name field of the native dialog.

    auto_id 1001 is not enough: the dialog's address bar reports the same id and
    selecting it types into the address box (measured in t12). Match the control
    type and the label instead.
    '''
    return _find(pid, lambda info, el: info.control_type == 'Edit'
                 and info.class_name == 'Edit'
                 and (info.name or '').startswith('文件名'))


def _save_button(pid: int):
    return _find(pid, lambda info, el: info.control_type == 'Button'
                 and info.automation_id == '1' and '保存' in (info.name or ''))


def _save_dialog_to_kdx(pid: int, stem: str) -> tuple:
    '''Drive 菜单(M) -> 文件(F) -> 另存为(A) -> 浏览 -> name -> 保存.

    Returns (ok, stage, detail). Everything is Invoke/Expand/SetValue through UI
    Automation; no screen coordinates are used, so the call cannot land a click on
    the wrong control or the wrong window.
    '''
    if _by_id(pid, 'mFileItem', tries=2) is None:
        root = _by_id(pid, 'mRootMenu', tries=6)
        if root is None:
            return False, 'menu', 'the 菜单(M) item (auto_id mRootMenu) is absent'
        try:
            root.expand()
        except Exception as exc:
            return False, 'menu', 'expanding 菜单(M) failed: %s: %s' % (
                type(exc).__name__, exc)
        time.sleep(0.8)
    item = _by_id(pid, 'mFileItem', tries=6)
    if item is None:
        return False, 'menu', '文件(F) (auto_id mFileItem) did not appear'
    try:
        item.expand()
    except Exception:
        pass
    time.sleep(0.8)
    save_as = _by_id(pid, 'mSaveAs', tries=8)
    if save_as is None:
        return False, 'menu', '另存为(A) (auto_id mSaveAs) did not appear'
    try:
        save_as.invoke()
    except Exception as exc:
        return False, 'menu', 'invoking 另存为(A) failed: %s: %s' % (
            type(exc).__name__, exc)
    time.sleep(1.6)
    browse = _by_id(pid, 'btnOpenSaveFileDialog', tries=10)
    if browse is None:
        return False, 'dialog', ('the 另存为 panel opened but 浏览 '
                                 '(auto_id btnOpenSaveFileDialog) never appeared')
    try:
        browse.invoke()
    except Exception as exc:
        return False, 'dialog', 'invoking 浏览 failed: %s: %s' % (
            type(exc).__name__, exc)
    time.sleep(2.0)
    edit = _file_name_edit(pid)
    if edit is None:
        return False, 'dialog', ('the native save dialog did not appear '
                                 '(no Edit named 文件名: was found)')
    try:
        edit.set_edit_text(stem)
    except Exception:
        try:
            edit.set_text(stem)
        except Exception as exc:
            return False, 'dialog', 'could not type into the name field: %s: %s' % (
                type(exc).__name__, exc)
    time.sleep(0.3)
    button = _save_button(pid)
    if button is None:
        return False, 'dialog', 'the 保存(S) button (auto_id 1) was not found'
    try:
        button.invoke()
    except Exception as exc:
        return False, 'dialog', 'invoking 保存(S) failed: %s: %s' % (
            type(exc).__name__, exc)
    return True, 'save', ''


# -- ZIP + Pillow -----------------------------------------------------------
def media_entries(kdx_path: str) -> list:
    '''Every image entry in the .kdx with the numbers the picker uses.

    Pillow is imported lazily and its absence is reported per entry rather
    than raised. The 32-bit interpreter that owns the KingDraw DLL is a bare
    embeddable build with no third-party packages, so 'cannot measure the
    preview' must not read as 'the .kdx is broken' -- and the ZIP is opened
    first so a non-ZIP file still fails as a non-ZIP file.
    '''
    rows = []
    with zipfile.ZipFile(kdx_path) as zf:
        for name in zf.namelist():
            lowered = name.lower()
            if not lowered.startswith('media/') or name.endswith('/'):
                continue
            if not lowered.endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp')):
                continue
            blob = zf.read(name)
            try:
                from PIL import Image
            except ImportError:
                rows.append({'name': name, 'bytes': len(blob),
                             'error': 'Pillow is not installed in this interpreter'})
                continue
            try:
                img = Image.open(io.BytesIO(blob))
                img.load()
            except Exception as exc:
                rows.append({'name': name, 'bytes': len(blob), 'error': str(exc)})
                continue
            rgb = img.convert('RGB')
            colours = rgb.getcolors(maxcolors=4000000) or []
            total = float(max(1, rgb.size[0] * rgb.size[1]))
            dominant = max((count for count, _ in colours), default=total) / total
            rows.append({
                'name': name, 'bytes': len(blob), 'mode': img.mode,
                'width': img.size[0], 'height': img.size[1],
                'area': img.size[0] * img.size[1],
                'colours': len(colours), 'dominant': round(dominant, 4),
                'error': '',
            })
    return rows


def pick_media(rows: list) -> Optional[dict]:
    '''Colour richness first, then pixel area: the render beats the placeholder.'''
    usable = [r for r in rows if not r.get('error') and r.get('area', 0) >= MIN_MEDIA_AREA]
    if not usable:
        return None
    return max(usable, key=lambda r: (r['colours'], r['area'], r['bytes']))


def _trim_to_ink(img, pad_ratio: float = 0.06):
    '''Crop the dead paper, then put a uniform margin back.

    KingDraw renders into a fixed preview canvas, so where the structure lands
    is up to the app: measured on three exports, an acetate came back 336x300
    with 8 px of paper on the left and 171 px on the right, and a caffeine was
    flush against the left edge. A picture half full of dead space is not usable
    in a document, and one that touches an edge reads as cut.

    The background colour is taken from the corner pixel, not assumed white,
    because the exporter can be pointed at a tinted page.
    '''
    from PIL import Image, ImageChops
    flat = img.convert('RGB')
    background = flat.getpixel((0, 0))
    solid = Image.new('RGB', flat.size, background)
    diff = ImageChops.difference(flat, solid).convert('L')
    box = diff.point(lambda v: 255 if v > 24 else 0).getbbox()
    if not box:
        return img, None
    short = min(box[2] - box[0], box[3] - box[1])
    pad = max(4, int(round(short * pad_ratio)))
    # Not 'expand the box and clamp to the canvas': when the drawing sits on
    # KingDraw's own edge (measured on caffeine) there is no paper to expand
    # into and that side comes back with 0 px, i.e. still cut. Paste the ink
    # onto a fresh canvas instead, so every side gets the same margin wherever
    # the app happened to place the structure.
    ink = flat.crop(box)
    canvas = Image.new('RGB', (ink.size[0] + 2 * pad, ink.size[1] + 2 * pad),
                       background)
    canvas.paste(ink, (pad, pad))
    return canvas, {'before_px': list(flat.size), 'after_px': list(canvas.size),
                    'box': list(box), 'pad_px': pad,
                    'background': list(background)}


def _convert(src_blob: bytes, out_path: str, min_side: int) -> dict:
    '''Write the image: crop the dead paper, then upscale only real ink.'''
    from PIL import Image
    img = Image.open(io.BytesIO(src_blob))
    img.load()
    source_size = list(img.size)
    trimmed = None
    try:
        img, trimmed = _trim_to_ink(img)
    except Exception:
        # A picture that cannot be measured is still a picture; keep it whole.
        pass
    scale = 1.0
    if min_side and min(img.size) < min_side:
        scale = min(4.0, float(min_side) / float(min(img.size)))
        target = (max(1, int(round(img.size[0] * scale))),
                  max(1, int(round(img.size[1] * scale))))
        img = img.convert('RGB').resize(target, Image.LANCZOS)
    suffix = os.path.splitext(out_path)[1].lower() or '.png'
    if suffix in ('.jpg', '.jpeg'):
        img = img.convert('RGB')
        img.save(out_path, 'JPEG', quality=95)
    elif suffix == '.webp':
        img.convert('RGB').save(out_path, 'WEBP', quality=95)
    elif suffix == '.bmp':
        img.convert('RGB').save(out_path, 'BMP')
    elif suffix in ('.tif', '.tiff'):
        img.convert('RGB').save(out_path, 'TIFF')
    else:
        img.convert('RGB').save(out_path, 'PNG')
    return {'width': img.size[0], 'height': img.size[1], 'source_size': source_size,
            'scale': round(scale, 3), 'upscaled': scale > 1.0, 'trimmed': trimmed}


def inspect_image(path: str) -> dict:
    '''Re-read the delivered file, so the numbers come from the file, not memory.'''
    from PIL import Image
    with Image.open(path) as img:
        img.load()
        rgb = img.convert('RGB')
        colours = rgb.getcolors(maxcolors=4000000) or []
        total = float(max(1, rgb.size[0] * rgb.size[1]))
        dominant = max((count for count, _ in colours), default=total) / total
        return {'format': img.format, 'mode': img.mode,
                'width': img.size[0], 'height': img.size[1],
                'colours': len(colours), 'dominant': round(dominant, 4),
                'bytes': os.path.getsize(path)}


# -- the public capability --------------------------------------------------
def export_image(struct_path: str, out_path: Optional[str] = None,
                 timeout: float = 90.0, keep_kdx: bool = False,
                 min_side: int = 300, close_app: bool = True,
                 python64: Optional[str] = None, overwrite: bool = True) -> Result:
    '''Render *struct_path* through KingDraw and write its picture as a raster file.

    Every stage reports its own failure instead of collapsing into E99: the app
    refusing to show the save menu, the native dialog never appearing, the .kdx
    carrying no media, and a blank image all answer differently.

    Runs in-process when this interpreter has pywinauto and Pillow; otherwise the
    call is bridged to a 64-bit interpreter through bin/kd_export.py (the bundled
    32-bit runtime has neither).
    '''
    started = time.monotonic()
    stage = 'locate'
    if not struct_path:
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.PARSE_FAILED, stage,
                                       detail='empty path'))
    src = os.path.abspath(struct_path)
    if not os.path.isfile(src):
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.PARSE_FAILED, stage,
                                       detail='not a file: ' + src,
                                       message='Input structure file does not exist'))
    # Sniff the content before touching the GUI: launching KingDraw with a text
    # file only lands us in "the save menu was not offered", which hides the real
    # problem (the input is not a structure).
    with open(src, 'rb') as fh:
        head = fh.read(4096)
    if not (b'M  END' in head or b'V3000' in head or head.startswith(b'Begin Header')):
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.PARSE_FAILED, stage,
                                       detail='no molblock marker (M  END / V3000) and '
                                              'no KingDraw header in the first 4 KiB',
                                       message='Input is not a molfile or a .king',
                                       hint='Convert the structure first: '
                                            'kd mol "<SMILES>" --out x.mol'))
    dest = os.path.abspath(out_path) if out_path else os.path.splitext(src)[0] + '.png'
    if os.path.splitext(dest)[1].lower() not in IMAGE_SUFFIXES:
        dest = dest + '.png'
    if os.path.isfile(dest) and not overwrite:
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                      failure=_failure(ErrorCode.PARSE_FAILED, stage,
                                       detail='output exists: ' + dest,
                                       message='Output already exists'))

    if not (_have_uia() and _have_pillow()):
        return _export_via_bridge(src, dest, timeout, keep_kdx, min_side, close_app,
                                  python64, overwrite)

    from .. import applock
    from . import kd_open
    # Temp work happens on an ASCII path: the project folder has non-ASCII
    # characters and the native dialog is happier with %TEMP%.
    workdir = tempfile.mkdtemp(prefix='kd_export_')
    stem = os.path.splitext(os.path.basename(src))[0] or 'structure'
    target = os.path.join(workdir, 'kd_export_' + stem)
    kdx = target + '.kdx'
    pre_pids = kd_open.list_pids()
    pid = None
    res = None
    held = None
    try:
        # KingDraw is single-instance: two calls at once hand their files to
        # the same window and both time out (measured: 122 s each, no output).
        stage = 'lock'
        try:
            held = applock.hold(applock.KINGDRAW, timeout=timeout)
        except applock.AppBusy as busy:
            return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                          elapsed_ms=int((time.monotonic() - started) * 1000),
                          data={'path': src, 'waited_s': round(busy.waited, 2)},
                          failure=_failure(
                              ErrorCode.KD_CLI_DID_NOT_OPEN, 'lock',
                              detail=busy.hint(),
                              message='KingDraw is busy with another call',
                              hint=busy.hint()))
        # Debris from runs that were killed before their finally could run.
        # This happens inside the app lock, so no other export can be
        # running: anything older than the budget below is dead by
        # definition, and a --keep-kdx archive is skipped below.
        swept = _sweep_stale_temp()
        stage = 'open'
        opened = kd_open.open_file(src, timeout=min(60.0, timeout))
        if not opened.ok and 'rc=0' in (opened.failure.detail or ''):
            # The launcher forwarded the file and exited 0 without producing a
            # window: the single instance it was handed to was on its way out
            # (measured after a close). Wait for it to go, then start a fresh one.
            time.sleep(2.0)
            opened = kd_open.open_file(src, timeout=min(60.0, timeout), reuse=False)
        if not opened.ok:
            return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                          elapsed_ms=int((time.monotonic() - started) * 1000),
                          data={'path': src, 'open': opened.data},
                          failure=opened.failure)
        pid = opened.data['pid']
        stage = 'save'
        ok, where, detail = _save_dialog_to_kdx(pid, target)
        if not ok:
            messages = {
                'menu': 'KingDraw did not offer 另存为',
                'dialog': 'The native save dialog never showed up',
                'save': 'The save command could not be issued',
            }
            return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                          elapsed_ms=int((time.monotonic() - started) * 1000),
                          data={'path': src, 'pid': pid, 'stage': where},
                          failure=_failure(
                              ErrorCode.KD_CLI_DID_NOT_OPEN, where,
                              detail=detail, message=messages.get(where, 'Save failed'),
                              hint='Run test/probe_kd_kdx_media.py to watch the same '
                                   'UIA steps by hand'))
        deadline = time.monotonic() + max(5.0, min(30.0, timeout / 3.0))
        while time.monotonic() < deadline and not os.path.isfile(kdx):
            time.sleep(0.4)
        if not os.path.isfile(kdx):
            return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                          elapsed_ms=int((time.monotonic() - started) * 1000),
                          data={'path': src, 'pid': pid, 'workdir': workdir},
                          failure=_failure(
                              ErrorCode.KD_CLI_DID_NOT_OPEN, 'save',
                              detail='the dialog was driven but no .kdx appeared at '
                                     + kdx,
                              message='KingDraw closed the dialog without writing a '
                                      '.kdx'))
        stage = 'extract'
        rows = media_entries(kdx)
        best = pick_media(rows)
        if best is None:
            return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                          elapsed_ms=int((time.monotonic() - started) * 1000),
                          data={'path': src, 'kdx': kdx, 'media': rows},
                          failure=_failure(
                              ErrorCode.PARSE_FAILED, 'extract',
                              detail='media entries: %r' % (rows,),
                              message='The .kdx carries no usable preview image',
                              hint='keep_kdx=True keeps the archive for inspection'))
        with zipfile.ZipFile(kdx) as zf:
            blob = zf.read(best['name'])
        stage = 'convert'
        os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
        converted = _convert(blob, dest, min_side)
        stage = 'verify'
        report = inspect_image(dest)
        if report['dominant'] > BLANK_RATIO:
            os.remove(dest)
            return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                          elapsed_ms=int((time.monotonic() - started) * 1000),
                          data={'path': src, 'kdx': kdx, 'media': rows,
                                'blank': report},
                          failure=_failure(
                              ErrorCode.PARSE_FAILED, 'verify',
                              detail='%.2f%% of the pixels are one colour'
                                     % (report['dominant'] * 100),
                              message='The preview KingDraw rendered is blank'))
        data = {
            'path': src, 'out': dest, 'pid': pid,
            'source_name': best['name'], 'source_size': converted['source_size'],
            'source_bytes': best['bytes'], 'source_colours': best['colours'],
            'width': report['width'], 'height': report['height'],
            'bytes': report['bytes'], 'format': report['format'],
            'colours': report['colours'], 'dominant': report['dominant'],
            'upscaled': converted['upscaled'], 'scale': converted['scale'],
            'min_side': min_side, 'kdx': kdx if keep_kdx else None,
            'media': rows, 'verified_by': ['kdx:media', 'pillow:reopen', 'blank-check'],
            'waited_s': round(time.monotonic() - started, 2),
        }
        res = Result(ok=True, channel=CHANNEL, evidence=EVIDENCE_MEASURED,
                     elapsed_ms=int((time.monotonic() - started) * 1000), data=data)
        res.warnings.append(PREVIEW_WARNING)
        if swept:
            res.warnings.append(
                'removed %d temporary folder(s) an interrupted run could not '
                'clean up: %s' % (len(swept), ', '.join(os.path.basename(p)
                                                        for p in swept)))
        if converted['upscaled']:
            res.warnings.append(
                'the preview KingDraw rendered is %dx%d; it was upscaled x%.2f to '
                '%dx%d for screen use -- the pixels are interpolated, not rendered'
                % (converted['source_size'][0], converted['source_size'][1],
                   converted['scale'], report['width'], report['height']))
        if len(rows) > 1:
            res.warnings.append(
                'the .kdx held %d images; %s was chosen (colour richness first, '
                'then area) because the pixel-largest entry is a placeholder'
                % (len(rows), best['name']))
        res.degraded = True
        res.degrade_reason = 'preview-level raster extracted from a .kdx, not a render'
        return res
    finally:
        # Batch operation: the instance this call opened is closed again, an
        # instance the user already had open is left alone (close_app only ever
        # posts WM_CLOSE).
        if close_app and pid is not None and pid not in pre_pids:
            try:
                kd_open.close_app(pid, 12.0)
            except Exception:
                pass
        if not keep_kdx:
            _remove_tree(workdir)
        if held is not None:
            held.release()


def _export_via_bridge(src, dest, timeout, keep_kdx, min_side, close_app,
                       python64, overwrite) -> Result:
    if os.environ.get('CHEMTOOL_KD_EXPORT_HELPER'):
        # This process *is* the helper; bridging again would fork forever (the
        # helper interpreter was picked without the packages once, and that is
        # exactly how the endless wait looked from outside).
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_INFERRED,
                      failure=_failure(
                          ErrorCode.NOT_INSTALLED, 'bridge',
                          detail='interpreter %s has no pywinauto/Pillow' % sys.executable,
                          message='The 64-bit helper cannot do the export itself',
                          hint='Install pywinauto and Pillow for %s, or point %s at one '
                               'that has them' % (sys.executable, PY64_ENV)))
    script = os.path.join(_root(), 'bin', 'kd_export.py')
    if not os.path.isfile(script):
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_INFERRED,
                      failure=_failure(ErrorCode.NOT_INSTALLED, 'bridge',
                                       detail='missing ' + script,
                                       message='The 64-bit export helper is missing'))
    exe = find_python64(python64)
    if exe is None:
        return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_INFERRED,
                      failure=_failure(ErrorCode.NOT_INSTALLED, 'bridge',
                                       detail='no 64-bit interpreter with pywinauto '
                                              'and Pillow was found',
                                       message='Cannot reach the UI Automation helper',
                                       hint='Set %s to a 64-bit python.exe' % PY64_ENV))
    # The helper starts KingDraw, and KingDraw inherits whatever stdio it is given.
    # With capture_output=True the pipe stays open in the grandchild, so the wait
    # never ends even after the helper exits (measured: 120 s of nothing). Hand the
    # answer over in a file and give the child no pipes at all.
    bridge_dir = tempfile.mkdtemp(prefix='kd_export_bridge_')
    try:
        result_file = os.path.join(bridge_dir, 'result.json')
        log_file = os.path.join(bridge_dir, 'helper.log')
        cmd = [exe, script, src, '--out', dest, '--timeout', str(timeout),
               '--min-side', str(min_side), '--result-file', result_file]
        if keep_kdx:
            cmd.append('--keep-kdx')
        if not close_app:
            cmd.append('--keep-open')
        if not overwrite:
            cmd.append('--no-overwrite')
        budget = max(30.0, timeout + 60)
        deadline = time.monotonic() + budget
        proc = None
        log_handle = None
        try:
            # A real file handle, not a pipe and not the null device: KingDraw is
            # started by the helper and inherits these handles, and with a pipe the
            # wait never sees EOF, while the null device stalls the helper outright
            # (both measured). The file also gives the caller something to quote.
            log_handle = open(log_file, 'wb')
            proc = subprocess.Popen(cmd, stdout=log_handle, stderr=subprocess.STDOUT)
        except OSError as exc:
            # Close the log handle before the finally block deletes the folder:
            # on Windows an open handle makes that delete silently fail, which
            # would put the leak straight back on this path.
            if log_handle is not None:
                try:
                    log_handle.close()
                except Exception:
                    pass
            return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_INFERRED,
                          failure=_failure(ErrorCode.NOT_INSTALLED, 'bridge',
                                           detail=str(exc),
                                           message='Could not start the 64-bit helper'))
        # The answer arrives in the result file; the helper's own exit is not the
        # signal, because the UIA/COM teardown can hold the interpreter open for
        # minutes after the work is done (measured: result written, process still
        # alive 30 s later, KingDraw already closed).
        while time.monotonic() < deadline:
            if os.path.isfile(result_file) or proc.poll() is not None:
                break
            time.sleep(0.4)
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        out = ''
        if os.path.isfile(result_file):
            with open(result_file, encoding='utf-8') as fh:
                out = fh.read().strip()
            try:
                os.remove(result_file)
            except OSError:
                pass
        if not out:
            try:
                log_handle.close()
            except Exception:
                pass
            tail = ''
            try:
                with open(log_file, 'rb') as fh:
                    tail = fh.read()[-600:].decode('utf-8', 'replace')
            except OSError:
                pass
            return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_INFERRED,
                          failure=_failure(
                              ErrorCode.UNKNOWN, 'bridge',
                              detail='rc=%s, no result file (%s), helper log: %r'
                                     % (proc.returncode, result_file, tail),
                              message='The 64-bit export helper returned nothing'))
        try:
            log_handle.close()
        except Exception:
            pass
        try:
            payload = json.loads(out)
        except ValueError:
            return Result(ok=False, channel=CHANNEL, evidence=EVIDENCE_INFERRED,
                          failure=_failure(ErrorCode.UNKNOWN, 'bridge',
                                           detail='unparsable helper output: ' + out[:300]))
        res = Result(
            ok=bool(payload.get('ok')), channel=CHANNEL, evidence=EVIDENCE_INFERRED,
            elapsed_ms=payload.get('elapsed_ms'),
            data=payload.get('data') or {},
            failure=(Failure(**payload['failure']) if payload.get('failure') else None),
            warnings=payload.get('warnings') or [])
        # The physical evidence is A-grade in-process; over the bridge the numbers came
        # from another process, so the envelope keeps its own weaker evidence label but
        # must not drop the "this is a preview" flags the caller relies on.
        res.degraded = payload.get('degraded') or bool((payload.get('data') or {}).get('upscaled'))
        res.degrade_reason = payload.get('degrade_reason') or (
            'preview-level raster extracted from a .kdx, not a render'
            if res.degraded else '')
        return res
    finally:
        # The scratch directory holds the helper log and result file; nothing
        # else refers to it once we return. It used to survive every call:
        # measured 25 691 leftover kd_export_bridge_* folders in %TEMP%.
        _remove_tree(bridge_dir)


__all__ = ['CHANNEL', 'PREVIEW_WARNING', 'export_image', 'find_python64',
           'inspect_image', 'media_entries', 'pick_media']
