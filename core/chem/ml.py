"""chem_ml: small, honest QSAR.

Training data stays on this machine, the model is a plain sklearn pipeline saved
with joblib, and every number reported comes from cross-validation on the rows
that were actually usable -- not from the fit.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from . import mol as molmod

FEATURES = ["mw", "logp", "tpsa", "hbd", "hba", "rotb", "rings", "aromatic_rings",
            "heavy", "fraction_csp3", "molar_refractivity", "bertz", "balaban_j",
            "num_heteroatoms", "num_charges", "qed"]


def models_dir():
    local = os.environ.get("LOCALAPPDATA") or str(Path.home())
    path = Path(local) / "dsh-chem" / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def describe_molecule(m):
    from rdkit.Chem import Crippen, Descriptors, QED, rdMolDescriptors
    return [
        Descriptors.MolWt(m), Crippen.MolLogP(m), rdMolDescriptors.CalcTPSA(m),
        rdMolDescriptors.CalcNumHBD(m), rdMolDescriptors.CalcNumHBA(m),
        rdMolDescriptors.CalcNumRotatableBonds(m), rdMolDescriptors.CalcNumRings(m),
        rdMolDescriptors.CalcNumAromaticRings(m), m.GetNumHeavyAtoms(),
        rdMolDescriptors.CalcFractionCSP3(m), Crippen.MolMR(m),
        Descriptors.BertzCT(m), Descriptors.BalabanJ(m),
        rdMolDescriptors.CalcNumHeteroatoms(m),
        sum(abs(atom.GetFormalCharge()) for atom in m.GetAtoms()),
        QED.qed(m),
    ]


def _dataset(payload):
    """Return (smiles_list, labels, features, skipped)."""
    import csv
    import io
    text = payload.get("text") or ""
    path = payload.get("path") or ""
    if path:
        target = Path(path)
        if not target.is_file():
            raise molmod.MolError("no-such-file", "找不到训练数据：" + str(target))
        text = target.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise molmod.MolError("no-data", "没有训练数据（给 path 或 text）")
    smiles_column = payload.get("smilesColumn") or "smiles"
    label_column = payload.get("labelColumn") or "activity"
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames and smiles_column in reader.fieldnames:
        rows = list(reader)
    else:
        # Fall back to "smiles<TAB>value" per line.
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.replace("\t", " ").split()
            if len(parts) >= 2:
                rows.append({smiles_column: parts[0], label_column: parts[1]})
    smiles, labels, matrix, skipped = [], [], [], []
    for row in rows:
        raw = (row.get(smiles_column) or "").strip()
        value = (row.get(label_column) or "").strip()
        if not raw:
            continue
        try:
            numeric = float(value)
        except ValueError:
            skipped.append({"smiles": raw, "reason": "标签不是数字：" + value[:20]})
            continue
        try:
            m = molmod.parse_struct(raw)
        except molmod.MolError as exc:
            skipped.append({"smiles": raw, "reason": exc.message})
            continue
        smiles.append(molmod.canonical(m))
        labels.append(numeric)
        matrix.append(describe_molecule(m))
    if len(smiles) < 6:
        raise molmod.MolError("too-few-rows",
                              "可用数据只有 %d 行，交叉验证至少需要 6 行" % len(smiles),
                              "补数据，或用同一批分子的多个性质")
    return smiles, labels, matrix, skipped


def _make_model(kind, n_samples):
    from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    kind = (kind or "rf").strip().lower()
    if kind in ("pls", "plsregression"):
        from sklearn.cross_decomposition import PLSRegression
        estimator = PLSRegression(n_components=min(5, max(2, n_samples // 3)))
    elif kind == "rf":
        estimator = RandomForestRegressor(n_estimators=300, random_state=42, n_jobs=1)
    elif kind in ("gbr", "boost"):
        estimator = GradientBoostingRegressor(random_state=42)
    elif kind in ("linear", "ridge"):
        estimator = Ridge(alpha=1.0)
    else:
        raise molmod.MolError("bad-model", "不认识的 model：" + kind,
                              "pls | rf | gbr | linear")
    return Pipeline([("impute", SimpleImputer(strategy="median")),
                     ("scale", StandardScaler()),
                     ("model", estimator)]), kind


def _do_train(payload):
    import numpy as np
    from sklearn.model_selection import KFold, cross_val_predict

    smiles, labels, matrix, skipped = _dataset(payload)
    pipeline, kind = _make_model(payload.get("model"), len(smiles))
    X = np.asarray(matrix, dtype=float)
    y = np.asarray(labels, dtype=float)
    folds = int(payload.get("folds") or min(5, len(smiles)))
    splitter = KFold(n_splits=max(2, folds), shuffle=True, random_state=42)
    predicted = cross_val_predict(pipeline, X, y, cv=splitter)
    residual = y - predicted
    ss_res = float((residual ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    rmse = float(np.sqrt((residual ** 2).mean()))
    mae = float(np.abs(residual).mean())
    pipeline.fit(X, y)

    name = (payload.get("name") or ("qsar-" + time.strftime("%Y%m%d-%H%M%S"))).strip()
    safe_name = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in name)
    model_path = models_dir() / (safe_name + ".joblib")
    meta_path = models_dir() / (safe_name + ".json")
    import joblib
    joblib.dump(pipeline, str(model_path))

    from rdkit import DataStructs
    from rdkit.Chem import rdFingerprintGenerator
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=1024)
    train_fps = []
    for text in smiles[:2000]:
        fingerprint = generator.GetFingerprint(molmod.parse_struct(text))
        train_fps.append(DataStructs.BitVectToBinaryText(fingerprint).hex())

    meta = {"name": safe_name, "model": kind, "rows": len(smiles),
            "features": FEATURES, "folds": splitter.get_n_splits(),
            "metrics": {"r2": round(r2, 4), "rmse": round(rmse, 4), "mae": round(mae, 4)},
            "labelRange": [round(float(y.min()), 4), round(float(y.max()), 4)],
            "trainedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "trainInchikeys": [molmod.inchikey(molmod.parse_struct(t)) for t in smiles[:2000]],
            "trainFingerprints": train_fps,
            "skipped": skipped[:20]}
    meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "channel": "sklearn",
            "data": {"model": safe_name, "kind": kind, "rows": len(smiles),
                     "features": len(FEATURES), "cv": meta["metrics"],
                     "labelRange": meta["labelRange"],
                     "modelPath": str(model_path), "metaPath": str(meta_path),
                     "skipped": skipped[:20]},
            "warnings": (["%d 行数据被跳过" % len(skipped)] if skipped else [])
                        + (["交叉验证 R2 如为负，说明这批描述符解释不了这个标签，别拿去预测"]
                           if r2 < 0 else [])}


def _load(name):
    safe_name = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in str(name))
    model_path = models_dir() / (safe_name + ".joblib")
    meta_path = models_dir() / (safe_name + ".json")
    if not model_path.is_file():
        raise molmod.MolError("no-model", "没有这个模型：" + safe_name,
                              "先 train，或 list 看有哪些")
    import joblib
    pipeline = joblib.load(str(model_path))
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    return pipeline, meta, safe_name


def _do_predict(payload):
    import numpy as np
    from rdkit import DataStructs
    from rdkit.Chem import rdFingerprintGenerator

    pipeline, meta, name = _load(payload.get("model") or "")
    raw = payload.get("smiles") or payload.get("smilesList") or ""
    if isinstance(raw, list):
        items = [str(s) for s in raw]
    else:
        items = [s.strip() for s in str(raw).replace(",", "\n").splitlines() if s.strip()]
    if not items:
        return {"ok": False, "failure": {"code": "missing-input", "message": "需要 smiles 列表"}}

    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=1024)
    train = [DataStructs.CreateFromBinaryText(bytes.fromhex(h))
             for h in meta.get("trainFingerprints", [])]
    rows, skipped = [], []
    for text in items:
        try:
            m = molmod.parse_struct(text)
        except molmod.MolError as exc:
            skipped.append({"smiles": text, "error": exc.message})
            continue
        vector = np.asarray([describe_molecule(m)], dtype=float)
        value = float(np.ravel(pipeline.predict(vector))[0])
        nearest = 0.0
        if train:
            fingerprint = generator.GetFingerprint(m)
            nearest = max(DataStructs.TanimotoSimilarity(fingerprint, fp) for fp in train)
        rows.append({"smiles": molmod.canonical(m), "predicted": round(value, 4),
                     "nearestTrainingSimilarity": round(nearest, 4),
                     "insideApplicability": bool(nearest >= float(payload.get("cutoff") or 0.4))})
    outside = [r for r in rows if not r["insideApplicability"]]
    return {"ok": True, "channel": "sklearn",
            "data": {"model": name, "count": len(rows), "predictions": rows,
                     "skipped": skipped, "cv": meta.get("metrics"),
                     "outsideApplicability": len(outside)},
            "warnings": (["%d 个分子的结构与训练集差得远（Tanimoto < %.2f），预测只能当参考"
                          % (len(outside), float(payload.get("cutoff") or 0.4))] if outside else [])}


def handle(payload):
    action = (payload.get("action") or "train").strip().lower()
    if action == "train":
        try:
            return _do_train(payload)
        except molmod.MolError as exc:
            return {"ok": False, "failure": {"code": exc.code, "message": exc.message,
                                            "hint": exc.hint}}
    if action in ("predict", "score"):
        try:
            return _do_predict(payload)
        except molmod.MolError as exc:
            return {"ok": False, "failure": {"code": exc.code, "message": exc.message,
                                            "hint": exc.hint}}
    if action == "list":
        rows = []
        for meta_path in sorted(models_dir().glob("*.json")):
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            rows.append({"model": meta.get("name"), "kind": meta.get("model"),
                         "rows": meta.get("rows"), "cv": meta.get("metrics"),
                         "trainedAt": meta.get("trainedAt")})
        return {"ok": True, "channel": "sklearn", "data": {"dir": str(models_dir()), "models": rows}}
    if action == "describe":
        try:
            _, meta, name = _load(payload.get("model") or "")
        except molmod.MolError as exc:
            return {"ok": False, "failure": {"code": exc.code, "message": exc.message}}
        meta = dict(meta)
        meta.pop("trainFingerprints", None)
        return {"ok": True, "channel": "sklearn", "data": meta}
    return {"ok": False, "failure": {"code": "unknown-action", "message": "不认识的 action：" + action,
                                    "hint": "train | predict | list | describe"}}
