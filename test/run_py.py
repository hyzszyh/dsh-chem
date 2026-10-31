r"""Run every engine assertion suite with the runtime interpreter.

    %LOCALAPPDATA%\dsh-chem\runtime\Scripts\python.exe test/run_py.py

Exits non-zero if any suite fails, so CI and preflight can call one command.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITES = ["py_props", "py_clean", "py_calc", "py_compare", "py_table", "py_draw",
          "py_enum", "py_parse", "py_db", "py_ml", "py_vendor", "py_office",
          "py_exam", "py_spectra", "py_retro"]


def main() -> int:
    failures = []
    for name in SUITES:
        script = ROOT / "test" / (name + ".py")
        if not script.is_file():
            print("SKIP  %s (missing)" % name)
            continue
        proc = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        tail = [line for line in proc.stdout.strip().splitlines() if line.strip()][-1:] or [""]
        status = "PASS" if proc.returncode == 0 else "FAIL"
        if proc.returncode != 0:
            failures.append(name)
        print("%s  %s  %s" % (status, name, tail[0]))
    print("")
    if failures:
        print("engine suites: %d FAIL (%s)" % (len(failures), ", ".join(failures)))
        return 1
    print("engine suites: %d/%d PASS" % (len(SUITES), len(SUITES)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
