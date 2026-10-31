#!/usr/bin/env python
"""dsh-chem runtime bootstrap: build an isolated venv and install pinned deps.

Usage:
  python bin/setup.py --check          # 只探测，不改动
  python bin/setup.py                  # 建 venv 并装 core 依赖
  python bin/setup.py --extras retro,spectra
  python bin/setup.py --recreate       # 删掉重建
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCAL = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
RUNTIME = LOCAL / "dsh-chem" / "runtime"
VENV_PY = RUNTIME / "Scripts" / "python.exe" if os.name == "nt" else RUNTIME / "bin" / "python"
RUNTIME_JSON = LOCAL / "dsh-chem" / "runtime.json"
EXTRAS = {"retro": ["rdchiral==1.1.0", "aizynthfinder>=4.3"],
          "spectra": ["nmrglue>=0.10", "matchms>=0.28"],
          "similar": ["mmpdb>=3.1", "fpsim2>=0.7"]}


def candidates():
    """Interpreters to build the venv from, in priority order."""
    out = []
    for p in sorted(glob.glob(str(Path.home() / ".dsh" / "dsh-runtimes" / "*" / "dependencies" / "python" / "python.exe"))):
        out.append(("dsh-bundled", p))
    for p in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python313" / "python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python311" / "python.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python310" / "python.exe",
    ):
        if p.exists():
            out.append(("system", str(p)))
    for name in ("python", "python3"):
        w = shutil.which(name)
        if w:
            out.append(("path", w))
    return out


def ascii_tmp() -> Path:
    p = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "Temp" / "dsh-chem-setup"
    p.mkdir(parents=True, exist_ok=True)
    return p


def run(cmd, **kw):
    env = dict(os.environ)
    tmp = str(ascii_tmp())
    env.update({"TMP": tmp, "TEMP": tmp, "PYTHONIOENCODING": "utf-8"})
    return subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)


def check(extras):
    info = {"runtime": str(RUNTIME), "venv_python": str(VENV_PY), "exists": VENV_PY.exists(),
            "candidates": [], "requirements": str(ROOT / "requirements-runtime.txt"), "extras": extras}
    for kind, path in candidates():
        r = run([path, "-c", "import sys; print(sys.version.split()[0])"])
        info["candidates"].append({"kind": kind, "path": path,
                                   "version": r.stdout.strip() if r.returncode == 0 else None})
    free = shutil.disk_usage(LOCAL).free / 1e9
    info["free_gb"] = round(free, 1)
    info["ok"] = bool(info["candidates"]) and free > 1.0
    return info


def build(extras, recreate):
    if recreate and RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    info = check(extras)
    if not info["candidates"]:
        return {"ok": False, "error": "no python interpreter found", "check": info}
    tried = []
    if not VENV_PY.exists():
        RUNTIME.parent.mkdir(parents=True, exist_ok=True)
        for cand in info["candidates"]:
            if RUNTIME.exists():
                shutil.rmtree(RUNTIME, ignore_errors=True)
            r = run([cand["path"], "-m", "venv", str(RUNTIME)])
            tried.append({"base": cand["path"], "kind": cand["kind"], "rc": r.returncode,
                          "err": (r.stderr or r.stdout or "")[-300:]})
            if r.returncode == 0 and VENV_PY.exists():
                break
        else:
            return {"ok": False, "error": "venv create failed for every candidate", "tried": tried}
    steps = []
    r = run([str(VENV_PY), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    steps.append({"step": "pip-upgrade", "rc": r.returncode})
    r = run([str(VENV_PY), "-m", "pip", "install", "-r", str(ROOT / "requirements-runtime.txt")])
    steps.append({"step": "core", "rc": r.returncode, "tail": (r.stdout or r.stderr)[-400:]})
    for group in extras:
        pkgs = EXTRAS.get(group)
        if not pkgs:
            steps.append({"step": group, "rc": -1, "error": "unknown group"})
            continue
        r = run([str(VENV_PY), "-m", "pip", "install", *pkgs])
        steps.append({"step": group, "rc": r.returncode, "tail": (r.stdout or r.stderr)[-300:]})
    probe = run([str(VENV_PY), str(ROOT / "bin" / "chem.py"), "probe"])
    versions = {}
    try:
        versions = json.loads(probe.stdout)["probe"]["packages"]
    except Exception:
        versions = {}
    base_info = tried
    cfg = RUNTIME / "pyvenv.cfg"
    if cfg.exists():
        try:
            kv = dict(line.split(" = ", 1) for line in cfg.read_text(encoding="utf-8").splitlines() if " = " in line)
            base_info = [{"kind": "existing-venv", "home": kv.get("home", "").strip(),
                          "version": kv.get("version", "").strip()}]
        except Exception:
            pass
    # A probe that swallows ImportError still exits 0, so ok cannot be the probe's
    # return code alone: a fresh machine ran pip, hit an unsatisfiable pin, and the
    # script still reported success with nine null packages (measured 2026-10-31).
    missing = sorted(name for name, version in (versions or {}).items() if not version)
    failed = [step.get('step') for step in steps if step.get('rc') not in (0,)]
    payload = {'ok': probe.returncode == 0 and not missing and not failed,
               'built_at': __import__('datetime').datetime.now().isoformat(' ', 'seconds'),
               'venv': str(RUNTIME), 'base_python': base_info, 'steps': steps,
               'packages': versions}
    if not payload['ok']:
        detail = '缺 %s；失败步骤 %s' % (','.join(missing) or '无', ','.join(failed) or '无')
        payload['hint'] = ('核心依赖没装齐（' + detail + '）。看 steps 里 rc != 0 的那一条；'
                           '常见原因是网络或版本约束，修好后重跑 python bin/setup.py')
    RUNTIME_JSON.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--recreate", action="store_true")
    ap.add_argument("--extras", default="")
    a = ap.parse_args()
    extras = [x.strip() for x in a.extras.split(",") if x.strip()]
    if a.check:
        print(json.dumps(check(extras), ensure_ascii=False, indent=2))
        return 0
    out = build(extras, a.recreate)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
