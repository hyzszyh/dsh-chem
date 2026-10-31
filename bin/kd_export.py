'''64-bit launcher for the KingDraw export: prints one JSON Result line.

The bundled 32-bit runtime has neither pywinauto nor Pillow, so the export runs
here and kd_export.export_image() calls this script when it needs the bridge.
'''
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'core'))

# Marks this process as the helper, so a missing package here reports a failure
# instead of spawning another helper.
os.environ['CHEMTOOL_KD_EXPORT_HELPER'] = '1'


def main(argv):
    import argparse
    from chemdraw_tool.adapters import kd_export

    ap = argparse.ArgumentParser(prog='kd_export.py')
    ap.add_argument('path')
    ap.add_argument('--out', default=None)
    ap.add_argument('--timeout', type=float, default=90.0)
    ap.add_argument('--min-side', type=int, default=300)
    ap.add_argument('--keep-kdx', action='store_true')
    ap.add_argument('--keep-open', action='store_true')
    ap.add_argument('--no-overwrite', action='store_true')
    ap.add_argument('--python64', default=None)
    ap.add_argument('--result-file', default=None,
                    help='write the JSON Result here instead of stdout (the caller '
                         'that started KingDraw must not use pipes)')
    args = ap.parse_args(argv[1:])
    # This process is the one that drives the single-instance KingDraw window,
    # so it takes the app lock for the whole open+save+extract cycle. The
    # caller in bridge mode holds nothing (it would deadlock against us); the
    # lock here is what keeps two parallel exports from fighting over one
    # window.
    from chemdraw_tool import applock
    try:
        held = applock.hold(applock.KINGDRAW, timeout=args.timeout)
    except applock.AppBusy as busy:
        res = kd_export.Result(
            ok=False, channel=kd_export.CHANNEL,
            evidence=kd_export.EVIDENCE_MEASURED,
            failure=kd_export._failure(
                kd_export.ErrorCode.KD_CLI_DID_NOT_OPEN, 'lock',
                detail=busy.hint(),
                message='KingDraw is busy with another call',
                hint=busy.hint()))
    else:
        try:
            res = kd_export.export_image(
                args.path, args.out, timeout=args.timeout, keep_kdx=args.keep_kdx,
                min_side=args.min_side, close_app=not args.keep_open,
                python64=args.python64, overwrite=not args.no_overwrite)
        finally:
            held.release()
    text = json.dumps(res.to_dict(), ensure_ascii=False)
    if args.result_file:
        tmp = args.result_file + '.part'
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(text)
        os.replace(tmp, args.result_file)
    else:
        print(text)
        sys.stdout.flush()
    # Hard exit: comtypes/UIA keeps worker threads alive and interpreter shutdown
    # can block for minutes even though the work is finished and KingDraw is
    # closed. The caller waits for the result file, so nothing is lost.
    os._exit(0 if res.ok else 1)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
