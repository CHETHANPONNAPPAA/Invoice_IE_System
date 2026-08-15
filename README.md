# Invoice Intelligence Ledger

An end-to-end information extraction pipeline for the **business invoice** domain: POS tagging, named entity recognition, relation extraction, event extraction, temporal ordering, and a synthesized knowledge graph — delivered as an interactive Streamlit app, with a Jupyter notebook documenting the backend.

- **Backend**: `pipeline.py` — a single, reusable module imported by both the notebook and the app, so results never drift between the two.
- **Backend development**: `backend_notebook.ipynb` — executed notebook walking through every pipeline stage with real outputs.
- **Frontend**: `app.py` (+ `theme.py` for the visual design) — a Streamlit web app.

## Pipeline stages

| # | Stage | Approach |
|---|---|---|
| 1 | POS tagging | spaCy statistical tagger + dependency parser |
| 2 | Named entity recognition | spaCy statistical NER + regex-detected invoice entities (INVOICE_NUMBER, PO_NUMBER, TAX_ID, AMOUNT, PAYMENT_TERM) |
| 3 | Entity linking (optional) | Wikidata `wbsearchentities` REST API |
| 4 | Relation extraction | Dependency-parse rule engine + proximity field-linking |
| 5 | Event extraction | Trigger-word lexicon + nearest-date association |
| 6 | Temporal ordering | Calendar-date filtering + NetworkX DAG |
| 7 | Knowledge graph | NetworkX `MultiDiGraph` + interactive `pyvis` rendering |

See `report.md` for full technical detail on each stage, including known limitations.

## Project structure

```
.
├── app.py                  # Streamlit frontend
├── theme.py                # UI design tokens / CSS / component helpers
├── pipeline.py              # backend: all NLP/extraction logic
├── backend_notebook.ipynb  # executed backend development notebook
├── build_notebook.py       # script that generates backend_notebook.ipynb
├── report.md                # full pipeline report (source of truth)
├── build_report.js         # generates the ANLP lab report .docx from report.md content
├── ANLP_Lab_Report.docx    # generated lab report (fill in name/USN/repo link before submitting)
├── report_assets/          # diagrams/figures embedded in the lab report
├── requirements.txt
└── sample_data/
    ├── invoice_1.txt
    ├── invoice_2.txt
    └── *.csv                # example entity/relation/event exports
```

## Setup

**Requirements:** Python 3.10+

```bash
git clone <your-repo-url>
cd <repo-folder>
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` installs spaCy's English model (`en_core_web_sm`) directly from its release wheel URL, so **no separate `spacy download` step is needed** — this also matters for hosts like Streamlit Community Cloud, which only run `pip install -r requirements.txt`.

### Dependencies

| Package | Used for |
|---|---|
| `spacy` | POS tagging, dependency parsing, statistical NER |
| `pandas` | Entity/relation/event tables |
| `networkx` | Temporal graph + knowledge graph |
| `python-dateutil` | Calendar-date parsing |
| `requests` | Wikidata entity-linking API calls |
| `streamlit` | Web app framework |
| `plotly` | Milestone timeline chart, POS/entity distribution charts |
| `pyvis` | Interactive knowledge-graph network |
| `nbformat` / `jupyter` | Backend notebook |

## Running the frontend (Streamlit app)

```bash
streamlit run app.py
```

Opens at `http://localhost:8501`. From the sidebar you can:
- load a bundled sample invoice, paste text, or upload a `.txt` file,
- optionally enable Wikidata entity linking (requires internet access to `wikidata.org`),
- click **Run extraction pipeline**, then browse the tabs: Annotated text, POS tags, Entities, Relations, Knowledge Graph, Events & Timeline, and Report.

## Running the backend (notebook)

```bash
jupyter notebook backend_notebook.ipynb
```

Or regenerate it from scratch and re-execute:

```bash
python build_notebook.py
jupyter nbconvert --to notebook --execute --inplace backend_notebook.ipynb
```

## Deploying to Streamlit Community Cloud

1. Push this repo to GitHub (make sure `sample_data/` is committed).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub.
3. **Create app** → select this repo/branch → main file path: `app.py` → **Deploy**.

No `packages.txt` or secrets are required — `pyvis` outputs self-contained static HTML (no headless browser needed at runtime), and the Wikidata API is public/keyless.

> **Note:** if your repo nests `app.py` inside a subfolder, that's fine — all file paths in `app.py` are resolved relative to the script's own location (`Path(__file__).resolve().parent`), not the process's working directory, so it works regardless of where Streamlit's main-file path points.

## Known limitations

- Rule-based relation/event extraction has limited recall on sentence structures outside the trigger lexicon, and occasional false positives on ambiguous dependency parses.
- Wikidata linking is best-effort: it fails silently (no crash) if `wikidata.org` isn't reachable.
- No cross-document entity resolution yet — each invoice is processed independently.

Full detail: see `report.md`.
