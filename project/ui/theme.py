"""Visual system for the Streamlit UI: palette, CSS and small HTML components."""
from __future__ import annotations

import html

import streamlit as st

PRIMARY = "#0F766E"
PRIMARY_DARK = "#0F172A"
PRIMARY_SOFT = "#F0FDFA"
BG = "#F8FAFC"
SURFACE = "#FFFFFF"
BORDER = "#E2E8F0"
TEXT = "#0F172A"
MUTED = "#64748B"
AMBER = "#D97706"
RED = "#DC2626"
GREEN = "#16A34A"
GREY = "#94A3B8"

TONES = {
    "primary": (PRIMARY, PRIMARY_SOFT),
    "warn": (AMBER, "#FFFBEB"),
    "bad": (RED, "#FEF2F2"),
    "good": (GREEN, "#F0FDF4"),
    "muted": (GREY, "#F1F5F9"),
}

STATUS_TONE = {
    "DRAFT": "muted",
    "VALIDATED": "primary",
    "PENDING_APPROVAL": "warn",
    "APPROVED": "good",
    "CREATED": "good",
    "RECEIVED": "good",
    "REJECTED": "bad",
    "CANCELLED": "bad",
    "pending_approval": "warn",
    "created": "good",
    "escalated": "bad",
    "rejected": "bad",
    "no_action": "muted",
    "failed": "bad",
    "high": "bad",
    "medium": "warn",
    "low": "muted",
}

CSS = f"""
<style>
:root {{
  --primary: {PRIMARY};
  --bg: {BG};
  --border: {BORDER};
  --text: {TEXT};
  --muted: {MUTED};
}}
html, body, [class*="css"] {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: {TEXT};
}}
.stApp {{
  background: {BG};
  color: {TEXT};
}}
section[data-testid="stSidebar"] {{
  background: {PRIMARY_DARK};
  border-right: 1px solid #1E293B;
}}
section[data-testid="stSidebar"] * {{
  color: #F8FAFC !important;
}}
section[data-testid="stSidebar"] [data-baseweb="select"] * {{
  color: {TEXT} !important;
}}
section[data-testid="stSidebar"] .stButton button {{
  background: {PRIMARY};
  border: 1px solid #14B8A6;
  color: #FFFFFF !important;
  font-weight: 600;
  border-radius: 8px;
}}
section[data-testid="stSidebar"] .stButton button:hover {{
  background: #0D9488;
  border-color: #2DD4BF;
}}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"] {{
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 2px;
}}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"][aria-current="page"] {{
  background: #1E293B;
  border-left: 3px solid #14B8A6;
}}
.block-container {{
  padding-top: 1.8rem;
  padding-bottom: 3.5rem;
  max-width: 1360px;
}}
h1, h2, h3, h4 {{
  color: {TEXT};
  letter-spacing: -0.02em;
  font-weight: 700;
}}
.pa-eyebrow {{
  text-transform: uppercase;
  font-size: 0.72rem;
  letter-spacing: 0.1em;
  color: {PRIMARY};
  font-weight: 700;
}}
.pa-title {{
  font-size: 1.85rem;
  font-weight: 800;
  margin: 0.1rem 0 0.25rem 0;
  color: {TEXT};
}}
.pa-sub {{
  color: {MUTED};
  font-size: 0.95rem;
  margin-bottom: 1.3rem;
  max-width: 72rem;
  line-height: 1.5;
}}
.pa-card {{
  background: {SURFACE};
  border: 1px solid {BORDER};
  border-radius: 12px;
  padding: 18px 20px;
  margin-bottom: 14px;
  box-shadow: 0 1px 3px 0 rgba(0,0,0,0.04);
}}
.pa-banner {{
  background: linear-gradient(135deg, #F0FDFA 0%, #FFFFFF 100%);
  border: 1px solid #CCFBF1;
  border-radius: 14px;
  padding: 22px 26px;
  margin-bottom: 22px;
  box-shadow: 0 4px 6px -1px rgba(15,118,110,0.06);
}}
.pa-banner h3 {{
  margin: 0 0 6px 0;
  color: #115E59;
  font-size: 1.3rem;
  font-weight: 800;
}}
.pa-banner p {{
  margin: 0 0 14px 0;
  color: {MUTED};
  font-size: 0.93rem;
  line-height: 1.5;
}}
.pa-flow-steps {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
  margin-top: 16px;
}}
.pa-flow-step {{
  background: #FFFFFF;
  border: 1px solid #CCFBF1;
  border-radius: 10px;
  padding: 14px 16px;
  box-shadow: 0 1px 2px 0 rgba(0,0,0,0.03);
}}
.pa-flow-step .num {{
  display: inline-block;
  width: 24px;
  height: 24px;
  line-height: 24px;
  text-align: center;
  background: {PRIMARY};
  color: #FFFFFF;
  border-radius: 50%;
  font-size: 0.78rem;
  font-weight: 700;
  margin-right: 8px;
}}
.pa-flow-step .title {{
  font-weight: 700;
  font-size: 0.92rem;
  color: {TEXT};
}}
.pa-flow-step .desc {{
  font-size: 0.82rem;
  color: {MUTED};
  margin-top: 6px;
  line-height: 1.45;
}}
.pa-callout {{
  background: #F0FDFA;
  border-left: 4px solid {PRIMARY};
  border-radius: 0 10px 10px 0;
  padding: 14px 18px;
  margin: 14px 0;
  font-size: 0.9rem;
  color: {TEXT};
  line-height: 1.5;
}}
.pa-callout.tip {{
  background: #FFFBEB;
  border-left-color: {AMBER};
}}
.pa-callout.success {{
  background: #F0FDF4;
  border-left-color: {GREEN};
}}
.pa-kpi {{
  background: {SURFACE};
  border: 1px solid {BORDER};
  border-radius: 12px;
  padding: 16px 18px;
  height: 100%;
  border-top: 4px solid var(--tone);
  box-shadow: 0 1px 3px 0 rgba(0,0,0,0.03);
}}
.pa-kpi .l {{
  color: {MUTED};
  font-size: 0.76rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}}
.pa-kpi .v {{
  font-size: 1.75rem;
  font-weight: 800;
  color: {TEXT};
  margin-top: 4px;
}}
.pa-kpi .s {{
  color: {MUTED};
  font-size: 0.82rem;
  margin-top: 4px;
  line-height: 1.35;
}}
.pa-pill {{
  display: inline-block;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 0.76rem;
  font-weight: 700;
  color: var(--fg);
  background: var(--bgc);
  border: 1px solid var(--fg);
  white-space: nowrap;
}}
.pa-mode {{
  font-size: 0.78rem;
  padding: 8px 12px;
  border-radius: 8px;
  background: #1E293B;
  border: 1px solid #334155;
  color: #94A3B8;
  line-height: 1.4;
}}
.pa-step {{
  display: flex;
  gap: 14px;
  padding: 12px 0;
  border-bottom: 1px solid {BORDER};
}}
.pa-step:last-child {{
  border-bottom: none;
}}
.pa-dot {{
  width: 12px;
  height: 12px;
  border-radius: 50%;
  margin-top: 5px;
  flex: 0 0 12px;
  background: var(--tone);
}}
.pa-step .a {{
  font-weight: 700;
  font-size: 0.95rem;
  color: {TEXT};
}}
.pa-step .m {{
  color: {MUTED};
  font-size: 0.8rem;
  margin-top: 2px;
}}
.pa-stepper {{
  display: flex;
  gap: 0;
  margin: 10px 0 8px 0;
  flex-wrap: wrap;
}}
.pa-stepper div {{
  flex: 1;
  min-width: 110px;
  text-align: center;
  font-size: 0.74rem;
  font-weight: 700;
  padding: 8px 6px;
  border: 1px solid {BORDER};
  background: {SURFACE};
  color: {MUTED};
}}
.pa-stepper div:first-child {{
  border-radius: 8px 0 0 8px;
}}
.pa-stepper div:last-child {{
  border-radius: 0 8px 8px 0;
}}
.pa-stepper div.done {{
  background: #CCFBF1;
  color: #0F766E;
  border-color: #99F6E4;
}}
.pa-stepper div.now {{
  background: {PRIMARY};
  color: #FFFFFF;
  border-color: {PRIMARY};
}}
.pa-stepper div.bad {{
  background: #FEE2E2;
  color: {RED};
  border-color: {RED};
}}
.pa-empty {{
  text-align: center;
  padding: 38px 24px;
  color: {MUTED};
  background: {SURFACE};
  border: 1px dashed {BORDER};
  border-radius: 12px;
  font-size: 0.92rem;
}}
.pa-blocked {{
  border-left: 4px solid {RED};
  background: #FEF2F2;
  padding: 12px 16px;
  border-radius: 8px;
  color: {RED};
  font-weight: 600;
}}
.pa-kv {{
  display: grid;
  grid-template-columns: 160px 1fr;
  gap: 6px 14px;
  font-size: 0.9rem;
}}
.pa-kv .k {{
  color: {MUTED};
  font-weight: 500;
}}
div[data-testid="stMetric"] {{
  background: {SURFACE};
  border: 1px solid {BORDER};
  border-radius: 12px;
  padding: 14px 18px;
  box-shadow: 0 1px 3px 0 rgba(0,0,0,0.02);
}}
.pa-product-card {{
  background: #FFFFFF;
  border: 1px solid #E2E8F0;
  border-radius: 14px;
  padding: 18px 20px;
  margin-bottom: 14px;
  box-shadow: 0 1px 3px 0 rgba(0,0,0,0.04);
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}}
.pa-product-card:hover {{
  border-color: #CBD5E1;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}}
.pa-badge {{
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 10px;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 700;
  line-height: 1.3;
}}
.pa-badge.critical {{
  background: #FEF2F2;
  color: #DC2626;
  border: 1px solid #FCA5A5;
}}
.pa-badge.low {{
  background: #FFFBEB;
  color: #D97706;
  border: 1px solid #FDE68A;
}}
.pa-badge.healthy {{
  background: #F0FDF4;
  color: #16A34A;
  border: 1px solid #BBF7D0;
}}
.pa-badge.expiry {{
  background: #FFF7ED;
  color: #EA580C;
  border: 1px solid #FFEDD5;
}}
.pa-stat-box {{
  background: #F8FAFC;
  border: 1px solid #E2E8F0;
  border-radius: 10px;
  padding: 10px 14px;
  text-align: center;
}}
.pa-stat-box .label {{
  font-size: 0.72rem;
  color: #64748B;
  text-transform: uppercase;
  font-weight: 700;
  letter-spacing: 0.05em;
}}
.pa-stat-box .val {{
  font-size: 1.15rem;
  font-weight: 800;
  color: #0F172A;
  margin-top: 2px;
}}
.stTabs [data-baseweb="tab-list"] {{
  gap: 8px;
  border-bottom: 2px solid {BORDER};
}}
.stTabs [data-baseweb="tab"] {{
  background: transparent;
  border-radius: 8px 8px 0 0;
  padding: 8px 16px;
  font-weight: 600;
  color: {MUTED};
}}
.stTabs [aria-selected="true"] {{
  color: {PRIMARY} !important;
  border-bottom: 3px solid {PRIMARY} !important;
}}
</style>
"""



def inject():
    st.markdown(CSS, unsafe_allow_html=True)


def esc(x) -> str:
    return html.escape(str(x))


def header(eyebrow: str, title: str, subtitle: str = ""):
    st.markdown(f'<div class="pa-eyebrow">{esc(eyebrow)}</div><div class="pa-title">{esc(title)}</div>'
                + (f'<div class="pa-sub">{esc(subtitle)}</div>' if subtitle else ""), unsafe_allow_html=True)


def pill(text: str, tone: str = "") -> str:
    fg, bg = TONES.get(tone or STATUS_TONE.get(text, "muted"), TONES["muted"])
    return f'<span class="pa-pill" style="--fg:{fg};--bgc:{bg}">{esc(text)}</span>'


def kpi(label: str, value, sub: str = "", tone: str = "primary"):
    color = TONES.get(tone, TONES["primary"])[0]
    st.markdown(f'<div class="pa-kpi" style="--tone:{color}"><div class="l">{esc(label)}</div>'
                f'<div class="v">{esc(value)}</div><div class="s">{esc(sub)}</div></div>', unsafe_allow_html=True)


def empty(msg: str):
    st.markdown(f'<div class="pa-empty">{esc(msg)}</div>', unsafe_allow_html=True)


def blocked(msg: str):
    st.markdown(f'<div class="pa-blocked">{esc(msg)}</div>', unsafe_allow_html=True)


def stepper(states: list, current: str, failed: bool = False):
    idx = states.index(current) if current in states else -1
    parts = []
    for i, s in enumerate(states):
        cls = "now" if i == idx else "done" if i < idx else ""
        if failed and i == idx:
            cls = "bad"
        parts.append(f'<div class="{cls}">{esc(s.replace("_", " "))}</div>')
    st.markdown(f'<div class="pa-stepper">{"".join(parts)}</div>', unsafe_allow_html=True)


def kv(rows: list):
    inner = "".join(f'<div class="k">{esc(k)}</div><div>{v}</div>' for k, v in rows)
    st.markdown(f'<div class="pa-kv">{inner}</div>', unsafe_allow_html=True)


def money(v) -> str:
    return "-" if v is None else f"{v:,.2f}"


def flow_banner(title: str, subtitle: str, steps: list[tuple[str, str, str]]):
    """Render a clean 3-step workflow banner with numbers, titles, and explanations."""
    step_html = "".join(
        f'<div class="pa-flow-step"><span class="num">{esc(num)}</span>'
        f'<span class="title">{esc(h)}</span><div class="desc">{esc(d)}</div></div>'
        for num, h, d in steps
    )
    st.markdown(
        f'<div class="pa-banner"><h3>{esc(title)}</h3><p>{esc(subtitle)}</p>'
        f'<div class="pa-flow-steps">{step_html}</div></div>',
        unsafe_allow_html=True,
    )


def callout(text: str, kind: str = "info"):
    """Render a clean callout box (info, tip, or success)."""
    cls = "pa-callout"
    if kind == "tip":
        cls += " tip"
    elif kind == "success":
        cls += " success"
    st.markdown(f'<div class="{cls}">{text}</div>', unsafe_allow_html=True)
