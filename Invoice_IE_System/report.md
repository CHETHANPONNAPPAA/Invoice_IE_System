# Business Invoice Information Extraction — Pipeline Report

## 1. Objective and domain

This system extracts structured information from **business invoices**:
POS tags, named entities, entity relations, business events, and a
temporal ordering of those events — delivered as an interactive
**Streamlit** application backed by a **Python/Jupyter** development
notebook.

Invoices were chosen as the domain because they are dense,
semi-structured business documents with a predictable set of fields
(invoice number, PO number, tax ID, vendor/buyer, amounts, dates,
payment terms) and a predictable event sequence (order → ship → deliver
→ pay), making them a good testbed for every stage of a classic IE
pipeline.

## 2. Architecture

```
                ┌─────────────────────┐
                │   pipeline.py        │   <-- single source of truth
                │  (backend module)    │
                └─────────┬───────────┘
                          │ imported by
        ┌─────────────────┼─────────────────┐
        │                                     │
┌───────▼────────┐                  ┌─────────▼─────────┐
│ backend_notebook│                  │      app.py         │
│    .ipynb        │                  │  (Streamlit UI)     │
│ (R&D / testing)  │                  │                     │
└──────────────────┘                  └─────────────────────┘
```

`pipeline.py` is imported unchanged by both the notebook (used for
development, debugging, and validating each stage in isolation) and the
Streamlit app (used for interactive, end-user extraction). This keeps
the notebook and the deployed app from ever drifting out of sync.

## 3. Pipeline stages

### 3.1 POS tagging
- **Tool:** spaCy (`en_core_web_sm`), statistical tagger + dependency parser.
- **Output:** per-token `pos` (universal tag), `tag` (Penn Treebank fine
  tag), `dep` (dependency relation), `head`, `lemma`.
- Used both as a deliverable in its own right and as the syntactic
  scaffold for relation and event extraction (Stage 3.4 and 3.5 both
  walk the dependency tree spaCy builds here).

### 3.2 Named Entity Recognition (NER)
Two sources of entities are merged:
1. **Statistical NER** (spaCy): `PERSON`, `ORG`, `GPE`/`LOC`, `DATE`,
   `MONEY`, `CARDINAL`, etc. — good for names, places, and generic dates.
2. **Domain-specific regex entities** (`pipeline.CUSTOM_REGEX_ENTITIES`):
   `INVOICE_NUMBER` (e.g. `INV-2024-1042`), `PO_NUMBER` (`PO-88291`),
   `TAX_ID` (`GSTIN:...`, `EIN-...`), `AMOUNT` (currency-prefixed
   numbers), `PAYMENT_TERM` (`Net 30`, `Due on receipt`).

Because spaCy's tokenizer splits codes like `INV-2024-1042` across
several tokens, these domain entities are matched with regex directly
against the raw text and re-aligned to character-level spaCy `Span`
objects (`doc.char_span(..., alignment_mode="expand")`), then merged
with the statistical entities via `spacy.util.filter_spans`, with the
regex-based entities given priority on overlap. This avoids brittle
token-pattern matching while still producing valid spaCy `Doc.ents`
(which downstream stages, and spaCy's `displacy` renderer, depend on).

### 3.3 Entity linking (Wikidata)
`pipeline.link_entities()` sends each `ORGANIZATION` / `PERSON` /
`LOCATION` entity string to the public Wikidata `wbsearchentities` API
and attaches a QID, a short description, and a canonical URL when a
match is found. This is **best-effort and optional** (toggled in the
Streamlit sidebar): it requires outbound internet access to
`www.wikidata.org`, and fails silently (returns `None`) if that access
isn't available, so the rest of the pipeline is unaffected. In a
sandboxed/offline environment this stage simply won't populate; running
the app on a normal machine with internet access will.

### 3.4 Relation extraction
Implemented as a **rule engine over the dependency parse** (no separate
ML model required, though the module is written so a transformer-based
extractor such as `Babelscape/rebel-large` via Hugging Face
`transformers` could be substituted in without touching the rest of the
pipeline):
- **SVO triples** — for each verb, find its `nsubj`/`nsubjpass` and
  `dobj`/`pobj`/`attr` children (falling back to the object of an
  attached preposition, e.g. "issued **to** Beta Retail Corp"). The
  verb lemma is mapped to a canonical relation label via
  `RELATION_VERBS` (e.g. `issue → ISSUED_BY`, `ship → SHIPPED_TO`,
  `pay → PAID_BY`).
- **Field linking** — a proximity rule that connects an implicit
  `INVOICE` document node to nearby `AMOUNT`/`DATE` entities preceded by
  keywords like *total*, *subtotal*, *due date* (e.g.
  `(INVOICE, HAS_AMOUNT, $4,730.00)`).

Output is a table of `(subject, relation, object, evidence sentence)`.

### 3.5 Event extraction
A small **trigger lexicon** (`EVENT_TRIGGERS`) maps invoice-relevant
verbs/nouns to canonical business event types:

| Trigger words | Event type |
|---|---|
| issue, generate | `InvoiceIssued` |
| order, place | `OrderPlaced` |
| ship, dispatch | `GoodsShipped` |
| deliver | `GoodsDelivered` |
| receive | `GoodsReceived` |
| pay | `PaymentMade` |
| due | `PaymentDue` |
| cancel | `OrderCancelled` |
| return | `GoodsReturned` |
| refund | `RefundIssued` |

Each detected trigger is paired with the nearest `DATE` entity in the
same sentence (falling back to the nearest date in the document within
a character-distance window).

### 3.6 Temporal ordering
Event dates are parsed with `dateutil`, but only when the date text
actually looks like a calendar date (contains a 4-digit year or a month
name — implemented in `_try_parse_date` / `_CALENDAR_DATE_RE`). This
deliberately excludes **durations** like *"15 days"* or payment terms
like *"Net 30"*, which are not absolute timestamps and would otherwise
be mis-parsed by naive date parsers. Dated events are sorted
chronologically and encoded as a **NetworkX `DiGraph`** where an edge
`A → B` means "A happens before B".

### 3.7 Milestone timeline diagram
A first pass at the timeline used a plain date-axis scatter plot, which
breaks down in a very common invoice scenario: several events sharing
the same date (e.g. an order placed and invoice issued on the same day)
render their labels directly on top of each other, and any event whose
date couldn't be resolved was silently dropped from the chart.

`render_event_timeline_figure()` fixes both problems:
- Each event's label sits at the tip of a vertical "stem" whose height
  cycles through six levels **in sequence order** (not date order), so
  same-date (or near-date) events always land on different rows instead
  of overlapping.
- Events with no resolvable date are fanned out to the right of the
  real dates on a synthetic axis, drawn with a dotted stem and a diamond
  marker, and explicitly labeled "date unresolved" — visible and
  honestly flagged rather than silently discarded.
- Thin connector arrows are drawn along the baseline between
  consecutive events, mirroring the `BEFORE` edges in the NetworkX
  temporal graph, so the sequence is legible even when dates are far
  apart or missing.

### 3.8 Knowledge graph
`build_knowledge_graph()` folds the NER table and the relation table
into a single `networkx.MultiDiGraph`: every `(subject, relation,
object)` row becomes an edge, and each node is colored by its entity
type (pulled from the NER table where available, falling back to the
type recorded alongside the relation). This is a `MultiDiGraph`
specifically because a single pair of entities can be linked by more
than one fact — e.g. an organization can both `ISSUED_BY` an invoice and
appear as its `BILLED_TO` party.

`render_knowledge_graph_html()` renders this graph as a self-contained,
interactive network diagram via `pyvis` (physics-based layout, draggable
nodes, hover tooltips showing the supporting sentence), embedded in the
Streamlit app with `streamlit.components.v1.html()`. Node size scales
with degree centrality, so the busiest entities in the document — almost
always the vendor and the invoice itself — are visually the largest.
`knowledge_graph_stats()` additionally ranks entities by degree/degree
centrality for the "Most connected entities" table shown alongside the
graph.

## 4. Deliverables mapping

| Deliverable | Where to find it |
|---|---|
| Annotated text output | Streamlit "Annotated text" tab (`displacy` NER highlighting); notebook Section 3 |
| Entity and relation tables | Streamlit "Entities"/"Relations" tabs + CSV download; notebook exports to `sample_data/*.csv` |
| Event timeline / temporal graph | Streamlit "Events & Timeline" tab (milestone diagram + NetworkX edge table); notebook Section 7 |
| Knowledge graph | Streamlit "Knowledge Graph" tab (interactive `pyvis` network + centrality table); notebook Section 8 |
| Short report | this file (`report.md`), also rendered inside the Streamlit app's "Report" tab |

## 5. UI design

The Streamlit app carries a deliberate visual identity (`theme.py`) rather
than default Streamlit styling — an "audit ledger" concept grounded in
the invoice domain itself:

- **Palette**: deep ink-navy background (`#0B1220`) with a brass/gold
  accent (`#D4A15A`) standing in for a ledger stamp, teal/amber/red
  reserved for status meaning rather than decoration.
- **Type**: Space Grotesk for headings, IBM Plex Sans for body text, and
  IBM Plex Mono for anything that is literally ledger data — entity
  codes, invoice/PO numbers, badge labels — so the data itself reads as
  data.
- **KPI ledger row**: entity/relation/event/graph-edge counts rendered
  as stamped cards at the top of the page after each run, giving an
  at-a-glance summary before drilling into any tab.
- **Stamped badges**: a consistent color-coded badge component
  (`theme.badge`) used for entity types, event types, and knowledge-graph
  node types, so the same visual vocabulary for "what kind of thing is
  this" carries across every tab.
- **Charts**: Plotly's dark template with the same brass/entity-color
  palette, transparent backgrounds so they sit flush inside the themed
  page rather than showing a white card.

## 6. Tools used

| Stage | Tool |
|---|---|
| POS tagging, dependency parsing | spaCy |
| Statistical NER | spaCy |
| Domain entity detection | Python `re` + spaCy `Span`/`filter_spans` |
| Entity linking | Wikidata REST API (`requests`) |
| Relation & event extraction | Rule engine over spaCy dependency parse |
| Temporal graph | NetworkX |
| Knowledge graph | NetworkX (`MultiDiGraph`) + `pyvis` (interactive rendering) |
| Tabular deliverables | pandas |
| Frontend | Streamlit + Plotly, custom theme (`theme.py`) |
| Backend development | Jupyter notebook (`backend_notebook.ipynb`) |

NLTK, Stanza, Hugging Face Transformers, and Stanford CoreNLP were all
permitted but not required for this implementation; spaCy alone covers
POS/NER/dependency parsing adequately for the invoice domain, and using
one library end-to-end keeps the notebook and app consistent. The
architecture is modular enough that any stage can be swapped for one of
these alternatives — for example, replacing the rule-based relation
extractor with a Hugging Face `transformers` pipeline running
`Babelscape/rebel-large` for open relation extraction, or replacing
spaCy's NER with Stanza/CoreNLP for languages spaCy's small English
model handles poorly.

## 7. Known limitations

- The rule-based relation and event extractors are lexicon/dependency
  driven, so recall is limited to sentences containing a recognized
  trigger verb, and precision suffers on complex or passive
  constructions (some spurious relations may appear, e.g. from
  incidental verbs unrelated to the invoice's core narrative).
- spaCy's small English model (`en_core_web_sm`) occasionally
  mislabels an entity (e.g. tagging a stray "Invoice" or "Bill" token
  as `LOCATION`/`PERSON`); a larger model (`en_core_web_trf`) would
  improve accuracy at the cost of speed/size.
- Wikidata linking requires outbound internet access and is best-effort
  only — it will silently return no links in network-restricted
  environments (including this build/test sandbox).
- The temporal graph assumes a simple linear "before" chain between
  consecutively dated events; it does not yet model events that occur
  on the same date or true partial-order/branching timelines.
- The knowledge graph is built per-document from the rule-based relation
  extractor, so it inherits that stage's precision/recall limits; it
  does not yet merge entities across multiple invoices (e.g. recognizing
  "Acme Manufacturing" in one invoice and "Acme Mfg." in another as the
  same node) — see the batch/corpus extension idea below.

## 8. Running the system

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
streamlit run app.py
```

To explore/extend the backend interactively:

```bash
jupyter notebook backend_notebook.ipynb
```
