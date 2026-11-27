"""Operational pages: Overview, Inventory Catalog, Alerts, and Purchasing Assistant."""
from __future__ import annotations

import altair as alt
import pandas as pd
import streamlit as st

from procure.models import CaseFile

from . import products, state
from . import theme as T

AGENT_LABEL = {
    "stock_monitor": "Stock Checker (Shortage & Expiry Detection)",
    "forecaster": "Demand Prediction (LightGBM Machine Learning)",
    "supplier": "Supplier Comparison (Best Quote & Reliability)",
    "po_agent": "Purchase Order Planner (Order Formulation)",
    "validator": "Order Safety Check (Budget & Policy Compliance)",
    "gate": "Safe-Action Gate (Manager Approval Required)",
    "human_approver": "Store Manager (Executive Sign-Off)",
    "orchestrator": "Procurement Orchestrator",
}
AGENT_TONE = {
    "stock_monitor": "primary",
    "forecaster": "primary",
    "supplier": "primary",
    "po_agent": "primary",
    "validator": "good",
    "gate": "good",
    "orchestrator": "muted",
    "human_approver": "good",
}


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
    df["total_value"] = df["on_hand"] * df["unit_cost"]
    return df


def expiry_frame(svc, window: int = 30) -> pd.DataFrame:
    db, today = svc.env.db, svc.env.today
    rows = db.execute("SELECT b.sku, b.qty, b.expiry_day, i.name, i.category, i.unit_cost FROM batches b "
                      "JOIN items i USING(sku) WHERE b.expiry_day IS NOT NULL AND b.qty>0 AND b.expiry_day<=? "
                      "ORDER BY b.expiry_day", (today + window,)).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return pd.DataFrame(columns=["sku", "qty", "expiry_day", "name", "category", "unit_cost", "days_to_expiry", "value"])
    df["days_to_expiry"] = df["expiry_day"] - today
    df["value"] = df["qty"] * df["unit_cost"]
    return df


# ------------------------------------------------------------------ Overview / Main Dashboard
def overview():
    svc = state.svc()
    prof_name = str(svc.env.meta("profile") or "supermarket").title()
    T.header(
        "Store Management",
        "Executive Dashboard",
        f"Real-time inventory health, critical reorder items, and purchasing actions for **{prof_name}** (Day {svc.env.today})."
    )

    inv = inventory_frame(svc)
    exp = expiry_frame(svc, 14)
    open_pos = svc.purchase_orders(state.user(), "PENDING_APPROVAL")
    total_inv_val = inv["total_value"].sum()
    low_stock_count = int(inv["below_reorder"].sum())
    exp_val = float(exp["value"].sum()) if not exp.empty else 0.0

    # 6 Key Business Metrics answering the store owner's top questions
    c = st.columns(4)
    with c[0]:
        T.kpi("Inventory Value", f"${total_inv_val:,.2f}", f"{len(inv)} total active products", "primary")
    with c[1]:
        tone = "bad" if low_stock_count > 0 else "good"
        T.kpi("Products Running Low", low_stock_count, "Below safety reorder threshold", tone)
    with c[2]:
        tone = "bad" if exp_val > 0 else "good"
        T.kpi("Expiring Stock (14d)", f"${exp_val:,.2f}", f"{len(exp)} batches at risk of spoilage", tone)
    with c[3]:
        n_pos = len(open_pos)
        tone = "warn" if n_pos > 0 else "good"
        T.kpi("Awaiting Manager Sign-Off", f"{n_pos} Order{'s' if n_pos != 1 else ''}",
              "Pending executive authorization", tone)

    st.write("")

    # Actionable Top Banners
    b1, b2 = st.columns([1, 1])
    with b1:
        if st.button("Browse Full Product Inventory", icon=":material/inventory_2:", use_container_width=True):
            st.switch_page(PAGES["inventory"])
    with b2:
        if st.button("Open Manager Approval Desk", icon=":material/fact_check:", type="primary", use_container_width=True):
            st.switch_page(PAGES["approvals"])

    st.write("")

    # Urgent Restock Items with full product photography and 1-click reorder
    urgent = inv[inv["stockout_risk"] | inv["below_reorder"]].copy()
    st.markdown("### Critical Products Requiring Immediate Restock")
    st.caption("These items have fallen below safety stock or have less cover than supplier delivery lead time.")

    if urgent.empty:
        st.success("All inventory levels are healthy! No products currently require emergency replenishment.",
                   icon=":material/check_circle:")
    else:
        urg_show = urgent.sort_values("cover_days").head(5)
        for _, row in urg_show.iterrows():
            with st.container(border=True):
                r1, r2, r3, r4 = st.columns([4, 2, 2, 2])
                with r1:
                    st.markdown(products.product_cell_html(
                        row["sku"], row["name"], row["category"],
                        subtext=f"Product Code: {row['sku']} • Cost: ${row['unit_cost']:.2f} / unit",
                        size=48
                    ), unsafe_allow_html=True)
                with r2:
                    st.metric("Stock on Hand", f"{int(row['on_hand'])} units", f"Safety Point: {int(row['reorder_point'])}")
                with r3:
                    st.metric("Stock Cover", f"{row['cover_days']:.1f} days", f"Lead time: {int(row['min_lead_days'])}d",
                              delta_color="inverse")
                with r4:
                    st.write("")
                    if st.button("Order Restock", icon=":material/shopping_cart:", key=f"ov_urg_{row['sku']}",
                                 type="primary", use_container_width=True):
                        st.session_state["run_request"] = {"sku": row["sku"], "fault": None}
                        st.switch_page(PAGES["agent_run"])

    st.write("")

    # Expiry clearance queue
    if not exp.empty:
        st.markdown("### Perishable Batches Nearing Expiry (Action Required)")
        st.caption("Discounting these items now liquidates stock before expiration and prevents total inventory write-off.")
        exp_show = exp.head(4)
        for _, erow in exp_show.iterrows():
            with st.container(border=True):
                e1, e2, e3, e4 = st.columns([4, 2, 2, 2])
                with e1:
                    st.markdown(products.product_cell_html(
                        erow["sku"], erow["name"], erow["category"],
                        subtext=f"Batch expires in {int(erow['days_to_expiry'])} days (Day {int(erow['expiry_day'])})",
                        size=48
                    ), unsafe_allow_html=True)
                with e2:
                    st.metric("Expiring Quantity", f"{int(erow['qty'])} units")
                with e3:
                    st.metric("Value at Risk", f"${erow['value']:,.2f}", delta="-100% loss if expired", delta_color="inverse")
                with e4:
                    st.write("")
                    if st.button("Review Clearance", icon=":material/sell:", key=f"ov_exp_{erow['sku']}",
                                 use_container_width=True):
                        st.session_state["run_request"] = {"sku": erow["sku"], "fault": None}
                        st.switch_page(PAGES["agent_run"])

    st.markdown("---")
    st.markdown("### Inventory Diagnostics & Trends")
    t1, t2 = st.tabs(["Stock vs Safety Buffers", "30-Day Expiry Schedule"])
    with t1:
        show = inv.assign(ratio=inv["on_hand"] / inv["reorder_point"].clip(lower=1)).sort_values("ratio").head(15)
        if not show.empty:
            base = alt.Chart(show).encode(y=alt.Y("name:N", sort=list(show["name"]), title=None))
            bars = base.mark_bar(size=14).encode(
                x=alt.X("on_hand:Q", title="Units on Hand"),
                color=alt.condition("datum.below_reorder", alt.value(T.AMBER), alt.value(T.PRIMARY)),
                tooltip=["name", "sku", "on_hand", "reorder_point", "cover_days"]
            )
            ticks = base.mark_tick(color=T.RED, thickness=3, size=18).encode(x="reorder_point:Q")
            st.altair_chart((bars + ticks).properties(height=340), use_container_width=True)
            st.caption("Amber bar = stock is below safety reorder threshold. Red tick = minimum reorder point.")
    with t2:
        ex30 = expiry_frame(svc, 30)
        if ex30.empty:
            T.empty("No products expire in the next 30 days.")
        else:
            agg = ex30.groupby("days_to_expiry", as_index=False).agg(value=("value", "sum"), batches=("sku", "count"))
            ch = alt.Chart(agg).mark_bar(color=T.AMBER).encode(
                x=alt.X("days_to_expiry:O", title="Days Remaining to Expiry"),
                y=alt.Y("value:Q", title="At-Risk Stock Value ($)"),
                color=alt.condition(alt.datum.days_to_expiry <= 7, alt.value(T.RED), alt.value(T.AMBER)),
                tooltip=["days_to_expiry", "value", "batches"]
            )
            st.altair_chart(ch.properties(height=340), use_container_width=True)
            st.caption("Red bars expire within 7 days. Discount immediately to recover capital.")


# ------------------------------------------------------------------ Product Inventory Catalog
def inventory():
    svc = state.svc()
    T.header(
        "Product Management",
        "Inventory Catalog",
        "Browse all store products, monitor current stock levels, check days of supply, and initiate purchases."
    )
    inv = inventory_frame(svc)

    f1, f2, f3 = st.columns([3, 2, 2])
    search = f1.text_input("Search products", placeholder="Type product name or code...")
    categories = ["All Categories"] + sorted(inv["category"].unique())
    cat_filter = f2.selectbox("Filter by Category", categories)
    status_filter = f3.selectbox("Stock Status", ["All Products", "Low Stock (< Safety Threshold)", "Healthy Stock"])

    df = inv.copy()
    if search:
        df = df[df["name"].str.contains(search, case=False) | df["sku"].str.contains(search, case=False)]
    if cat_filter != "All Categories":
        df = df[df["category"] == cat_filter]
    if status_filter == "Low Stock (< Safety Threshold)":
        df = df[df["below_reorder"]]
    elif status_filter == "Healthy Stock":
        df = df[~df["below_reorder"]]

    st.caption(f"Showing **{len(df)}** products matching filters.")

    for _, row in df.iterrows():
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([4, 2, 2, 2])
            with c1:
                st.markdown(products.product_cell_html(
                    row["sku"], row["name"], row["category"],
                    subtext=f"Product Code: {row['sku']} • Unit Cost: ${row['unit_cost']:.2f}",
                    size=46
                ), unsafe_allow_html=True)
            with c2:
                st.metric("Stock on Hand", f"{int(row['on_hand'])} units", f"Safety: {int(row['reorder_point'])}")
            with c3:
                color = "inverse" if row["stockout_risk"] else "normal"
                st.metric("Days of Supply", f"{row['cover_days']:.1f} days", f"Daily sales: {row['avg_daily']:.1f}",
                          delta_color=color)
            with c4:
                st.write("")
                if st.button("Order Restock", icon=":material/add_shopping_cart:", key=f"inv_ord_{row['sku']}",
                             type="primary" if row["below_reorder"] else "secondary", use_container_width=True):
                    st.session_state["run_request"] = {"sku": row["sku"], "fault": None}
                    st.switch_page(PAGES["agent_run"])


# ------------------------------------------------------------------ Alerts and Cases
def alerts():
    svc = state.svc()
    T.header(
        "Stock Alerts",
        "Shortage & Expiry Warnings",
        "Actionable alerts generated automatically based on live inventory buffers, sales velocity, and batch expiration dates."
    )

    al = svc.alerts(state.user())
    if not al:
        st.success("All inventory levels are healthy! No products currently require reordering.", icon=":material/check_circle:")
        return

    # Two clear business tabs
    t1, t2 = st.tabs(["Low Stock Alerts (Needs Restocking)", "Expiry Alerts (Put on Sale)"])
    with t1:
        stock_alerts = [a for a in al if a.kind in ("stockout", "both")]
        if not stock_alerts:
            st.success("No stockout risks detected. Every product has adequate coverage.", icon=":material/check_circle:")
        else:
            for a in stock_alerts:
                supply = a.on_hand / max(0.1, a.avg_daily)
                with st.container(border=True):
                    a1, a2, a3, a4 = st.columns([4, 2, 2, 2])
                    with a1:
                        st.markdown(products.product_cell_html(
                            a.sku,
                            subtext=f"Product Code: {a.sku} • Priority: {a.severity.title()}",
                            size=46
                        ), unsafe_allow_html=True)
                    with a2:
                        st.metric("On Hand", f"{int(a.on_hand)} units", f"Safety Point: {int(a.reorder_point)}")
                    with a3:
                        st.metric("Remaining Supply", f"{supply:.1f} days", f"Daily sales: {a.avg_daily:.1f}")
                    with a4:
                        st.write("")
                        if st.button("Plan Reorder with AI", icon=":material/auto_mode:", key=f"alt_btn_{a.sku}",
                                     type="primary", use_container_width=True):
                            st.session_state["run_request"] = {"sku": a.sku, "fault": None}
                            st.switch_page(PAGES["agent_run"])

    with t2:
        exp_alerts = [a for a in al if a.kind in ("expiry", "both")]
        if not exp_alerts:
            st.success("No batches expiring soon. Shelf inventory is fresh.", icon=":material/check_circle:")
        else:
            for a in exp_alerts:
                with st.container(border=True):
                    e1, e2, e3 = st.columns([5, 3, 2])
                    with e1:
                        st.markdown(products.product_cell_html(
                            a.sku,
                            subtext=f"Product Code: {a.sku} • Expiry alert condition",
                            size=46
                        ), unsafe_allow_html=True)
                    with e2:
                        st.markdown(
                            '<div class="pa-callout tip" style="margin:0; padding:8px 12px; font-size:0.85rem;">'
                            '<b>Clearance Recommended:</b> Batch approaching expiration. '
                            'Apply price markdown to clear stock before expiry loss.</div>',
                            unsafe_allow_html=True
                        )
                    with e3:
                        st.write("")
                        if st.button("Apply Markdown", icon=":material/percent:", key=f"alt_exp_{a.sku}",
                                     use_container_width=True):
                            st.session_state["run_request"] = {"sku": a.sku, "fault": None}
                            st.switch_page(PAGES["agent_run"])


# ------------------------------------------------------------------ Smart Purchasing Assistant
def agent_run():
    svc = state.svc()
    T.header(
        "Purchasing Assistant",
        "Automated Order Planning",
        "Select a product below. The system predicts customer sales, compares supplier quotes, audits store budgets, "
        "and drafts a complete purchase order ready for manager authorization."
    )

    req = st.session_state.pop("run_request", None)
    if req is None:
        al = svc.alerts(state.user())
        if not al:
            T.empty("No active alerts. Browse the Product Catalog to initiate an order manually.")
            return

        sorted_al = sorted(al, key=lambda a: (0 if a.kind == "stockout" else (1 if a.kind == "both" else 2), -a.on_hand))
        c1, c2 = st.columns([3, 1])

        def _fmt(s):
            for a in sorted_al:
                if a.sku == s:
                    v = products.get_product_visuals(a.sku)
                    tag = "Restock Needed" if a.kind == "stockout" else ("Clearance Risk" if a.kind == "expiry" else "Dual Risk")
                    return f"[{tag}] {v['name']} ({a.sku}) - {int(a.on_hand)} on hand"
            return s

        sku = c1.selectbox("Select Product to Plan", [a.sku for a in sorted_al], format_func=_fmt)
        c2.write("")
        if c2.button("Run AI Planning", icon=":material/play_arrow:", type="primary",
                     disabled=not svc.can(state.user(), "run_case"), use_container_width=True):
            req = {"sku": sku, "fault": None}

    if req:
        sku = req["sku"]
        v = products.get_product_visuals(sku)
        st.markdown(
            f'<div class="pa-product-card">'
            f'{products.product_cell_html(sku, v["name"], v["category"], subtext="Selected for automated purchasing analysis", size=54)}'
            f'</div>',
            unsafe_allow_html=True
        )

        with st.status(f"AI Purchasing Assistant is analyzing '{v['name']}' ...", expanded=True) as status:
            case: CaseFile | None = None
            for kind, item in svc.run_case_stream(state.user(), sku, req.get("fault")):
                if kind == "msg":
                    author = getattr(item, "author", "")
                    label = AGENT_LABEL.get(author, author)
                    st.write(f":material/check_circle: **{label}**: {_summary(item)}")
                elif kind == "case":
                    case = item

            if case is None:
                status.update(label="Analysis could not be completed", state="error")
                st.warning("No case result was produced. Please try another product.")
                return

            status.update(label="Analysis Complete: Order recommendation formulated", state="complete")

        st.session_state["last_case"] = case.task_id
        return render_case_summary(case)

    # Show previous case if available
    task = st.session_state.get("last_case")
    case = svc.cases.get(task) if task else None
    if not case:
        T.empty("No purchasing plan executed yet in this session. Select a product above to begin.")
        return

    st.markdown(f"**Previous Sourcing Plan:** Product `{case.sku}`")
    render_case_summary(case)


def _summary(m) -> str:
    o = m.output
    a = m.author
    if a == "stock_monitor":
        return f"Risk detected ({o.get('kind', 'alert')}). Current stock on hand: {int(o.get('on_hand', 0))} units."
    if a == "forecaster":
        return f"Machine learning projected sales of {o.get('mean_14d', 0):.0f} units over 14 days (LightGBM ML model)."
    if a == "supplier":
        opts = o.get("options", [])
        if opts:
            top = opts[0]
            return (f"Evaluated {len(opts)} supplier quotes. Best vendor: {top.get('name')} "
                    f"(@ ${top.get('unit_price', 0):.2f}/unit, {top.get('lead_time', 0)}d delivery, "
                    f"{top.get('reliability', 0):.0%} reliability).")
        return "No suppliers available."
    if a == "po_agent":
        qty = o.get("qty", 0)
        price = o.get("unit_price", 0)
        action = "Replenishment order recommended" if o.get("action") == "order" else "Clearance markdown recommended"
        return f"{action}: {qty} units from {o.get('supplier_name')} @ ${price:.2f}/unit (Total: ${float(qty) * float(price):,.2f})."
    if a == "validator":
        if o.get("passed"):
            return "Order Safety Check: PASSED. Order complies with store budget caps and supplier minimum order sizes."
        return "Safety Flag: " + "; ".join(f["message"] for f in o.get("failures", []))
    if a == "gate":
        return f"Purchase Order #{o.get('po_id')} formulated in PENDING_APPROVAL state. Waiting for manager sign-off."
    if a == "human_approver":
        return f"Manager decision: {o.get('status')} by authorized store manager."
    return str(o)[:120]


def render_case_summary(case: CaseFile):
    st.markdown("---")
    v = products.get_product_visuals(case.sku)

    if case.status == "pending_approval" and case.draft:
        draft = case.draft
        st.markdown(
            f'<div class="pa-product-card">'
            f'<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">'
            f'{products.product_cell_html(case.sku, v["name"], v["category"], subtext="Purchase Order Drafted", size=52)}'
            f'<div style="font-size:1.6rem; font-weight:800; color:#0F766E;">${draft.total:,.2f}</div>'
            f'</div>'
            f'<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(160px, 1fr)); gap:10px; margin-top:14px;">'
            f'<div class="pa-stat-box"><div class="label">Requested Order</div><div class="val">{draft.qty} units</div></div>'
            f'<div class="pa-stat-box"><div class="label">Selected Vendor</div><div class="val">{draft.supplier_name}</div></div>'
            f'<div class="pa-stat-box"><div class="label">Unit Price</div><div class="val">${draft.unit_price:.2f}</div></div>'
            f'<div class="pa-stat-box"><div class="label">Order Safety Check</div><div class="val" style="color:#16A34A;">PASSED</div></div>'
            f'</div>'
            f'</div>',
            unsafe_allow_html=True
        )

        T.callout(
            f"**Purchase Request #{case.po_id} Created Successfully:** Waiting for manager approval.<br>"
            "**Corporate Governance Policy:** Buyers (Alice) cannot approve orders. Store Manager (Bob) holds executive sign-off authority.",
            kind="success"
        )

        c_a, c_b = st.columns([1, 1])
        with c_a:
            if st.button("Switch to Bob & Open Approval Desk", icon=":material/person_check:", type="primary",
                         use_container_width=True):
                st.session_state["acting_user"] = "bob"
                st.switch_page(PAGES["approvals"])
        with c_b:
            if st.button("Open Approval Desk", icon=":material/fact_check:", use_container_width=True):
                st.switch_page(PAGES["approvals"])

    elif case.status == "no_action" and case.draft and case.draft.action == "markdown":
        st.markdown(
            f'<div class="pa-product-card">'
            f'{products.product_cell_html(case.sku, v["name"], v["category"], subtext="Inventory Clearance Action", size=52)}'
            f'</div>',
            unsafe_allow_html=True
        )
        T.callout(
            "**Inventory Clearance Action Recommended:** The system determined that ordering more units is unnecessary "
            "due to expiring shelf stock. Instead, an immediate **20% price markdown** is recommended to liquidate current "
            "shelf inventory before expiration.",
            kind="tip"
        )


def workflow_dot(visited: set, failed: set, active: str = "") -> str:
    """Graphviz state visualization for technical view."""
    nodes = [
        ("stock_monitor", "Stock Checker\n(Shortage Alert)"),
        ("forecaster", "Expected Sales\n(LightGBM ML)"),
        ("supplier", "Supplier Comparison\n(Multi-Factor Score)"),
        ("po_agent", "Purchase Order\n(Plan Formulation)"),
        ("validator", "Safety Check\n(Budget & Policy Gate)"),
        ("po_reviser", "Bounded Revision\n(Max 2 Tries)"),
        ("escalate", "Human Escalation\n(Exception Handled)"),
        ("gate_submit", "Safe-Action Gate\n(Approval Queue)"),
        ("human_approval", "Store Manager\n(Executive Sign-Off)"),
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


def render_step(m, container):
    tone = AGENT_TONE.get(m.author, "muted")
    if m.author == "validator" and not m.output.get("passed", True):
        tone = "bad"
    if m.author == "forecaster" and "error" in m.output:
        tone = "bad"
    color = T.TONES[tone][0]
    with container:
        st.markdown(
            f'<div class="pa-step" style="--tone:{color}"><div class="pa-dot"></div><div style="flex:1">'
            f'<div class="a">{T.esc(AGENT_LABEL.get(m.author, m.author))}</div>'
            f'<div>{T.esc(_summary(m))}</div>'
            f'</div></div>',
            unsafe_allow_html=True
        )


PAGES: dict = {}  # populated by app.py
