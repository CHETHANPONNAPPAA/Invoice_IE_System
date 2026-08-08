"""
app.py — Streamlit front end for the Invoice Intelligence Ledger.

Run with:
    streamlit run app.py

This file is intentionally thin: all NLP logic lives in pipeline.py, and all
visual design lives in theme.py, so the notebook (backend_notebook.ipynb)
and this app always share identical extraction logic.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.io as pio
import streamlit.components.v1 as components

import pipeline as pl
import theme

st.set_page_config(page_title="Invoice Intelligence Ledger", page_icon="🧾", layout="wide")
theme.inject(st)
pio.templates.default = "plotly_dark"

PLOTLY_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(color=theme.TEXT, family="IBM Plex Sans, sans-serif"),
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)

# --------------------------------------------------------------------------
# Sidebar — input controls
# --------------------------------------------------------------------------
st.sidebar.markdown(
    f'<div style="font-family:{theme.FONT_DISPLAY}; font-weight:700; font-size:1.15rem; '
    f'color:{theme.BRASS};">🧾 Invoice Ledger</div>'
    f'<div style="color:{theme.MUTED}; font-size:0.8rem; margin-bottom:14px;">'
    f'Text → structure → knowledge graph</div>',
    unsafe_allow_html=True,
)

SAMPLE_FILES = {
    "Sample invoice 1 (Acme → Beta Retail)": "sample_data/invoice_1.txt",
    "Sample invoice 2 (Global Tech → Nova Electronics)": "sample_data/invoice_2.txt",
}

source = st.sidebar.radio("Input source", ["Choose a sample invoice", "Paste text", "Upload a .txt file"])

text = ""
if source == "Choose a sample invoice":
    choice = st.sidebar.selectbox("Sample", list(SAMPLE_FILES.keys()))
    with open(SAMPLE_FILES[choice], encoding="utf-8") as f:
        text = f.read()
elif source == "Paste text":
    text = st.sidebar.text_area("Paste invoice text", height=250)
else:
    uploaded = st.sidebar.file_uploader("Upload invoice (.txt)", type=["txt"])
    if uploaded is not None:
        text = uploaded.read().decode("utf-8", errors="ignore")

do_linking = st.sidebar.checkbox(
    "Link entities to Wikidata",
    value=False,
    help="Queries the public Wikidata API for ORG/PERSON/LOCATION entities. "
         "Requires outbound internet access to wikidata.org.",
)

run_btn = st.sidebar.button("▶ Run extraction pipeline", type="primary", use_container_width=True)

st.sidebar.markdown('<hr class="ie-rule" style="margin:14px 0;"/>', unsafe_allow_html=True)
st.sidebar.markdown(
    f'<div style="font-family:{theme.FONT_MONO}; font-size:11px; letter-spacing:0.1em; '
    f'text-transform:uppercase; color:{theme.MUTED}; margin-bottom:6px;">Pipeline stages</div>',
    unsafe_allow_html=True,
)
st.sidebar.markdown(
    "1. POS tagging (spaCy)\n"
    "2. NER — statistical + invoice-specific regex\n"
    "3. Entity linking (Wikidata, optional)\n"
    "4. Relation extraction (dependency rules)\n"
    "5. Event extraction (trigger lexicon)\n"
    "6. Temporal ordering (NetworkX DAG)\n"
    "7. Knowledge graph synthesis"
)

# --------------------------------------------------------------------------
# Hero
# --------------------------------------------------------------------------
theme.hero(
    st,
    eyebrow="STAGE 01–07 · UNSTRUCTURED TEXT → LEDGER → GRAPH",
    title="Invoice Intelligence Ledger",
    subtitle="An end-to-end information extraction pipeline for business invoices: "
             "POS tagging, named entity recognition, relation extraction, event extraction, "
             "temporal ordering, and a synthesized knowledge graph.",
)

if not text.strip():
    st.info("👈 Choose a sample invoice, paste text, or upload a file, then click **Run extraction pipeline**.")
    st.stop()

with st.expander("📃 Raw input text", expanded=False):
    st.text(text)

if not run_btn:
    st.warning("Click **Run extraction pipeline** in the sidebar to process this text.")
    st.stop()

with st.spinner("Running pipeline..."):
    nlp = pl.load_nlp()
    result = pl.run_pipeline(text, nlp=nlp, do_entity_linking=do_linking)

# --------------------------------------------------------------------------
# KPI ledger row
# --------------------------------------------------------------------------
kg = result["knowledge_graph"]
theme.kpi_row(st, [
    ("Entities", len(result["entities_df"])),
    ("Relations", len(result["relations_df"])),
    ("Events", len(result["events_df"])),
    ("Graph edges", kg.number_of_edges()),
])

tabs = st.tabs([
    "🖍️ Annotated text",
    "🔤 POS tags",
    "🏷️ Entities",
    "🔗 Relations",
    "🕸️ Knowledge Graph",
    "📅 Events & Timeline",
    "🧾 Report",
])

# --- Tab 1: Annotated text (displaCy NER highlighting) ---
with tabs[0]:
    theme.section_title(st, "Named entities highlighted in context")
    html = pl.render_entities_html(result["doc"])
    st.markdown(
        f'<div style="line-height:2.1; background:{theme.PANEL}; border:1px solid {theme.BORDER}; '
        f'border-radius:8px; padding:16px;">{html}</div>',
        unsafe_allow_html=True,
    )

# --- Tab 2: POS tagging ---
with tabs[1]:
    theme.section_title(st, "Part-of-speech tags",
                         "Universal POS (`pos`), Penn Treebank fine tag (`tag`), and dependency relation (`dep`) per token.")
    st.dataframe(result["pos_df"], use_container_width=True, height=450)
    pos_counts = result["pos_df"]["pos"].value_counts().reset_index()
    pos_counts.columns = ["POS", "count"]
    fig = px.bar(pos_counts, x="POS", y="count", title="POS tag distribution",
                 color_discrete_sequence=[theme.BRASS])
    fig.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig, use_container_width=True)

# --- Tab 3: Entities ---
with tabs[2]:
    theme.section_title(st, "Detected entities")
    ent_df = result["entities_df"]

    present_labels = ent_df["label"].value_counts()
    theme.badge_legend(st, [
        (label, pl.ENTITY_COLORS.get(label, theme.MUTED), int(count))
        for label, count in present_labels.items()
    ])

    st.dataframe(ent_df, use_container_width=True, height=380)

    label_counts = ent_df["label"].value_counts().reset_index()
    label_counts.columns = ["label", "count"]
    color_map = {l: pl.ENTITY_COLORS.get(l, theme.MUTED) for l in label_counts["label"]}
    fig2 = px.pie(label_counts, names="label", values="count", title="Entity type distribution",
                  color="label", color_discrete_map=color_map, hole=0.45)
    fig2.update_layout(**PLOTLY_LAYOUT)
    st.plotly_chart(fig2, use_container_width=True)

    if do_linking and "wikidata_qid" in ent_df.columns:
        theme.section_title(st, "Wikidata-linked entities")
        linked = ent_df[ent_df["wikidata_qid"].notna()][["text", "label", "wikidata_qid", "wikidata_description", "wikidata_url"]]
        if linked.empty:
            st.info("No entities were successfully linked (check network access to wikidata.org).")
        else:
            st.dataframe(linked, use_container_width=True)

    csv = ent_df.to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Download entities as CSV", csv, "entities.csv", "text/csv")

# --- Tab 4: Relations ---
with tabs[3]:
    theme.section_title(st, "Extracted relations", "subject → relation → object, with the source sentence as evidence.")
    rel_df = result["relations_df"]
    if rel_df.empty:
        st.info("No relations were extracted from this text.")
    else:
        st.dataframe(rel_df, use_container_width=True, height=380)
        csv2 = rel_df.to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download relations as CSV", csv2, "relations.csv", "text/csv")

# --- Tab 5: Knowledge Graph ---
with tabs[4]:
    theme.section_title(
        st, "Entity–relationship knowledge graph",
        "Every extracted relation as a connected graph. Node size scales with degree "
        "(how many facts touch that entity) — hover a node or edge for detail.",
    )
    if kg.number_of_nodes() == 0:
        st.info("No relations were extracted, so there's no graph to draw for this text.")
    else:
        stats = pl.knowledge_graph_stats(kg)
        present_kg_labels = stats["top_entities"]["type"].value_counts()
        theme.badge_legend(st, [
            (label, pl.KG_NODE_COLORS.get(label, theme.MUTED), int(count))
            for label, count in present_kg_labels.items()
        ])

        graph_html = pl.render_knowledge_graph_html(kg)
        st.markdown('<div class="ie-graph-frame">', unsafe_allow_html=True)
        components.html(graph_html, height=580, scrolling=False)
        st.markdown('</div>', unsafe_allow_html=True)

        col1, col2 = st.columns([1, 1])
        with col1:
            st.metric("Nodes (entities)", stats["nodes"])
        with col2:
            st.metric("Edges (facts)", stats["edges"])

        theme.section_title(st, "Most connected entities", "Ranked by degree — how many extracted facts reference each entity.")
        st.dataframe(stats["top_entities"], use_container_width=True, height=300)

# --- Tab 6: Events & Timeline ---
with tabs[5]:
    theme.section_title(st, "Detected events, ordered chronologically")
    ev_df = result["events_df"]
    if ev_df.empty:
        st.info("No events were detected in this text.")
    else:
        present_event_types = ev_df["event_type"].value_counts()
        theme.badge_legend(st, [
            (etype, pl.EVENT_COLORS.get(etype, theme.MUTED), int(count))
            for etype, count in present_event_types.items()
        ])

        st.dataframe(
            ev_df[["sequence", "event_type", "trigger", "date_text", "date_parsed", "sentence"]],
            use_container_width=True,
            height=280,
        )

        dated = ev_df[ev_df["date_parsed"].notna()]
        timeline_fig = pl.render_event_timeline_figure(ev_df, result["temporal_graph"])
        st.plotly_chart(timeline_fig, use_container_width=True)
        if dated.empty:
            st.caption("None of the detected events had a resolvable calendar date, so they're fanned out on a synthetic axis (marked 'date unresolved').")
        elif len(dated) < len(ev_df):
            st.caption(f"{len(ev_df) - len(dated)} event(s) had no resolvable date and are shown fanned out to the right, marked 'date unresolved'.")

        theme.section_title(st, "Temporal graph (event precedence)")
        graph = result["temporal_graph"]
        edge_rows = [{"before": u, "after": v} for u, v in graph.edges()]
        st.dataframe(pd.DataFrame(edge_rows), use_container_width=True)

        csv3 = ev_df.drop(columns=["date_parsed"]).to_csv(index=False).encode("utf-8")
        st.download_button("⬇️ Download events as CSV", csv3, "events.csv", "text/csv")

# --- Tab 7: Report ---
with tabs[6]:
    theme.section_title(st, "Pipeline report")
    try:
        with open("report.md", encoding="utf-8") as f:
            st.markdown(f.read())
    except FileNotFoundError:
        st.info("report.md not found alongside app.py.")
