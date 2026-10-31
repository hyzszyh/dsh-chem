"""Tool dispatch: chem_<name> -> handler(payload) -> envelope.

A handler returns {"ok": True, ...} or {"ok": False, "failure": {...}}; it
never raises to the caller and never prints. bin/chem.py turns the result into
the single JSON line the plugin parses.
"""

from __future__ import annotations

from . import (calc, clean, compare, db, draw, enum, exam, ml, office, parse, props,
               retro, spectra, table, vendor)

HANDLERS = {
    "props": props.handle,
    "clean": clean.handle,
    "calc": calc.handle,
    "compare": compare.handle,
    "table": table.handle,
    "draw": draw.handle,
    "parse": parse.handle,
    "enum": enum.handle,
    "db": db.handle,
    "ml": ml.handle,
    "vendor": vendor.handle,
    "office": office.handle,
    "exam": exam.handle,
    "spectra": spectra.handle,
    "retro": retro.handle,
}

# Declared but not yet implemented (W2..W7). Reported explicitly instead of
# pretending to succeed, so a half-built plugin cannot look finished.
PENDING = {}


def run_tool(name, payload):
    handler = HANDLERS.get(name)
    if handler is not None:
        return handler(payload or {})
    if name in PENDING:
        return {"ok": False, "stage": PENDING[name], "tool": "chem_" + name,
                "received": payload or {},
                "error": "tool not implemented yet: chem_" + name}
    return {"ok": False, "error": "unknown tool: " + name,
            "known": sorted(list(HANDLERS) + list(PENDING))}