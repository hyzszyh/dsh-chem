'''Probe the real export table of GRDKitDll.dll (pure-Python PE parsing).

Runs in either interpreter (it only reads bytes). Prints export names, ordinals and,
for stdcall decoration (_name@N), the argument bytes so the ctypes signature is
derived instead of guessed.
'''
from __future__ import annotations

import struct
import sys

DLL = sys.argv[1] if len(sys.argv) > 1 else r'D:\tool\KingDraw\GRDKitDll.dll'


def parse(data: bytes):
    e = struct.unpack_from('<I', data, 0x3C)[0]
    assert data[e:e + 4] == b'PE\x00\x00', 'not a PE file'
    coff = e + 4
    machine, nsec, _ts, _sym, _nsym, optsz, _chars = struct.unpack_from(
        '<HHIIIHH', data, coff)
    opt = coff + 20
    magic = struct.unpack_from('<H', data, opt)[0]
    dd = opt + (96 if magic == 0x10B else 112)
    exp_rva, exp_size = struct.unpack_from('<II', data, dd)
    secs = []
    off = opt + optsz
    for _ in range(nsec):
        name = data[off:off + 8].rstrip(b'\x00').decode('ascii', 'replace')
        vsz, va, rawsz, rawptr = struct.unpack_from('<IIII', data, off + 8)
        secs.append((name, va, vsz, rawsz, rawptr))
        off += 40
    return machine, magic, exp_rva, exp_size, secs


def rva2off(secs, rva: int) -> int:
    for _name, va, vsz, rawsz, rawptr in secs:
        if va <= rva < va + max(vsz, rawsz):
            delta = rva - va
            if delta >= rawsz:
                raise ValueError('rva 0x%x in uninitialized tail of section' % rva)
            return rawptr + delta
    raise ValueError('rva 0x%x not mapped' % rva)


def main(path: str) -> int:
    data = open(path, 'rb').read()
    machine, magic, exp_rva, exp_size, secs = parse(data)
    print('machine: 0x%04x (%s)' % (
        machine, {0x14C: 'x86', 0x8664: 'x64'}.get(machine, '?')), file=sys.stderr)
    print('sections:', file=sys.stderr)
    for nm, va, vsz, rawsz, rawptr in secs:
        print('  %-8s va=%08x vsz=%08x rawsz=%08x rawptr=%08x'
              % (nm, va, vsz, rawsz, rawptr), file=sys.stderr)
    print('export dir rva=%08x size=%d' % (exp_rva, exp_size), file=sys.stderr)
    if not exp_rva:
        print('no export directory')
        return 1
    eo = rva2off(secs, exp_rva)
    (_chars, ts, _maj, _min, _name, base, nfunc, nname,
     afunc, aname, aord) = struct.unpack_from('<IIHHIIIIIII', data, eo)
    print('base ordinal: %d, functions: %d, names: %d, build: 0x%08x'
          % (base, nfunc, nname, ts))
    rows = []
    for i in range(nname):
        nrva = struct.unpack_from('<I', data, rva2off(secs, aname) + 4 * i)[0]
        nord = struct.unpack_from('<H', data, rva2off(secs, aord) + 2 * i)[0]
        frva = struct.unpack_from('<I', data, rva2off(secs, afunc) + 4 * (base + nord - base))[0]
        off = rva2off(secs, nrva)
        end = data.index(b'\x00', off)
        rows.append((base + nord, data[off:end].decode('ascii', 'replace'), frva))
    for ordv, nm, frva in sorted(rows):
        extra = ''
        if nm.startswith('_') and '@' in nm:
            try:
                nbytes = int(nm.rsplit('@', 1)[1])
                extra = '  -> stdcall %d bytes = %d dwords' % (nbytes, nbytes // 4)
            except ValueError:
                pass
        print('  ord=%-4d func=%08x %s%s' % (ordv, frva, nm, extra))
    print('total: %d' % len(rows))
    return 0


if __name__ == '__main__':
    raise SystemExit(main(DLL))
