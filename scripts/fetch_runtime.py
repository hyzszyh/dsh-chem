'''Fetch the 32-bit embeddable Python that the KingDraw channel needs.

GRDKitDll.dll is x86 and refuses to load into a 64-bit interpreter, so this
project uses a second interpreter under runtime/py32/. That payload is ~10 MB
of binary that does not belong in git, hence this script.

    python scripts/fetch_runtime.py            # download + unpack
    python scripts/fetch_runtime.py --verify   # report what is already there

The archive comes from python.org over HTTPS. The SHA-256 is printed so it can
be checked against the published value; pass --sha256 to enforce it.
'''

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request
import zipfile

VERSION = '3.11.9'
FILE = 'python-%s-embed-win32.zip' % VERSION
URL = 'https://www.python.org/ftp/python/%s/%s' % (VERSION, FILE)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RUNTIME = os.path.join(ROOT, 'runtime')
TARGET = os.path.join(RUNTIME, 'py32')
ARCHIVE = os.path.join(RUNTIME, FILE)


def sha256_of(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def download(dest):
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    print('downloading ' + URL)
    with urllib.request.urlopen(URL) as response, open(dest, 'wb') as out:
        total = int(response.headers.get('Content-Length') or 0)
        seen = 0
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            seen += len(chunk)
            if total:
                pct = seen * 100 // total
                sys.stdout.write('\r  %d%% (%d/%d bytes)' % (pct, seen, total))
                sys.stdout.flush()
    print()


def unpack(archive, target):
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(target)
    print('unpacked into ' + target)


def main(argv=None):
    parser = argparse.ArgumentParser(description='prepare runtime/py32')
    parser.add_argument('--sha256', default=None,
                        help='expected SHA-256 of the archive; a mismatch aborts')
    parser.add_argument('--verify', action='store_true',
                        help='only report what is already unpacked')
    args = parser.parse_args(argv)

    python_exe = os.path.join(TARGET, 'python.exe')
    if args.verify:
        print('interpreter: ' + python_exe)
        print('present    : ' + str(os.path.isfile(python_exe)))
        if os.path.isfile(ARCHIVE):
            print('archive    : ' + ARCHIVE)
            print('sha256     : ' + sha256_of(ARCHIVE))
        return 0 if os.path.isfile(python_exe) else 1

    if os.path.isfile(python_exe):
        print('already present: ' + python_exe)
        return 0

    if not os.path.isfile(ARCHIVE):
        download(ARCHIVE)
    digest = sha256_of(ARCHIVE)
    print('archive sha256: ' + digest)
    if args.sha256 and args.sha256.lower() != digest.lower():
        print('MISMATCH: expected ' + args.sha256)
        return 2
    unpack(ARCHIVE, TARGET)
    print('done. try: runtime/py32/python.exe bin/cli.py doctor kd --json')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())