"""v2 task CLI: one JSON envelope per call.

The agent talks to these verbs; everything else (MCP, plugin) is a transport in
front of them. See docs/v2/requirements.md §7.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'core'))

from chemdraw_tool.v2 import tasks  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='v2')
    sub = parser.add_subparsers(dest='verb', required=True)
    sub.add_parser('status')

    draw = sub.add_parser('draw')
    draw.add_argument('source')
    draw.add_argument('--width-mm', type=float, default=None)
    draw.add_argument('--dpi', type=int, default=300)
    draw.add_argument('--out-dir', default=None)
    draw.add_argument('--name', default='')
    draw.add_argument('--visible', action='store_true')

    fig = sub.add_parser('figure')
    fig.add_argument('source')
    fig.add_argument('--preset', default='cn-1col')
    fig.add_argument('--out-dir', default=None)
    fig.add_argument('--name', default='')

    bat = sub.add_parser('batch')
    bat.add_argument('sources', nargs='+')
    bat.add_argument('--width-mm', type=float, default=None)
    bat.add_argument('--dpi', type=int, default=300)
    bat.add_argument('--columns', type=int, default=3)
    bat.add_argument('--no-sheet', action='store_true')

    con = sub.add_parser('convert')
    con.add_argument('source')
    con.add_argument('--to', default='sdf')
    con.add_argument('--label', default='')

    ana = sub.add_parser('analyze')
    ana.add_argument('sources', nargs='+')

    chk = sub.add_parser('check')
    chk.add_argument('source')
    chk.add_argument('--with-layout', action='store_true')

    st = sub.add_parser('stoich')
    st.add_argument('reaction')
    st.add_argument('--scale-mmol', type=float, default=1.0)
    st.add_argument('--yield', dest='yield_percent', type=float, default=None)

    rx = sub.add_parser('reaction')
    rx.add_argument('reaction')
    rx.add_argument('--conditions', default='')
    rx.add_argument('--width-mm', type=float, default=None)
    rx.add_argument('--dpi', type=int, default=300)
    rx.add_argument('--out-dir', default=None)
    rx.add_argument('--name', default='')

    d3 = sub.add_parser('3d')
    d3.add_argument('source')
    d3.add_argument('--no-optimize', action='store_true')
    d3.add_argument('--label', default='')

    rs = sub.add_parser('resolve')
    rs.add_argument('query')
    rs.add_argument('--offline', action='store_true')

    oc = sub.add_parser('ocr')
    oc.add_argument('image', nargs='?', default='')
    oc.add_argument('--llm-hint', default='')
    oc.add_argument('--engines', default='',
                    help='comma separated subset, e.g. molvec,decimer')
    oc.add_argument('--probe', action='store_true',
                    help='report which readers exist and what they need')
    gr = sub.add_parser('grade')
    gr.add_argument('--answer', required=True)
    gr.add_argument('submissions', nargs='+')

    va = sub.add_parser('variants')
    va.add_argument('scaffold')
    va.add_argument('substituents', nargs='+')
    close = sub.add_parser('close')
    close.add_argument('--quit', action='store_true')
    return parser


def run(args) -> dict:
    if args.verb == 'status':
        return tasks.status()
    if args.verb == 'draw':
        return tasks.draw(args.source, width_mm=args.width_mm, dpi=args.dpi,
                           out_dir=args.out_dir, visible=args.visible,
                           name=args.name)
    if args.verb == 'figure':
        return tasks.figure_export(args.source, preset=args.preset,
                                    out_dir=args.out_dir, name=args.name)
    if args.verb == 'batch':
        return tasks.batch(args.sources, width_mm=args.width_mm, dpi=args.dpi,
                           columns=args.columns, sheet=not args.no_sheet)
    if args.verb == 'convert':
        return tasks.convert(args.source, to=args.to, label=args.label)
    if args.verb == 'analyze':
        return tasks.analyze(args.sources)
    if args.verb == 'check':
        return tasks.check(args.source, with_layout=args.with_layout)
    if args.verb == 'stoich':
        return tasks.stoich(args.reaction, scale_mmol=args.scale_mmol,
                            yield_percent=args.yield_percent)
    if args.verb == 'reaction':
        return tasks.reaction_scheme(args.reaction, conditions=args.conditions,
                                     width_mm=args.width_mm, dpi=args.dpi,
                                     out_dir=args.out_dir, name=args.name)
    if args.verb == '3d':
        return tasks.three_d(args.source, optimize=not args.no_optimize,
                             label=args.label)
    if args.verb == 'resolve':
        return tasks.resolve_name(args.query, allow_network=not args.offline)
    if args.verb == 'ocr':
        if args.probe or not args.image:
            return tasks.ocr_probe()
        wanted = [row.strip() for row in (args.engines or '').split(',') if row.strip()]
        return tasks.ocr(args.image, llm_hint=args.llm_hint,
                         engines=wanted or None)
    if args.verb == 'grade':
        return tasks.grade(args.answer, args.submissions)
    if args.verb == 'variants':
        return tasks.variants(args.scaffold, args.substituents)
    return tasks.close(quit_app=args.quit)


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    result = run(args)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write('\n')
    return 0 if result.get('ok') else 1


if __name__ == '__main__':
    raise SystemExit(main())