"""Visual system for the Streamlit UI: palette, CSS and small HTML components."""
from __future__ import annotations

import html

import streamlit as st

PRIMARY = "#0F5C63"
PRIMARY_DARK = "#0A4247"
PRIMARY_SOFT = "#E3EFF0"
BG = "#F5F8F9"
SURFACE = "#FFFFFF"
BORDER = "#DCE5E7"
TEXT = "#1E2B2E"
MUTED = "#5F7276"
AMBER = "#E8A33D"
RED = "#B5483F"
GREEN = "#3C8D5A"
GREY = "#7A8B8F"

TONES = {"primary": (PRIMARY, PRIMARY_SOFT), "warn": (AMBER, "#FBF1E0"), "bad": (RED, "#F6E4E2"),
         "good": (GREEN, "#E3F1E8"), "muted": (GREY, "#EEF2F3")}

STATUS_TONE = {"DRAFT": "muted", "VALIDATED": "primary", "PENDING_APPROVAL": "warn", "APPROVED": "good",
               "CREATED": "good", "RECEIVED": "good", "REJECTED": "bad", "CANCELLED": "bad",
               "pending_approval": "warn", "created": "good", "escalated": "bad", "rejected": "bad",
               "no_action": "muted", "failed": "bad", "high": "bad", "medium": "warn", "low": "muted"}

CSS = f"""
<style>
:root {{ --primary:{PRIMARY}; --bg:{BG}; --border:{BORDER}; --text:{TEXT}; --muted:{MUTED}; }}
html, body, [class*="css"] {{ font-family: "Inter", "Segoe UI", system-ui, -apple-system, sans-serif; }}
.stApp {{ background:{BG}; color:{TEXT}; }}
section[data-testid="stSidebar"] {{ background:{PRIMARY_DARK}; }}
section[data-testid="stSidebar"] * {{ color:#E6F0F1 !important; }}
section[data-testid="stSidebar"] [data-baseweb="select"] * {{ color:{TEXT} !important; }}
section[data-testid="stSidebar"] .stButton button {{ background:{PRIMARY}; border:1px solid #2A7A81; color:#fff !important; }}
section[data-testid="stSidebar"] .stButton button:hover {{ background:#13707A; border-color:#5FA7AD; }}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"] {{ border-radius:6px; }}
section[data-testid="stSidebar"] a[data-testid="stSidebarNavLink"][aria-current="page"] {{ background:#13707A; }}
.block-container {{ padding-top:1.6rem; padding-bottom:3rem; max-width:1400px; }}
h1, h2, h3 {{ color:{TEXT}; letter-spacing:-0.01em; }}
.pa-eyebrow {{ text-transform:uppercase; font-size:.72rem; letter-spacing:.09em; color:{PRIMARY}; font-weight:700; }}
.pa-title {{ font-size:1.7rem; font-weight:700; margin:.1rem 0 .2rem 0; color:{TEXT}; }}
.pa-sub {{ color:{MUTED}; font-size:.93rem; margin-bottom:1.1rem; max-width:70rem; }}
.pa-card {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; padding:16px 18px; margin-bottom:12px; }}
.pa-banner {{ background:linear-gradient(135deg, #F0F7F7 0%, #FFFFFF 100%); border:1px solid #C8DFE1;
              border-radius:12px; padding:20px 24px; margin-bottom:20px; box-shadow:0 2px 6px rgba(15,92,99,0.04); }}
.pa-banner h3 {{ margin:0 0 6px 0; color:{PRIMARY_DARK}; font-size:1.25rem; font-weight:700; }}
.pa-banner p {{ margin:0 0 14px 0; color:{MUTED}; font-size:0.92rem; line-height:1.5; }}
.pa-flow-steps {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(240px, 1fr)); gap:12px; margin-top:14px; }}
.pa-flow-step {{ background:#FFFFFF; border:1px solid {BORDER}; border-radius:8px; padding:12px 14px;
                 box-shadow:0 1px 3px rgba(0,0,0,0.03); }}
.pa-flow-step .num {{ display:inline-block; width:22px; height:22px; line-height:22px; text-align:center;
                      background:{PRIMARY}; color:#fff; border-radius:50%; font-size:0.75rem; font-weight:700;
                      margin-right:6px; }}
.pa-flow-step .title {{ font-weight:700; font-size:0.88rem; color:{TEXT}; }}
.pa-flow-step .desc {{ font-size:0.79rem; color:{MUTED}; margin-top:4px; line-height:1.4; }}
.pa-callout {{ background:#EBF4F5; border-left:4px solid {PRIMARY}; border-radius:0 8px 8px 0; padding:12px 16px;
               margin:12px 0; font-size:0.88rem; color:{TEXT}; }}
.pa-callout.tip {{ background:#FFF9E6; border-left-color:{AMBER}; }}
.pa-callout.success {{ background:#EAF5ED; border-left-color:{GREEN}; }}
.pa-kpi {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; padding:14px 16px; height:100%;
          border-top:3px solid var(--tone); box-shadow:0 2px 4px rgba(0,0,0,0.02); }}
.pa-kpi .l {{ color:{MUTED}; font-size:.78rem; font-weight:600; text-transform:uppercase; letter-spacing:.05em; }}
.pa-kpi .v {{ font-size:1.65rem; font-weight:700; color:{TEXT}; margin-top:4px; }}
.pa-kpi .s {{ color:{MUTED}; font-size:.8rem; margin-top:2px; }}
.pa-pill {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:.74rem; font-weight:600;
           color:var(--fg); background:var(--bgc); border:1px solid var(--fg); white-space:nowrap; }}
.pa-mode {{ font-size:.75rem; padding:6px 10px; border-radius:6px; background:#0B4D53; border:1px solid #2A7A81; }}
.pa-step {{ display:flex; gap:12px; padding:10px 0; border-bottom:1px solid {BORDER}; }}
.pa-step:last-child {{ border-bottom:none; }}
.pa-dot {{ width:12px; height:12px; border-radius:50%; margin-top:5px; flex:0 0 12px; background:var(--tone); }}
.pa-step .a {{ font-weight:700; color:{TEXT}; }}
.pa-step .m {{ color:{MUTED}; font-size:.8rem; }}
.pa-stepper {{ display:flex; gap:0; margin:6px 0 4px 0; flex-wrap:wrap; }}
.pa-stepper div {{ flex:1; min-width:110px; text-align:center; font-size:.72rem; font-weight:600; padding:7px 4px;
                   border:1px solid {BORDER}; background:{SURFACE}; color:{MUTED}; }}
.pa-stepper div.done {{ background:{PRIMARY_SOFT}; color:{PRIMARY}; border-color:#B7D3D6; }}
.pa-stepper div.now {{ background:{PRIMARY}; color:#fff; border-color:{PRIMARY}; }}
.pa-stepper div.bad {{ background:#F6E4E2; color:{RED}; border-color:{RED}; }}
.pa-empty {{ text-align:center; padding:34px; color:{MUTED}; background:{SURFACE}; border:1px dashed {BORDER};
            border-radius:10px; }}
.pa-blocked {{ border-left:4px solid {RED}; background:#F6E4E2; padding:10px 14px; border-radius:6px; color:{RED};
              font-weight:600; }}
.pa-kv {{ display:grid; grid-template-columns: 150px 1fr; gap:4px 12px; font-size:.9rem; }}
.pa-kv .k {{ color:{MUTED}; }}
div[data-testid="stMetric"] {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:10px; padding:10px 14px; }}
.stTabs [data-baseweb="tab-list"] {{ gap:4px; }}
.stTabs [data-baseweb="tab"] {{ background:{SURFACE}; border:1px solid {BORDER}; border-radius:6px 6px 0 0; }}
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
