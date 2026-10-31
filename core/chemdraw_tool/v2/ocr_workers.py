"""Run one reader inside the interpreter that can actually run it.

MolScribe and DECIMER each need their own dependency tree (one wants torch plus
albumentations 1.4, the other pins TensorFlow 2.15 / Keras 2). Rather than poison
the main interpreter, each engine gets a venv and this worker is executed by that
venv: the CLI stays on one Python, the engines do not.

Protocol: argv in, one JSON line on stdout, nothing else on stdout. One image or
many -- a batch loads the model once, which is the difference between 3 s and
40 s per picture. Usage:

    <engine python> ocr_workers.py --engine molscribe --image a.png --image b.png
"""

import argparse
import json
import sys


def _bridge_molscribe_onmt() -> bool:
    """MolScribe was written against OpenNMT-py 2.x.

    That version's MultiHeadedAttention took `layer_cache` and `step` for
    stepwise decoding. 3.x dropped both and always recomputes the attention over
    the whole sequence: correct, only slower. So the two keywords are dropped
    here instead of pinning a two-year-old tokenizer stack that no longer
    installs on this Python.
    """
    try:
        from onmt.modules import MultiHeadedAttention
    except Exception:
        return False
    if getattr(MultiHeadedAttention.forward, "_chem_shim", False):
        return True
    import inspect
    original = MultiHeadedAttention.forward
    allowed = set(inspect.signature(original).parameters)

    def forward(*args, **kwargs):
        # Filter rather than blacklist: 2.x passed layer_cache, step, attn_type;
        # a future version may pass something else again.
        accepted = {key: value for key, value in kwargs.items()
                    if key in allowed}
        return original(*args, **accepted)

    forward._chem_shim = True
    MultiHeadedAttention.forward = forward
    return True


def load_molscribe(model_path: str, device: str):
    import torch
    from molscribe import MolScribe
    _bridge_molscribe_onmt()
    return MolScribe(model_path, device=torch.device(device))


def molscribe_one(net, image: str) -> dict:
    answer = net.predict_image_file(image, return_confidence=True) or {}
    return {"smiles": answer.get("smiles") or "",
            "confidence": answer.get("confidence"),
            "molfile": answer.get("molfile") or ""}


def decimer_one(image: str) -> dict:
    from DECIMER import predict_SMILES
    return {"smiles": predict_SMILES(image) or ""}


def main() -> int:
    parser = argparse.ArgumentParser(description="single-engine OCR worker")
    parser.add_argument("--engine", required=True,
                        choices=["molscribe", "decimer"])
    parser.add_argument("--image", action="append", default=[])
    parser.add_argument("--model", default="")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    if not args.image:
        sys.stdout.write(json.dumps({"ok": False, "error": "no image"}) + "\n")
        return 2
    results = []
    try:
        net = None
        if args.engine == "molscribe":
            net = load_molscribe(args.model, args.device)
        for image in args.image:
            try:
                payload = (molscribe_one(net, image) if net
                           else decimer_one(image))
                payload["image"] = image
                payload["ok"] = True
            except Exception as exc:
                payload = {"ok": False, "image": image,
                           "error": "%s: %s" % (type(exc).__name__, exc)}
            results.append(payload)
    except Exception as exc:
        sys.stdout.write(json.dumps({"ok": False, "error": "%s: %s" % (
            type(exc).__name__, exc)}) + "\n")
        return 1
    sys.stdout.write(json.dumps({"ok": True, "results": results}) + "\n")
    return 0


if __name__ == '__main__':
    sys.exit(main())
