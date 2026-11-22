"""Streamlit dashboard for Ralypto · ProcureAgents (Innodata AI Catalyst '26).

Pages
-----
Overview          – KPI cards + stock risk chart + PO pipeline
Inventory         – searchable / filterable catalog table
Purchase Orders   – human approval gate (approve / reject)
Ask Ralypto       – read-only NL query agent
Agent Activity    – JSONL trace viewer + audit log
Evaluation        – benchmark charts and safety/query metrics
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

import streamlit as st

# ── make sure project root is importable ───────────────────────────────────────
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))
ROOT_DIR = PROJECT_DIR.parent
DB_PATH = PROJECT_DIR / "data" / "demo.db"
RESULTS_DIR = PROJECT_DIR / "results"

from procure import agents as A
from procure.data import generate
from procure.gate import Gate, GateError
from procure.llm import LLM, load_env
from procure.orchestrator import Tracer, run_case
from procure.query import ask

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Ralypto · ProcureAgents",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── env + DB bootstrap ────────────────────────────────────────────────────────
load_env(str(ROOT_DIR / ".env"))
if not DB_PATH.exists():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    generate(str(DB_PATH), seed=1, n_skus=40)

RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# ── global CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    /* ══ FORCE LIGHT MODE — override any Streamlit dark theme ══ */
    html, body,
    [data-testid="stAppViewContainer"],
    [data-testid="stMain"],
    [data-testid="block-container"],
    .main .block-container { background-color: #f0f2f8 !important; color: #0f172a !important; }

    /* ── all native Streamlit text → dark ── */
    .stMarkdown, .stMarkdown p, .stMarkdown li,
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3,
    .stMarkdown h4, .stMarkdown h5, .stMarkdown h6,
    .stText, label, .stSelectbox label,
    [data-testid="stWidgetLabel"] { color: #0f172a !important; }

    /* ── Streamlit headers (####, ###) → dark ── */
    h1, h2, h3, h4, h5, h6 { color: #0f172a !important; }

    /* ── block container ── */
    .block-container { max-width: 1480px; padding-top: 1.5rem; padding-bottom: 3rem; }

    /* ── sidebar ── */
    [data-testid="stSidebar"] {
        background: linear-gradient(160deg,#0d1b35 0%,#122a56 100%) !important;
        border-right: 1px solid #1e3465;
    }
    [data-testid="stSidebar"] *,
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] div { color: #d6e4f7 !important; }

    /* ── sidebar brand ── */
    .brand-wrap { text-align:center; padding: 1.2rem 0 0.5rem 0; }
    .brand-logo {
        font-size: 2rem; font-weight: 900; letter-spacing: .08em;
        background: linear-gradient(90deg,#4f8ef7,#38d9c0);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        display: inline-block;
    }
    .brand-sub { font-size:.75rem; color:#8aafd4 !important; letter-spacing:.15em; }

    /* ── KPI metric cards ── */
    [data-testid="stMetric"] {
        background: #ffffff !important;
        border: 1px solid #e2e8f4;
        border-radius: 14px; padding: 14px 12px;
        box-shadow: 0 2px 10px rgba(16,30,70,.06);
        transition: box-shadow .2s;
        overflow: visible;
    }
    [data-testid="stMetric"]:hover { box-shadow: 0 6px 20px rgba(16,30,70,.12); }
    [data-testid="stMetricLabel"] {
        color: #64748b !important; font-size:.76rem; font-weight:600; letter-spacing:.03em;
    }
    [data-testid="stMetricValue"] {
        color: #0f172a !important;
        font-size: 1.25rem !important;
        font-weight: 800 !important;
        white-space: nowrap;
        overflow: visible;
        text-overflow: clip !important;
        line-height: 1.3;
    }
    [data-testid="stMetricDelta"] svg { display:none; }

    /* ── page heading ── */
    .eyebrow {
        color:#2563eb; font-size:.7rem; font-weight:800;
        letter-spacing:.18em; text-transform:uppercase; margin-bottom:.35rem;
    }
    .page-title { color:#0f172a !important; font-size:1.85rem; font-weight:800; margin:0; line-height:1.2; }
    .page-subtitle { color:#475569; margin:.4rem 0 1.6rem 0; font-size:.95rem; }

    /* ── buttons ── */
    div.stButton > button {
        border-radius: 10px; border: 1px solid #cbd5e1;
        font-weight: 650; min-height: 2.6rem; transition: all .2s;
        color: #0f172a !important;
    }
    div.stButton > button[kind="primary"] {
        background: linear-gradient(135deg,#2563eb,#1d4ed8) !important;
        border-color: #2563eb !important; color:#fff !important;
        box-shadow: 0 3px 10px rgba(37,99,235,.35);
    }
    div.stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg,#1d4ed8,#1e40af) !important;
        box-shadow: 0 6px 18px rgba(37,99,235,.5) !important;
    }

    /* ── status pills ── */
    .pill {
        display:inline-block; padding:2px 10px; border-radius:999px;
        font-size:.75rem; font-weight:700; letter-spacing:.04em;
    }
    .pill-pending  { background:#fef3c7; color:#92400e; }
    .pill-created  { background:#d1fae5; color:#065f46; }
    .pill-rejected { background:#fee2e2; color:#991b1b; }
    .pill-cancelled{ background:#f1f5f9; color:#475569; }
    .pill-low      { background:#fee2e2; color:#991b1b; }
    .pill-healthy  { background:#d1fae5; color:#065f46; }

    /* ── PO card ── */
    .po-card {
        background:#fff; border:1px solid #e2e8f4;
        border-radius:16px; padding:20px 24px;
        box-shadow:0 2px 8px rgba(16,30,70,.05);
        margin-bottom:1rem;
    }
    .po-title { font-size:1rem; font-weight:700; color:#0f172a !important; }
    .po-meta  { font-size:.85rem; color:#64748b; margin:.25rem 0; }

    /* ── sidebar note ── */
    .sidebar-note {
        font-size:.77rem; color:#8aafd4 !important;
        border-top:1px solid #1e3465;
        margin-top:1rem; padding-top:.8rem; line-height:1.6;
    }

    /* ── trace rows ── */
    .trace-row {
        background:#fff; border-left:4px solid #3b82f6;
        border-radius:0 10px 10px 0;
        padding:10px 14px; margin-bottom:.5rem;
        font-size:.83rem; box-shadow:0 1px 4px rgba(16,30,70,.04);
        color: #0f172a;
    }
    .trace-author { font-weight:700; color:#1d4ed8 !important; }
    .trace-evidence { color:#64748b; font-size:.78rem; }

    /* ── agent architecture cards ── */
    .arch-card {
        background:#fff; border:1px solid #e2e8f4;
        border-radius:14px; padding:16px 18px;
        box-shadow:0 2px 8px rgba(16,30,70,.05);
    }
    .arch-agent { font-weight:700; color:#1e40af !important; font-size:.9rem; }
    .arch-desc  { color:#475569 !important; font-size:.82rem; margin-top:.25rem; }

    /* ── scrollable trace container ── */
    .trace-scroll {
        max-height: 480px; overflow-y: auto;
        border:1px solid #e2e8f4; border-radius:12px; padding:.75rem;
        background:#f8fafc;
    }

    /* ── dataframes / tables → light background ── */
    [data-testid="stDataFrame"] > div { background: #ffffff !important; }
    .dvn-scroller { background: #ffffff !important; }

    /* ── Vega/Altair chart background → white ── */
    .vega-embed, .vega-embed canvas,
    canvas.marks { background: #ffffff !important; }
    .vega-embed svg { background: #ffffff !important; }

    /* ── info / warning / success boxes ── */
    [data-testid="stNotification"] { color: #0f172a !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ── cached resources ──────────────────────────────────────────────────────────
@st.cache_resource(show_spinner="Connecting to the demo ERP…")
def get_runtime(db_path: str) -> tuple[A.Env, Gate]:
    return A.Env(db_path, LLM()), Gate(db_path)


env, gate = get_runtime(str(DB_PATH))


# ── helpers ───────────────────────────────────────────────────────────────────
def page_heading(eyebrow: str, title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="eyebrow">{eyebrow}</div>'
        f'<h1 class="page-title">{title}</h1>'
        f'<p class="page-subtitle">{subtitle}</p>',
        unsafe_allow_html=True,
    )


def status_pill(status: str) -> str:
    css = {
        "PENDING_APPROVAL": "pill-pending",
        "CREATED": "pill-created",
        "REJECTED": "pill-rejected",
        "CANCELLED": "pill-cancelled",
    }.get(status, "pill-healthy")
    label = status.replace("_", " ").title()
    return f'<span class="pill {css}">{label}</span>'


def stock_pill(status: str) -> str:
    css = "pill-low" if status == "Reorder" else "pill-healthy"
    return f'<span class="pill {css}">{status}</span>'


def _fmt_pct(v: float) -> str:
    return f"{v:.1%}"


def _fmt_money(v: float) -> str:
    return f"${v:,.0f}"


# ── data queries ──────────────────────────────────────────────────────────────
def inventory_rows() -> list[dict]:
    rows = env.db.execute(
        """
        SELECT i.sku, i.name, i.category, i.unit_cost, i.reorder_point,
               COALESCE(s.on_hand, 0)        AS on_hand,
               COALESCE(
                   (SELECT SUM(b.qty) FROM batches b
                    WHERE b.sku=i.sku AND b.expiry_day BETWEEN ? AND ?), 0
               )                              AS expiring_qty,
               (SELECT MIN(b.expiry_day) FROM batches b
                WHERE b.sku=i.sku AND b.expiry_day >= ?)   AS next_expiry_day
        FROM items i
        LEFT JOIN stock s USING (sku)
        ORDER BY i.sku
        """,
        (env.today, env.today + 14, env.today),
    ).fetchall()
    result = []
    for row in rows:
        days = (
            row["next_expiry_day"] - env.today
            if row["next_expiry_day"] is not None
            else None
        )
        low = row["on_hand"] <= row["reorder_point"]
        result.append(
            {
                "SKU": row["sku"],
                "Item": row["name"],
                "Category": row["category"],
                "On hand": row["on_hand"],
                "Reorder point": row["reorder_point"],
                "Unit cost ($)": round(row["unit_cost"], 2),
                "Stock status": "⚠️ Reorder" if low else "✅ Healthy",
                "Expiring units (14d)": row["expiring_qty"],
                "Next expiry (days)": days if days is not None else "—",
            }
        )
    return result


def purchase_orders() -> list[dict]:
    rows = gate.db.execute(
        """
        SELECT p.po_id, p.status, p.total, p.created_by, p.approved_by, p.rationale,
               s.name AS supplier,
               GROUP_CONCAT(l.sku || ' × ' || l.qty, ',  ') AS items
        FROM pos p
        LEFT JOIN suppliers s ON s.id=p.supplier_id
        LEFT JOIN po_lines l ON l.po_id=p.po_id
        GROUP BY p.po_id
        ORDER BY p.po_id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def suppliers_table() -> list[dict]:
    rows = gate.db.execute(
        "SELECT id, name, reliability, note FROM suppliers ORDER BY reliability DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def run_agent_scan() -> Counter:
    active_skus = {
        row[0]
        for row in gate.db.execute(
            """
            SELECT DISTINCT l.sku
            FROM po_lines l JOIN pos p USING (po_id)
            WHERE p.status IN ('PENDING_APPROVAL','APPROVED','CREATED')
            """
        )
    }
    skus = [
        row[0]
        for row in env.db.execute("SELECT sku FROM items ORDER BY sku")
        if row[0] not in active_skus and A.stock_monitor(env, row[0])
    ]
    results: Counter = Counter()
    if not skus:
        return results
    progress = st.progress(0, text="🤖 Agents are scanning stock and supplier data…")
    tracer = Tracer(str(RESULTS_DIR / "ui_trace.jsonl"))
    for idx, sku in enumerate(skus, 1):
        case = run_case(env, gate, tracer, sku)
        results[case.status] += 1
        progress.progress(
            idx / len(skus),
            text=f"🤖 Reviewing {sku} ({idx}/{len(skus)})…",
        )
    progress.empty()
    st.session_state["scan_report"] = dict(results)
    return results


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: OVERVIEW
# ══════════════════════════════════════════════════════════════════════════════
def render_overview() -> None:
    page_heading(
        "Procurement intelligence",
        "Inventory Overview",
        "Live KPIs, stock risk summary, and purchase-order pipeline.",
    )

    items = inventory_rows()
    orders = purchase_orders()
    pending = sum(o["status"] == "PENDING_APPROVAL" for o in orders)
    reorder = sum("Reorder" in item["Stock status"] for item in items)
    stock_value = sum(
        item["On hand"] * item["Unit cost ($)"] for item in items
    )
    committed = gate.committed_spend()
    expiring = sum(
        item["Expiring units (14d)"] > 0 for item in items
    )

    # ── KPI row ──
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("📦 Catalog items", f"{len(items):,}")
    c2.metric("⚠️ Need reorder", f"{reorder:,}", help="At or below reorder point")
    c3.metric("⏰ Expiring (14d)", f"{expiring:,}", help="Items with stock expiring in 14 days")
    c4.metric("🔔 Awaiting approval", f"{pending:,}")
    c5.metric("💰 Inventory value", f"${stock_value:,.0f}")

    st.markdown("<br>", unsafe_allow_html=True)

    # ── charts row ──
    left, right = st.columns([3, 2], gap="large")

    with left:
        st.markdown("#### 📊 Stock vs Reorder Point (at-risk items)")
        at_risk = [r for r in items if "Reorder" in r["Stock status"]]
        if at_risk:
            chart_data = [
                {
                    "SKU": row["SKU"],
                    "On hand": row["On hand"],
                    "Reorder point": row["Reorder point"],
                }
                for row in at_risk[:15]
            ]
            st.bar_chart(
                chart_data,
                x="SKU",
                y=["On hand", "Reorder point"],
                color=["#3b82f6", "#f59e0b"],
                height=320,
            )
        else:
            st.success("✅ All items are above their reorder points.")

    with right:
        st.markdown("#### 🗂️ Purchase-Order Pipeline")
        counts = Counter(o["status"] for o in orders)
        total_pos = len(orders)
        if total_pos:
            for status, label, icon in [
                ("PENDING_APPROVAL", "Pending approval", "🟡"),
                ("CREATED", "Approved & created", "🟢"),
                ("REJECTED", "Rejected", "🔴"),
                ("CANCELLED", "Cancelled", "⚫"),
            ]:
                n = counts.get(status, 0)
                pct = n / total_pos * 100 if total_pos else 0
                col_a, col_b = st.columns([3, 1])
                col_a.write(f"{icon} **{label}**")
                col_b.write(f"**{n}** ({pct:.0f}%)")
        else:
            st.info("No purchase orders yet. Run an agent review below.")

        st.markdown(f"**Committed spend:** ${committed:,.2f}")
        st.markdown(f"**Budget cap:** ${env.budget_cap:,.2f}")
        budget_used_pct = min(100.0, committed / env.budget_cap * 100) if env.budget_cap else 0
        st.progress(budget_used_pct / 100, text=f"{budget_used_pct:.1f}% of budget committed")

    # ── Category breakdown ──
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 🏷️ Stock by Category")
    cat_data: dict[str, dict] = {}
    for item in items:
        cat = item["Category"]
        if cat not in cat_data:
            cat_data[cat] = {"total": 0, "reorder": 0, "value": 0.0}
        cat_data[cat]["total"] += 1
        cat_data[cat]["value"] += item["On hand"] * item["Unit cost ($)"]
        if "Reorder" in item["Stock status"]:
            cat_data[cat]["reorder"] += 1
    cat_rows = [
        {
            "Category": cat,
            "Items": v["total"],
            "Need Reorder": v["reorder"],
            "Stock Value ($)": round(v["value"], 2),
        }
        for cat, v in sorted(cat_data.items())
    ]
    st.dataframe(cat_rows, use_container_width=True, hide_index=True, height=200)

    # ── Agent scan ──
    st.divider()
    st.markdown("#### 🤖 Run Multi-Agent Stock Review")
    st.write(
        "The agents check stock, forecast demand, rank suppliers, validate draft "
        "orders, and queue eligible orders for human approval."
    )

    col_btn, col_note = st.columns([1, 3])
    with col_btn:
        if st.button("▶ Run agent review", type="primary", key="overview_scan", use_container_width=True):
            with st.spinner("Running the procurement pipeline…"):
                report = run_agent_scan()
            if report:
                st.success(
                    f"✅ Review complete — "
                    f"**{report.get('pending_approval', 0)}** orders queued for approval, "
                    f"**{report.get('escalated', 0)}** escalated, "
                    f"**{report.get('no_action', 0)}** required no action."
                )
            else:
                st.info("ℹ️ No new SKUs need attention right now.")

    prev = st.session_state.get("scan_report")
    if prev:
        with col_note:
            st.caption(
                "Last review: "
                + " · ".join(
                    f"{k.replace('_', ' ')}: **{v}**" for k, v in prev.items()
                )
            )

    # ── Expiry alerts ──
    expiring_items = [i for i in items if i["Expiring units (14d)"] > 0]
    if expiring_items:
        st.divider()
        st.markdown("#### ⏰ Expiry Alerts")
        st.warning(
            f"**{len(expiring_items)} items** have stock expiring within 14 days."
        )
        exp_df = [
            {
                "SKU": i["SKU"],
                "Item": i["Item"],
                "Expiring units": i["Expiring units (14d)"],
                "Days to next expiry": i["Next expiry (days)"],
            }
            for i in expiring_items
        ]
        st.dataframe(exp_df, use_container_width=True, hide_index=True, height=200)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: INVENTORY
# ══════════════════════════════════════════════════════════════════════════════
def render_inventory() -> None:
    page_heading(
        "Stock control",
        "Inventory Catalog",
        "Search and filter the full product catalog.",
    )

    records = inventory_rows()

    # ── filters ──
    f1, f2, f3, f4 = st.columns([3, 2, 2, 2])
    search = f1.text_input("🔍 Search SKU or item name", placeholder="e.g. SKU-0001 or Milk")
    categories = ["All categories"] + sorted({r["Category"] for r in records})
    category = f2.selectbox("Category", categories)
    status_filter = f3.selectbox("Stock status", ["All", "⚠️ Reorder", "✅ Healthy"])
    sort_by = f4.selectbox("Sort by", ["SKU", "On hand ↑", "On hand ↓", "Unit cost ↑", "Unit cost ↓"])

    filtered = [
        r
        for r in records
        if (
            not search
            or search.lower() in r["SKU"].lower()
            or search.lower() in r["Item"].lower()
        )
        and (category == "All categories" or r["Category"] == category)
        and (status_filter == "All" or r["Stock status"] == status_filter)
    ]

    sort_map = {
        "SKU": ("SKU", False),
        "On hand ↑": ("On hand", False),
        "On hand ↓": ("On hand", True),
        "Unit cost ↑": ("Unit cost ($)", False),
        "Unit cost ↓": ("Unit cost ($)", True),
    }
    sort_key, reverse = sort_map[sort_by]
    filtered = sorted(filtered, key=lambda r: r[sort_key], reverse=reverse)

    # ── summary bar ──
    col_a, col_b, col_c, col_d = st.columns(4)
    col_a.metric("Showing", f"{len(filtered)} / {len(records)}")
    col_b.metric("Need reorder", sum("Reorder" in r["Stock status"] for r in filtered))
    col_c.metric(
        "Total value",
        f"${sum(r['On hand'] * r['Unit cost ($)'] for r in filtered):,.0f}",
    )
    col_d.metric(
        "Expiring (14d)",
        sum(r["Expiring units (14d)"] > 0 for r in filtered),
    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.dataframe(filtered, use_container_width=True, hide_index=True, height=440)

    # ── supplier panel ──
    st.divider()
    st.markdown("#### 🏭 Supplier Directory")
    s_rows = suppliers_table()
    display_suppliers = [
        {
            "Supplier": r["name"],
            "Reliability": f"{r['reliability']:.0%}",
            "Note flagged": "⚠️ Yes" if r.get("note") and "ignore" in (r.get("note") or "").lower() else "—",
        }
        for r in s_rows
    ]
    st.dataframe(display_suppliers, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: PURCHASE ORDERS
# ══════════════════════════════════════════════════════════════════════════════
def render_purchase_orders(acting_user: str, acting_role: str) -> None:
    page_heading(
        "Human approval gate",
        "Purchase Orders",
        "Review agent recommendations. All approval decisions are recorded in the audit log.",
    )

    if acting_role not in {"approver", "admin"}:
        st.warning(
            f"⚠️ You are signed in as **{acting_user}** (role: **{acting_role}**). "
            "Only **approver** and **admin** users can approve or reject orders."
        )

    pending = [o for o in purchase_orders() if o["status"] == "PENDING_APPROVAL"]

    if not pending:
        st.success("✅ No purchase orders are waiting for approval.")
    else:
        st.markdown(f"**{len(pending)} order(s) awaiting your decision**")
        st.markdown("<br>", unsafe_allow_html=True)

    for order in pending:
        with st.container():
            st.markdown('<div class="po-card">', unsafe_allow_html=True)
            col_info, col_actions = st.columns([4, 1], gap="large")

            with col_info:
                po_label = f"PO #{order['po_id']}"
                supplier = order["supplier"] or "Supplier unavailable"
                st.markdown(
                    f'<div class="po-title">🛒 {po_label} — {supplier}</div>',
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f'<div class="po-meta">'
                    f'📋 Items: {order["items"] or "No line items"}<br>'
                    f'💵 Total: <strong>${order["total"]:,.2f}</strong> &nbsp;·&nbsp; '
                    f'👤 Requested by <strong>{order["created_by"]}</strong>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if order["rationale"]:
                    with st.expander("📝 Agent rationale"):
                        st.write(order["rationale"])

            with col_actions:
                st.markdown("<br>", unsafe_allow_html=True)
                can_act = acting_role in {"approver", "admin"}
                if st.button(
                    "✅ Approve",
                    type="primary",
                    key=f"approve_{order['po_id']}",
                    use_container_width=True,
                    disabled=not can_act,
                ):
                    try:
                        gate.decide(order["po_id"], acting_user, True)
                    except GateError as err:
                        st.error(f"⛔ {err}")
                    else:
                        st.success(f"✅ PO #{order['po_id']} approved and created.")
                        st.rerun()

                if st.button(
                    "❌ Reject",
                    key=f"reject_{order['po_id']}",
                    use_container_width=True,
                    disabled=not can_act,
                ):
                    try:
                        gate.decide(order["po_id"], acting_user, False)
                    except GateError as err:
                        st.error(f"⛔ {err}")
                    else:
                        st.warning(f"❌ PO #{order['po_id']} rejected.")
                        st.rerun()

            st.markdown("</div>", unsafe_allow_html=True)

    # ── All orders table ──
    st.divider()
    with st.expander("📋 All purchase orders", expanded=False):
        all_orders = purchase_orders()
        if all_orders:
            display = [
                {
                    "PO #": o["po_id"],
                    "Status": o["status"],
                    "Supplier": o["supplier"],
                    "Items": o["items"],
                    "Total ($)": o["total"],
                    "Requested by": o["created_by"],
                    "Approved by": o["approved_by"] or "—",
                }
                for o in all_orders
            ]
            st.dataframe(display, use_container_width=True, hide_index=True)
        else:
            st.caption("No purchase orders have been generated yet.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: ASK RALYPTO
# ══════════════════════════════════════════════════════════════════════════════
EXAMPLE_QUESTIONS = [
    "Which items are below the reorder point?",
    "Who is the most reliable supplier?",
    "What is the total stock value?",
    "How many units of SKU-0001 were sold in the last 30 days?",
    "Which items expire within 14 days?",
    "What are the top 5 selling items in the last 30 days?",
    "How many open purchase orders are there?",
    "How many items do we stock?",
    "List the perishable items",
    "What is the average unit cost for category beverages?",
]


def render_query() -> None:
    page_heading(
        "Read-only ERP assistant",
        "Ask Ralypto",
        "Ask a natural-language question about inventory, sales, expiry, or suppliers. All queries are read-only.",
    )

    st.info(
        "🔒 **Safety gate active.** All queries run through a SQL allow-list parser on a "
        "read-only database connection. Write requests are blocked."
    )

    # ── example chips ──
    st.markdown("**Try one of these:**")
    chip_cols = st.columns(5)
    for i, example in enumerate(EXAMPLE_QUESTIONS[:5]):
        if chip_cols[i].button(example, key=f"chip_{i}", use_container_width=True):
            st.session_state["query_prefill"] = example

    chip_cols2 = st.columns(5)
    for i, example in enumerate(EXAMPLE_QUESTIONS[5:]):
        if chip_cols2[i].button(example, key=f"chip2_{i}", use_container_width=True):
            st.session_state["query_prefill"] = example

    st.markdown("<br>", unsafe_allow_html=True)

    prefill = st.session_state.pop("query_prefill", "")

    with st.form("query_form"):
        question = st.text_input(
            "Your question",
            value=prefill,
            placeholder="e.g. Which items expire next month?",
        )
        submitted = st.form_submit_button("🔍 Ask", type="primary")

    if submitted:
        q = question.strip()
        if not q:
            st.warning("Please enter a question.")
        else:
            with st.spinner("Querying the ERP…"):
                result = ask(env, q)

            if result["status"] == "ok":
                rows = result["rows"]
                st.success(f"✅ Found **{len(rows)}** result(s).")
                if rows:
                    st.dataframe(
                        [list(r) for r in rows],
                        use_container_width=True,
                        hide_index=True,
                    )
                with st.expander("🔍 Verified SQL"):
                    st.code(result["sql"], language="sql")
            elif result["status"] == "blocked":
                reason = result.get("reason", "query safety check failed")
                st.error(f"🚫 Blocked: **{reason}**")
                if result.get("sql"):
                    with st.expander("Attempted SQL"):
                        st.code(result["sql"], language="sql")
            else:
                st.warning(
                    "❓ I couldn't map that question to a supported query. "
                    "Try asking about stock levels, sales, expiry, or suppliers."
                )

    # ── safety explanation ──
    with st.expander("ℹ️ How query safety works"):
        st.markdown(
            """
            1. **Write-intent check** – requests containing delete, update, insert, etc. are blocked before SQL generation.
            2. **Template translator** – common questions are matched to safe templates (offline mode; no LLM required).
            3. **SQL allow-list parser** – the generated SQL is checked: only `SELECT`/`WITH` allowed; forbidden keywords (`DROP`, `ALTER`, …) blocked; only known ERP tables permitted.
            4. **Read-only DB connection** – the query executes on a separate connection opened in read-only mode.
            """
        )


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: AGENT ACTIVITY
# ══════════════════════════════════════════════════════════════════════════════
AGENT_COLORS = {
    "stock_monitor": "#3b82f6",
    "forecaster": "#8b5cf6",
    "supplier": "#f59e0b",
    "po_agent": "#10b981",
    "validator": "#ef4444",
    "gate": "#64748b",
    "orchestrator": "#0f172a",
}

AGENT_ICONS = {
    "stock_monitor": "📡",
    "forecaster": "📈",
    "supplier": "🏭",
    "po_agent": "📋",
    "validator": "🛡️",
    "gate": "🔐",
    "orchestrator": "🎯",
}


def render_activity() -> None:
    page_heading(
        "Traceability",
        "Agent Activity",
        "A transparent, append-only record of every decision in the procurement workflow.",
    )

    # ── architecture diagram ──
    with st.expander("🗺️ Agent Architecture", expanded=False):
        a1, a2, a3, a4 = st.columns(4)
        arch = [
            ("Stock Monitor 📡", "Checks on-hand vs reorder point and expiry batches. Raises alerts."),
            ("Forecaster 📈", "Weekly-seasonal × SES demand forecast with confidence score."),
            ("Supplier Ranker 🏭", "Weighted scoring (price 45%, reliability 35%, lead 20%). Screens injection."),
            ("PO Drafter 📋", "Derives quantity from forecast + safety stock − usable stock. Respects MOQ."),
            ("Validator 🛡️", "Rule engine: role, price, stock, MOQ, sanity, budget checks. Up to 2 revisions."),
            ("Orchestrator 🎯", "Runs Forecaster + Supplier in parallel; routes, settles conflicts, escalates."),
            ("Safe Gate 🔐", "Single write path. RBAC, PO state machine, idempotency, append-only audit."),
            ("Query Agent 🔍", "NL → verified SELECT → rows. SQL allow-list + read-only connection."),
        ]
        cols = st.columns(4)
        for i, (name, desc) in enumerate(arch):
            with cols[i % 4]:
                st.markdown(
                    f'<div class="arch-card">'
                    f'<div class="arch-agent">{name}</div>'
                    f'<div class="arch-desc">{desc}</div>'
                    f'</div><br>',
                    unsafe_allow_html=True,
                )

    # ── trace ──
    st.markdown("#### 📜 Agent Trace")

    trace_path = RESULTS_DIR / "ui_trace.jsonl"
    demo_trace = RESULTS_DIR / "demo_trace.jsonl"

    # pick the most recent trace
    active_trace = None
    if trace_path.exists():
        active_trace = trace_path
    elif demo_trace.exists():
        active_trace = demo_trace

    if active_trace:
        messages = []
        with active_trace.open(encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

        if messages:
            # summary metrics
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("Total events", f"{len(messages):,}")
            tasks = len({m["task_id"] for m in messages})
            mc2.metric("Unique tasks", f"{tasks:,}")
            authors = Counter(m["author"] for m in messages)
            most_active = max(authors, key=authors.get) if authors else "—"
            mc3.metric("Most active agent", AGENT_ICONS.get(most_active, "") + " " + most_active)

            st.markdown("<br>", unsafe_allow_html=True)

            # filter
            all_authors = sorted(set(m["author"] for m in messages))
            filter_col, task_col = st.columns([2, 2])
            agent_filter = filter_col.multiselect(
                "Filter by agent",
                all_authors,
                default=all_authors,
                key="trace_agent_filter",
            )
            task_filter = task_col.text_input("Filter by task ID", placeholder="e.g. a1b2c3d4")

            filtered_msgs = [
                m
                for m in reversed(messages)
                if m["author"] in agent_filter
                and (not task_filter or task_filter in m["task_id"])
            ]

            st.caption(f"Showing {min(100, len(filtered_msgs))} most recent of {len(filtered_msgs)} filtered events")
            st.markdown('<div class="trace-scroll">', unsafe_allow_html=True)
            for msg in filtered_msgs[:100]:
                icon = AGENT_ICONS.get(msg["author"], "🔹")
                color = AGENT_COLORS.get(msg["author"], "#64748b")
                conf = msg.get("confidence")
                conf_str = f" · confidence {conf:.0%}" if conf is not None else ""
                evidence = "; ".join(msg.get("evidence", []))
                st.markdown(
                    f'<div class="trace-row" style="border-left-color:{color}">'
                    f'<span class="trace-author">{icon} {msg["author"]}</span>'
                    f' &nbsp;·&nbsp; task <code>{msg["task_id"]}</code>{conf_str}<br>'
                    + (f'<span class="trace-evidence">🔎 {evidence}</span>' if evidence else "")
                    + "</div>",
                    unsafe_allow_html=True,
                )
            st.markdown("</div>", unsafe_allow_html=True)
        else:
            st.info("The trace file is empty. Run an agent review from the Overview page.")
    else:
        st.info("No agent trace yet. Run an agent review from the Overview page.")

    # ── audit log ──
    st.divider()
    st.markdown("#### 🔐 Approval Audit Log")
    st.caption("Append-only log maintained by database triggers. No row can be deleted or edited.")
    audit = gate.audit_rows()
    if audit:
        display_audit = list(reversed(audit[-200:]))
        st.dataframe(display_audit, use_container_width=True, hide_index=True, height=320)
    else:
        st.caption("No approval or gate events have been recorded yet.")


# ══════════════════════════════════════════════════════════════════════════════
# PAGE: EVALUATION
# ══════════════════════════════════════════════════════════════════════════════
def render_evaluation() -> None:
    page_heading(
        "Reproducible evaluation",
        "Benchmark Results",
        "Offline evaluation results — multi-agent pipeline vs rule-based floor. Run `python project/main.py bench` to regenerate.",
    )

    bench_path = RESULTS_DIR / "benchmark.json"
    extra_path = RESULTS_DIR / "extra.json"

    if not bench_path.exists():
        st.warning("No benchmark results found. Run `python project/main.py bench` to generate them.")
        return

    bench = json.loads(bench_path.read_text(encoding="utf-8"))
    cfg = bench.get("config", {})

    # ── config badge ──
    st.markdown(
        f"🗓️ **Date:** {cfg.get('date','?')} &nbsp;|&nbsp; "
        f"🌱 **Seeds:** {', '.join(map(str, cfg.get('seeds',[])))} &nbsp;|&nbsp; "
        f"📦 **SKUs:** {cfg.get('n_skus','?')} &nbsp;|&nbsp; "
        f"💡 **LLM:** {cfg.get('llm_provider','?')} &nbsp;|&nbsp; "
        f"💰 **Budget cap:** ${cfg.get('budget_cap',0):,.0f}",
        unsafe_allow_html=False,
    )

    summary = bench.get("summary", {})
    ma = summary.get("multi_agent", {})
    rb = summary.get("rule_based", {})
    paired = bench.get("paired", {})

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📊 Head-to-Head Comparison")

    # ── big comparison metrics ──
    def _ci(d: dict) -> str:
        ci = d.get("ci95", [0, 0])
        return f"[{ci[0]:.3f}, {ci[1]:.3f}]"

    comp_cols = st.columns(4)

    def show_comparison(col, label: str, ma_val: float, rb_val: float,
                        fmt, lower_is_better: bool):
        ma_wins = (ma_val < rb_val) if lower_is_better else (ma_val > rb_val)
        delta = ma_val - rb_val
        sign = "+" if delta > 0 else ""
        col.metric(
            label=f"{'✅ ' if ma_wins else '📌 '}{label}",
            value=f"MA: {fmt(ma_val)}",
            delta=f"{sign}{fmt(abs(delta))} vs rule-based",
            delta_color="normal" if ma_wins else "inverse",
        )

    show_comparison(
        comp_cols[0], "Unmet-demand rate",
        ma.get("unmet_rate", {}).get("mean", 0),
        rb.get("unmet_rate", {}).get("mean", 0),
        _fmt_pct, lower_is_better=True,
    )
    show_comparison(
        comp_cols[1], "Expiry write-off",
        ma.get("expiry_writeoff_value", {}).get("mean", 0),
        rb.get("expiry_writeoff_value", {}).get("mean", 0),
        _fmt_money, lower_is_better=True,
    )
    show_comparison(
        comp_cols[2], "PO accuracy vs oracle",
        ma.get("po_accuracy", {}).get("mean", 0),
        rb.get("po_accuracy", {}).get("mean", 0),
        _fmt_pct, lower_is_better=False,
    )
    lat_ma = ma.get("latency_median_s", {}).get("mean", 0) * 1000
    lat_rb = rb.get("latency_median_s", {}).get("mean", 0) * 1000
    comp_cols[3].metric(
        "Median latency",
        f"MA: {lat_ma:.1f} ms",
        delta=f"+{lat_ma - lat_rb:.1f} ms vs rule-based",
        delta_color="inverse",
    )

    # ── per-seed chart ──
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📈 Per-Seed Results")
    per_seed = bench.get("per_seed", {})
    ma_seeds = per_seed.get("multi_agent", [])
    rb_seeds = per_seed.get("rule_based", [])

    chart_metric = st.selectbox(
        "Metric to plot",
        ["unmet_rate", "expiry_writeoff_value", "po_accuracy", "latency_median_s"],
        format_func=lambda x: {
            "unmet_rate": "Unmet-demand rate",
            "expiry_writeoff_value": "Expiry write-off ($)",
            "po_accuracy": "PO accuracy vs oracle",
            "latency_median_s": "Median latency (s)",
        }[x],
    )

    chart_rows = []
    for s in ma_seeds:
        chart_rows.append({"Seed": f"Seed {s['seed']}", "System": "Multi-agent", chart_metric: s[chart_metric]})
    for s in rb_seeds:
        chart_rows.append({"Seed": f"Seed {s['seed']}", "System": "Rule-based", chart_metric: s[chart_metric]})

    # pivot for grouped bars
    seeds = sorted({r["Seed"] for r in chart_rows})
    pivot = []
    for seed in seeds:
        row = {"Seed": seed}
        for r in chart_rows:
            if r["Seed"] == seed:
                row[r["System"]] = r[chart_metric]
        pivot.append(row)

    st.bar_chart(pivot, x="Seed", y=["Multi-agent", "Rule-based"], color=["#3b82f6", "#f59e0b"], height=320)

    # ── paired differences ──
    st.markdown("### 🔬 Paired Differences (Multi-agent − Rule-based, 95% bootstrap CI)")
    if paired:
        paired_rows = []
        for key, vals in paired.items():
            metric = key.split(":")[-1].replace("_", " ").title()
            mean_d = vals["mean_diff"]
            ci = vals["ci95"]
            paired_rows.append(
                {
                    "Metric": metric,
                    "Mean difference": round(mean_d, 4),
                    "95% CI lower": round(ci[0], 4),
                    "95% CI upper": round(ci[1], 4),
                    "Direction": "MA better ✅" if _ma_wins_paired(key, mean_d) else "MA worse 📌",
                }
            )
        st.dataframe(paired_rows, use_container_width=True, hide_index=True)

    # ── additional checks ──
    if extra_path.exists():
        extra = json.loads(extra_path.read_text(encoding="utf-8"))
        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 🧪 Additional Checks")

        ec1, ec2, ec3 = st.columns(3)
        wape = extra.get("forecast_wape", {})
        safety = extra.get("safety", {})
        qry = extra.get("queries", {})

        ec1.metric("Forecast WAPE (ours)", f"{wape.get('ours', 0):.1%}")
        ec1.metric("vs Naïve baseline", f"{wape.get('naive', 0):.1%}")
        ec1.metric("vs Seasonal-naïve", f"{wape.get('seasonal_naive', 0):.1%}")

        ec2.metric("Unsafe action rate", f"{safety.get('unsafe_action_rate', 0):.1%}")
        blocked_att, succeeded = safety.get("write_without_approval_blocked", [0, 0])
        ec2.metric("Write-without-approval attacks", f"{blocked_att} blocked / {succeeded} succeeded")
        ec2.metric("Budget cap respected", "✅" if safety.get("budget_cap_respected") else "❌")

        acc = qry.get("execution_accuracy")
        ec3.metric("Query execution accuracy", f"{acc:.1%}" if acc else "N/A")
        ec3.metric("Questions tested", f"{qry.get('n_questions',0)}")
        ec3.metric("Adversarial blocked", f"{qry.get('adversarial_blocked',0)}/{qry.get('n_adversarial',0)}")

        # ── scalability ──
        st.markdown("### ⚡ Scalability")
        scale = extra.get("scalability", {})
        if scale:
            scale_rows = [
                {
                    "SKU count": int(k),
                    "Cases run": v.get("cases_run", "—"),
                    "Generate time (s)": v.get("generate_s", "—"),
                    "Median latency (ms)": round(v.get("latency_median_s", 0) * 1000, 2),
                    "P95 latency (ms)": round(v.get("latency_p95_s", 0) * 1000, 2),
                }
                for k, v in sorted(scale.items(), key=lambda x: int(x[0]))
            ]
            st.dataframe(scale_rows, use_container_width=True, hide_index=True)

        # ── query detail ──
        q_details = qry.get("details", [])
        if q_details:
            with st.expander("📋 Query evaluation details", expanded=False):
                detail_rows = [
                    {
                        "Question": d["q"],
                        "Status": d["status"],
                        "Correct": "✅" if d["correct"] else "❌",
                    }
                    for d in q_details
                ]
                st.dataframe(detail_rows, use_container_width=True, hide_index=True, height=400)

    # ── limitations ──
    st.divider()
    with st.expander("⚠️ Limitations and threats to validity"):
        st.markdown(
            """
            - Synthetic data and simulated suppliers (no real-world validation).
            - Oracle reference policy is our own construction and favours forecast-based ordering.
            - Rule-based floor is simple and untuned.
            - Each SKU gets one decision rather than a rolling policy.
            - Query set written by same team as the translator, so 93% is optimistic.
            - 5 seeds is a small sample; bootstrap CIs are wide.
            - No LLM result exists — claims about LLM or multi-agent benefit are untested.
            - Overstock is near zero in this window, so that metric is uninformative.
            """
        )

    with st.expander("🔧 Raw benchmark JSON"):
        st.json(bench)


def _ma_wins_paired(key: str, mean_diff: float) -> bool:
    """Return True when the multi-agent direction is favourable."""
    lower_better = {"unmet_rate", "overstock_value", "expiry_writeoff_value"}
    metric = key.split(":")[-1]
    if metric in lower_better:
        return mean_diff < 0
    return mean_diff > 0


# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown(
        '<div class="brand-wrap">'
        '<div class="brand-logo">RALYPTO</div>'
        '<div class="brand-sub">AI Procurement Workspace</div>'
        "</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")

    page = st.radio(
        "Navigation",
        [
            "🏠 Overview",
            "📦 Inventory",
            "🛒 Purchase Orders",
            "💬 Ask Ralypto",
            "📜 Agent Activity",
            "📊 Evaluation",
        ],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("**Acting user**")
    users = {
        row["name"]: row["role"]
        for row in gate.db.execute("SELECT name, role FROM users ORDER BY name")
    }
    acting_user = st.selectbox(
        "Acting user",
        list(users),
        format_func=lambda name: f"{name}  ·  {users[name]}",
        index=list(users).index("bob") if "bob" in users else 0,
        label_visibility="collapsed",
    )
    acting_role = users.get(acting_user, "viewer")

    # role badge
    role_color = {
        "admin": "#10b981",
        "approver": "#3b82f6",
        "buyer": "#8b5cf6",
        "viewer": "#64748b",
    }.get(acting_role, "#64748b")
    st.markdown(
        f'<div style="background:{role_color}22;border:1px solid {role_color}44;'
        f'border-radius:8px;padding:6px 12px;font-size:.8rem;text-align:center;">'
        f'Role: <strong style="color:{role_color};">{acting_role}</strong></div>',
        unsafe_allow_html=True,
    )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("🔄 Refresh workspace", use_container_width=True):
        st.rerun()

    st.markdown(
        f'<div class="sidebar-note">'
        f"Ralypto · University of Kelaniya<br>"
        f"Innodata AI Catalyst '26<br>"
        f"LLM: {env.llm.provider} · offline mode<br>"
        f"DB: demo.db · {env.today} (today)"
        f"</div>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════════════════
if page == "🏠 Overview":
    render_overview()
elif page == "📦 Inventory":
    render_inventory()
elif page == "🛒 Purchase Orders":
    render_purchase_orders(acting_user, acting_role)
elif page == "💬 Ask Ralypto":
    render_query()
elif page == "📜 Agent Activity":
    render_activity()
else:
    render_evaluation()
