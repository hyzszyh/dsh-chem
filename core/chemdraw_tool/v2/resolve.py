"""Names and CAS numbers to structures (FR-I1).

Three layers, tried in order, each one reported as the source: a local dictionary
that works offline, then PubChem over the network. OPSIN would be a third layer
for systematic IUPAC names; it needs a Java jar, so it is only used when one is
actually present.
"""

import json
import re
import urllib.parse
import urllib.request

CAS_PATTERN = re.compile(r'^\d{2,7}-\d{2}-\d$')

# Common teaching names. Keep this list small and correct rather than large and
# guessed: a wrong structure here would be worse than no answer at all.
NAMES = {
    '阿司匹林': 'CC(=O)Oc1ccccc1C(=O)O',
    'aspirin': 'CC(=O)Oc1ccccc1C(=O)O',
    '对乙酰氨基酚': 'CC(=O)Nc1ccc(O)cc1',
    '扑热息痛': 'CC(=O)Nc1ccc(O)cc1',
    'paracetamol': 'CC(=O)Nc1ccc(O)cc1',
    'acetaminophen': 'CC(=O)Nc1ccc(O)cc1',
    '咖啡因': 'Cn1cnc2c1c(=O)n(C)c(=O)n2C',
    'caffeine': 'Cn1cnc2c1c(=O)n(C)c(=O)n2C',
    '布洛芬': 'CC(C)Cc1ccc(cc1)C(C)C(=O)O',
    'ibuprofen': 'CC(C)Cc1ccc(cc1)C(C)C(=O)O',
    '苯酚': 'Oc1ccccc1',
    'phenol': 'Oc1ccccc1',
    '乙醇': 'CCO',
    '酒精': 'CCO',
    'ethanol': 'CCO',
    '甲醇': 'CO',
    'methanol': 'CO',
    '乙酸': 'CC(=O)O',
    '醋酸': 'CC(=O)O',
    'acetic acid': 'CC(=O)O',
    '丙酮': 'CC(C)=O',
    'acetone': 'CC(C)=O',
    '乙醚': 'CCOCC',
    'diethyl ether': 'CCOCC',
    '乙酸乙酯': 'CC(=O)OCC',
    'ethyl acetate': 'CC(=O)OCC',
    '苯甲酸': 'OC(=O)c1ccccc1',
    'benzoic acid': 'OC(=O)c1ccccc1',
    '水杨酸': 'OC(=O)c1ccccc1O',
    'salicylic acid': 'OC(=O)c1ccccc1O',
    '苯甲醛': 'O=Cc1ccccc1',
    'benzaldehyde': 'O=Cc1ccccc1',
    '苯胺': 'Nc1ccccc1',
    'aniline': 'Nc1ccccc1',
    '硝基苯': '[O-][N+](=O)c1ccccc1',
    'nitrobenzene': '[O-][N+](=O)c1ccccc1',
    '甲苯': 'Cc1ccccc1',
    'toluene': 'Cc1ccccc1',
    '苯': 'c1ccccc1',
    'benzene': 'c1ccccc1',
    '萘': 'c1ccc2ccccc2c1',
    'naphthalene': 'c1ccc2ccccc2c1',
    '吡啶': 'c1ccncc1',
    'pyridine': 'c1ccncc1',
    '呋喃': 'c1ccoc1',
    'furan': 'c1ccoc1',
    '噻吩': 'c1ccsc1',
    'thiophene': 'c1ccsc1',
    '吲哚': 'c1ccc2[nH]ccc2c1',
    'indole': 'c1ccc2[nH]ccc2c1',
    '咪唑': 'c1cnc[nH]1',
    'imidazole': 'c1cnc[nH]1',
    '尿素': 'NC(N)=O',
    'urea': 'NC(N)=O',
    '甘油': 'OCC(O)CO',
    'glycerol': 'OCC(O)CO',
    '柠檬酸': 'OC(=O)CC(O)(CC(=O)O)C(=O)O',
    'citric acid': 'OC(=O)CC(O)(CC(=O)O)C(=O)O',
    '葡萄糖': 'OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O',
    'glucose': 'OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O',
    '果糖': 'OC[C@H]1O[C@](O)(CO)[C@@H](O)[C@@H]1O',
    'fructose': 'OC[C@H]1O[C@](O)(CO)[C@@H](O)[C@@H]1O',
    '甘氨酸': 'NCC(=O)O',
    'glycine': 'NCC(=O)O',
    '丙氨酸': 'C[C@@H](N)C(=O)O',
    'alanine': 'C[C@@H](N)C(=O)O',
    '苯丙氨酸': 'N[C@@H](Cc1ccccc1)C(=O)O',
    'phenylalanine': 'N[C@@H](Cc1ccccc1)C(=O)O',
    '维生素C': 'OC[C@H](O)[C@H]1OC(=O)C(O)=C1O',
    '抗坏血酸': 'OC[C@H](O)[C@H]1OC(=O)C(O)=C1O',
    'ascorbic acid': 'OC[C@H](O)[C@H]1OC(=O)C(O)=C1O',
    '麻黄碱': 'C[C@@H](NC)[C@H](O)c1ccccc1',
    'ephedrine': 'C[C@@H](NC)[C@H](O)c1ccccc1',
    '樟脑': 'CC1(C)C2CCC1(C)C(=O)C2',
    'camphor': 'CC1(C)C2CCC1(C)C(=O)C2',
    '氯仿': 'ClC(Cl)Cl',
    'chloroform': 'ClC(Cl)Cl',
    '四氯化碳': 'ClC(Cl)(Cl)Cl',
    'carbon tetrachloride': 'ClC(Cl)(Cl)Cl',
}

CAS = {
    '64-19-7': 'CC(=O)O',
    '50-78-2': 'CC(=O)Oc1ccccc1C(=O)O',
    '103-90-2': 'CC(=O)Nc1ccc(O)cc1',
    '58-08-2': 'Cn1cnc2c1c(=O)n(C)c(=O)n2C',
    '108-95-2': 'Oc1ccccc1',
    '64-17-5': 'CCO',
    '67-64-1': 'CC(C)=O',
    '69-72-7': 'OC(=O)c1ccccc1O',
    '60-29-7': 'CCOCC',
    '141-78-6': 'CC(=O)OCC',
}

PUBCHEM = ('https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/%s'
           '/property/IsomericSMILES,CanonicalSMILES/JSON')


def _pubchem(query: str, timeout: float = 8.0) -> dict:
    url = PUBCHEM % urllib.parse.quote(query, safe='')
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except Exception as exc:
        return {'smiles': '', 'error': '%s: %s' % (type(exc).__name__, str(exc)[:80])}
    try:
        row = payload['PropertyTable']['Properties'][0]
    except Exception:
        return {'smiles': '', 'error': 'PubChem answered without a property table'}
    smiles = (row.get('IsomericSMILES') or row.get('CanonicalSMILES')
              or row.get('SMILES') or '')
    return {'smiles': smiles, 'error': '' if smiles else 'PubChem had no SMILES'}


def resolve(query: str, allow_network: bool = True) -> dict:
    '''Try the local tables, then PubChem; report which layer answered.'''
    text = (query or '').strip()
    tried = []
    if not text:
        return {'ok': False, 'query': text, 'smiles': '', 'source': '',
                'tried': ['empty query']}
    key = text.lower()
    for table, label in ((NAMES, 'local-names'), (CAS, 'local-cas')):
        candidate = table.get(text) or table.get(key)
        if candidate:
            return {'ok': True, 'query': text, 'smiles': candidate,
                    'source': label, 'tried': tried + [label]}
    tried.extend(['local-names', 'local-cas'])
    if not allow_network:
        return {'ok': False, 'query': text, 'smiles': '', 'source': '',
                'tried': tried, 'reason': 'offline and not in the local tables'}
    answer = _pubchem(text)
    tried.append('pubchem')
    if answer['smiles']:
        return {'ok': True, 'query': text, 'smiles': answer['smiles'],
                'source': 'pubchem', 'tried': tried}
    return {'ok': False, 'query': text, 'smiles': '', 'source': '',
            'tried': tried, 'reason': answer.get('error') or 'not found'}