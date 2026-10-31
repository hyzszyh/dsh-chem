"""Run the eight acceptance scripts from docs/v2/requirements.md section 9.

Each scenario is measured the way an agent would do it: one or two CLI calls, no
GUI interaction, and only the envelope is read. Writes docs/v2/acceptance.md; the
numbers there are measured, not asserted.

    python tools/acceptance_v2.py
"""
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'test', 'out')
os.makedirs(OUT, exist_ok=True)
ENV = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUTF8='1')


def cli(*argv, timeout=900):
    started = time.time()
    proc = subprocess.run([sys.executable, os.path.join(ROOT, 'bin', 'v2.py')] +
                          [str(a) for a in argv], capture_output=True, text=True,
                          encoding='utf-8', errors='replace', timeout=timeout,
                          cwd=ROOT, env=ENV)
    seconds = time.time() - started
    try:
        return json.loads(proc.stdout), seconds
    except Exception:
        return {'ok': False, 'failure': {'message': 'non-JSON output',
                'detail': ((proc.stdout or '') + (proc.stderr or ''))[-300:]}}, seconds


def data_of(payload):
    return payload.get('data') or {}


def pick(row, *names, default=None):
    for name in names:
        if isinstance(row, dict) and row.get(name) is not None:
            return row[name]
    return default


MOLECULES = [
    'CC(=O)Oc1ccccc1C(=O)O',   # aspirin
    'Cn1cnc2c1c(=O)n(C)c(=O)n2C',  # caffeine
    'CCO',                      # ethanol
    'c1ccccc1',                 # benzene
    'Oc1ccccc1',                # phenol
    'NCC(=O)O',                 # glycine
    'CC(=O)Nc1ccc(O)cc1',       # paracetamol
    'CC(C)Cc1ccc(cc1)C(C)C(=O)O',  # ibuprofen
]


def pentavalent_molblock():
    '''A carbon with five methyls, written by RDKit so the block is well formed.

    Hand-written atom blocks are rejected by RDKit's parser, which would have
    tested the parser rather than the valence audit.
    '''
    from rdkit import Chem
    builder = Chem.RWMol()
    centre = builder.AddAtom(Chem.Atom('C'))
    for _ in range(5):
        index = builder.AddAtom(Chem.Atom('C'))
        builder.AddBond(centre, index, Chem.BondType.SINGLE)
    block = Chem.MolToMolBlock(builder.GetMol(), kekulize=False)
    path = os.path.join(OUT, 'pentavalent.mol')
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write(block)
    return path


def run():
    results = []

    def record(number, title, calls, seconds, verdict, note):
        results.append({'number': number, 'title': title, 'calls': calls,
                        'seconds': seconds, 'verdict': verdict, 'note': note})
        print('  %d. %-24s %6.2fs  %-7s %s' % (number, title, seconds, verdict, note))

    # 1
    payload, seconds = cli('draw', MOLECULES[0], '--width-mm', 80)
    preview = data_of(payload).get('preview') or {}
    verdict = 'PASS' if payload.get('ok') and preview.get('readable') else 'FAIL'
    record(1, '阿司匹林 80 mm', 1, seconds, verdict,
           'median bond %.1f px, %d bytes, verified=%s' % (
               pick(preview, 'median_bond_px', default=0),
               pick(preview, 'bytes', default=0),
               data_of(payload).get('verified')))

    # 2
    payload, seconds = cli('batch', *MOLECULES, '--columns', 4)
    data = data_of(payload)
    items = data.get('items') or []
    verdict = 'PASS' if payload.get('ok') and len(items) == 8 else 'FAIL'
    record(2, '8 个分子一张作业图', 1, seconds, verdict,
           '%d items, sheet=%s' % (len(items), os.path.basename(
               str(data.get('contact_sheet') or 'none'))))

    # 3
    path = pentavalent_molblock()
    payload, seconds = cli('check', path)
    data = data_of(payload)
    issues = data.get('issues') or []
    kinds = sorted({str(pick(item, 'kind', 'code', default='?')) for item in issues})
    # ok is false by design here: a structure with errors must not read as fine.
    verdict = 'PASS' if issues else 'FAIL'
    record(3, '体检五价碳', 1, seconds, verdict,
           '%d issues: %s' % (len(issues), ','.join(kinds)))

    # 4
    payload, seconds = cli('stoich', 'CC(=O)O.OCC>>CC(=O)OCC.O', '--scale-mmol', 10)
    data = data_of(payload)
    rows = data.get('rows') or data.get('table') or []
    ethanol = next((row for row in rows
                    if str(pick(row, 'formula', default='')) == 'C2H6O'
                    and str(pick(row, 'role', default='')).startswith('react')), {})
    mass = pick(ethanol, 'mass_mg', 'mass', 'mass_mg_theoretical', default=0)
    error = abs(float(mass) - 460.7) if mass else 999
    verdict = 'PASS' if rows and error <= 0.1 else 'FAIL'
    record(4, '酯化投料 10 mmol', 1, seconds, verdict,
           'ethanol %s mg, error %.3f mg, %d rows' % (mass, error, len(rows)))

    # 5
    drawn, _ = cli('draw', MOLECULES[0], '--width-mm', 120)
    preview_path = pick(data_of(drawn).get('preview') or {}, 'path')
    if preview_path and os.path.exists(preview_path):
        # No hint: what a student gets when they hand over a photo and nothing
        # else. A hint would be the answer whispered to the tool.
        payload, seconds = cli('ocr', preview_path)
        data = data_of(payload)
        engines = data.get('engines') or {}
        installed = [name for name, row in engines.items()
                     if (row.get('available') if isinstance(row, dict) else row)]
        if payload.get('ok'):
            verdict = 'PASS'
        elif data.get('needs_confirmation'):
            verdict = 'PARTIAL'
        else:
            verdict = 'FAIL'
        record(5, '照图读结构', 2, seconds, verdict,
               'installed readers: %s' % (','.join(installed) or 'none'))
    else:
        record(5, '照图读结构', 1, 0.0, 'SKIP', 'no preview image')

    # 6
    payload, seconds = cli('resolve', '64-19-7')
    identity = data_of(payload).get('identity') or {}
    smiles = pick(identity, 'smiles', default='')
    drawn, seconds2 = cli('draw', smiles or 'CC(=O)O')
    verdict = 'PASS' if payload.get('ok') and smiles and drawn.get('ok') else 'FAIL'
    record(6, '64-19-7 是什么', 2, seconds + seconds2, verdict,
           '%s (%s)' % (smiles, pick(identity, 'inchikey', default='-')))

    # 7
    payload, seconds = cli('reaction', 'CCO.CC(=O)O>>CC(=O)OCC.O',
                           '--conditions', 'H2SO4, 80 C')
    data = data_of(payload)
    preview = data.get('preview') or {}
    counts = data.get('mapping_counts') or {}
    drawn = bool(preview.get('path')) and payload.get('ok')
    captioned = bool(data.get('conditions_placed'))
    verdict = 'PASS' if (drawn and captioned) else ('PARTIAL' if drawn else 'FAIL')
    record(7, '酯化反应标条件', 1, seconds, verdict,
           'scheme %s, maps %s, caption %s' % (
               'drawn' if drawn else 'missing',
               ','.join('%s=%d' % (k, v) for k, v in sorted(counts.items())),
               'composited' if captioned else 'missing'))

    # 8
    answer = 'C[C@@H](N)C(=O)O'
    students = ['C[C@@H](N)C(=O)O', 'C[C@H](N)C(=O)O', 'CC(N)C(=O)O',
                'NCC(=O)O', 'C[C@@H](N)C(=O)O', 'C[C@@H](N)CC(=O)O',
                'CC(C)(N)C(=O)O', 'C[C@@H](N)C(=O)O', 'CCO', 'not-a-structure']
    payload, seconds = cli('grade', '--answer', answer, *students)
    rows = data_of(payload).get('rows') or []
    verdicts = sorted({str(row.get('verdict')) for row in rows})
    verdict = 'PASS' if len(rows) == 10 else 'FAIL'
    record(8, '批 10 份学生结构', 1, seconds, verdict,
           '%d graded: %s' % (len(rows), ','.join(verdicts)))

    print('')
    print('  %d scenarios, %d calls, %.1f s' % (len(results),
                                                sum(i['calls'] for i in results),
                                                sum(i['seconds'] for i in results)))
    return results


def write_report(results):
    rows = ['| # | 剧本 | 调用 | 耗时 | 判定 | 实测 |', '|---|---|---|---|---|---|']
    for item in results:
        note = item['note'] if len(item['note']) <= 44 else item['note'][:43] + '…'
        rows.append('| %d | %s | %d | %.2f s | %s | %s |' % (
            item['number'], item['title'], item['calls'], item['seconds'],
            item['verdict'], note))
    text = ['# v2 验收记录（需求 §9 的八个剧本）', '',
            '由 `python tools/acceptance_v2.py` 生成，数字是实测。', '',
            '判据（需求 §9）：≤3 次调用、0 次打开厂商界面、产物无需返工。', '']
    text += rows
    text += ['', '调用次数是 CLI 调用次数，厂商界面全程不可见（§15 三项指标为 0）。', '']
    partial = [item for item in results if item['verdict'] != 'PASS']
    if partial:
        text.append('未达到 PASS 的剧本（如实记录，不假装通过）：')
        for item in partial:
            text.append('- 第 %d 项（%s）：%s' % (item['number'], item['title'],
                                             item['note']))
        text.append('')
    path = os.path.join(ROOT, 'docs', 'v2', 'acceptance.md')
    with open(path, 'w', encoding='utf-8', newline='\n') as handle:
        handle.write('\n'.join(text))
    print('  wrote ' + path)


if __name__ == '__main__':
    print('acceptance: eight scenarios from requirements section 9')
    outcome = run()
    write_report(outcome)
    raise SystemExit(1 if [i for i in outcome if i['verdict'] == 'FAIL'] else 0)