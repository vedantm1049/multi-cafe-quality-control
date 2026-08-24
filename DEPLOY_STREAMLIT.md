# Deploy the live QC app on Streamlit Community Cloud

The repository is ready for Streamlit Community Cloud.

## Deploy

1. Go to `share.streamlit.io` and sign in with GitHub.
2. Click **Create app**.
3. Choose **Yup, I have an app**.
4. Select:
   - **Repository:** `vedantm1049/multi-cafe-quality-control`
   - **Branch:** `main`
   - **Main file path:** `streamlit_app.py`
5. Choose an available app URL, for example `multi-chain-quality-control`.
6. Click **Deploy**.

Streamlit will read `requirements.txt` from the repository root and install the required Python packages.

## What the live app supports

- Upload an 8-sheet `.xlsx` QC workbook.
- Validate all sheets and required columns before analysis.
- Show unmatched identifiers instead of silently guessing.
- Switch between Region A and Region B.
- View network KPIs and store-level QC risk.
- Rank stores needing attention.
- Rank best-performing stores.
- Prioritize store × defect action points.
- Show worst SKUs by store.
- Show weekly refund and rating trends.
- Download store rankings, action points and SKU analysis as CSV.
- Run the entire workflow with a built-in synthetic workbook using **Use sample workbook**.
- Download the same synthetic workbook to inspect the expected input format.

## Local run

If you ever want to run the app locally:

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## After deployment

Copy the final `https://<your-name>.streamlit.app/` URL and replace the README's current static-demo emphasis with a prominent **Try the Live App** link.

Keep the GitHub Pages demo as a static preview or fallback.
