"""Journal figure presets and the width a page can actually afford.

A preset is a promise: 80 mm means 80 mm in the exported file, and a bond has to
stay long enough to read at that width (FR-O1, FR-D12).
"""

PRESETS = {
    'cn-1col': {'width_mm': 80.0, 'dpi': 600,
                'note': '中文期刊单栏 8 cm'},

    'cn-2col': {'width_mm': 170.0, 'dpi': 600,
                'note': '中文期刊图式跨栏 17 cm'},
    'acs-1col': {'width_mm': 82.6, 'dpi': 600, 'note': 'ACS 单栏 3.25 in'},
    'acs-2col': {'width_mm': 177.8, 'dpi': 600, 'note': 'ACS 双栏 7 in'},
    'rsc-1col': {'width_mm': 83.0, 'dpi': 600, 'note': 'RSC 单栏'},
    'nature-1col': {'width_mm': 89.0, 'dpi': 600, 'note': 'Nature 单栏 89 mm'},
    'nature-2col': {'width_mm': 183.0, 'dpi': 600, 'note': 'Nature 双栏 183 mm'},
    'web': {'width_mm': 140.0, 'dpi': 300, 'note': '屏幕/讲义，非投稿'},
}


def preset(name: str) -> dict:
    '''Look a preset up, or raise a KeyError naming the ones that exist.'''
    key = (name or 'cn-1col').strip().lower()
    if key not in PRESETS:
        raise KeyError('%s; known: %s' % (key, ', '.join(sorted(PRESETS))))
    data = dict(PRESETS[key])
    data['name'] = key
    return data


def resolve(preset_row: dict, stats: dict, suggested_mm: float) -> dict:
    '''Does the drawing read at the preset width, and what would make it read?'''
    width = float(preset_row['width_mm'])
    readable = bool(stats.get('readable'))
    return {
        'preset': preset_row['name'],
        'width_mm': width,
        'dpi': int(preset_row['dpi']),
        'readable_at_preset': readable,
        'median_bond_px': stats.get('median_px'),
        'wider_mm': round(suggested_mm, 1),
        'advice': ('as asked' if readable else
                   'needs about %g mm to stay readable; split it or accept the loss'
                   % round(suggested_mm, 1)),
    }