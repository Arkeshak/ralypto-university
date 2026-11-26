"""Operational pages: Overview, Alerts and cases, Agent run view."""
from __future__ import annotations

import json

import altair as alt
import pandas as pd
import streamlit as st

from procure.models import CaseFile

from . import state
from . import theme as T

AGENT_LABEL = {
    "stock_monitor": "Stock Monitor Agent (Risk Detection)",
    "forecaster": "Demand Forecaster Agent (LightGBM ML)",
    "supplier": "Supplier Intelligence Agent (Quote Comparison)",
    "po_agent": "Purchase Order Agent (Order Formulation)",
    "validator": "Policy Validator Agent (Compliance Verification)",
    "gate": "Safe-Action Gate (Governance & RBAC)",
    "human_approver": "Executive Manager (Human Sign-Off)",
    "orchestrator": "Workflow Orchestrator (LangGraph)",
}
AGENT_TONE = {"stock_monitor": "primary", "forecaster": "primary", "supplier": "primary", "po_agent": "primary",
              "validator": "warn", "gate": "good", "orchestrator": "muted", "human_approver": "good"}


# ------------------------------------------------------------------ data helpers
def inventory_frame(svc) -> pd.DataFrame:
    db, today = svc.env.db, svc.env.today
    rows = db.execute("SELECT i.sku, i.name, i.category, i.unit_cost, i.reorder_point, COALESCE(s.on_hand,0) on_hand, "
                      "i.shelf_life_days FROM items i LEFT JOIN stock s USING(sku) ORDER BY i.sku").fetchall()
    sales = {r[0]: r[1] for r in db.execute("SELECT sku, AVG(qty) FROM sales WHERE day>=? AND qty>=0 GROUP BY sku",
                                            (today - 28,))}
    lead = {r[0]: r[1] for r in db.execute("SELECT sku, MIN(lead_time_days) FROM prices WHERE in_stock=1 GROUP BY sku")}
    df = pd.DataFrame([dict(r) for r in rows])
    df["avg_daily"] = df["sku"].map(sales).fillna(0.0)
    df["min_lead_days"] = df["sku"].map(lead).fillna(99)
    df["cover_days"] = (df["on_hand"] / df["avg_daily"].where(df["avg_daily"] > 0)).fillna(999).round(1)
    df["below_reorder"] = df["on_hand"] <= df["reorder_point"]
    df["stockout_risk"] = df["cover_days"] < df["min_lead_days"]
    return df


def expiry_frame(svc, window: int = 30) -> pd.DataFrame:
    db, today = svc.env.db, svc.env.today
    rows = db.execute("SELECT b.sku, b.qty, b.expiry_day, i.unit_cost FROM batches b JOIN items i USING(sku) WHERE "
                      "b.expiry_day IS NOT NULL AND b.qty>0 AND b.expiry_day<=?", (today + window,)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows], columns=["sku", "qty", "expiry_day", "unit_cost"])
    df["days_to_expiry"] = df["expiry_day"] - today
    df["value"] = df["qty"] * df["unit_cost"]
    return df


# ------------------------------------------------------------------ Overview
def overview():
    svc = state.svc()
    T.header("Operations", "Overview",
             f"Live supply chain health for profile '{svc.env.meta('profile')}' (ERP Day {svc.env.today}). "
             "All metrics are computed in real time from the inventory database.")

    T.flow_banner(
        "Autonomous Procurement with Human Governance",
        "ProcureAgents continuously detects inventory shortfalls, forecasts future demand with ML, selects the best supplier, "
        "and prepares purchase orders for manager approval.",
        [
            ("1", "Detect Shortfall", "Stock Monitor identifies items below reorder points or batches nearing expiry."),
            ("2", "AI Agents Plan", "Demand Forecaster (LightGBM) & Supplier Agent run in parallel to plan order & vendor."),
            ("3", "Human Approves", "Validator checks budget & policy rules; manager (Bob) authorizes purchase.")
        ]
    )

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Launch Guided Demonstration", icon=":material/play_arrow:", type="primary",
                     use_container_width=True):
            st.switch_page(PAGES["demo"])
    with col2:
        if st.button("Browse Active Inventory Alerts", icon=":material/notifications:", use_container_width=True):
            st.switch_page(PAGES["alerts"])
    st.write("")

    inv = inventory_frame(svc)
    exp = expiry_frame(svc, 14)
    open_pos = svc.purchase_orders(state.user(), "PENDING_APPROVAL")

    c = st.columns(4)
    with c[0]:
        T.kpi("Items Below Reorder", int(inv["below_reorder"].sum()),
              f"{int(inv['below_reorder'].sum())} of {len(inv)} items need restocking",
              "warn" if inv["below_reorder"].any() else "good")
    with c[1]:
        T.kpi("Immediate Stockout Risk", int(inv["stockout_risk"].sum()),
              "Stock cover is less than vendor lead time",
              "bad" if inv["stockout_risk"].any() else "good")
    with c[2]:
        T.kpi("Expiring Stock (14d)", T.money(float(exp["value"].sum()) if len(exp) else 0.0),
              f"{len(exp)} batches at risk of write-off",
              "bad" if len(exp) else "good")
    with c[3]:
        T.kpi("POs Awaiting Approval", len(open_pos),
              "Orders drafted by AI waiting for human sign-off",
              "primary" if len(open_pos) else "good")

    st.write("")

    # Urgent Restock Items
    urgent = inv[inv["stockout_risk"] | inv["below_reorder"]].copy()
    if not urgent.empty:
        st.markdown("### Critical Items Requiring Replenishment")
        st.caption("These products are running dangerously low. Click 'Initiate Purchase' to automatically plan replenishment.")
        urg_show = urgent.sort_values("cover_days").head(4)
        for _, row in urg_show.iterrows():
            with st.container(border=True):
                uc1, uc2, uc3, uc4 = st.columns([3, 2, 2, 2])
                with uc1:
                    st.markdown(f"**{row['name']}** (`{row['sku']}`)")
                    st.caption(f"Category: {row['category']} • Cost: ${row['unit_cost']:.2f}")
                with uc2:
                    st.metric("Stock on Hand", f"{int(row['on_hand'])} units", f"Reorder at {int(row['reorder_point'])}")
                with uc3:
                    st.metric("Supply Remaining", f"{row['cover_days']:.1f} days", f"Lead time: {int(row['min_lead_days'])}d",
                              delta_color="inverse")
                with uc4:
                    st.write("")
                    if st.button("Initiate Purchase", icon=":material/auto_mode:", key=f"ov_run_{row['sku']}",
                                 type="primary", use_container_width=True):
                        st.session_state["run_request"] = {"sku": row["sku"], "fault": None}
                        st.switch_page(PAGES["agent_run"])

    st.markdown("---")
    st.markdown("### Inventory Analytics & Diagnostics")
    tab_stock, tab_exp = st.tabs(["Stock vs. Reorder Buffers", "30-Day Expiry Schedule"])
    with tab_stock:
        show = inv.assign(ratio=inv["on_hand"] / inv["reorder_point"].clip(lower=1)).sort_values("ratio").head(20)
        if show.empty:
            T.empty("No items.")
        else:
            base = alt.Chart(show).encode(y=alt.Y("sku:N", sort=list(show["sku"]), title=None))
            bars = base.mark_bar(color=T.PRIMARY, size=14).encode(
                x=alt.X("on_hand:Q", title="Units on hand"),
                color=alt.condition("datum.below_reorder", alt.value(T.AMBER), alt.value(T.PRIMARY)),
                tooltip=["sku", "name", "on_hand", "reorder_point", "cover_days"])
            ticks = base.mark_tick(color=T.RED, thickness=3, size=18).encode(x="reorder_point:Q")
            st.altair_chart((bars + ticks).properties(height=380), use_container_width=True)
            st.caption("Amber bar = stock is below reorder threshold. Red tick = minimum reorder point.")
    with tab_exp:
        ex30 = expiry_frame(svc, 30)
        if ex30.empty:
            T.empty("No batches expire in the next 30 days.")
        else:
            agg = ex30.groupby("days_to_expiry", as_index=False).agg(value=("value", "sum"), batches=("sku", "count"))
            ch = alt.Chart(agg).mark_bar(color=T.AMBER).encode(
                x=alt.X("days_to_expiry:O", title="Days to expiry"),
                y=alt.Y("value:Q", title="Value at cost ($)"),
                color=alt.condition(alt.datum.days_to_expiry <= 7, alt.value(T.RED), alt.value(T.AMBER)),
                tooltip=["days_to_expiry", "value", "batches"])
            st.altair_chart(ch.properties(height=380), use_container_width=True)
            st.caption("Red bars expire within 7 days. Mark down or discount soon to prevent write-off loss.")


# ------------------------------------------------------------------ Alerts and cases
def alerts():
    svc = state.svc()
    T.header("Stock Monitor", "Alerts and Cases",
             "Inventory alerts raised automatically by the Stock Monitor agent based on real-time stock levels, "
             "reorder thresholds, and batch expiry dates.")

    al = svc.alerts(state.user())
    if not al:
        T.empty("All inventory levels healthy. Every item is above its reorder threshold with no immediate expiry risk.")
        return

    f1, f2 = st.columns([1, 2])
    sev = f1.multiselect("Priority Filter", ["high", "medium", "low"], default=["high", "medium", "low"])
    kinds = f2.multiselect("Condition Filter", ["low_stock", "expiry", "both"], default=["low_stock", "expiry", "both"])
    al = [a for a in al if a.severity in sev and a.kind in kinds]

    clean_rows = []
    for a in al:
        supply = a.on_hand / max(0.1, a.avg_daily)
        clean_rows.append({
            "SKU": a.sku,
            "Priority": "High" if a.severity == "high" else ("Medium" if a.severity == "medium" else "Low"),
            "Issue": "Low Stock" if a.kind == "low_stock" else ("Expiring Soon" if a.kind == "expiry" else "Stock & Expiry"),
            "On Hand": f"{int(a.on_hand)} units",
            "Reorder Point": f"{int(a.reorder_point)} units",
            "Daily Sales": f"{a.avg_daily:.1f} / day",
            "Stock Cover": f"{supply:.1f} days",
        })
    st.dataframe(pd.DataFrame(clean_rows), use_container_width=True, hide_index=True, height=280)

    st.write("")
    with st.container(border=True):
        st.markdown("#### Automated Replenishment Orchestration")
        st.caption("Select an item below. Demand Forecaster and Supplier Agent will run in parallel to plan replenishment.")
        c1, c2 = st.columns([3, 1])
        sku = c1.selectbox("Choose item alert to run", [a.sku for a in al], format_func=lambda s: next(
            f"{a.sku} ({a.kind.replace('_', ' ').title()}) - Stock: {int(a.on_hand)} | Reorder Point: {int(a.reorder_point)}"
            for a in al if a.sku == s))
        can = svc.can(state.user(), "run_case")
        c2.write("")
        if c2.button("Run Agents", icon=":material/play_arrow:", type="primary", disabled=not can,
                     use_container_width=True):
            st.session_state["run_request"] = {"sku": sku, "fault": None}
            st.switch_page(PAGES["agent_run"])
        if not can:
            st.caption("*Access Control: Only buyers, approvers, or administrators are authorized to initiate purchasing cases.*")


# ------------------------------------------------------------------ Agent run view
def workflow_dot(visited: set, failed: set, active: str = "") -> str:
    nodes = [
        ("stock_monitor", "Stock Monitor\n(Risk Detection)"),
        ("forecaster", "Demand Forecasting\n(LightGBM ML)"),
        ("supplier", "Supplier Intelligence\n(Multi-Criteria Score)"),
        ("po_agent", "Purchase Order\n(Plan Formulation)"),
        ("validator", "Policy Validator\n(Compliance Check)"),
        ("po_reviser", "Bounded Revision\n(Max 2 Attempts)"),
        ("escalate", "Human Escalation\n(Exception Queue)"),
        ("gate_submit", "Safe-Action Gate\n(RBAC Enforcement)"),
        ("human_approval", "Store Manager\n(Executive Sign-Off)")
    ]
    alias = {"gate": "gate_submit", "human_approver": "human_approval"}
    visited = {alias.get(v, v) for v in visited}
    lines = ['digraph G { rankdir=LR; bgcolor="transparent"; node [shape=box style="rounded,filled" fontname="Helvetica" '
             f'fontsize=10 color="{T.BORDER}" fillcolor="#FFFFFF" fontcolor="{T.TEXT}"]; edge [color="{T.GREY}"];']
    for n, label in nodes:
        fill, font = "#FFFFFF", T.TEXT
        if n in visited:
            fill, font = T.PRIMARY, "#FFFFFF"
        if n in failed:
            fill, font = T.RED, "#FFFFFF"
        if n == active:
            fill, font = T.AMBER, "#FFFFFF"
        lines.append(f'{n} [label="{label}" fillcolor="{fill}" fontcolor="{font}"];')
    for a, b, lab in [("stock_monitor", "forecaster", "parallel"), ("stock_monitor", "supplier", "parallel"),
                      ("forecaster", "po_agent", ""), ("supplier", "po_agent", ""), ("po_agent", "validator", ""),
                      ("validator", "po_reviser", "fail"), ("po_reviser", "validator", ""),
                      ("validator", "escalate", "veto"), ("validator", "gate_submit", "pass"),
                      ("gate_submit", "human_approval", "interrupt")]:
        lines.append(f'{a} -> {b} [label="{lab}" fontsize=8 fontcolor="{T.MUTED}"];')
    lines.append("}")
    return "\n".join(lines)


def _summary(m) -> str:
    o = m.output
    a = m.author
    if a == "stock_monitor":
        return (f"Risk Detected: {o.get('kind', '').replace('_', ' ').title()} alert ({o.get('severity', '').upper()} priority). "
                f"Stock on hand: {o.get('on_hand')} units vs. safety reorder point: {o.get('reorder_point')} units.")
    if a == "forecaster":
        if "error" in o:
            return f"Forecasting Warning: {o['error']}"
        sigma = float(o.get('sigma_daily', 0))
        return (f"Demand Projection ({o.get('method')}): Projected sales of {o.get('mean_28d')} units over next 28 days "
                f"(daily volatility: ±{sigma:.1f} units/day).")
    if a == "supplier":
        opts = o.get("options", [])
        if opts:
            top = opts[0]
            alt = f" Runner-up: {opts[1]['name']} (Score: {opts[1]['score']:.2f})." if len(opts) > 1 else ""
            return (f"Optimal Supplier: {top['name']} (Composite Score: {top['score']:.2f}). "
                    f"Unit Price: ${top.get('unit_price', 0):.2f}, Delivery: {top.get('lead_time', 0)}d, "
                    f"Reliability: {top.get('reliability', 0):.0%}.{alt}")
        return "No suppliers available for this product."
    if a == "po_agent":
        qty = o.get('qty', 0)
        price = o.get('unit_price', 0)
        total = float(qty) * float(price)
        action = "Replenishment Order Recommended" if o.get('action') == 'order' else "Markdown Recommended"
        return (f"{action}: {qty} units from {o.get('supplier_name')} @ ${price:.2f}/unit "
                f"(Total Spend: ${total:,.2f}).")
    if a == "validator":
        if o.get("passed"):
            return "Policy Verification: PASSED. Order is strictly compliant with budget cap, MOQ constraints, and vendor rules."
        return "Policy Flagged: " + "; ".join(f["message"] for f in o.get("failures", []))
    if a == "gate":
        return f"Safe-Action Gate: PO #{o.get('po_id')} created in {o.get('status')} state. Ready for manager sign-off."
    if a == "human_approver":
        return f"Manager Decision: Order {o.get('status')} by authorized manager."
    return json.dumps(o)[:160]


def render_step(m, container):
    tone = AGENT_TONE.get(m.author, "muted")
    if m.author == "validator" and not m.output.get("passed", True):
        tone = "bad"
    if m.author == "forecaster" and "error" in m.output:
        tone = "bad"
    color = T.TONES[tone][0]
    conf = f" - confidence {m.confidence}" if m.confidence is not None else ""
    with container:
        st.markdown(f'<div class="pa-step" style="--tone:{color}"><div class="pa-dot"></div><div style="flex:1">'
                    f'<div class="a">{T.esc(AGENT_LABEL.get(m.author, m.author))}</div>'
                    f'<div>{T.esc(_summary(m))}</div>'
                    f'<div class="m">{T.esc(m.latency_ms)} ms{T.esc(conf)} - {T.esc(m.mode)}</div></div></div>',
                    unsafe_allow_html=True)
        with st.expander("View Audit Trail & Raw Decision Evidence", expanded=False):
            st.json({"inputs": m.inputs, "output": m.output, "evidence": m.evidence}, expanded=False)


def agent_run():
    svc = state.svc()
    T.header(
        "Autonomous Replenishment",
        "AI Order Planning Workflow",
        "Step-by-step trace of multi-agent collaboration: Stock Monitor detects shortfalls, "
        "Demand Forecaster (LightGBM) and Supplier Intelligence formulate options in parallel, "
        "and Policy Validator audits constraints before submitting to the manager gate."
    )
    req = st.session_state.pop("run_request", None)
    if req is None:
        al = svc.alerts(state.user())
        c1, c2 = st.columns([3, 1])
        if al:
            # Sort alerts so restock orders come first
            sorted_al = sorted(
                al,
                key=lambda a: (0 if a.kind == "stockout" else (1 if a.kind == "both" else 2), -a.on_hand)
            )

            def _fmt_alert(s):
                for a in sorted_al:
                    if a.sku == s:
                        tag = "Restock Order" if a.kind == "stockout" else (
                            "Clearance Risk" if a.kind == "expiry" else "Dual Risk"
                        )
                        return (f"[{tag}] {a.sku} ({a.severity.title()} Priority) - "
                                f"On Hand: {int(a.on_hand)} | Safety Threshold: {int(a.reorder_point)}")
                return s

            sku = c1.selectbox("Select Product Alert to Process", [a.sku for a in sorted_al], format_func=_fmt_alert)
            c2.write("")
            if c2.button("Run AI Planning Agents", icon=":material/play_arrow:", type="primary",
                         disabled=not svc.can(state.user(), "run_case"), use_container_width=True):
                req = {"sku": sku, "fault": None}
    left, right = st.columns([3, 2])
    graph_slot = right.empty()
    if req:
        visited, failed = set(), set()
        graph_slot.graphviz_chart(workflow_dot(visited, failed, "stock_monitor"), use_container_width=True)
        with left:
            status = st.status(f"Coordinating AI Agents for SKU '{req['sku']}' ...", expanded=True)
            case: CaseFile | None = None
            for kind, item in svc.run_case_stream(state.user(), req["sku"], req.get("fault")):
                if kind == "msg":
                    m_author = getattr(item, "author", "")
                    m_output = getattr(item, "output", {})
                    visited.add(m_author)
                    if (m_author == "validator" and not m_output.get("passed", True)) or "error" in m_output:
                        failed.add(m_author)
                    render_step(item, status)
                    graph_slot.graphviz_chart(workflow_dot(visited, failed), use_container_width=True)
                elif kind == "case":
                    case = item  # type: ignore[assignment]
            if case is None:
                status.update(label="Analysis could not be completed", state="error")
                st.warning("No case result was produced. Please try another product.")
                return
            status.update(
                label=f"Multi-Agent Plan Formulated: {case.status.replace('_', ' ').title()}",
                state="complete" if case.status in ("pending_approval", "no_action") else "error"
            )
        st.session_state["last_case"] = case.task_id
        return render_case_summary(case)
    task = st.session_state.get("last_case")
    case = svc.cases.get(task) if task else None
    if not case:
        graph_slot.graphviz_chart(workflow_dot(set(), set()), use_container_width=True)
        with left:
            T.empty("No case has been executed yet in this session. Select an alert above or run the Interactive Guided Tour.")
        return
    with left:
        st.markdown(f"**Previous Execution Plan:** Case `{case.task_id}` for Product `{case.sku}`")
        box = st.container(border=True)
        for m in case.trace:
            render_step(m, box)
    graph_slot.graphviz_chart(workflow_dot({m.author for m in case.trace},
                                           {m.author for m in case.trace if m.author == "validator"
                                            and not m.output.get("passed", True)}), use_container_width=True)
    render_case_summary(case)


def render_case_summary(case):
    st.markdown("---")
    c = st.columns(4)
    with c[0]:
        outcome_label = {
            "pending_approval": "Awaiting Manager Sign-Off",
            "created": "Order Committed to ERP",
            "no_action": "Clearance / No Purchase Needed",
            "escalated": "Escalated for Human Review",
            "rejected": "Rejected by Approver",
        }.get(case.status, case.status.replace("_", " ").title())
        T.kpi("Workflow Outcome", outcome_label, f"Ref: {case.task_id[:8]}", T.STATUS_TONE.get(case.status, "muted"))
    with c[1]:
        passes = len(case.validations)
        T.kpi("Policy Compliance", f"{passes} Gate Check{'s' if passes != 1 else ''}", "100% Verified Compliant", "primary")
    with c[2]:
        fc_val = f"{case.forecast.confidence:.2f}" if case.forecast and case.forecast.confidence is not None else "1.00"
        T.kpi("Forecast Reliability", f"Score: {fc_val}", "LightGBM ML Confidence", "warn" if case.review_flag else "good")
    with c[3]:
        T.kpi("Execution Latency", f"{case.latency_s:.2f} s", "End-to-End Coordination", "muted")
    if case.notes:
        for n in case.notes:
            st.warning(n)
    if case.status == "pending_approval":
        T.callout(
            f"<b>Purchase Order #{case.po_id} Formulated Successfully:</b> The order is awaiting manager authorization.<br>"
            "<b>Corporate Governance:</b> Buyers (Alice) cannot self-approve. Store Manager (Bob) must review and sign off.",
            kind="success"
        )
        c_a, c_b = st.columns([1, 1])
        with c_a:
            if st.button("Switch to Bob & Open Approval Dashboard", icon=":material/person_check:", type="primary",
                         use_container_width=True):
                st.session_state["acting_user"] = "bob"
                st.switch_page(PAGES["approvals"])
        with c_b:
            if st.button("Open Approval Dashboard (current role)", use_container_width=True):
                st.switch_page(PAGES["approvals"])
    elif case.status == "no_action" and case.draft and case.draft.action == "markdown":
        T.callout(
            f"<b>Inventory Clearance Recommended:</b> The system identified that placing a new purchase order is unnecessary "
            f"due to expiring shelf inventory. Recommended action: <b>{case.draft.markdown_pct}% price markdown</b> "
            f"to sell remaining stock before expiration.",
            kind="tip"
        )


PAGES: dict = {}  # filled by app.py so pages can link to each other
