from pathlib import Path
import sys, json
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'core'))
from PIL import Image
from chemdraw_tool import artwork

Image.new('RGBA', (4000, 3000), (255, 255, 255, 255)).save('test/out/_art_raw.png', dpi=(144, 144))
raw = artwork.check('test/out/_art_raw.png', journal='acs', min_dpi=1200)
print('raw ok:', raw.ok)
print('raw issues:', raw.data['issues'])
print('raw warnings:', [w[:70] for w in raw.data['warnings']])

r = artwork.normalize('test/out/_art_raw.png', 'test/out/_art_norm.tif', dpi=1200, max_width_mm=85)
print('normalize ok:', r.ok)
if r.ok:
    print('  bytes', r.data['bytes'], 'mode', r.data['mode'], 'size', r.data['width_px'], 'x', r.data['height_px'])
    print('  width_mm', r.data['width_mm'], 'before', r.data['before'])
    c = artwork.check('test/out/_art_norm.tif', journal='acs', min_dpi=1200)
    print('norm check ok:', c.ok, 'dpi', c.data['dpi'], 'mode', c.data['mode'])
print('export_args(4000, 1200):', artwork.export_args(4000, 1200))
print('export_args(3543, 1000):', artwork.export_args(3543, 1000))