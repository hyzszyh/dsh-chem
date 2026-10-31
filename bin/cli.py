'''Thin launcher so both interpreters can run the package without installing it.'''

import os
import sys

# Windows consoles default to cp1252; molecule names and paths are UTF-8.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))

from chemdraw_tool.cli import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())