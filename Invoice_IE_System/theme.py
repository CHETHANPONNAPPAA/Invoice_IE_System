"""
theme.py — visual identity for the Invoice Intelligence Ledger app.

Concept: an audit-ledger / financial-terminal aesthetic grounded in the
invoice domain itself — deep ink-navy pages, a brass "stamped ledger"
accent for structure and labels, teal/amber/red reserved strictly for
status meaning (matched / due / overdue), and a monospace face for
anything that is literally ledger data (codes, amounts, IDs).

Kept out of app.py so the UI logic and the visual design can evolve
independently.
"""

# --------------------------------------------------------------------------
# Design tokens
# --------------------------------------------------------------------------

INK = "#0B1220"          # page background
PANEL = "#121B2E"        # card / panel background
PANEL_ALT = "#17223A"    # hover / secondary panel
BRASS = "#D4A15A"        # primary accent — "stamped ledger" gold
TEAL = "#4FD1C5"         # positive / matched
AMBER = "#F2B84B"        # warning / due
RED = "#EF5350"          # alert / overdue / mismatch
TEXT = "#E8EAED"
MUTED = "#93A1B5"
BORDER = "rgba(212,161,90,0.25)"

FONT_DISPLAY = "'Space Grotesk', sans-serif"
FONT_BODY = "'IBM Plex Sans', sans-serif"
FONT_MONO = "'IBM Plex Mono', monospace"


def _hex_to_rgba(hex_color, alpha):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap');

:root {{
    --ink: {INK};
    --panel: {PANEL};
    --panel-alt: {PANEL_ALT};
    --brass: {BRASS};
    --teal: {TEAL};
    --amber: {AMBER};
    --red: {RED};
    --text: {TEXT};
    --muted: {MUTED};
    --border: {BORDER};
}}

/* -- page shell -- */
.stApp {{
    background:
        radial-gradient(ellipse 1200px 600px at 15% -10%, rgba(212,161,90,0.07), transparent 60%),
        var(--ink);
    font-family: {FONT_BODY};
    color: var(--text);
}}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"] {{ right: 1rem; }}
.block-container {{ padding-top: 2rem; max-width: 1200px; }}

/* -- sidebar -- */
section[data-testid="stSidebar"] {{
    background: var(--panel);
    border-right: 1px solid var(--border);
}}
section[data-testid="stSidebar"] * {{ color: var(--text); }}
section[data-testid="stSidebar"] .stCaptionContainer, section[data-testid="stSidebar"] small {{
    color: var(--muted) !important;
}}

/* -- typography -- */
h1, h2, h3, h4 {{
    font-family: {FONT_DISPLAY};
    letter-spacing: -0.01em;
    color: var(--text) !important;
}}
p, li, label, span, div {{ font-family: {FONT_BODY}; }}
code, .stCodeBlock, pre {{ font-family: {FONT_MONO} !important; }}

/* -- hero -- */
.ie-eyebrow {{
    font-family: {FONT_MONO};
    font-size: 11px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--brass);
    margin-bottom: 6px;
}}
.ie-hero-title {{
    font-family: {FONT_DISPLAY};
    font-weight: 700;
    font-size: 2.4rem;
    line-height: 1.1;
    margin: 0 0 8px 0;
    background: linear-gradient(90deg, #F3D9AE 0%, var(--brass) 55%, #9c6f2e 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
}}
.ie-hero-sub {{
    color: var(--muted);
    font-size: 0.98rem;
    max-width: 780px;
    margin-bottom: 4px;
}}
.ie-rule {{
    border: none;
    height: 1px;
    background: linear-gradient(90deg, var(--brass), transparent 75%);
    opacity: 0.55;
    margin: 18px 0 26px 0;
}}

/* -- KPI ledger row -- */
.ie-kpi-row {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 22px; }}
.ie-kpi-card {{
    background: linear-gradient(180deg, var(--panel-alt), var(--panel));
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px 16px 12px 16px;
    position: relative;
    overflow: hidden;
}}
.ie-kpi-card::before {{
    content: "";
    position: absolute; top: 0; left: 0; right: 0; height: 2px;
    background: var(--brass); opacity: 0.7;
}}
.ie-kpi-number {{
    font-family: {FONT_DISPLAY}; font-weight: 700; font-size: 1.9rem; color: var(--text);
}}
.ie-kpi-label {{
    font-family: {FONT_MONO}; font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase;
    color: var(--muted); margin-top: 2px;
}}

/* -- stamped badges (entity / event type legend) -- */
.ie-badge {{
    display: inline-flex; align-items: center; gap: 5px;
    font-family: {FONT_MONO}; font-size: 10.5px; letter-spacing: 0.08em; text-transform: uppercase;
    padding: 3px 8px; margin: 2px 5px 2px 0;
    border-radius: 4px; border: 1px solid var(--border);
}}
.ie-badge-dot {{ width: 7px; height: 7px; border-radius: 50%; display: inline-block; }}

/* -- section headers -- */
.ie-section-title {{
    font-family: {FONT_DISPLAY}; font-weight: 600; font-size: 1.15rem; color: var(--text);
    margin-bottom: 2px;
}}
.ie-section-sub {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 14px; }}

/* -- tabs -- */
[data-baseweb="tab-list"] {{
    gap: 4px; border-bottom: 1px solid var(--border);
}}
button[data-baseweb="tab"] {{
    font-family: {FONT_MONO}; font-size: 12.5px; letter-spacing: 0.03em;
    color: var(--muted); background: transparent;
}}
button[data-baseweb="tab"][aria-selected="true"] {{
    color: var(--brass) !important;
    border-bottom: 2px solid var(--brass) !important;
}}

/* -- buttons -- */
.stButton > button, .stDownloadButton > button {{
    background: linear-gradient(135deg, var(--brass), #b9843f);
    color: #1a1305; font-weight: 600; border: none; border-radius: 5px;
    font-family: {FONT_BODY};
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    filter: brightness(1.08);
}}
section[data-testid="stSidebar"] .stButton > button {{ width: 100%; }}

/* -- dataframes / expanders / containers -- */
[data-testid="stDataFrame"], [data-testid="stExpander"] {{
    border: 1px solid var(--border) !important;
    border-radius: 6px !important;
    overflow: hidden;
}}
[data-testid="stMetric"] {{
    background: var(--panel-alt); border: 1px solid var(--border); border-radius: 6px; padding: 10px 14px;
}}

/* -- alerts -- */
[data-testid="stAlertContainer"] {{ border-radius: 6px; }}

/* -- iframe (pyvis / plotly) wrapper -- */
.ie-graph-frame {{
    border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
    background: {INK};
    display: flex; justify-content: center; align-items: center;
}}
.ie-graph-frame iframe {{ display: block; margin: 0 auto; }}
</style>
"""


def inject(st):
    """Call once near the top of app.py: theme.inject(st)."""
    st.markdown(CSS, unsafe_allow_html=True)


def hero(st, eyebrow, title, subtitle):
    st.markdown(
        f"""
        <div class="ie-eyebrow">{eyebrow}</div>
        <div class="ie-hero-title">{title}</div>
        <div class="ie-hero-sub">{subtitle}</div>
        <hr class="ie-rule"/>
        """,
        unsafe_allow_html=True,
    )


def section_title(st, title, subtitle=None):
    sub_html = f'<div class="ie-section-sub">{subtitle}</div>' if subtitle else ""
    st.markdown(f'<div class="ie-section-title">{title}</div>{sub_html}', unsafe_allow_html=True)


def kpi_row(st, items):
    """items: list of (label, value) tuples."""
    cards = "".join(
        f'<div class="ie-kpi-card"><div class="ie-kpi-number">{value}</div>'
        f'<div class="ie-kpi-label">{label}</div></div>'
        for label, value in items
    )
    st.markdown(f'<div class="ie-kpi-row">{cards}</div>', unsafe_allow_html=True)


def badge(label, color, count=None):
    suffix = f" ({count})" if count is not None else ""
    return (
        f'<span class="ie-badge" style="color:{color}; background:{_hex_to_rgba(color, 0.12)};">'
        f'<span class="ie-badge-dot" style="background:{color};"></span>{label}{suffix}</span>'
    )


def badge_legend(st, labels_with_colors_and_counts):
    """labels_with_colors_and_counts: list of (label, color, count)."""
    html = "".join(badge(l, c, n) for l, c, n in labels_with_colors_and_counts)
    st.markdown(f'<div style="margin: 6px 0 16px 0;">{html}</div>', unsafe_allow_html=True)
