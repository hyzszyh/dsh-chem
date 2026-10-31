import os
import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'core'))

if '--surface' in sys.argv and sys.argv[sys.argv.index('--surface') + 1] == 'tasks':
    from chemdraw_tool.mcp_tasks import serve as serve_tasks
    raise SystemExit(serve_tasks())

from chemdraw_tool.mcp_server import serve  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(serve())