"""Image to structure: several readers, one arbiter (FR-I2, requirements §6).

A vision model alone is not evidence, and a single OCR engine fails on busy
layouts. So every reader proposes a structure, RDKit throws away anything that is
not a valid molecule, and agreement between independent readers is what buys
confidence. A single proposal is returned as a candidate, never as an answer.

The readers do not share a runtime. MolVec is a Java jar, OSRA is a native
binary, MolScribe wants torch plus an old albumentations, DECIMER pins
TensorFlow 2.15 / Keras 2. Each therefore lives in its own environment and is
called as a subprocess; this module only knows how to ask and how to weigh the
answers. That also keeps the drawing path fast: nothing here imports torch or
TensorFlow into the process that drives ChemDraw.
"""

import importlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORKER = os.path.join(HERE, "ocr_workers.py")
ROOT_ENV = os.environ.get("CHEM_DRAW_TOOL_ENGINES", "")


def _engine_root() -> str:
    if ROOT_ENV:
        return ROOT_ENV
    base = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(base, "chem-draw-tool", "engines") if base else ""


def _model_root() -> str:
    base = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(base, "chem-draw-tool", "models") if base else ""


def _first(*paths) -> str:
    for path in paths:
        if path and os.path.exists(path):
            return path
    return ""


def _timeout() -> int:
    try:
        return max(30, int(os.environ.get("CHEM_OCR_TIMEOUT", "600")))
    except ValueError:
        return 600


# Each spec answers two questions: can this engine run here, and if not, why.
# The "why" travels back to the caller -- an agent that is told "DECIMER: no
# interpreter at <path>" can act, one that is told "DECIMER: False" cannot.
def engine_specs() -> dict:
    engines = _engine_root()
    models = _model_root()
    java = shutil.which("java") or ""
    return {
        "molvec": {
            "kind": "java",
            "java": java,
            "jar": _first(os.path.join(engines, "molvec", "molvec.jar")),
            "needs": "a JDK and molvec-0.9.8-jar-with-dependencies.jar",
        },
        "molscribe": {
            "kind": "python",
            "python": _first(os.path.join(engines, "molscribe", "Scripts",
                                           "python.exe"),
                             os.path.join(engines, "molscribe", "bin", "python")),
            "model": _first(os.path.join(models, "swin_base_char_aux_1m.pth")),
            "needs": "its own venv plus the swin_base checkpoint",
        },
        "decimer": {
            "kind": "python",
            "python": _first(os.path.join(engines, "decimer", "Scripts",
                                           "python.exe"),
                             os.path.join(engines, "decimer", "bin", "python")),
            "needs": "its own venv with TensorFlow 2.15 / Keras 2",
        },
        "osra": {
            "kind": "exe",
            "exe": _first(os.path.join(engines, "osra", "osra.exe"),
                          shutil.which("osra") or ""),
            "needs": "the standalone OSRA binary",
        },
    }


def _probe_cache_path() -> str:
    root = _engine_root()
    return os.path.join(root, ".probe.json") if root else ""


def _read_cache() -> dict:
    path = _probe_cache_path()
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as stream:
            return json.load(stream)
    except Exception:
        return {}


def _write_cache(rows: dict) -> None:
    path = _probe_cache_path()
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as stream:
            json.dump(rows, stream, indent=2)
    except Exception:
        pass


def _importable(python: str, module: str, fresh: bool) -> tuple:
    """Ask the engine's own interpreter whether the module imports.

    A venv on disk proves nothing -- the first MolScribe install here had a venv,
    a checkpoint and a broken dependency. So the answer is measured, cached for a
    day (TensorFlow takes seconds to import), and refreshed on demand.
    """
    cache = _read_cache()
    row = cache.get(module) or {}
    age = time.time() - float(row.get("at") or 0)
    if not fresh and row and age < 86400:
        return bool(row.get("ok")), row.get("detail", "")
    argv = [python, "-c", "import %s" % module]
    try:
        done = subprocess.run(argv, capture_output=True, timeout=240)
        ok = done.returncode == 0
        detail = "" if ok else (done.stderr or b"").decode("utf-8", "replace").strip().splitlines()[-1:]
        detail = detail[0][:160] if detail else ""
    except Exception as exc:
        ok = False
        detail = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    cache[module] = {"ok": ok, "at": time.time(), "detail": detail}
    _write_cache(cache)
    return ok, detail


MOLSCRIBE_CAPABILITY = """
import inspect
from molscribe import MolScribe  # noqa: F401
try:
    from onmt.modules import MultiHeadedAttention as M
except Exception as exc:
    print("no-onmt:", exc)
    raise SystemExit(0)
ok = "layer_cache" in inspect.signature(M.forward).parameters
print("capable" if ok else "onmt-too-new")
"""


def _molscribe_capable(python: str, fresh: bool) -> tuple:
    """Importing is not enough: MolScribe calls an attention API that onmt 3.x
    removed. Asking for the specific capability is cheaper and more honest than
    loading a 1.1 GB checkpoint and watching it fail."""
    cache = _read_cache()
    row = cache.get("molscribe-capability") or {}
    age = time.time() - float(row.get("at") or 0)
    if not fresh and row and age < 86400:
        return bool(row.get("ok")), row.get("detail", "")
    try:
        done = subprocess.run([python, "-c", MOLSCRIBE_CAPABILITY],
                              capture_output=True, timeout=240)
        text = (done.stdout or b"").decode("utf-8", "replace").strip()
        ok = text.endswith("capable")
        detail = "" if ok else (text or (done.stderr or b"").decode(
            "utf-8", "replace").strip().splitlines()[-1:][0][:120])
    except Exception as exc:
        ok = False
        detail = "%s: %s" % (type(exc).__name__, str(exc)[:120])
    cache["molscribe-capability"] = {"ok": ok, "at": time.time(),
                                     "detail": detail}
    _write_cache(cache)
    return ok, detail


def engine_reports(specs=None) -> dict:
    """Every engine with a verdict and, when unusable, the missing piece."""
    specs = engine_specs() if specs is None else specs
    report = {}
    for name, spec in specs.items():
        kind = spec["kind"]
        if kind == "java":
            if not spec["java"]:
                report[name] = {"available": False, "reason": "no java on PATH",
                                "needs": spec["needs"]}
            elif not spec["jar"]:
                report[name] = {"available": False,
                                "reason": "molvec.jar not found",
                                "needs": spec["needs"]}
            else:
                report[name] = {"available": True, "reason": "jar + java",
                                "path": spec["jar"]}
        elif kind == "python":
            if not spec["python"]:
                report[name] = {"available": False,
                                "reason": "no interpreter for this engine",
                                "needs": spec["needs"]}
            elif name == "molscribe" and not spec.get("model"):
                report[name] = {"available": False,
                                "reason": "checkpoint missing",
                                "needs": spec["needs"]}
            else:
                module = "molscribe" if name == "molscribe" else "DECIMER"
                fresh = os.environ.get("CHEM_OCR_REFRESH") == "1"
                ok, detail = _importable(spec["python"], module, fresh)
                broken = ""
                if ok and name == "molscribe":
                    ok, detail = _molscribe_capable(spec["python"], fresh)
                    if not ok:
                        broken = "needs the OpenNMT-py 2.x attention API"
                if ok:
                    report[name] = {"available": True,
                                    "reason": "interpreter imports " + module,
                                    "path": spec["python"]}
                else:
                    report[name] = {"available": False,
                                    "reason": broken or (
                                        "%s does not import: %s" % (
                                            module,
                                            detail or "unknown error")),
                                    "needs": spec["needs"]}
        else:
            if spec["exe"]:
                report[name] = {"available": True, "reason": "binary found",
                                "path": spec["exe"]}
            else:
                report[name] = {"available": False, "reason": "binary not found",
                                "needs": spec["needs"]}
    return report


def engines_available() -> dict:
    """Which readers can run right now (kept for callers from v2.0)."""
    return {name: row["available"] for name, row in engine_reports().items()}


def _engine_env(name: str) -> dict:
    """Engine-specific environment: DECIMER looks for weights under pystow."""
    if name != "decimer":
        return {}
    home = os.environ.get("CHEM_OCR_PYSTOW", "")
    if not home:
        root = _model_root()
        home = os.path.join(root, "decimer", "pystow") if root else ""
    return {"PYSTOW_HOME": home} if home else {}


def _run_json(argv, cwd="", env=None) -> dict:
    """Call an engine and read the single JSON line it prints."""
    merged = dict(os.environ)
    merged.update(env or {})
    completed = subprocess.run(argv, cwd=cwd or None, env=merged,
                               capture_output=True, timeout=_timeout())
    text = (completed.stdout or b"").decode("utf-8", "replace").strip()
    line = text.splitlines()[-1] if text else ""
    if not line:
        error = (completed.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(error[-300:] or "engine wrote nothing")
    payload = json.loads(line)
    if not payload.get("ok", True):
        raise RuntimeError(payload.get("error", "engine failed"))
    return payload


def _mol_from_text(text: str, suffix: str) -> list:
    """Turn a molfile/SMILES blob into canonical SMILES via RDKit."""
    from rdkit import Chem, RDLogger
    RDLogger.DisableLog("rdApp.*")
    # Never strip a molfile: its first line is the (empty) title, and trimming it
    # shifts the counts line up by one, which makes RDKit read the header as atoms.
    blob = text or ""
    if not blob.strip():
        return []
    mol = None
    if suffix == ".mol" or "V2000" in blob or "V3000" in blob:
        mol = Chem.MolFromMolBlock(blob, sanitize=False)
        if mol is not None:
            try:
                Chem.SanitizeMol(mol)
            except Exception:
                mol = None
    if mol is None:
        mol = Chem.MolFromSmiles(blob.strip())
    if mol is None:
        return []
    return [Chem.MolToSmiles(mol)]


def _run_molvec(path: str, spec: dict) -> list:
    folder = tempfile.mkdtemp(prefix="molvec-")
    out = os.path.join(folder, "out.mol")
    completed = subprocess.run([spec["java"], "-jar", spec["jar"],
                                "-f", path, "-o", out],
                               capture_output=True, timeout=_timeout())
    if not os.path.exists(out):
        error = (completed.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(error[-300:] or "molvec wrote no molfile")
    with open(out, encoding="utf-8", errors="replace") as stream:
        return _mol_from_text(stream.read(), ".mol")


def _run_python_engine(path: str, spec: dict, name: str) -> list:
    argv = [spec["python"], WORKER, "--engine", name, "--image", path]
    if spec.get("model"):
        argv += ["--model", spec["model"]]
    payload = _run_json(argv, cwd=os.path.dirname(spec["python"]),
                        env=_engine_env(name))
    rows = payload.get("results") or [payload]
    found = []
    for row in rows:
        if row.get("ok") is False:
            raise RuntimeError(row.get("error", "engine failed"))
        found.extend(_mol_from_text(row.get("smiles", ""), ".smi"))
    return found


def read_batch(paths, engines, specs=None) -> dict:
    """One model load per engine, then every image: the cheap way to scan a set."""
    import time
    specs = engine_specs() if specs is None else specs
    reports = engine_reports(specs)
    answers = {name: {} for name in engines}
    timings = {}
    notes = []
    for name in engines:
        row = reports.get(name) or {}
        if not row.get("available"):
            notes.append("%s unavailable: %s" % (name, row.get("reason")))
            continue
        started = time.perf_counter()
        try:
            if name in ("molscribe", "decimer"):
                argv = [specs[name]["python"], WORKER, "--engine", name]
                for path in paths:
                    argv += ["--image", path]
                if specs[name].get("model"):
                    argv += ["--model", specs[name]["model"]]
                payload = _run_json(argv, cwd=os.path.dirname(
                    specs[name]["python"]), env=_engine_env(name))
                for row in payload.get("results") or []:
                    image = os.path.basename(row.get("image", ""))
                    answers[name][image] = _mol_from_text(
                        row.get("smiles", ""), ".smi") if row.get("ok") else []
                    if row.get("ok") is False:
                        notes.append("%s could not read %s: %s" % (
                            name, image, str(row.get("error"))[:80]))
            else:
                runner = (DEFAULT_RUNNERS().get(name))
                if runner is None:
                    notes.append("%s has no runner" % name)
                    continue
                for path in paths:
                    image = os.path.basename(path)
                    try:
                        answers[name][image] = runner(path)
                    except Exception as exc:
                        answers[name][image] = []
                        notes.append("%s could not read %s: %s" % (
                            name, image, str(exc)[:80]))
        except Exception as exc:
            notes.append("%s failed: %s" % (name, str(exc)[:120]))
        timings[name] = round((time.perf_counter() - started) * 1000, 1)
    return {"answers": answers, "engine_ms": timings, "notes": notes,
            "engines": reports}


def _run_osra(path: str, spec: dict) -> list:
    completed = subprocess.run([spec["exe"], "--format", "smi", path],
                               capture_output=True, timeout=_timeout())
    text = (completed.stdout or b"").decode("utf-8", "replace")
    return _mol_from_text(text, ".smi")


def DEFAULT_RUNNERS():
    """Built lazily: a runner closes over the spec it was probed from."""
    specs = engine_specs()
    reports = engine_reports(specs)
    runners = {}
    if reports["molvec"]["available"]:
        runners["molvec"] = lambda path: _run_molvec(path, specs["molvec"])
    if reports["molscribe"]["available"]:
        runners["molscribe"] = (lambda path:
                                _run_python_engine(path, specs["molscribe"],
                                                   "molscribe"))
    if reports["decimer"]["available"]:
        runners["decimer"] = (lambda path:
                              _run_python_engine(path, specs["decimer"],
                                                 "decimer"))
    if reports["osra"]["available"]:
        runners["osra"] = lambda path: _run_osra(path, specs["osra"])
    return runners


def _prepare(image_path: str, out_dir: str) -> str:
    """Grayscale, stretched, upscaled: cheap and it helps every reader."""
    from PIL import Image, ImageOps
    os.makedirs(out_dir, exist_ok=True)
    with Image.open(image_path) as page:
        grey = page.convert("L")
        grey = ImageOps.autocontrast(grey)
        if grey.width < 1000:
            factor = 1000.0 / max(1, grey.width)
            grey = grey.resize((int(grey.width * factor),
                                int(grey.height * factor)), Image.LANCZOS)
        target = os.path.join(out_dir,
                              "prepared-%d.png" % int(os.path.getmtime(image_path)))
        grey.save(target, "PNG")
    return target


def _canonical(smiles: str) -> dict:
    from rdkit import Chem, RDLogger
    from rdkit.Chem import rdMolDescriptors
    RDLogger.DisableLog("rdApp.*")
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        return {}
    return {"smiles": Chem.MolToSmiles(mol),
            "inchikey": Chem.MolToInchiKey(mol),
            "formula": rdMolDescriptors.CalcMolFormula(mol)}


def vote(proposals, min_votes: int = 2) -> dict:
    """Group proposals by InChIKey and rank them by how many readers agree."""
    groups = {}
    rejected = []
    readers = []
    for proposal in proposals:
        smiles = (proposal or {}).get("smiles", "")
        source = (proposal or {}).get("source", "?")
        verified = _canonical(smiles)
        if not verified:
            rejected.append({"source": source, "smiles": smiles,
                             "reason": "RDKit could not read it"})
            readers.append({"source": source, "smiles": smiles,
                            "inchikey": "", "agrees": None,
                            "why": "RDKit could not read it"})
            continue
        readers.append({"source": source, "smiles": verified["smiles"],
                        "inchikey": verified["inchikey"], "agrees": None,
                        "why": ""})
        key = verified["inchikey"]
        entry = groups.setdefault(key, {
            "inchikey": key, "smiles": verified["smiles"],
            "formula": verified["formula"], "votes": 0, "sources": []})
        if source not in entry["sources"]:
            entry["sources"].append(source)
            entry["votes"] += 1
    ranked = sorted(groups.values(), key=lambda row: -row["votes"])
    best = ranked[0] if ranked else None
    if best:
        best = dict(best)
        best["confidence"] = ("high" if best["votes"] >= max(2, min_votes)
                              else "medium" if best["votes"] >= 1 else "low")
    # Which reader said what, and who broke ranks. When two engines disagree,
    # the agent needs the split, not just the winner: a wrong bond order from one
    # reader is invisible in a single "confidence: medium".
    best_key = best["inchikey"] if best else ""
    for row in readers:
        if row["inchikey"]:
            row["agrees"] = row["inchikey"] == best_key
    differing = [row for row in readers if row["agrees"] is False]
    return {"candidates": ranked, "best": best, "rejected": rejected,
            "readers": readers, "differing": differing,
            "needs_confirmation": not best or best["votes"] < max(2, min_votes)}


def read_image(image_path: str, llm_hint: str = "", engines=None,
               runners=None, out_dir: str = "", available=None) -> dict:
    """Read a picture with every available reader, then arbitrate."""
    import time
    runners = dict(DEFAULT_RUNNERS() if runners is None else runners)
    reports = engine_reports() if available is None else dict(available)
    wanted = list(runners) if engines is None else list(engines)
    proposals = []
    notes = []
    timings = {}
    prepared = ""
    if out_dir and os.path.exists(image_path):
        try:
            prepared = _prepare(image_path, out_dir)
        except Exception as exc:
            notes.append("preprocessing failed: %s" % str(exc)[:80])
    for name in wanted:
        row = reports.get(name)
        if isinstance(row, bool):
            row = {"available": row, "reason": "not installed"}
        row = row or {}
        if not row.get("available"):
            reason = row.get("reason") or "not installed"
            notes.append("%s unavailable: %s" % (name, reason))
            continue
        runner = runners.get(name)
        if runner is None:
            notes.append("%s has no runner wired up" % name)
            continue
        started = time.perf_counter()
        try:
            for smiles in runner(prepared or image_path) or []:
                proposals.append({"smiles": smiles, "source": name})
        except subprocess.TimeoutExpired:
            notes.append("%s timed out after %ds" % (name, _timeout()))
        except Exception as exc:
            notes.append("%s failed: %s" % (name, str(exc)[:120]))
        timings[name] = round((time.perf_counter() - started) * 1000, 1)
    if llm_hint:
        proposals.append({"smiles": llm_hint, "source": "llm"})
    result = vote(proposals)
    result["proposals"] = proposals
    # read_image keeps readers/differing from vote(); nothing to add here.
    result["prepared_image"] = prepared
    result["engines"] = reports
    result["engine_ms"] = timings
    result["notes"] = notes
    return result
