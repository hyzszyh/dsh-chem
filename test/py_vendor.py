r"""Assertions for chem_vendor: CDXML round trip is real; cdx is honest about vendor."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "core"))

from chem import vendor  # noqa: E402

results = []
TMP = Path(tempfile.mkdtemp(prefix="dsh-chem-vendor-"))
ETH = "LFQSCWFLJHTTHZ-UHFFFAOYSA-N"
ACID = "QTBSBXVTEAMEQO-UHFFFAOYSA-N"


def check(label, ok, detail=""):
    results.append((label, bool(ok), detail))


target = TMP / "pair.cdxml"
written = vendor.handle({"action": "write", "smiles": "CCO,CC(=O)O", "out": str(target)})
check("write cdxml ok", written["ok"] is True, str(written.get("failure")))
check("write verified by reread", written["data"]["reread"] == 2, str(written["data"].get("reread")))
check("reread inchikeys match", written["data"]["rereadInchikeys"] == [ETH, ACID],
      str(written["data"]["rereadInchikeys"]))
check("cdxml has no phantom atoms", written["data"]["count"] == 2, str(written["data"]["count"]))

read = vendor.handle({"action": "read", "path": str(target)})
check("read cdxml ok", read["ok"] is True, str(read.get("failure")))
check("read count 2", read["data"]["count"] == 2, str(read["data"]["count"]))
check("read format detected", read["data"]["format"] == "cdxml", str(read["data"]["format"]))
check("read first record ethanol", read["data"]["records"][0]["inchikey"] == ETH,
      str(read["data"]["records"][0]))

info = vendor.handle({"action": "info", "path": str(target)})
check("info records", info["data"]["records"] == 2, str(info["data"]["records"]))
check("info needsVendor false for cdxml", info["data"]["needsVendor"] is False)

split_dir = TMP / "parts"
split = vendor.handle({"action": "split", "path": str(target), "outDir": str(split_dir)})
check("split ok", split["ok"] is True, str(split.get("failure")))
check("split 2 parts", split["data"]["parts"] == 2, str(split["data"]["parts"]))
one = vendor.handle({"action": "read", "path": split["data"]["files"][0]})
check("split part readable", one["data"]["count"] == 1, str(one["data"]["count"]))

merged = vendor.handle({"action": "merge", "paths": split["data"]["files"], "out": str(TMP / "merged.cdxml")})
check("merge ok", merged["ok"] is True, str(merged.get("failure")))
check("merge keeps 2", merged["data"]["reread"] == 2, str(merged["data"].get("reread")))
check("merge reports sources", merged["data"]["mergedFrom"] == 2, str(merged["data"].get("mergedFrom")))

sdf_out = TMP / "pair.sdf"
sdf = vendor.handle({"action": "write", "smiles": "CCO,CC(=O)O", "out": str(sdf_out)})
check("write sdf ok", sdf["ok"] is True, str(sdf.get("failure")))
sdf_read = vendor.handle({"action": "read", "path": str(sdf_out)})
check("read sdf 2 records", sdf_read["data"]["count"] == 2, str(sdf_read["data"].get("count")))

fake_cdx = TMP / "fake.cdx"
fake_cdx.write_bytes(b"VjCD0100" + b"\x00" * 64)
cdx_read = vendor.handle({"action": "read", "path": str(fake_cdx)})
check("binary cdx fails honestly", cdx_read["ok"] is False,
      str(cdx_read.get("failure", {}).get("code")))
check("cdx failure names the format", cdx_read["failure"]["format"] == "cdx",
      str(cdx_read.get("failure", {}).get("format")))

check("missing file rejected", vendor.handle({"action": "info", "path": "D:/nope/x.cdxml"})["ok"] is False)
bad = vendor.handle({"action": "write", "smiles": "CCO", "out": str(TMP / "x.xyz")})
check("bad write format rejected", bad["ok"] is False and bad["failure"]["code"] == "bad-format",
      str(bad.get("failure", {}).get("code")))
check("eps without out rejected", vendor.handle({"action": "eps"})["ok"] is False)
check("unknown action rejected", vendor.handle({"action": "wat"})["ok"] is False)

# The public surface of chem_vendor is do/path, not action/out. Every call used to
# fall through to action=info and answer 'no-such-file' on a path it was never given,
# so the whole channel looked like 'ChemDraw 不可用' while COM worked fine. These
# assertions exercise the names the tool actually receives.
public_out = TMP / "public.cdxml"
public_write = vendor.handle({"do": "cdxml-write", "smiles": "CCO", "path": str(public_out)})
check("do=cdxml-write writes through path", public_write["ok"] is True, str(public_write.get("failure")))
check("do=cdxml-write produced the file", public_out.is_file(), str(public_out))
public_read = vendor.handle({"do": "cdx-read", "path": str(public_out)})
check("do=cdx-read reads it back", public_read["ok"] is True and public_read["data"]["count"] == 1,
      str(public_read.get("failure")))

probe = vendor.handle({"do": "probe"})
check("do=probe reports a channel", probe["ok"] is True and "chemdraw" in probe["data"],
      str(probe.get("failure")))
check("probe names a progid or says why not",
      probe["data"]["chemdraw"]["dispatch"] is True or bool(probe["data"]["chemdraw"].get("note")),
      str(probe["data"]["chemdraw"].get("progid")))
check("probe maps six formats", len(probe["data"]["formats"]) == 6,
      str(probe["data"]["formats"]))

eps_out = TMP / "public.eps"
eps = vendor.handle({"do": "eps", "smiles": "CCO", "path": str(eps_out)})
check("do=eps either writes or says needs-vendor",
      (eps["ok"] and eps_out.is_file())
      or eps.get("failure", {}).get("code") in ("needs-vendor", "vendor-export-failed"),
      str(eps.get("failure", {}).get("code")) + " ok=" + str(eps.get("ok")))

cdx_out = TMP / "public.cdx"
cdx_write = vendor.handle({"do": "cdx-write", "smiles": "CCO", "path": str(cdx_out)})
check("do=cdx-write fails with a measured reason, not silently",
      cdx_write["ok"] is False
      and cdx_write.get("failure", {}).get("code") in ("needs-vendor", "vendor-save-failed"),
      str(cdx_write.get("failure", {}).get("code")))

failed = 0
for label, ok, detail in results:
    if not ok:
        failed += 1
    print(("PASS  " if ok else "FAIL  ") + label + (("  [" + detail + "]") if detail else ""))
print("")
print("chem_vendor: %d/%d PASS" % (len(results) - failed, len(results)))
raise SystemExit(0 if failed == 0 else 1)
