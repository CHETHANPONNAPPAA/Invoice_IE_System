"""
pipeline.py
-----------
Backend Information Extraction pipeline for the Business Invoice domain.

Stages implemented:
    1. POS tagging                (spaCy)
    2. Named Entity Recognition   (spaCy statistical NER + custom EntityRuler
                                    for invoice-specific entities)
    3. Entity linking             (Wikidata REST API, best-effort / optional)
    4. Relation extraction        (dependency-parse rule engine)
    5. Event extraction           (trigger-lexicon + nearest-date association)
    6. Temporal ordering          (date normalisation + NetworkX DAG)

This module is imported by BOTH:
    - backend_notebook.ipynb  (development / experimentation)
    - app.py                  (Streamlit front end)

so that the notebook and the deployed app never drift apart.
"""

import re
import itertools
from datetime import datetime

import spacy
from spacy.tokens import Span
from spacy.util import filter_spans
import pandas as pd
import networkx as nx
from dateutil import parser as dateparser

try:
    import requests
except ImportError:
    requests = None


# --------------------------------------------------------------------------
# 1. MODEL LOADING + CUSTOM INVOICE ENTITY DETECTION
# --------------------------------------------------------------------------

_NLP_CACHE = {}

# Domain-specific entities that plain spaCy statistical NER does not know
# about. These invoice codes (INV-2024-1042, PO-88291, ...) get split across
# several tokens by spaCy's tokenizer, which makes token-based EntityRuler
# patterns brittle. Instead we run these as regexes directly over the raw
# text and convert the character spans into spaCy Spans afterwards -- this
# is robust regardless of how the tokenizer splits the match internally.
CUSTOM_REGEX_ENTITIES = [
    ("INVOICE_NUMBER", re.compile(r"(?i)\bINV(?:OICE)?[-#]?\d{2,}(?:-[A-Za-z0-9]+)*\b")),
    ("PO_NUMBER", re.compile(r"(?i)\bPO[-#]?\d{2,}(?:-[A-Za-z0-9]+)*\b")),
    ("TAX_ID", re.compile(r"(?i)\b(?:GSTIN|VAT|TIN|EIN)[-:]?\s*[:\-]?\s*[A-Z0-9]{5,}\b")),
    ("AMOUNT", re.compile(r"[$₹€£]\s?\d[\d,]*(?:\.\d{1,2})?")),
    ("AMOUNT", re.compile(r"(?i)\b(?:USD|INR|EUR|GBP)\s?\d[\d,]*(?:\.\d{1,2})?\b")),
    ("PAYMENT_TERM", re.compile(r"(?i)\bNet\s?\d{1,3}\b")),
    ("PAYMENT_TERM", re.compile(r"(?i)\bDue\s+on\s+receipt\b")),
]


def load_nlp(model="en_core_web_sm"):
    """Load (and cache) a bare spaCy pipeline. Custom entities are layered on
    per-document in `extract_entities` (see CUSTOM_REGEX_ENTITIES)."""
    if model in _NLP_CACHE:
        return _NLP_CACHE[model]
    nlp = spacy.load(model)
    _NLP_CACHE[model] = nlp
    return nlp


def _custom_regex_spans(doc):
    """Find domain-specific entity spans via regex and align them to the doc."""
    spans = []
    for label, pattern in CUSTOM_REGEX_ENTITIES:
        for m in pattern.finditer(doc.text):
            span = doc.char_span(m.start(), m.end(), label=label, alignment_mode="expand")
            if span is not None:
                spans.append(span)
    return spans


# --------------------------------------------------------------------------
# 2. POS TAGGING
# --------------------------------------------------------------------------

def pos_tag(text, nlp=None):
    """Return a DataFrame of token-level POS/morphology/dependency info."""
    nlp = nlp or load_nlp()
    doc = nlp(text)
    rows = [
        {
            "token": tok.text,
            "lemma": tok.lemma_,
            "pos": tok.pos_,          # coarse universal POS
            "tag": tok.tag_,          # fine-grained Penn Treebank tag
            "dep": tok.dep_,          # dependency relation
            "head": tok.head.text,
            "is_stop": tok.is_stop,
        }
        for tok in doc
        if not tok.is_space
    ]
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------
# 3. NAMED ENTITY RECOGNITION
# --------------------------------------------------------------------------

# Map spaCy's generic labels to business-friendly names used downstream.
LABEL_MAP = {
    "ORG": "ORGANIZATION",
    "PERSON": "PERSON",
    "GPE": "LOCATION",
    "LOC": "LOCATION",
    "DATE": "DATE",
    "TIME": "TIME",
    "MONEY": "AMOUNT",
    "CARDINAL": "CARDINAL",
    "PRODUCT": "PRODUCT",
    "INVOICE_NUMBER": "INVOICE_NUMBER",
    "PO_NUMBER": "PO_NUMBER",
    "TAX_ID": "TAX_ID",
    "AMOUNT": "AMOUNT",
    "PAYMENT_TERM": "PAYMENT_TERM",
}


def extract_entities(text, nlp=None):
    """Return (doc, entities_df) — entities_df has one row per detected entity.

    Combines spaCy's statistical NER (PERSON/ORG/GPE/DATE/MONEY/...) with
    regex-detected invoice-specific entities (INVOICE_NUMBER, PO_NUMBER,
    TAX_ID, AMOUNT, PAYMENT_TERM). Overlaps are resolved with spaCy's
    `filter_spans`, which keeps the longest, then earliest span, so
    domain-specific spans placed first win ties against generic ones (e.g.
    "GSTIN: 29ABCDE1234F1Z5" -> TAX_ID instead of CARDINAL).
    """
    nlp = nlp or load_nlp()
    doc = nlp(text)

    custom_spans = _custom_regex_spans(doc)

    def _overlaps_any(span, others):
        return any(span.start < o.end and o.start < span.end for o in others)

    # Custom (regex-detected) spans always win over the generic statistical
    # NER on overlap, regardless of which one is longer -- this fixes cases
    # like "Payment Term: Net 30" being tagged WORK_OF_ART by spaCy's NER
    # when we specifically want "Net 30" -> PAYMENT_TERM.
    kept_statistical_ents = [e for e in doc.ents if not _overlaps_any(e, custom_spans)]
    combined = filter_spans(custom_spans + kept_statistical_ents)
    doc.ents = combined

    rows = []
    for ent in doc.ents:
        rows.append(
            {
                "text": ent.text,
                "label": LABEL_MAP.get(ent.label_, ent.label_),
                "start_char": ent.start_char,
                "end_char": ent.end_char,
            }
        )
    df = pd.DataFrame(rows).drop_duplicates().reset_index(drop=True)
    return doc, df


# --------------------------------------------------------------------------
# 4. ENTITY LINKING (Wikidata) — best effort, requires internet access
# --------------------------------------------------------------------------

def link_entity_to_wikidata(entity_text, timeout=4):
    """
    Query the public Wikidata API for a candidate QID + description for an
    entity string (typically ORGANIZATION / PERSON / LOCATION).

    Returns a dict {qid, label, description, url} or None if unavailable.
    Fails silently (returns None) if there is no network access — this keeps
    the rest of the pipeline fully offline-capable.
    """
    if requests is None:
        return None
    try:
        resp = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": entity_text,
                "language": "en",
                "format": "json",
                "limit": 1,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        results = resp.json().get("search", [])
        if not results:
            return None
        top = results[0]
        return {
            "qid": top.get("id"),
            "label": top.get("label"),
            "description": top.get("description", ""),
            "url": f"https://www.wikidata.org/wiki/{top.get('id')}",
        }
    except Exception:
        return None


def link_entities(entities_df, labels_to_link=("ORGANIZATION", "PERSON", "LOCATION")):
    """Add Wikidata linking columns to an entities DataFrame (best effort)."""
    df = entities_df.copy()
    qids, urls, descs = [], [], []
    for _, row in df.iterrows():
        if row["label"] in labels_to_link:
            link = link_entity_to_wikidata(row["text"])
        else:
            link = None
        qids.append(link["qid"] if link else None)
        urls.append(link["url"] if link else None)
        descs.append(link["description"] if link else None)
    df["wikidata_qid"] = qids
    df["wikidata_description"] = descs
    df["wikidata_url"] = urls
    return df


# --------------------------------------------------------------------------
# 5. RELATION EXTRACTION (dependency-parse rule engine)
# --------------------------------------------------------------------------

# Trigger verbs mapped to a canonical relation label.
RELATION_VERBS = {
    "issue": "ISSUED_BY",
    "bill": "BILLED_TO",
    "invoice": "BILLED_TO",
    "order": "ORDERED_BY",
    "ship": "SHIPPED_TO",
    "deliver": "DELIVERED_TO",
    "pay": "PAID_BY",
    "owe": "OWED_BY",
    "purchase": "PURCHASED_BY",
    "supply": "SUPPLIED_BY",
    "sell": "SOLD_TO",
}


def _entity_span_for_token(tok, ent_lookup):
    return ent_lookup.get(tok.i)


def extract_relations(doc):
    """
    Rule-based relation extraction using dependency parses:
      - SVO triples: nsubj --VERB--> dobj/pobj, where subject/object overlap
        a named entity.
      - Trigger-verb relations mapped to canonical labels (RELATION_VERBS).
      - Simple appositive / prepositional linking for invoice fields, e.g.
        "Invoice INV-2024-001 ... Total Amount: $500" -> (INVOICE_NUMBER, HAS_AMOUNT, AMOUNT)
    """
    ent_lookup = {}
    for ent in doc.ents:
        for tok in ent:
            ent_lookup[tok.i] = ent

    relations = []

    # --- (a) verb-mediated subject/object relations ---
    for tok in doc:
        if tok.pos_ != "VERB":
            continue
        lemma = tok.lemma_.lower()
        subj = next((c for c in tok.children if c.dep_ in ("nsubj", "nsubjpass")), None)
        obj = next((c for c in tok.children if c.dep_ in ("dobj", "pobj", "attr")), None)
        if obj is None:
            # look one level deeper through a preposition (e.g. "issued to X")
            prep = next((c for c in tok.children if c.dep_ == "prep"), None)
            if prep is not None:
                obj = next((c for c in prep.children if c.dep_ == "pobj"), None)
        if subj is None or obj is None:
            continue

        subj_ent = _entity_span_for_token(subj, ent_lookup)
        obj_ent = _entity_span_for_token(obj, ent_lookup)

        relation_label = RELATION_VERBS.get(lemma, lemma.upper())
        relations.append(
            {
                "subject": subj_ent.text if subj_ent else subj.text,
                "subject_label": subj_ent.label_ if subj_ent else subj.pos_,
                "relation": relation_label,
                "object": obj_ent.text if obj_ent else obj.text,
                "object_label": obj_ent.label_ if obj_ent else obj.pos_,
                "evidence": tok.sent.text.strip(),
            }
        )

    # --- (b) proximity-based field linking for invoice key/value pairs ---
    # e.g. "Total Amount: $500.00" / "Due Date: 12 March 2024"
    field_keywords = {
        "AMOUNT": ["total", "amount", "subtotal", "balance", "due amount", "grand total", "tax"],
        "DATE": ["date", "due date", "invoice date", "delivery date"],
    }
    ents_sorted = sorted(doc.ents, key=lambda e: e.start_char)
    for ent in ents_sorted:
        mapped_label = LABEL_MAP.get(ent.label_, ent.label_)
        if mapped_label not in ("AMOUNT", "DATE"):
            continue
        window_start = max(0, ent.start_char - 40)
        preceding_text = doc.text[window_start: ent.start_char].lower()
        for field_label, keywords in field_keywords.items():
            if mapped_label != field_label:
                continue
            for kw in keywords:
                if kw in preceding_text:
                    relations.append(
                        {
                            "subject": "INVOICE",
                            "subject_label": "DOCUMENT",
                            "relation": f"HAS_{field_label}",
                            "object": ent.text,
                            "object_label": mapped_label,
                            "evidence": doc.text[window_start: ent.end_char].strip(),
                        }
                    )
                    break

    df = pd.DataFrame(relations).drop_duplicates(subset=["subject", "relation", "object"]).reset_index(drop=True)
    return df


# --------------------------------------------------------------------------
# 6. EVENT EXTRACTION
# --------------------------------------------------------------------------

EVENT_TRIGGERS = {
    "issue": "InvoiceIssued",
    "generate": "InvoiceIssued",
    "order": "OrderPlaced",
    "place": "OrderPlaced",
    "ship": "GoodsShipped",
    "dispatch": "GoodsShipped",
    "deliver": "GoodsDelivered",
    "receive": "GoodsReceived",
    "pay": "PaymentMade",
    "due": "PaymentDue",
    "cancel": "OrderCancelled",
    "return": "GoodsReturned",
    "refund": "RefundIssued",
}


def _nearest_date_entity(trigger_char_idx, date_entities, max_distance=120):
    """Find the DATE entity whose span is closest (in characters) to a trigger."""
    best, best_dist = None, None
    for ent in date_entities:
        dist = min(abs(ent.start_char - trigger_char_idx), abs(ent.end_char - trigger_char_idx))
        if best_dist is None or dist < best_dist:
            best, best_dist = ent, dist
    if best is not None and best_dist is not None and best_dist <= max_distance:
        return best
    return None


_CALENDAR_DATE_RE = re.compile(
    r"(?i)\b(\d{4})\b|"                                            # a 4-digit year
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\b"  # a month name
)
_DURATION_RE = re.compile(r"(?i)\b\d+\s*(day|days|week|weeks|month|months|year|years)\b")


def _try_parse_date(text):
    """Parse `text` into a datetime ONLY if it looks like an actual calendar
    date (contains a 4-digit year or a month name). This prevents durations
    like "15 days" or "Net 30" from being silently mis-parsed into a bogus
    absolute date (dateutil would otherwise happily read "15" as a day-of-month).
    """
    if not text:
        return None
    if _DURATION_RE.search(text) and not _CALENDAR_DATE_RE.search(text):
        return None
    if not _CALENDAR_DATE_RE.search(text):
        return None
    try:
        return dateparser.parse(text, fuzzy=True, default=datetime(1900, 1, 1))
    except Exception:
        return None


def extract_events(doc):
    """
    Detect event mentions via a trigger-word lexicon and associate each
    with the nearest DATE entity in the same sentence (falls back to the
    nearest date anywhere in the document within a character window).

    Returns a DataFrame: event_type, trigger, sentence, date_text, date_parsed
    """
    date_entities = [e for e in doc.ents if e.label_ == "DATE"]
    events = []
    seen = set()

    for tok in doc:
        lemma = tok.lemma_.lower()
        if tok.pos_ not in ("VERB", "NOUN", "ADJ"):
            continue
        if lemma not in EVENT_TRIGGERS:
            continue

        event_type = EVENT_TRIGGERS[lemma]
        # prefer a DATE entity within the same sentence
        sent_dates = [e for e in date_entities if e.sent.start_char <= tok.idx < e.sent.end_char] if date_entities else []
        candidates = sent_dates if sent_dates else date_entities
        nearest = _nearest_date_entity(tok.idx, candidates) if candidates else None

        date_text = nearest.text if nearest else None
        date_parsed = _try_parse_date(date_text) if date_text else None

        key = (event_type, tok.sent.text.strip())
        if key in seen:
            continue
        seen.add(key)

        events.append(
            {
                "event_type": event_type,
                "trigger": tok.text,
                "sentence": tok.sent.text.strip(),
                "date_text": date_text,
                "date_parsed": date_parsed,
            }
        )

    df = pd.DataFrame(events)
    return df


# --------------------------------------------------------------------------
# 7. TEMPORAL ORDERING
# --------------------------------------------------------------------------

def build_temporal_order(events_df):
    """
    Sort events chronologically by parsed date (undated events are placed
    at the end, in document order) and build a NetworkX DAG where an edge
    A -> B means "A happens before B".
    """
    if events_df.empty:
        return events_df, nx.DiGraph()

    df = events_df.copy()
    df["_sort_key"] = df["date_parsed"].apply(lambda d: d if pd.notnull(d) else datetime.max)
    df = df.sort_values("_sort_key").reset_index(drop=True)
    df["sequence"] = range(1, len(df) + 1)

    graph = nx.DiGraph()
    for i, row in df.iterrows():
        node_id = f"E{row['sequence']}: {row['event_type']}"
        graph.add_node(
            node_id,
            event_type=row["event_type"],
            date=row["date_text"],
            sentence=row["sentence"],
        )
        if i > 0:
            prev_id = f"E{df.iloc[i-1]['sequence']}: {df.iloc[i-1]['event_type']}"
            graph.add_edge(prev_id, node_id, relation="BEFORE")

    df = df.drop(columns=["_sort_key"])
    return df, graph


# --------------------------------------------------------------------------
# 8. FULL PIPELINE ORCHESTRATION
# --------------------------------------------------------------------------

def run_pipeline(text, nlp=None, do_entity_linking=False):
    """Run the full IE pipeline on a single invoice text and return a dict of all artifacts."""
    nlp = nlp or load_nlp()
    doc, entities_df = extract_entities(text, nlp)
    pos_df = pos_tag(text, nlp)
    relations_df = extract_relations(doc)
    events_df = extract_events(doc)
    ordered_events_df, temporal_graph = build_temporal_order(events_df)
    knowledge_graph = build_knowledge_graph(entities_df, relations_df)

    if do_entity_linking and not entities_df.empty:
        entities_df = link_entities(entities_df)

    return {
        "doc": doc,
        "pos_df": pos_df,
        "entities_df": entities_df,
        "relations_df": relations_df,
        "events_df": ordered_events_df,
        "temporal_graph": temporal_graph,
        "knowledge_graph": knowledge_graph,
    }


# --------------------------------------------------------------------------
# 9. RENDERING HELPERS (for Streamlit / notebook display)
# --------------------------------------------------------------------------

ENTITY_COLORS = {
    "ORGANIZATION": "#8ecae6",
    "PERSON": "#ffb703",
    "LOCATION": "#90be6d",
    "DATE": "#f9844a",
    "TIME": "#f9c74f",
    "AMOUNT": "#f94144",
    "INVOICE_NUMBER": "#9b5de5",
    "PO_NUMBER": "#c77dff",
    "TAX_ID": "#4cc9f0",
    "PAYMENT_TERM": "#43aa8b",
    "PRODUCT": "#577590",
}


def render_entities_html(doc):
    """Return spaCy displaCy HTML for entity highlighting, using our custom color map."""
    from spacy import displacy

    options = {"colors": ENTITY_COLORS}
    return displacy.render(doc, style="ent", options=options, page=False, jupyter=False)


EVENT_COLORS = {
    "InvoiceIssued": "#9b5de5",
    "OrderPlaced": "#4361ee",
    "GoodsShipped": "#4cc9f0",
    "GoodsDelivered": "#43aa8b",
    "GoodsReceived": "#90be6d",
    "PaymentDue": "#f9844a",
    "PaymentMade": "#2a9d8f",
    "OrderCancelled": "#e63946",
    "GoodsReturned": "#f3722c",
    "RefundIssued": "#f94144",
}
_DEFAULT_EVENT_COLOR = "#8ecae6"

# Vertical offsets cycled per event (in sequence order, NOT by date) so that
# events sharing an identical or nearby date never land on the same label
# row -- this is what fixes label collisions like two events both on Dec 20.
_ZIGZAG_HEIGHTS = [1.0, -1.0, 1.9, -1.9, 2.8, -2.8]


def render_event_timeline_figure(events_df, graph=None, title="Event timeline"):
    """
    Build a readable "milestone timeline" diagram for the extracted events:

      - Dated events are placed on a real date axis (so actual time gaps
        between events are visible); events without a resolvable date are
        placed after the last dated event on a synthetic axis and clearly
        marked "date unresolved" instead of being silently dropped.
      - Each event gets a short vertical stem up/down from a horizontal
        baseline, with its label attached to the stem tip. Stem height
        cycles through several levels in *sequence* order (not date order),
        so same-date / near-date events land on different rows instead of
        overlapping each other.
      - Thin connector arrows are drawn along the baseline between
        consecutive events (mirroring the BEFORE edges in the NetworkX
        temporal graph) to show the flow of the sequence.

    Returns a plotly.graph_objects.Figure.
    """
    import plotly.graph_objects as go

    fig = go.Figure()

    if events_df is None or events_df.empty:
        fig.update_layout(title=title, height=300)
        fig.add_annotation(text="No events detected", showarrow=False, x=0.5, y=0.5,
                            xref="paper", yref="paper", font=dict(size=14))
        return fig

    df = events_df.reset_index(drop=True).copy()
    dated_mask = df["date_parsed"].notna() if "date_parsed" in df.columns else pd.Series([False] * len(df))
    dated = df[dated_mask]
    undated = df[~dated_mask]

    # --- x-position assignment ---
    # Dated events sit at their real date. Undated events are fanned out
    # evenly to the right of the last real date on a synthetic day-spaced
    # axis, so they stay visible and ordered without falsely implying a
    # precise date.
    x_positions = {}
    for idx, row in dated.iterrows():
        x_positions[idx] = row["date_parsed"]

    if not dated.empty:
        cursor = dated["date_parsed"].max()
    else:
        cursor = pd.Timestamp.today().normalize()
    step = pd.Timedelta(days=max(1, int(getattr(dated["date_parsed"], "diff", lambda: None)().dt.days.dropna().mean()) if len(dated) > 1 else 3)) if not dated.empty else pd.Timedelta(days=3)
    for idx, row in undated.iterrows():
        cursor = cursor + step
        x_positions[idx] = cursor

    # --- baseline ---
    all_x = [x_positions[i] for i in df.index]
    x_min, x_max = min(all_x), max(all_x)
    pad = (x_max - x_min) * 0.08 if x_max != x_min else pd.Timedelta(days=2)
    fig.add_shape(type="line", x0=x_min - pad, x1=x_max + pad, y0=0, y1=0,
                  line=dict(color="rgba(150,150,150,0.5)", width=2))

    # --- connectors along the sequence (mirrors the temporal graph edges) ---
    ordered_idx = list(df.index)
    for a, b in zip(ordered_idx[:-1], ordered_idx[1:]):
        fig.add_annotation(
            x=x_positions[b], y=0, ax=x_positions[a], ay=0,
            xref="x", yref="y", axref="x", ayref="y",
            showarrow=True, arrowhead=2, arrowsize=1, arrowwidth=1.4,
            arrowcolor="rgba(120,170,255,0.6)",
        )

    # --- per-event stem + marker + label ---
    for i, (idx, row) in enumerate(df.iterrows()):
        x = x_positions[idx]
        height = _ZIGZAG_HEIGHTS[i % len(_ZIGZAG_HEIGHTS)]
        color = EVENT_COLORS.get(row["event_type"], _DEFAULT_EVENT_COLOR)
        is_undated = idx in undated.index

        # stem
        fig.add_shape(type="line", x0=x, x1=x, y0=0, y1=height,
                      line=dict(color=color, width=1.5, dash="dot" if is_undated else "solid"))

        # baseline marker
        fig.add_trace(go.Scatter(
            x=[x], y=[0], mode="markers",
            marker=dict(size=10, color=color, line=dict(width=1.5, color="white")),
            hovertext=f"{row['sequence']}. {row['event_type']}<br>{row['sentence'][:120]}",
            hoverinfo="text", showlegend=False,
        ))

        # label at stem tip
        label = f"{row['sequence']}. {row['event_type']}"
        date_caption = "date unresolved" if is_undated else pd.Timestamp(x).strftime("%d %b %Y")
        fig.add_trace(go.Scatter(
            x=[x], y=[height], mode="markers+text",
            marker=dict(size=7, color=color, symbol="diamond" if is_undated else "circle"),
            text=[f"<b>{label}</b><br>{date_caption}"],
            textposition="top center" if height > 0 else "bottom center",
            textfont=dict(size=11, color=color),
            hoverinfo="skip", showlegend=False,
        ))

    fig.update_layout(
        title=title,
        height=420,
        margin=dict(l=30, r=30, t=60, b=40),
        xaxis=dict(title="Date (undated events fanned out to the right)", type="date",
                    gridcolor="rgba(147,161,181,0.15)", zerolinecolor="rgba(147,161,181,0.15)"),
        yaxis=dict(visible=False, range=[-3.6, 3.6]),
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#E8EAED", family="IBM Plex Sans, sans-serif"),
        hoverlabel=dict(bgcolor="#17223A", font_color="#E8EAED"),
    )
    return fig


# --------------------------------------------------------------------------
# 10. KNOWLEDGE GRAPH
# --------------------------------------------------------------------------

KG_NODE_COLORS = {
    **ENTITY_COLORS,
    "DOCUMENT": "#D4A15A",
    "OTHER": "#5C6B84",
}


def build_knowledge_graph(entities_df, relations_df):
    """
    Build an entity-relationship knowledge graph from the extracted relations
    (subject --relation--> object), enriched with entity-type labels pulled
    from `entities_df` where available.

    Returns a networkx.MultiDiGraph — MultiDiGraph because a single pair of
    entities can legitimately be connected by more than one relation (e.g.
    an ORG can both ISSUE an invoice and be BILLED_TO on it).
    """
    graph = nx.MultiDiGraph()

    label_lookup = {}
    if entities_df is not None and not entities_df.empty:
        for _, row in entities_df.iterrows():
            label_lookup.setdefault(row["text"], row["label"])

    if relations_df is None or relations_df.empty:
        return graph

    for _, row in relations_df.iterrows():
        subj, obj, rel = row["subject"], row["object"], row["relation"]
        subj_label = label_lookup.get(subj, row.get("subject_label", "OTHER"))
        obj_label = label_lookup.get(obj, row.get("object_label", "OTHER"))
        if subj == "INVOICE":
            subj_label = "DOCUMENT"

        if subj not in graph:
            graph.add_node(subj, label=subj_label)
        if obj not in graph:
            graph.add_node(obj, label=obj_label)
        graph.add_edge(subj, obj, relation=rel, evidence=row.get("evidence", ""))

    return graph


def knowledge_graph_stats(graph):
    """Summary stats for the knowledge graph: size + most central entities."""
    if graph.number_of_nodes() == 0:
        return {"nodes": 0, "edges": 0, "top_entities": pd.DataFrame()}

    degree = dict(graph.degree())
    centrality = nx.degree_centrality(graph)
    rows = [
        {
            "entity": node,
            "type": data.get("label", "OTHER"),
            "connections": degree.get(node, 0),
            "centrality": round(centrality.get(node, 0), 3),
        }
        for node, data in graph.nodes(data=True)
    ]
    top_df = pd.DataFrame(rows).sort_values("connections", ascending=False).reset_index(drop=True)
    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "top_entities": top_df,
    }


def _inject_autofit_script(html):
    """
    pyvis/vis-network's force layout can settle off-center (especially with
    barnes_hut gravity pulling asymmetrically before it fully stabilizes),
    and physics stays live afterward so any interaction nudges it further
    off-center. This appends a small script that waits for the layout to
    stabilize, calls `network.fit()` to center + zoom the view on all nodes,
    then freezes physics so it stays put instead of drifting again.
    """
    script = """
    <script type="text/javascript">
      (function () {
        function centerGraph() {
          if (typeof network === "undefined") { return; }
          network.fit({animation: {duration: 400, easingFunction: "easeInOutQuad"}});
          network.setOptions({physics: false});
        }
        if (typeof network !== "undefined") {
          network.once("stabilizationIterationsDone", centerGraph);
        }
        // fallback in case stabilization finished before this script attached
        setTimeout(centerGraph, 1200);
      })();
    </script>
    """
    return html.replace("</body>", script + "</body>")


def render_knowledge_graph_html(graph, height="560px", width="100%"):
    """
    Render the knowledge graph as a self-contained, interactive HTML/JS
    network diagram (via pyvis) suitable for embedding with
    streamlit.components.v1.html(). Node size scales with degree
    (how many facts connect to that entity), and edges are labeled with
    the relation type. The view auto-centers on the graph once the force
    layout settles (see `_inject_autofit_script`).
    """
    from pyvis.network import Network

    net = Network(
        height=height, width=width, directed=True,
        bgcolor="#0B1220", font_color="#E8EAED", cdn_resources="in_line",
    )
    net.barnes_hut(gravity=-2500, central_gravity=0.35, spring_length=140, spring_strength=0.02, damping=0.3)

    if graph.number_of_nodes() == 0:
        net.add_node("No relations extracted", color="#5C6B84")
        return _inject_autofit_script(net.generate_html())

    degree = dict(graph.degree())
    max_deg = max(degree.values()) if degree else 1

    for node, data in graph.nodes(data=True):
        label = data.get("label", "OTHER")
        color = KG_NODE_COLORS.get(label, KG_NODE_COLORS["OTHER"])
        size = 16 + 28 * (degree.get(node, 0) / max_deg if max_deg else 0)
        net.add_node(
            node, label=node, title=f"{label} · {degree.get(node, 0)} connection(s)",
            color=color, size=size, borderWidth=2, font={"color": "#E8EAED", "size": 14},
        )

    for u, v, data in graph.edges(data=True):
        net.add_edge(
            u, v, label=data.get("relation", ""),
            title=data.get("evidence", "")[:200],
            color="rgba(212,161,90,0.55)", font={"color": "#D4A15A", "size": 10, "strokeWidth": 0},
            arrows="to",
        )

    net.set_options("""
    {
      "physics": {"stabilization": {"enabled": true, "iterations": 150, "fit": true}},
      "edges": {"smooth": {"type": "continuous"}, "width": 1.5},
      "interaction": {"hover": true, "tooltipDelay": 100},
      "layout": {"improvedLayout": true}
    }
    """)
    return _inject_autofit_script(net.generate_html())
