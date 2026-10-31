"""Replace machine-specific identifiers with portable placeholders.

Rewrites only tracked text files, longest pattern first, and reports a per-rule
count so the diff stays auditable. Run tools/publish_scan.py afterwards: the tree
counts must reach zero before a public push.

    python tools/sanitize_paths.py --dry-run
    python tools/sanitize_paths.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TEXT_SUFFIXES = {".md", ".py", ".js", ".mjs", ".cjs", ".ts", ".json", ".yml", ".yaml",
                 ".txt", ".ps1", ".cmd", ".sh", ".toml", ".cfg", ".ini", ".html", ".css"}

# Order matters: the longest, most specific forms first.
RULES = [
    (r"C:\Users\hyzs_zyh\AppData\Local\Programs\Python\Python311\python.exe",
     "%LOCALAPPDATA%\\Programs\\Python\\Python311\\python.exe"),
    (r"C:\Users\hyzs_zyh\.dsh\plugins\dsh-chem-draw",
     r"%USERPROFILE%\.dsh\plugins\dsh-chem"),
    (r"C:\Users\hyzs_zyh\.dsh\plugins\dsh-chem",
     r"%USERPROFILE%\.dsh\plugins\dsh-chem"),
    (r"C:\Users\hyzs_zyh", "<user-home>"),
    (r"C:/Users/hyzs_zyh", "<user-home>"),
    (r"C:\Temp\cdprobe", r"%TEMP%\cdprobe"),
    (r"D:\成果存放—学术\chem-draw-tool", "<repo>"),
    (r"D:/成果存放—学术/chem-draw-tool", "<repo>"),
    (r"/d/成果存放—学术/chem-draw-tool", "$REPO"),
    (r"D:\成果存放—学术", "<workdir>"),
    (r"D:/成果存放—学术", "<workdir>"),
    (r"成果存放—学术", "<workdir>"),
    (r"C:\Users\<user-home>", "<user-home>"),
    (r"hyzs_zyh", "<user>"),
]

# Files whose hardcoded ROOT assignment should become a computed one instead of a
# placeholder, so the script still runs anywhere.
COMPUTED_ROOT = {
    "test/e2e_cd_ascii.py",
    "test/e2e_cd_open.py",
    "test/e2e_cd_reopen.py",
    "test/e2e_visual_check.py",
}


def tracked_text_files():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True)
    for raw in out.stdout.split(b"\x00"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "replace")
        path = ROOT / rel
        if path.suffix.lower() in TEXT_SUFFIXES and path.is_file():
            yield rel, path


def main(argv):
    dry = "--dry-run" in argv
    totals = {pattern: 0 for pattern, _ in RULES}
    touched = []
    for rel, path in tracked_text_files():
        original = path.read_text(encoding="utf-8", errors="surrogateescape")
        text = original
        for pattern, replacement in RULES:
            if pattern not in text:
                continue
            totals[pattern] += text.count(pattern)
            text = text.replace(pattern, replacement)
        if rel in COMPUTED_ROOT:
            for form in ("ROOT = r'<repo>'", "ROOT = '<repo>'", 'ROOT = r"<repo>"', 'ROOT = "<repo>"'):
                if form in text:
                    text = text.replace(form, "ROOT = str(Path(__file__).resolve().parent.parent)")
                    if "from pathlib import Path" not in text:
                        lines = text.splitlines()
                        insert_at = 1 if lines and lines[0].startswith("#!") else 0
                        lines.insert(insert_at, "from pathlib import Path")
                        text = "\n".join(lines) + "\n"
                    break
        if text == original:
            continue
        touched.append(rel)
        if not dry:
            path.write_text(text, encoding="utf-8", errors="surrogateescape")
    print("rules:")
    for pattern, replacement in RULES:
        if totals[pattern]:
            print("  %5d  %-58s -> %s" % (totals[pattern], pattern[:58], replacement))
    print("files touched: %d" % len(touched))
    for rel in touched:
        print("  " + rel)
    if dry:
        print("(dry run, nothing written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
