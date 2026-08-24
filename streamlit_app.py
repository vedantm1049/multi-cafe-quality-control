from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from scripts.sample_workbook import build_sample_workbook


ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / "scripts" / "cafe_qc_engine.py"

st.set_page_config(
    page_title="Multi-Chain F&B Quality Control",
    page_icon="☕",
    layout="wide",
)


@st.cache_data(show_spinner=False)
def sample_workbook_bytes() -> bytes:
    return build_sample_workbook()


def persist_workbook(data: bytes) -> tuple[str, str]:
    digest = hashlib.sha256(data).hexdigest()
    path = Path(tempfile.gettempdir()) / f"cafe-qc-{digest}.xlsx"
    if not path.exists():
        path.write_bytes(data)
    return digest, str(path)


@st.cache_data(show_spinner=False)
def run_engine(file_hash: str, file_path: str, command: str, region: str | None = None, n: int | None = None) -> dict:
    del file_hash
    cmd = [sys.executable, str(ENGINE), command, "--file", file_path]
    if region:
        cmd.extend(["--region", region])
    if n is not None:
        if command == "worst-skus":
            cmd.extend(["--per-store-n", str(n)])
        else:
            cmd.extend(["--n", str(n)])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
    raw = result.stdout.strip()
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(result.stderr.strip() or "The QC engine returned an unreadable response.") from exc

    if result.returncode != 0 or "error" in payload:
        raise RuntimeError(payload.get("error") or result.stderr.strip() or "The QC engine could not process this workbook.")
    return payload


def display_region(region: str) -> str:
    return "Region A" if region == "region_a" else "Region B"


def dataframe_download(df: pd.DataFrame, filename: str, label: str) -> None:
    st.download_button(
        label,
        data=df.to_csv(index=False).encode("utf-8"),
        file_name=filename,
        mime="text/csv",
    )


def store_rows_df(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    keep = [
        "store_name",
        "composite_score",
        "refund_rate_pct",
        "avg_rating",
        "units_sold",
        "refund_events",
        "volume_tier",
    ]
    df = df[[c for c in keep if c in df.columns]].copy()
    return df.rename(columns={
        "store_name": "Store",
        "composite_score": "QC risk score",
        "refund_rate_pct": "Refund rate %",
        "avg_rating": "Avg rating",
        "units_sold": "Units sold",
        "refund_events": "Refund events",
        "volume_tier": "Volume tier",
    })


st.title("AI Quality Control for Multi-Chain F&B Operations")
st.markdown(
    "Turn ratings, refunds, complaints and sales records across a multi-location F&B network "
    "into ranked stores, root causes and actionable QC priorities."
)

st.subheader("Analyze a QC workbook")
left, right = st.columns([2, 1])

with left:
    uploaded = st.file_uploader(
        "Upload QC Workbook (.xlsx)",
        type=["xlsx"],
        help="Expected format: the 8-sheet QC workbook documented in the repository.",
    )

with right:
    st.markdown("**No workbook available?**")
    if st.button("Use sample workbook", type="primary"):
        st.session_state["use_sample_workbook"] = True
    sample_bytes = sample_workbook_bytes()
    st.download_button(
        "Download sample workbook",
        data=sample_bytes,
        file_name="sample-multi-chain-qc-workbook.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

if uploaded is not None:
    workbook_bytes = uploaded.getvalue()
    workbook_name = uploaded.name
    st.session_state["use_sample_workbook"] = False
elif st.session_state.get("use_sample_workbook"):
    workbook_bytes = sample_workbook_bytes()
    workbook_name = "Synthetic sample workbook"
else:
    workbook_bytes = None
    workbook_name = None

if workbook_bytes is None:
    st.info("Upload an Excel workbook or click **Use sample workbook** to run the live analysis.")
    st.stop()

file_hash, file_path = persist_workbook(workbook_bytes)

try:
    with st.spinner("Validating workbook…"):
        validation = run_engine(file_hash, file_path, "validate")
except Exception as exc:
    st.error(f"Workbook validation failed: {exc}")
    st.stop()

region_a_diag = validation["sheets"]["region_a"]
region_b_diag = validation["sheets"]["region_b"]
store_count = region_a_diag["mapping_store_count"] + region_b_diag["mapping_store_count"]
unmatched = sum(
    len(diag.get(key, []))
    for diag in (region_a_diag, region_b_diag)
    for key in ("refund_unmatched_store_names", "rating_unmatched_wh_codes", "sales_unmatched")
)

st.success(f"Workbook validated · 8/8 sheets · {store_count} mapped stores · {unmatched} unmatched identifiers")
st.caption(f"Source: {workbook_name}. Uploads are analyzed in the app runtime; this demo does not write them back to GitHub.")

region = st.selectbox("Region", ["region_a", "region_b"], format_func=display_region)

try:
    with st.spinner("Running QC analysis…"):
        dashboard = run_engine(file_hash, file_path, "dashboard")
        worst = run_engine(file_hash, file_path, "worst", region=region, n=10)
        best = run_engine(file_hash, file_path, "best", region=region, n=10)
        action_points = run_engine(file_hash, file_path, "action-points", region=region, n=15)
        worst_skus = run_engine(file_hash, file_path, "worst-skus", region=region, n=5)
        analysis = run_engine(file_hash, file_path, "analysis", region=region)
except Exception as exc:
    st.error(f"Analysis failed: {exc}")
    st.stop()

region_data = dashboard["regions"][region]
stores = region_data.get("stores", [])
units_sold = sum((s.get("units_sold") or 0) for s in stores)
refund_events = sum((s.get("refund_events") or 0) for s in stores)
rated_orders = sum((s.get("rated_orders") or 0) for s in stores)
weighted_rating_numerator = sum((s.get("avg_rating") or 0) * (s.get("rated_orders") or 0) for s in stores)
avg_rating = weighted_rating_numerator / rated_orders if rated_orders else 0
refund_rate = (refund_events / units_sold * 100) if units_sold else 0
complaints = region_data.get("tag_polarity_breakdown", {}).get("complaint", 0)

st.markdown(f"### {display_region(region)}")
metric_cols = st.columns(5)
metric_cols[0].metric("Stores", len(stores))
metric_cols[1].metric("Units sold", f"{units_sold:,.0f}")
metric_cols[2].metric("Refund rate", f"{refund_rate:.2f}%")
metric_cols[3].metric("Average rating", f"{avg_rating:.2f}")
metric_cols[4].metric("Complaint tags", f"{complaints:,}")

st.caption("QC risk score: lower is better; higher means greater combined refund/rating risk after the volume adjustment.")

overview_tab, fix_tab, action_tab, sku_tab, best_tab, trends_tab = st.tabs(
    ["Overview", "Stores to Fix", "Action Points", "Worst SKUs", "Best Stores", "Trends"]
)

with overview_tab:
    st.subheader("Network view")
    store_df = pd.DataFrame(stores)
    if not store_df.empty:
        cols = [c for c in ["store_name", "composite_score", "refund_rate_pct", "avg_rating", "units_sold", "volume_tier"] if c in store_df.columns]
        overview_df = store_df[cols].copy().rename(columns={
            "store_name": "Store",
            "composite_score": "QC risk score",
            "refund_rate_pct": "Refund rate %",
            "avg_rating": "Avg rating",
            "units_sold": "Units sold",
            "volume_tier": "Volume tier",
        })
        overview_df = overview_df.sort_values("QC risk score", ascending=False, na_position="last")
        st.dataframe(overview_df, hide_index=True, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Refund reasons**")
        reasons = pd.Series(region_data.get("refund_reason_breakdown", {}), name="Refund events")
        if not reasons.empty:
            st.bar_chart(reasons.sort_values(ascending=False))
    with c2:
        st.markdown("**Refund categories**")
        categories = pd.Series(region_data.get("category_breakdown", {}), name="Refund events")
        if not categories.empty:
            st.bar_chart(categories.sort_values(ascending=False))

with fix_tab:
    st.subheader("Stores needing attention")
    st.write("Ranked by the same deterministic QC engine used by the plugin.")
    worst_df = store_rows_df(worst.get("rows", []))
    if worst_df.empty:
        st.info("No stores could be ranked for this region.")
    else:
        st.dataframe(worst_df, hide_index=True, use_container_width=True)
        dataframe_download(worst_df, f"{region}-stores-to-fix.csv", "Download store ranking")

with action_tab:
    st.subheader("Prioritized root causes")
    action_df = pd.DataFrame(action_points.get("rows", []))
    if action_df.empty:
        st.info("No action points were generated for this region.")
    else:
        keep = ["store_name", "defect_type", "instance_count", "refund_rate_pct", "severity_avg_refund_amount", "impact_score", "confirmed_by_customer_feedback"]
        action_df = action_df[[c for c in keep if c in action_df.columns]].rename(columns={
            "store_name": "Store",
            "defect_type": "Defect",
            "instance_count": "Instances",
            "refund_rate_pct": "Refund rate %",
            "severity_avg_refund_amount": "Avg refund amount",
            "impact_score": "Impact score",
            "confirmed_by_customer_feedback": "Confirmed by customer feedback",
        })
        st.dataframe(action_df, hide_index=True, use_container_width=True)
        dataframe_download(action_df, f"{region}-action-points.csv", "Download action points")

with sku_tab:
    st.subheader("Worst SKUs by store")
    flat_rows = []
    for store in worst_skus.get("stores", []):
        for rank, sku in enumerate(store.get("top_skus", []), start=1):
            flat_rows.append({
                "Store": store.get("store_name"),
                "Rank": rank,
                "SKU": sku.get("sku"),
                "Product": sku.get("title"),
                "Refund events": sku.get("refund_count"),
                "Store refund events": store.get("total_refund_events"),
            })
    sku_df = pd.DataFrame(flat_rows)
    if sku_df.empty:
        st.info("No refunded SKUs were found for this region.")
    else:
        st.dataframe(sku_df, hide_index=True, use_container_width=True)
        dataframe_download(sku_df, f"{region}-worst-skus.csv", "Download SKU analysis")

with best_tab:
    st.subheader("Best-performing stores")
    best_df = store_rows_df(best.get("rows", []))
    if best_df.empty:
        st.info("No stores could be ranked for this region.")
    else:
        st.dataframe(best_df, hide_index=True, use_container_width=True)
        if best.get("sample_floor_applied"):
            st.caption("The best-store list applies the configured minimum sample floor for this region.")

with trends_tab:
    st.subheader("Weekly trends")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Refund events by week**")
        refund_weekly = pd.Series(analysis.get("refund_events_weekly", {}), name="Refund events")
        if not refund_weekly.empty:
            refund_weekly.index = pd.to_datetime(refund_weekly.index)
            st.line_chart(refund_weekly)
    with c2:
        st.markdown("**Average rating by week**")
        rating_weekly = pd.Series(analysis.get("avg_rating_weekly", {}), name="Average rating", dtype="float64")
        if not rating_weekly.empty:
            rating_weekly.index = pd.to_datetime(rating_weekly.index)
            st.line_chart(rating_weekly)

with st.expander("Validation details"):
    st.json(validation)

st.divider()
st.caption("Synthetic sample data is provided only to demonstrate the workflow. The scoring and analysis run through the repository's QC engine.")
