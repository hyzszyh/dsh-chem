'''Launcher for the 64-bit UIA reader.

The bundled 32-bit runtime has neither pywinauto nor comtypes, so this script is
executed by the 64-bit interpreter that does; core/ is put on sys.path the same
way bin/cli.py and bin/kd_worker.py do it.

Usage: python bin/kd_uia.py <pid>   -> one JSON object on stdout
'''

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))

from chemdraw_tool.kd_uia import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
