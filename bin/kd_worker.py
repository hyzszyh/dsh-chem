'''Launcher for the 32-bit KingDraw worker.

The bundled embeddable interpreter does not put the working directory on
sys.path, so 'python -m chemdraw_tool.kd_worker' cannot resolve the package.
This launcher inserts core/ explicitly, the same way bin/cli.py does.
'''

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))

from chemdraw_tool.kd_worker import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())