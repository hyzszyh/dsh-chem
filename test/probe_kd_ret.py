'''Read the stdcall argument count straight out of each exported function.

x86 stdcall functions end with 'ret N' (C2 lo hi), x86 cdecl with plain 'ret'
(C3). Scanning the machine code of each export gives the argument byte count
without guessing, and the three decorated exports (_supKingToJson@4,
_kingCleanUp@24, _smilesToMolBA2@24) act as a self-check on the technique.
'''
from __future__ import annotations

import struct
import sys

DLL = sys.argv[1] if len(sys.argv) > 1 else r'D:\tool\KingDraw\GRDKitDll.dll'
NAMES = [
    'supKingToJson', '_supKingToJson@4', 'kingCleanUp', '_kingCleanUp@24',
    'cleanUp', 'molToSmiles', 'smilesToMol', 'smilesToMolBA',
    '_smilesToMolBA2@24', 'substructMatch', 'structMatch',
    'getMolFormula', 'getFormula', 'mol2dTo3d', 'smiles2dTo3d',
]


def load_sections(data: bytes):
    e = struct.unpack_from('<I', data, 0x3C)[0]
    coff = e + 4
    _m, nsec, _ts, _sym, _nsym, optsz, _c = struct.unpack_from('<HHIIIHH', data, coff)
    opt = coff + 20
    magic = struct.unpack_from('<H', data, opt)[0]
    dd = opt + (96 if magic == 0x10B else 112)
    exp_rva = struct.unpack_from('<II', data, dd)[0]
    secs = []
    off = opt + optsz
    for _ in range(nsec):
        vsz, va, rawsz, rawptr = struct.unpack_from('<IIII', data, off + 8)
        secs.append((va, vsz, rawsz, rawptr))
        off += 40
    return exp_rva, secs


def rva2off(secs, rva):
    for va, vsz, rawsz, rawptr in secs:
        if va <= rva < va + max(vsz, rawsz):
            delta = rva - va
            if delta >= rawsz:
                raise ValueError('uninitialized rva')
            return rawptr + delta
    raise ValueError('rva 0x%x not mapped' % rva)


def exports(data, secs, exp_rva):
    eo = rva2off(secs, exp_rva)
    (_c, _ts, _mj, _mn, _name, base, nfunc, nname,
     afunc, aname, aord) = struct.unpack_from('<IIHHIIIIIII', data, eo)
    fo, no, oo = rva2off(secs, afunc), rva2off(secs, aname), rva2off(secs, aord)
    out = {}
    for i in range(nname):
        nrva = struct.unpack_from('<I', data, no + 4 * i)[0]
        nord = struct.unpack_from('<H', data, oo + 2 * i)[0]
        frva = struct.unpack_from('<I', data, fo + 4 * (base + nord - base))[0]
        o = rva2off(secs, nrva)
        out[data[o:data.index(b'\x00', o)].decode('ascii', 'replace')] = frva
    return out


def scan_ret(data, secs, frva, window=0x600):
    off = rva2off(secs, frva)
    code = data[off:off + window]
    hits = []
    for i in range(len(code) - 3):
        b = code[i]
        if b == 0xC3:
            hits.append((i, 'ret', None))
        elif b == 0xC2 and i + 2 < len(code):
            n = struct.unpack_from('<H', code, i + 1)[0]
            if n % 4 == 0 and n <= 64:
                hits.append((i, 'ret-imm', n))
    return hits


def main():
    data = open(DLL, 'rb').read()
    exp_rva, secs = load_sections(data)
    table = exports(data, secs, exp_rva)
    print('export                     rva      first stdcall-ret   all ret-imm hits')
    for name in NAMES:
        if name not in table:
            print('%-26s MISSING' % name)
            continue
        frva = table[name]
        hits = scan_ret(data, secs, frva)
        imm = [h for h in hits if h[1] == 'ret-imm']
        plain = [h for h in hits if h[1] == 'ret']
        first = imm[0] if imm else None
        desc = ', '.join('%d@%d' % (h[2], h[0]) for h in imm[:6]) or '-'
        pd = ', '.join(str(h[0]) for h in plain[:4]) or '-'
        print('%-26s %08x  %-18s  stdcall:%-24s plain-ret:%s' % (
            name, frva,
            ('ret %d' % first[2]) if first else ('ret (at %d)' % plain[0][0] if plain else 'none'),
            desc, pd))


if __name__ == '__main__':
    main()
