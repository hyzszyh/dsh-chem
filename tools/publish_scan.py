"""Publishability scan: count machine-specific identifiers in the tree and history.

Run before any push to a public remote. Tree hits are fatal (exit 1); history hits
are reported with a count and a fix hint, because the only real cure there is
rewriting history with git filter-repo.

    python tools/publish_scan.py            # summary
    python tools/publish_scan.py --verbose  # show first 5 lines per category
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# category -> (regex, fate, note)
CATEGORIES = {
    "username": (r"hyzs_zyh", "fatal", "登录名出现在文本里"),
    "workspace_name": (r"成果存放", "fatal", "个人工作区中文目录名"),
    # \\Users\\<name>\\... with a real name; <...> and ... are placeholders and pass.
    "drive_path": (r"[A-Za-z]:\\Users\\(?!\.\.\.|<)[^\\\s'\"]+", "fatal", "带用户名的绝对路径"),
    "temp_dir": (r"[A-Za-z]:\\\\Temp\\\\cdprobe", "fatal", "本机临时目录"),
    "secret": (r"(sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})",
               "fatal", "看起来像密钥"),
    "local_appdata": (r"%LOCALAPPDATA%", "ok", "环境变量写法，可移植"),
    "home_env": (r"%USERPROFILE%", "ok", "环境变量写法，可移植"),
}

TEXT_SUFFIXES = {".md", ".py", ".js", ".mjs", ".cjs", ".ts", ".json", ".yml", ".yaml",
                 ".txt", ".ps1", ".cmd", ".sh", ".toml", ".cfg", ".ini", ".html", ".css"}


# The scan and the sanitizer contain the identifiers they look for (as patterns and
# replacement rules). Scanning them would always fail, so they are excluded by name:
# they are detectors, not leaked content.
SELF_EXEMPT = {"tools/publish_scan.py", "tools/sanitize_paths.py"}


def tracked_text_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True)
    for raw in out.stdout.split(b"\x00"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "replace")
        path = ROOT / rel
        if rel in SELF_EXEMPT or path.suffix.lower() not in TEXT_SUFFIXES or not path.is_file():
            continue
        yield rel, path


def scan_tree():
    counts = {name: 0 for name in CATEGORIES}
    samples = {name: [] for name in CATEGORIES}
    for rel, path in tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for name, (pattern, _fate, _note) in CATEGORIES.items():
            hits = re.findall(pattern, text)
            if hits:
                counts[name] += len(hits)
                if len(samples[name]) < 5:
                    line = next((n for n, l in enumerate(text.splitlines(), 1) if re.search(pattern, l)), "?")
                    samples[name].append("%s:%s" % (rel, line))
    return counts, samples


def scan_history():
    """Count hits over every blob any commit ever contained (diff text is enough)."""
    counts = {}
    for name, (pattern, _fate, _note) in CATEGORIES.items():
        if _fate != "fatal":
            continue
        proc = subprocess.run(["git", "log", "--all", "-p", "--format=", "-U0"],
                              cwd=ROOT, capture_output=True)
        text = proc.stdout.decode("utf-8", "ignore")
        counts[name] = len(re.findall(pattern, text))
    return counts


def main(argv):
    verbose = "--verbose" in argv
    counts, samples = scan_tree()
    history = scan_history()
    fatal = [name for name, (pattern, fate, _note) in CATEGORIES.items()
             if fate == "fatal" and counts[name]]
    print("tree hits (tracked files)")
    for name, (pattern, fate, note) in CATEGORIES.items():
        mark = "FAIL" if fate == "fatal" and counts[name] else "ok  "
        print("  %s %-16s %4d  %s" % (mark, name, counts[name], note))
        if verbose and samples[name]:
            for line in samples[name]:
                print("        " + line)
    print("")
    print("history hits (all commits; needs filter-repo to clear)")
    for name, value in history.items():
        print("  %-16s %5d" % (name, value))
    print("")
    verdict = "clean" if not fatal else "NOT READY: " + ", ".join(fatal)
    print("verdict: " + verdict)
    return 0 if not fatal else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
