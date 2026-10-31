#!/usr/bin/env python
"""Install dsh-chem with one command: runtime, plugin folder, profile wiring, self-check.

    git clone https://github.com/hyzszyh/dsh-chem.git && python dsh-chem/bin/install.py

Why one script instead of four steps: the four steps were only separate because they
used to be written for different people (the runtime was for the CLI, the plugin copy
was for the host). For someone who just wants the tools to show up, a missing venv or
a forgotten profile edit is a silent failure, and "invisible plugin" was the single
most common result of getting one of them wrong.

    python bin/install.py              # install or repair, then self-check
    python bin/install.py --check      # compare only, change nothing
    python bin/install.py --remove     # uninstall and unwire
    python bin/install.py --extras retro,spectra
    python bin/install.py --recreate   # rebuild the venv from scratch
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "bin"))
sys.path.insert(0, str(REPO / "tools"))

import install_plugin  # noqa: E402
import setup as runtime  # noqa: E402


def selfcheck() -> dict:
    """Run the engine's own self-check with the installed interpreter."""
    entry = install_plugin.dsh_home() / "plugins" / install_plugin.PLUGIN_NAME / "engine" / "bin" / "chem.py"
    python = runtime.VENV_PY
    if not entry.is_file():
        return {"ok": False, "problem": "installed engine missing", "path": str(entry)}
    if not python.exists():
        return {"ok": False, "problem": "runtime missing", "path": str(python)}
    out = subprocess.run([str(python), str(entry), "selfcheck", "--json"], capture_output=True, text=True)
    try:
        payload = json.loads(out.stdout.strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "problem": "selfcheck did not return JSON",
                "stderr": (out.stderr or out.stdout)[-300:]}
    return payload


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    remove = "--remove" in argv
    check_only = "--check" in argv
    recreate = "--recreate" in argv
    extras = []
    if "--extras" in argv:
        index = argv.index("--extras")
        if index + 1 < len(argv):
            extras = [part.strip() for part in argv[index + 1].split(",") if part.strip()]

    target = install_plugin.dsh_home() / "plugins" / install_plugin.PLUGIN_NAME

    if remove:
        code = install_plugin.remove(target)
        install_plugin.unwire_profile()
        return code

    if check_only:
        code = install_plugin.check(target)
        report = selfcheck()
        print(json.dumps({"selfcheck": report.get("ok"), "checks": len(report.get("checks") or [])},
                         ensure_ascii=False))
        return 0 if code == 0 and report.get("ok") else 1

    print("[1/3] runtime ...")
    payload = runtime.build(extras, recreate)
    if not payload.get("ok"):
        print(json.dumps({"ok": False, "stage": "runtime", "hint": payload.get("hint"),
                          "steps": [s.get("step") for s in payload.get("steps", []) if s.get("rc") not in (0,)]},
                         ensure_ascii=False))
        return 1

    print("[2/3] plugin + profile ...")
    code = install_plugin.install(target)
    if code != 0:
        return code
    wired = install_plugin.wire_profile(target)
    if not wired.get("ok"):
        print(json.dumps(wired, ensure_ascii=False))
        return 1

    print("[3/3] self-check ...")
    report = selfcheck()
    ok = bool(report.get("ok"))
    print(json.dumps({
        "ok": ok,
        "venv": payload.get("venv"),
        "packages": payload.get("packages"),
        "profile_changed": wired.get("changed"),
        "selfcheck": [c.get("name") for c in report.get("checks") or []],
        "vendors": (report.get("probe") or {}).get("vendors"),
        "next": "重开 DSH：右栏出现「化学绘图」，模型侧多出 15 个 chem_* 工具",
    }, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
