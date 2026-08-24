#!/usr/bin/env python3
"""Build the GitHub Pages demo from the exact sample workbook used by Streamlit.

This keeps one synthetic dataset as the source of truth for both demos.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from sample_workbook import build_sample_workbook


ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "scripts" / "cafe_qc_web_engine.py"
DOCS = ROOT / "docs"


def run_engine(workbook: Path, command: str, *, region: str | None = None, n: int | None = None, per_store_n: int | None = None) -> dict:
    args = [sys.executable, str(ENGINE), command, "--file", str(workbook)]
    if region:
        args += ["--region", region]
    if n is not None:
        args += ["--n", str(n)]
    if per_store_n is not None:
        args += ["--per-store-n", str(per_store_n)]

    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse {command} output: {proc.stdout}\n{proc.stderr}") from exc
    if proc.returncode != 0 or "error" in payload:
        raise RuntimeError(payload.get("error") or proc.stderr or f"{command} failed")
    return payload


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    workbook_bytes = build_sample_workbook()

    # Commit the exact workbook used to generate the static preview so anyone
    # can download it and upload it into the Streamlit app for the same result.
    sample_path = DOCS / "sample-qc-workbook.xlsx"
    sample_path.write_bytes(workbook_bytes)

    with tempfile.NamedTemporaryFile(suffix=".xlsx") as tmp:
        tmp.write(workbook_bytes)
        tmp.flush()
        workbook = Path(tmp.name)

        data = {
            "dashboard": run_engine(workbook, "dashboard"),
            "best": {
                "region_a": run_engine(workbook, "best", region="region_a", n=6),
                "region_b": run_engine(workbook, "best", region="region_b", n=5),
            },
            "worst": {
                "region_a": run_engine(workbook, "worst", region="region_a", n=5),
                "region_b": run_engine(workbook, "worst", region="region_b", n=5),
            },
            "worst_skus": {
                "region_a": run_engine(workbook, "worst-skus", region="region_a", per_store_n=5),
                "region_b": run_engine(workbook, "worst-skus", region="region_b", per_store_n=5),
            },
            "action_points": {
                "region_a": run_engine(workbook, "action-points", region="region_a", n=5),
                "region_b": run_engine(workbook, "action-points", region="region_b", n=5),
            },
        }

    js = "window.DEMO_DATA = " + json.dumps(data, separators=(",", ":"), default=str) + ";\n"
    (DOCS / "demo-data.js").write_text(js, encoding="utf-8")
    print("Wrote docs/demo-data.js and docs/sample-qc-workbook.xlsx")


if __name__ == "__main__":
    main()
