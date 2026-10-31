"""Two independent routes, one capability table (requirements §14).

ChemDraw and KingDraw share nothing at runtime: no imports across the two,
separate application locks, separate state. A task picks the first route in its
candidate list that is actually available, and every answer reports which one
served it.
"""

import os

CHEMDRAW = 'chemdraw'
KINGDRAW = 'kingdraw'

ROUTES = {
    CHEMDRAW: {
        'bits': 64,
        'driver': 'com+command',
        'lock': 'chem-draw-tool.chemdraw',
        'needs_license': True,
        'strengths': ['objects', 'readback', 'figure export'],
    },
    KINGDRAW: {
        'bits': 32,
        'driver': 'dll+host',
        'lock': 'chem-draw-tool.kingdraw',
        'needs_license': False,
        'strengths': ['no license', 'format conversion', 'formula', '3d'],
    },
}

# task -> candidate routes, in the order they should be tried.
TASKS = {
    'status': [CHEMDRAW, KINGDRAW],
    'draw': [CHEMDRAW, KINGDRAW],
    'figure': [CHEMDRAW, KINGDRAW],
    'convert': [KINGDRAW, CHEMDRAW],
    'formula': [KINGDRAW, CHEMDRAW],
    'close': [CHEMDRAW, KINGDRAW],
}

PROGID = 'ChemDraw_x64.Application'


def _progid_registered(progid: str = PROGID) -> bool:
    '''Is the ChemDraw ProgID on this machine? No application is started.'''
    try:
        import winreg
    except Exception:
        return False
    for root in (winreg.HKEY_CLASSES_ROOT,):
        try:
            with winreg.OpenKey(root, progid) as key:
                winreg.QueryValueEx(key, '')
                return True
        except OSError:
            return False
    return False


def _kingdraw_dll() -> str:
    '''The KingDraw DLL path, resolved the same way the v1 adapter does.'''
    try:
        from ..adapters import kd_native
        home = kd_native.find_home()
        if home:
            candidate = os.path.join(home, kd_native.DLL_NAME)
            if os.path.exists(candidate):
                return candidate
    except Exception:
        pass
    for root in ('D:/tool/KingDraw', 'C:/Program Files/KingDraw',
                 'C:/Program Files (x86)/KingDraw'):
        if not os.path.isdir(root):
            continue
        for base, _dirs, files in os.walk(root):
            for name in files:
                if name.lower().endswith('.dll') and 'kingdraw' in name.lower():
                    return os.path.join(base, name)
    return ''


def available() -> dict:
    '''Route -> bool, probed without launching anything.'''
    return {
        CHEMDRAW: _progid_registered(),
        KINGDRAW: bool(_kingdraw_dll()),
    }


def pick(task: str, have: dict = None) -> str:
    '''First candidate route for this task that is actually usable.'''
    have = available() if have is None else have
    for name in TASKS.get(task, list(ROUTES)):
        if have.get(name):
            return name
    return ''