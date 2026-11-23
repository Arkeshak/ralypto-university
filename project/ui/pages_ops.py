"""Operational pages: Overview, Alerts and cases, Agent run view."""
from __future__ import annotations

import json

import altair as alt
import pandas as pd
import streamlit as st

from procure.orchestrator import LOW_CONFIDENCE, MAX_REVISIONS

from . import state
from . import theme as T

AGENT_LABEL = {"stock_monitor": "Stock Monitor", "orchestrator": "Orchestrator", "forecaster": "Demand Forecasting",
               "supplier": "Supplier", "po_agent": "Purchase Order", "validator": "Validator", "gate": "Safe-action gate",
               "human_approver": "Human Approver"}
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
             f"Live view of the synthetic ERP (profile {svc.env.meta('profile')}, day {svc.env.today}). "
             "All figures are read through the agents' read-only connection.")
    inv = inventory_frame(svc)
    exp = expiry_frame(svc, 14)
    open_pos = svc.purchase_orders(state.user(), "PENDING_APPROVAL")
    c = st.columns(5)
    with c[0]:
        T.kpi("Items low on stock", int(inv["below_reorder"].sum()), f"of {len(inv)} SKUs at or below reorder point",
              "warn" if inv["below_reorder"].any() else "good")
    with c[1]:
        T.kpi("Expiring batches", len(exp), "within 14 days", "warn" if len(exp) else "good")
    with c[2]:
        T.kpi("Open POs", len(open_pos), "awaiting approval", "primary")
    with c[3]:
        T.kpi("Stockout risk", int(inv["stockout_risk"].sum()), "SKUs with cover shorter than the fastest lead time",
              "bad" if inv["stockout_risk"].any() else "good")
    with c[4]:
        T.kpi("Expiry value at risk", T.money(float(exp["value"].sum()) if len(exp) else 0.0), "at cost, next 14 days",
              "bad" if len(exp) else "good")
    st.write("")
    left, right = st.columns([3, 2])
    with left:
        st.markdown("**Stock vs reorder level** (items at or near the reorder point)")
        show = inv.assign(ratio=inv["on_hand"] / inv["reorder_point"].clip(lower=1)).sort_values("ratio").head(20)
        if show.empty:
            T.empty("No items.")
        else:
            base = alt.Chart(show).encode(y=alt.Y("sku:N", sort=list(show["sku"]), title=None))
            bars = base.mark_bar(color=T.PRIMARY, size=12).encode(
                x=alt.X("on_hand:Q", title="units"),
                color=alt.condition("datum.below_reorder", alt.value(T.AMBER), alt.value(T.PRIMARY)),
                tooltip=["sku", "name", "on_hand", "reorder_point", "cover_days"])
            ticks = base.mark_tick(color=T.RED, thickness=2, size=16).encode(x="reorder_point:Q")
            st.altair_chart((bars + ticks).properties(height=420), use_container_width=True)
            st.caption("Bars: on hand (amber = at or below reorder point). Red tick: reorder point.")
    with right:
        st.markdown("**Expiry timeline** (value expiring per day, next 30 days)")
        ex30 = expiry_frame(svc, 30)
        if ex30.empty:
            T.empty("No batches expire in the next 30 days.")
        else:
            agg = ex30.groupby("days_to_expiry", as_index=False).agg(value=("value", "sum"), batches=("sku", "count"))
            ch = alt.Chart(agg).mark_bar(color=T.AMBER).encode(
                x=alt.X("days_to_expiry:O", title="days to expiry"), y=alt.Y("value:Q", title="value at cost"),
                color=alt.condition(alt.datum.days_to_expiry <= 7, alt.value(T.RED), alt.value(T.AMBER)),
                tooltip=["days_to_expiry", "value", "batches"])
            st.altair_chart(ch.properties(height=420), use_container_width=True)
            st.caption("Red: expires within 7 days.")


# ------------------------------------------------------------------ Alerts and cases
def alerts():
    svc = state.svc()
    T.header("Stock Monitor", "Alerts and cases",
             "Alerts raised by the Stock Monitor agent from stock, reorder points and expiry dates. "
             "Select one and run the agent team on it.")
    al = svc.alerts(state.user())
    if not al:
        T.empty("No alerts: every item is above its reorder point and nothing expires within 14 days.")
        return
    f1, f2 = st.columns([1, 3])
    sev = f1.multiselect("Severity", ["high", "medium", "low"], default=["high", "medium", "low"])
    kinds = f2.multiselect("Type", ["low_stock", "expiry", "both"], default=["low_stock", "expiry", "both"])
    al = [a for a in al if a.severity in sev and a.kind in kinds]
    df = pd.DataFrame([{"SKU": a.sku, "Severity": a.severity, "Type": a.kind, "On hand": a.on_hand,
                        "Reorder point": a.reorder_point, "Avg daily (28d)": a.avg_daily,
                        "Expiring qty": a.expiring_qty, "Days to expiry": a.days_to_expiry, "Evidence": a.evidence}
                       for a in al])
    st.dataframe(df, use_container_width=True, hide_index=True, height=360)
    st.markdown("**Run the agents on an alert**")
    c1, c2, c3 = st.columns([2, 2, 1])
    sku = c1.selectbox("Alert", [a.sku for a in al], format_func=lambda s: next(
        f"{a.sku} - {a.severity} - {a.kind}" for a in al if a.sku == s))
    fault = c2.selectbox("Fault injection (for testing)", ["none", "forecaster"],
                         help="'forecaster' makes the Forecasting agent fail so the deterministic fallback runs.")
    can = svc.can(state.user(), "run_case")
    c3.write("")
    if c3.button("Run agents", type="primary", disabled=not can, use_container_width=True):
        st.session_state["run_request"] = {"sku": sku, "fault": None if fault == "none" else fault}
        st.switch_page(PAGES["agent_run"])
    if not can:
        st.info(f"Your role ({state.role()}) can view alerts but cannot start a purchasing case. "
                "Switch to a buyer, approver or admin in the sidebar.")


# ------------------------------------------------------------------ Agent run view
def workflow_dot(visited: set, failed: set, active: str = "") -> str:
    nodes = [("stock_monitor", "Stock Monitor"), ("forecaster", "Demand Forecasting\n(LightGBM)"),
             ("supplier", "Supplier\n(weighted score)"), ("po_agent", "Purchase Order"), ("validator", "Validator\n(veto)"),
             ("po_reviser", "PO revision\n(max 2)"), ("escalate", "Escalate to human"), ("gate_submit", "Safe-action gate"),
             ("human_approval", "Human Approver")]
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
        return (f"{o.get('kind')} alert, severity {o.get('severity')}: on hand {o.get('on_hand')}, "
                f"reorder point {o.get('reorder_point')}")
    if a == "forecaster":
        if "error" in o:
            return f"FAILED: {o['error']}"
        return f"{o.get('method')}: {o.get('mean_28d')} units over 28 days, sigma/day {o.get('sigma_daily')}"
    if a == "supplier":
        opts = o.get("options", [])
        return " vs ".join(f"{x['name']} (score {x['score']})" for x in opts) or "no supplier available"
    if a == "po_agent":
        return (f"{o.get('action')} {o.get('qty')} x {o.get('supplier_name')} at {o.get('unit_price')} "
                f"(revision {o.get('revision')})")
    if a == "validator":
        return "PASS" if o.get("passed") else "VETO: " + "; ".join(f["message"] for f in o.get("failures", []))
    if a == "gate":
        return f"PO #{o.get('po_id')} -> {o.get('status')}"
    if a == "human_approver":
        return f"decision -> {o.get('status')}"
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
        with st.expander("input / output / evidence", expanded=False):
            st.json({"inputs": m.inputs, "output": m.output, "evidence": m.evidence}, expanded=False)


def agent_run():
    svc = state.svc()
    T.header("Multi-agent workflow", "Agent run view",
             "Step-by-step timeline of one purchasing case: Stock Monitor, then Forecasting and Supplier in parallel, "
             "then Purchase Order and the Validator. Each step shows its input, output, confidence, evidence and latency.")
    req = st.session_state.pop("run_request", None)
    if req is None:
        al = svc.alerts(state.user())
        c1, c2 = st.columns([3, 1])
        if al:
            sku = c1.selectbox("Alert to run", [a.sku for a in al], format_func=lambda s: next(
                f"{a.sku} - {a.severity} - {a.kind}" for a in al if a.sku == s))
            c2.write("")
            if c2.button("Run agents", type="primary", disabled=not svc.can(state.user(), "run_case"),
                         use_container_width=True):
                req = {"sku": sku, "fault": None}
    left, right = st.columns([3, 2])
    graph_slot = right.empty()
    if req:
        visited, failed = set(), set()
        graph_slot.graphviz_chart(workflow_dot(visited, failed, "stock_monitor"), use_container_width=True)
        with left:
            status = st.status(f"Running agents on {req['sku']} ...", expanded=True)
            case = None
            for kind, item in svc.run_case_stream(state.user(), req["sku"], req.get("fault")):
                if kind == "msg":
                    visited.add(item.author)
                    if (item.author == "validator" and not item.output.get("passed", True)) or "error" in item.output:
                        failed.add(item.author)
                    render_step(item, status)
                    graph_slot.graphviz_chart(workflow_dot(visited, failed), use_container_width=True)
                else:
                    case = item
            status.update(label=f"Case {case.task_id} finished: {case.status}",
                          state="complete" if case.status in ("pending_approval", "no_action") else "error")
        st.session_state["last_case"] = case.task_id
        return render_case_summary(case)
    task = st.session_state.get("last_case")
    case = svc.cases.get(task) if task else None
    if not case:
        graph_slot.graphviz_chart(workflow_dot(set(), set()), use_container_width=True)
        with left:
            T.empty("No case run yet in this session. Pick an alert above, or use 'Run demo scenario' in the sidebar.")
        return
    with left:
        st.markdown(f"**Last case {case.task_id}** - {case.sku}")
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
        T.kpi("Outcome", case.status.replace("_", " "), f"task {case.task_id}", T.STATUS_TONE.get(case.status, "muted"))
    with c[1]:
        T.kpi("Validator passes", len(case.validations), f"max {MAX_REVISIONS + 1} (2 revisions)", "primary")
    with c[2]:
        T.kpi("Forecast confidence", case.forecast.confidence if case.forecast else "-",
              f"review flag below {LOW_CONFIDENCE}" + (" - FLAGGED" if case.review_flag else ""),
              "warn" if case.review_flag else "good")
    with c[3]:
        T.kpi("Case latency", f"{case.latency_s:.2f} s", case.mode, "muted")
    if case.notes:
        for n in case.notes:
            st.warning(n)
    if case.status == "pending_approval":
        st.success(f"PO #{case.po_id} is waiting at the human-approval interrupt. Open the Approval dashboard.")
        if st.button("Go to approval dashboard"):
            st.switch_page(PAGES["approvals"])


PAGES: dict = {}  # filled by app.py so pages can link to each other
